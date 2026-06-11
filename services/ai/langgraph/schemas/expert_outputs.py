from pydantic import BaseModel, Field

from .agent_outputs import Question


class ReceiverPayload(BaseModel):
    signals: list[str]
    evidence: list[str]
    implications: list[str]
    uncertainty: list[str] | None = None


class ReceiverOutputs(BaseModel):
    for_synthesis: ReceiverPayload = Field(
        ...,
        description="Output for Synthesis Agent creating comprehensive athlete report"
    )
    for_season_planner: ReceiverPayload = Field(
        ...,
        description="Output for Season Planner designing 12-24 week macro-cycles"
    )
    for_weekly_planner: ReceiverPayload = Field(
        ...,
        description="Output for Weekly Planner creating next 28-day training plan"
    )


class ExpertOutputBase(BaseModel):
    output: list[Question] | ReceiverOutputs = Field(
        ...,
        description="EITHER questions for HITL OR full output for downstream consumers"
    )


class MetricsExpertOutputs(ExpertOutputBase):
    pass


class ActivityExpertOutputs(ExpertOutputBase):
    pass


class PhysiologyExpertOutputs(ExpertOutputBase):
    pass


# ── Combined node schemas (replaces 3+3+1 individual nodes) ──────────────────

class CombinedSummaryOutputs(BaseModel):
    """Output from combined_summarizer_node (replaces 3 individual summarizers)."""
    metrics: str = Field(..., description="Metrics data summary (markdown)")
    physiology: str = Field(..., description="Physiology/recovery data summary (markdown)")
    activity: str = Field(..., description="Activity data summary with last 15 run splits (markdown)")


class CombinedAnalystOutputs(BaseModel):
    """Output from combined_analyst_node (replaces 3 experts + synthesis)."""
    metrics: ReceiverOutputs = Field(..., description="Metrics expert analysis for downstream consumers")
    physiology: ReceiverOutputs = Field(..., description="Physiology expert analysis for downstream consumers")
    activity: ReceiverOutputs = Field(..., description="Activity expert analysis for downstream consumers")
    synthesis: str = Field(..., description="Integrated synthesis narrative combining all three domains")
