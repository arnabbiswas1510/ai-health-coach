"""Single source of truth for the athlete's heart-rate zones.

Both WOTD generation (``wotd_generator.generate_workout_of_the_day``) and
post-run coaching feedback (``run_coach_feedback.generate_run_feedback``) must
describe the SAME zones, or the athlete is told to run at one HR and then graded
against a different one.

Before this module existed, ``run_coach_feedback._get_zone2()`` duplicated the
logic badly:

  * it read LTHR only from ``get_training_status()`` (no date argument) and
    never tried ``get_user_profile()`` — which is where the value actually
    lives — so it almost always failed to find an LTHR;
  * it then fell back to the age formula ``220 - age``, which is explicitly
    forbidden, producing Z2 = 100-120 bpm at age 53;
  * even on the rare success path it used hard-coded 0.80/0.89 percentages
    instead of the empirically calibrated constants, giving 141-157 bpm.

Meanwhile WOTD prescribes 132-154 bpm at LTHR=177. So a textbook walk-run
executed exactly as prescribed was being graded as "way above Zone 2".

Rules enforced here (see AGENTS.md):
  * LTHR is ALWAYS fetched live from Garmin.
  * There is NEVER an age-based or max-HR-based fallback. If LTHR cannot be
    resolved, a ``ValueError`` is raised and the caller must abort.
  * Zone percentages come from ``zone_calibrator`` so auto-recalibration is
    picked up by every consumer at once.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from services.garmin.zone_calibrator import (
    _default_calibration,
    load_calibration,
    maybe_recalibrate,
)

logger = logging.getLogger(__name__)

# Non-calibrated anchors. These describe the shape of the zone model above Z2
# and are deliberately NOT athlete-calibrated.
LTHR_TO_MAX_HR_RATIO = 0.88
Z1_FLOOR_PCT = 0.55
Z3_CEILING_PCT = 0.94
Z4_CEILING_PCT = 1.05

# How far back to scan training_status for an LTHR before giving up.
LTHR_SCAN_DAYS = 15


@dataclass(frozen=True)
class HRZones:
    """Resolved HR zones for the athlete, anchored on a live LTHR."""

    lthr: int
    max_hr: int
    z1_high: int
    z2_low: int
    z2_high: int
    walk_break_hr: int
    z3_high: int
    z4_high: int
    z2_floor_pct: float
    z2_ceiling_pct: float
    walk_break_pct: float

    def describe(self) -> str:
        return (
            f"Z2={self.z2_low}-{self.z2_high} bpm "
            f"({self.z2_floor_pct * 100:.1f}-{self.z2_ceiling_pct * 100:.1f}% LTHR), "
            f"walk break >={self.walk_break_hr} bpm, LTHR={self.lthr} bpm"
        )

    def zone_table(self) -> dict[str, tuple[int, int]]:
        """Return Z1-Z5 as absolute bpm ranges.

        Every boundary is anchored on LTHR, so a consumer that renders zone
        targets (e.g. PlanParser) cannot drift away from the Z2 the athlete is
        actually prescribed by WOTD.
        """
        return {
            "Z1": (int(self.lthr * Z1_FLOOR_PCT), self.z2_low),
            "Z2": (self.z2_low, self.z2_high),
            "Z3": (self.z2_high, self.z3_high),
            "Z4": (self.z3_high, self.z4_high),
            "Z5": (self.z4_high, self.max_hr),
        }


def _parse_lthr_value(val: Any) -> int | None:
    """Extract a positive integer LTHR, rejecting None, mocks, and invalid values."""
    if val is None or type(val).__name__ in ("MagicMock", "Mock"):
        return None
    if isinstance(val, (int, float)):
        i = int(val)
        return i if i > 0 else None
    if isinstance(val, str) and val.strip().isdigit():
        i = int(val.strip())
        return i if i > 0 else None
    return None


def resolve_lthr(client: Any, *, log_prefix: str = "HRZones") -> int:
    """Return the athlete's current LTHR from Garmin.

    Priority:
      1. ``get_user_profile() -> userData.lactateThresholdHeartRate`` (primary)
      2. ``client.get_lactate_threshold(latest=True)`` (biometric endpoint)
      3. a scan of the last ``LTHR_SCAN_DAYS`` days of ``get_training_status()``
      4. ``client.get_heart_rate_zones()`` (configured biometric zones)

    Raises:
        ValueError: if LTHR cannot be resolved from any source. There is no
            age-based fallback by design.
    """
    lthr: int | None = None

    try:
        profile = client.get_user_profile()
        if isinstance(profile, dict):
            user_data = profile.get("userData")
            if isinstance(user_data, dict):
                parsed = _parse_lthr_value(user_data.get("lactateThresholdHeartRate"))
                if parsed:
                    lthr = parsed
                    logger.info("%s: LTHR from get_user_profile: %d bpm", log_prefix, lthr)
    except Exception as exc:
        logger.warning("%s: get_user_profile failed: %s", log_prefix, exc)

    if not lthr and hasattr(client, "get_lactate_threshold"):
        try:
            lt_data = client.get_lactate_threshold(latest=True)
            if isinstance(lt_data, dict):
                sh_data = lt_data.get("speed_and_heart_rate")
                if isinstance(sh_data, dict):
                    parsed = _parse_lthr_value(sh_data.get("heartRate"))
                    if parsed:
                        lthr = parsed
                        logger.info("%s: LTHR from get_lactate_threshold: %d bpm", log_prefix, lthr)
        except Exception as exc:
            logger.debug("%s: get_lactate_threshold failed: %s", log_prefix, exc)

    if not lthr:
        logger.info(
            "%s: LTHR not in user profile — scanning recent training_status dates...",
            log_prefix,
        )
        for days_ago in range(0, LTHR_SCAN_DAYS):
            day = (date.today() - timedelta(days=days_ago)).isoformat()
            try:
                status = client.get_training_status(day)
                if isinstance(status, dict):
                    raw = status.get("lactateThresholdHeartRate") or status.get(
                        "latestLactateThresholdHeartRate"
                    )
                    parsed = _parse_lthr_value(raw)
                    if parsed:
                        lthr = parsed
                        logger.info(
                            "%s: LTHR from training_status(%s): %d bpm", log_prefix, day, lthr
                        )
                        break
            except Exception:
                continue

    if not lthr and hasattr(client, "get_heart_rate_zones"):
        try:
            hr_zones_list = client.get_heart_rate_zones()
            if isinstance(hr_zones_list, list):
                running_profile = None
                default_profile = None
                for p in hr_zones_list:
                    if isinstance(p, dict):
                        sport = str(p.get("sport") or "").upper()
                        if sport == "RUNNING":
                            running_profile = p
                        elif sport == "DEFAULT" or not default_profile:
                            default_profile = p
                chosen = running_profile or default_profile
                if chosen:
                    parsed = _parse_lthr_value(chosen.get("lactateThresholdHeartRate"))
                    if parsed:
                        lthr = parsed
                        logger.info(
                            "%s: LTHR from get_heart_rate_zones (%s): %d bpm",
                            log_prefix, chosen.get("sport"), lthr,
                        )
        except Exception as exc:
            logger.debug("%s: get_heart_rate_zones failed: %s", log_prefix, exc)

    if not lthr:
        raise ValueError(
            f"{log_prefix}: LTHR is unavailable from all sources (get_user_profile + "
            f"get_lactate_threshold + training_status + get_heart_rate_zones). "
            "Cannot compute Zone 2 without LTHR. Ensure at least one recent run with a known "
            "lactate threshold is synced to Garmin Connect."
        )

    return lthr


def compute_zones(
    lthr: int,
    zone_cal: dict,
    athlete_cfg: dict | None = None,
    *,
    log_prefix: str = "HRZones",
) -> HRZones:
    """Build the full zone set from a live LTHR and calibrated percentages.

    A manual ``zone2_min`` / ``zone2_max`` in coach_config always wins.
    """
    athlete_cfg = athlete_cfg or {}

    floor_pct = zone_cal["z2_floor_pct"]
    ceiling_pct = zone_cal["z2_ceiling_pct"]
    walk_break_pct = zone_cal["walk_break_pct"]

    max_hr = int(lthr / LTHR_TO_MAX_HR_RATIO)
    z1_high = int(lthr * floor_pct)
    z2_low = int(lthr * floor_pct)
    z2_high = int(lthr * ceiling_pct)
    walk_break_hr = int(lthr * walk_break_pct)
    z3_high = int(lthr * Z3_CEILING_PCT)
    z4_high = int(lthr * Z4_CEILING_PCT)

    logger.info(
        "%s: zones from LTHR=%d | Z2=%d\u2013%d (%.1f\u2013%.1f%%) | walk_break\u2265%d | max_hr=%d",
        log_prefix, lthr, z2_low, z2_high, floor_pct * 100, ceiling_pct * 100,
        walk_break_hr, max_hr,
    )

    if athlete_cfg.get("zone2_min"):
        z2_low = int(athlete_cfg["zone2_min"])
        logger.info("%s: z2_low overridden by config: %d", log_prefix, z2_low)
    if athlete_cfg.get("zone2_max"):
        z2_high = int(athlete_cfg["zone2_max"])
        logger.info("%s: z2_high overridden by config: %d", log_prefix, z2_high)

    return HRZones(
        lthr=lthr,
        max_hr=max_hr,
        z1_high=z1_high,
        z2_low=z2_low,
        z2_high=z2_high,
        walk_break_hr=walk_break_hr,
        z3_high=z3_high,
        z4_high=z4_high,
        z2_floor_pct=floor_pct,
        z2_ceiling_pct=ceiling_pct,
        walk_break_pct=walk_break_pct,
    )


def calibration_for(user_data_dir: Path | None) -> dict:
    """Return the persisted zone calibration, or factory defaults.

    Consumers that have no data directory (e.g. the CLI analysis path) still get
    the same empirically calibrated percentages rather than inventing their own.
    """
    if user_data_dir is None:
        return _default_calibration()
    return load_calibration(user_data_dir)


def get_hr_zones(
    client: Any,
    athlete_cfg: dict | None,
    user_data_dir: Path,
    *,
    recalibrate: bool = False,
    log_prefix: str = "HRZones",
) -> HRZones:
    """Resolve LTHR and return the athlete's zones.

    Args:
        recalibrate: when True, allow ``zone_calibrator.maybe_recalibrate`` to
            fire (it resets the run counter as a side effect). Only the WOTD
            path should pass True — read-only consumers such as post-run
            feedback must not consume the calibration cycle.
    """
    lthr = resolve_lthr(client, log_prefix=log_prefix)

    if recalibrate:
        zone_cal = maybe_recalibrate(client, lthr, user_data_dir)
    else:
        zone_cal = load_calibration(user_data_dir)

    return compute_zones(lthr, zone_cal, athlete_cfg, log_prefix=log_prefix)
