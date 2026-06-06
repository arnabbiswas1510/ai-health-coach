import logging
from datetime import datetime

from services.ai.ai_settings import AgentRole
from services.ai.langgraph.state.training_analysis_state import TrainingAnalysisState
from services.ai.model_config import ModelSelector
from services.ai.utils.retry_handler import AI_ANALYSIS_CONFIG, retry_with_backoff

from .tool_calling_helper import extract_text_content

logger = logging.getLogger(__name__)

PLAN_FORMATTER_SYSTEM_PROMPT = """You are a data visualization specialist.
## Goal
Transform training plans and expert analysis into beautiful, functional HTML documents.
## Principles
- Clarity: Make complex training information immediately accessible.
- Hierarchy: Use visual structure to guide attention.
- Usability: Design for both desktop planning and mobile execution.
- Aesthetics: Create a professional, athlete-focused visual experience.

## Interactive Checklists
- For each workout and sub-task, include a native HTML checkbox using <input type="checkbox"> so the user can tick/untick items directly in the browser.
- Wrap each checkbox in a <label> (or associate via for/id) for tap-friendly, accessible interaction.
- Use meaningful name/value attributes (e.g., name="wk-2025-09-18-run" value="done") to support optional form submission.

## Section 3: Retro - Review & Run Analysis
- Focus: Highlight the athlete's recent runs and their overall impact on fitness and readiness.
- Run Impact: Clearly describe the impact of recent runs on metrics (e.g., overshooting Z2 HR, cardiovascular load, VO2 max changes, recovery levels).
- Analysis: Break down "What went right" (e.g., good pacing on treadmill, strict Z2 adherence) versus "What was unnecessary/overshot" (e.g., running too fast outdoors, spiking heart rate to Zone 3/4).
- Future Recommendations: Detail actionable advice on how to improve next runs (e.g., walk-run ratios, pacing rules, HR alarms).
- Retro Styling: Style Section 3 with a beautiful retro-modern card layout (e.g., warm background accents, structured alert cards, positive green markers for right actions, amber/red warning indicators for overshoots, and clear icons). Ensure it matches the overall professional layout and visual aesthetic of the page.
"""

PLAN_FORMATTER_USER_PROMPT = """Transform the training plan and activity analysis into a professional HTML document.

## Inputs
### Season Plan
```markdown
{season_plan}
```
### 4-Week Plan
```markdown
{weekly_plan}
```
### Activity Expert Analysis
```markdown
{activity_analysis}
```
### Metrics Expert Analysis
```markdown
{metrics_analysis}
```
### Physiology Expert Analysis
```markdown
{physiology_analysis}
```

## Task
Convert the markdown and analysis content into a single, self-contained HTML document.

## Constraints
- **Compactness**: The user must see the "big picture" easily. Avoid excessive scrolling.
- **Layout**: Use a dense, information-rich layout (e.g., grid or compact cards) for the 4-week plan.
- **Usability**: Include interactive checkboxes for every workout item.
- **Design**: Professional, athlete-focused aesthetic with clear visual hierarchy.

## Output Requirements
1. **Structure**:
   - Header: Athlete name and period.
   - Section 1: Season Plan Overview (High level).
   - Section 2: 4-Week Plan (Detailed but compact).
   - Section 3: Retro - Review & Run Analysis (Review and analysis of the runs done so far: what impact the last n runs had on fitness, what was done right, what was unnecessary, and suggested future improvements based on the expert analysis).
2. **Format**: Complete HTML5 document with embedded CSS.
3. **Content**: Preserve all workout details but format them densely.
4. **Return**: ONLY the HTML code.
"""


async def plan_formatter_node(state: TrainingAnalysisState) -> dict[str, list | str]:  # noqa: C901
    logger.info("Starting plan formatter node")

    try:
        agent_start_time = datetime.now()

        def get_content(field):
            value = state.get(field, "")
            if hasattr(value, "output"):
                output = value.output
                if isinstance(output, str):
                    return output
                raise ValueError("AgentOutput contains questions, not content. HITL interaction required.")
            if isinstance(value, dict):
                return value.get("output", value.get("content", value))
            return value

        from services.ai.langgraph.utils.output_helper import extract_expert_output

        def get_expert_analysis(key, target_field="for_weekly_planner"):
            val = state.get(key)
            if not val:
                return "No analysis data available."
            try:
                return extract_expert_output(val, target_field)
            except Exception as exc:
                logger.warning("Could not extract expert output for %s: %s", key, exc)
                return str(val)

        async def call_plan_formatting():
            response = await ModelSelector.get_llm(AgentRole.FORMATTER).ainvoke([
                {"role": "system", "content": PLAN_FORMATTER_SYSTEM_PROMPT},
                {"role": "user", "content": PLAN_FORMATTER_USER_PROMPT.format(
                    season_plan=get_content("season_plan"),
                    weekly_plan=get_content("weekly_plan"),
                    activity_analysis=get_expert_analysis("activity_outputs"),
                    metrics_analysis=get_expert_analysis("metrics_outputs"),
                    physiology_analysis=get_expert_analysis("physiology_outputs")
                )},
            ])
            return extract_text_content(response)

        planning_html = await retry_with_backoff(
            call_plan_formatting, AI_ANALYSIS_CONFIG, "Plan Formatter"
        )

        if planning_html:
            planning_html = planning_html.strip()
            if planning_html.startswith("```"):
                lines = planning_html.splitlines()
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                planning_html = "\n".join(lines).strip()

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
