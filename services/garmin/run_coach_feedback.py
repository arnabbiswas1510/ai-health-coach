"""Lightweight post-run coaching feedback.

Called from daemon.py when a new completed activity is detected.
Makes a single AI call and produces a short coaching note (3-4 sentences).

Output:
  - Logged to daemon logger (always)
  - Appended to data/<athlete>/run_feedback.log (persistent)
  - Written to Logseq journal as a 'coach_feedback' property (if Logseq reachable)
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date
from pathlib import Path
from typing import Any

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

    if dist_km < 0.5:
        logger.info("Run feedback: activity %s too short (%.2f km) — skipping.", activity_id, dist_km)
        return None

    # ── Athlete context ───────────────────────────────────────────────────────
    athlete_cfg = config.get("athlete", {})
    context_cfg = config.get("context", {})
    age         = int(athlete_cfg.get("age", 53))

    # Zone 2 — derive same way as wotd_generator
    z2_low, z2_high = _get_zone2(client, athlete_cfg, age)

    analysis_context = context_cfg.get("analysis", "")

    # ── Build prompt ──────────────────────────────────────────────────────────
    hr_str = f"Avg HR: {avg_hr} bpm" + (f", Max HR: {max_hr} bpm" if max_hr else "")
    pace_str = f"{pace_min_km} min/km" if pace_min_km else "unknown pace"
    cal_str = f"{calories} kcal" if calories else "unknown"

    prompt = f"""You are a supportive running coach giving brief post-run feedback to an athlete.

ATHLETE:
  Age: {age}
  Goal: Lose weight to 160 lbs, building aerobic base
  Zone 2 HR: {z2_low}–{z2_high} bpm
  Background: {analysis_context.strip()}

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
1. Whether HR stayed in Zone 2 (if HR data available)
2. One thing they did well
3. One concrete tip for the next run

Keep it concise, personal, and actionable. No bullet points — flowing sentences only."""

    # ── Call AI ───────────────────────────────────────────────────────────────
    feedback = None
    try:
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
        from services.logseq import write_props_dict
        props = {"coach-feedback": feedback}
        synced = write_props_dict(props, date=date.today())
        if synced:
            logger.info("Run feedback written to Logseq journal.")
        else:
            logger.info("Logseq not reachable — feedback saved to log file only.")
    except Exception as exc:
        logger.debug("Logseq write skipped: %s", exc)

    return feedback


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_zone2(client: Any, athlete_cfg: dict, age: int) -> tuple[int, int]:
    """Derive Zone 2 HR bounds, same logic as wotd_generator."""
    lthr = None
    try:
        profile_data = client.get_training_status()
        lthr = (profile_data or {}).get("lactateThresholdHeartRate")
    except Exception:
        pass

    max_hr = int(lthr / 0.88) if lthr else (220 - age)
    z2_low = int(lthr * 0.80) if lthr else int(max_hr * 0.60)
    z2_high = int(lthr * 0.89) if lthr else int(max_hr * 0.72)

    if athlete_cfg.get("zone2_min"):
        z2_low = int(athlete_cfg["zone2_min"])
    if athlete_cfg.get("zone2_max"):
        z2_high = int(athlete_cfg["zone2_max"])

    return z2_low, z2_high
