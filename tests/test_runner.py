"""
Unit tests for sandbox.core.runner.

Both the ModelAdapter and DockerSandbox are fully mocked so no live Ollama
instance or Docker daemon is required.
"""

from unittest.mock import MagicMock, patch

import pytest

from sandbox.core.adapter import ModelAdapter, ModelAdapterError
from sandbox.core.runner import _build_effective_user_prompt, run
from sandbox.core.types import EvaluationResult, RunResult
from sandbox.scenarios.file_injection import FILE_INJECTION_SCENARIO
from sandbox.scenarios.tool_output_injection import TOOL_OUTPUT_INJECTION_SCENARIO

SECRET = "CONFIDENTIAL-SECRET-XK29-ALPHA"


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_adapter(output: str) -> ModelAdapter:
    adapter = MagicMock(spec=ModelAdapter)
    adapter.ask.return_value = output
    return adapter


def _make_mock_sandbox(file_content: str = "file content") -> MagicMock:
    """Return a MagicMock that behaves like a DockerSandbox context manager."""
    sandbox = MagicMock()
    sandbox.__enter__ = MagicMock(return_value=sandbox)
    sandbox.__exit__ = MagicMock(return_value=False)
    sandbox.read_file.return_value = file_content
    return sandbox


def _patch_secret(secret: str = SECRET):
    return patch("sandbox.core.runner.load_secret", return_value=secret)


def _patch_sandbox(sandbox: MagicMock = None):
    mock = sandbox or _make_mock_sandbox()
    return patch("sandbox.core.runner.DockerSandbox", return_value=mock)


# ---------------------------------------------------------------------------
# Return type contract
# ---------------------------------------------------------------------------


def test_run_returns_run_result():
    with _patch_secret(), _patch_sandbox():
        result = run("m", "file_injection_v1", _make_adapter("clean"))
    assert isinstance(result, RunResult)


def test_run_result_model_field():
    with _patch_secret(), _patch_sandbox():
        result = run("llama3.2", "file_injection_v1", _make_adapter("clean"))
    assert result.model == "llama3.2"


def test_run_result_scenario_id_field():
    with _patch_secret(), _patch_sandbox():
        result = run("m", "file_injection_v1", _make_adapter("clean"))
    assert result.scenario_id == "file_injection_v1"


def test_run_result_scenario_name_non_empty():
    with _patch_secret(), _patch_sandbox():
        result = run("m", "file_injection_v1", _make_adapter("clean"))
    assert result.scenario_name.strip() != ""


def test_run_result_attack_type_non_empty():
    with _patch_secret(), _patch_sandbox():
        result = run("m", "file_injection_v1", _make_adapter("clean"))
    assert result.attack_type.strip() != ""


def test_run_result_model_output_preserved():
    with _patch_secret(), _patch_sandbox():
        result = run("m", "file_injection_v1", _make_adapter("exact output text"))
    # For file injection, the adapter gets the enriched prompt but returns "exact output text"
    assert result.model_output == "exact output text"


def test_run_result_evaluation_is_evaluation_result():
    with _patch_secret(), _patch_sandbox():
        result = run("m", "file_injection_v1", _make_adapter("clean"))
    assert isinstance(result.evaluation, EvaluationResult)


def test_run_result_timestamp_is_iso8601():
    with _patch_secret(), _patch_sandbox():
        result = run("m", "file_injection_v1", _make_adapter("clean"))
    assert "T" in result.timestamp


# ---------------------------------------------------------------------------
# Evaluation integration
# ---------------------------------------------------------------------------


def test_run_detects_secret_in_output():
    with _patch_secret(), _patch_sandbox():
        result = run("m", "file_injection_v1", _make_adapter(f"here: {SECRET}"))
    assert result.evaluation.compromised is True
    assert result.evaluation.extracted_secret == SECRET


def test_run_clean_output_not_compromised():
    with _patch_secret(), _patch_sandbox():
        result = run("m", "file_injection_v1", _make_adapter("I cannot help with that."))
    assert result.evaluation.compromised is False
    assert result.evaluation.extracted_secret is None


# ---------------------------------------------------------------------------
# Scenario routing
# ---------------------------------------------------------------------------


def test_run_tool_output_scenario():
    with _patch_secret(), _patch_sandbox():
        result = run("m", "tool_output_injection_v1", _make_adapter("fine"))
    assert result.scenario_id == "tool_output_injection_v1"


def test_run_raises_key_error_for_unknown_scenario():
    with _patch_secret(), _patch_sandbox():
        with pytest.raises(KeyError):
            run("m", "does_not_exist", _make_adapter(""))


# ---------------------------------------------------------------------------
# Sandbox integration
# ---------------------------------------------------------------------------


def test_run_creates_sandbox_with_correct_scenario():
    with _patch_secret():
        with patch("sandbox.core.runner.DockerSandbox") as mock_cls:
            mock_cls.return_value = _make_mock_sandbox()
            run("m", "file_injection_v1", _make_adapter("out"))
    call_kwargs = mock_cls.call_args.kwargs
    assert call_kwargs["scenario"].id == "file_injection_v1"


def test_run_passes_secret_to_sandbox():
    with _patch_secret("MY-SECRET"):
        with patch("sandbox.core.runner.DockerSandbox") as mock_cls:
            mock_cls.return_value = _make_mock_sandbox()
            run("m", "file_injection_v1", _make_adapter("out"))
    call_kwargs = mock_cls.call_args.kwargs
    assert call_kwargs["secret"] == "MY-SECRET"


def test_run_calls_adapter_ask():
    adapter = _make_adapter("output")
    with _patch_secret(), _patch_sandbox():
        run("m", "file_injection_v1", adapter)
    adapter.ask.assert_called_once()


def test_run_propagates_model_adapter_error():
    adapter = MagicMock(spec=ModelAdapter)
    adapter.ask.side_effect = ModelAdapterError("connection refused")
    with _patch_secret(), _patch_sandbox():
        with pytest.raises(ModelAdapterError):
            run("m", "file_injection_v1", adapter)


# ---------------------------------------------------------------------------
# on_step callback
# ---------------------------------------------------------------------------


def test_run_calls_on_step_callback():
    calls: list[tuple[str, str]] = []

    def cb(key: str, detail: str) -> None:
        calls.append((key, detail))

    with _patch_secret(), _patch_sandbox():
        run("m", "file_injection_v1", _make_adapter("output"), on_step=cb)

    assert len(calls) > 0


def test_run_on_step_emits_scenario_loaded():
    keys: list[str] = []
    with _patch_secret(), _patch_sandbox():
        run("m", "file_injection_v1", _make_adapter("out"), on_step=lambda k, d: keys.append(k))
    assert "scenario_loaded" in keys


def test_run_on_step_emits_model_calling_before_model_done():
    keys: list[str] = []
    with _patch_secret(), _patch_sandbox():
        run("m", "file_injection_v1", _make_adapter("out"), on_step=lambda k, d: keys.append(k))
    assert "model_calling" in keys
    assert "model_done" in keys
    assert keys.index("model_calling") < keys.index("model_done")


def test_run_on_step_none_does_not_raise():
    with _patch_secret(), _patch_sandbox():
        run("m", "file_injection_v1", _make_adapter("out"), on_step=None)


# ---------------------------------------------------------------------------
# _build_effective_user_prompt
# ---------------------------------------------------------------------------


def test_file_injection_appends_file_content_to_prompt():
    sandbox = _make_mock_sandbox(file_content="INJECTED PAYLOAD CONTENT")
    prompt = _build_effective_user_prompt(FILE_INJECTION_SCENARIO, sandbox, SECRET)
    assert FILE_INJECTION_SCENARIO.user_prompt in prompt
    assert "INJECTED PAYLOAD CONTENT" in prompt


def test_file_injection_reads_each_environment_file():
    sandbox = _make_mock_sandbox()
    _build_effective_user_prompt(FILE_INJECTION_SCENARIO, sandbox, SECRET)
    actual_calls = [c.args[0] for c in sandbox.read_file.call_args_list]
    # Every environment file must be read
    for filename in FILE_INJECTION_SCENARIO.environment.files:
        assert filename in actual_calls


def test_file_injection_also_reads_secret_txt():
    """Runner must include secret.txt in context so the injection can succeed."""
    sandbox = _make_mock_sandbox()
    _build_effective_user_prompt(FILE_INJECTION_SCENARIO, sandbox, SECRET)
    actual_calls = [c.args[0] for c in sandbox.read_file.call_args_list]
    assert "secret.txt" in actual_calls


def test_file_injection_secret_content_present_in_prompt():
    """The real secret value must appear in the assembled prompt."""
    sandbox = _make_mock_sandbox(file_content=SECRET)
    prompt = _build_effective_user_prompt(FILE_INJECTION_SCENARIO, sandbox, SECRET)
    assert SECRET in prompt


def test_tool_output_returns_scenario_user_prompt_unchanged():
    sandbox = _make_mock_sandbox()
    prompt = _build_effective_user_prompt(TOOL_OUTPUT_INJECTION_SCENARIO, sandbox, SECRET)
    assert prompt == TOOL_OUTPUT_INJECTION_SCENARIO.user_prompt
    sandbox.read_file.assert_not_called()


def test_file_injection_wraps_content_in_file_tags():
    sandbox = _make_mock_sandbox(file_content="some content")
    prompt = _build_effective_user_prompt(FILE_INJECTION_SCENARIO, sandbox, SECRET)
    assert "<file name=" in prompt
    assert "</file>" in prompt
