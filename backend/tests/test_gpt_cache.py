"""Tests for GPT response caching in openai_client (Issue #77)."""

import os
import sys
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import openai_client


@pytest.fixture(autouse=True)
def clean():
    openai_client.reset_client()
    openai_client.reset_cache()
    yield
    openai_client.reset_client()
    openai_client.reset_cache()


class TestCacheKey:
    def test_deterministic(self):
        msgs = [{"role": "user", "content": "hello"}]
        k1 = openai_client._compute_cache_key(messages=msgs, model="gpt-4o")
        k2 = openai_client._compute_cache_key(messages=msgs, model="gpt-4o")
        assert k1 == k2

    def test_different_input_different_key(self):
        k1 = openai_client._compute_cache_key(
            messages=[{"role": "user", "content": "A"}], model="gpt-4o"
        )
        k2 = openai_client._compute_cache_key(
            messages=[{"role": "user", "content": "B"}], model="gpt-4o"
        )
        assert k1 != k2

    def test_different_model_different_key(self):
        msgs = [{"role": "user", "content": "hello"}]
        k1 = openai_client._compute_cache_key(messages=msgs, model="gpt-4o")
        k2 = openai_client._compute_cache_key(messages=msgs, model="gpt-35-turbo")
        assert k1 != k2


class TestCacheStats:
    def test_initial_stats(self):
        stats = openai_client.get_cache_stats()
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["hit_rate"] == 0.0
        assert stats["size"] == 0

    def test_reset_cache(self):
        openai_client._cache_hits = 5
        openai_client._cache_misses = 3
        openai_client._response_cache["x"] = "y"
        openai_client.reset_cache()
        assert openai_client.get_cache_stats()["hits"] == 0
        assert openai_client.get_cache_stats()["size"] == 0


class TestCachedChatCompletion:
    @patch("openai_client.get_openai_client")
    def test_cache_hit(self, mock_get_client):
        mock_client = MagicMock()
        fake_resp = MagicMock()
        fake_resp.choices = [MagicMock(message=MagicMock(content="cached"))]
        mock_client.chat.completions.create.return_value = fake_resp
        mock_get_client.return_value = mock_client

        msgs = [{"role": "user", "content": "test prompt"}]

        # First call — cache miss
        r1 = openai_client.cached_chat_completion(msgs, model="gpt-4o")
        assert mock_client.chat.completions.create.call_count == 1

        # Second call — cache hit
        r2 = openai_client.cached_chat_completion(msgs, model="gpt-4o")
        assert mock_client.chat.completions.create.call_count == 1  # no extra call
        assert r1 is r2

        stats = openai_client.get_cache_stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1

    @patch("openai_client.get_openai_client")
    def test_bypass_cache(self, mock_get_client):
        mock_client = MagicMock()
        fake_resp = MagicMock()
        mock_client.chat.completions.create.return_value = fake_resp
        mock_get_client.return_value = mock_client

        msgs = [{"role": "user", "content": "test"}]

        openai_client.cached_chat_completion(msgs)
        openai_client.cached_chat_completion(msgs, bypass_cache=True)
        # bypass_cache should force a new call even though key exists
        assert mock_client.chat.completions.create.call_count == 2

    @patch("openai_client.get_openai_client")
    def test_different_params_no_hit(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = MagicMock()
        mock_get_client.return_value = mock_client

        openai_client.cached_chat_completion(
            [{"role": "user", "content": "a"}], temperature=0.0
        )
        openai_client.cached_chat_completion(
            [{"role": "user", "content": "a"}], temperature=1.0
        )
        assert mock_client.chat.completions.create.call_count == 2
        assert openai_client.get_cache_stats()["misses"] == 2
