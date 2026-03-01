"""
Unit tests for scenario definitions and the scenario registry.

Verifies:
- Each scenario satisfies the structural contract (Scenario dataclass).
- Attack types are correctly assigned.
- Required string fields are non-empty.
- Environments contain the expected file keys.
- Registry lookup by ID works correctly.
- Unknown scenario ID raises KeyError.
- list_scenarios returns all registered scenarios.
"""

import pytest

from sandbox.core.types import AttackType, Scenario
from sandbox.scenarios.file_injection import FILE_INJECTION_SCENARIO
from sandbox.scenarios.tool_output_injection import TOOL_OUTPUT_INJECTION_SCENARIO
from sandbox.scenarios.registry import (
    SCENARIO_REGISTRY,
    get_scenario,
    list_scenarios,
)


# ---------------------------------------------------------------------------
# File injection scenario
# ---------------------------------------------------------------------------


def test_file_injection_is_scenario_instance():
    assert isinstance(FILE_INJECTION_SCENARIO, Scenario)


def test_file_injection_id():
    assert FILE_INJECTION_SCENARIO.id == "file_injection_v1"


def test_file_injection_attack_type():
    assert FILE_INJECTION_SCENARIO.attack_type == AttackType.FILE_INJECTION


def test_file_injection_system_prompt_non_empty():
    assert FILE_INJECTION_SCENARIO.system_prompt.strip() != ""


def test_file_injection_user_prompt_non_empty():
    assert FILE_INJECTION_SCENARIO.user_prompt.strip() != ""


def test_file_injection_readme_in_environment():
    assert "README.md" in FILE_INJECTION_SCENARIO.environment.files


def test_file_injection_payload_targets_secret():
    readme = FILE_INJECTION_SCENARIO.environment.files["README.md"]
    assert "secret.txt" in readme


# ---------------------------------------------------------------------------
# Tool output injection scenario
# ---------------------------------------------------------------------------


def test_tool_output_is_scenario_instance():
    assert isinstance(TOOL_OUTPUT_INJECTION_SCENARIO, Scenario)


def test_tool_output_id():
    assert TOOL_OUTPUT_INJECTION_SCENARIO.id == "tool_output_injection_v1"


def test_tool_output_attack_type():
    assert TOOL_OUTPUT_INJECTION_SCENARIO.attack_type == AttackType.TOOL_OUTPUT_INJECTION


def test_tool_output_system_prompt_non_empty():
    assert TOOL_OUTPUT_INJECTION_SCENARIO.system_prompt.strip() != ""


def test_tool_output_user_prompt_non_empty():
    assert TOOL_OUTPUT_INJECTION_SCENARIO.user_prompt.strip() != ""


def test_tool_output_payload_targets_secret():
    assert "secret.txt" in TOOL_OUTPUT_INJECTION_SCENARIO.user_prompt


def test_tool_output_environment_has_main_py():
    assert "main.py" in TOOL_OUTPUT_INJECTION_SCENARIO.environment.files


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_registry_contains_file_injection():
    assert "file_injection_v1" in SCENARIO_REGISTRY


def test_registry_contains_tool_output_injection():
    assert "tool_output_injection_v1" in SCENARIO_REGISTRY


def test_get_scenario_returns_correct_type():
    result = get_scenario("file_injection_v1")
    assert isinstance(result, Scenario)


def test_get_scenario_returns_correct_id():
    result = get_scenario("tool_output_injection_v1")
    assert result.id == "tool_output_injection_v1"


def test_get_scenario_raises_on_unknown_id():
    with pytest.raises(KeyError):
        get_scenario("nonexistent_scenario_id")


def test_list_scenarios_returns_all():
    scenarios = list_scenarios()
    assert len(scenarios) == len(SCENARIO_REGISTRY)


def test_list_scenarios_contains_expected_ids():
    ids = {s.id for s in list_scenarios()}
    assert "file_injection_v1" in ids
    assert "tool_output_injection_v1" in ids


def test_list_scenarios_all_are_scenario_instances():
    for s in list_scenarios():
        assert isinstance(s, Scenario)
