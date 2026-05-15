"""Tests for openai_client module — shared Azure OpenAI client factory."""

import os
import threading
import time
from unittest.mock import patch, MagicMock

import pytest

# Reset singleton before each test
import openai_client


@pytest.fixture(autouse=True)
def reset():
    openai_client.reset_client()
    yield
    openai_client.reset_client()


class TestGetOpenAIClient:
    @patch.dict(os.environ, {"AZURE_OPENAI_KEY": "test-key-123"})
    @patch("openai_client.AzureOpenAI")
    def test_creates_client_with_api_key(self, mock_cls):
        mock_cls.return_value = MagicMock()
        openai_client.reset_client()
        # Force reload env var
        openai_client.AZURE_OPENAI_KEY = "test-key-123"
        client = openai_client.get_openai_client()
        assert client is not None
        mock_cls.assert_called_once()
        # Verify api_key was passed
        call_kwargs = mock_cls.call_args
        assert "test-key-123" in str(call_kwargs)

    @patch.dict(os.environ, {"AZURE_OPENAI_KEY": "test-key-123"})
    @patch("openai_client.AzureOpenAI")
    def test_returns_singleton(self, mock_cls):
        mock_cls.return_value = MagicMock()
        openai_client.reset_client()
        c1 = openai_client.get_openai_client()
        c2 = openai_client.get_openai_client()
        assert c1 is c2
        assert mock_cls.call_count == 1

    def test_reset_clears_singleton(self):
        openai_client._client = MagicMock()
        openai_client.reset_client()
        assert openai_client._client is None

    @patch("openai_client.get_bearer_token_provider", return_value=lambda: "token")
    @patch("openai_client.DefaultAzureCredential")
    @patch("openai_client.AzureOpenAI")
    def test_creates_client_with_credential(self, mock_cls, mock_cred, mock_token):
        mock_cls.return_value = MagicMock()
        openai_client.reset_client()
        # Force empty key to trigger credential path
        openai_client.AZURE_OPENAI_KEY = ""
        client = openai_client.get_openai_client()
        assert client is not None
        mock_cred.assert_called_once()


class TestOpenAIGuardrails:
    def test_retry_wait_honors_retry_after_header(self):
        rate_limit_error = MagicMock()
        rate_limit_error.response = MagicMock(headers={"Retry-After": "5"})
        rate_limit_error.status_code = 429
        retry_state = MagicMock()
        retry_state.attempt_number = 1
        retry_state.outcome = MagicMock()
        retry_state.outcome.exception.return_value = rate_limit_error

        delay = openai_client._retry_wait_seconds(retry_state)
        assert delay >= 5

    def test_retry_wait_does_not_cap_provider_retry_after(self):
        rate_limit_error = MagicMock()
        rate_limit_error.response = MagicMock(headers={"Retry-After": "180"})
        rate_limit_error.status_code = 429
        retry_state = MagicMock()
        retry_state.attempt_number = 1
        retry_state.outcome = MagicMock()
        retry_state.outcome.exception.return_value = rate_limit_error

        assert openai_client._retry_wait_seconds(retry_state) == 180

    def test_deployment_limit_uses_floor_per_worker(self, monkeypatch):
        monkeypatch.delenv("OPENAI_MAX_INFLIGHT_PER_WORKER", raising=False)
        monkeypatch.setenv("OPENAI_MAX_INFLIGHT_DEPLOYMENT", "16")
        monkeypatch.setenv("WEB_CONCURRENCY", "3")

        assert openai_client._openai_per_worker_limit() == 5

    def test_malformed_admission_timeout_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("OPENAI_ADMISSION_TIMEOUT_SECONDS", "not-a-float")

        assert openai_client._env_float("OPENAI_ADMISSION_TIMEOUT_SECONDS", 2.0) == 2.0

    def test_admission_queue_times_out_when_worker_slots_exhausted(self, monkeypatch):
        monkeypatch.setattr(openai_client, "_openai_inflight", threading.BoundedSemaphore(1))
        monkeypatch.setattr(openai_client, "OPENAI_ADMISSION_TIMEOUT_SECONDS", 0.01)

        start_gate = threading.Event()

        def slow():
            start_gate.set()
            time.sleep(0.05)
            return "ok"

        wrapped = openai_client.openai_retry(slow)
        first_result = {}

        def run_first():
            first_result["value"] = wrapped()

        thread = threading.Thread(target=run_first)
        thread.start()
        start_gate.wait(timeout=1)

        with pytest.raises(TimeoutError):
            wrapped()

        thread.join(timeout=1)
        assert first_result["value"] == "ok"
