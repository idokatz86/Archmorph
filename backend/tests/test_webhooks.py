"""Comprehensive tests for webhooks.py and routers/webhooks.py — Sprint 9 #175."""
import asyncio
import pytest
from unittest.mock import patch

from webhooks import (
    register_webhook,
    list_webhooks,
    get_webhook,
    delete_webhook,
    update_webhook,
    dispatch_event,
    get_delivery_logs,
    get_delivery_stats,
    register_integration,
    list_integrations,
    delete_integration,
    get_integration,
    emit_event,
    _deliver_payload,
    compute_signature,
    verify_signature,
    validate_webhook_url,
    clear_all,
    ALL_EVENT_TYPES,
    INTEGRATION_REQUIREMENTS,
)


@pytest.fixture(autouse=True)
def reset_state():
    """Clear all webhook state between tests."""
    clear_all()
    yield
    clear_all()


# ---------------------------------------------------------------------------
# HMAC Signature
# ---------------------------------------------------------------------------

class TestSignature:
    def test_compute_and_verify(self):
        payload = b'{"event":"test"}'
        secret = "my-secret"
        sig = compute_signature(payload, secret)
        assert isinstance(sig, str)
        assert len(sig) == 64  # SHA-256 hex
        assert verify_signature(payload, secret, sig) is True

    def test_verify_wrong_secret(self):
        payload = b'{"event":"test"}'
        sig = compute_signature(payload, "correct-secret")
        assert verify_signature(payload, "wrong-secret", sig) is False

    def test_verify_wrong_payload(self):
        sig = compute_signature(b"payload1", "secret")
        assert verify_signature(b"payload2", "secret", sig) is False


# ---------------------------------------------------------------------------
# Webhook CRUD
# ---------------------------------------------------------------------------

class TestWebhookCRUD:
    def test_register_webhook(self):
        wh = register_webhook(
            url="https://example.com/hook",
            events=["analysis.completed"],
            description="Test hook",
        )
        assert wh.url == "https://example.com/hook"
        assert wh.events == ["analysis.completed"]
        assert wh.active is True
        assert wh.id.startswith("wh-")

    def test_register_generates_secret(self):
        wh = register_webhook(url="https://example.com/hook", events=["analysis.completed"])
        assert wh.secret  # auto-generated if not provided

    def test_register_custom_secret(self):
        wh = register_webhook(
            url="https://example.com/hook",
            events=["analysis.completed"],
            secret="my-secret-123",
        )
        assert wh.secret == "my-secret-123"

    def test_list_webhooks_empty(self):
        assert list_webhooks() == []

    def test_list_webhooks(self):
        register_webhook(url="https://a.com/hook", events=["analysis.completed"])
        register_webhook(url="https://b.com/hook", events=["iac.generated"])
        result = list_webhooks()
        assert len(result) == 2

    def test_list_webhooks_by_owner(self):
        register_webhook(url="https://a.com/hook", events=["analysis.completed"], owner_id="user1")
        register_webhook(url="https://b.com/hook", events=["iac.generated"], owner_id="user2")
        assert len(list_webhooks(owner_id="user1")) == 1

    def test_get_webhook(self):
        wh = register_webhook(url="https://example.com/hook", events=["analysis.completed"])
        fetched = get_webhook(wh.id)
        assert fetched is not None
        assert fetched.url == "https://example.com/hook"

    def test_get_webhook_not_found(self):
        assert get_webhook("nonexistent") is None

    def test_delete_webhook(self):
        wh = register_webhook(url="https://example.com/hook", events=["analysis.completed"])
        assert delete_webhook(wh.id) is True
        assert get_webhook(wh.id) is None

    def test_delete_webhook_not_found(self):
        assert delete_webhook("nonexistent") is False

    def test_update_webhook_url(self):
        wh = register_webhook(url="https://old.com/hook", events=["analysis.completed"])
        updated = update_webhook(wh.id, url="https://new.com/hook")
        assert updated is not None
        assert updated.url == "https://new.com/hook"

    def test_update_webhook_events(self):
        wh = register_webhook(url="https://example.com/hook", events=["analysis.completed"])
        updated = update_webhook(wh.id, events=["iac.generated", "hld.exported"])
        assert updated.events == ["iac.generated", "hld.exported"]

    def test_update_webhook_active(self):
        wh = register_webhook(url="https://example.com/hook", events=["analysis.completed"])
        updated = update_webhook(wh.id, active=False)
        assert updated.active is False

    def test_update_webhook_not_found(self):
        assert update_webhook("nonexistent", url="https://x.com") is None


class TestWebhookUrlValidation:
    @pytest.mark.parametrize(
        "url",
        [
            "http://example.com/hook",
            "https://localhost/hook",
            "https://localhost./hook",
            "https://127.0.0.1/hook",
            "https://127.1/hook",
            "https://10.0.0.5/hook",
            "https://172.16.0.1/hook",
            "https://192.168.1.10/hook",
            "https://169.254.169.254/latest/meta-data",
            "https://0.0.0.0/hook",
            "https://224.0.0.1/hook",
            "https://[::1]/hook",
            "https://[fc00::1]/hook",
            "https://[fe80::1]/hook",
            "https://[ff02::1]/hook",
            "https://metadata.google.internal/computeMetadata/v1",
            "https://metadata/hook",
            "https://service.internal/hook",
            "https://printer.local/hook",
        ],
    )
    def test_validate_webhook_url_blocks_internal_targets(self, url):
        with pytest.raises(ValueError):
            validate_webhook_url(url)

    @pytest.mark.parametrize(
        "url",
        [
            "https://example.com/hook",
            "HTTPS://hooks.example.org/webhook?token=abc",
            "https://8.8.8.8/hook",
            "https://[2001:4860:4860::8888]/hook",
        ],
    )
    def test_validate_webhook_url_allows_public_https_targets(self, url):
        validate_webhook_url(url)

    def test_register_webhook_rejects_internal_target(self):
        with pytest.raises(ValueError):
            register_webhook(url="https://127.0.0.1/hook", events=["analysis.completed"])

    def test_update_webhook_rejects_internal_target_without_mutating_existing_url(self):
        wh = register_webhook(url="https://example.com/hook", events=["analysis.completed"])

        with pytest.raises(ValueError):
            update_webhook(wh.id, url="https://169.254.169.254/latest/meta-data")

        assert get_webhook(wh.id).url == "https://example.com/hook"

    @patch("httpx.AsyncClient")
    def test_deliver_payload_revalidates_target_before_network_call(self, mock_client):
        result = asyncio.run(_deliver_payload(
            url="https://localhost/hook",
            payload_bytes=b"{}",
            signature="sig",
            event_type="analysis.completed",
            delivery_id="dlv-test",
        ))

        assert result.success is False
        assert "not allowed" in result.error
        mock_client.assert_not_called()


# ---------------------------------------------------------------------------
# Dispatch & Delivery
# ---------------------------------------------------------------------------

class TestDispatch:
    @patch("webhooks._deliver_payload")
    def test_dispatch_event_matching(self, mock_deliver):
        from webhooks import DeliveryAttempt
        mock_deliver.return_value = DeliveryAttempt(
            attempt=1, timestamp="t", status_code=200, success=True, latency_ms=50
        )
        register_webhook(url="https://example.com/hook", events=["analysis.completed"])
        logs = asyncio.run(dispatch_event("analysis.completed", {"result": "ok"}))
        assert len(logs) == 1
        assert logs[0].delivered is True

    @patch("webhooks._deliver_payload")
    def test_dispatch_event_no_match(self, mock_deliver):
        register_webhook(url="https://example.com/hook", events=["iac.generated"])
        logs = asyncio.run(dispatch_event("analysis.completed", {"result": "ok"}))
        assert len(logs) == 0
        mock_deliver.assert_not_called()

    @patch("webhooks._deliver_payload")
    def test_dispatch_inactive_webhook_skipped(self, mock_deliver):
        wh = register_webhook(url="https://example.com/hook", events=["analysis.completed"])
        update_webhook(wh.id, active=False)
        logs = asyncio.run(dispatch_event("analysis.completed", {"result": "ok"}))
        assert len(logs) == 0

    def test_delivery_logs_empty(self):
        assert get_delivery_logs() == []

    def test_delivery_stats_empty(self):
        stats = get_delivery_stats()
        assert stats["total_deliveries"] == 0
        assert stats["active_webhooks"] == 0


# ---------------------------------------------------------------------------
# Integrations
# ---------------------------------------------------------------------------

class TestIntegrations:
    def test_register_slack_integration(self):
        integ = register_integration(
            integration_type="slack",
            name="My Slack",
            config={"webhook_url": "https://hooks.slack.com/test"},
        )
        assert integ.type == "slack"
        assert integ.name == "My Slack"
        assert integ.enabled is True

    def test_register_teams_integration(self):
        integ = register_integration(
            integration_type="teams",
            name="My Teams",
            config={"webhook_url": "https://teams.webhook.office.com/test"},
        )
        assert integ.type == "teams"

    def test_register_invalid_type(self):
        with pytest.raises((ValueError, KeyError)):
            register_integration(integration_type="invalid", name="Bad", config={})

    def test_register_missing_config(self):
        with pytest.raises((ValueError, KeyError)):
            register_integration(integration_type="slack", name="Bad", config={})

    def test_list_integrations(self):
        register_integration("slack", "S1", {"webhook_url": "https://a.com"})
        register_integration("teams", "T1", {"webhook_url": "https://b.com"})
        result = list_integrations()
        assert len(result) == 2

    def test_delete_integration(self):
        integ = register_integration("slack", "S1", {"webhook_url": "https://a.com"})
        assert delete_integration(integ.id) is True
        assert get_integration(integ.id) is None

    def test_delete_integration_not_found(self):
        assert delete_integration("nonexistent") is False

    def test_integration_requirements(self):
        assert "slack" in INTEGRATION_REQUIREMENTS
        assert "webhook_url" in INTEGRATION_REQUIREMENTS["slack"]
        assert "teams" in INTEGRATION_REQUIREMENTS
        assert "azure_devops" in INTEGRATION_REQUIREMENTS
        assert "github" in INTEGRATION_REQUIREMENTS

    def test_all_event_types(self):
        assert len(ALL_EVENT_TYPES) >= 6
        assert "analysis.completed" in ALL_EVENT_TYPES


# ---------------------------------------------------------------------------
# Emit event (webhooks + integrations)
# ---------------------------------------------------------------------------

class TestEmitEvent:
    @patch("webhooks._deliver_payload")
    def test_emit_event_summary(self, mock_deliver):
        from webhooks import DeliveryAttempt
        mock_deliver.return_value = DeliveryAttempt(
            attempt=1, timestamp="t", status_code=200, success=True, latency_ms=10
        )
        register_webhook(url="https://a.com/hook", events=["analysis.completed"])
        result = asyncio.run(emit_event("analysis.completed", {"status": "done"}))
        assert "webhook_deliveries" in result
        assert "integration_deliveries" in result


# ---------------------------------------------------------------------------
# Router endpoints (via TestClient)
# ---------------------------------------------------------------------------
