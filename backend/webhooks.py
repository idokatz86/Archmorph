"""
Webhook engine — event-driven integration platform.

Provides webhook registration, HMAC-signed delivery with retries,
delivery logging, and built-in integrations (Slack, Teams, Azure DevOps).
"""

import hashlib
import hmac
import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger("webhooks")

# ---------------------------------------------------------------------------
# Event types
# ---------------------------------------------------------------------------

class WebhookEventType(str, Enum):
    ANALYSIS_COMPLETED = "analysis.completed"
    IAC_GENERATED = "iac.generated"
    HLD_EXPORTED = "hld.exported"
    VERSION_CREATED = "version.created"
    RISK_SCORE_CHANGED = "risk.score_changed"
    COMPLIANCE_ASSESSED = "compliance.assessed"
    INFRA_IMPORTED = "infra.imported"
    EXPORT_COMPLETED = "export.completed"


ALL_EVENT_TYPES: List[str] = [e.value for e in WebhookEventType]

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class WebhookRegistration:
    id: str
    url: str
    secret: str
    events: List[str]
    created_at: str
    owner_id: str = "system"
    active: bool = True
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DeliveryAttempt:
    attempt: int
    timestamp: str
    status_code: Optional[int] = None
    error: Optional[str] = None
    latency_ms: float = 0.0
    success: bool = False


@dataclass
class DeliveryLog:
    id: str
    webhook_id: str
    event_type: str
    payload: Dict[str, Any]
    created_at: str
    attempts: List[DeliveryAttempt] = field(default_factory=list)
    delivered: bool = False
    final_status: str = "pending"

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d


# ---------------------------------------------------------------------------
# HMAC signing
# ---------------------------------------------------------------------------

def compute_signature(payload_bytes: bytes, secret: str) -> str:
    """Compute HMAC-SHA256 signature for payload verification."""
    return hmac.new(
        secret.encode("utf-8"),
        payload_bytes,
        hashlib.sha256,
    ).hexdigest()


def verify_signature(payload_bytes: bytes, secret: str, signature: str) -> bool:
    """Verify HMAC-SHA256 signature."""
    expected = compute_signature(payload_bytes, secret)
    return hmac.compare_digest(expected, signature)


# ---------------------------------------------------------------------------
# Webhook registry (in-memory, thread-safe)
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_webhooks: Dict[str, WebhookRegistration] = {}
_delivery_logs: List[DeliveryLog] = []
_MAX_LOGS = 10000

# Retry config
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2  # seconds — exponential: 2, 4, 8
DELIVERY_TIMEOUT = 10  # seconds


def register_webhook(
    url: str,
    events: List[str],
    secret: Optional[str] = None,
    owner_id: str = "system",
    description: str = "",
) -> WebhookRegistration:
    """Register a new webhook endpoint."""
    if not url or not url.startswith(("http://", "https://")):
        raise ValueError("Webhook URL must start with http:// or https://")

    # Validate event types
    invalid = [e for e in events if e not in ALL_EVENT_TYPES]
    if invalid:
        raise ValueError(f"Invalid event types: {invalid}")

    if not events:
        raise ValueError("At least one event type required")

    wh = WebhookRegistration(
        id=f"wh-{uuid.uuid4().hex[:12]}",
        url=url,
        secret=secret or uuid.uuid4().hex,
        events=events,
        created_at=datetime.now(timezone.utc).isoformat(),
        owner_id=owner_id,
        description=description,
    )

    with _lock:
        _webhooks[wh.id] = wh

    logger.info("Registered webhook %s for events %s", wh.id, events)
    return wh


def list_webhooks(owner_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """List all registered webhooks, optionally filtered by owner."""
    with _lock:
        hooks = list(_webhooks.values())

    if owner_id:
        hooks = [h for h in hooks if h.owner_id == owner_id]

    result = []
    for h in hooks:
        d = h.to_dict()
        d["secret"] = d["secret"][:4] + "****"  # mask secret
        result.append(d)
    return result


def get_webhook(webhook_id: str) -> Optional[WebhookRegistration]:
    """Get a webhook by ID."""
    with _lock:
        return _webhooks.get(webhook_id)


def delete_webhook(webhook_id: str) -> bool:
    """Remove a webhook registration."""
    with _lock:
        if webhook_id in _webhooks:
            del _webhooks[webhook_id]
            logger.info("Deleted webhook %s", webhook_id)
            return True
    return False


def update_webhook(
    webhook_id: str,
    url: Optional[str] = None,
    events: Optional[List[str]] = None,
    active: Optional[bool] = None,
    description: Optional[str] = None,
) -> Optional[WebhookRegistration]:
    """Update a webhook registration."""
    with _lock:
        wh = _webhooks.get(webhook_id)
        if not wh:
            return None
        if url is not None:
            wh.url = url
        if events is not None:
            invalid = [e for e in events if e not in ALL_EVENT_TYPES]
            if invalid:
                raise ValueError(f"Invalid event types: {invalid}")
            wh.events = events
        if active is not None:
            wh.active = active
        if description is not None:
            wh.description = description
    return wh


# ---------------------------------------------------------------------------
# Delivery engine
# ---------------------------------------------------------------------------

def _deliver_payload(
    url: str,
    payload_bytes: bytes,
    signature: str,
    event_type: str,
    delivery_id: str,
) -> DeliveryAttempt:
    """Attempt a single HTTP POST delivery."""
    start = time.monotonic()
    try:
        resp = httpx.post(
            url,
            content=payload_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Archmorph-Signature": f"sha256={signature}",
                "X-Archmorph-Event": event_type,
                "X-Archmorph-Delivery": delivery_id,
                "User-Agent": "Archmorph-Webhooks/1.0",
            },
            timeout=DELIVERY_TIMEOUT,
        )
        latency = (time.monotonic() - start) * 1000
        success = 200 <= resp.status_code < 300
        return DeliveryAttempt(
            attempt=0,
            timestamp=datetime.now(timezone.utc).isoformat(),
            status_code=resp.status_code,
            latency_ms=round(latency, 2),
            success=success,
        )
    except Exception as exc:
        latency = (time.monotonic() - start) * 1000
        return DeliveryAttempt(
            attempt=0,
            timestamp=datetime.now(timezone.utc).isoformat(),
            error=str(exc)[:200],
            latency_ms=round(latency, 2),
            success=False,
        )


def _dispatch_single(wh: WebhookRegistration, event_type: str, payload: Dict[str, Any]) -> DeliveryLog:
    """Deliver a webhook with retries and logging."""
    delivery_id = f"dlv-{uuid.uuid4().hex[:12]}"
    envelope = {
        "event": event_type,
        "delivery_id": delivery_id,
        "webhook_id": wh.id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": payload,
    }
    payload_bytes = json.dumps(envelope, default=str).encode("utf-8")
    signature = compute_signature(payload_bytes, wh.secret)

    log = DeliveryLog(
        id=delivery_id,
        webhook_id=wh.id,
        event_type=event_type,
        payload=envelope,
        created_at=datetime.now(timezone.utc).isoformat(),
    )

    for attempt_num in range(1, MAX_RETRIES + 1):
        result = _deliver_payload(wh.url, payload_bytes, signature, event_type, delivery_id)
        result.attempt = attempt_num
        log.attempts.append(result)

        if result.success:
            log.delivered = True
            log.final_status = "delivered"
            logger.info("Webhook %s delivered to %s (attempt %d)", delivery_id, wh.url, attempt_num)
            break

        if attempt_num < MAX_RETRIES:
            wait = RETRY_BACKOFF_BASE ** attempt_num
            logger.warning(
                "Webhook %s delivery attempt %d failed (%s), retrying in %ds",
                delivery_id, attempt_num, result.error or f"HTTP {result.status_code}", wait,
            )
            time.sleep(wait)

    if not log.delivered:
        log.final_status = "failed"
        logger.error("Webhook %s delivery failed after %d attempts", delivery_id, MAX_RETRIES)

    # Store delivery log
    with _lock:
        _delivery_logs.append(log)
        if len(_delivery_logs) > _MAX_LOGS:
            _delivery_logs.pop(0)

    return log


def dispatch_event(event_type: str, payload: Dict[str, Any]) -> List[DeliveryLog]:
    """Dispatch an event to all subscribed webhooks (async via threads)."""
    if event_type not in ALL_EVENT_TYPES:
        logger.warning("Unknown event type: %s", event_type)
        return []

    with _lock:
        subscribers = [
            wh for wh in _webhooks.values()
            if wh.active and event_type in wh.events
        ]

    if not subscribers:
        return []

    logs: List[DeliveryLog] = []
    threads: List[threading.Thread] = []

    for wh in subscribers:
        t = threading.Thread(
            target=lambda w=wh: logs.append(_dispatch_single(w, event_type, payload)),
            daemon=True,
        )
        threads.append(t)
        t.start()

    for t in threads:
        t.join(timeout=DELIVERY_TIMEOUT * MAX_RETRIES + 30)

    return logs


def get_delivery_logs(
    webhook_id: Optional[str] = None,
    event_type: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """Retrieve delivery logs with optional filtering."""
    with _lock:
        logs = list(_delivery_logs)

    if webhook_id:
        logs = [entry for entry in logs if entry.webhook_id == webhook_id]
    if event_type:
        logs = [entry for entry in logs if entry.event_type == event_type]

    logs = sorted(logs, key=lambda entry: entry.created_at, reverse=True)[:limit]
    return [entry.to_dict() for entry in logs]


def get_delivery_stats() -> Dict[str, Any]:
    """Get aggregate delivery statistics."""
    with _lock:
        logs = list(_delivery_logs)

    total = len(logs)
    delivered = sum(1 for entry in logs if entry.delivered)
    failed = total - delivered

    by_event: Dict[str, Dict[str, int]] = {}
    for log in logs:
        if log.event_type not in by_event:
            by_event[log.event_type] = {"delivered": 0, "failed": 0}
        if log.delivered:
            by_event[log.event_type]["delivered"] += 1
        else:
            by_event[log.event_type]["failed"] += 1

    return {
        "total_deliveries": total,
        "delivered": delivered,
        "failed": failed,
        "success_rate": round(delivered / total * 100, 1) if total else 100.0,
        "by_event": by_event,
        "active_webhooks": sum(1 for w in _webhooks.values() if w.active),
    }


# ---------------------------------------------------------------------------
# Built-in integrations
# ---------------------------------------------------------------------------

class IntegrationType(str, Enum):
    SLACK = "slack"
    TEAMS = "teams"
    AZURE_DEVOPS = "azure_devops"
    GITHUB = "github"


@dataclass
class IntegrationConfig:
    id: str
    type: str
    name: str
    config: Dict[str, str]
    enabled: bool = True
    created_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # Mask secrets
        masked = {}
        for k, v in d["config"].items():
            if "token" in k.lower() or "secret" in k.lower() or "key" in k.lower():
                masked[k] = v[:4] + "****" if len(v) > 4 else "****"
            else:
                masked[k] = v
        d["config"] = masked
        return d


_integrations: Dict[str, IntegrationConfig] = {}


def register_integration(
    integration_type: str,
    name: str,
    config: Dict[str, str],
) -> IntegrationConfig:
    """Register a built-in integration (Slack, Teams, etc.)."""
    if integration_type not in [t.value for t in IntegrationType]:
        raise ValueError(f"Unsupported integration type: {integration_type}")

    required_fields = INTEGRATION_REQUIREMENTS.get(integration_type, [])
    missing = [f for f in required_fields if f not in config]
    if missing:
        raise ValueError(f"Missing required config fields: {missing}")

    integration = IntegrationConfig(
        id=f"int-{uuid.uuid4().hex[:12]}",
        type=integration_type,
        name=name,
        config=config,
        created_at=datetime.now(timezone.utc).isoformat(),
    )

    with _lock:
        _integrations[integration.id] = integration

    logger.info("Registered %s integration: %s", integration_type, name)
    return integration


def list_integrations() -> List[Dict[str, Any]]:
    """List all registered integrations."""
    with _lock:
        return [i.to_dict() for i in _integrations.values()]


def delete_integration(integration_id: str) -> bool:
    """Remove an integration."""
    with _lock:
        if integration_id in _integrations:
            del _integrations[integration_id]
            return True
    return False


def get_integration(integration_id: str) -> Optional[IntegrationConfig]:
    """Get integration by ID."""
    with _lock:
        return _integrations.get(integration_id)


# Integration requirements
INTEGRATION_REQUIREMENTS: Dict[str, List[str]] = {
    "slack": ["webhook_url"],
    "teams": ["webhook_url"],
    "azure_devops": ["organization", "project", "pat_token"],
    "github": ["repo", "token"],
}


# ---------------------------------------------------------------------------
# Integration dispatchers
# ---------------------------------------------------------------------------

def _format_slack_message(event_type: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Format a Slack incoming webhook payload."""
    emoji_map = {
        "analysis.completed": ":mag:",
        "iac.generated": ":hammer_and_wrench:",
        "hld.exported": ":page_facing_up:",
        "version.created": ":bookmark:",
        "risk.score_changed": ":warning:",
        "compliance.assessed": ":shield:",
        "infra.imported": ":inbox_tray:",
        "export.completed": ":outbox_tray:",
    }
    emoji = emoji_map.get(event_type, ":bell:")
    diagram_id = data.get("diagram_id", "unknown")

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"{emoji} *Archmorph Event: `{event_type}`*\n"
                        f"Diagram: `{diagram_id}`",
            },
        },
    ]

    # Add details based on event type
    if event_type == "analysis.completed":
        services = data.get("total_services", 0)
        confidence = data.get("confidence", "N/A")
        blocks.append({
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Services:* {services}"},
                {"type": "mrkdwn", "text": f"*Confidence:* {confidence}"},
            ],
        })
    elif event_type == "risk.score_changed":
        score = data.get("overall_score", "N/A")
        tier = data.get("risk_tier", "N/A")
        blocks.append({
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Risk Score:* {score}"},
                {"type": "mrkdwn", "text": f"*Tier:* {tier}"},
            ],
        })

    return {"blocks": blocks}


def _format_teams_card(event_type: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Format a Microsoft Teams Connector card payload."""
    diagram_id = data.get("diagram_id", "unknown")
    color_map = {
        "analysis.completed": "00CC00",
        "iac.generated": "0078D4",
        "risk.score_changed": "FF8C00",
        "compliance.assessed": "800080",
    }

    facts = [{"name": k, "value": str(v)} for k, v in list(data.items())[:6]]

    return {
        "@type": "MessageCard",
        "@context": "http://schema.org/extensions",
        "themeColor": color_map.get(event_type, "808080"),
        "summary": f"Archmorph: {event_type}",
        "sections": [
            {
                "activityTitle": f"Archmorph Event: {event_type}",
                "activitySubtitle": f"Diagram: {diagram_id}",
                "facts": facts,
                "markdown": True,
            }
        ],
    }


def _format_azure_devops_work_item(event_type: str, data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Format Azure DevOps work item patch document."""
    diagram_id = data.get("diagram_id", "unknown")
    title = f"[Archmorph] {event_type} — {diagram_id}"
    description = json.dumps(data, indent=2, default=str)

    return [
        {"op": "add", "path": "/fields/System.Title", "value": title},
        {"op": "add", "path": "/fields/System.Description", "value": f"<pre>{description}</pre>"},
        {"op": "add", "path": "/fields/System.Tags", "value": "archmorph;auto-generated"},
    ]


def send_to_integration(
    integration: IntegrationConfig,
    event_type: str,
    data: Dict[str, Any],
) -> Dict[str, Any]:
    """Send an event to a built-in integration."""
    result = {
        "integration_id": integration.id,
        "type": integration.type,
        "event_type": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    try:
        if integration.type == IntegrationType.SLACK:
            payload = _format_slack_message(event_type, data)
            resp = httpx.post(
                integration.config["webhook_url"],
                json=payload,
                timeout=10,
            )
            result["status_code"] = resp.status_code
            result["success"] = 200 <= resp.status_code < 300

        elif integration.type == IntegrationType.TEAMS:
            payload = _format_teams_card(event_type, data)
            resp = httpx.post(
                integration.config["webhook_url"],
                json=payload,
                timeout=10,
            )
            result["status_code"] = resp.status_code
            result["success"] = 200 <= resp.status_code < 300

        elif integration.type == IntegrationType.AZURE_DEVOPS:
            org = integration.config["organization"]
            project = integration.config["project"]
            pat = integration.config["pat_token"]
            url = f"https://dev.azure.com/{org}/{project}/_apis/wit/workitems/$Task?api-version=7.0"
            patch_doc = _format_azure_devops_work_item(event_type, data)
            resp = httpx.post(
                url,
                json=patch_doc,
                headers={
                    "Content-Type": "application/json-patch+json",
                    "Authorization": f"Basic {pat}",
                },
                timeout=15,
            )
            result["status_code"] = resp.status_code
            result["success"] = 200 <= resp.status_code < 300

        elif integration.type == IntegrationType.GITHUB:
            repo = integration.config["repo"]
            token = integration.config["token"]
            url = f"https://api.github.com/repos/{repo}/dispatches"
            resp = httpx.post(
                url,
                json={
                    "event_type": f"archmorph.{event_type}",
                    "client_payload": data,
                },
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                },
                timeout=10,
            )
            result["status_code"] = resp.status_code
            result["success"] = 200 <= resp.status_code < 300

    except Exception as exc:
        result["success"] = False
        result["error"] = str(exc)[:200]

    return result


def dispatch_to_integrations(event_type: str, data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Send event to all enabled built-in integrations."""
    with _lock:
        enabled = [i for i in _integrations.values() if i.enabled]

    results = []
    for integration in enabled:
        r = send_to_integration(integration, event_type, data)
        results.append(r)

    return results


# ---------------------------------------------------------------------------
# Convenience: dispatch to both webhooks AND integrations
# ---------------------------------------------------------------------------

def emit_event(event_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Emit an event to all subscribers (webhooks + integrations).

    This is the primary API for other modules to trigger webhook delivery.
    """
    webhook_logs = dispatch_event(event_type, payload)
    integration_results = dispatch_to_integrations(event_type, payload)

    return {
        "event_type": event_type,
        "webhook_deliveries": len(webhook_logs),
        "webhook_successes": sum(1 for wl in webhook_logs if wl.delivered),
        "integration_deliveries": len(integration_results),
        "integration_successes": sum(1 for r in integration_results if r.get("success")),
    }


# ---------------------------------------------------------------------------
# Test / reset helpers
# ---------------------------------------------------------------------------

def clear_all():
    """Clear all registrations and logs (for testing)."""
    with _lock:
        _webhooks.clear()
        _delivery_logs.clear()
        _integrations.clear()
