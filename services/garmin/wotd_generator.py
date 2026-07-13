"""Workout of the Day (WOTD) Generator.

Triggered every morning after Garmin Connect receives overnight sleep data.
Generates exactly ONE workout via AI and pushes it to the Garmin calendar,
replacing any previously pushed WOTD.

Entry point: generate_workout_of_the_day()
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date
from pathlib import Path
from typing import Any

from services.garmin.zone_calibrator import maybe_recalibrate, increment_run_counter

logger = logging.getLogger(__name__)

# Sentinel ID written to disk when no previous WOTD exists
_NO_PREVIOUS_ID = ""

# Prefix used for all WOTD workout names so we can identify them later
WOTD_NAME_PREFIX = "WOTD:"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def generate_workout_of_the_day(
    client: Any,          # garminconnect.Garmin (raw, not GarminConnectClient)
    config: dict,         # parsed coach_config.yaml
    user_data_dir: Path,
    sleep_data: dict,
) -> None:
    """Main entry point called from daemon.py on the sleep trigger.

    Args:
        client:        Authenticated garminconnect.Garmin instance.
        config:        Full coach_config.yaml as dict.
        user_data_dir: Per-user data directory (Path).
        sleep_data:    Raw Garmin sleep API response (dict).
    """
    wotd_cfg = config.get("workout_of_the_day", {})
    if not wotd_cfg.get("enabled", True):
        logger.info("WOTD: feature disabled in coach_config.yaml — skipping.")
        return

    dry_run = not wotd_cfg.get("push_to_garmin", True)
    if dry_run:
        logger.info("WOTD: push_to_garmin=false — dry-run mode (no Garmin writes).")

    # ── Step 1: weighted run baseline (pace, HR, distance) ───────────────────
    n_runs   = int(wotd_cfg.get("recent_runs_count", 10))
    decay    = float(wotd_cfg.get("decay_factor", 0.85))
    baseline = _weighted_run_baseline(client, n=n_runs, decay=decay)
    logger.info("WOTD: baseline from last %d runs (decay=%.2f): %s", n_runs, decay, baseline)

    # ── Step 1b: HRM-600 running dynamics (last 3 runs only — older runs pre-date HRM-600) ──
    dynamics = _fetch_run_dynamics(client, n=3)
    if dynamics["run_count"] > 0:
        logger.info("WOTD: running dynamics from last %d run(s): %s", dynamics["run_count"], dynamics)
    else:
        logger.info("WOTD: no HRM-600 dynamics data available yet.")

    # ── Step 1c: HRV + Training Readiness ─────────────────────────────────────
    hrv_data   = _fetch_hrv(client)
    readiness  = _fetch_training_readiness(client)
    if hrv_data:
        logger.info("WOTD: HRV: %s ms (%s), weekly avg %s ms",
                    hrv_data.get("last_night_avg"), hrv_data.get("status"), hrv_data.get("weekly_avg"))
    if readiness:
        logger.info("WOTD: Training Readiness: %s/100 (%s), limiting: %s",
                    readiness.get("score"), readiness.get("level"), readiness.get("limiting_factor"))

    # ── Step 2: sleep quality ─────────────────────────────────────────────────
    sleep_summary = _extract_sleep_summary(sleep_data)
    logger.info("WOTD: sleep summary: %s", sleep_summary)

    # ── Step 3: athlete profile & constraints ─────────────────────────────────
    athlete_cfg = config.get("athlete", {})
    context_cfg = config.get("context", {})
    age         = int(athlete_cfg.get("age", 53))

    # Zone 2 HR — priority: (1) get_user_profile (primary, same as data_extractor.py),
    #                        (2) recent training_status scan (secondary),
    #                        (3) manual coach_config override (always wins if set)
    # NEVER falls back to age-based formula — LTHR absence is a hard error.
    lthr = None

    # Primary: get_user_profile → userData.lactateThresholdHeartRate
    try:
        profile = client.get_user_profile() or {}
        user_data = profile.get("userData") or {}
        raw_lthr = user_data.get("lactateThresholdHeartRate")
        if raw_lthr:
            lthr = int(raw_lthr)
            logger.info("WOTD: LTHR from get_user_profile: %d bpm", lthr)
    except Exception as exc:
        logger.warning("WOTD: get_user_profile failed: %s", exc)

    # Secondary: scan last 14 days of training_status
    if not lthr:
        logger.info("WOTD: LTHR not in user profile — scanning recent training_status dates...")
        from datetime import timedelta
        for days_ago in range(0, 15):
            d = (date.today() - timedelta(days=days_ago)).isoformat()
            try:
                ts = client.get_training_status(d) or {}
                raw_lthr = ts.get("lactateThresholdHeartRate") or ts.get("latestLactateThresholdHeartRate")
                if raw_lthr:
                    lthr = int(raw_lthr)
                    logger.info("WOTD: LTHR from training_status(%s): %d bpm", d, lthr)
                    break
            except Exception:
                continue

    if not lthr:
        raise ValueError(
            "WOTD: LTHR is unavailable from all sources (get_user_profile + last 14 days of "
            "training_status). Cannot compute Zone 2 without LTHR — WOTD aborted. "
            "Ensure at least one recent run with a known lactate threshold is synced to Garmin Connect."
        )

    # ── Auto-recalibrate zone % constants every 10 runs ──────────────────────
    # maybe_recalibrate() checks run counter in zone_calibration.json.
    # Returns current calibration dict (updated in-place if recalibration ran).
    # LTHR is the live anchor; percentages are the stable athlete constants.
    zone_cal = maybe_recalibrate(client, lthr, user_data_dir)

    # ── All 5 HR zones from LTHR ─────────────────────────────────────────────────
    # CALIBRATION BASIS (2026-07-13, LTHR=177):
    # Empirically derived from Garmin HR-in-timezones data across 3 recent runs:
    #   - Today (walk-run):  96.8 min in 132–154 bpm; 0 min above 155 → ceiling=154=87%
    #   - Jul 11 (cont run): 15 min above 155 bpm → ceiling was too high, confirmed 87% is right
    #   - Jul 10 (cont run): 8.8 min above 155 bpm → same
    # Walk recovery naturally lands in 110–131 bpm (Garmin Z2 in their own scale).
    # Run segments start at ~132 bpm → floor = 132 = 74.6% of LTHR.
    #
    # AUTO-RECALIBRATION:
    # These PERCENTAGES are stable athlete constants — they represent the athlete's
    # body relationship to LTHR and change slowly with long-term fitness adaptation.
    # The ABSOLUTE bpm values auto-scale every day because LTHR is fetched live from
    # get_user_profile() — as Garmin updates LTHR from training data, all zone
    # boundaries shift automatically without any code change.
    # Example: if LTHR rises from 177 → 185 (fitness gain), Z2 becomes 138–161 bpm.
    # Recalibrate percentages only when athlete feedback signals a sustained shift
    # (e.g. 'feels too easy' or 'always hitting ceiling') — not on a single run.
    #
    # Z1 Recovery      : < 74.6% LTHR    (walk recovery; HR naturally drifts here)
    # Z2 Aerobic (RUN) : 74.6 – 87% LTHR  (empirically: run segments land here)
    # Z3 Tempo         : 87 – 94% LTHR   (aerobic threshold; walk break triggered at Z3 floor)
    # Z4 Threshold     : 94 – 105% LTHR  (lactate threshold; avoid)
    # Z5 Max           : > 105% LTHR     (VO2max; irrelevant for weight-loss phase)
    #
    # With LTHR=177: walk-break trigger=155, Z2=132–154, walk-recovery<132
    # Load persisted percentages — updated by auto-calibration every 10 runs.
    # Falls back to empirical factory defaults (2026-07-13) if no file exists yet.
    Z2_FLOOR_PCT   = zone_cal["z2_floor_pct"]
    Z2_CEILING_PCT = zone_cal["z2_ceiling_pct"]
    WALK_BREAK_PCT = zone_cal["walk_break_pct"]

    max_hr        = int(lthr / 0.88)
    z1_high       = int(lthr * Z2_FLOOR_PCT)
    z2_low        = int(lthr * Z2_FLOOR_PCT)
    z2_high       = int(lthr * Z2_CEILING_PCT)
    walk_break_hr = int(lthr * WALK_BREAK_PCT)
    z3_high       = int(lthr * 0.94)
    z4_high       = int(lthr * 1.05)
    # Z5 = above z4_high
    logger.info(
        "WOTD: zones from LTHR=%d | Z2=%d\u2013%d (%.1f\u2013%.1f%%) | walk_break\u2265%d | max_hr=%d",
        lthr, z2_low, z2_high, Z2_FLOOR_PCT * 100, Z2_CEILING_PCT * 100,
        walk_break_hr, max_hr,
    )

    # Manual coach_config override always takes highest priority
    if athlete_cfg.get("zone2_min"):
        z2_low = int(athlete_cfg["zone2_min"])
        logger.info("WOTD: z2_low overridden by config: %d", z2_low)
    if athlete_cfg.get("zone2_max"):
        z2_high = int(athlete_cfg["zone2_max"])
        logger.info("WOTD: z2_high overridden by config: %d", z2_high)

    # Current weight from body metrics if available
    weight_kg = None
    try:
        body_data = client.get_body_composition("2020-01-01", date.today().isoformat())
        entries = (body_data or {}).get("totalAverage", {})
        weight_kg = entries.get("weight")  # kg
    except Exception:
        pass

    is_weekday      = date.today().weekday() < 5   # Mon=0 … Fri=4 are weekdays
    target_lbs      = int(wotd_cfg.get("target_weight_lbs", 160))
    max_duration    = int(
        wotd_cfg.get("weekday_max_duration_min", 60) if is_weekday
        else wotd_cfg.get("weekend_max_duration_min", 105)
    )
    planning_context = context_cfg.get("planning", "")

    # ── Step 4: call AI ───────────────────────────────────────────────────────
    ai_json = _call_ai_for_workout(
        age=age,
        target_lbs=target_lbs,
        weight_kg=weight_kg,
        z2_low=z2_low,
        z2_high=z2_high,
        baseline=baseline,
        dynamics=dynamics,
        sleep_summary=sleep_summary,
        hrv_data=hrv_data,
        readiness=readiness,
        is_weekday=is_weekday,
        max_duration_min=max_duration,
        planning_context=planning_context,
        n_runs=n_runs,
        lthr=lthr,
        z1_high=z1_high,
        z3_high=z3_high,
        z4_high=z4_high,
        max_hr=max_hr,
    )
    if not ai_json:
        logger.error("WOTD: AI returned no workout — aborting.")
        return

    logger.info(
        "WOTD: AI designed '%s' (%s, %d min, %.1f km)",
        ai_json.get("workout_name"),
        ai_json.get("workout_type"),
        ai_json.get("duration_min", 0),
        ai_json.get("distance_km", 0),
    )
    logger.info("WOTD coach note: %s", ai_json.get("coach_note", ""))

    if dry_run:
        logger.info("WOTD (dry-run): would push workout: %s", json.dumps(ai_json, indent=2))
        return

    # ── Step 5: sweep ALL stale WOTD workouts from the library ─────────────
    # More robust than deleting a single stored ID:
    # handles first-run (no stored ID), container restarts, and any duplicates.
    _sweep_stale_wotd_workouts(client)

    # ── Step 6: push today's WOTD ─────────────────────────────────────────────
    new_id = _push_wotd(client, ai_json)
    if new_id:
        id_file = user_data_dir / "wotd_last_id.txt"
        id_file.write_text(new_id, encoding="utf-8")
        logger.info("WOTD: successfully pushed. id=%s, saved to %s", new_id, id_file)
    else:
        logger.error("WOTD: push failed — id_file NOT updated.")


# ---------------------------------------------------------------------------
# Step 1 — Weighted run baseline
# ---------------------------------------------------------------------------

def _weighted_run_baseline(client: Any, n: int = 10, decay: float = 0.85) -> dict:
    """Fetch recent running activities and compute an exponentially-weighted baseline.

    Recent runs carry more weight: weight_i = decay^(N-1-i), i=0 oldest.
    Returns a dict with avg_dist_km, avg_pace_min_km, avg_hr, avg_duration_min.
    Falls back to sensible defaults when no runs are found.
    """
    defaults = {
        "avg_dist_km": 5.0,
        "avg_pace_min_km": 7.0,
        "avg_hr": 130,
        "avg_duration_min": 35,
        "run_count": 0,
    }
    try:
        activities = client.get_activities(0, max(n * 3, 30)) or []  # fetch extra to filter
    except Exception as exc:
        logger.warning("WOTD: could not fetch activities for baseline: %s", exc)
        return defaults

    runs = [
        a for a in activities
        if (a.get("activityType", {}) or {}).get("typeKey", "").lower() in
           ("running", "trail_running", "treadmill_running")
    ]
    runs = runs[:n]

    if not runs:
        logger.warning("WOTD: no recent running activities found — using defaults.")
        return defaults

    # Reverse so index 0 = oldest, index N-1 = most recent
    runs = list(reversed(runs))
    weights   = [decay ** (len(runs) - 1 - i) for i in range(len(runs))]
    total_w   = sum(weights)

    w_dist = w_pace = w_hr = w_dur = 0.0
    hr_w_total = 0.0

    for run, w in zip(runs, weights):
        dist_m   = run.get("distance") or 0
        dur_s    = run.get("duration") or run.get("movingDuration") or 0
        speed_ms = run.get("averageSpeed") or 0
        avg_hr   = run.get("averageHR")

        dist_km    = dist_m / 1000.0
        dur_min    = dur_s / 60.0
        pace_min_km = (1000.0 / speed_ms / 60.0) if speed_ms > 0 else (dur_min / dist_km if dist_km > 0 else 7.0)

        w_dist += w * dist_km
        w_pace += w * pace_min_km
        w_dur  += w * dur_min
        if avg_hr:
            w_hr       += w * avg_hr
            hr_w_total += w

    return {
        "avg_dist_km":      round(w_dist / total_w, 2),
        "avg_pace_min_km":  round(w_pace / total_w, 2),
        "avg_hr":           int(w_hr / hr_w_total) if hr_w_total > 0 else 130,
        "avg_duration_min": int(w_dur  / total_w),
        "run_count":        len(runs),
    }


# ---------------------------------------------------------------------------
# Step 1b — HRM-600 Running Dynamics (last N detailed runs)
# ---------------------------------------------------------------------------

def _fetch_run_dynamics(client: Any, n: int = 3) -> dict:
    """Fetch detailed activity summaries for the last N runs and compute
    exponentially-weighted running dynamics from HRM-600.

    Returns a dict with avg power, cadence, GCT, stride, vertical metrics,
    plus the most recent run's compliance and RPE.
    Silently returns empty dict on any API failure.
    """
    empty = {"run_count": 0}
    try:
        activities = client.get_activities(0, max(n * 3, 15)) or []
    except Exception as exc:
        logger.warning("WOTD dynamics: could not fetch activity list: %s", exc)
        return empty

    runs = [
        a for a in activities
        if (a.get("activityType") or {}).get("typeKey", "").lower()
        in ("running", "trail_running", "treadmill_running")
    ][:n]

    if not runs:
        return empty

    # Most recent first → reversed for weighting (index 0 = oldest in window)
    runs_rev = list(reversed(runs))
    decay = 0.85
    weights = [decay ** (len(runs_rev) - 1 - i) for i in range(len(runs_rev))]
    total_w = sum(weights)

    w_power = w_norm = w_cad = w_gct = w_bal = w_stride = w_osc = w_ratio = 0.0
    cnt_power = cnt_cad = cnt_gct = cnt_bal = cnt_stride = cnt_osc = cnt_ratio = 0.0

    last_compliance = last_rpe = last_feeling = None

    for idx, (run, w) in enumerate(zip(runs_rev, weights)):
        act_id = run.get("activityId")
        if not act_id:
            continue
        try:
            detail = client.get_activity(act_id) or {}
            s = detail.get("summaryDTO") or {}
        except Exception as exc:
            logger.warning("WOTD dynamics: could not fetch activity %s: %s", act_id, exc)
            continue

        def _wt(field, acc, cnt):
            v = s.get(field)
            if v is not None and float(v) > 0:
                return acc + w * float(v), cnt + w
            return acc, cnt

        w_power,  cnt_power  = _wt("averagePower",              w_power,  cnt_power)
        w_norm,   cnt_power  = _wt("normalizedPower",           w_norm,   cnt_power)
        w_cad,    cnt_cad    = _wt("averageRunCadence",         w_cad,    cnt_cad)
        w_gct,    cnt_gct    = _wt("groundContactTime",         w_gct,    cnt_gct)
        w_bal,    cnt_bal    = _wt("groundContactBalanceLeft",  w_bal,    cnt_bal)
        w_stride, cnt_stride = _wt("strideLength",              w_stride, cnt_stride)
        w_osc,    cnt_osc    = _wt("verticalOscillation",       w_osc,    cnt_osc)
        w_ratio,  cnt_ratio  = _wt("verticalRatio",             w_ratio,  cnt_ratio)

        # Capture most recent run's compliance + RPE (runs[0] = most recent)
        if idx == len(runs_rev) - 1:
            last_compliance = s.get("directWorkoutComplianceScore")
            last_rpe        = s.get("directWorkoutRpe")
            last_feeling    = s.get("directWorkoutFeel")  # numeric → convert below

    def _avg(acc, cnt): return round(acc / cnt, 1) if cnt > 0 else None

    # Convert Garmin's 0-100 feel scale to label
    feeling_label = None
    if last_feeling is not None:
        feel = int(last_feeling)
        if feel <= 20:    feeling_label = "very_rough"
        elif feel <= 40:  feeling_label = "rough"
        elif feel <= 60:  feeling_label = "ok"
        elif feel <= 80:  feeling_label = "good"
        else:             feeling_label = "very_good"

    return {
        "run_count":          len(runs),
        "avg_power_w":        _avg(w_power,  cnt_power),
        "norm_power_w":       _avg(w_norm,   cnt_power),
        "avg_cadence_spm":    _avg(w_cad,    cnt_cad),
        "avg_gct_ms":         _avg(w_gct,    cnt_gct),
        "avg_gct_balance":    _avg(w_bal,    cnt_bal),
        "avg_stride_cm":      _avg(w_stride, cnt_stride),
        "avg_vert_osc_cm":    _avg(w_osc,    cnt_osc),
        "avg_vert_ratio_pct": _avg(w_ratio,  cnt_ratio),
        "last_compliance":    int(last_compliance) if last_compliance is not None else None,
        "last_rpe":           int(last_rpe)         if last_rpe is not None else None,
        "last_feeling":       feeling_label,
    }


# ---------------------------------------------------------------------------
# Step 1c — HRV & Training Readiness
# ---------------------------------------------------------------------------

def _fetch_hrv(client: Any) -> dict:
    """Fetch today's overnight HRV summary. Returns {} on failure."""
    try:
        data = client.get_hrv_data(date.today().isoformat()) or {}
        summary = data.get("hrvSummary") or {}
        baseline = summary.get("baseline") or {}
        return {
            "last_night_avg": summary.get("lastNightAvg"),
            "weekly_avg":     summary.get("weeklyAvg"),
            "status":         summary.get("status"),          # BALANCED / UNBALANCED / LOW
            "baseline_low":   baseline.get("balancedLow"),
            "baseline_high":  baseline.get("balancedUpper"),
        }
    except Exception as exc:
        logger.warning("WOTD: could not fetch HRV data: %s", exc)
        return {}


def _fetch_training_readiness(client: Any) -> dict:
    """Fetch today's Training Readiness score. Returns {} on failure."""
    try:
        data = client.get_training_readiness(date.today().isoformat()) or []
        rec = data[0] if isinstance(data, list) and data else (data or {})
        # Find the most limiting factor (lowest factor percentage)
        factors = {
            "sleep":   rec.get("sleepScoreFactorPercent"),
            "hrv":     rec.get("hrvFactorPercent"),
            "load":    rec.get("acwrFactorPercent"),
            "stress":  rec.get("stressHistoryFactorPercent"),
        }
        limiting = min(
            ((k, v) for k, v in factors.items() if v is not None),
            key=lambda x: x[1],
            default=(None, None),
        )[0]
        return {
            "score":          rec.get("score"),
            "level":          rec.get("level"),          # LOW / MODERATE / HIGH
            "recovery_time_h": rec.get("recoveryTime"),
            "acute_load":     rec.get("acuteLoad"),
            "limiting_factor": limiting,
            "hrv_factor_pct":   rec.get("hrvFactorPercent"),
            "sleep_factor_pct": rec.get("sleepScoreFactorPercent"),
            "stress_factor_pct": rec.get("stressHistoryFactorPercent"),
            "load_factor_pct":  rec.get("acwrFactorPercent"),
        }
    except Exception as exc:
        logger.warning("WOTD: could not fetch training readiness: %s", exc)
        return {}


# ---------------------------------------------------------------------------
# Step 2 — Sleep quality
# ---------------------------------------------------------------------------

def _extract_sleep_summary(sleep_data: dict) -> dict:
    """Extract relevant fields from the raw Garmin sleep API response."""
    daily = (sleep_data.get("dailySleepDTO") or {})
    secs  = daily.get("sleepTimeSeconds") or 0
    hours = round(int(secs) / 3600, 1) if secs else 0.0

    scores  = daily.get("sleepScores") or {}
    overall = scores.get("overall") or {}
    score   = overall.get("value")   # 0-100

    recovery = _classify_recovery(hours, score)

    return {
        "sleep_hours":    hours,
        "sleep_score":    score,
        "recovery_status": recovery,
    }


def _classify_recovery(sleep_hours: float, sleep_score: int | None) -> str:
    score = sleep_score or 0
    if sleep_hours >= 7.5 and score >= 70:
        return "well_rested"
    elif sleep_hours >= 6.0 and score >= 50:
        return "adequate"
    elif sleep_hours >= 5.0 and score >= 40:
        return "tired"
    else:
        return "very_tired"


# ---------------------------------------------------------------------------
# Step 4 — AI call
# ---------------------------------------------------------------------------

def _call_ai_for_workout(
    age: int,
    target_lbs: int,
    weight_kg: float | None,
    z2_low: int,
    z2_high: int,
    baseline: dict,
    dynamics: dict,
    sleep_summary: dict,
    hrv_data: dict,
    readiness: dict,
    is_weekday: bool,
    max_duration_min: int,
    planning_context: str,
    n_runs: int,
    # Full zone chart from LTHR
    lthr: int = 0,
    z1_high: int = 0,
    z3_high: int = 0,
    z4_high: int = 0,
    max_hr: int = 0,
) -> dict | None:
    """Build prompt and call Gemini to get today's workout JSON."""
    weight_str = f"{weight_kg:.1f} kg" if weight_kg else "unknown"
    day_type   = "Weekday" if is_weekday else "Weekend"
    recovery   = sleep_summary["recovery_status"]
    sleep_h    = sleep_summary["sleep_hours"]
    sleep_s    = sleep_summary["sleep_score"]
    score_str  = f"{sleep_s}/100" if sleep_s is not None else "not available"

    # ── Format running dynamics section ──────────────────────────────────────
    if dynamics.get("run_count", 0) > 0:
        cadence    = dynamics.get("avg_cadence_spm")
        power      = dynamics.get("avg_power_w")
        norm_pwr   = dynamics.get("norm_power_w")
        gct        = dynamics.get("avg_gct_ms")
        gct_bal    = dynamics.get("avg_gct_balance")
        stride     = dynamics.get("avg_stride_cm")
        vert_osc   = dynamics.get("avg_vert_osc_cm")
        vert_ratio = dynamics.get("avg_vert_ratio_pct")
        compliance = dynamics.get("last_compliance")
        last_rpe   = dynamics.get("last_rpe")
        feeling    = dynamics.get("last_feeling")

        # Cadence coaching note
        cadence_note = ""
        if cadence and cadence < 160:
            cadence_note = f" ← LOW (target 170+ spm — consider shorter, quicker steps)"
        elif cadence and cadence < 170:
            cadence_note = f" ← approaching target (goal: 170+ spm)"
        else:
            cadence_note = f" ← good"

        # Compliance signal for difficulty adjustment
        compliance_note = ""
        if compliance is not None:
            if compliance >= 80:
                compliance_note = f"{compliance}% ✅ — can nudge today slightly harder"
            elif compliance < 60:
                compliance_note = f"{compliance}% ⚠️ — consider slightly easier today"
            else:
                compliance_note = f"{compliance}%"

        # Vertical ratio efficiency
        vert_note = ""
        if vert_ratio:
            if vert_ratio > 10:
                vert_note = " ← high bounce (energy wastage — cue: run tall, drive hips)"
            elif vert_ratio > 8:
                vert_note = " ← moderate (improving)"
            else:
                vert_note = " ← good efficiency"

        dynamics_section = f"""\nRUNNING DYNAMICS (HRM-600, weighted avg last {dynamics['run_count']} run(s)):
  Running power:      {power or 'n/a'} W avg / {norm_pwr or 'n/a'} W normalized
  Cadence:            {cadence or 'n/a'} spm{cadence_note}
  Ground contact:     {gct or 'n/a'} ms | balance left: {gct_bal or 'n/a'}% (ideal ~50%)
  Stride length:      {stride or 'n/a'} cm
  Vertical oscillation: {vert_osc or 'n/a'} cm | vertical ratio: {vert_ratio or 'n/a'}%{vert_note}
  Last WOTD compliance: {compliance_note or 'n/a'}
  Last run RPE:       {last_rpe or 'n/a'}/100 | feeling: {feeling or 'n/a'}"""
    else:
        dynamics_section = "\nRUNNING DYNAMICS: Not yet available (HRM-600 recently added)."

    # ── Format HRV section ────────────────────────────────────────────────────
    if hrv_data.get("last_night_avg"):
        hrv_status = hrv_data.get("status", "unknown")
        hrv_last   = hrv_data["last_night_avg"]
        hrv_wkly   = hrv_data.get("weekly_avg", "n/a")
        hrv_low    = hrv_data.get("baseline_low", "n/a")
        hrv_high   = hrv_data.get("baseline_high", "n/a")
        hrv_delta  = hrv_last - hrv_wkly if isinstance(hrv_wkly, (int, float)) else 0
        hrv_trend  = f"+{hrv_delta}" if hrv_delta >= 0 else str(hrv_delta)
        hrv_section = f"""\nHRV (overnight, HRM-600 correlated):
  Last night: {hrv_last} ms (weekly avg: {hrv_wkly} ms, trend: {hrv_trend} ms)
  Status:     {hrv_status} (athlete baseline: {hrv_low}–{hrv_high} ms)"""
    else:
        hrv_section = "\nHRV: Not available."

    # ── Format Training Readiness section ────────────────────────────────────
    if readiness.get("score") is not None:
        r_score    = readiness["score"]
        r_level    = readiness.get("level", "unknown")
        r_limit    = readiness.get("limiting_factor", "none")
        r_recov_h  = readiness.get("recovery_time_h", "n/a")
        r_load     = readiness.get("acute_load", "n/a")
        readiness_section = f"""\nTRAINING READINESS (composite — HRV + recovery + load + sleep + stress):
  Score:            {r_score}/100 ({r_level})
  Recovery time:    {r_recov_h} h remaining
  Acute training load: {r_load}
  Limiting factor:  {r_limit} (the factor most holding the score down)
  Factors:          sleep {readiness.get('sleep_factor_pct', 'n/a')}% | hrv {readiness.get('hrv_factor_pct', 'n/a')}% | load {readiness.get('load_factor_pct', 'n/a')}% | stress {readiness.get('stress_factor_pct', 'n/a')}%"""
    else:
        readiness_section = "\nTRAINING READINESS: Not available."

    prompt = f"""You are an expert running coach AI specialising in weight-loss training for recreational runners.
You have access to detailed HRM-600 running dynamics and Garmin's physiological metrics.

ATHLETE PROFILE:
  Age: {age}
  Weight: {weight_str}
  Target weight: {target_lbs} lbs (~{round(target_lbs * 0.453592, 1)} kg)
  Zone chart (Coggan modified model, all from LTHR = {lthr} bpm):
    Z1 Recovery   < {z1_high} bpm    (< 76% LTHR — warm-up / cool-down only)
    Z2 Aerobic    {z2_low}–{z2_high} bpm  (76–90% LTHR — TARGET ZONE: fat-burning, aerobic base; widest practical range)
    Z3 Tempo      {z2_high+1}–{z3_high} bpm  (90–94% LTHR — aerobic threshold; avoid on easy days)
    Z4 Threshold  {z3_high+1}–{z4_high} bpm  (94–105% LTHR — hard; only in explicit threshold work)
    Z5 Max        > {z4_high} bpm    (> 105% LTHR — maximum; not relevant for weight loss phase)
  Max HR (estimated): {max_hr} bpm

TRAINING CONTEXT:
{planning_context.strip()}

LAST NIGHT'S SLEEP:
  Duration:        {sleep_h} hours
  Sleep score:     {score_str}
  Recovery status: {recovery}
{hrv_section}
{readiness_section}

RECENT FITNESS BASELINE (exponentially-weighted last {n_runs} runs, recent = higher weight):
  Avg distance:  {baseline['avg_dist_km']} km
  Avg pace:      {baseline['avg_pace_min_km']} min/km
  Avg HR:        {baseline['avg_hr']} bpm
  Avg duration:  {baseline['avg_duration_min']} min
{dynamics_section}

TODAY:
  Day type:     {day_type}
  Max duration: {max_duration_min} minutes (including warmup and cooldown)

DESIGN exactly ONE workout for today. Rules:
1. Total duration (warmup + main + cooldown) MUST NOT exceed {max_duration_min} minutes.
2. Use Training Readiness as the PRIMARY intensity driver:
   - Score ≥ 70 (HIGH): can assign normal/progressive effort
   - Score 50–69 (MODERATE): keep fully aerobic, reduce intensity ~10%
   - Score < 50 (LOW): easy recovery run or walk-run only
3. Use sleep recovery as a SECONDARY signal (reinforces readiness).
4. Use walk-run intervals to keep HR in Zone 2 (athlete's HR spikes to Z3/4 when running continuously).
5. Optimise for weight loss: prioritise fat-burning aerobic volume over speed.
6. Compliance signal: if last WOTD compliance was ≥ 80%, you can push slightly harder today.
   If compliance was < 60% AND readiness is < 65, ease off slightly.
7. Cadence coaching: if avg cadence < 165 spm, prefer structured intervals so the athlete
   can focus on quick short steps during run segments (target: 170+ spm).
8. Power targets (if available): design intervals where target effort is ~{int(dynamics.get('avg_power_w', 0) * 0.90) if dynamics.get('avg_power_w') else 'n/a'} W Z2 power.
9. workout_type must be one of: "simple", "structured", "long"
   - Use "long" ONLY on weekends when duration > 60 min
   - Use "structured" for interval/walk-run work (preferred when cadence < 165)
   - Use "simple" for steady-pace aerobic runs
10. WALK-BREAK RULE (critical for knee health and zone compliance):
    - Run segments: target HR {z2_low}–{z2_high} bpm (empirically calibrated Z2)
    - Walk break trigger: START WALKING immediately if HR reaches {walk_break_hr} bpm or above
    - Resume running when HR drops back below {z2_low} bpm (full Z1 recovery)
    - This is non-negotiable: crossing {walk_break_hr} bpm risks knee fatigue and Z3 drift
    - The walk-run method is the PREFERRED format for this athlete (knees, injury prevention)

Return ONLY valid JSON (no markdown, no explanation):
{{
  "workout_name": "WOTD: [short descriptive name]",
  "workout_type": "structured",
  "description": "2-3 sentence description shown in Garmin Connect",
  "duration_min": 60,
  "distance_km": 7.0,
  "target_hr_low": {z2_low},
  "target_hr_high": {z2_high},
  "target_power_low": null,
  "target_power_high": null,
  "warmup_min": 5,
  "main_min": 50,
  "cooldown_min": 5,
  "cadence_target_spm": 170,
  "coach_note": "Why this workout today, what to focus on, 2-3 sentences",
  "intervals": []
}}

For structured workouts with run/walk intervals, populate "intervals":
[{{"iterations": 6, "work_min": 5, "recovery_min": 1, "hr_low": {z2_low}, "hr_high": {z2_high}, "cadence_spm": 170}}]
"""

    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        model = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",
            google_api_key=os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY"),
            temperature=0.3,
        )
        response = model.invoke(prompt)
        raw = response.content.strip()

        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        result = json.loads(raw)
        # Validate required fields
        if "workout_name" not in result or "workout_type" not in result:
            logger.error("WOTD: AI response missing required fields: %s", raw[:200])
            return None

        # Enforce workout name prefix
        if not result["workout_name"].startswith(WOTD_NAME_PREFIX):
            result["workout_name"] = WOTD_NAME_PREFIX + " " + result["workout_name"]

        # ── Hard duration clamp (safety net — prompt should already enforce this) ──
        # Guarantees weekday ≤ 60 min and weekend ≤ 105 min regardless of AI output.
        total = result.get("duration_min", 0)
        if total > max_duration_min:
            overflow = total - max_duration_min
            # Trim from main block first; never trim warmup/cooldown below 3 min each
            main_min = result.get("main_min", total - result.get("warmup_min", 5) - result.get("cooldown_min", 5))
            new_main = max(main_min - overflow, 3)
            result["main_min"] = new_main
            result["duration_min"] = result.get("warmup_min", 5) + new_main + result.get("cooldown_min", 5)
            logger.warning(
                "WOTD: AI returned duration_min=%d > cap=%d — clamped to %d min (main: %d→%d).",
                total, max_duration_min, result["duration_min"], main_min, new_main,
            )

        return result
    except Exception as exc:
        logger.error("WOTD: AI call failed: %s", exc, exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Step 5 — Sweep all stale WOTD workouts from the library
# ---------------------------------------------------------------------------

def _sweep_stale_wotd_workouts(client: Any) -> int:
    """Delete every WOTD:-prefixed workout from the Garmin workout library.

    This is a full sweep rather than a single-ID delete, so it handles:
    - First run (no stored ID file)
    - Workouts that accumulated before the ID file existed
    - Any duplicates that crept in via manual pushes

    Returns the count of workouts deleted.
    """
    try:
        workouts = client.get_workouts(0, 100) or []
    except Exception as exc:
        logger.warning("WOTD sweep: could not list workouts from library: %s", exc)
        return 0

    deleted = 0
    for w in workouts:
        name = (w.get("workoutName") or "").strip()
        wid  = str(w.get("workoutId", ""))
        if not name.startswith(WOTD_NAME_PREFIX) or not wid:
            continue
        try:
            client.delete_workout(wid)
            logger.info("WOTD sweep: deleted '%s' (id=%s)", name, wid)
            deleted += 1
        except Exception as exc:
            exc_str = str(exc).lower()
            if "404" in exc_str or "not found" in exc_str:
                logger.info("WOTD sweep: '%s' (id=%s) already gone — skipping.", name, wid)
            else:
                logger.warning("WOTD sweep: could not delete '%s' (id=%s): %s", name, wid, exc)

    if deleted:
        logger.info("WOTD sweep: removed %d stale workout(s) from library.", deleted)
    else:
        logger.info("WOTD sweep: no stale WOTD workouts found in library.")
    return deleted


# ---------------------------------------------------------------------------
# Step 6 — Push today's WOTD
# ---------------------------------------------------------------------------

def _push_wotd(client: Any, ai_json: dict) -> str | None:
    """Build a Garmin RunningWorkout from the AI JSON and push + schedule it for today.

    Returns the new workout_id string, or None on failure.
    """
    try:
        from garminconnect.workout import (
            RunningWorkout,
            WorkoutSegment,
            create_cooldown_step,
            create_interval_step,
            create_recovery_step,
            create_repeat_group,
            create_warmup_step,
        )

        workout_type = ai_json.get("workout_type", "simple")
        warmup_secs  = float(ai_json.get("warmup_min", 5)) * 60
        main_secs    = float(ai_json.get("main_min", 30)) * 60
        cooldown_secs = float(ai_json.get("cooldown_min", 5)) * 60
        total_secs   = warmup_secs + main_secs + cooldown_secs
        hr_low       = float(ai_json.get("target_hr_low", 120))
        hr_high      = float(ai_json.get("target_hr_high", 145))

        HR_TARGET = {
            "workoutTargetTypeId": 4,
            "workoutTargetTypeKey": "heart.rate.zone",
            "displayOrder": 4,
        }
        NO_TARGET = {
            "workoutTargetTypeId": 1,
            "workoutTargetTypeKey": "no.target",
            "displayOrder": 1,
        }

        warmup   = create_warmup_step(warmup_secs, step_order=1)
        cooldown = create_cooldown_step(cooldown_secs, step_order=99)

        if workout_type == "structured" and ai_json.get("intervals"):
            steps = [warmup]
            for order, ivl in enumerate(ai_json["intervals"], start=2):
                work_secs     = float(ivl.get("work_min", 4)) * 60
                recovery_secs = float(ivl.get("recovery_min", 1)) * 60
                iterations    = int(ivl.get("iterations", 4))
                ivl_hr_low    = float(ivl.get("hr_low", hr_low))
                ivl_hr_high   = float(ivl.get("hr_high", hr_high))

                work_step = create_interval_step(work_secs, step_order=1, target_type=HR_TARGET)
                work_step.targetValueOne = ivl_hr_low
                work_step.targetValueTwo = ivl_hr_high
                rec_step  = create_recovery_step(recovery_secs, step_order=2, target_type=NO_TARGET)
                repeat    = create_repeat_group(
                    iterations=iterations,
                    workout_steps=[work_step, rec_step],
                    step_order=order,
                )
                steps.append(repeat)
            steps.append(cooldown)

        elif workout_type == "long":
            main_step = create_interval_step(main_secs, step_order=2, target_type=NO_TARGET)
            steps = [warmup, main_step, cooldown]

        else:  # simple
            main_step = create_interval_step(main_secs, step_order=2, target_type=HR_TARGET)
            main_step.targetValueOne = hr_low
            main_step.targetValueTwo = hr_high
            steps = [warmup, main_step, cooldown]

        workout = RunningWorkout(
            workoutName=ai_json["workout_name"][:64],
            estimatedDurationInSecs=int(total_secs),
            description=(ai_json.get("description", ""))[:500],
            workoutSegments=[
                WorkoutSegment(
                    segmentOrder=1,
                    sportType={"sportTypeId": 1, "sportTypeKey": "running"},
                    workoutSteps=steps,
                )
            ],
        )

        upload_result = client.upload_running_workout(workout)
        workout_id    = str(upload_result["workoutId"])
        today_str     = date.today().isoformat()
        client.schedule_workout(workout_id, today_str)
        logger.info("WOTD: uploaded and scheduled id=%s for %s", workout_id, today_str)
        return workout_id

    except Exception as exc:
        logger.error("WOTD: push failed: %s", exc, exc_info=True)
        return None
