"""
Tests for Stripe Billing routes (Issue #144).
"""

import json
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Create a test client for the Archmorph API."""
    import sys
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from main import app
    return TestClient(app, raise_server_exceptions=False)


# ─────────────────────────────────────────────────────────────
# Pricing
# ─────────────────────────────────────────────────────────────
class TestPricing:
    def test_get_pricing(self, client):
        resp = client.get("/api/billing/pricing")
        assert resp.status_code == 200
        data = resp.json()
        assert "tiers" in data
        assert len(data["tiers"]) == 3

    def test_pricing_has_free_tier(self, client):
        data = client.get("/api/billing/pricing").json()
        free = next(t for t in data["tiers"] if t["id"] == "free")
        assert free["price_monthly"] == 0
        assert len(free["features"]) >= 4

    def test_pricing_has_pro_tier(self, client):
        data = client.get("/api/billing/pricing").json()
        pro = next(t for t in data["tiers"] if t["id"] == "pro")
        assert pro["price_monthly"] == 29
        assert pro["highlighted"] is True

    def test_pricing_has_enterprise_tier(self, client):
        data = client.get("/api/billing/pricing").json()
        enterprise = next(t for t in data["tiers"] if t["id"] == "enterprise")
        assert enterprise["price_monthly"] == 99

    def test_pricing_tiers_have_limits(self, client):
        data = client.get("/api/billing/pricing").json()
        for tier in data["tiers"]:
            assert "limits" in tier
            assert "analyses_per_month" in tier["limits"]

    def test_pricing_has_billing_cycles(self, client):
        data = client.get("/api/billing/pricing").json()
        assert "billing_cycles" in data
        assert "monthly" in data["billing_cycles"]
        assert "annual" in data["billing_cycles"]

    def test_pricing_has_annual_discount(self, client):
        data = client.get("/api/billing/pricing").json()
        assert "annual_discount" in data

    def test_pricing_tiers_have_cta(self, client):
        data = client.get("/api/billing/pricing").json()
        for tier in data["tiers"]:
            assert "cta" in tier

    def test_pricing_currency(self, client):
        data = client.get("/api/billing/pricing").json()
        assert data["currency"] == "usd"

    def test_pricing_pro_has_more_features_than_free(self, client):
        data = client.get("/api/billing/pricing").json()
        free = next(t for t in data["tiers"] if t["id"] == "free")
        pro = next(t for t in data["tiers"] if t["id"] == "pro")
        assert len(pro["features"]) > len(free["features"])


# ─────────────────────────────────────────────────────────────
# Checkout (Mock Mode)
# ─────────────────────────────────────────────────────────────
class TestCheckout:
    def test_create_checkout_pro(self, client):
        resp = client.post("/api/billing/checkout", json={
            "tier": "pro",
            "email": "user@example.com",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "session_id" in data
        assert data["tier"] == "pro"
        assert data["mode"] == "mock"

    def test_create_checkout_enterprise(self, client):
        resp = client.post("/api/billing/checkout", json={
            "tier": "enterprise",
            "email": "admin@corp.com",
        })
        assert resp.status_code == 200
        assert resp.json()["tier"] == "enterprise"

    def test_create_checkout_invalid_tier(self, client):
        resp = client.post("/api/billing/checkout", json={
            "tier": "ultimate",
        })
        assert resp.status_code == 422

    def test_create_checkout_free_tier_rejected(self, client):
        resp = client.post("/api/billing/checkout", json={
            "tier": "free",
        })
        # "free" doesn't match the pattern ^(pro|enterprise)$
        assert resp.status_code == 422

    def test_create_checkout_no_email(self, client):
        resp = client.post("/api/billing/checkout", json={
            "tier": "pro",
        })
        assert resp.status_code == 200  # Email is optional

    def test_checkout_returns_url(self, client):
        resp = client.post("/api/billing/checkout", json={
            "tier": "pro",
            "email": "test@test.com",
        })
        assert "url" in resp.json()

    def test_checkout_annual_flag(self, client):
        resp = client.post("/api/billing/checkout", json={
            "tier": "pro",
            "annual": True,
        })
        assert resp.status_code == 200


# ─────────────────────────────────────────────────────────────
# Portal (Mock Mode)
# ─────────────────────────────────────────────────────────────
class TestPortal:
    def test_create_portal_session(self, client):
        resp = client.post("/api/billing/portal", json={
            "customer_id": "cus_test123",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "url" in data
        assert data["mode"] == "mock"

    def test_create_portal_missing_customer(self, client):
        resp = client.post("/api/billing/portal", json={})
        assert resp.status_code == 422


# ─────────────────────────────────────────────────────────────
# Subscription Status
# ─────────────────────────────────────────────────────────────
class TestSubscriptionStatus:
    def test_get_default_subscription(self, client):
        resp = client.get("/api/billing/subscription/cus_unknown")
        assert resp.status_code == 200
        data = resp.json()
        assert data["tier"] == "free"
        assert data["status"] == "active"

    def test_get_subscription_after_activation(self, client):
        # Simulate webhook checkout.session.completed
        webhook_event = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "customer": "cus_activated",
                    "metadata": {"tier": "pro"},
                }
            },
        }
        client.post("/api/billing/webhook", content=json.dumps(webhook_event))

        # Check subscription
        resp = client.get("/api/billing/subscription/cus_activated")
        assert resp.status_code == 200
        data = resp.json()
        assert data["tier"] == "pro"
        assert data["status"] == "active"


# ─────────────────────────────────────────────────────────────
# Webhook
# ─────────────────────────────────────────────────────────────
class TestWebhook:
    def test_webhook_checkout_completed(self, client):
        event = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "customer": "cus_wh_test",
                    "metadata": {"tier": "enterprise"},
                }
            },
        }
        resp = client.post("/api/billing/webhook", content=json.dumps(event))
        assert resp.status_code == 200
        assert resp.json()["received"] is True

    def test_webhook_subscription_updated(self, client):
        # First activate
        client.post("/api/billing/webhook", content=json.dumps({
            "type": "checkout.session.completed",
            "data": {"object": {"customer": "cus_update", "metadata": {"tier": "pro"}}},
        }))
        # Then update
        event = {
            "type": "customer.subscription.updated",
            "data": {
                "object": {
                    "customer": "cus_update",
                    "status": "active",
                    "cancel_at_period_end": True,
                }
            },
        }
        resp = client.post("/api/billing/webhook", content=json.dumps(event))
        assert resp.status_code == 200

    def test_webhook_subscription_deleted(self, client):
        # Activate first
        client.post("/api/billing/webhook", content=json.dumps({
            "type": "checkout.session.completed",
            "data": {"object": {"customer": "cus_cancel", "metadata": {"tier": "pro"}}},
        }))
        # Then delete
        event = {
            "type": "customer.subscription.deleted",
            "data": {"object": {"customer": "cus_cancel"}},
        }
        resp = client.post("/api/billing/webhook", content=json.dumps(event))
        assert resp.status_code == 200

        # Verify downgraded
        status = client.get("/api/billing/subscription/cus_cancel").json()
        assert status["tier"] == "free"
        assert status["status"] == "canceled"

    def test_webhook_payment_failed(self, client):
        # Activate first
        client.post("/api/billing/webhook", content=json.dumps({
            "type": "checkout.session.completed",
            "data": {"object": {"customer": "cus_fail", "metadata": {"tier": "pro"}}},
        }))
        # Payment fails
        event = {
            "type": "invoice.payment_failed",
            "data": {"object": {"customer": "cus_fail"}},
        }
        resp = client.post("/api/billing/webhook", content=json.dumps(event))
        assert resp.status_code == 200

        status = client.get("/api/billing/subscription/cus_fail").json()
        assert status["status"] == "past_due"

    def test_webhook_invalid_payload(self, client):
        resp = client.post("/api/billing/webhook", content=b"not json")
        assert resp.status_code == 400

    def test_webhook_unknown_event(self, client):
        event = {
            "type": "unknown.event",
            "data": {"object": {}},
        }
        resp = client.post("/api/billing/webhook", content=json.dumps(event))
        assert resp.status_code == 200  # Acknowledged even if not processed
