"""Formatter Node (analysis.html / Physiology & Metrics tab).

Asks the LLM for a structured JSON data object, then renders it into a
fully locked HTML page via analysis_template.render_analysis_html().

Look-and-feel (CSS, fonts, layout) never changes between analytics runs.
"""
import json
import logging
from datetime import datetime

from services.ai.ai_settings import AgentRole
from services.ai.langgraph.state.training_analysis_state import TrainingAnalysisState
from services.ai.model_config import ModelSelector
from services.ai.utils.retry_handler import AI_ANALYSIS_CONFIG, retry_with_backoff

from .analysis_template import ANALYSIS_JSON_SCHEMA, render_analysis_html
from .tool_calling_helper import extract_text_content

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

FORMATTER_SYSTEM_PROMPT = """\
You are a sports-science data extractor. Your sole job is to read an athlete
performance synthesis report and emit a single, valid JSON object that captures
all key data points. A Python renderer turns your JSON into HTML — you never
write HTML or CSS.

Status values for kpi_rows.status must be one of:
  optimal | ready | needs_improvement | behind_plan | target | neutral

Output format:
"""

FORMATTER_USER_PROMPT = """\
Produce the JSON data object for this athlete's physiology & metrics report.

### Synthesis Report
{synthesis_result}

{schema}

Remember: return ONLY valid JSON, no markdown fences, no extra text.
"""

FORMATTER_PLOT_NOTE = """\
Note: if the synthesis report contains [PLOT:plot_id] references, include the
text "[PLOT:plot_id]" verbatim inside the relevant deep_dive_sections body string.
"""


# ---------------------------------------------------------------------------
# JSON parsing (same helper as plan_formatter)
# ---------------------------------------------------------------------------

def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _parse_json_safely(raw: str) -> dict | None:
    try:
        return json.loads(_strip_fences(raw))
    except json.JSONDecodeError:
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

async def formatter_node(state: TrainingAnalysisState) -> dict[str, list | str]:
    logger.info("Starting HTML formatter node (template-based)")

    try:
        plotting_enabled = state.get("plotting_enabled", False)
        logger.info(
            "Formatter node: Plotting %s",
            "enabled" if plotting_enabled else "disabled",
        )

        agent_start_time = datetime.now()

        athlete_name = state.get("athlete_name", "Athlete")
        current_date_raw = state.get("current_date", {})
        current_date_str = (
            current_date_raw.get("date", datetime.now().strftime("%Y-%m-%d"))
            if isinstance(current_date_raw, dict)
            else str(current_date_raw)
        )

        synthesis_result = extract_text_content(state.get("synthesis_result", ""))

        system_prompt = FORMATTER_SYSTEM_PROMPT + ANALYSIS_JSON_SCHEMA
        user_prompt = FORMATTER_USER_PROMPT.format(
            synthesis_result=synthesis_result,
            schema=ANALYSIS_JSON_SCHEMA,
        ) + (FORMATTER_PLOT_NOTE if plotting_enabled else "")

        async def call_llm():
            response = await ModelSelector.get_llm(AgentRole.FORMATTER).ainvoke([
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ])
            return extract_text_content(response)

        raw_response = await retry_with_backoff(call_llm, AI_ANALYSIS_CONFIG, "Analysis Formatter JSON")

        data = _parse_json_safely(raw_response)

        if data is None:
            logger.error(
                "Formatter node: LLM did not return valid JSON. "
                "Raw response (first 500 chars): %s",
                raw_response[:500],
            )
            data = {
                "athlete_name": athlete_name,
                "generated_at": current_date_str,
                "page_title": f"{athlete_name} Physiology & Metrics",
                "report_period": datetime.now().strftime("%B %Y"),
                "executive_summary": "Analysis data could not be parsed this run. Please retry.",
                "kpi_rows": [],
                "deep_dive_sections": [],
                "recommendations": [],
            }

        data.setdefault("athlete_name", athlete_name)
        data.setdefault("generated_at", current_date_str)

        analysis_html = render_analysis_html(data)

        execution_time = (datetime.now() - agent_start_time).total_seconds()
        logger.info("HTML formatting completed in %.2fs", execution_time)

        return {
            "analysis_html": analysis_html,
            "costs": [
                {
                    "agent": "formatter",
                    "execution_time": execution_time,
                    "timestamp": datetime.now().isoformat(),
                }
            ],
        }

    except Exception as exc:
        logger.exception("Formatter node failed")
        return {"errors": [f"HTML formatting failed: {exc!s}"]}
