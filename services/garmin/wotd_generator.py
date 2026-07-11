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

    # ── Step 1: weighted run baseline ────────────────────────────────────────
    n_runs   = int(wotd_cfg.get("recent_runs_count", 10))
    decay    = float(wotd_cfg.get("decay_factor", 0.85))
    baseline = _weighted_run_baseline(client, n=n_runs, decay=decay)
    logger.info("WOTD: baseline from last %d runs (decay=%.2f): %s", n_runs, decay, baseline)

    # ── Step 2: sleep quality ─────────────────────────────────────────────────
    sleep_summary = _extract_sleep_summary(sleep_data)
    logger.info("WOTD: sleep summary: %s", sleep_summary)

    # ── Step 3: athlete profile & constraints ─────────────────────────────────
    athlete_cfg = config.get("athlete", {})
    context_cfg = config.get("context", {})
    age         = int(athlete_cfg.get("age", 53))

    # Zone 2 HR — derive from LTHR if available, otherwise age-based
    lthr = None
    try:
        profile_data = client.get_training_status()
        lthr = (profile_data or {}).get("lactateThresholdHeartRate")
    except Exception:
        pass

    max_hr    = int(lthr / 0.88) if lthr else (220 - age)
    z2_low    = int(lthr * 0.80) if lthr else int(max_hr * 0.60)
    z2_high   = int(lthr * 0.89) if lthr else int(max_hr * 0.72)

    # Override with manual config if provided
    if athlete_cfg.get("zone2_min"):
        z2_low = int(athlete_cfg["zone2_min"])
    if athlete_cfg.get("zone2_max"):
        z2_high = int(athlete_cfg["zone2_max"])

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
        sleep_summary=sleep_summary,
        is_weekday=is_weekday,
        max_duration_min=max_duration,
        planning_context=planning_context,
        n_runs=n_runs,
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
    sleep_summary: dict,
    is_weekday: bool,
    max_duration_min: int,
    planning_context: str,
    n_runs: int,
) -> dict | None:
    """Build prompt and call Gemini (via langchain) to get today's workout JSON."""
    weight_str = f"{weight_kg:.1f} kg" if weight_kg else "unknown"
    day_type   = "Weekday" if is_weekday else "Weekend"
    recovery   = sleep_summary["recovery_status"]
    sleep_h    = sleep_summary["sleep_hours"]
    sleep_s    = sleep_summary["sleep_score"]

    score_str = f"{sleep_s}/100" if sleep_s is not None else "not available"

    prompt = f"""You are an expert running coach AI specialising in weight-loss training for recreational runners.

ATHLETE PROFILE:
  Age: {age}
  Weight: {weight_str}
  Target weight: {target_lbs} lbs (~{round(target_lbs * 0.453592, 1)} kg)
  Zone 2 HR range: {z2_low}–{z2_high} bpm

TRAINING CONTEXT:
{planning_context.strip()}

LAST NIGHT'S SLEEP:
  Duration:        {sleep_h} hours
  Sleep score:     {score_str}
  Recovery status: {recovery}

RECENT FITNESS BASELINE (exponentially-weighted last {n_runs} runs, recent = higher weight):
  Avg distance:  {baseline['avg_dist_km']} km
  Avg pace:      {baseline['avg_pace_min_km']} min/km
  Avg HR:        {baseline['avg_hr']} bpm
  Avg duration:  {baseline['avg_duration_min']} min

TODAY:
  Day type:     {day_type}
  Max duration: {max_duration_min} minutes (including warmup and cooldown)

DESIGN exactly ONE workout for today. Rules:
1. Total duration (warmup + main + cooldown) MUST NOT exceed {max_duration_min} minutes.
2. Adjust intensity based on recovery:
   - well_rested: normal or slightly progressive effort
   - adequate: normal effort, stay aerobic
   - tired: reduce distance by ~20%, keep entirely Zone 2
   - very_tired: short easy jog or walk-run, 25-30 min max
3. Use walk-run intervals if needed to keep HR in Zone 2 (athlete struggles to stay in Z2 while running).
4. Optimise for weight loss: prioritise fat-burning aerobic work over speed.
5. workout_type must be one of: "simple", "structured", "long"
   - Use "long" ONLY on weekends when duration > 60 min
   - Use "structured" for interval work (e.g. run 4 min / walk 1 min repeats)
   - Use "simple" for steady-pace aerobic runs

Return ONLY valid JSON (no markdown, no explanation):
{{
  "workout_name": "WOTD: [short descriptive name]",
  "workout_type": "simple",
  "description": "2-3 sentence description shown in Garmin Connect",
  "duration_min": 45,
  "distance_km": 6.0,
  "target_hr_low": {z2_low},
  "target_hr_high": {z2_high},
  "warmup_min": 5,
  "main_min": 35,
  "cooldown_min": 5,
  "coach_note": "Why this workout today in 1-2 sentences",
  "intervals": []
}}

For structured workouts with run/walk intervals, populate "intervals":
[{{"iterations": 4, "work_min": 4, "recovery_min": 1, "hr_low": {z2_low}, "hr_high": {z2_high}}}]
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
