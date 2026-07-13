"""Zone Auto-Calibrator for WOTD.

Analyses the last N (default 10) runs from Garmin's HR-in-timezones endpoint
and derives empirical Z2_FLOOR_PCT and Z2_CEILING_PCT constants relative to
the athlete's current LTHR.

Calibration is persisted to ``zone_calibration.json`` in the user's data
directory and loaded on every WOTD generation.  The zone *percentages* are the
stable constants; the absolute bpm targets auto-scale daily because LTHR is
fetched live from Garmin.

Methodology
-----------
Garmin's own HR-zone model uses fixed clinical thresholds that happen to match
your empirical data well:
  - zone3.lowBoundary  → the HR where aerobic running starts  (floor)
  - zone4.lowBoundary  → the HR where hard effort starts      (walk-break trigger)
  - ceiling            → zone4.lowBoundary - 1                (Z2 ceiling)

We average these across all recent runs (weighted towards newer), divide by
the LTHR at calibration time, and store as percentages so they survive future
LTHR changes without requiring another recalibration run.

Guard rails (sanity clamps)
---------------------------
The new percentages are clamped to ±0.05 of the previous values to prevent
a single anomalous run from blowing up the zones.  Calibration is also skipped
if fewer than MIN_RUNS_FOR_CALIBRATION runs have meaningful zone data.
"""
from __future__ import annotations

import json
import logging
import math
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

CALIBRATION_FILENAME   = "zone_calibration.json"
RUNS_PER_CALIBRATION   = 10          # recalibrate every N completed runs
MIN_RUNS_FOR_CALIBRATION = 5         # need at least this many with valid zone data
DECAY_FACTOR           = 0.90        # weight for recency (newest run = weight 1.0)

# Hard bounds: never let percentages drift outside these, regardless of data
FLOOR_MIN_PCT  = 0.68   # absolute minimum floor (Friel Z2 lower bound)
FLOOR_MAX_PCT  = 0.82   # absolute maximum floor
CEILING_MIN_PCT = 0.80  # absolute minimum ceiling
CEILING_MAX_PCT = 0.94  # absolute maximum ceiling (must stay below LTHR)

# Default starting constants (empirically set 2026-07-13 from 3-run analysis)
DEFAULT_FLOOR_PCT       = 0.746
DEFAULT_CEILING_PCT     = 0.870
DEFAULT_WALK_BREAK_PCT  = 0.876   # = ceiling + ~1 bpm delta at LTHR=177

# Garmin zone indices in the HR-timezones response (0-indexed)
GARMIN_ZONE3_IDX = 2   # "Aerobic" in Garmin's 5-zone model
GARMIN_ZONE4_IDX = 3   # "Threshold" in Garmin's model


# ── Calibration file I/O ──────────────────────────────────────────────────────

def _cal_path(user_data_dir: Path) -> Path:
    return user_data_dir / CALIBRATION_FILENAME


def load_calibration(user_data_dir: Path) -> dict:
    """Load calibration from disk; return defaults if file missing or corrupt."""
    path = _cal_path(user_data_dir)
    try:
        with open(path) as f:
            data = json.load(f)
        # Validate essential keys exist
        _ = data["z2_floor_pct"], data["z2_ceiling_pct"], data["walk_break_pct"]
        logger.info(
            "ZoneCal: loaded from %s | Z2=%.1f%%\u2013%.1f%% | runs_since=%d",
            path, data["z2_floor_pct"] * 100, data["z2_ceiling_pct"] * 100,
            data.get("runs_since_calibration", 0),
        )
        return data
    except FileNotFoundError:
        logger.info("ZoneCal: no calibration file found — using factory defaults.")
    except (KeyError, json.JSONDecodeError, TypeError) as exc:
        logger.warning("ZoneCal: calibration file corrupt (%s) — using factory defaults.", exc)

    return _default_calibration()


def _default_calibration() -> dict:
    return {
        "z2_floor_pct": DEFAULT_FLOOR_PCT,
        "z2_ceiling_pct": DEFAULT_CEILING_PCT,
        "walk_break_pct": DEFAULT_WALK_BREAK_PCT,
        "runs_since_calibration": 0,
        "last_calibrated_date": None,
        "lthr_at_last_calibration": None,
        "calibration_notes": "Factory defaults (empirically set 2026-07-13 from 3-run Garmin analysis)",
    }


def _save_calibration(user_data_dir: Path, cal: dict) -> None:
    path = _cal_path(user_data_dir)
    user_data_dir.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(cal, f, indent=2)
    logger.info("ZoneCal: saved calibration to %s", path)


# ── Run counter ───────────────────────────────────────────────────────────────

def increment_run_counter(user_data_dir: Path) -> int:
    """Bump the run counter and return the new count.

    Called by the daemon each time it detects a new completed run.
    Returns the new ``runs_since_calibration`` value.
    """
    cal = load_calibration(user_data_dir)
    cal["runs_since_calibration"] = cal.get("runs_since_calibration", 0) + 1
    _save_calibration(user_data_dir, cal)
    return cal["runs_since_calibration"]


def is_calibration_due(user_data_dir: Path) -> bool:
    """Return True if we have accumulated RUNS_PER_CALIBRATION runs since last calibration."""
    cal = load_calibration(user_data_dir)
    return cal.get("runs_since_calibration", 0) >= RUNS_PER_CALIBRATION


# ── Zone data extraction from Garmin API ──────────────────────────────────────

def _extract_zone_boundaries(hr_timezones: list[dict]) -> tuple[int | None, int | None]:
    """Extract (zone3_low, zone4_low) boundaries from Garmin's HR-timezones response.

    The response looks like:
      [{"zoneNumber": 1, "secsInZone": 4.0, "zoneLowBoundary": 90},
       {"zoneNumber": 2, ...,"zoneLowBoundary": 110},
       {"zoneNumber": 3, ...,"zoneLowBoundary": 132},   ← aerobic running starts here
       {"zoneNumber": 4, ...,"zoneLowBoundary": 155},   ← walk-break trigger here
       {"zoneNumber": 5, ...,"zoneLowBoundary": 178}]

    Returns (zone3_low, zone4_low) or (None, None) if data is missing/short.
    """
    if not hr_timezones or len(hr_timezones) < 4:
        return None, None
    try:
        # Sort by zoneNumber to be safe against API ordering changes
        zones = sorted(hr_timezones, key=lambda z: z.get("zoneNumber", 0))
        z3_low = int(zones[GARMIN_ZONE3_IDX]["zoneLowBoundary"])
        z4_low = int(zones[GARMIN_ZONE4_IDX]["zoneLowBoundary"])
        # Sanity check: zone3 < zone4 and both in physiologically sane range
        if 90 <= z3_low < z4_low <= 210:
            return z3_low, z4_low
    except (IndexError, KeyError, TypeError, ValueError):
        pass
    return None, None


def _fetch_recent_run_zones(
    client: Any,
    n: int = RUNS_PER_CALIBRATION,
) -> list[dict]:
    """Fetch HR-in-timezones data for the last ``n`` running activities.

    Returns a list of dicts, each with keys:
      - activity_id
      - activity_date  (YYYY-MM-DD str)
      - zone3_low      (bpm)
      - zone4_low      (bpm)
      - secs_in_zone3  (seconds spent in Z3 during this run)
    """
    RUNNING_TYPES = {
        "running", "trail_running", "treadmill_running",
        "indoor_running", "street_running",
    }
    try:
        acts = client.get_activities(0, max(n * 3, 30))   # fetch extra; filter to runs
    except Exception as exc:
        logger.warning("ZoneCal: could not fetch activities: %s", exc)
        return []

    runs = [
        a for a in acts
        if a.get("activityType", {}).get("typeKey", "") in RUNNING_TYPES
           or "run" in (a.get("activityName") or "").lower()
    ][:n]

    results = []
    for r in runs:
        aid = r["activityId"]
        dt  = (r.get("startTimeLocal") or "")[:10]
        try:
            zones_raw = client.get_activity_hr_in_timezones(aid)
            z3_low, z4_low = _extract_zone_boundaries(zones_raw)
            if z3_low is None:
                logger.debug("ZoneCal: run %s (%s) has no valid zone data — skipping.", aid, dt)
                continue
            secs_z3 = next(
                (z.get("secsInZone", 0) for z in zones_raw
                 if z.get("zoneNumber") == GARMIN_ZONE3_IDX + 1),  # API is 1-indexed
                0,
            )
            results.append({
                "activity_id": aid,
                "activity_date": dt,
                "zone3_low": z3_low,
                "zone4_low": z4_low,
                "secs_in_zone3": float(secs_z3),
            })
            logger.debug("ZoneCal: run %s (%s) | z3_low=%d z4_low=%d", aid, dt, z3_low, z4_low)
        except Exception as exc:
            logger.debug("ZoneCal: zone fetch failed for run %s: %s", aid, exc)

    logger.info("ZoneCal: collected zone data from %d / %d recent runs.", len(results), len(runs))
    return results


# ── Core calibration algorithm ────────────────────────────────────────────────

def _compute_new_percentages(
    run_zones: list[dict],
    current_lthr: int,
    current_floor_pct: float,
    current_ceiling_pct: float,
) -> tuple[float, float] | None:
    """Compute new (floor_pct, ceiling_pct) from run zone data.

    Algorithm:
    1. For each run, derive floor_pct = zone3_low / lthr
                              ceiling_pct = (zone4_low - 1) / lthr
    2. Apply exponential decay weights so newer runs matter more.
    3. Weighted average → candidate percentages.
    4. Clamp to ±0.04 of current values (prevents one weird run causing a big shift).
    5. Apply absolute physiological bounds.

    Returns None if there aren't enough quality data points.
    """
    if len(run_zones) < MIN_RUNS_FOR_CALIBRATION:
        logger.info(
            "ZoneCal: only %d runs with valid data (need %d) — skipping calibration.",
            len(run_zones), MIN_RUNS_FOR_CALIBRATION,
        )
        return None

    # Sort newest-first (list comes newest-first from Garmin already, but be safe)
    runs = sorted(run_zones, key=lambda r: r["activity_date"], reverse=True)

    weighted_floor_sum   = 0.0
    weighted_ceiling_sum = 0.0
    weight_total         = 0.0

    for i, r in enumerate(runs):
        weight = DECAY_FACTOR ** i                  # newest run = 1.0, oldest ≈ 0.9^9 ≈ 0.39
        floor_pct_this   = r["zone3_low"] / current_lthr
        ceiling_pct_this = (r["zone4_low"] - 1) / current_lthr

        weighted_floor_sum   += weight * floor_pct_this
        weighted_ceiling_sum += weight * ceiling_pct_this
        weight_total         += weight

    raw_floor   = weighted_floor_sum   / weight_total
    raw_ceiling = weighted_ceiling_sum / weight_total

    logger.info(
        "ZoneCal: weighted averages → floor_pct=%.3f (%.1f%%) ceiling_pct=%.3f (%.1f%%)",
        raw_floor, raw_floor * 100, raw_ceiling, raw_ceiling * 100,
    )

    # Clamp: don't move more than ±4% from current calibration in one go
    MAX_SHIFT = 0.04
    clamped_floor   = max(current_floor_pct - MAX_SHIFT,
                          min(current_floor_pct + MAX_SHIFT, raw_floor))
    clamped_ceiling = max(current_ceiling_pct - MAX_SHIFT,
                          min(current_ceiling_pct + MAX_SHIFT, raw_ceiling))

    # Apply absolute physiological bounds
    new_floor   = max(FLOOR_MIN_PCT,   min(FLOOR_MAX_PCT,   clamped_floor))
    new_ceiling = max(CEILING_MIN_PCT, min(CEILING_MAX_PCT, clamped_ceiling))

    # Sanity: floor must be below ceiling by at least 8%
    if new_ceiling - new_floor < 0.08:
        logger.warning(
            "ZoneCal: floor/ceiling too close (%.3f / %.3f) — skipping calibration.",
            new_floor, new_ceiling,
        )
        return None

    return new_floor, new_ceiling


# ── Public orchestrator ───────────────────────────────────────────────────────

def maybe_recalibrate(
    client: Any,
    current_lthr: int,
    user_data_dir: Path,
) -> dict:
    """Check if calibration is due; if so, run it and return updated calibration.

    Always returns the current (possibly freshly updated) calibration dict so
    the caller can use it immediately.

    Call this from ``generate_workout_of_the_day()`` just before zone constants
    are needed.
    """
    cal = load_calibration(user_data_dir)

    if not is_calibration_due(user_data_dir):
        runs_done = cal.get("runs_since_calibration", 0)
        runs_left = RUNS_PER_CALIBRATION - runs_done
        logger.info(
            "ZoneCal: %d/%d runs since last calibration (%d more needed).",
            runs_done, RUNS_PER_CALIBRATION, runs_left,
        )
        return cal

    logger.info(
        "ZoneCal: %d runs accumulated — starting auto-recalibration against LTHR=%d.",
        cal.get("runs_since_calibration", 0), current_lthr,
    )

    run_zones = _fetch_recent_run_zones(client, n=RUNS_PER_CALIBRATION)
    result = _compute_new_percentages(
        run_zones,
        current_lthr,
        current_floor_pct=cal["z2_floor_pct"],
        current_ceiling_pct=cal["z2_ceiling_pct"],
    )

    if result is None:
        # Not enough quality data — reset counter and try again next 10 runs
        logger.warning("ZoneCal: calibration incomplete — resetting counter.")
        cal["runs_since_calibration"] = 0
        _save_calibration(user_data_dir, cal)
        return cal

    new_floor, new_ceiling = result
    new_walk_break = new_ceiling + (1 / current_lthr)   # 1 bpm above ceiling as a fraction

    old_floor_bpm   = int(cal["z2_floor_pct"]   * current_lthr)
    old_ceiling_bpm = int(cal["z2_ceiling_pct"] * current_lthr)
    new_floor_bpm   = int(new_floor   * current_lthr)
    new_ceiling_bpm = int(new_ceiling * current_lthr)

    logger.info(
        "ZoneCal: recalibrated! Z2 floor %d\u2192%d bpm (%.1f%%\u2192%.1f%%), "
        "ceiling %d\u2192%d bpm (%.1f%%\u2192%.1f%%)",
        old_floor_bpm, new_floor_bpm, cal["z2_floor_pct"] * 100, new_floor * 100,
        old_ceiling_bpm, new_ceiling_bpm, cal["z2_ceiling_pct"] * 100, new_ceiling * 100,
    )

    cal.update({
        "z2_floor_pct":             round(new_floor, 4),
        "z2_ceiling_pct":           round(new_ceiling, 4),
        "walk_break_pct":           round(new_walk_break, 4),
        "runs_since_calibration":   0,
        "last_calibrated_date":     date.today().isoformat(),
        "lthr_at_last_calibration": current_lthr,
        "calibration_notes": (
            f"Auto-calibrated {date.today().isoformat()} from {len(run_zones)} runs. "
            f"Z2={new_floor_bpm}\u2013{new_ceiling_bpm} bpm @ LTHR={current_lthr}."
        ),
        "run_zone_snapshots": [
            {"date": r["activity_date"], "z3_low": r["zone3_low"], "z4_low": r["zone4_low"]}
            for r in run_zones[:10]
        ],
    })
    _save_calibration(user_data_dir, cal)
    return cal
