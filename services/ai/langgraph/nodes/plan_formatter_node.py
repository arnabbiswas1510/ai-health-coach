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
- **Theme (Dark Mode by default)**: Use a premium dark theme matching GitHub/Garmin dashboards. Use background color `#0d1117` (or transparent if loaded in iframe), card background `rgba(22, 27, 34, 0.6)`, borders `rgba(240, 246, 252, 0.1)`, primary text `#c9d1d9`, secondary text `#8b949e`, and titles `#f0f6fc`. Ensure there are no white/light backgrounds, and no hardcoded dark text on dark backgrounds.

## Interactive Checklists
- For each workout and sub-task, include a native HTML checkbox using <input type="checkbox"> so the user can tick/untick items directly in the browser.
- Wrap each checkbox in a <label> (or associate via for/id) for tap-friendly, accessible interaction.
- Use meaningful name/value attributes (e.g., name="wk-2025-09-18-run" value="done") to support optional form submission.

## Section 2: Today's Autoregulated Workout
- **Today's Suggested Workout Hero Card**: Put today's suggested workout at the very top of Section 2 in a premium, high-impact hero card layout. Display Target Distance (km and converted miles), Target Duration (mins), Target Pace (min/km and converted min/mile), and Target HR Zone in large, highly readable text with icons or badges. **CRITICAL: NEVER use JavaScript to populate these workout metric values. Always parse the `{weekly_plan}` markdown yourself and hardcode ALL values directly as static text in the HTML. The metric boxes must never be empty — if a value is missing in the input, write 'TBD'.** Include the step-by-step segments (Warmup, Run/Walk intervals, Cooldown) as checklist items using `<input type="checkbox">` and `<label>`. Ensure that metric item blocks are allowed to wrap (`flex-wrap: wrap`) on all screen widths, preventing layout overflow/clipping when cards share rows in multi-column grids.
- **Garmin Recovery Check & Feedback Card**: Render a dedicated card displaying the athlete's key Garmin recovery indicators (Sleep overall score/quality, Overnight HRV, Average Stress, Weight) alongside their latest typed persistent feedback (e.g., soreness, fatigue, missed runs) and a summary of how the system scaled today's run.
- **7-Day Provisional Forecast Accordion**: Render the provisional 7-day forecast in a collapsible HTML `<details>` and `<summary>` element. When collapsed, the summary should display a clean title (e.g., "🔮 7-Day Provisional Forecast (Day 2 - 7)"). When expanded, it should show a neat day-by-day table/grid outlining Focus and provisional workouts. Include a clear disclaimer: *"Provisional — Will dynamically recalculate tomorrow based on your body's recovery."*

## Section 3: Retro - Review & Run Analysis
- **CRITICAL HTML Structure**: Section 3 MUST be wrapped in a container element (such as `<section>` or `<div>`) with the exact attribute `id="retro-analysis"` (e.g., `<section id="retro-analysis">`). This element must be a direct child of the main `.container` wrapper.
- **Season Progression & Alignment Card**: Include a beautiful strategic feedback card at the very top of Section 3 (inside `#retro-analysis`). This card compares completed volume against the Season Plan target, tracks aerobic pace-to-HR trends, flags Acute-to-Chronic Workload Ratio (ACWR) ratings, and provides macro strategic advice to keep the runner on track despite daily autoregulation adjustments.
- **Paginated Last 15 Runs Split Breakdown**:
  - Extract and present a detailed split-by-split breakdown for the last 15 running activities (newest first) based on the raw activities summary.
  - Implement client-side pagination (5 runs per page) using simple, highly performant inline vanilla JS and CSS. Write clean pagination controls (Previous, Page numbers, Next) styled beautifully. Active/inactive button states should have clear styling.
  - Page changes must use instant state switching (e.g., adding/removing a `.hidden` class with `display: none !important;` and a brief fade animation like `transition: opacity 0.2s;`).
  - For each of the 15 runs, display a card containing:
    - **Header info**: Date, Run Title/Name, Total Distance (km & converted miles), Total Duration, Avg HR.
    - **Interactive Split Breakdown Table**:
      - Columns: Lap #, Distance (show both km and converted miles, e.g. "1.00 km (0.62 mi)"), Split Time (min:sec), Pace (show both min/km and converted min/mile, e.g. "6:15/km (10:04/mi)"), Avg HR (bpm), and **Split Review**.
      - Under **Split Review**, analyze if it was a success:
        - Write "✅ Good Zone 2" (in green) if Avg HR is in Zone 2 (100 to 120 bpm, or under 120 bpm).
        - Write "⚠️ Pace Overshot / HR Spike" (in amber/red) if Avg HR is above 120 bpm (spiked into Zone 3/4) or if the pace was unsustainably fast.
        - Point out any cardiovascular drift (HR rising over subsequent splits despite steady/slower pace).
  - Ensure the table is responsive, visually clean, and adheres strictly to the premium dark mode styling.
  - **Robust Client-side JS Parsing**:
    - Handle variations in keys and table headers safely. Normalize headers by replacing non-alphanumeric characters (like slashes, spaces) with underscores, or explicitly check both `run.avg_pace` and `run['avg_pace/power']`.
    - Check if values exist before calling string methods like `.split()`, `.replace()`, etc. (e.g., `if (run && run.avg_pace) { ... } else { ... }`).
    - Parse raw activities table markdown lines using `split(/\r?\n/)` to handle CRLF and LF line endings correctly.
    - Provide fallback values (like "N/A" or "0:00") if any duration, pace, or heart rate values are missing or malformed, ensuring that a single parsing failure does not break the entire page loading or execution.
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
### Suggested Workout & Forecast
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
### Raw Activity Data & Splits
```markdown
{activity_summary}
```

## Task
Convert the markdown and analysis content into a single, self-contained HTML document.

## Constraints
- **Compactness**: The user must see the "big picture" easily. Avoid excessive scrolling.
- **Layout**: Use a premium, responsive layout (grid/cards) matching GitHub/Garmin dashboards.
- **Usability**: Include interactive checkboxes for every workout item.
- **Design**: Professional, athlete-focused aesthetic with clear visual hierarchy.

## Output Requirements
1. **Structure**:
    - Header: Athlete name and training horizon.
    - Section 1: Season Plan Overview (High level).
    - Section 2: Today's Autoregulated Workout (Suggested Run of the Day hero card + Garmin Recovery Check & Feedback card + Collapsible 7-Day Provisional Forecast accordion).
    - Section 3: Retro - Review & Run Analysis (Review and analysis of the runs done so far. This section MUST start with a Season Progression & Alignment strategic feedback card at the top, followed by the paginated split cards for the last 15 runs).
2. **Format**: Complete HTML5 document with embedded CSS.
3. **Content**: Preserve all workout and forecast details but format them densely.
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
                    physiology_analysis=get_expert_analysis("physiology_outputs"),
                    activity_summary=get_content("activity_summary")
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
