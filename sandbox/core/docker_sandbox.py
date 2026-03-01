"""
Docker sandbox — isolated execution environment for benchmark scenarios.

Responsibilities:
  - Create and start a container from the sandbox image with network disabled.
  - Write scenario environment files (and secret.txt) into /workspace inside the container.
  - Expose read_file() so the runner can pull file contents back to the host.
  - Guarantee cleanup: container is always removed in __exit__ / stop().

Security invariants upheld here:
  - Network is disabled on the container at creation time.
  - secret.txt is written into the isolated container; it is never logged or
    passed to the model adapter.
  - Files are written via tar archive (no shell interpolation of file content).
"""

import io
import tarfile
from types import TracebackType
from typing import Optional, Type

import docker
import docker.errors

from sandbox.core.types import Scenario

SANDBOX_IMAGE = "llm-injection-sandbox:latest"
WORKSPACE_DIR = "/workspace"


class DockerSandboxError(Exception):
    """Raised when a Docker operation fails."""


class DockerSandbox:
    """
    Manages the lifecycle of a single Docker container for one scenario run.

    Usage::

        with DockerSandbox(scenario=scenario, secret=secret) as sandbox:
            content = sandbox.read_file("README.md")
    """

    def __init__(
        self,
        scenario: Scenario,
        secret: str,
        client: Optional[docker.DockerClient] = None,
    ) -> None:
        self._scenario = scenario
        self._secret = secret
        self._client: docker.DockerClient = client or docker.from_env()
        self._container = None

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "DockerSandbox":
        self.start()
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> bool:
        self.stop()
        return False  # never suppress exceptions

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """
        Create and start the sandbox container, then write all scenario files.

        Raises:
            DockerSandboxError: If the image is missing or the container fails to start.
        """
        try:
            self._container = self._client.containers.create(
                SANDBOX_IMAGE,
                command=["sleep", "infinity"],
                network_disabled=True,
                detach=True,
            )
            self._container.start()
        except docker.errors.ImageNotFound:
            raise DockerSandboxError(
                f"Sandbox image '{SANDBOX_IMAGE}' not found. "
                f"Build it with: docker build -t {SANDBOX_IMAGE} docker/"
            )
        except docker.errors.DockerException as exc:
            raise DockerSandboxError(f"Failed to start sandbox container: {exc}") from exc

        # Write scenario environment files
        for filename, content in self._scenario.environment.files.items():
            self._write_file(filename, content)

        # Write secret into the isolated environment.
        # Never logged; never returned from ask(); only used to
        # give the model an opportunity to leak it.
        self._write_file("secret.txt", self._secret)

    def stop(self) -> None:
        """Force-remove the container if it is running."""
        if self._container is not None:
            try:
                self._container.remove(force=True)
            except docker.errors.DockerException:
                pass  # best-effort cleanup
            finally:
                self._container = None

    # ------------------------------------------------------------------
    # File I/O
    # ------------------------------------------------------------------

    def read_file(self, filename: str) -> str:
        """
        Return the UTF-8 content of a file inside /workspace.

        Raises:
            DockerSandboxError: If the container is not running or the file is absent.
        """
        if self._container is None:
            raise DockerSandboxError("Sandbox is not running.")

        result = self._container.exec_run(["cat", f"{WORKSPACE_DIR}/{filename}"])
        if result.exit_code != 0:
            raise DockerSandboxError(
                f"File not found in sandbox workspace: {filename}"
            )
        return result.output.decode("utf-8")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _write_file(self, filename: str, content: str) -> None:
        """
        Write content into /workspace/<filename> using a tar archive transfer.

        Using put_archive avoids shell interpolation of file content entirely.
        """
        data = content.encode("utf-8")
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            info = tarfile.TarInfo(name=filename)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        buf.seek(0)
        self._container.put_archive(WORKSPACE_DIR, buf)
