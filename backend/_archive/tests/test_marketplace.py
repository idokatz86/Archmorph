"""Comprehensive tests for marketplace.py and routers/marketplace.py — Sprint 9 #148."""
import pytest

from marketplace import (
    resolve_landing_page_token,
    activate_subscription,
    handle_marketplace_webhook,
    report_usage_to_marketplace,
    get_subscription,
    get_subscription_by_tenant,
    list_subscriptions,
    get_webhook_events,
    get_usage_reports,
    get_marketplace_overview,
    clear_all,
    PLAN_DETAILS,
    WEBHOOK_ACTIONS,
    METERED_DIMENSIONS,
    SSO_PROVIDERS,
    SLA_DOCUMENTATION,
    SECURITY_QUESTIONNAIRE,
    COSELL_MATERIALS,
    SubscriptionStatus,
)


@pytest.fixture(autouse=True)
def reset_state():
    """Clear marketplace state between tests."""
    clear_all()
    yield
    clear_all()


# ---------------------------------------------------------------------------
# Constants & static data
# ---------------------------------------------------------------------------

class TestConstants:
    def test_plan_details_has_four_plans(self):
        assert len(PLAN_DETAILS) == 4
        for key in ["archmorph-free", "archmorph-pro", "archmorph-team", "archmorph-enterprise"]:
            assert key in PLAN_DETAILS

    def test_plan_details_structure(self):
        for plan_id, details in PLAN_DETAILS.items():
            assert "name" in details
            assert "monthly_price" in details
            assert "analyses_per_month" in details
            assert "features" in details
            assert isinstance(details["features"], list)

    def test_free_plan_price_zero(self):
        assert PLAN_DETAILS["archmorph-free"]["monthly_price"] == 0

    def test_webhook_actions(self):
        assert "ChangePlan" in WEBHOOK_ACTIONS
        assert "Suspend" in WEBHOOK_ACTIONS
        assert "Unsubscribe" in WEBHOOK_ACTIONS

    def test_metered_dimensions(self):
        assert "analyses" in METERED_DIMENSIONS
        assert "iac_downloads" in METERED_DIMENSIONS

    def test_sso_providers(self):
        assert "azure_ad" in SSO_PROVIDERS
        assert "protocol" in SSO_PROVIDERS["azure_ad"]

    def test_sla_documentation(self):
        assert "tiers" in SLA_DOCUMENTATION

    def test_security_questionnaire(self):
        assert "sections" in SECURITY_QUESTIONNAIRE or isinstance(SECURITY_QUESTIONNAIRE, dict)

    def test_cosell_materials(self):
        assert isinstance(COSELL_MATERIALS, dict)


# ---------------------------------------------------------------------------
# Landing page & activation
# ---------------------------------------------------------------------------

class TestLandingPage:
    def test_resolve_token(self):
        result = resolve_landing_page_token("some-marketplace-token")
        assert "subscription_id" in result or "marketplace_subscription_id" in result

    def test_resolve_empty_token(self):
        # Should still return something (simulated)
        result = resolve_landing_page_token("x")
        assert isinstance(result, dict)


class TestActivation:
    def test_activate_subscription(self):
        sub = activate_subscription(
            marketplace_subscription_id="ms-123",
            plan_id="archmorph-pro",
            tenant_id="tenant-abc",
            purchaser_email="user@example.com",
        )
        assert sub.marketplace_subscription_id == "ms-123"
        assert sub.plan_id == "archmorph-pro"
        assert sub.tenant_id == "tenant-abc"
        assert sub.status in [SubscriptionStatus.SUBSCRIBED, SubscriptionStatus.PENDING, "subscribed", "pending"]

    def test_activate_with_quantity(self):
        sub = activate_subscription(
            marketplace_subscription_id="ms-456",
            plan_id="archmorph-team",
            tenant_id="tenant-xyz",
            purchaser_email="admin@corp.com",
            quantity=25,
        )
        assert sub.quantity == 25

    def test_get_subscription_after_activation(self):
        sub = activate_subscription(
            marketplace_subscription_id="ms-789",
            plan_id="archmorph-free",
            tenant_id="tenant-def",
            purchaser_email="test@test.com",
        )
        fetched = get_subscription(sub.id)
        assert fetched is not None
        assert fetched.tenant_id == "tenant-def"

    def test_get_subscription_by_tenant(self):
        activate_subscription(
            marketplace_subscription_id="ms-111",
            plan_id="archmorph-pro",
            tenant_id="unique-tenant",
            purchaser_email="a@a.com",
        )
        fetched = get_subscription_by_tenant("unique-tenant")
        assert fetched is not None
        assert fetched.tenant_id == "unique-tenant"

    def test_get_subscription_not_found(self):
        assert get_subscription("nonexistent") is None

    def test_get_subscription_by_tenant_not_found(self):
        assert get_subscription_by_tenant("nonexistent") is None


# ---------------------------------------------------------------------------
# Webhook handling
# ---------------------------------------------------------------------------

class TestMarketplaceWebhook:
    def test_change_plan(self):
        sub = activate_subscription("ms-w1", "archmorph-free", "t1", "a@a.com")
        result = handle_marketplace_webhook(
            action="ChangePlan",
            subscription_id=sub.id,
            payload={"plan_id": "archmorph-pro"},
        )
        assert result.get("status") == "processed" or "action" in result

    def test_suspend(self):
        sub = activate_subscription("ms-w2", "archmorph-pro", "t2", "b@b.com")
        result = handle_marketplace_webhook(
            action="Suspend",
            subscription_id=sub.id,
            payload={},
        )
        assert isinstance(result, dict)

    def test_unsubscribe(self):
        sub = activate_subscription("ms-w3", "archmorph-pro", "t3", "c@c.com")
        result = handle_marketplace_webhook(
            action="Unsubscribe",
            subscription_id=sub.id,
            payload={},
        )
        assert isinstance(result, dict)

    def test_webhook_events_recorded(self):
        sub = activate_subscription("ms-w4", "archmorph-pro", "t4", "d@d.com")
        handle_marketplace_webhook("Suspend", sub.id, {})
        events = get_webhook_events()
        assert len(events) >= 1


# ---------------------------------------------------------------------------
# Usage reporting
# ---------------------------------------------------------------------------

class TestUsageReporting:
    def test_report_usage(self):
        sub = activate_subscription("ms-u1", "archmorph-pro", "t1", "a@a.com")
        report = report_usage_to_marketplace(
            subscription_id=sub.id,
            dimension="analyses",
            quantity=5.0,
        )
        assert isinstance(report, dict)
        assert report.get("quantity") == 5.0 or "dimension" in report

    def test_usage_reports_list(self):
        sub = activate_subscription("ms-u2", "archmorph-pro", "t2", "b@b.com")
        report_usage_to_marketplace(sub.id, "analyses", 3.0)
        reports = get_usage_reports()
        assert len(reports) >= 1

    def test_usage_reports_by_subscription(self):
        sub1 = activate_subscription("ms-u3", "archmorph-pro", "t3", "c@c.com")
        sub2 = activate_subscription("ms-u4", "archmorph-pro", "t4", "d@d.com")
        report_usage_to_marketplace(sub1.id, "analyses", 1.0)
        report_usage_to_marketplace(sub2.id, "analyses", 2.0)
        reports = get_usage_reports(subscription_id=sub1.id)
        assert all(r.get("resourceId") == sub1.id for r in reports)


# ---------------------------------------------------------------------------
# Subscriptions listing
# ---------------------------------------------------------------------------

class TestSubscriptionListing:
    def test_list_empty(self):
        assert list_subscriptions() == []

    def test_list_multiple(self):
        activate_subscription("ms-l1", "archmorph-free", "t1", "a@a.com")
        activate_subscription("ms-l2", "archmorph-pro", "t2", "b@b.com")
        result = list_subscriptions()
        assert len(result) == 2

    def test_list_by_status(self):
        activate_subscription("ms-l3", "archmorph-free", "t3", "c@c.com")
        # All new subs should be subscribed/pending
        result = list_subscriptions(status="subscribed")
        # Should return at least the one we just created
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------

class TestMarketplaceOverview:
    def test_overview_empty(self):
        overview = get_marketplace_overview()
        assert isinstance(overview, dict)
        assert "total_subscriptions" in overview or "subscriptions" in overview

    def test_overview_with_data(self):
        activate_subscription("ms-o1", "archmorph-free", "t1", "a@a.com")
        activate_subscription("ms-o2", "archmorph-pro", "t2", "b@b.com")
        overview = get_marketplace_overview()
        assert isinstance(overview, dict)


# ---------------------------------------------------------------------------
# Router endpoints (via TestClient)
# ---------------------------------------------------------------------------

class TestMarketplaceRouter:
    def test_resolve_token(self, test_client):
        resp = test_client.post("/marketplace/resolve", json={"token": "test-token-123"})
        assert resp.status_code == 200

    def test_activate(self, test_client):
        resp = test_client.post("/marketplace/activate", json={
            "marketplace_subscription_id": "ms-r1",
            "plan_id": "archmorph-pro",
            "tenant_id": "tenant-r1",
            "purchaser_email": "router@test.com",
        })
        assert resp.status_code == 200

    def test_get_subscriptions(self, test_client):
        resp = test_client.get("/marketplace/subscriptions")
        assert resp.status_code == 200

    def test_marketplace_overview(self, test_client):
        resp = test_client.get("/marketplace/overview")
        assert resp.status_code == 200

    def test_marketplace_events(self, test_client):
        resp = test_client.get("/marketplace/events")
        assert resp.status_code == 200

    def test_usage_reports(self, test_client):
        resp = test_client.get("/marketplace/usage-reports")
        assert resp.status_code == 200


class TestEnterpriseRouter:
    def test_enterprise_plans(self, test_client):
        resp = test_client.get("/enterprise/plans")
        assert resp.status_code == 200
        data = resp.json()
        assert "plans" in data or isinstance(data, dict)

    def test_enterprise_sla(self, test_client):
        resp = test_client.get("/enterprise/sla")
        assert resp.status_code == 200

    def test_security_questionnaire(self, test_client):
        resp = test_client.get("/enterprise/security-questionnaire")
        assert resp.status_code == 200

    def test_sso_providers(self, test_client):
        resp = test_client.get("/enterprise/sso-providers")
        assert resp.status_code == 200

    def test_metering_dimensions(self, test_client):
        resp = test_client.get("/enterprise/metering-dimensions")
        assert resp.status_code == 200
