"""
Archmorph — Unit Tests for IaC Chat Module
============================================

Tests the iac_chat.py module:
  - Session management (history, clear)
  - GPT-4o IaC chat processing (mocked)
  - API endpoint integration tests
"""

import io
import json
import os
import sys
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from iac_chat import (
    process_iac_chat,
    get_iac_chat_history,
    clear_iac_chat,
    IAC_CHAT_SESSIONS,
)


SAMPLE_TF_CODE = """
resource "azurerm_resource_group" "rg" {
  name     = "rg-archmorph-dev"
  location = "westeurope"
  tags = {
    environment = "dev"
    project     = "archmorph"
  }
}
""".strip()

MOCK_CHAT_RESPONSE = {
    "message": "Added a Virtual Network with 3 subnets.",
    "code": SAMPLE_TF_CODE + '\n\nresource "azurerm_virtual_network" "vnet" {\n  name = "vnet-archmorph-dev"\n  location = azurerm_resource_group.rg.location\n  resource_group_name = azurerm_resource_group.rg.name\n  address_space = ["10.0.0.0/16"]\n}',
    "changes_summary": ["Added azurerm_virtual_network", "Used 10.0.0.0/16 address space"],
    "services_added": ["Azure Virtual Network"],
}


# ====================================================================
# 1. Session Management
# ====================================================================

class TestSessionManagement:
    def setup_method(self):
        IAC_CHAT_SESSIONS.clear()

    def test_get_empty_history(self):
        history = get_iac_chat_history("nonexistent-diagram")
        assert history == []

    def test_clear_nonexistent_session(self):
        result = clear_iac_chat("nonexistent-diagram")
        assert result is False

    def test_clear_existing_session(self):
        IAC_CHAT_SESSIONS["test-1:iac"] = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        result = clear_iac_chat("test-1")
        assert result is True
        assert "test-1:iac" not in IAC_CHAT_SESSIONS

    def test_get_history_returns_stored_messages(self):
        IAC_CHAT_SESSIONS["test-hist:iac"] = [
            {"role": "user", "content": "Add VNet", "ts": "2026-01-01T00:00:00"},
            {"role": "assistant", "content": "Done", "ts": "2026-01-01T00:00:01"},
        ]
        history = get_iac_chat_history("test-hist")
        assert len(history) == 2
        assert history[0]["role"] == "user"
        assert history[1]["role"] == "assistant"


# ====================================================================
# 2. GPT-4o IaC Chat Processing (Mocked)
# ====================================================================

class TestIacChatProcessing:
    def setup_method(self):
        IAC_CHAT_SESSIONS.clear()

    @patch("iac_chat.cached_chat_completion")
    @patch("iac_chat._apply_validation", side_effect=lambda code, _format: code)
    def test_process_iac_chat_returns_result(self, mock_validation, mock_completion):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps(MOCK_CHAT_RESPONSE)
        mock_response.choices[0].finish_reason = "stop"
        mock_completion.return_value = mock_response

        result = process_iac_chat(
            diagram_id="test-diagram",
            message="Add a VNet with 3 subnets",
            current_code=SAMPLE_TF_CODE,
            iac_format="terraform",
        )

        assert "reply" in result
        assert "code" in result
        assert "changes_summary" in result
        assert "services_added" in result
        assert result["error"] is False
        mock_validation.assert_called_once()

    @patch("iac_chat.cached_chat_completion")
    def test_process_iac_chat_stores_history(self, mock_completion):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps(MOCK_CHAT_RESPONSE)
        mock_response.choices[0].finish_reason = "stop"
        mock_completion.return_value = mock_response

        process_iac_chat("test-hist", "Add VNet", SAMPLE_TF_CODE)

        history = get_iac_chat_history("test-hist")
        assert len(history) == 2
        assert history[0]["role"] == "user"
        assert history[0]["content"] == "Add VNet"
        assert history[1]["role"] == "assistant"

    @patch("iac_chat.cached_chat_completion")
    def test_process_iac_chat_sends_code_in_prompt(self, mock_completion):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps(MOCK_CHAT_RESPONSE)
        mock_response.choices[0].finish_reason = "stop"
        mock_completion.return_value = mock_response

        process_iac_chat("test-prompt", "Add storage", SAMPLE_TF_CODE, "terraform")

        call_args = mock_completion.call_args
        messages = call_args.kwargs["messages"]
        user_msg = messages[-1]["content"]
        assert "azurerm_resource_group" in user_msg
        assert "Add storage" in user_msg
        assert "Terraform" in user_msg

    @patch("iac_chat.cached_chat_completion")
    def test_process_iac_chat_with_analysis_context(self, mock_completion):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps(MOCK_CHAT_RESPONSE)
        mock_response.choices[0].finish_reason = "stop"
        mock_completion.return_value = mock_response

        context = {
            "source_provider": "aws",
            "services_detected": 10,
            "architecture_patterns": ["event-driven"],
            "zones": [{"name": "test"}],
        }
        process_iac_chat("test-ctx", "Add VNet", SAMPLE_TF_CODE, "terraform", context)

        call_args = mock_completion.call_args
        messages = call_args.kwargs["messages"]
        system_msg = messages[0]["content"]
        assert "AWS" in system_msg
        assert "event-driven" in system_msg

    @patch("iac_chat.cached_chat_completion")
    def test_process_iac_chat_api_error(self, mock_completion):
        mock_completion.side_effect = Exception("API timeout")

        result = process_iac_chat("test-err", "Add VNet", SAMPLE_TF_CODE)

        assert result["error"] is True
        assert result["code"] == SAMPLE_TF_CODE  # Returns original code on error
        assert "error" in result["reply"].lower() or "unexpected" in result["reply"].lower()

    @patch("iac_chat.cached_chat_completion")
    def test_process_iac_chat_json_error(self, mock_completion):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "not valid json {{"
        mock_response.choices[0].finish_reason = "stop"
        mock_completion.return_value = mock_response

        result = process_iac_chat("test-json-err", "Add VNet", SAMPLE_TF_CODE)

        assert result["error"] is True
        assert result["code"] == SAMPLE_TF_CODE

    @patch("iac_chat.cached_chat_completion")
    def test_process_iac_chat_bicep_format(self, mock_completion):
        bicep_response = {
            "message": "Added VNet.",
            "code": "param location string = 'westeurope'\nresource vnet 'Microsoft.Network/virtualNetworks@2023-05-01' = {}",
            "changes_summary": ["Added VNet"],
            "services_added": ["VNet"],
        }
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps(bicep_response)
        mock_response.choices[0].finish_reason = "stop"
        mock_completion.return_value = mock_response

        process_iac_chat("test-bicep", "Add VNet", "param location string", "bicep")

        call_args = mock_completion.call_args
        messages = call_args.kwargs["messages"]
        user_msg = messages[-1]["content"]
        assert "Bicep" in user_msg

    @patch("iac_chat.cached_chat_completion")
    def test_process_iac_chat_conversation_flow(self, mock_completion):
        """Test multi-turn conversation preserves history."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].finish_reason = "stop"

        # Turn 1
        resp1 = {"message": "Added VNet", "code": "# code1", "changes_summary": [], "services_added": []}
        mock_response.choices[0].message.content = json.dumps(resp1)
        mock_completion.return_value = mock_response
        process_iac_chat("test-conv", "Add VNet", SAMPLE_TF_CODE)

        # Turn 2
        resp2 = {"message": "Added NSG", "code": "# code2", "changes_summary": [], "services_added": []}
        mock_response.choices[0].message.content = json.dumps(resp2)
        process_iac_chat("test-conv", "Now add NSG", "# code1")

        # Verify history has 4 messages (2 turns)
        history = get_iac_chat_history("test-conv")
        assert len(history) == 4

        # Verify GPT-4o received conversation history on 2nd call
        call_args = mock_completion.call_args
        messages = call_args.kwargs["messages"]
        # System + 2 history msgs (from turn 1) + current user = 4
        assert len(messages) >= 4


# ====================================================================
# 3. IaC Chat API Endpoint Integration Tests
# ====================================================================

class TestIacChatEndpoints:
    @pytest.fixture(scope="module")
    def client(self):
        from fastapi.testclient import TestClient
        from main import app
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c

    @pytest.fixture
    def analyzed_diagram(self, client):
        from main import SESSION_STORE, IMAGE_STORE
        SESSION_STORE.clear()
        IMAGE_STORE.clear()
        IAC_CHAT_SESSIONS.clear()

        content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        resp = client.post(
            "/api/projects/proj-iac/diagrams",
            files={"file": ("arch.png", io.BytesIO(content), "image/png")},
        )
        diagram_id = resp.json()["diagram_id"]

        mock_analysis = {
            "diagram_type": "Test", "source_provider": "aws", "target_provider": "azure",
            "architecture_patterns": [], "services_detected": 1,
            "zones": [{"id": 1, "name": "Test", "number": 1, "services": [
                {"aws": "S3", "azure": "Blob Storage", "confidence": 0.95},
            ]}],
            "mappings": [{"source_service": "S3", "source_provider": "aws", "azure_service": "Blob Storage", "confidence": 0.95}],
            "warnings": [],
            "confidence_summary": {"high": 1, "medium": 0, "low": 0, "average": 0.95},
        }
        with patch("routers.diagrams.analyze_image", return_value=mock_analysis):
            client.post(f"/api/diagrams/{diagram_id}/analyze")

        yield diagram_id
        SESSION_STORE.clear()
        IMAGE_STORE.clear()
        IAC_CHAT_SESSIONS.clear()

    @patch("iac_chat.cached_chat_completion")
    def test_iac_chat_endpoint(self, mock_completion, client, analyzed_diagram):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps(MOCK_CHAT_RESPONSE)
        mock_response.choices[0].finish_reason = "stop"
        mock_completion.return_value = mock_response

        resp = client.post(
            f"/api/diagrams/{analyzed_diagram}/iac-chat",
            json={"message": "Add VNet", "code": SAMPLE_TF_CODE, "format": "terraform"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "reply" in data
        assert "code" in data
        assert data["error"] is False

    def test_iac_chat_history_endpoint(self, client, analyzed_diagram):
        resp = client.get(f"/api/diagrams/{analyzed_diagram}/iac-chat/history")
        assert resp.status_code == 200
        data = resp.json()
        assert "messages" in data
        assert data["diagram_id"] == analyzed_diagram

    def test_iac_chat_clear_endpoint(self, client, analyzed_diagram):
        IAC_CHAT_SESSIONS[f"{analyzed_diagram}:iac"] = [{"role": "user", "content": "test"}]

        resp = client.delete(f"/api/diagrams/{analyzed_diagram}/iac-chat")
        assert resp.status_code == 200
        assert resp.json()["cleared"] is True

    def test_iac_chat_clear_nonexistent(self, client):
        resp = client.delete("/api/diagrams/nonexistent-diagram/iac-chat")
        assert resp.status_code == 200
        assert resp.json()["cleared"] is False


# ====================================================================
# 4. Defensive coercion of changes_summary / services_added
#    (Regression for React error #31 on {type, message} objects)
# ====================================================================

from iac_chat import _coerce_to_str_list


class TestCoerceToStrList:
    def test_strings_pass_through(self):
        assert _coerce_to_str_list(["a", "b"]) == ["a", "b"]

    def test_dict_with_message_key(self):
        # The exact shape that triggered React error #31 in production.
        out = _coerce_to_str_list([{"type": "add", "message": "Added VNet"}])
        assert out == ["Added VNet"]

    def test_dict_with_text_or_name_or_label_or_value(self):
        assert _coerce_to_str_list([{"text": "x"}]) == ["x"]
        assert _coerce_to_str_list([{"name": "Azure SQL"}]) == ["Azure SQL"]
        assert _coerce_to_str_list([{"label": "lbl"}]) == ["lbl"]
        assert _coerce_to_str_list([{"value": "v"}]) == ["v"]

    def test_dict_with_no_known_key_serializes(self):
        out = _coerce_to_str_list([{"foo": "bar"}])
        assert out == ['{"foo": "bar"}']

    def test_drops_none_keeps_falsy_strings(self):
        assert _coerce_to_str_list([None, "", "x"]) == ["", "x"]

    def test_non_list_input_returns_empty(self):
        assert _coerce_to_str_list(None) == []
        assert _coerce_to_str_list("not a list") == []
        assert _coerce_to_str_list({"k": "v"}) == []

    def test_numbers_and_bools_coerced(self):
        assert _coerce_to_str_list([1, 2.5, True, False]) == ["1", "2.5", "True", "False"]

    def test_nested_lists_stringified(self):
        out = _coerce_to_str_list([["nested"]])
        assert isinstance(out[0], str)

    @patch("iac_chat.cached_chat_completion")
    def test_process_iac_chat_normalizes_object_items(self, mock_completion):
        # Simulate a misbehaving model returning {type, message} objects.
        bad_response = {
            "message": "Updated.",
            "code": SAMPLE_TF_CODE,
            "changes_summary": [
                {"type": "add", "message": "Added VNet"},
                {"type": "modify", "message": "Resized subnet"},
                "plain string",
            ],
            "services_added": [{"name": "VNet"}, {"name": "NSG"}],
        }
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps(bad_response)
        mock_response.choices[0].finish_reason = "stop"
        mock_completion.return_value = mock_response

        result = process_iac_chat(
            diagram_id="coerce-test",
            message="Add a VNet",
            current_code=SAMPLE_TF_CODE,
            iac_format="terraform",
        )

        assert result["error"] is False
        # Every item must be a string (renderable in JSX without crashing React).
        assert all(isinstance(c, str) for c in result["changes_summary"])
        assert all(isinstance(s, str) for s in result["services_added"])
        assert result["changes_summary"] == ["Added VNet", "Resized subnet", "plain string"]
        assert result["services_added"] == ["VNet", "NSG"]

