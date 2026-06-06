import logging
from datetime import datetime
from typing import Any, cast

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from services.ai.langgraph.config.langsmith_config import LangSmithConfig
from services.ai.langgraph.nodes.activity_expert_node import activity_expert_node
from services.ai.langgraph.nodes.activity_summarizer_node import activity_summarizer_node
from services.ai.langgraph.nodes.data_integration_node import data_integration_node
from services.ai.langgraph.nodes.formatter_node import formatter_node
from services.ai.langgraph.nodes.metrics_expert_node import metrics_expert_node
from services.ai.langgraph.nodes.metrics_summarizer_node import metrics_summarizer_node
from services.ai.langgraph.nodes.orchestrator_node import master_orchestrator_node
from services.ai.langgraph.nodes.physiology_expert_node import physiology_expert_node
from services.ai.langgraph.nodes.physiology_summarizer_node import physiology_summarizer_node
from services.ai.langgraph.nodes.plan_formatter_node import plan_formatter_node
from services.ai.langgraph.nodes.plot_resolution_node import plot_resolution_node
from services.ai.langgraph.nodes.season_planner_node import season_planner_node
from services.ai.langgraph.nodes.synthesis_node import synthesis_node
from services.ai.langgraph.nodes.weekly_planner_node import weekly_planner_node
from services.ai.langgraph.state.training_analysis_state import TrainingAnalysisState, create_initial_state
from services.ai.langgraph.utils.workflow_cost_tracker import ProgressIntegratedCostTracker

logger = logging.getLogger(__name__)


def create_planning_workflow():
    LangSmithConfig.setup_langsmith()

    workflow = StateGraph(TrainingAnalysisState)

    workflow.add_node("season_planner", season_planner_node)
    workflow.add_node("master_orchestrator", master_orchestrator_node)
    workflow.add_node("data_integration", data_integration_node)
    workflow.add_node("weekly_planner", weekly_planner_node)
    workflow.add_node("plan_formatter", plan_formatter_node)

    workflow.add_edge(START, "season_planner")
    workflow.add_edge("season_planner", "master_orchestrator")

    workflow.add_edge("master_orchestrator", "data_integration")
    workflow.add_edge("master_orchestrator", "plan_formatter")
    workflow.add_edge("master_orchestrator", "season_planner")
    workflow.add_edge("master_orchestrator", "weekly_planner")

    workflow.add_edge("data_integration", "weekly_planner")
    workflow.add_edge("weekly_planner", "master_orchestrator")
    workflow.add_edge("plan_formatter", END)

    checkpointer = MemorySaver()
    app = workflow.compile(checkpointer=checkpointer)

    logger.info("Created complete LangGraph planning workflow with 4 agents")
    return app


async def run_weekly_planning(
    user_id: str,
    athlete_name: str,
    garmin_data: dict,
    planning_context: str = "",
    weight_context: str = "",
    competitions: list | None = None,
    current_date: dict | None = None,
    week_dates: list | None = None,
    metrics_outputs=None,
    activity_outputs=None,
    physiology_outputs=None,
    plots: list | None = None,
    available_plots: list | None = None,
) -> dict:
    execution_id = f"{user_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_planning"
    config = {"configurable": {"thread_id": execution_id}}

    initial_state = create_initial_state(
        user_id=user_id,
        athlete_name=athlete_name,
        garmin_data=garmin_data,
        planning_context=planning_context,
        weight_context=weight_context,
        competitions=competitions,
        current_date=current_date,
        week_dates=week_dates,
        execution_id=execution_id,
    )
    initial_state.update({
        "metrics_outputs": metrics_outputs,
        "activity_outputs": activity_outputs,
        "physiology_outputs": physiology_outputs,
        "plots": plots or [],
        "available_plots": available_plots or [],
    })

    async for chunk in create_planning_workflow().astream(
        initial_state,
        config=config,
        stream_mode="values",
    ):
        logger.info("Planning workflow step: %s", list(chunk.keys()) if chunk else "None")
        final_state = chunk

    return final_state


def create_integrated_analysis_and_planning_workflow():
    LangSmithConfig.setup_langsmith()

    workflow = StateGraph(TrainingAnalysisState)

    workflow.add_node("metrics_summarizer", metrics_summarizer_node)
    workflow.add_node("physiology_summarizer", physiology_summarizer_node)
    workflow.add_node("activity_summarizer", activity_summarizer_node)

    workflow.add_node("metrics_expert", metrics_expert_node)
    workflow.add_node("physiology_expert", physiology_expert_node)
    workflow.add_node("activity_expert", activity_expert_node)

    workflow.add_node("synthesis", synthesis_node)
    workflow.add_node("formatter", formatter_node)
    workflow.add_node("plot_resolution", plot_resolution_node)

    workflow.add_node("season_planner", season_planner_node)
    workflow.add_node("master_orchestrator", master_orchestrator_node)
    workflow.add_node("data_integration", data_integration_node)
    workflow.add_node("weekly_planner", weekly_planner_node)
    workflow.add_node("plan_formatter", plan_formatter_node)

    workflow.add_node("finalize", lambda state: state, defer=True)

    workflow.add_edge(START, "metrics_summarizer")
    workflow.add_edge(START, "physiology_summarizer")
    workflow.add_edge(START, "activity_summarizer")

    workflow.add_edge("metrics_summarizer", "metrics_expert")
    workflow.add_edge("physiology_summarizer", "physiology_expert")
    workflow.add_edge("activity_summarizer", "activity_expert")

    workflow.add_edge(["metrics_expert", "physiology_expert", "activity_expert"], "master_orchestrator")

    # Master orchestrator uses ONLY Command(goto=...) for dynamic routing
    # NO unconditional edges from orchestrator - it routes dynamically based on stage

    workflow.add_edge("synthesis", "formatter")
    workflow.add_edge("formatter", "plot_resolution")

    # Season planner routes back to orchestrator for HITL handling
    workflow.add_edge("season_planner", "master_orchestrator")

    # Data integration → weekly planner → orchestrator
    workflow.add_edge("data_integration", "weekly_planner")
    workflow.add_edge("weekly_planner", "master_orchestrator")

    workflow.add_edge("plot_resolution", "finalize")
    workflow.add_edge("plan_formatter", "finalize")
    workflow.add_edge("finalize", END)

    checkpointer = MemorySaver()
    app = workflow.compile(checkpointer=checkpointer)
    logger.info(
        "Created integrated analysis + planning workflow with parallel architecture: "
        "3 summarizers → 3 experts → [analysis branch (synthesis/formatter/plots) || planning branch (season/data_integration/weekly/plan_formatter)] → finalize"
    )

    return app


async def run_complete_analysis_and_planning(
    user_id: str,
    athlete_name: str,
    garmin_data: dict,
    analysis_context: str = "",
    planning_context: str = "",
    weight_context: str = "",
    competitions: list | None = None,
    current_date: dict | None = None,
    week_dates: list | None = None,
    progress_manager=None,
    plotting_enabled: bool = False,
    hitl_enabled: bool = True,
    skip_synthesis: bool = False,
) -> dict:
    execution_id = f"{user_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_complete"
    cost_tracker = ProgressIntegratedCostTracker(f"garmin_ai_coach_{user_id}", progress_manager)


    final_state, execution = await cost_tracker.run_workflow_with_progress(
        create_integrated_analysis_and_planning_workflow(),
        cast("dict[str, Any]", create_initial_state(
            user_id=user_id,
            athlete_name=athlete_name,
            garmin_data=garmin_data,
            analysis_context=analysis_context,
            planning_context=planning_context,
            weight_context=weight_context,
            competitions=competitions,
            current_date=current_date,
            week_dates=week_dates,
            execution_id=execution_id,
            plotting_enabled=plotting_enabled,
            hitl_enabled=hitl_enabled,
            skip_synthesis=skip_synthesis,
        )),
        execution_id,
        user_id,
    )

    if execution.cost_summary:
        final_state["cost_summary"] = cost_tracker.get_legacy_cost_summary(execution)
        final_state["execution_metadata"] = {
            "trace_id": execution.trace_id,
            "root_run_id": execution.root_run_id,
            "execution_time_seconds": execution.execution_time_seconds,
            "total_cost_usd": execution.cost_summary.total_cost_usd,
            "total_tokens": execution.cost_summary.total_tokens,
        }
        logger.info(
            "Workflow complete for user %s: $%.4f (%d tokens)",
            user_id,
            execution.cost_summary.total_cost_usd,
            execution.cost_summary.total_tokens,
        )
    else:
        logger.warning("No cost data available for user %s workflow", user_id)
        final_state["cost_summary"] = {"total_cost_usd": 0.0, "total_tokens": 0}
        final_state["execution_metadata"] = {}

    return final_state


async def run_weekly_planning_with_context(
    user_id: str,
    athlete_name: str,
    season_plan_text: str,
    planning_context: str = "",
    current_date: dict | None = None,
    week_dates: list | None = None,
    metrics_outputs=None,
    activity_outputs=None,
    physiology_outputs=None,
    weight_context: str = "",
    competitions: list | None = None,
) -> dict:
    """Re-run only the planning branch using cached expert outputs.

    Used by the chat API to quickly update the weekly plan from user feedback
    without re-running the slow Garmin data extraction and analysis pipeline.

    Returns a dict with keys:
      - ``weekly_plan_md``: the raw markdown plan text
      - ``planning_html``: the rendered HTML plan page
    """
    execution_id = f"{user_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_chat"
    config = {"configurable": {"thread_id": execution_id}}

    # Build minimal workflow: data_integration → weekly_planner → plan_formatter
    LangSmithConfig.setup_langsmith()
    workflow = StateGraph(TrainingAnalysisState)
    workflow.add_node("data_integration", data_integration_node)
    workflow.add_node("weekly_planner", weekly_planner_node)
    workflow.add_node("plan_formatter", plan_formatter_node)
    workflow.add_edge(START, "data_integration")
    workflow.add_edge("data_integration", "weekly_planner")
    workflow.add_edge("weekly_planner", "plan_formatter")
    workflow.add_edge("plan_formatter", END)

    checkpointer = MemorySaver()
    mini_app = workflow.compile(checkpointer=checkpointer)

    initial_state = create_initial_state(
        user_id=user_id,
        athlete_name=athlete_name,
        garmin_data={},
        planning_context=planning_context,
        weight_context=weight_context,
        competitions=competitions,
        current_date=current_date,
        week_dates=week_dates,
        execution_id=execution_id,
        hitl_enabled=False,
        skip_synthesis=True,
    )

    # Pre-populate outputs so planners can use them
    initial_state.update({
        "metrics_outputs": metrics_outputs,
        "activity_outputs": activity_outputs,
        "physiology_outputs": physiology_outputs,
        "season_plan": season_plan_text,
        "season_plan_complete": True,
        "synthesis_complete": True,
    })

    final_state: dict = {}
    async for chunk in mini_app.astream(initial_state, config=config, stream_mode="values"):
        final_state = chunk

    # Extract weekly plan markdown
    weekly_plan_raw = final_state.get("weekly_plan", "")
    weekly_plan_md = ""
    if isinstance(weekly_plan_raw, dict):
        output = weekly_plan_raw.get("output", "")
        weekly_plan_md = output if isinstance(output, str) else ""
    elif isinstance(weekly_plan_raw, str):
        weekly_plan_md = weekly_plan_raw

    planning_html = final_state.get("planning_html", "")
    if planning_html and not isinstance(planning_html, str):
        planning_html = str(planning_html)

    # Inject chat panel into the rendered HTML
    planning_html = _inject_chat_panel(planning_html)

    return {"weekly_plan_md": weekly_plan_md, "planning_html": planning_html}


def _inject_iframe_helpers(html: str, is_planning: bool) -> str:
    """Inject styling and scripts to support seamless iframe embedding and resizing."""
    if not html or "iframe-helper-injected" in html:
        return html

    css_overrides = r"""
<!-- ========== Iframe Embed Helper Styles ========== -->
<style id="iframe-helper-injected">
  /* General resets when loaded inside an iframe */
  body.in-iframe {
    background: transparent !important;
    background-color: transparent !important;
    color: #c9d1d9 !important;
    margin: 0 !important;
    padding: 0 !important;
    overflow: hidden !important; /* Prevent double scrollbars and layout loops */
    font-family: 'Outfit', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif !important;

    /* Override variable definitions of sub-documents to force dark mode */
    --color-text: #c9d1d9 !important;
    --color-dark: #f0f6fc !important;
    --color-light: rgba(22, 27, 34, 0.4) !important;
    --color-bg-light: rgba(22, 27, 34, 0.6) !important;
    --color-bg-dark: transparent !important;
    --color-border: rgba(240, 246, 252, 0.1) !important;

    --color-primary-text: #c9d1d9 !important;
    --color-secondary-text: #8b949e !important;
    --color-background-light: rgba(22, 27, 34, 0.4) !important;
    --color-background-white: rgba(22, 27, 34, 0.6) !important;

    --retro-bg-card: rgba(255, 255, 255, 0.02) !important;
    --retro-border-card: rgba(240, 246, 252, 0.05) !important;
  }

  body.in-iframe header,
  body.in-iframe footer,
  body.in-iframe #garmin-chat-panel {
    display: none !important;
  }

  body.in-iframe .container {
    max-width: 100% !important;
    margin: 0 !important;
    padding: 0 !important;
    background: transparent !important;
    background-color: transparent !important;
    box-shadow: none !important;
  }

  /* Unified Card Sections */
  body.in-iframe section,
  body.in-iframe .card-section {
    background-color: rgba(22, 27, 34, 0.6) !important;
    border: 1px solid rgba(240, 246, 252, 0.1) !important;
    box-shadow: none !important;
    border-radius: 20px !important;
    padding: 25px !important;
    margin-bottom: 20px !important;
  }

  body.in-iframe h1 { display: none !important; }

  body.in-iframe h2 {
    border-bottom: 2px solid rgba(240, 246, 252, 0.1) !important;
    color: #f0f6fc !important;
    font-size: 1.6em !important;
    font-weight: 700 !important;
    padding-left: 0 !important;
    border-left: none !important;
  }

  body.in-iframe h3 {
    color: #58a6ff !important;
    font-size: 1.3em !important;
    font-weight: 600 !important;
  }

  body.in-iframe h4 {
    color: #f0f6fc !important;
    font-size: 1.1em !important;
    font-weight: 600 !important;
  }

  /* Target schedule-specific styles */
  body.in-iframe .day-card {
    background-color: rgba(255, 255, 255, 0.02) !important;
    border: 1px solid rgba(240, 246, 252, 0.05) !important;
    border-top: 5px solid #58a6ff !important;
    color: #c9d1d9 !important;
    border-radius: 12px !important;
    padding: 15px !important;
  }
  body.in-iframe .day-card h4 { color: #f0f6fc !important; }
  body.in-iframe .day-card .day-focus {
    background-color: rgba(88, 166, 255, 0.15) !important;
    color: #58a6ff !important;
  }
  body.in-iframe .day-card .focus { color: #bc8cff !important; }
  body.in-iframe .day-card .purpose,
  body.in-iframe .day-card .adaptation {
    color: #8b949e !important;
    border-left: 2px solid rgba(240, 246, 252, 0.1) !important;
  }
  body.in-iframe .zone-definitions,
  body.in-iframe .zone-table {
    background-color: rgba(255, 255, 255, 0.01) !important;
    border: 1px solid rgba(240, 246, 252, 0.08) !important;
  }
  body.in-iframe .zone-definitions th,
  body.in-iframe .zone-table th {
    background-color: rgba(88, 166, 255, 0.08) !important;
    color: #f0f6fc !important;
    border-bottom: 1px solid rgba(240, 246, 252, 0.1) !important;
  }
  body.in-iframe .zone-definitions td,
  body.in-iframe .zone-table td {
    border-bottom: 1px solid rgba(240, 246, 252, 0.05) !important;
  }
  body.in-iframe .zone-table .zone-1,
  body.in-iframe .zone-table .zone-2,
  body.in-iframe .zone-table .zone-3,
  body.in-iframe .zone-table .zone-4,
  body.in-iframe .zone-table .zone-5 {
    background-color: rgba(255, 255, 255, 0.02) !important;
    color: #c9d1d9 !important;
  }
  body.in-iframe .zone-definitions tr:nth-child(even),
  body.in-iframe .zone-table tr:nth-child(even) {
    background-color: rgba(255, 255, 255, 0.02) !important;
  }
  body.in-iframe .week-plan {
    background-color: rgba(255, 255, 255, 0.01) !important;
    border: 1px solid rgba(240, 246, 252, 0.05) !important;
    border-radius: 16px !important;
    padding: 20px !important;
  }
  body.in-iframe .week-plan > h3 {
    color: #f0f6fc !important;
    border-bottom: 2px solid rgba(240, 246, 252, 0.1) !important;
  }
  body.in-iframe .week-plan .week-notes {
    background-color: rgba(188, 140, 255, 0.04) !important;
    border-left: 5px solid #bc8cff !important;
    color: #c9d1d9 !important;
    border-radius: 8px !important;
    padding: 12px !important;
  }
  body.in-iframe [style*="background-color: white"],
  body.in-iframe [style*="background-color: #fff"],
  body.in-iframe [style*="background-color: #ffffff"],
  body.in-iframe [style*="background-color: #f8f9fa"],
  body.in-iframe [style*="background-color: rgb(255, 255, 255)"],
  body.in-iframe [style*="background: white"],
  body.in-iframe [style*="background: #fff"],
  body.in-iframe [style*="background: #ffffff"],
  body.in-iframe [style*="background: rgb(255, 255, 255)"],
  body.in-iframe .expert-card,
  body.in-iframe .expert-rationale div,
  body.in-iframe .qualitative-constraints div,
  body.in-iframe .qualitative-constraints ul,
  body.in-iframe .card {
    background-color: rgba(22, 27, 34, 0.6) !important;
    background: rgba(22, 27, 34, 0.6) !important;
    border: 1px solid rgba(240, 246, 252, 0.1) !important;
    border-radius: 8px !important;
    padding: 15px !important;
  }

  body.in-iframe [style*="background-color: white"] p,
  body.in-iframe [style*="background-color: white"] li,
  body.in-iframe [style*="background-color: white"] span,
  body.in-iframe [style*="background-color: white"] div,
  body.in-iframe [style*="background-color: #fff"] p,
  body.in-iframe [style*="background-color: #fff"] li,
  body.in-iframe [style*="background-color: #fff"] span,
  body.in-iframe [style*="background-color: #fff"] div,
  body.in-iframe [style*="background-color: #ffffff"] p,
  body.in-iframe [style*="background-color: #ffffff"] li,
  body.in-iframe [style*="background-color: #ffffff"] span,
  body.in-iframe [style*="background-color: #ffffff"] div,
  body.in-iframe [style*="background: white"] p,
  body.in-iframe [style*="background: white"] li,
  body.in-iframe [style*="background: white"] span,
  body.in-iframe [style*="background: white"] div,
  body.in-iframe [style*="background: #fff"] p,
  body.in-iframe [style*="background: #fff"] li,
  body.in-iframe [style*="background: #fff"] span,
  body.in-iframe [style*="background: #fff"] div,
  body.in-iframe [style*="background: #ffffff"] p,
  body.in-iframe [style*="background: #ffffff"] li,
  body.in-iframe [style*="background: #ffffff"] span,
  body.in-iframe [style*="background: #ffffff"] div,
  body.in-iframe .expert-card *,
  body.in-iframe .expert-rationale div *,
  body.in-iframe .qualitative-constraints div *,
  body.in-iframe .qualitative-constraints ul li {
    color: #c9d1d9 !important;
  }

  body.in-iframe [style*="background-color: white"] strong,
  body.in-iframe [style*="background-color: #fff"] strong,
  body.in-iframe [style*="background-color: #ffffff"] strong,
  body.in-iframe [style*="background: white"] strong,
  body.in-iframe [style*="background: #fff"] strong,
  body.in-iframe [style*="background: #ffffff"] strong {
    color: #f0f6fc !important;
  }
  body.in-iframe #season-plan li {
    background-color: rgba(255, 255, 255, 0.01) !important;
    border-left: 5px solid #3498db !important;
    border-radius: 8px !important;
    color: #c9d1d9 !important;
  }
  body.in-iframe #season-plan li strong { color: #f0f6fc !important; }
  body.in-iframe ul li { color: #c9d1d9 !important; }
  body.in-iframe .workout-checkbox-wrapper {
    border-top: 1px dashed rgba(240, 246, 252, 0.1) !important;
  }
  body.in-iframe .workout-checkbox-wrapper label {
    color: #f0f6fc !important;
  }
  body.in-iframe .workout-checkbox-wrapper input[type="checkbox"]:checked + label {
    color: #8b949e !important;
  }

  /* Hide retro section inside standard schedule iframe */
  body.in-iframe:not(.retro-only) #retro-analysis {
    display: none !important;
  }

  /* 2. Metrics Tab Styling (analysis.html) */
  body.in-iframe table {
    border-collapse: collapse !important;
    width: 100% !important;
    margin-bottom: 20px !important;
  }
  body.in-iframe th,
  body.in-iframe td {
    border: 1px solid rgba(240, 246, 252, 0.1) !important;
    padding: 12px 15px !important;
    color: #c9d1d9 !important;
  }
  body.in-iframe th {
    background-color: rgba(188, 140, 255, 0.08) !important;
    color: #f0f6fc !important;
    font-weight: 600 !important;
  }
  body.in-iframe tr:nth-child(even) {
    background-color: rgba(255, 255, 255, 0.02) !important;
  }
  body.in-iframe .category-header {
    background-color: rgba(255, 255, 255, 0.05) !important;
    color: #f0f6fc !important;
    font-weight: 700 !important;
  }
  body.in-iframe td:first-child {
    color: #8b949e !important;
  }
  body.in-iframe ol li {
    background-color: rgba(255, 255, 255, 0.02) !important;
    border-left: 5px solid #28a745 !important;
    color: #c9d1d9 !important;
    box-shadow: none !important;
  }
  body.in-iframe ol li strong {
    color: #58a6ff !important;
  }
  body.in-iframe .status-danger { color: #f85149 !important; font-weight: 600; }
  body.in-iframe .status-warning { color: #d29922 !important; font-weight: 600; }
  body.in-iframe .status-success { color: #3fb950 !important; font-weight: 600; }
  body.in-iframe .status-info { color: #8b949e !important; }

  /* 3. Retro Tab Styling (planning.html?tab=retro) */
  body.retro-only .container > *:not(#retro-analysis) {
    display: none !important;
  }
  body.retro-only .container {
    gap: 0 !important;
  }
  body.retro-only #retro-analysis {
    display: block !important;
    margin: 0 !important;
    box-shadow: none !important;
    border: 1px solid rgba(240, 246, 252, 0.1) !important;
    background-color: rgba(22, 27, 34, 0.6) !important;
    border-radius: 20px !important;
    padding: 25px !important;
    color: #c9d1d9 !important;
  }
  body.retro-only .retro-grid,
  body.retro-only .retro-analysis-grid {
    display: grid !important;
    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)) !important;
    gap: 20px !important;
    margin-top: 20px !important;
  }
  body.retro-only .retro-card {
    background-color: rgba(255, 255, 255, 0.02) !important;
    border-radius: 12px !important;
    padding: 20px !important;
    color: #c9d1d9 !important;
  }
  body.retro-only .retro-card.info {
    background-color: rgba(88, 166, 255, 0.08) !important;
    border: 1px solid rgba(88, 166, 255, 0.3) !important;
  }
  body.retro-only .retro-card.positive {
    background-color: rgba(63, 185, 80, 0.08) !important;
    border: 1px solid rgba(63, 185, 80, 0.3) !important;
  }
  body.retro-only .retro-card.negative {
    background-color: rgba(248, 81, 73, 0.08) !important;
    border: 1px solid rgba(248, 81, 73, 0.3) !important;
  }
  body.retro-only .retro-card.warning {
    background-color: rgba(210, 153, 34, 0.08) !important;
    border: 1px solid rgba(210, 153, 34, 0.3) !important;
  }
  body.retro-only .retro-card h3 {
    color: #f0f6fc !important;
    font-size: 1.25em !important;
    font-weight: 600 !important;
    border-bottom: 1px solid rgba(240, 246, 252, 0.08) !important;
    padding-bottom: 8px !important;
    margin-bottom: 12px !important;
  }
  body.retro-only .retro-card.info h3 { color: #58a6ff !important; }
  body.retro-only .retro-card.positive h3 { color: #3fb950 !important; }
  body.retro-only .retro-card.negative h3 { color: #f85149 !important; }
  body.retro-only .retro-card.warning h3 { color: #d29922 !important; }

  body.retro-only .retro-card li {
    border-bottom: 1px dotted rgba(240, 246, 252, 0.1) !important;
    padding: 10px 0 !important;
    color: #c9d1d9 !important;
  }
  body.retro-only .retro-card li strong { color: #f0f6fc !important; }
  body.retro-only h2 {
    border-bottom: 2px solid #d35400 !important;
    color: #f0f6fc !important;
    font-size: 1.6em !important;
    font-weight: 700 !important;
  }
</style>

<script>
  (function() {
    if (window.self !== window.top) {
      document.body.classList.add('in-iframe');
      if (window.location.hash === '#retro-analysis' || window.location.search.includes('tab=retro')) {
        document.body.classList.add('retro-only');
      }

      // Auto height communication via postMessage
      function sendHeight() {
        if (document.documentElement) {
          window.parent.postMessage({
            type: 'resize',
            height: document.documentElement.scrollHeight
          }, '*');
        }
      }

      window.addEventListener('load', sendHeight);

      // Only send height on horizontal resize to avoid feedback loops
      let lastWidth = window.innerWidth;
      window.addEventListener('resize', function() {
        if (window.innerWidth !== lastWidth) {
          lastWidth = window.innerWidth;
          sendHeight();
        }
      });

      // Monitor DOM updates and clicks to resize instantly
      document.body.addEventListener('click', function() {
        setTimeout(sendHeight, 50);
      });

      const observer = new MutationObserver(sendHeight);
      observer.observe(document.body, { attributes: true, childList: true, subtree: true });
    }
  })();
</script>
<!-- ========== End Iframe Embed Helper ========== -->
"""
    if "</body>" in html:
        return html.replace("</body>", css_overrides + "\n</body>")
    return html + css_overrides


def _inject_chat_panel(html: str) -> str:
    """Inject the floating chat sidebar into an existing planning HTML page."""
    if not html:
        return html

    # First inject iframe helpers to planning.html
    html = _inject_iframe_helpers(html, is_planning=True)

    if "garmin-chat-panel" in html:
        return html

    chat_html = _get_chat_panel_html()
    # Inject before </body>
    if "</body>" in html:
        return html.replace("</body>", chat_html + "\n</body>")
    return html + chat_html


def _get_chat_panel_html() -> str:
    return r"""
<!-- ========== Garmin AI Coach Chat Panel ========== -->
<style>
  #garmin-chat-panel {
    position: fixed;
    bottom: 24px;
    right: 24px;
    width: 380px;
    max-height: 600px;
    background: rgba(15, 23, 42, 0.92);
    backdrop-filter: blur(16px);
    border: 1px solid rgba(99, 179, 237, 0.25);
    border-radius: 20px;
    box-shadow: 0 24px 64px rgba(0,0,0,0.5), 0 0 0 1px rgba(255,255,255,0.05);
    display: flex;
    flex-direction: column;
    overflow: hidden;
    z-index: 9999;
    font-family: 'Inter', 'Segoe UI', system-ui, sans-serif;
    transition: all 0.3s cubic-bezier(0.4,0,0.2,1);
  }
  #garmin-chat-panel.collapsed {
    max-height: 56px;
    width: 220px;
  }
  #chat-header {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 14px 18px;
    background: linear-gradient(135deg, rgba(59,130,246,0.3), rgba(139,92,246,0.3));
    border-bottom: 1px solid rgba(255,255,255,0.08);
    cursor: pointer;
    user-select: none;
    flex-shrink: 0;
  }
  #chat-header .chat-icon {
    width: 28px; height: 28px;
    background: linear-gradient(135deg, #3b82f6, #8b5cf6);
    border-radius: 8px;
    display: flex; align-items: center; justify-content: center;
    font-size: 14px;
    flex-shrink: 0;
  }
  #chat-header h3 {
    margin: 0;
    font-size: 14px;
    font-weight: 600;
    color: #e2e8f0;
    flex: 1;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  #chat-toggle-btn {
    background: none; border: none;
    color: #94a3b8; cursor: pointer;
    font-size: 16px; padding: 2px 6px;
    border-radius: 6px;
    transition: color 0.2s, background 0.2s;
  }
  #chat-toggle-btn:hover { color: #e2e8f0; background: rgba(255,255,255,0.1); }
  #chat-body {
    display: flex;
    flex-direction: column;
    flex: 1;
    overflow: hidden;
    transition: opacity 0.2s;
  }
  #garmin-chat-panel.collapsed #chat-body { opacity: 0; pointer-events: none; }
  #chat-messages {
    flex: 1;
    overflow-y: auto;
    padding: 16px;
    display: flex;
    flex-direction: column;
    gap: 12px;
    max-height: 380px;
    scrollbar-width: thin;
    scrollbar-color: rgba(99,179,237,0.3) transparent;
  }
  .chat-msg {
    display: flex;
    flex-direction: column;
    max-width: 88%;
    animation: msgIn 0.25s ease;
  }
  @keyframes msgIn {
    from { opacity: 0; transform: translateY(8px); }
    to   { opacity: 1; transform: translateY(0); }
  }
  .chat-msg.user { align-self: flex-end; }
  .chat-msg.assistant { align-self: flex-start; }
  .msg-bubble {
    padding: 10px 14px;
    border-radius: 16px;
    font-size: 13px;
    line-height: 1.5;
    color: #e2e8f0;
    word-break: break-word;
  }
  .chat-msg.user .msg-bubble {
    background: linear-gradient(135deg, #3b82f6, #6366f1);
    border-bottom-right-radius: 4px;
  }
  .chat-msg.assistant .msg-bubble {
    background: rgba(51, 65, 85, 0.8);
    border: 1px solid rgba(99,179,237,0.15);
    border-bottom-left-radius: 4px;
  }
  .msg-label {
    font-size: 10px;
    color: #64748b;
    margin-bottom: 4px;
    padding: 0 4px;
    font-weight: 500;
    letter-spacing: 0.05em;
    text-transform: uppercase;
  }
  .chat-msg.user .msg-label { text-align: right; }
  #chat-thinking {
    display: none;
    align-self: flex-start;
    padding: 10px 14px;
    background: rgba(51,65,85,0.8);
    border: 1px solid rgba(99,179,237,0.15);
    border-radius: 16px;
    border-bottom-left-radius: 4px;
    font-size: 13px;
    color: #94a3b8;
    gap: 6px;
    align-items: center;
  }
  #chat-thinking.visible { display: flex; }
  .thinking-dots span {
    display: inline-block;
    width: 5px; height: 5px;
    background: #64b5f6;
    border-radius: 50%;
    animation: dot-bounce 1.2s infinite;
    margin: 0 1px;
  }
  .thinking-dots span:nth-child(2) { animation-delay: 0.2s; }
  .thinking-dots span:nth-child(3) { animation-delay: 0.4s; }
  @keyframes dot-bounce {
    0%, 80%, 100% { transform: translateY(0); opacity: 0.4; }
    40% { transform: translateY(-5px); opacity: 1; }
  }
  #chat-input-area {
    display: flex;
    gap: 8px;
    padding: 12px 14px;
    border-top: 1px solid rgba(255,255,255,0.06);
    background: rgba(15,23,42,0.6);
    flex-shrink: 0;
  }
  #chat-input {
    flex: 1;
    background: rgba(30,41,59,0.9);
    border: 1px solid rgba(99,179,237,0.2);
    border-radius: 12px;
    padding: 9px 13px;
    color: #e2e8f0;
    font-size: 13px;
    font-family: inherit;
    outline: none;
    resize: none;
    min-height: 38px;
    max-height: 120px;
    overflow-y: auto;
    line-height: 1.4;
    transition: border-color 0.2s;
  }
  #chat-input:focus { border-color: rgba(99,179,237,0.5); }
  #chat-input::placeholder { color: #475569; }
  #chat-send-btn {
    width: 38px; height: 38px;
    background: linear-gradient(135deg, #3b82f6, #6366f1);
    border: none;
    border-radius: 10px;
    color: white;
    font-size: 16px;
    cursor: pointer;
    display: flex; align-items: center; justify-content: center;
    flex-shrink: 0;
    transition: opacity 0.2s, transform 0.1s;
    align-self: flex-end;
  }
  #chat-send-btn:hover { opacity: 0.85; }
  #chat-send-btn:active { transform: scale(0.95); }
  #chat-send-btn:disabled { opacity: 0.4; cursor: not-allowed; }
  #chat-plan-reload {
    display: none;
    margin: 8px 14px;
    padding: 9px 14px;
    background: linear-gradient(135deg, rgba(16,185,129,0.2), rgba(6,182,212,0.2));
    border: 1px solid rgba(16,185,129,0.4);
    border-radius: 10px;
    color: #34d399;
    font-size: 12px;
    text-align: center;
    cursor: pointer;
    transition: background 0.2s;
    font-weight: 500;
  }
  #chat-plan-reload.visible { display: block; }
  #chat-plan-reload:hover { background: linear-gradient(135deg, rgba(16,185,129,0.35), rgba(6,182,212,0.35)); }
  #chat-clear-btn {
    font-size: 10px;
    color: #475569;
    background: none;
    border: none;
    cursor: pointer;
    padding: 2px 8px;
    border-radius: 6px;
    transition: color 0.2s;
  }
  #chat-clear-btn:hover { color: #94a3b8; }
</style>

<div id="garmin-chat-panel">
  <div id="chat-header" onclick="toggleChatPanel()">
    <div class="chat-icon">🤖</div>
    <h3>AI Coach Chat</h3>
    <button id="chat-toggle-btn" title="Minimize">-</button>
  </div>
  <div id="chat-body">
    <div id="chat-messages">
      <div class="chat-msg assistant">
        <div class="msg-label">Coach</div>
        <div class="msg-bubble">
          👋 Hi! I'm your AI coach. Tell me how you'd like to adjust your training plan — e.g. <em>"I can't train on Wednesdays"</em> or <em>"Make week 3 a recovery week"</em>.
        </div>
      </div>
    </div>
    <div id="chat-thinking">
      <span>🧠 Re-planning</span>
      <div class="thinking-dots"><span></span><span></span><span></span></div>
    </div>
    <div id="chat-plan-reload" onclick="location.reload()">
      🔄 Plan updated! Click to refresh the page
    </div>
    <div id="chat-input-area">
      <textarea id="chat-input" placeholder="Ask your coach anything…" rows="1"
        onkeydown="handleChatKey(event)" oninput="autoResize(this)"></textarea>
      <button id="chat-send-btn" onclick="sendChatMessage()" title="Send">➤</button>
    </div>
    <div style="display:flex;justify-content:flex-end;padding:0 14px 10px;">
      <button id="chat-clear-btn" onclick="clearChatHistory()">Clear history</button>
    </div>
  </div>
</div>

<script>
(function() {
  const CHAT_API = '/api/chat';
  const USER_ID = 'Arnabbiswas';
  let isThinking = false;

  function toggleChatPanel() {
    const panel = document.getElementById('garmin-chat-panel');
    const btn = document.getElementById('chat-toggle-btn');
    panel.classList.toggle('collapsed');
    btn.textContent = panel.classList.contains('collapsed') ? '+' : '-';
  }

  function autoResize(el) {
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 120) + 'px';
  }

  function handleChatKey(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendChatMessage();
    }
  }

  function appendMessage(role, content) {
    const container = document.getElementById('chat-messages');
    const div = document.createElement('div');
    div.className = 'chat-msg ' + role;
    div.innerHTML = '<div class="msg-label">' + (role === 'user' ? 'You' : 'Coach') + '</div>'
      + '<div class="msg-bubble">' + escapeHtml(content) + '</div>';
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
  }

  function escapeHtml(s) {
    return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
            .replace(/"/g,'&quot;').replace(/\n/g,'<br>').replace(/\*(.*?)\*/g,'<em>$1</em>');
  }

  function setThinking(on) {
    isThinking = on;
    const el = document.getElementById('chat-thinking');
    el.classList.toggle('visible', on);
    document.getElementById('chat-send-btn').disabled = on;
    document.getElementById('chat-input').disabled = on;
    if (on) el.scrollIntoView({behavior:'smooth'});
  }

  function showReloadBanner() {
    document.getElementById('chat-plan-reload').classList.add('visible');
  }

  async function sendChatMessage() {
    if (isThinking) return;
    const input = document.getElementById('chat-input');
    const message = input.value.trim();
    if (!message) return;

    input.value = '';
    input.style.height = 'auto';
    appendMessage('user', message);
    setThinking(true);
    document.getElementById('chat-plan-reload').classList.remove('visible');

    try {
      const resp = await fetch(CHAT_API, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({user_id: USER_ID, message: message}),
      });

      if (!resp.ok) {
        const err = await resp.text();
        throw new Error('Server error ' + resp.status + ': ' + err);
      }

      const data = await resp.json();
      appendMessage('assistant', data.reply || 'Plan updated.');
      if (data.plan_updated) showReloadBanner();

    } catch(e) {
      appendMessage('assistant', '❌ Error: ' + e.message);
    } finally {
      setThinking(false);
    }
  }

  async function clearChatHistory() {
    try {
      await fetch(CHAT_API.replace('/chat', '/chat/' + USER_ID + '/history'), {method: 'DELETE'});
    } catch(e) { /* ignore */ }
    const container = document.getElementById('chat-messages');
    container.innerHTML = '<div class="chat-msg assistant"><div class="msg-label">Coach</div>'
      + '<div class="msg-bubble">Chat history cleared. How can I help with your training plan?</div></div>';
    document.getElementById('chat-plan-reload').classList.remove('visible');
  }

  // Make functions global
  window.toggleChatPanel = toggleChatPanel;
  window.sendChatMessage = sendChatMessage;
  window.handleChatKey = handleChatKey;
  window.autoResize = autoResize;
  window.clearChatHistory = clearChatHistory;
})();
</script>
<!-- ========== End Chat Panel ========== -->
"""
