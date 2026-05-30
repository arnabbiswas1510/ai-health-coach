"""FastAPI chat backend for interactive AI coaching.

Exposes POST /chat so the browser can send a natural-language prompt and
receive an updated weekly plan without re-running the full Garmin analysis.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
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
# In-memory conversation history (per-user, resets on server restart)
# ---------------------------------------------------------------------------
_conversation_history: dict[str, list[dict[str, str]]] = {}

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


def _build_week_dates(start: date, n_weeks: int = 4) -> list[dict[str, str]]:
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


def _summarise_change(old_plan: str, new_plan: str, user_message: str) -> str:
    """Return a short coach-style reply summarising what changed."""
    if not new_plan:
        return "I've updated your training plan based on your feedback."

    return (
        "✅ I've updated your 4-week training plan based on your request. "
        "The plan has been refreshed on this page — scroll down to see the changes. "
        f"(Your request: *\"{user_message}\"*)"
    )


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:  # noqa: C901
    user_id = req.user_id.strip() or "Arnabbiswas"
    message = req.message.strip()

    if not message:
        return ChatResponse(
            reply="Please send a non-empty message.",
            plan_updated=False,
            history=_conversation_history.get(user_id, []),
        )

    history = _conversation_history.setdefault(user_id, [])
    history.append({"role": "user", "content": message})

    user_data_dir = DATA_DIR / user_id

    planning_context = _build_planning_context(history[:-1], message)

    old_plan = _read_text(user_data_dir / "weekly_plan.md")

    plan_updated = False
    reply = "I encountered an error updating the plan. Please try again."

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
        reply = _summarise_change(old_plan, weekly_plan_md, message)

    except TimeoutError:
        logger.error("Weekly re-plan timed out for user=%s", user_id)
        reply = "⏱ The re-planning took too long. Please try a simpler request."
    except Exception as exc:
        logger.exception("Weekly re-plan failed for user=%s: %s", user_id, exc)
        reply = f"❌ An error occurred while updating the plan: {exc!s}"

    history.append({"role": "assistant", "content": reply})

    return ChatResponse(reply=reply, plan_updated=plan_updated, history=history)


@app.delete("/chat/{user_id}/history")
async def clear_history(user_id: str) -> dict[str, str]:
    _conversation_history.pop(user_id, None)
    return {"status": "cleared", "user_id": user_id}
