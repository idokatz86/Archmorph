"""Tests for chatbot module — GPT-4o powered AI assistant with GitHub issue creation."""

from unittest.mock import patch, MagicMock

import pytest

from chatbot import (
    process_chat_message, get_chat_history, clear_chat_session,
    CHAT_SESSIONS, _call_ai_assistant, _create_github_issue,
)


@pytest.fixture(autouse=True)
def clear_sessions():
    CHAT_SESSIONS.clear()
    yield
    CHAT_SESSIONS.clear()


class TestChatbot:
    """Basic chatbot functionality tests."""

    @patch("chatbot._call_ai_assistant")
    def test_process_chat_message_calls_ai(self, mock_ai):
        """Messages should be processed by GPT-4o AI assistant."""
        mock_ai.return_value = {"reply": "Hello! How can I help?", "action": None}
        result = process_chat_message("session-1", "Hello")
        assert "reply" in result
        assert result["ai_powered"] is True
        mock_ai.assert_called_once()

    def test_get_chat_history_empty(self):
        """Empty session should return empty history."""
        history = get_chat_history("no-such-session")
        assert history == []

    @patch("chatbot._call_ai_assistant")
    def test_chat_history_accumulates(self, mock_ai):
        """Messages accumulate in session history."""
        mock_ai.return_value = {"reply": "Response", "action": None}
        process_chat_message("session-2", "Q1")
        process_chat_message("session-2", "Q2")
        history = get_chat_history("session-2")
        # Each call adds user + assistant = 2 entries; 2 calls = 4
        assert len(history) >= 4

    def test_clear_chat_session(self):
        """Should clear session history."""
        CHAT_SESSIONS["session-x"] = [{"role": "user", "content": "test"}]
        result = clear_chat_session("session-x")
        assert result is True
        assert "session-x" not in CHAT_SESSIONS

    def test_clear_nonexistent_session(self):
        """Clearing non-existent session should return False."""
        result = clear_chat_session("does-not-exist")
        assert result is False


class TestAIAssistant:
    """Tests for GPT-4o AI assistant integration."""

    @patch("chatbot.get_openai_client")
    @patch("chatbot.openai_retry")
    def test_ai_assistant_returns_reply(self, mock_retry, mock_client):
        """AI assistant should return a reply from GPT-4o."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "I can help with that!"
        mock_response.usage.total_tokens = 100
        mock_retry.return_value = lambda **kwargs: mock_response

        result = _call_ai_assistant("How does Archmorph work?", [])
        assert "reply" in result
        assert result["reply"] == "I can help with that!"

    @patch("chatbot.get_openai_client")
    @patch("chatbot.openai_retry")
    def test_ai_assistant_extracts_bug_action(self, mock_retry, mock_client):
        """AI should extract bug creation actions from response."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '''I'll help you report that bug.
```json
{"action": "create_bug", "title": "Button broken", "description": "The submit button doesn't work"}
```
'''
        mock_response.usage.total_tokens = 150
        mock_retry.return_value = lambda **kwargs: mock_response

        result = _call_ai_assistant("The button is broken", [])
        assert result["action"] is not None
        assert result["action"]["action"] == "create_bug"
        assert "Button broken" in result["action"]["title"]

    @patch("chatbot.get_openai_client")
    @patch("chatbot.openai_retry")
    def test_ai_assistant_extracts_feature_action(self, mock_retry, mock_client):
        """AI should extract feature request actions from response."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '''Great idea! Let me create a feature request.
```json
{"action": "create_feature", "title": "Dark mode", "description": "Add dark theme support"}
```
'''
        mock_response.usage.total_tokens = 120
        mock_retry.return_value = lambda **kwargs: mock_response

        result = _call_ai_assistant("Can you add dark mode?", [])
        assert result["action"] is not None
        assert result["action"]["action"] == "create_feature"

    @patch("chatbot.get_openai_client")
    def test_ai_assistant_handles_error(self, mock_client):
        """AI should handle errors gracefully."""
        mock_client.side_effect = Exception("API unavailable")

        result = _call_ai_assistant("Hello", [])
        assert "error" in result
        assert "apologize" in result["reply"].lower() or "trouble" in result["reply"].lower()


class TestIssueCreation:
    """Tests for GitHub issue creation flow."""

    @patch("chatbot._call_ai_assistant")
    def test_bug_draft_flow(self, mock_ai):
        """AI detecting bug should create draft for confirmation."""
        mock_ai.return_value = {
            "reply": "I'll report this bug for you.",
            "action": {"action": "create_bug", "title": "Test bug", "description": "Bug details"},
        }

        result = process_chat_message("session-bug", "Report a bug: button doesn't work")
        assert result["action"] == "issue_draft"
        assert result["data"]["type"] == "bug"
        assert "yes" in result["reply"].lower()

    @patch("chatbot._call_ai_assistant")
    def test_feature_draft_flow(self, mock_ai):
        """AI detecting feature request should create draft for confirmation."""
        mock_ai.return_value = {
            "reply": "I'll create a feature request.",
            "action": {"action": "create_feature", "title": "New feature", "description": "Details"},
        }

        result = process_chat_message("session-feat", "I want a new feature")
        assert result["action"] == "issue_draft"
        assert result["data"]["type"] == "feature"

    @patch("chatbot._create_github_issue")
    @patch("chatbot._call_ai_assistant")
    def test_confirmation_creates_issue(self, mock_ai, mock_create):
        """Confirming draft should create GitHub issue."""
        # First, create a draft
        mock_ai.return_value = {
            "reply": "I'll report this.",
            "action": {"action": "create_bug", "title": "Bug title", "description": "Bug desc"},
        }
        process_chat_message("session-confirm", "Report bug: something broke")

        # Then confirm
        mock_create.return_value = {
            "success": True,
            "issue_number": 42,
            "issue_url": "https://github.com/test/issues/42",
            "title": "[Bug] Bug title",
        }
        result = process_chat_message("session-confirm", "yes")

        assert result["action"] == "bug_created"
        assert result["data"]["issue_number"] == 42
        mock_create.assert_called_once()


class TestGitHubIssueCreation:
    """Tests for direct GitHub issue creation."""

    @patch("chatbot.GITHUB_TOKEN", "")
    def test_no_token_returns_error(self):
        """Should return error when GitHub token not set."""
        result = _create_github_issue("Test", "Body", ["bug"])
        assert result["success"] is False
        assert "not configured" in result["error"].lower()

    @patch("chatbot.GITHUB_TOKEN", "fake-token")
    def test_creates_issue_successfully(self):
        """Should create issue with correct parameters."""
        with patch("github.Github") as mock_github_cls:
            mock_repo = MagicMock()
            mock_issue = MagicMock()
            mock_issue.number = 123
            mock_issue.html_url = "https://github.com/test/issues/123"
            mock_issue.title = "Test Issue"
            mock_issue.labels = [MagicMock(name="bug")]
            mock_repo.create_issue.return_value = mock_issue
            mock_repo.get_labels.return_value = [MagicMock(name="bug")]
            mock_github_cls.return_value.get_repo.return_value = mock_repo

            result = _create_github_issue("Test Issue", "Issue body", ["bug"])

            assert result["success"] is True
            assert result["issue_number"] == 123
            mock_repo.create_issue.assert_called_once()

    @patch("chatbot.GITHUB_TOKEN", "fake-token")
    def test_handles_api_error(self):
        """Should handle GitHub API errors."""
        with patch("github.Github") as mock_github_cls:
            mock_github_cls.return_value.get_repo.side_effect = Exception("Rate limited")

            result = _create_github_issue("Test", "Body", ["bug"])

            assert result["success"] is False
            assert "Rate limited" in result["error"]
