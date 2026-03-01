"""
Unit tests for sandbox.core.adapter.

Ollama HTTP calls are fully mocked — no live model required.
"""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from sandbox.core.adapter import ModelAdapterError, OllamaAdapter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_response(content: str, status_code: int = 200) -> MagicMock:
    response = MagicMock(spec=httpx.Response)
    response.json.return_value = {"message": {"content": content}}
    response.status_code = status_code
    if status_code >= 400:
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            message="error", request=MagicMock(), response=response
        )
    else:
        response.raise_for_status.return_value = None
    return response


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_ask_returns_model_content():
    with patch("sandbox.core.adapter.httpx.post") as mock_post:
        mock_post.return_value = _mock_response("Hello from model")
        adapter = OllamaAdapter(model="test-model")
        result = adapter.ask("system prompt", "user prompt")
    assert result == "Hello from model"


def test_ask_sends_correct_model_name():
    with patch("sandbox.core.adapter.httpx.post") as mock_post:
        mock_post.return_value = _mock_response("")
        adapter = OllamaAdapter(model="llama3.2")
        adapter.ask("s", "u")
        payload = mock_post.call_args.kwargs["json"]
    assert payload["model"] == "llama3.2"


def test_ask_sends_system_and_user_messages():
    with patch("sandbox.core.adapter.httpx.post") as mock_post:
        mock_post.return_value = _mock_response("")
        adapter = OllamaAdapter(model="m")
        adapter.ask("sys-content", "usr-content")
        payload = mock_post.call_args.kwargs["json"]
    messages = payload["messages"]
    assert messages[0] == {"role": "system", "content": "sys-content"}
    assert messages[1] == {"role": "user", "content": "usr-content"}


def test_ask_disables_streaming():
    with patch("sandbox.core.adapter.httpx.post") as mock_post:
        mock_post.return_value = _mock_response("")
        adapter = OllamaAdapter(model="m")
        adapter.ask("s", "u")
        payload = mock_post.call_args.kwargs["json"]
    assert payload["stream"] is False


def test_ask_uses_correct_endpoint():
    with patch("sandbox.core.adapter.httpx.post") as mock_post:
        mock_post.return_value = _mock_response("")
        adapter = OllamaAdapter(model="m", base_url="http://localhost:11434")
        adapter.ask("s", "u")
        url = mock_post.call_args.args[0]
    assert url == "http://localhost:11434/api/chat"


def test_base_url_trailing_slash_normalised():
    with patch("sandbox.core.adapter.httpx.post") as mock_post:
        mock_post.return_value = _mock_response("")
        adapter = OllamaAdapter(model="m", base_url="http://localhost:11434/")
        adapter.ask("s", "u")
        url = mock_post.call_args.args[0]
    assert url == "http://localhost:11434/api/chat"


def test_ask_returns_empty_string_when_content_is_empty():
    with patch("sandbox.core.adapter.httpx.post") as mock_post:
        mock_post.return_value = _mock_response("")
        adapter = OllamaAdapter(model="m")
        result = adapter.ask("s", "u")
    assert result == ""


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_http_error_raises_model_adapter_error():
    with patch("sandbox.core.adapter.httpx.post") as mock_post:
        mock_post.side_effect = httpx.ConnectError("refused")
        adapter = OllamaAdapter(model="m")
        with pytest.raises(ModelAdapterError):
            adapter.ask("s", "u")


def test_http_status_error_raises_model_adapter_error():
    with patch("sandbox.core.adapter.httpx.post") as mock_post:
        mock_post.return_value = _mock_response("", status_code=500)
        adapter = OllamaAdapter(model="m")
        with pytest.raises(ModelAdapterError):
            adapter.ask("s", "u")


def test_malformed_response_raises_model_adapter_error():
    with patch("sandbox.core.adapter.httpx.post") as mock_post:
        response = MagicMock(spec=httpx.Response)
        response.raise_for_status.return_value = None
        response.json.return_value = {"unexpected": "shape"}
        mock_post.return_value = response
        adapter = OllamaAdapter(model="m")
        with pytest.raises(ModelAdapterError):
            adapter.ask("s", "u")


def test_model_adapter_error_contains_model_name():
    with patch("sandbox.core.adapter.httpx.post") as mock_post:
        mock_post.side_effect = httpx.ConnectError("refused")
        adapter = OllamaAdapter(model="llama3.2")
        with pytest.raises(ModelAdapterError, match="llama3.2"):
            adapter.ask("s", "u")
