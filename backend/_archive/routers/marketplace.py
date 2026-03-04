"""Azure Marketplace & Enterprise Sales REST endpoints."""

from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel, Field
from typing import Dict, Optional

from routers.shared import limiter, verify_api_key
from marketplace import (
    resolve_landing_page_token,
    activate_subscription,
    handle_marketplace_webhook,
    report_usage_to_marketplace,
    get_subscription,
    list_subscriptions,
    get_webhook_events,
    get_usage_reports,
    get_marketplace_overview,
    PLAN_DETAILS,
    SLA_DOCUMENTATION,
    SECURITY_QUESTIONNAIRE,
    COSELL_MATERIALS,
    SSO_PROVIDERS,
    METERED_DIMENSIONS,
)

router = APIRouter(tags=["marketplace"])

# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class LandingPageRequest(BaseModel):
    token: str = Field(..., min_length=1)


class ActivateRequest(BaseModel):
    marketplace_subscription_id: str = Field(..., min_length=1)
    plan_id: str = Field(..., min_length=1)
    tenant_id: str = Field(..., min_length=1)
    purchaser_email: str = Field(..., min_length=3)
    quantity: int = Field(1, ge=1)


class MarketplaceWebhookPayload(BaseModel):
    action: str = Field(..., pattern="^(ChangePlan|ChangeQuantity|Suspend|Reinstate|Unsubscribe|Renew|Transfer)$")
    subscription_id: str = Field(..., min_length=1)
    payload: Dict = Field(default_factory=dict)


class UsageReportRequest(BaseModel):
    subscription_id: str = Field(..., min_length=1)
    dimension: str = Field(..., min_length=1)
    quantity: float = Field(..., gt=0)
    plan_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Marketplace SaaS landing page
# ---------------------------------------------------------------------------

@router.post("/marketplace/resolve")
@limiter.limit("20/minute")
async def resolve_token(request: Request, body: LandingPageRequest):
    """Resolve a Marketplace landing page token to subscription details."""
    result = resolve_landing_page_token(body.token)
    return result


@router.post("/marketplace/activate")
@limiter.limit("10/minute")
async def activate(request: Request, body: ActivateRequest, _=Depends(verify_api_key)):
    """Activate a Marketplace subscription after landing page resolution."""
    try:
        sub = activate_subscription(
            marketplace_subscription_id=body.marketplace_subscription_id,
            plan_id=body.plan_id,
            tenant_id=body.tenant_id,
            purchaser_email=body.purchaser_email,
            quantity=body.quantity,
        )
        return sub.to_dict()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ---------------------------------------------------------------------------
# Marketplace webhook handler
# ---------------------------------------------------------------------------

@router.post("/marketplace/webhook")
async def marketplace_webhook(request: Request, body: MarketplaceWebhookPayload):
    """
    Handle Azure Marketplace lifecycle webhooks.

    Microsoft calls this endpoint when subscription state changes.
    """
    result = handle_marketplace_webhook(
        action=body.action,
        subscription_id=body.subscription_id,
        payload=body.payload,
    )
    return result


# ---------------------------------------------------------------------------
# Usage metering
# ---------------------------------------------------------------------------

@router.post("/marketplace/usage")
@limiter.limit("60/minute")
async def report_usage(request: Request, body: UsageReportRequest, _=Depends(verify_api_key)):
    """Report usage to Azure Marketplace Metering API."""
    try:
        report = report_usage_to_marketplace(
            subscription_id=body.subscription_id,
            dimension=body.dimension,
            quantity=body.quantity,
            plan_id=body.plan_id,
        )
        return report
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ---------------------------------------------------------------------------
# Subscription management
# ---------------------------------------------------------------------------

@router.get("/marketplace/subscriptions")
@limiter.limit("30/minute")
async def get_subscriptions(
    request: Request, status: Optional[str] = None, _=Depends(verify_api_key)
):
    """List all Marketplace subscriptions."""
    return {"subscriptions": list_subscriptions(status=status)}


@router.get("/marketplace/subscriptions/{sub_id}")
@limiter.limit("30/minute")
async def get_sub_detail(request: Request, sub_id: str, _=Depends(verify_api_key)):
    """Get subscription details."""
    sub = get_subscription(sub_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")
    return sub.to_dict()


@router.get("/marketplace/overview")
@limiter.limit("30/minute")
async def marketplace_overview(request: Request, _=Depends(verify_api_key)):
    """Get Marketplace dashboard overview."""
    return get_marketplace_overview()


@router.get("/marketplace/events")
@limiter.limit("30/minute")
async def marketplace_events(request: Request, limit: int = 50, _=Depends(verify_api_key)):
    """Get recent Marketplace webhook events."""
    return {"events": get_webhook_events(limit=limit)}


@router.get("/marketplace/usage-reports")
@limiter.limit("30/minute")
async def usage_reports(
    request: Request, subscription_id: Optional[str] = None, limit: int = 50, _=Depends(verify_api_key)
):
    """Get usage metering reports."""
    return {"reports": get_usage_reports(subscription_id=subscription_id, limit=limit)}


# ---------------------------------------------------------------------------
# Enterprise Sales readiness endpoints
# ---------------------------------------------------------------------------

@router.get("/enterprise/plans")
async def enterprise_plans(request: Request):
    """Get available plans with feature comparison."""
    return {"plans": PLAN_DETAILS}


@router.get("/enterprise/sla")
async def enterprise_sla(request: Request):
    """Get SLA documentation for all tiers."""
    return SLA_DOCUMENTATION


@router.get("/enterprise/security-questionnaire")
async def security_questionnaire(request: Request):
    """Get pre-filled security questionnaire for enterprise procurement."""
    return SECURITY_QUESTIONNAIRE


@router.get("/enterprise/sso-providers")
async def sso_providers(request: Request):
    """Get supported SSO providers and configuration details."""
    return {"providers": SSO_PROVIDERS}


@router.get("/enterprise/cosell")
@limiter.limit("10/minute")
async def cosell_materials(request: Request, _=Depends(verify_api_key)):
    """Get Microsoft co-sell readiness materials."""
    return COSELL_MATERIALS


@router.get("/enterprise/metering-dimensions")
async def metering_dimensions(request: Request):
    """Get available metering dimensions for usage reporting."""
    return {"dimensions": METERED_DIMENSIONS}
