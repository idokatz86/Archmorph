"""Tests for openai_client module — shared Azure OpenAI client factory."""

import os
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
