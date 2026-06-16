"""Plan Formatter Node.

Asks the LLM for a structured JSON data object describing the training plan,
then renders it into a fully locked HTML page via planning_template.render_planning_html().

This guarantees that look-and-feel (CSS, fonts, layout, JS) never changes
between analytics runs — only the training-specific content changes.
"""
import json
import logging
from datetime import datetime

from services.ai.ai_settings import AgentRole
from services.ai.langgraph.state.training_analysis_state import TrainingAnalysisState
from services.ai.model_config import ModelSelector
from services.ai.utils.retry_handler import AI_ANALYSIS_CONFIG, retry_with_backoff

from .planning_template import PLANNING_JSON_SCHEMA, render_planning_html
from .tool_calling_helper import extract_text_content

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

PLAN_FORMATTER_SYSTEM_PROMPT = """\
You are a sports-science data extractor. Your sole job is to read raw training
plan text and expert analysis, then emit a single, valid JSON object that
captures all key data points. A separate Python renderer will turn your JSON
into a beautiful HTML page — you never write HTML or CSS.

## Theme reference (for status labeling only)
Zone 2 HR is the target aerobic training zone. Readiness colors:
  green  = excellent recovery, ready to train hard
  yellow = moderate — train but be cautious
  red    = poor recovery — scale down or rest

## Output format
"""

PLAN_FORMATTER_USER_PROMPT = """\
Produce the JSON data object for this athlete's training dashboard.

### Athlete
Name: {athlete_name}
Date: {current_date}
Zone 2 range: {z2_low}–{z2_high} bpm

### Season Plan
{season_plan}

### Today's Suggested Workout & Forecast
{weekly_plan}

### Activity Expert Analysis
{activity_analysis}

### Metrics Expert Analysis
{metrics_analysis}

### Physiology Expert Analysis
{physiology_analysis}

### Raw Activity Data & Splits (for recent_runs)
{activity_summary}

{schema}

Remember: return ONLY valid JSON, no markdown fences, no extra text.
"""


# ---------------------------------------------------------------------------
# JSON parsing with fallback
# ---------------------------------------------------------------------------

def _strip_fences(text: str) -> str:
    """Remove ```json ... ``` or ``` ... ``` wrappers if present."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        # drop first and last fence lines
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _parse_json_safely(raw: str) -> dict | None:
    """Try to parse LLM output as JSON; return None on failure."""
    try:
        return json.loads(_strip_fences(raw))
    except json.JSONDecodeError:
        # Try to find the first '{' and last '}' and parse that substring
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(raw[start : end + 1])
            except json.JSONDecodeError:
                pass
    return None


# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------

async def plan_formatter_node(state: TrainingAnalysisState) -> dict[str, list | str]:  # noqa: C901
    logger.info("Starting plan formatter node (template-based)")

    try:
        agent_start_time = datetime.now()

        # ── Extract Zone 2 bounds ──────────────────────────────────────────
        garmin_data = state.get("garmin_data", {})
        user_profile = garmin_data.get("user_profile", {}) if isinstance(garmin_data, dict) else {}
        z2_low = 100
        z2_high = 120
        if isinstance(user_profile, dict):
            z2_low = user_profile.get("zone2_low", z2_low)
            z2_high = user_profile.get("zone2_high", z2_high)

        # ── Helper extractors ──────────────────────────────────────────────
        def get_content(field):
            value = state.get(field, "")
            if hasattr(value, "output"):
                output = value.output
                if isinstance(output, str):
                    return output
                raise ValueError("AgentOutput contains questions; HITL required.")
            if isinstance(value, dict):
                return value.get("output", value.get("content", value))
            return value or ""

        from services.ai.langgraph.utils.output_helper import extract_expert_output

        def get_expert(key, target="for_weekly_planner"):
            val = state.get(key)
            if not val:
                return "No analysis available."
            try:
                return extract_expert_output(val, target)
            except Exception as exc:
                logger.warning("Could not extract expert output for %s: %s", key, exc)
                return str(val)

        # ── Build prompt ───────────────────────────────────────────────────
        athlete_name = state.get("athlete_name", "Athlete")
        current_date_raw = state.get("current_date", {})
        current_date_str = (
            current_date_raw.get("date", datetime.now().strftime("%Y-%m-%d"))
            if isinstance(current_date_raw, dict)
            else str(current_date_raw)
        )

        system_prompt = PLAN_FORMATTER_SYSTEM_PROMPT + PLANNING_JSON_SCHEMA

        user_prompt = PLAN_FORMATTER_USER_PROMPT.format(
            athlete_name=athlete_name,
            current_date=current_date_str,
            z2_low=z2_low,
            z2_high=z2_high,
            season_plan=get_content("season_plan"),
            weekly_plan=get_content("weekly_plan"),
            activity_analysis=get_expert("activity_outputs"),
            metrics_analysis=get_expert("metrics_outputs"),
            physiology_analysis=get_expert("physiology_outputs"),
            activity_summary=get_content("activity_summary"),
            schema=PLANNING_JSON_SCHEMA,
        )

        # ── Call LLM ───────────────────────────────────────────────────────
        async def call_llm():
            response = await ModelSelector.get_llm(AgentRole.FORMATTER).ainvoke([
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ])
            return extract_text_content(response)

        raw_response = await retry_with_backoff(call_llm, AI_ANALYSIS_CONFIG, "Plan Formatter JSON")

        # ── Parse JSON & render ────────────────────────────────────────────
        data = _parse_json_safely(raw_response)

        if data is None:
            logger.error(
                "Plan formatter: LLM did not return valid JSON. "
                "Raw response (first 500 chars): %s",
                raw_response[:500],
            )
            # Minimal fallback so the page is not blank
            data = {
                "athlete_name": athlete_name,
                "generated_at": current_date_str,
                "page_title": f"{athlete_name} Training Dashboard",
                "season_phase": "—",
                "season_overview": "Analysis data could not be parsed this run. Please retry.",
                "season_milestones": [],
                "today_metrics": {
                    "workout_type": "See weekly plan",
                    "distance_km": "TBD", "distance_miles": "TBD",
                    "duration": "TBD", "pace_km": "TBD",
                    "pace_miles": "TBD", "hr_zone": f"Zone 2 ({z2_low}–{z2_high} bpm)",
                },
                "workout_steps": [],
                "why_prescription": "Data unavailable — please re-run the coach.",
                "recovery_indicators": {
                    "sleep": "—", "hrv": "—", "rhr": "—",
                    "stress": "—", "weight": "—",
                    "readiness_label": "Unknown", "readiness_color": "yellow",
                },
                "adaptation_message": "",
                "forecast_days": [],
                "season_progression": "",
                "weight_accountability": {
                    "start_weight": "—", "target_weight": "—", "current_weight": "—",
                    "deviation": "—", "status": "neutral", "coaching_message": "—",
                },
                "recent_runs": [],
            }

        # Ensure required top-level defaults
        data.setdefault("athlete_name", athlete_name)
        data.setdefault("generated_at", current_date_str)

        planning_html = render_planning_html(data)

        execution_time = (datetime.now() - agent_start_time).total_seconds()
        logger.info("Plan formatting completed in %.2fs", execution_time)

        return {
            "planning_html": planning_html,
            "costs": [
                {
                    "agent": "plan_formatter",
                    "execution_time": execution_time,
                    "timestamp": datetime.now().isoformat(),
                }
            ],
        }

    except Exception as exc:
        logger.exception("Plan formatter node failed")
        return {"errors": [f"Plan formatting failed: {exc!s}"]}
