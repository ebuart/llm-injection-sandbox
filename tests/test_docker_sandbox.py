"""
Unit tests for sandbox.core.docker_sandbox.

The Docker SDK client and container are fully mocked — no daemon required.
All tests verify behaviour and invariants of DockerSandbox without any I/O.
"""

import io
import tarfile
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import docker.errors
import pytest

from sandbox.core.docker_sandbox import (
    SANDBOX_IMAGE,
    WORKSPACE_DIR,
    DockerSandbox,
    DockerSandboxError,
)
from sandbox.core.types import AttackType, Scenario, ScenarioEnvironment

SECRET = "CONFIDENTIAL-SECRET-XK29-ALPHA"

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_SCENARIO = Scenario(
    id="test_scenario",
    name="Test",
    description="Unit-test scenario",
    attack_type=AttackType.FILE_INJECTION,
    system_prompt="system",
    user_prompt="user",
    environment=ScenarioEnvironment(files={"README.md": "payload content"}),
)


def _make_exec_result(exit_code: int, output: bytes) -> SimpleNamespace:
    return SimpleNamespace(exit_code=exit_code, output=output)


def _make_docker_client(container: MagicMock = None) -> MagicMock:
    client = MagicMock()
    client.containers.create.return_value = container or MagicMock()
    return client


# ---------------------------------------------------------------------------
# Container creation
# ---------------------------------------------------------------------------


def test_start_creates_container_from_sandbox_image():
    container = MagicMock()
    container.exec_run.return_value = _make_exec_result(0, b"")
    client = _make_docker_client(container)

    sandbox = DockerSandbox(scenario=_SCENARIO, secret=SECRET, client=client)
    sandbox.start()
    sandbox.stop()

    client.containers.create.assert_called_once()
    call_kwargs = client.containers.create.call_args
    assert call_kwargs.args[0] == SANDBOX_IMAGE


def test_start_disables_network():
    container = MagicMock()
    container.exec_run.return_value = _make_exec_result(0, b"")
    client = _make_docker_client(container)

    sandbox = DockerSandbox(scenario=_SCENARIO, secret=SECRET, client=client)
    sandbox.start()
    sandbox.stop()

    call_kwargs = client.containers.create.call_args.kwargs
    assert call_kwargs["network_disabled"] is True


def test_start_calls_container_start():
    container = MagicMock()
    container.exec_run.return_value = _make_exec_result(0, b"")
    client = _make_docker_client(container)

    sandbox = DockerSandbox(scenario=_SCENARIO, secret=SECRET, client=client)
    sandbox.start()
    sandbox.stop()

    container.start.assert_called_once()


# ---------------------------------------------------------------------------
# File writing
# ---------------------------------------------------------------------------


def test_start_writes_scenario_files_via_put_archive():
    container = MagicMock()
    container.exec_run.return_value = _make_exec_result(0, b"")
    client = _make_docker_client(container)

    sandbox = DockerSandbox(scenario=_SCENARIO, secret=SECRET, client=client)
    sandbox.start()
    sandbox.stop()

    # put_archive called for each environment file + secret.txt
    expected_call_count = len(_SCENARIO.environment.files) + 1  # +1 for secret.txt
    assert container.put_archive.call_count == expected_call_count


def test_start_writes_secret_file():
    container = MagicMock()
    container.exec_run.return_value = _make_exec_result(0, b"")
    client = _make_docker_client(container)

    # Capture what was written via put_archive
    written_files: dict[str, str] = {}

    def capture_archive(path, data):
        buf = io.BytesIO(data.read())
        with tarfile.open(fileobj=buf) as tar:
            for member in tar.getmembers():
                written_files[member.name] = tar.extractfile(member).read().decode()

    container.put_archive.side_effect = capture_archive

    sandbox = DockerSandbox(scenario=_SCENARIO, secret=SECRET, client=client)
    sandbox.start()
    sandbox.stop()

    assert "secret.txt" in written_files
    assert written_files["secret.txt"] == SECRET


def test_start_writes_environment_files_with_correct_content():
    container = MagicMock()
    container.exec_run.return_value = _make_exec_result(0, b"")
    client = _make_docker_client(container)

    written_files: dict[str, str] = {}

    def capture_archive(path, data):
        buf = io.BytesIO(data.read())
        with tarfile.open(fileobj=buf) as tar:
            for member in tar.getmembers():
                written_files[member.name] = tar.extractfile(member).read().decode()

    container.put_archive.side_effect = capture_archive

    sandbox = DockerSandbox(scenario=_SCENARIO, secret=SECRET, client=client)
    sandbox.start()
    sandbox.stop()

    assert "README.md" in written_files
    assert written_files["README.md"] == "payload content"


def test_put_archive_targets_workspace_dir():
    container = MagicMock()
    container.exec_run.return_value = _make_exec_result(0, b"")
    client = _make_docker_client(container)

    sandbox = DockerSandbox(scenario=_SCENARIO, secret=SECRET, client=client)
    sandbox.start()
    sandbox.stop()

    for archive_call in container.put_archive.call_args_list:
        assert archive_call.args[0] == WORKSPACE_DIR


# ---------------------------------------------------------------------------
# read_file
# ---------------------------------------------------------------------------


def test_read_file_returns_file_content():
    container = MagicMock()
    container.exec_run.return_value = _make_exec_result(0, b"hello content")
    client = _make_docker_client(container)

    sandbox = DockerSandbox(scenario=_SCENARIO, secret=SECRET, client=client)
    sandbox.start()
    result = sandbox.read_file("README.md")
    sandbox.stop()

    assert result == "hello content"


def test_read_file_uses_cat_command():
    container = MagicMock()
    container.exec_run.return_value = _make_exec_result(0, b"content")
    client = _make_docker_client(container)

    sandbox = DockerSandbox(scenario=_SCENARIO, secret=SECRET, client=client)
    sandbox.start()
    sandbox.read_file("myfile.txt")
    sandbox.stop()

    # The last exec_run call (after start's writes) should be the cat
    last_call = container.exec_run.call_args
    cmd = last_call.args[0]
    assert "cat" in cmd
    assert f"{WORKSPACE_DIR}/myfile.txt" in cmd


def test_read_file_raises_on_nonzero_exit():
    container = MagicMock()
    # start writes succeed, read fails
    container.exec_run.return_value = _make_exec_result(1, b"No such file")
    client = _make_docker_client(container)

    sandbox = DockerSandbox(scenario=_SCENARIO, secret=SECRET, client=client)
    sandbox.start()
    with pytest.raises(DockerSandboxError, match="README.md"):
        sandbox.read_file("README.md")
    sandbox.stop()


def test_read_file_raises_when_sandbox_not_started():
    client = _make_docker_client()
    sandbox = DockerSandbox(scenario=_SCENARIO, secret=SECRET, client=client)
    with pytest.raises(DockerSandboxError):
        sandbox.read_file("anything.txt")


# ---------------------------------------------------------------------------
# Stop / cleanup
# ---------------------------------------------------------------------------


def test_stop_removes_container_with_force():
    container = MagicMock()
    container.exec_run.return_value = _make_exec_result(0, b"")
    client = _make_docker_client(container)

    sandbox = DockerSandbox(scenario=_SCENARIO, secret=SECRET, client=client)
    sandbox.start()
    sandbox.stop()

    container.remove.assert_called_once_with(force=True)


def test_stop_clears_container_reference():
    container = MagicMock()
    container.exec_run.return_value = _make_exec_result(0, b"")
    client = _make_docker_client(container)

    sandbox = DockerSandbox(scenario=_SCENARIO, secret=SECRET, client=client)
    sandbox.start()
    sandbox.stop()

    # After stop, container reference is cleared
    assert sandbox._container is None


def test_stop_is_idempotent():
    container = MagicMock()
    container.exec_run.return_value = _make_exec_result(0, b"")
    client = _make_docker_client(container)

    sandbox = DockerSandbox(scenario=_SCENARIO, secret=SECRET, client=client)
    sandbox.start()
    sandbox.stop()
    sandbox.stop()  # second call must not raise

    container.remove.assert_called_once()  # only called once


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------


def test_context_manager_calls_start_and_stop():
    container = MagicMock()
    container.exec_run.return_value = _make_exec_result(0, b"")
    client = _make_docker_client(container)

    with DockerSandbox(scenario=_SCENARIO, secret=SECRET, client=client):
        container.start.assert_called_once()

    container.remove.assert_called_once_with(force=True)


def test_context_manager_stops_on_exception():
    container = MagicMock()
    container.exec_run.return_value = _make_exec_result(0, b"")
    client = _make_docker_client(container)

    with pytest.raises(RuntimeError):
        with DockerSandbox(scenario=_SCENARIO, secret=SECRET, client=client):
            raise RuntimeError("simulated failure")

    container.remove.assert_called_once_with(force=True)


def test_context_manager_does_not_suppress_exceptions():
    container = MagicMock()
    container.exec_run.return_value = _make_exec_result(0, b"")
    client = _make_docker_client(container)

    with pytest.raises(ValueError):
        with DockerSandbox(scenario=_SCENARIO, secret=SECRET, client=client):
            raise ValueError("must propagate")


# ---------------------------------------------------------------------------
# Error handling — image not found
# ---------------------------------------------------------------------------


def test_start_raises_docker_sandbox_error_on_missing_image():
    client = MagicMock()
    client.containers.create.side_effect = docker.errors.ImageNotFound("not found")

    sandbox = DockerSandbox(scenario=_SCENARIO, secret=SECRET, client=client)
    with pytest.raises(DockerSandboxError, match=SANDBOX_IMAGE):
        sandbox.start()


def test_start_raises_docker_sandbox_error_on_docker_exception():
    client = MagicMock()
    client.containers.create.side_effect = docker.errors.DockerException("daemon error")

    sandbox = DockerSandbox(scenario=_SCENARIO, secret=SECRET, client=client)
    with pytest.raises(DockerSandboxError):
        sandbox.start()
