"""Tests for chatbot module — AI-powered assistant with GitHub issue creation."""

from unittest.mock import patch, MagicMock

import pytest

from chatbot import process_chat_message, get_chat_history, clear_chat_session, CHAT_SESSIONS


@pytest.fixture(autouse=True)
def clear_sessions():
    CHAT_SESSIONS.clear()
    yield
    CHAT_SESSIONS.clear()


class TestChatbot:
    def test_process_chat_message_general(self):
        """General messages get a help/FAQ reply without calling OpenAI."""
        result = process_chat_message("session-1", "Hello")
        assert "reply" in result
        assert len(result["reply"]) > 0

    def test_get_chat_history_empty(self):
        history = get_chat_history("no-such-session")
        assert history == []

    def test_chat_history_accumulates(self):
        """General replies accumulate in session history."""
        process_chat_message("session-2", "Q1")
        process_chat_message("session-2", "Q2")
        history = get_chat_history("session-2")
        # Each call adds user + assistant = 2 entries; 2 calls = 4
        assert len(history) >= 4

    def test_clear_chat_session(self):
        CHAT_SESSIONS["session-x"] = [{"role": "user", "content": "test"}]
        clear_chat_session("session-x")
        assert "session-x" not in CHAT_SESSIONS

    def test_clear_nonexistent_session(self):
        # Should not raise
        clear_chat_session("does-not-exist")
