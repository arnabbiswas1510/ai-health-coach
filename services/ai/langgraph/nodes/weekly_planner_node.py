import json
import logging
from datetime import datetime

from services.ai.ai_settings import AgentRole
from services.ai.langgraph.schemas import AgentOutput
from services.ai.langgraph.state.training_analysis_state import TrainingAnalysisState
from services.ai.langgraph.utils.message_helper import normalize_langchain_messages
from services.ai.langgraph.utils.output_helper import extract_agent_content, extract_expert_output
from services.ai.model_config import ModelSelector
from services.ai.utils.retry_handler import AI_ANALYSIS_CONFIG, retry_with_backoff

from .node_base import (
    configure_node_tools,
    create_cost_entry,
    execute_node_with_error_handling,
    log_node_completion,
)
from .prompt_components import get_hitl_instructions, get_workflow_context
from .tool_calling_helper import handle_tool_calling_in_node

logger = logging.getLogger(__name__)

WEEKLY_PLANNER_SYSTEM_PROMPT = """## Goal
Create detailed, practical training plans that balance stress and recovery.
## Principles
- Adaptation: Progressive overload with adequate recovery.
- Specificity: Training must match the demands of the event.
- Individualization: Adapt to the athlete's current state and history."""

WEEKLY_PLANNER_USER_PROMPT = """## Task
Create today's custom, autoregulated running workout prescription and a provisional 7-day training forecast.

## Constraints
- **Prioritize Athlete Feedback**: Carefully check the "Recent athlete feedback & coaching history" inside the **User Context** (e.g. sore muscles, busy day, missed runs). Make this the primary constraint when prescribing today's run.
  - If they mention soreness, injury risk, or severe fatigue: scale down the volume/intensity significantly, or prescribe a rest day.
  - If they missed a run due to a busy schedule: do not overcompensate with excessive volume. Hold steady or adjust.
- **Respect Physiological Readiness**: Check the Metrics, Activity, and Physiology Expert analyses (sleep duration, sleep quality, stress levels, HRV, ACWR). Scale today's run according to their warnings or limits.
- **Today's Run Focus**: Focus heavily on Base Building / Zone 2 running, walk-run intervals, or active recovery as appropriate.

## Inputs
### Season Plan
```markdown
{season_plan}
```
### Athlete Context
- Name: {athlete_name}
- Date: ```json {current_date} ```
- Upcoming Weeks: ```json {week_dates} ```
- Competitions: ```json {competitions} ```
- **User Context**: ``` {planning_context} ```
- **Athlete Profile & Weight Goals**: {weight_context}

### Expert Analysis
- Metrics: ``` {metrics_analysis} ```
- Activity: ``` {activity_analysis} ```
- Physiology: ``` {physiology_analysis} ```

## Output Requirements
Your output MUST contain exactly two sections:

1. **NEXT WORKOUT (Run of the Day)**:
   - **Workout Details**: Target Distance (km), Target Duration (mins), Target Pace (min/km), Target HR Zone.
   - **Structured segments**: Step-by-step instructions (Warmup, Run/Walk intervals, Cooldown).
   - **Purpose**: Why this workout is prescribed today.
   - **Why This Prescription? (Autoregulation Check)**: A dedicated explanation of how the user's Garmin recovery metrics (Sleep score, stress, HRV) AND their typed feedback (soreness, busy schedule) directly determined this workout's structure, pacing, or distance.

2. **7-DAY PROVISIONAL FORECAST**:
   - Provide a concise day-by-day outline for the next 7 days (Day 2 to Day 7).
   - For each day, list Day, Date, Focus (e.g. Z2 Aerobic, Strength, Rest), and a very brief provisional workout.
   - Explicitly add this disclaimer at the top of the forecast: *"Provisional — Will dynamically recalculate tomorrow based on your body's recovery."*
"""

WEEKLY_PLANNER_FINAL_CHECKLIST = """
## Final Checklist
- Generate only the Next Workout and a 7-day provisional forecast.
- Factor in and directly respond to the athlete's latest feedback/comments in the planning context.
- Adhere strictly to the physiological limits specified by the experts.
- Keep output concise and structured.
"""


async def weekly_planner_node(state: TrainingAnalysisState) -> dict[str, list | str]:
    logger.info("Starting weekly planner node")

    hitl_enabled = state.get("hitl_enabled", True)
    logger.info("Weekly planner node: HITL %s", "enabled" if hitl_enabled else "disabled")

    agent_start_time = datetime.now()

    tools = configure_node_tools(
        agent_name="weekly_planner",
        plot_storage=None,
        plotting_enabled=False,
    )

    system_prompt = (
        get_workflow_context("weekly_planner")
        + WEEKLY_PLANNER_SYSTEM_PROMPT
        + (get_hitl_instructions("weekly_planner") if hitl_enabled else "")
        + WEEKLY_PLANNER_FINAL_CHECKLIST
    )

    qa_messages = normalize_langchain_messages(state.get("weekly_planner_messages", []))
    user_message = {
        "role": "user",
        "content": WEEKLY_PLANNER_USER_PROMPT.format(
            season_plan=extract_agent_content(state.get("season_plan")),
            athlete_name=state["athlete_name"],
            current_date=json.dumps(state["current_date"], indent=2),
            week_dates=json.dumps(state["week_dates"], indent=2),
            competitions=json.dumps(state["competitions"], indent=2),
            planning_context=state["planning_context"],
            metrics_analysis=extract_expert_output(state.get("metrics_outputs"), "for_weekly_planner"),
            activity_analysis=extract_expert_output(state.get("activity_outputs"), "for_weekly_planner"),
            physiology_analysis=extract_expert_output(state.get("physiology_outputs"), "for_weekly_planner"),
            weight_context=state.get("weight_context", ""),
        ),
    }
    base_messages = [{"role": "system", "content": system_prompt}, user_message]

    base_llm = ModelSelector.get_llm(AgentRole.WORKOUT)
    llm_with_tools = base_llm.bind_tools(tools) if tools else base_llm
    llm_with_structure = llm_with_tools.with_structured_output(AgentOutput)

    async def call_weekly_planning():
        messages_with_qa = base_messages + qa_messages
        if tools:
            return await handle_tool_calling_in_node(
                llm_with_tools=llm_with_structure,
                messages=messages_with_qa,
                tools=tools,
                max_iterations=15,
            )
        return await llm_with_structure.ainvoke(messages_with_qa)

    async def node_execution():
        agent_output = await retry_with_backoff(
            call_weekly_planning, AI_ANALYSIS_CONFIG, "Weekly Planning"
        )

        execution_time = (datetime.now() - agent_start_time).total_seconds()
        log_node_completion("Weekly planning", execution_time)

        return {
            "weekly_plan": agent_output.model_dump(),
            "costs": [create_cost_entry("weekly_planner", execution_time)],
        }

    return await execute_node_with_error_handling(
        node_name="Weekly planner",
        node_function=node_execution,
        error_message_prefix="Weekly planning failed",
    )
