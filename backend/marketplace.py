"""
Azure Marketplace SaaS integration & Enterprise Sales readiness module.

Handles Marketplace webhook lifecycle events (subscription purchase,
suspend, reinstate, unsubscribe), usage metering API reporting,
landing page token resolution, SSO readiness, and enterprise
admin capabilities.
"""

import logging
import threading
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("marketplace")

# ---------------------------------------------------------------------------
# Marketplace subscription lifecycle
# ---------------------------------------------------------------------------

class SubscriptionStatus(str, Enum):
    PENDING = "pending"
    SUBSCRIBED = "subscribed"
    SUSPENDED = "suspended"
    UNSUBSCRIBED = "unsubscribed"


class MarketplacePlan(str, Enum):
    FREE = "archmorph-free"
    PRO = "archmorph-pro"
    TEAM = "archmorph-team"
    ENTERPRISE = "archmorph-enterprise"


PLAN_DETAILS: Dict[str, Dict[str, Any]] = {
    "archmorph-free": {
        "name": "Free",
        "monthly_price": 0,
        "analyses_per_month": 5,
        "team_members": 1,
        "features": ["basic_analysis", "single_cloud", "community_support"],
    },
    "archmorph-pro": {
        "name": "Pro",
        "monthly_price": 49,
        "analyses_per_month": 50,
        "team_members": 5,
        "features": ["advanced_analysis", "multi_cloud", "iac_generation", "hld_export", "email_support"],
    },
    "archmorph-team": {
        "name": "Team",
        "monthly_price": 149,
        "analyses_per_month": -1,  # unlimited
        "team_members": 25,
        "features": ["unlimited_analysis", "multi_cloud", "iac_generation", "hld_export",
                      "compliance_mapping", "risk_scoring", "priority_support", "sso"],
    },
    "archmorph-enterprise": {
        "name": "Enterprise",
        "monthly_price": -1,  # custom pricing
        "analyses_per_month": -1,
        "team_members": -1,
        "features": ["unlimited_analysis", "multi_cloud", "iac_generation", "hld_export",
                      "compliance_mapping", "risk_scoring", "dedicated_support", "sso",
                      "custom_integrations", "sla_guarantee", "on_premise_option"],
    },
}


@dataclass
class MarketplaceSubscription:
    id: str
    marketplace_subscription_id: str
    plan_id: str
    tenant_id: str
    purchaser_email: str
    status: str
    quantity: int = 1
    created_at: str = ""
    updated_at: str = ""
    suspended_at: Optional[str] = None
    cancel_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["plan_details"] = PLAN_DETAILS.get(self.plan_id, {})
        return d


# ---------------------------------------------------------------------------
# In-memory store (thread-safe)
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_subscriptions: Dict[str, MarketplaceSubscription] = {}
_webhook_events: List[Dict[str, Any]] = []
_usage_reports: List[Dict[str, Any]] = []
_MAX_EVENTS = 5000


# ---------------------------------------------------------------------------
# Landing page token resolution
# ---------------------------------------------------------------------------

def resolve_landing_page_token(token: str) -> Dict[str, Any]:
    """
    Resolve a Marketplace landing page token.

    When a user purchases from Azure Marketplace, they're redirected to
    our landing page with a token. We resolve it to get subscription details.

    In production, this calls the Marketplace SaaS Fulfillment API:
    POST https://marketplaceapi.microsoft.com/api/saas/subscriptions/resolve?api-version=2018-08-31
    """
    # For development/testing, simulate token resolution
    return {
        "subscription_id": f"sub-{uuid.uuid4().hex[:12]}",
        "subscription_name": "Archmorph Cloud Architecture",
        "offer_id": "archmorph",
        "plan_id": "archmorph-pro",
        "quantity": 1,
        "purchaser_email": "buyer@example.com",
        "purchaser_tenant_id": f"tenant-{uuid.uuid4().hex[:8]}",
        "token": token,
        "resolved_at": datetime.now(timezone.utc).isoformat(),
    }


def activate_subscription(
    marketplace_subscription_id: str,
    plan_id: str,
    tenant_id: str,
    purchaser_email: str,
    quantity: int = 1,
) -> MarketplaceSubscription:
    """Activate a new Marketplace subscription."""
    if plan_id not in PLAN_DETAILS:
        raise ValueError(f"Unknown plan: {plan_id}")

    now = datetime.now(timezone.utc).isoformat()
    sub = MarketplaceSubscription(
        id=f"msub-{uuid.uuid4().hex[:12]}",
        marketplace_subscription_id=marketplace_subscription_id,
        plan_id=plan_id,
        tenant_id=tenant_id,
        purchaser_email=purchaser_email,
        status=SubscriptionStatus.SUBSCRIBED,
        quantity=quantity,
        created_at=now,
        updated_at=now,
    )

    with _lock:
        _subscriptions[sub.id] = sub

    logger.info("Activated marketplace subscription %s (plan: %s)", sub.id, plan_id)
    return sub


# ---------------------------------------------------------------------------
# Webhook lifecycle handlers
# ---------------------------------------------------------------------------

WEBHOOK_ACTIONS = [
    "ChangePlan", "ChangeQuantity", "Suspend", "Reinstate",
    "Unsubscribe", "Renew", "Transfer",
]


def handle_marketplace_webhook(action: str, subscription_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle Azure Marketplace webhook lifecycle events.

    Microsoft sends webhooks for subscription changes:
    - ChangePlan: customer upgrades/downgrades
    - Suspend: payment failure or admin action
    - Reinstate: subscription re-activated
    - Unsubscribe: customer cancels
    """
    now = datetime.now(timezone.utc).isoformat()

    event = {
        "id": f"evt-{uuid.uuid4().hex[:12]}",
        "action": action,
        "subscription_id": subscription_id,
        "payload": payload,
        "received_at": now,
        "processed": False,
    }

    # Find matching subscription
    sub = None
    with _lock:
        for s in _subscriptions.values():
            if s.marketplace_subscription_id == subscription_id:
                sub = s
                break

    if not sub:
        event["error"] = "Subscription not found"
        with _lock:
            _webhook_events.append(event)
            if len(_webhook_events) > _MAX_EVENTS:
                _webhook_events.pop(0)
        return event

    if action == "ChangePlan":
        new_plan = payload.get("planId", sub.plan_id)
        if new_plan in PLAN_DETAILS:
            sub.plan_id = new_plan
            sub.updated_at = now
            event["processed"] = True
            event["new_plan"] = new_plan

    elif action == "ChangeQuantity":
        new_qty = payload.get("quantity", sub.quantity)
        sub.quantity = int(new_qty)
        sub.updated_at = now
        event["processed"] = True

    elif action == "Suspend":
        sub.status = SubscriptionStatus.SUSPENDED
        sub.suspended_at = now
        sub.updated_at = now
        event["processed"] = True

    elif action == "Reinstate":
        sub.status = SubscriptionStatus.SUBSCRIBED
        sub.suspended_at = None
        sub.updated_at = now
        event["processed"] = True

    elif action == "Unsubscribe":
        sub.status = SubscriptionStatus.UNSUBSCRIBED
        sub.cancel_reason = payload.get("reason", "customer_cancelled")
        sub.updated_at = now
        event["processed"] = True

    elif action == "Renew":
        sub.updated_at = now
        event["processed"] = True

    with _lock:
        _webhook_events.append(event)
        if len(_webhook_events) > _MAX_EVENTS:
            _webhook_events.pop(0)

    logger.info("Processed marketplace webhook: %s for %s", action, subscription_id)
    return event


# ---------------------------------------------------------------------------
# Marketplace Metering API
# ---------------------------------------------------------------------------

METERED_DIMENSIONS = {
    "analyses": "Architecture analyses performed",
    "iac_downloads": "IaC code downloads",
    "hld_generations": "HLD document generations",
}


def report_usage_to_marketplace(
    subscription_id: str,
    dimension: str,
    quantity: float,
    plan_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Report usage to Azure Marketplace Metering API.

    In production, this POSTs to:
    https://marketplaceapi.microsoft.com/api/usageEvent?api-version=2018-08-31
    """
    if dimension not in METERED_DIMENSIONS:
        raise ValueError(f"Unknown metering dimension: {dimension}")

    now = datetime.now(timezone.utc)
    report = {
        "id": f"usage-{uuid.uuid4().hex[:12]}",
        "resourceId": subscription_id,
        "dimension": dimension,
        "quantity": quantity,
        "planId": plan_id or "archmorph-pro",
        "effectiveStartTime": now.replace(minute=0, second=0, microsecond=0).isoformat(),
        "reported_at": now.isoformat(),
        "status": "accepted",
    }

    with _lock:
        _usage_reports.append(report)

    logger.info("Reported usage: %s=%s for %s", dimension, quantity, subscription_id)
    return report


# ---------------------------------------------------------------------------
# Enterprise Sales readiness
# ---------------------------------------------------------------------------

SSO_PROVIDERS: Dict[str, Dict[str, str]] = {
    "azure_ad": {
        "name": "Azure Active Directory",
        "protocol": "OIDC",
        "discovery_url": "https://login.microsoftonline.com/{tenant_id}/v2.0/.well-known/openid-configuration",
        "scopes": "openid profile email",
    },
    "azure_ad_saml": {
        "name": "Azure AD (SAML)",
        "protocol": "SAML",
        "metadata_url": "https://login.microsoftonline.com/{tenant_id}/federationmetadata/2007-06/federationmetadata.xml",
    },
}


SLA_DOCUMENTATION: Dict[str, Any] = {
    "version": "1.0",
    "effective_date": "2026-03-01",
    "tiers": {
        "pro": {
            "availability": "99.5%",
            "support_response": "24 hours",
            "data_retention": "90 days",
            "backup_frequency": "daily",
        },
        "team": {
            "availability": "99.9%",
            "support_response": "4 hours",
            "data_retention": "1 year",
            "backup_frequency": "hourly",
        },
        "enterprise": {
            "availability": "99.99%",
            "support_response": "1 hour",
            "data_retention": "unlimited",
            "backup_frequency": "continuous",
            "dedicated_instance": True,
            "custom_sla": True,
        },
    },
    "exclusions": [
        "Planned maintenance windows (max 4 hours/month, 48h notice)",
        "Force majeure events",
        "Customer-caused outages",
        "Third-party service dependencies (Azure OpenAI, etc.)",
    ],
    "credits": {
        "99.9_to_99.5": "10% monthly credit",
        "99.5_to_99.0": "25% monthly credit",
        "below_99.0": "50% monthly credit",
    },
}


SECURITY_QUESTIONNAIRE: Dict[str, Any] = {
    "version": "2.0",
    "last_updated": "2026-02-22",
    "sections": {
        "data_security": {
            "encryption_at_rest": "AES-256 via Azure Storage Service Encryption",
            "encryption_in_transit": "TLS 1.2+ enforced",
            "key_management": "Azure Key Vault with customer-managed keys (Enterprise)",
            "data_residency": "Configurable per tenant (Azure regions)",
            "data_classification": "Customer architecture diagrams classified as Confidential",
        },
        "access_control": {
            "authentication": "Azure AD SSO (OIDC/SAML) + API key",
            "authorization": "RBAC with 4 roles: owner, admin, editor, viewer",
            "mfa": "Enforced via Azure AD conditional access",
            "session_management": "JWT tokens, 1h access / 7d refresh",
        },
        "infrastructure": {
            "hosting": "Azure App Service (PaaS) — no direct VM access",
            "database": "Azure Database for PostgreSQL Flexible Server",
            "networking": "VNet-integrated, private endpoints for DB and Key Vault",
            "waf": "Azure Front Door WAF with OWASP 3.2 ruleset",
            "ddos": "Azure DDoS Protection Standard",
        },
        "compliance": {
            "soc2_type2": "In progress — target Q3 2026",
            "iso27001": "Planned — target Q4 2026",
            "gdpr": "Compliant — DPA available",
            "hipaa": "Not applicable (no PHI processed)",
            "penetration_testing": "Annual third-party pentest (report available under NDA)",
        },
        "incident_response": {
            "plan": "Documented IR plan with 4 severity levels",
            "notification_sla": "Critical: 1h, High: 4h, Medium: 24h, Low: 72h",
            "contact": "security@archmorph.io",
            "post_incident_review": "Published within 5 business days",
        },
        "business_continuity": {
            "rto": "4 hours (Enterprise: 1 hour)",
            "rpo": "1 hour (Enterprise: 15 minutes)",
            "backup_strategy": "Geo-redundant Azure Backup, daily snapshots",
            "dr_testing": "Quarterly DR drills",
        },
    },
}


COSELL_MATERIALS: Dict[str, Any] = {
    "partner_center_id": "pending",
    "ip_cosell_eligible": False,
    "ip_cosell_prerequisites": [
        "Azure Marketplace SaaS transactable offer published",
        "> $100K Azure consumed revenue or > $5M marketplace revenue",
        "Azure IP co-sell solution validated",
        "Business profile published in Microsoft Partner Center",
    ],
    "well_architected_alignment": {
        "reliability": "Multi-region capable, auto-scaling, health probes",
        "security": "Azure AD SSO, Key Vault, private endpoints, WAF",
        "cost_optimization": "Tiered pricing, autoscale, reserved instances guidance",
        "operational_excellence": "IaC (Terraform), CI/CD, structured logging, Azure Monitor",
        "performance_efficiency": "CDN, Redis caching, async processing, connection pooling",
    },
    "solution_areas": [
        "Cloud Migration",
        "Application Modernization",
        "Azure Architecture",
        "Infrastructure as Code",
    ],
}


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def get_subscription(sub_id: str) -> Optional[MarketplaceSubscription]:
    """Get a subscription by internal ID."""
    with _lock:
        return _subscriptions.get(sub_id)


def get_subscription_by_tenant(tenant_id: str) -> Optional[MarketplaceSubscription]:
    """Get active subscription for a tenant."""
    with _lock:
        for s in _subscriptions.values():
            if s.tenant_id == tenant_id and s.status == SubscriptionStatus.SUBSCRIBED:
                return s
    return None


def list_subscriptions(status: Optional[str] = None) -> List[Dict[str, Any]]:
    """List all subscriptions, optionally filtered by status."""
    with _lock:
        subs = list(_subscriptions.values())
    if status:
        subs = [s for s in subs if s.status == status]
    return [s.to_dict() for s in subs]


def get_webhook_events(limit: int = 50) -> List[Dict[str, Any]]:
    """Get recent marketplace webhook events."""
    with _lock:
        return list(reversed(_webhook_events[-limit:]))


def get_usage_reports(subscription_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    """Get usage reports, optionally filtered by subscription."""
    with _lock:
        reports = list(_usage_reports)
    if subscription_id:
        reports = [r for r in reports if r["resourceId"] == subscription_id]
    return list(reversed(reports[-limit:]))


def get_marketplace_overview() -> Dict[str, Any]:
    """Get marketplace dashboard overview."""
    with _lock:
        subs = list(_subscriptions.values())
        events = list(_webhook_events)
        reports = list(_usage_reports)

    active = sum(1 for s in subs if s.status == SubscriptionStatus.SUBSCRIBED)
    suspended = sum(1 for s in subs if s.status == SubscriptionStatus.SUSPENDED)

    by_plan: Dict[str, int] = {}
    for s in subs:
        if s.status == SubscriptionStatus.SUBSCRIBED:
            by_plan[s.plan_id] = by_plan.get(s.plan_id, 0) + 1

    return {
        "total_subscriptions": len(subs),
        "active": active,
        "suspended": suspended,
        "by_plan": by_plan,
        "recent_webhook_events": len(events),
        "usage_reports_sent": len(reports),
        "plans_available": list(PLAN_DETAILS.keys()),
    }


def clear_all():
    """Clear all data (for testing)."""
    with _lock:
        _subscriptions.clear()
        _webhook_events.clear()
        _usage_reports.clear()
