from dataclasses import dataclass, field
from enum import Enum

from core.config import AIMode, get_config


class AgentRole(Enum):
    SUMMARIZER = "summarizer"
    METRICS_EXPERT = "metrics_expert"
    PHYSIOLOGY_EXPERT = "physiology_expert"
    ACTIVITY_EXPERT = "activity_expert"
    SYNTHESIS = "synthesis"
    WORKOUT = "workout"
    SEASON_PLANNER = "season_planner"
    FORMATTER = "formatter"


@dataclass
class AISettings:
    mode: AIMode

    model_assignments: dict[AIMode, dict[AgentRole, str]] = field(
        default_factory=lambda: {
            AIMode.STANDARD: {
                AgentRole.SUMMARIZER: "gemini-2.0-flash",
                AgentRole.FORMATTER: "gemini-2.0-flash",
                AgentRole.METRICS_EXPERT: "gemini-2.0-flash",
                AgentRole.PHYSIOLOGY_EXPERT: "gemini-2.0-flash",
                AgentRole.ACTIVITY_EXPERT: "gemini-2.0-flash",
                AgentRole.SYNTHESIS: "gemini-2.0-flash",
                AgentRole.WORKOUT: "gemini-2.0-flash",
                AgentRole.SEASON_PLANNER: "gemini-2.0-flash",
            },
            AIMode.COST_EFFECTIVE: {
                AgentRole.SUMMARIZER: "gemini-2.0-flash",
                AgentRole.FORMATTER: "gemini-2.0-flash",
                AgentRole.METRICS_EXPERT: "gemini-2.0-flash",
                AgentRole.PHYSIOLOGY_EXPERT: "gemini-2.0-flash",
                AgentRole.ACTIVITY_EXPERT: "gemini-2.0-flash",
                AgentRole.SYNTHESIS: "gemini-2.0-flash",
                AgentRole.WORKOUT: "gemini-2.0-flash",
                AgentRole.SEASON_PLANNER: "gemini-2.0-flash",
            },
            AIMode.DEVELOPMENT: {
                AgentRole.SUMMARIZER: "gemini-2.0-flash",
                AgentRole.FORMATTER: "gemini-2.0-flash",
                AgentRole.METRICS_EXPERT: "gemini-2.0-flash",
                AgentRole.PHYSIOLOGY_EXPERT: "gemini-2.0-flash",
                AgentRole.ACTIVITY_EXPERT: "gemini-2.0-flash",
                AgentRole.SYNTHESIS: "gemini-2.0-flash",
                AgentRole.WORKOUT: "gemini-2.0-flash",
                AgentRole.SEASON_PLANNER: "gemini-2.0-flash",
            },
            AIMode.PRO: {
                AgentRole.SUMMARIZER: "gemini-2.5-flash",
                AgentRole.FORMATTER: "gemini-2.5-flash",
                AgentRole.METRICS_EXPERT: "gemini-2.5-flash",
                AgentRole.PHYSIOLOGY_EXPERT: "gemini-2.5-flash",
                AgentRole.ACTIVITY_EXPERT: "gemini-2.5-flash",
                AgentRole.SYNTHESIS: "gemini-2.5-flash",
                AgentRole.WORKOUT: "gemini-2.5-flash",
                AgentRole.SEASON_PLANNER: "gemini-2.5-flash",
            },
        }
    )

    def get_model_for_role(self, role: AgentRole) -> str:
        return self.model_assignments[self.mode][role]

    @classmethod
    def load_settings(cls) -> "AISettings":
        return cls(mode=get_config().ai_mode)

    def reload(self) -> None:
        self.mode = get_config().ai_mode


# Global settings instance
ai_settings = AISettings.load_settings()
