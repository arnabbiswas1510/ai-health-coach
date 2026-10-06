"""Lightweight post-run coaching feedback.

Called from daemon.py when a new completed activity is detected.
Makes a single AI call and produces a short coaching note (3-4 sentences).

Output:
  - Logged to daemon logger (always)
  - Appended to data/<athlete>/run_feedback.log (persistent)
  - Written to Logseq journal as a 'coach_feedback' property (if Logseq reachable)

HR zones come from services.garmin.hr_zones — the SAME source WOTD uses — so the
athlete is never graded against a different Zone 2 than the one prescribed. If
LTHR cannot be resolved this raises ValueError rather than guessing from age;
daemon.py already wraps the call and will simply skip feedback for that run.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date
from pathlib import Path
from typing import Any

from services.garmin.hr_zones import get_hr_zones

logger = logging.getLogger(__name__)


def generate_run_feedback(
    client: Any,          # garminconnect.Garmin (raw)
    activity: dict,       # raw activity dict from get_activities()
    config: dict,         # parsed coach_config.yaml
    user_data_dir: Path,
) -> str | None:
    """Generate a short AI coaching note for a completed run.

    Returns the feedback string, or None on failure.
    """
    # ── Extract run stats ─────────────────────────────────────────────────────
    activity_id   = str(activity.get("activityId", ""))
    activity_name = activity.get("activityName", "Run")
    start_time    = activity.get("startTimeLocal", "")
    dist_m        = activity.get("distance") or 0
    dur_s         = activity.get("duration") or activity.get("movingDuration") or 0
    avg_speed_ms  = activity.get("averageSpeed") or 0
    avg_hr        = activity.get("averageHR")
    max_hr        = activity.get("maxHR")
    calories      = activity.get("calories") or activity.get("activeCalories")

    dist_km    = round(dist_m / 1000.0, 2) if dist_m else 0.0
    dur_min    = round(dur_s / 60.0, 1) if dur_s else 0.0
    pace_min_km = round(1000.0 / avg_speed_ms / 60.0, 2) if avg_speed_ms > 0 else None

    # Guard: must be an actual completed run with positive duration, distance, and speed
    if dist_km < 0.5 or dur_s < 60 or avg_speed_ms <= 0:
        logger.info(
            "Run feedback: activity %s is not a completed run (%.2f km, %.1f min, spd=%.2f m/s) — skipping.",
            activity_id, dist_km, dur_min, avg_speed_ms,
        )
        return None

    # Resolve target date of the actual run from startTimeLocal
    run_date = date.today()
    if start_time:
        try:
            run_date = date.fromisoformat(start_time.split()[0].split("T")[0])
        except Exception:
            pass

    # ── Athlete context ───────────────────────────────────────────────────────
    athlete_cfg = config.get("athlete", {})
    context_cfg = config.get("context", {})

    # HR zones — resolved from the SAME source of truth WOTD uses, so the run is
    # graded against exactly the zones it was prescribed in.
    # recalibrate=False: only WOTD may consume the 10-run calibration cycle.
    zones = get_hr_zones(
        client,
        athlete_cfg,
        user_data_dir,
        recalibrate=False,
        log_prefix="RunFeedback",
    )
    z2_low, z2_high = zones.z2_low, zones.z2_high
    walk_break_hr = zones.walk_break_hr

    analysis_context = context_cfg.get("analysis", "")

    # ── Build prompt ──────────────────────────────────────────────────────────
    hr_str = f"Avg HR: {avg_hr} bpm" + (f", Max HR: {max_hr} bpm" if max_hr else "")
    pace_str = f"{pace_min_km} min/km" if pace_min_km else "unknown pace"
    cal_str = f"{calories} kcal" if calories else "unknown"

    prompt = f"""You are a supportive running coach giving brief post-run feedback to an athlete.

ATHLETE:
  Goal: Lose weight to 160 lbs, building aerobic base
  Zone 2 HR (run target): {z2_low}–{z2_high} bpm (Garmin LTHR-calculated)
  Walk-break trigger: {walk_break_hr} bpm or above
  Background: {analysis_context.strip()}

These are the exact same HR targets this athlete's Workout of the Day was
prescribed with (anchored on a live Garmin LTHR of {zones.lthr} bpm), so judge
the run against these numbers and no others. The athlete trains in a walk-run
format: walk segments are INTENTIONAL recovery and HR dropping below {z2_low} bpm
during them is correct, not a failure.

CRITICAL INSTRUCTION:
Do NOT use or mention any age-based heart rate formulas (e.g. 220 - age).
Judge the run ONLY against the athlete's actual Garmin-calculated Zone 2 ({z2_low}–{z2_high} bpm)
and walk-break trigger ({walk_break_hr} bpm).

TODAY'S COMPLETED RUN:
  Name: {activity_name}
  Date: {start_time}
  Distance: {dist_km} km
  Duration: {dur_min} min
  Pace: {pace_str}
  {hr_str}
  Calories: {cal_str}

Write exactly 3–4 sentences of coaching feedback. Be specific and encouraging.
Address:
1. Whether average HR sat inside the {z2_low}–{z2_high} bpm Zone 2 band (if HR data available)
2. One thing they did well
3. One concrete tip for the next run

Keep it concise, personal, and actionable. No bullet points — flowing sentences only."""

    # ── Call AI ───────────────────────────────────────────────────────────────
    feedback = None
    try:
        try:
            from services.ai.model_config import ModelSelector
            from services.ai.ai_settings import AgentRole
            model = ModelSelector.get_llm(AgentRole.WORKOUT)
        except Exception:
            from langchain_google_genai import ChatGoogleGenerativeAI
            model = ChatGoogleGenerativeAI(
                model="gemini-2.5-flash",
                google_api_key=os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY"),
                temperature=0.4,
            )
        response = model.invoke(prompt)
        feedback = response.content.strip()
        logger.info("Run feedback for activity %s:\n%s", activity_id, feedback)
    except Exception as exc:
        logger.error("Run feedback AI call failed: %s", exc, exc_info=True)
        return None

    # ── Persist to log file ───────────────────────────────────────────────────
    try:
        log_path = user_data_dir / "run_feedback.log"
        entry = (
            f"\n{'='*60}\n"
            f"{start_time}  |  {dist_km} km  |  {dur_min} min  |  {pace_str}\n"
            f"{hr_str}  |  {cal_str}\n"
            f"{feedback}\n"
        )
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(entry)
        logger.info("Run feedback appended to %s", log_path)
    except Exception as exc:
        logger.warning("Could not write run feedback log: %s", exc)

    # ── Write to Logseq journal ───────────────────────────────────────────────
    try:
        from services.logseq import queue_pending_sync, write_props_dict
        props = {"coach": {"feedback": feedback.strip().replace("\n", " ")}}
        synced = write_props_dict(props, date=run_date)
        if synced:
            logger.info("Run feedback written to Logseq journal for %s.", run_date.isoformat())
        else:
            pending_sync_path = user_data_dir / "pending_logseq_syncs.json"
            queue_pending_sync(pending_sync_path, run_date.isoformat(), props)
            logger.info(
                "Logseq: SSH unavailable — queued coach feedback for %s in %s",
                run_date.isoformat(), pending_sync_path,
            )
    except Exception as exc:
        logger.warning("Could not write or queue run feedback for Logseq: %s", exc)

    return feedback

