"""
Stripe Billing & Payment routes (Issue #144).

Provides:
- Checkout session creation (upgrade to Pro/Enterprise)
- Stripe webhook handler (subscription lifecycle events)
- Customer portal redirect
- Subscription status endpoint
- Pricing tiers endpoint

Environment Variables:
  STRIPE_SECRET_KEY        — Stripe API secret key
  STRIPE_WEBHOOK_SECRET    — Stripe webhook signing secret
  STRIPE_PRICE_PRO         — Stripe Price ID for Pro monthly
  STRIPE_PRICE_ENTERPRISE  — Stripe Price ID for Enterprise monthly
  STRIPE_SUCCESS_URL       — Post-checkout redirect (success)
  STRIPE_CANCEL_URL        — Post-checkout redirect (cancel)
"""

import logging
import os
import hashlib
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from fastapi import APIRouter, Request, HTTPException, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from routers.shared import limiter

logger = logging.getLogger(__name__)

router = APIRouter()

# ─────────────────────────────────────────────────────────────
# Stripe Configuration
# ─────────────────────────────────────────────────────────────
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRICE_PRO = os.getenv("STRIPE_PRICE_PRO", "price_pro_monthly")
STRIPE_PRICE_ENTERPRISE = os.getenv("STRIPE_PRICE_ENTERPRISE", "price_enterprise_monthly")
STRIPE_SUCCESS_URL = os.getenv("STRIPE_SUCCESS_URL", "https://archmorph.io/billing?session_id={CHECKOUT_SESSION_ID}")
STRIPE_CANCEL_URL = os.getenv("STRIPE_CANCEL_URL", "https://archmorph.io/pricing")

# Stripe SDK availability flag
_stripe_available = False
_stripe = None

try:
    import stripe as _stripe_module
    _stripe = _stripe_module
    if STRIPE_SECRET_KEY:
        _stripe.api_key = STRIPE_SECRET_KEY
        _stripe_available = True
        logger.info("Stripe SDK initialized")
    else:
        logger.info("STRIPE_SECRET_KEY not set — billing endpoints return mock data")
except ImportError:
    logger.info("stripe package not installed — billing endpoints return mock data")


# ─────────────────────────────────────────────────────────────
# Pricing Tiers (source of truth)
# ─────────────────────────────────────────────────────────────
PRICING_TIERS: List[Dict[str, Any]] = [
    {
        "id": "free",
        "name": "Free",
        "price_monthly": 0,
        "price_annual": 0,
        "currency": "usd",
        "features": [
            "5 analyses per month",
            "3 IaC downloads per month",
            "2 HLD generations per month",
            "Community support",
            "Basic service mapping",
        ],
        "limits": {
            "analyses_per_month": 5,
            "iac_downloads_per_month": 3,
            "hld_generations_per_month": 2,
            "cost_estimates_per_month": 10,
            "share_links_per_month": 3,
        },
        "cta": "Get Started",
        "highlighted": False,
    },
    {
        "id": "pro",
        "name": "Pro",
        "price_monthly": 29,
        "price_annual": 290,
        "currency": "usd",
        "stripe_price_id": STRIPE_PRICE_PRO,
        "features": [
            "50 analyses per month",
            "30 IaC downloads per month",
            "20 HLD generations per month",
            "Priority support",
            "Advanced service mapping",
            "Cost optimization insights",
            "Export to Word/PDF/PPTX",
        ],
        "limits": {
            "analyses_per_month": 50,
            "iac_downloads_per_month": 30,
            "hld_generations_per_month": 20,
            "cost_estimates_per_month": 100,
            "share_links_per_month": 50,
        },
        "cta": "Upgrade to Pro",
        "highlighted": True,
    },
    {
        "id": "enterprise",
        "name": "Enterprise",
        "price_monthly": 99,
        "price_annual": 990,
        "currency": "usd",
        "stripe_price_id": STRIPE_PRICE_ENTERPRISE,
        "features": [
            "Unlimited analyses",
            "Unlimited IaC downloads",
            "Unlimited HLD generations",
            "Dedicated support & SLA",
            "SSO / Azure AD integration",
            "Custom service mappings",
            "Audit logging & compliance",
            "Multi-tenant isolation",
            "API access",
        ],
        "limits": {
            "analyses_per_month": 10000,
            "iac_downloads_per_month": 10000,
            "hld_generations_per_month": 10000,
            "cost_estimates_per_month": 10000,
            "share_links_per_month": 10000,
        },
        "cta": "Contact Sales",
        "highlighted": False,
    },
]


# ─────────────────────────────────────────────────────────────
# Pydantic Models
# ─────────────────────────────────────────────────────────────
class CheckoutRequest(BaseModel):
    tier: str = Field(..., pattern=r"^(pro|enterprise)$", description="Target tier")
    email: Optional[str] = Field(None, max_length=320)
    annual: bool = Field(False, description="Annual billing cycle")


class PortalRequest(BaseModel):
    customer_id: str = Field(..., min_length=1, max_length=128)


class SubscriptionStatus(BaseModel):
    tier: str
    status: str
    current_period_end: Optional[str] = None
    cancel_at_period_end: bool = False


# ─────────────────────────────────────────────────────────────
# In-memory subscription store (production would use database)
# ─────────────────────────────────────────────────────────────
_subscriptions: Dict[str, Dict[str, Any]] = {}


# ─────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────
@router.get("/api/billing/pricing")
@limiter.limit("30/minute")
async def get_pricing(request: Request) -> Dict[str, Any]:
    """Return pricing tiers with feature lists and limits."""
    return {
        "tiers": PRICING_TIERS,
        "currency": "usd",
        "billing_cycles": ["monthly", "annual"],
        "annual_discount": "2 months free",
    }


@router.post("/api/billing/checkout")
@limiter.limit("5/minute")
async def create_checkout_session(request: Request, data: CheckoutRequest) -> Dict[str, Any]:
    """Create a Stripe Checkout session for upgrading to Pro or Enterprise.

    If Stripe is not configured, returns a mock session for development.
    """
    tier_data = next((t for t in PRICING_TIERS if t["id"] == data.tier), None)
    if not tier_data:
        raise HTTPException(400, f"Invalid tier: {data.tier}")

    if not _stripe_available:
        # Mock response for development
        mock_id = f"cs_mock_{data.tier}_{hashlib.md5((data.email or 'anon').encode()).hexdigest()[:8]}"
        return {
            "session_id": mock_id,
            "url": f"{STRIPE_SUCCESS_URL.replace('{CHECKOUT_SESSION_ID}', mock_id)}",
            "tier": data.tier,
            "mode": "mock",
        }

    # Real Stripe checkout session
    try:
        price_id = tier_data.get("stripe_price_id")
        if not price_id:
            raise HTTPException(400, f"No Stripe price configured for tier: {data.tier}")

        session = _stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=STRIPE_SUCCESS_URL,
            cancel_url=STRIPE_CANCEL_URL,
            customer_email=data.email,
            metadata={"tier": data.tier},
        )
        return {
            "session_id": session.id,
            "url": session.url,
            "tier": data.tier,
            "mode": "live",
        }
    except Exception as exc:
        logger.error("Stripe checkout error: %s", exc)
        raise HTTPException(502, "Payment service temporarily unavailable")


@router.post("/api/billing/portal")
@limiter.limit("5/minute")
async def create_portal_session(request: Request, data: PortalRequest) -> Dict[str, Any]:
    """Create a Stripe Customer Portal session for managing subscriptions.

    Allows customers to update payment methods, view invoices, and cancel.
    """
    if not _stripe_available:
        return {
            "url": f"https://billing.stripe.com/p/mock/{data.customer_id}",
            "mode": "mock",
        }

    try:
        session = _stripe.billing_portal.Session.create(
            customer=data.customer_id,
            return_url=STRIPE_CANCEL_URL,
        )
        return {
            "url": session.url,
            "mode": "live",
        }
    except Exception as exc:
        logger.error("Stripe portal error: %s", exc)
        raise HTTPException(502, "Payment service temporarily unavailable")


@router.get("/api/billing/subscription/{customer_id}")
@limiter.limit("10/minute")
async def get_subscription_status(
    request: Request, customer_id: str
) -> Dict[str, Any]:
    """Get subscription status for a customer."""
    sub = _subscriptions.get(customer_id)
    if sub:
        return sub

    # Default: free tier
    return {
        "tier": "free",
        "status": "active",
        "current_period_end": None,
        "cancel_at_period_end": False,
    }


@router.post("/api/billing/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: Optional[str] = Header(None, alias="Stripe-Signature"),
) -> JSONResponse:
    """Handle Stripe webhook events.

    Processes subscription lifecycle events:
    - checkout.session.completed → activate subscription
    - customer.subscription.updated → update tier/status
    - customer.subscription.deleted → downgrade to free
    - invoice.payment_failed → flag for follow-up
    """
    body = await request.body()

    if _stripe_available and STRIPE_WEBHOOK_SECRET:
        try:
            event = _stripe.Webhook.construct_event(
                body, stripe_signature, STRIPE_WEBHOOK_SECRET
            )
        except Exception as exc:
            logger.warning("Webhook signature verification failed: %s", exc)
            raise HTTPException(400, "Invalid webhook signature")
    else:
        # Dev mode — parse raw JSON
        import json
        try:
            event = json.loads(body)
        except Exception:
            raise HTTPException(400, "Invalid webhook payload")

    event_type = event.get("type", "")
    data_obj = event.get("data", {}).get("object", {})

    logger.info("Stripe webhook received: %s", event_type)

    if event_type == "checkout.session.completed":
        customer_id = data_obj.get("customer", "")
        tier = data_obj.get("metadata", {}).get("tier", "pro")
        _subscriptions[customer_id] = {
            "tier": tier,
            "status": "active",
            "current_period_end": data_obj.get("current_period_end"),
            "cancel_at_period_end": False,
            "activated_at": datetime.now(timezone.utc).isoformat(),
        }
        logger.info("Subscription activated: customer=%s tier=%s", customer_id, tier)

    elif event_type == "customer.subscription.updated":
        customer_id = data_obj.get("customer", "")
        status = data_obj.get("status", "active")
        if customer_id in _subscriptions:
            _subscriptions[customer_id]["status"] = status
            _subscriptions[customer_id]["cancel_at_period_end"] = data_obj.get(
                "cancel_at_period_end", False
            )
        logger.info("Subscription updated: customer=%s status=%s", customer_id, status)

    elif event_type == "customer.subscription.deleted":
        customer_id = data_obj.get("customer", "")
        if customer_id in _subscriptions:
            _subscriptions[customer_id]["tier"] = "free"
            _subscriptions[customer_id]["status"] = "canceled"
        logger.info("Subscription canceled: customer=%s", customer_id)

    elif event_type == "invoice.payment_failed":
        customer_id = data_obj.get("customer", "")
        logger.warning("Payment failed for customer: %s", customer_id)
        if customer_id in _subscriptions:
            _subscriptions[customer_id]["status"] = "past_due"

    return JSONResponse({"received": True})
