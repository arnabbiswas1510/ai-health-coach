import json
import logging
from datetime import datetime

from services.ai.ai_settings import AgentRole
from services.ai.langgraph.schemas import (
    ActivityExpertOutputs,
    CombinedAnalystOutputs,
    MetricsExpertOutputs,
    PhysiologyExpertOutputs,
)
from services.ai.langgraph.state.training_analysis_state import TrainingAnalysisState
from services.ai.langgraph.utils.message_helper import normalize_langchain_messages
from services.ai.model_config import ModelSelector
from services.ai.tools.plotting import PlotStorage
from services.ai.utils.retry_handler import AI_ANALYSIS_CONFIG, retry_with_backoff

from .node_base import (
    configure_node_tools,
    create_cost_entry,
    create_plot_entries,
    execute_node_with_error_handling,
    log_node_completion,
)
from .prompt_components import (
    get_plotting_instructions,
    get_workflow_context,
)
from .tool_calling_helper import handle_tool_calling_in_node

logger = logging.getLogger(__name__)

COMBINED_ANALYST_SYSTEM_PROMPT_BASE = """## Goal
Analyze training metrics, physiology, and activity execution with data-driven precision, and synthesize these insights into a comprehensive athletic report.

## Domain 1: Metrics Expert (Global Stimulus)
Analyze training load patterns, fitness trends, and readiness.
### EWMA metrics (smooth, responsive)
- **Acute EWMA (7d)**: short-term load (fatigue proxy).
- **Chronic EWMA (28d)**: longer-term load (fitness/preparedness proxy).
- **Shifted Chronic EWMA (t-7)**: chronic EWMA evaluated 7 days earlier.
- **ACWR (EWMA shifted)**: Acute EWMA / Shifted Chronic EWMA (spike indicator).
- **Risk Index**: ln(ACWR) (symmetric measure of doubling/halving).
- **TSB**: Chronic EWMA - Acute EWMA (negative = accumulating fatigue).
- **Ramp Rate (7d)**: change in Chronic EWMA vs 7 days ago.
- **Monotony (7d)**: mean(daily load over last 7d) / SD(last 7d).
- **Strain (7d)**: (total weekly load) x Monotony.
### Rolling-sum metrics (Garmin-comparable scale)
- **Acute 7d Sum**: sum of daily loads over last 7 days.
- **Chronic 28d Avg (of Acute 7d Sum)**: average of the last 28 values of Acute 7d Sum.
- **ACWR 7d/28d (coupled)**: Acute 7d Sum / Chronic 28d Avg.
- **ACWR 7d/28d (uncoupled)**: Acute 7d Sum / Chronic 28d Avg computed up to (t-7), excluding the most recent week.

## Domain 2: Physiology Expert (Internal Response)
Optimize recovery and adaptation. Assess body metrics, sleep, HRV, resting heart rate, and stress. Identify recovery windows and stress costs.

## Domain 3: Activity Expert (Workout Execution)
Interpret activity summaries to optimize workout progression patterns. Detect execution details, zone distributions, and split performance from key sessions.

## Domain 4: Synthesis (Integrated Athlete Report)
Connect load (metrics), execution (activity), and response (physiology). Spot patterns in performance and adaptation. Create a coherent story.
"""

COMBINED_ANALYST_USER_PROMPT = """## Task
Perform a comprehensive athletic analysis across Metrics, Physiology, and Activity domains, and write the final integrated synthesis.

## Inputs
### Athlete Profile & Weight Goals
{weight_context}

### Metrics Summary
{metrics_summary}

### Physiology Summary
{physiology_summary}

### Activity Summary
{activity_summary}

### Context
- Competitions: ```json {competitions} ```
- Date: ```json {current_date} ```
- Style Guide: ```markdown {style_guide} ```
- **User Context**: ``` {analysis_context} ```

## Output Requirements
Generate the structured output matching the schema.
For each domain (`metrics`, `physiology`, `activity`), populate the three receiver fields (`for_synthesis`, `for_season_planner`, `for_weekly_planner`).
For EACH receiver field, populate:
- **Signals**: what changed (concise)
- **Evidence**: numbers + date ranges
- **Implications**: constraints/opportunities for this receiver
- **Uncertainty**: gaps/low coverage if any

For the `synthesis` field, write the final Integrated Athlete Report:
1. **Executive Summary**: High-level status and key takeaways.
2. **Key Performance Indicators**: Table format.
3. **Deep Dive**: Structured sections with clear headings.
4. **Recommendations**: Brief and actionable.
5. **Tone**: Professional, evidence-based, encouraging.
"""

async def combined_analyst_node(state: TrainingAnalysisState) -> dict[str, list | str | dict]:
    logger.info("Starting Combined Analyst node")
    node_name = "Combined Analyst"

    plot_storage = PlotStorage(state["execution_id"])
    plotting_enabled = state.get("plotting_enabled", False)

    logger.info(
        "Combined analyst: Plotting %s",
        "enabled" if plotting_enabled else "disabled",
    )

    tools = configure_node_tools(
        agent_name="combined_analyst",
        plot_storage=plot_storage,
        plotting_enabled=plotting_enabled,
    )

    system_prompt = (
        COMBINED_ANALYST_SYSTEM_PROMPT_BASE
        + (get_plotting_instructions("combined_analyst") if plotting_enabled else "")
    )

    base_llm = ModelSelector.get_llm(AgentRole.COMBINED_ANALYST)
    llm_with_tools = base_llm.bind_tools(tools) if tools else base_llm
    llm_with_structure = llm_with_tools.with_structured_output(CombinedAnalystOutputs)

    agent_start_time = datetime.now()

    async def call_analyst_with_tools():
        base_messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": COMBINED_ANALYST_USER_PROMPT.format(
                    weight_context=state.get("weight_context", ""),
                    metrics_summary=state.get("metrics_summary", "No metrics summary available"),
                    physiology_summary=state.get("physiology_summary", "No physiology summary available"),
                    activity_summary=state.get("activity_summary", "No activity summary available"),
                    competitions=json.dumps(state["competitions"], indent=2),
                    current_date=json.dumps(state["current_date"], indent=2),
                    style_guide=state.get("style_guide", ""),
                    analysis_context=state["analysis_context"],
                ),
            },
        ]

        # In this combined node, we don't have separate hitl messages for the combined agent
        # but we can fallback or handle if needed. We do not use it for now.
        return await handle_tool_calling_in_node(
            llm_with_tools=llm_with_structure,
            messages=base_messages,
            tools=tools,
            max_iterations=15,
        )

    async def node_execution():
        agent_output = await retry_with_backoff(
            call_analyst_with_tools, AI_ANALYSIS_CONFIG, "Combined Analyst with Tools"
        )
        logger.info("Combined Analyst completed")

        execution_time = (datetime.now() - agent_start_time).total_seconds()

        plots, plot_storage_data, available_plots = create_plot_entries("combined_analyst", plot_storage)

        log_node_completion("Combined analyst", execution_time, len(available_plots))

        return {
            "metrics_outputs": MetricsExpertOutputs(output=agent_output.metrics),
            "physiology_outputs": PhysiologyExpertOutputs(output=agent_output.physiology),
            "activity_outputs": ActivityExpertOutputs(output=agent_output.activity),
            "synthesis_result": agent_output.synthesis,
            "synthesis_complete": True,
            "plots": plots,
            "plot_storage_data": plot_storage_data,
            "costs": [create_cost_entry("combined_analyst", execution_time)],
            "available_plots": available_plots,
        }

    return await execute_node_with_error_handling(
        node_name="Combined Analyst",
        node_function=node_execution,
        error_message_prefix="Combined Analyst failed",
    )
