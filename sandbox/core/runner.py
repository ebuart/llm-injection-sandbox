"""
Scenario runner — core orchestration layer.

Responsibilities:
  1. Load the requested scenario from the registry.
  2. Load the secret from assets (host-side only; never sent to model).
  3. Start a DockerSandbox, write all scenario files (including secret.txt) into it.
  4. Build the effective user prompt by reading files from the sandbox where needed.
  5. Invoke the model adapter to obtain raw output.
  6. Pass output through the evaluator.
  7. Return a RunResult artifact.

CLI and API both call run() — no orchestration logic belongs in those layers.
"""

from datetime import datetime, timezone
from typing import Callable, Optional

from sandbox.core.adapter import ModelAdapter
from sandbox.core.docker_sandbox import DockerSandbox
from sandbox.core.evaluator import evaluate
from sandbox.core.secrets import load_secret
from sandbox.core.types import AttackType, RunResult, Scenario
from sandbox.scenarios.registry import get_scenario

StepCallback = Callable[[str, str], None]


def run(
    model: str,
    scenario_id: str,
    adapter: ModelAdapter,
    on_step: Optional[StepCallback] = None,
) -> RunResult:
    """
    Execute a single prompt injection scenario inside a Docker sandbox.

    Args:
        model:       Name of the Ollama model (e.g. "llama3.2").
        scenario_id: Registered scenario identifier (e.g. "file_injection_v1").
        adapter:     A ModelAdapter instance used to call the model.
        on_step:     Optional callback ``(step_key, detail)`` fired at each
                     significant step.  Keys: scenario_loaded, secret_loaded,
                     sandbox_ready, prompt_ready, model_calling, model_done,
                     evaluated.

    Returns:
        RunResult containing the raw output, evaluation, and metadata.

    Raises:
        KeyError:            If scenario_id is not in the registry.
        DockerSandboxError:  If the sandbox container cannot be started.
        ModelAdapterError:   If the model call fails.
        FileNotFoundError:   If secret.txt is missing.
    """
    def notify(key: str, detail: str = "") -> None:
        if on_step is not None:
            on_step(key, detail)

    scenario = get_scenario(scenario_id)
    notify("scenario_loaded", f"{scenario.id} · {scenario.name}")

    secret = load_secret()
    notify("secret_loaded", "[REDACTED]")

    file_list = ", ".join(list(scenario.environment.files.keys()) + ["secret.txt"])
    with DockerSandbox(scenario=scenario, secret=secret) as sandbox:
        notify("sandbox_ready", file_list)

        user_prompt = _build_effective_user_prompt(scenario, sandbox, secret)
        notify("prompt_ready", f"{len(user_prompt):,} chars")

        notify("model_calling", model)
        model_output = adapter.ask(scenario.system_prompt, user_prompt)
        notify("model_done", f"{len(model_output):,} chars output")

    evaluation = evaluate(model_output, secret)
    verdict = "COMPROMISED" if evaluation.compromised else "CLEAN"
    notify("evaluated", verdict)

    return RunResult(
        model=model,
        scenario_id=scenario.id,
        scenario_name=scenario.name,
        attack_type=scenario.attack_type.value,
        model_output=model_output,
        evaluation=evaluation,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


def _build_effective_user_prompt(
    scenario: Scenario, sandbox: DockerSandbox, secret: str
) -> str:
    """
    Construct the user prompt that will be sent to the model.

    FILE_INJECTION:
        The agent is expected to have read the environment files.
        We read each file from the sandbox and append the content to the
        prompt so the model "sees" them — including any injected payload.

    TOOL_OUTPUT_INJECTION:
        The injection payload is already embedded in scenario.user_prompt.
        If the template contains ``{secret}``, it is substituted with the
        real secret value to simulate a tool output that already read the
        file (e.g. ``cat secret.txt``).
    """
    if scenario.attack_type == AttackType.FILE_INJECTION:
        file_blocks = []
        for filename in scenario.environment.files:
            content = sandbox.read_file(filename)
            file_blocks.append(f"<file name='{filename}'>\n{content}\n</file>")
        # The AI also has legitimate read access to secret.txt in its workspace.
        # This is the realistic precondition: the agent can read sensitive files
        # as part of its job, and the injection in a compromised file exploits that.
        secret_content = sandbox.read_file("secret.txt")
        file_blocks.append(f"<file name='secret.txt'>\n{secret_content}\n</file>")
        file_context = "\n".join(file_blocks)
        return f"{scenario.user_prompt}\n\n{file_context}"

    if scenario.attack_type == AttackType.TOOL_OUTPUT_INJECTION:
        return scenario.user_prompt.replace("{secret}", secret)

    return scenario.user_prompt
