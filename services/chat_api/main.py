"""FastAPI chat backend for interactive AI coaching.

Exposes POST /chat so the browser can send a natural-language prompt and
receive an updated weekly plan without re-running the full Garmin analysis.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

app = FastAPI(title="Garmin AI Coach Chat API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Persistent conversation / feedback history (saved to data directory)
# ---------------------------------------------------------------------------

def _get_feedback_history_path(user_id: str) -> Path:
    return DATA_DIR / user_id / "feedback_history.json"


def _load_feedback_history(user_id: str) -> list[dict[str, str]]:
    path = _get_feedback_history_path(user_id)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Could not load feedback history from %s: %s", path, exc)
    return []


def _save_feedback_history(user_id: str, history: list[dict[str, str]]) -> None:
    path = _get_feedback_history_path(user_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(history, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.error("Could not save feedback history to %s: %s", path, exc)

# ---------------------------------------------------------------------------
# Data directory (shared volume with the coach container)
# ---------------------------------------------------------------------------
DATA_DIR = Path(os.getenv("OUTPUT_DIR", "/app/data"))


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    user_id: str = "Arnabbiswas"
    message: str


class ChatResponse(BaseModel):
    reply: str
    plan_updated: bool
    history: list[dict[str, str]]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> dict[str, Any]:
    """Load a JSON file; return empty dict on failure."""
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Could not load %s: %s", path, exc)
    return {}


def _read_text(path: Path) -> str:
    try:
        if path.exists():
            return path.read_text(encoding="utf-8")
    except Exception as exc:
        logger.warning("Could not read %s: %s", path, exc)
    return ""


def _build_week_dates(start: date, n_weeks: int = 4) -> list[dict[str, Any]]:
    weeks = []
    for i in range(n_weeks):
        week_start = start + timedelta(weeks=i)
        week_end = week_start + timedelta(days=6)
        weeks.append({
            "week": i + 1,
            "start": week_start.isoformat(),
            "end": week_end.isoformat(),
        })
    return weeks


def _extract_expert_outputs(user_data_dir: Path) -> tuple[Any, Any, Any]:
    """Load cached expert outputs from disk."""
    from services.ai.langgraph.schemas import ActivityExpertOutputs, MetricsExpertOutputs, PhysiologyExpertOutputs

    def _load_expert(cls, path):
        raw = _load_json(path)
        if raw:
            try:
                return cls(**raw)
            except Exception as exc:
                logger.warning("Could not parse %s: %s", path, exc)
        return None

    return (
        _load_expert(MetricsExpertOutputs, user_data_dir / "metrics_expert.json"),
        _load_expert(ActivityExpertOutputs, user_data_dir / "activity_expert.json"),
        _load_expert(PhysiologyExpertOutputs, user_data_dir / "physiology_expert.json"),
    )


def _build_planning_context(history: list[dict[str, str]], new_message: str) -> str:
    """Build a planning_context string from conversation history + new message."""
    lines = []
    if history:
        lines.append("## Previous coaching session context:")
        for turn in history:
            role = "Athlete" if turn["role"] == "user" else "Coach"
            lines.append(f"- **{role}**: {turn['content']}")
        lines.append("")
    lines.append(f"## Current athlete request:\n{new_message}")
    return "\n".join(lines)


async def _run_weekly_replan(
    user_id: str,
    user_data_dir: Path,
    planning_context: str,
) -> tuple[str, str]:
    """Re-run only the weekly planning branch and return (weekly_plan_md, planning_html)."""
    from services.ai.langgraph.workflows.planning_workflow import run_weekly_planning_with_context

    metrics_outputs, activity_outputs, physiology_outputs = _extract_expert_outputs(user_data_dir)
    season_plan = _read_text(user_data_dir / "season_plan.md")

    today = date.today()
    current_date = {
        "date": today.isoformat(),
        "day_name": today.strftime("%A"),
        "week_number": today.isocalendar()[1],
    }
    week_dates = _build_week_dates(today)

    result = await run_weekly_planning_with_context(
        user_id=user_id,
        athlete_name=user_id,
        season_plan_text=season_plan,
        planning_context=planning_context,
        current_date=current_date,
        week_dates=week_dates,
        metrics_outputs=metrics_outputs,
        activity_outputs=activity_outputs,
        physiology_outputs=physiology_outputs,
    )

    weekly_plan_md: str = result.get("weekly_plan_md", "")
    planning_html: str = result.get("planning_html", "")
    return weekly_plan_md, planning_html


def _parse_distance_override(message: str) -> float | None:
    """
    Extract an explicit run distance from a message.
    Supports patterns like:
      "3 miles", "3.5 miles", "5k", "5 km", "8 kilometers", "10K"
    Returns distance in **km**, or None if no override detected.
    """
    msg = message.lower().strip()

    # Miles: e.g. "3 miles", "3.5 mile"
    miles_match = re.search(r"(\d+(?:\.\d+)?)\s*miles?", msg)
    if miles_match:
        return round(float(miles_match.group(1)) * 1.60934, 2)

    # Kilometres written out: e.g. "8 km", "8 kilometers", "8 kilometres"
    km_match = re.search(r"(\d+(?:\.\d+)?)\s*k(?:m|ilomete?rs?)?", msg)
    if km_match:
        return float(km_match.group(1))

    return None


def _apply_suggested_run_override(
    user_data_dir: Path,
    distance_km: float,
) -> dict | None:
    """
    Load the existing suggested_run.json, override the distance (and
    recompute duration + structured segments), save both copies, and
    return the updated suggestion dict.
    """
    src = user_data_dir / "suggested_run.json"
    if not src.exists():
        logger.warning("suggested_run.json not found at %s — skipping override", src)
        return None

    try:
        suggestion = json.loads(src.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Could not parse suggested_run.json: %s", exc)
        return None

    # Recompute duration using existing pace
    segs = suggestion.get("structured_segments", {})
    pace_min = segs.get("target_pace_min", 8)
    pace_sec = segs.get("target_pace_sec", 57)
    pace_min_km = pace_min + pace_sec / 60.0  # min/km

    warmup_secs  = segs.get("warmup_secs",  300)
    cooldown_secs = segs.get("cooldown_secs", 300)
    run_secs = int(round(distance_km * pace_min_km * 60))
    total_min = round((warmup_secs + run_secs + cooldown_secs) / 60, 1)

    # Patch the suggestion
    suggestion["distance_km"] = round(distance_km, 2)
    suggestion["duration_min"] = total_min
    suggestion["workout_name"] = f"Coach: Athlete Override {distance_km:.1f}km"
    suggestion["notes"] = (
        f"Athlete requested {distance_km:.1f} km today (overriding autoregulated suggestion). "
        + suggestion.get("notes", "")
    )
    suggestion["structured_segments"] = {
        **segs,
        "name": suggestion["workout_name"],
        "run_secs": run_secs,
    }

    # Save to both locations
    for path in (src, DATA_DIR / "suggested_run.json"):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(suggestion, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning("Could not write %s: %s", path, exc)

    return suggestion


def _build_run_reply(suggestion: dict, distance_km: float, user_message: str) -> str:
    """Return a specific coach reply showing the updated workout details."""
    pace = suggestion.get("target_pace_str", "—")
    hr   = suggestion.get("target_hr_range", "—")
    dur  = suggestion.get("duration_min", "—")
    dist_mi = round(distance_km / 1.60934, 2)

    return (
        f"✅ Got it — I've updated today's workout to **{distance_km:.1f} km ({dist_mi} miles)**. "
        f"Here's your plan:\n\n"
        f"- 📏 **Distance:** {distance_km:.1f} km ({dist_mi} mi)\n"
        f"- ⏱ **Estimated time:** {dur} min\n"
        f"- 🏃 **Target pace:** {pace}\n"
        f"- ❤️ **HR zone:** {hr} (Zone 2)\n\n"
        f"The page will refresh automatically. Go crush it! 💪"
    )


def _summarise_change(new_plan: str, user_message: str) -> str:
    """Generic fallback reply when no specific run override was detected."""
    if not new_plan:
        return "I've updated the plan based on your feedback."
    return (
        "✅ I've updated the training plan based on your feedback. "
        "The page will refresh automatically so you can see the changes. "
        f'*(Your note: "{user_message}")*'
    )


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    user_id = req.user_id.strip() or "Arnabbiswas"
    message = req.message.strip()

    if not message:
        return ChatResponse(
            reply="Please send a non-empty message.",
            plan_updated=False,
            history=_load_feedback_history(user_id),
        )

    history = _load_feedback_history(user_id)
    history.append({"role": "user", "content": message})
    _save_feedback_history(user_id, history)

    user_data_dir = DATA_DIR / user_id

    planning_context = _build_planning_context(history[:-1], message)

    old_plan = _read_text(user_data_dir / "weekly_plan.md")

    plan_updated = False
    reply = "I encountered an error updating the plan. Please try again."

    # ── Step 1: Check for an explicit distance override ────────────────────
    distance_km = _parse_distance_override(message)
    updated_suggestion: dict | None = None
    if distance_km:
        logger.info("Distance override detected: %.2f km", distance_km)
        updated_suggestion = _apply_suggested_run_override(user_data_dir, distance_km)
        # Inject the override into planning_context so the LLM plan also reflects it
        miles = round(distance_km / 1.60934, 2)
        planning_context += (
            f"\n\n## Athlete distance override (apply this exactly):\n"
            f"The athlete has requested to run **{distance_km:.1f} km ({miles} miles)** today. "
            f"Update Today's Run in the weekly plan to reflect this exact distance, keeping Zone 2 HR."
        )

    try:
        logger.info("Running weekly re-plan for user=%s message=%r", user_id, message[:80])
        weekly_plan_md, planning_html = await asyncio.wait_for(
            _run_weekly_replan(user_id, user_data_dir, planning_context),
            timeout=300,
        )

        if weekly_plan_md:
            # Persist updated plans
            (user_data_dir / "weekly_plan.md").write_text(weekly_plan_md, encoding="utf-8")
            # Also update root data/ so nginx serves the new version
            root_data = DATA_DIR
            (root_data / "weekly_plan.md").write_text(weekly_plan_md, encoding="utf-8")

        if planning_html:
            (user_data_dir / "planning.html").write_text(planning_html, encoding="utf-8")
            (DATA_DIR / "planning.html").write_text(planning_html, encoding="utf-8")

        plan_updated = bool(weekly_plan_md)

        # ── Step 2: Build a specific or generic reply ──────────────────────
        if updated_suggestion and distance_km:
            reply = _build_run_reply(updated_suggestion, distance_km, message)
        else:
            reply = _summarise_change(weekly_plan_md, message)

    except TimeoutError:
        logger.error("Weekly re-plan timed out for user=%s", user_id)
        reply = "⏱ The re-planning took too long. Please try a simpler request."
    except Exception as exc:
        logger.exception("Weekly re-plan failed for user=%s: %s", user_id, exc)
        reply = f"❌ An error occurred while updating the plan: {exc!s}"

    # Load fresh history before appending response to make sure we stay in sync
    history = _load_feedback_history(user_id)
    history.append({"role": "assistant", "content": reply})
    _save_feedback_history(user_id, history)

    return ChatResponse(reply=reply, plan_updated=plan_updated, history=history)


@app.delete("/chat/{user_id}/history")
async def clear_history(user_id: str) -> dict[str, str]:
    path = _get_feedback_history_path(user_id)
    if path.exists():
        try:
            path.unlink()
        except Exception as exc:
            logger.warning("Could not delete feedback history at %s: %s", path, exc)
    return {"status": "cleared", "user_id": user_id}
