"""
Model adapter layer.

Provides:
  ModelAdapter  — abstract interface; all adapters must implement ask().
  OllamaAdapter — concrete Ollama implementation over HTTP.
  ModelAdapterError — raised for transport or protocol failures.

No business logic lives here.  The adapter only translates prompts → raw text.
"""

from abc import ABC, abstractmethod

import httpx

OLLAMA_DEFAULT_URL = "http://localhost:11434"
OLLAMA_TIMEOUT_SECONDS = 120.0


class ModelAdapterError(Exception):
    """Raised when the model adapter cannot fulfil the request."""


class ModelAdapter(ABC):
    @abstractmethod
    def ask(self, system_prompt: str, user_prompt: str) -> str:
        """
        Send a prompt pair to the model and return the raw text response.

        Args:
            system_prompt: The system-role message.
            user_prompt:   The user-role message.

        Returns:
            Raw string output from the model.

        Raises:
            ModelAdapterError: On transport failure or unexpected response shape.
        """


class OllamaAdapter(ModelAdapter):
    """Calls a local Ollama instance via its /api/chat endpoint."""

    def __init__(
        self,
        model: str,
        base_url: str = OLLAMA_DEFAULT_URL,
        timeout: float = OLLAMA_TIMEOUT_SECONDS,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def ask(self, system_prompt: str, user_prompt: str) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
        }
        try:
            response = httpx.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ModelAdapterError(
                f"Ollama request failed for model '{self.model}': {exc}"
            ) from exc

        data = response.json()
        try:
            return data["message"]["content"]
        except (KeyError, TypeError) as exc:
            raise ModelAdapterError(
                f"Unexpected Ollama response shape: {data!r}"
            ) from exc
