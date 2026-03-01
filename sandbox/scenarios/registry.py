"""
Scenario registry: single source of truth for all available scenarios.

New scenarios must be registered here to be discoverable by the CLI and API.
"""

from sandbox.core.types import Scenario
from sandbox.scenarios.file_injection import FILE_INJECTION_SCENARIO
from sandbox.scenarios.tool_output_injection import TOOL_OUTPUT_INJECTION_SCENARIO

SCENARIO_REGISTRY: dict[str, Scenario] = {
    FILE_INJECTION_SCENARIO.id: FILE_INJECTION_SCENARIO,
    TOOL_OUTPUT_INJECTION_SCENARIO.id: TOOL_OUTPUT_INJECTION_SCENARIO,
}


def get_scenario(scenario_id: str) -> Scenario:
    """Return a scenario by ID, or raise KeyError if not found."""
    if scenario_id not in SCENARIO_REGISTRY:
        available = list(SCENARIO_REGISTRY.keys())
        raise KeyError(
            f"Scenario '{scenario_id}' not found. Available: {available}"
        )
    return SCENARIO_REGISTRY[scenario_id]


def list_scenarios() -> list[Scenario]:
    """Return all registered scenarios."""
    return list(SCENARIO_REGISTRY.values())
