import json
import logging
from datetime import datetime

from services.ai.ai_settings import AgentRole
from services.ai.langgraph.schemas import CombinedSummaryOutputs
from services.ai.langgraph.state.training_analysis_state import TrainingAnalysisState
from services.ai.model_config import ModelSelector
from services.ai.utils.retry_handler import AI_ANALYSIS_CONFIG, retry_with_backoff

from .tool_calling_helper import extract_text_content

logger = logging.getLogger(__name__)

COMBINED_SUMMARIZER_SYSTEM_PROMPT = """## Goal
Preserve decision-relevant metrics from raw data with transparent compression for three domains: Metrics, Physiology, and Activity.

## Principles
- Preserve: Keep meaningful numbers (measurements, counts, rates) that affect downstream decisions.
- Detect: Distinguish signal (measurements) from noise (IDs, nulls).
- Organize: Use tables and lists with clear time windows.
- Transparent Compression: You MAY compress long sequences if you show how and where.
- No Hidden Aggregation: If you summarize a sequence, expose the values or an explicit table of windows.
- Factual only: Do NOT interpret or speculate.

## Domain Guidelines

### 1. Metrics Summarizer
- Input: `garmin_data` keys like `training_load_history`, `vo2_max_history`, `training_status`, `long_term_vo2_max_trend`.
- Focus: Summarize daily training load history, VO2 max history, training status, and VO2 max trends.

### 2. Physiology Summarizer
- Input: `garmin_data` keys like `recovery_indicators` (sleep, stress) and `physiological_markers` (HRV, body metrics).
- Focus: Summarize HRV data, sleep data, stress data, body metrics, and recovery indicators.

### 3. Activity Summarizer
- Input: `garmin_data` keys like `recent_activities`.
- Focus: Objectively describe recent training activities.
- Required Structure:
  - All Activities Table: compact table for every activity (date, type, duration, distance, elevation, avg HR, avg pace/power).
  - Key Sessions: deep dives ONLY for key sessions (intensity/novelty/anomaly).
  - Zone Distributions: summarize distributions in tables.
  - Last 15 Runs Split Breakdown: Provide a separate section for each of the last 15 runs (newest first). Include the date, name, overall distance/time/HR/pace, and a markdown table detailing every split/lap from Garmin.

## Final Checklist
- Factual only (no interpretation).
- Transparent compression (no hidden aggregation).
- Decision-relevant numbers prioritized.
"""

COMBINED_SUMMARIZER_USER_PROMPT = """## Task
Extract and organize decision-relevant metrics from this raw Garmin data.
Produce three distinct summaries: Metrics, Physiology, and Activity.

## Constraints
- Do NOT interpret or speculate.
- Exclude repeated nulls and structural IDs.
- You MAY compress long sequences, but show how (windows, ranges, or tables).

## Input Data
```json
{data}
```

Format the output strictly as the requested structured schema with:
1. `metrics` (markdown)
2. `physiology` (markdown)
3. `activity` (markdown)
"""

def extract_combined_data(state: TrainingAnalysisState) -> dict:
    garmin_data = state.get("garmin_data", {})
    recovery_indicators = garmin_data.get("recovery_indicators", [])
    physiological_markers = garmin_data.get("physiological_markers", {})

    return {
        "metrics": {
            "training_load_history": garmin_data.get("training_load_history", []),
            "vo2_max_history": garmin_data.get("vo2_max_history", {}),
            "training_status": garmin_data.get("training_status", {}),
            "long_term_vo2_max_trend": garmin_data.get("long_term_vo2_max_trend", {}),
        },
        "physiology": {
            "hrv_data": physiological_markers.get("hrv", {}),
            "sleep_data": [ind["sleep"] for ind in recovery_indicators if ind.get("sleep")],
            "stress_data": [ind["stress"] for ind in recovery_indicators if ind.get("stress")],
            "recovery_metrics": {
                "physiological_markers": physiological_markers,
                "body_metrics": garmin_data.get("body_metrics", {}),
                "recovery_indicators": recovery_indicators,
            },
        },
        "activity": garmin_data.get("recent_activities", []),
    }

async def combined_summarizer_node(state: TrainingAnalysisState) -> dict[str, list | str]:
    logger.info("Starting Combined Summarizer node")
    node_name = "Combined Summarizer"

    try:
        agent_start_time = datetime.now()
        data_to_summarize = extract_combined_data(state)

        base_llm = ModelSelector.get_llm(AgentRole.COMBINED_SUMMARIZER)
        llm_with_structure = base_llm.with_structured_output(CombinedSummaryOutputs)

        async def call_llm():
            response = await llm_with_structure.ainvoke(
                [
                    {"role": "system", "content": COMBINED_SUMMARIZER_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": COMBINED_SUMMARIZER_USER_PROMPT.format(
                            data=json.dumps(data_to_summarize, indent=2)
                        ),
                    },
                ]
            )
            return response

        result = await retry_with_backoff(
            call_llm, AI_ANALYSIS_CONFIG, node_name
        )

        execution_time = (datetime.now() - agent_start_time).total_seconds()
        logger.info("Combined Summarizer completed in %.2fs", execution_time)

        return {
            "metrics_summary": result.metrics,
            "physiology_summary": result.physiology,
            "activity_summary": result.activity,
            "costs": [
                {
                    "agent": "combined_summarizer",
                    "execution_time": execution_time,
                    "timestamp": datetime.now().isoformat(),
                }
            ],
        }

    except Exception as exc:
        logger.error("Combined Summarizer node failed: %s", exc)
        return {"errors": [f"Combined Summarizer failed: {exc}"]}
