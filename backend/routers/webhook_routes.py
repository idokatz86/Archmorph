from error_envelope import ArchmorphException
"""
Webhook subscription management routes (Issue #259).

REST API for creating, listing, updating, and deleting webhook
subscriptions, plus delivery log access and test event dispatch.
Builds on the existing ``webhooks`` module.
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from routers.shared import limiter, verify_api_key
from webhooks import (
    ALL_EVENT_TYPES,
    register_webhook,
    list_webhooks,
    get_webhook,
    update_webhook,
    delete_webhook,
    get_delivery_logs,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Webhooks"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class CreateWebhookRequest(BaseModel):
    url: str = Field(..., description="HTTPS endpoint to receive webhook POSTs")
    events: List[str] = Field(..., min_length=1, description="Event types to subscribe to")
    description: str = Field("", max_length=256, description="Human-readable description")
    secret: Optional[str] = Field(None, description="HMAC secret (auto-generated if omitted)")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "url": "https://example.com/webhook",
                "events": ["analysis.completed", "iac.generated"],
                "description": "My CI pipeline hook",
            }
        }
    )


class UpdateWebhookRequest(BaseModel):
    url: Optional[str] = Field(None, description="New endpoint URL")
    events: Optional[List[str]] = Field(None, description="Updated event list")
    active: Optional[bool] = Field(None, description="Enable/disable delivery")
    description: Optional[str] = Field(None, max_length=256)


class TestWebhookRequest(BaseModel):
    url: str = Field(..., description="URL to send the test event to")
    secret: str = Field("test-secret", description="HMAC secret for signature")
    event_type: str = Field("analysis.completed", description="Event type to simulate")


class WebhookInfo(BaseModel):
    id: str
    url: str
    secret: str  # masked
    events: List[str]
    created_at: str
    owner_id: str
    active: bool
    description: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post(
    "/api/webhooks",
    summary="Create webhook subscription",
    description="Register a URL to receive event notifications via HTTP POST. "
                "Each delivery includes an HMAC-SHA256 signature in the "
                "`X-Archmorph-Signature` header for payload verification.",
)
@limiter.limit("10/minute")
async def create_webhook(body: CreateWebhookRequest, request: Request, _auth=Depends(verify_api_key)):
    if not body.url.startswith("https://"):
        raise ArchmorphException(400, "Webhook URL must use HTTPS")

    # Validate event types against known list
    invalid = [e for e in body.events if e not in ALL_EVENT_TYPES]
    if invalid:
        raise ArchmorphException(
            400, f"Invalid event types: {invalid}. Valid: {sorted(ALL_EVENT_TYPES)}"
        )

    try:
        wh = register_webhook(
            url=body.url,
            events=body.events,
            secret=body.secret,
            description=body.description,
        )
    except ValueError as exc:
        raise ArchmorphException(400, str(exc))

    result = wh.to_dict()
    result["secret"] = result["secret"][:4] + "****"
    return result


@router.get(
    "/api/webhooks",
    summary="List webhook subscriptions",
    description="Return all active webhook subscriptions. Secrets are masked.",
)
@limiter.limit("30/minute")
async def list_webhooks_route(request: Request, _auth=Depends(verify_api_key)):
    return list_webhooks()


@router.put(
    "/api/webhooks/{webhook_id}",
    summary="Update webhook subscription",
    description="Modify URL, events, active status, or description of an existing subscription.",
)
@limiter.limit("10/minute")
async def update_webhook_route(
    webhook_id: str, body: UpdateWebhookRequest, request: Request, _auth=Depends(verify_api_key),
):
    wh = get_webhook(webhook_id)
    if not wh:
        raise ArchmorphException(404, f"Webhook not found: {webhook_id}")

    if body.url and not body.url.startswith("https://"):
        raise ArchmorphException(400, "Webhook URL must use HTTPS")

    if body.events:
        invalid = [e for e in body.events if e not in ALL_EVENT_TYPES]
        if invalid:
            raise ArchmorphException(400, f"Invalid event types: {invalid}")

    try:
        updated = update_webhook(
            webhook_id,
            url=body.url,
            events=body.events,
            active=body.active,
            description=body.description,
        )
    except ValueError as exc:
        raise ArchmorphException(400, str(exc))

    if not updated:
        raise ArchmorphException(404, f"Webhook not found: {webhook_id}")

    result = updated.to_dict()
    result["secret"] = result["secret"][:4] + "****"
    return result


@router.delete(
    "/api/webhooks/{webhook_id}",
    summary="Delete webhook subscription",
    description="Permanently remove a webhook subscription.",
)
@limiter.limit("10/minute")
async def delete_webhook_route(webhook_id: str, request: Request, _auth=Depends(verify_api_key)):
    if not delete_webhook(webhook_id):
        raise ArchmorphException(404, f"Webhook not found: {webhook_id}")
    return {"status": "deleted", "webhook_id": webhook_id}


@router.get(
    "/api/webhooks/{webhook_id}/logs",
    summary="Webhook delivery history",
    description="Retrieve delivery attempt logs for a specific webhook, ordered newest-first.",
)
@limiter.limit("30/minute")
async def webhook_logs(
    webhook_id: str, request: Request, _auth=Depends(verify_api_key),
):
    wh = get_webhook(webhook_id)
    if not wh:
        raise ArchmorphException(404, f"Webhook not found: {webhook_id}")

    limit = int(request.query_params.get("limit", "50"))
    limit = max(1, min(limit, 200))

    logs = get_delivery_logs(webhook_id=webhook_id, limit=limit)
    return {"webhook_id": webhook_id, "logs": logs, "count": len(logs)}


@router.post(
    "/api/webhooks/test",
    summary="Send test webhook event",
    description="Fire a synthetic event to a URL for integration testing. "
                "Does not require an existing subscription.",
)
@limiter.limit("5/minute")
async def test_webhook(body: TestWebhookRequest, request: Request, _auth=Depends(verify_api_key)):
    from webhooks import compute_signature, _deliver_payload
    import json
    import uuid as _uuid
    from datetime import datetime as _dt, timezone as _tz

    if not body.url.startswith("https://"):
        raise ArchmorphException(400, "Test URL must use HTTPS")

    delivery_id = f"test-{_uuid.uuid4().hex[:12]}"
    envelope = {
        "event": body.event_type,
        "delivery_id": delivery_id,
        "webhook_id": "test",
        "timestamp": _dt.now(_tz.utc).isoformat(),
        "data": {
            "test": True,
            "message": "This is a test webhook delivery from Archmorph",
            "diagram_id": "test-diagram-001",
            "total_services": 5,
            "confidence": "high",
        },
    }
    payload_bytes = json.dumps(envelope, default=str).encode("utf-8")
    signature = compute_signature(payload_bytes, body.secret)

    result = await _deliver_payload(
        url=body.url,
        payload_bytes=payload_bytes,
        signature=signature,
        event_type=body.event_type,
        delivery_id=delivery_id,
    )

    return {
        "delivery_id": delivery_id,
        "status": "delivered" if result.success else "failed",
        "status_code": result.status_code,
        "latency_ms": result.latency_ms,
        "error": result.error,
    }
