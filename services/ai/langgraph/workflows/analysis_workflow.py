import logging
from datetime import datetime

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from services.ai.langgraph.config.langsmith_config import LangSmithConfig
from services.ai.langgraph.nodes.combined_analyst_node import combined_analyst_node
from services.ai.langgraph.nodes.combined_summarizer_node import combined_summarizer_node
from services.ai.langgraph.nodes.formatter_node import formatter_node
from services.ai.langgraph.nodes.plot_resolution_node import plot_resolution_node
from services.ai.langgraph.state.training_analysis_state import TrainingAnalysisState, create_initial_state

logger = logging.getLogger(__name__)


def create_analysis_workflow():
    LangSmithConfig.setup_langsmith()

    workflow = StateGraph(TrainingAnalysisState)

    workflow.add_node("combined_summarizer", combined_summarizer_node)
    workflow.add_node("combined_analyst", combined_analyst_node)
    workflow.add_node("formatter", formatter_node)
    workflow.add_node("plot_resolution", plot_resolution_node)

    workflow.add_edge(START, "combined_summarizer")
    workflow.add_edge("combined_summarizer", "combined_analyst")
    workflow.add_edge("combined_analyst", "formatter")
    workflow.add_edge("formatter", "plot_resolution")
    workflow.add_edge("plot_resolution", END)

    checkpointer = MemorySaver()
    app = workflow.compile(checkpointer=checkpointer)
    logger.info("Created complete LangGraph analysis workflow with combined summarizer and analyst")

    return app


async def run_training_analysis(
    user_id: str,
    athlete_name: str,
    garmin_data: dict,
    analysis_context: str = "",
    weight_context: str = "",
    competitions: list | None = None,
    current_date: dict | None = None,
    plotting_enabled: bool = False,
) -> dict:
    execution_id = f"{user_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    config = {"configurable": {"thread_id": execution_id}}

    async for chunk in create_analysis_workflow().astream(
        create_initial_state(
            user_id=user_id,
            athlete_name=athlete_name,
            garmin_data=garmin_data,
            analysis_context=analysis_context,
            weight_context=weight_context,
            competitions=competitions,
            current_date=current_date,
            execution_id=execution_id,
            plotting_enabled=plotting_enabled,
        ),
        config=config,
        stream_mode="values",
    ):
        logger.info("Workflow step: %s", list(chunk.keys()) if chunk else "None")
        final_state = chunk

    return final_state


def create_simple_sequential_workflow():
    workflow = StateGraph(TrainingAnalysisState)

    workflow.add_node("combined_summarizer", combined_summarizer_node)
    workflow.add_node("combined_analyst", combined_analyst_node)
    workflow.add_node("formatter", formatter_node)
    workflow.add_node("plot_resolution", plot_resolution_node)

    workflow.add_edge(START, "combined_summarizer")
    workflow.add_edge("combined_summarizer", "combined_analyst")
    workflow.add_edge("combined_analyst", "formatter")
    workflow.add_edge("formatter", "plot_resolution")
    workflow.add_edge("plot_resolution", END)

    checkpointer = MemorySaver()
    return workflow.compile(checkpointer=checkpointer)

