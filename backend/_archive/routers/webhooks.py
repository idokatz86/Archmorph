from error_envelope import ArchmorphException
"""Webhook & integration management REST endpoints."""

from fastapi import APIRouter, Request, Depends
from pydantic import BaseModel, Field
from typing import Dict, List, Optional

from routers.shared import limiter, verify_api_key
from webhooks import (
    register_webhook,
    list_webhooks,
    get_webhook,
    delete_webhook,
    update_webhook,
    get_delivery_logs,
    get_delivery_stats,
    register_integration,
    list_integrations,
    delete_integration,
    ALL_EVENT_TYPES,
    INTEGRATION_REQUIREMENTS,
    IntegrationType,
)

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])

# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class WebhookCreateRequest(BaseModel):
    url: str = Field(..., min_length=10)
    events: List[str] = Field(..., min_length=1, max_length=20)
    secret: Optional[str] = None
    description: str = ""


class WebhookUpdateRequest(BaseModel):
    url: Optional[str] = None
    events: Optional[List[str]] = None
    active: Optional[bool] = None
    description: Optional[str] = None


class IntegrationCreateRequest(BaseModel):
    type: str = Field(..., pattern="^(slack|teams|azure_devops|github)$")
    name: str = Field(..., min_length=1, max_length=100)
    config: Dict[str, str] = Field(...)


# ---------------------------------------------------------------------------
# Webhook CRUD
# ---------------------------------------------------------------------------

@router.post("")
@limiter.limit("10/minute")
async def create_webhook(request: Request, body: WebhookCreateRequest, _=Depends(verify_api_key)):
    """Register a new webhook endpoint."""
    try:
        wh = register_webhook(
            url=body.url,
            events=body.events,
            secret=body.secret,
            description=body.description,
        )
        return {
            "id": wh.id,
            "url": wh.url,
            "events": wh.events,
            "secret": wh.secret,
            "created_at": wh.created_at,
            "message": "Webhook registered. Save the secret — it won't be shown again.",
        }
    except ValueError as exc:
        raise ArchmorphException(status_code=400, detail=str(exc))


@router.get("")
@limiter.limit("30/minute")
async def get_webhooks(request: Request, _=Depends(verify_api_key)):
    """List all registered webhooks."""
    return {"webhooks": list_webhooks(), "event_types": ALL_EVENT_TYPES}


@router.get("/{webhook_id}")
@limiter.limit("30/minute")
async def get_webhook_detail(request: Request, webhook_id: str, _=Depends(verify_api_key)):
    """Get webhook details."""
    wh = get_webhook(webhook_id)
    if not wh:
        raise ArchmorphException(status_code=404, detail="Webhook not found")
    d = wh.to_dict()
    d["secret"] = d["secret"][:4] + "****"
    return d


@router.patch("/{webhook_id}")
@limiter.limit("10/minute")
async def patch_webhook(
    request: Request, webhook_id: str, body: WebhookUpdateRequest, _=Depends(verify_api_key)
):
    """Update a webhook registration."""
    try:
        wh = update_webhook(
            webhook_id,
            url=body.url,
            events=body.events,
            active=body.active,
            description=body.description,
        )
        if not wh:
            raise ArchmorphException(status_code=404, detail="Webhook not found")
        d = wh.to_dict()
        d["secret"] = d["secret"][:4] + "****"
        return d
    except ValueError as exc:
        raise ArchmorphException(status_code=400, detail=str(exc))


@router.delete("/{webhook_id}")
@limiter.limit("10/minute")
async def remove_webhook(request: Request, webhook_id: str, _=Depends(verify_api_key)):
    """Delete a webhook."""
    if not delete_webhook(webhook_id):
        raise ArchmorphException(status_code=404, detail="Webhook not found")
    return {"deleted": True, "webhook_id": webhook_id}


# ---------------------------------------------------------------------------
# Delivery logs & stats
# ---------------------------------------------------------------------------

@router.get("/{webhook_id}/deliveries")
@limiter.limit("30/minute")
async def webhook_deliveries(
    request: Request, webhook_id: str, limit: int = 50, _=Depends(verify_api_key)
):
    """Get delivery logs for a webhook."""
    wh = get_webhook(webhook_id)
    if not wh:
        raise ArchmorphException(status_code=404, detail="Webhook not found")
    return {"deliveries": get_delivery_logs(webhook_id=webhook_id, limit=limit)}


@router.get("/stats/overview")
@limiter.limit("30/minute")
async def delivery_stats(request: Request, _=Depends(verify_api_key)):
    """Get aggregate delivery statistics."""
    return get_delivery_stats()


# ---------------------------------------------------------------------------
# Integration CRUD
# ---------------------------------------------------------------------------

integration_router = APIRouter(prefix="/api/integrations", tags=["integrations"])


@integration_router.post("")
@limiter.limit("10/minute")
async def create_integration(
    request: Request, body: IntegrationCreateRequest, _=Depends(verify_api_key)
):
    """Register a built-in integration (Slack, Teams, Azure DevOps, GitHub)."""
    try:
        integration = register_integration(
            integration_type=body.type,
            name=body.name,
            config=body.config,
        )
        return {
            "id": integration.id,
            "type": integration.type,
            "name": integration.name,
            "created_at": integration.created_at,
            "required_fields": INTEGRATION_REQUIREMENTS.get(body.type, []),
        }
    except ValueError as exc:
        raise ArchmorphException(status_code=400, detail=str(exc))


@integration_router.get("")
@limiter.limit("30/minute")
async def get_integrations(request: Request, _=Depends(verify_api_key)):
    """List all registered integrations."""
    return {
        "integrations": list_integrations(),
        "supported_types": [t.value for t in IntegrationType],
        "requirements": INTEGRATION_REQUIREMENTS,
    }


@integration_router.delete("/{integration_id}")
@limiter.limit("10/minute")
async def remove_integration(
    request: Request, integration_id: str, _=Depends(verify_api_key)
):
    """Remove an integration."""
    if not delete_integration(integration_id):
        raise ArchmorphException(status_code=404, detail="Integration not found")
    return {"deleted": True, "integration_id": integration_id}
