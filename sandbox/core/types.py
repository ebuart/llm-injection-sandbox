from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

# Re-export so callers only import from sandbox.core.types
__all__ = [
    "AttackType",
    "ScenarioEnvironment",
    "Scenario",
    "EvaluationResult",
    "RunResult",
]


class AttackType(str, Enum):
    FILE_INJECTION = "file_injection"
    TOOL_OUTPUT_INJECTION = "tool_output_injection"


@dataclass
class ScenarioEnvironment:
    """Files to place inside the sandbox before execution."""

    files: dict[str, str] = field(default_factory=dict)


@dataclass
class Scenario:
    id: str
    name: str
    description: str
    attack_type: AttackType
    system_prompt: str
    user_prompt: str
    environment: ScenarioEnvironment = field(default_factory=ScenarioEnvironment)


@dataclass
class EvaluationResult:
    compromised: bool
    reason: str
    extracted_secret: Optional[str] = None


@dataclass
class RunResult:
    """Artifact produced by a single scenario run."""

    model: str
    scenario_id: str
    scenario_name: str
    attack_type: str
    model_output: str
    evaluation: EvaluationResult
    timestamp: str  # ISO 8601 UTC
