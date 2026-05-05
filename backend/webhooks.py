"""
Webhook engine — event-driven integration platform.

Provides webhook registration, HMAC-signed delivery with retries,
delivery logging, and built-in integrations (Slack, Teams, Azure DevOps).
"""

import asyncio
import concurrent.futures
import hashlib
import hmac
import ipaddress
import json
import logging
import socket
import ssl
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

import httpx

logger = logging.getLogger("webhooks")

# ---------------------------------------------------------------------------
# Event types
# ---------------------------------------------------------------------------

class WebhookEventType(str, Enum):
    ANALYSIS_COMPLETED = "analysis.completed"
    IAC_GENERATED = "iac.generated"
    HLD_EXPORTED = "hld.exported"
    HLD_READY = "hld.ready"
    REPORT_READY = "report.ready"
    MIGRATION_TIMELINE_CREATED = "migration.timeline_created"
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
_MAX_LOGS = 10000
_delivery_logs: deque = deque(maxlen=_MAX_LOGS)

# Retry config
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2  # seconds — exponential: 2, 4, 8
DELIVERY_TIMEOUT = 10  # seconds
DNS_RESOLUTION_TIMEOUT = 3  # seconds


def _contains_control_characters(value: str) -> bool:
    return any(ord(char) < 32 or ord(char) == 127 for char in value)


def _reject_control_characters(*values: str) -> None:
    if any(_contains_control_characters(value) for value in values):
        raise WebhookTargetError("Webhook URL must not include control characters")


class WebhookTargetError(ValueError):
    """Raised when a webhook URL targets an unsafe outbound destination."""


@dataclass(frozen=True)
class WebhookTarget:
    hostname: str
    port: int
    path: str
    needs_resolution: bool
    literal_address: Optional[str] = None


def _normalize_ip_address(address: str) -> Optional[str]:
    candidate = address.split("%", 1)[0]
    try:
        ip = ipaddress.ip_address(candidate)
    except ValueError:
        return None
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return str(ip)


def _is_forbidden_ip(address: str) -> bool:
    normalized = _normalize_ip_address(address)
    if normalized is None:
        return True
    return not ipaddress.ip_address(normalized).is_global


def _addresses_from_addr_info(addr_info: list) -> List[str]:
    addresses: List[str] = []
    for entry in addr_info:
        sockaddr = entry[4]
        if not sockaddr:
            continue
        address = sockaddr[0]
        if address not in addresses:
            addresses.append(address)

    if not addresses:
        raise WebhookTargetError("Webhook target host could not be resolved")
    return addresses


def _resolve_host_addresses(hostname: str, port: int) -> List[str]:
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="webhook-dns")
    future = executor.submit(socket.getaddrinfo, hostname, port, type=socket.SOCK_STREAM)
    try:
        addr_info = future.result(timeout=DNS_RESOLUTION_TIMEOUT)
    except socket.gaierror as exc:
        raise WebhookTargetError("Webhook target host could not be resolved") from exc
    except concurrent.futures.TimeoutError as exc:
        future.cancel()
        raise WebhookTargetError("Webhook target DNS lookup timed out") from exc
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
    return _addresses_from_addr_info(addr_info)


async def _resolve_host_addresses_async(hostname: str, port: int) -> List[str]:
    try:
        addr_info = await asyncio.wait_for(
            asyncio.get_running_loop().getaddrinfo(
                hostname,
                port,
                type=socket.SOCK_STREAM,
            ),
            timeout=DNS_RESOLUTION_TIMEOUT,
        )
    except socket.gaierror as exc:
        raise WebhookTargetError("Webhook target host could not be resolved") from exc
    except asyncio.TimeoutError as exc:
        raise WebhookTargetError("Webhook target DNS lookup timed out") from exc
    return _addresses_from_addr_info(addr_info)


def _parse_webhook_target(url: str) -> WebhookTarget:
    _reject_control_characters(url)
    parsed = urlsplit(url)
    _reject_control_characters(parsed.scheme, parsed.netloc, parsed.path, parsed.query)
    if parsed.scheme.lower() != "https":
        raise WebhookTargetError("Webhook URL must use HTTPS")
    if not parsed.hostname:
        raise WebhookTargetError("Webhook URL must include a host")
    if parsed.username or parsed.password:
        raise WebhookTargetError("Webhook URL must not include credentials")
    try:
        parsed_port = parsed.port
    except ValueError as exc:
        raise WebhookTargetError("Webhook URL port is invalid") from exc
    port = 443 if parsed_port is None else parsed_port
    if port < 1 or port > 65535:
        raise WebhookTargetError("Webhook URL port is invalid")

    hostname = parsed.hostname.rstrip(".").lower()
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"

    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise WebhookTargetError("Webhook target host is not allowed")

    literal_address: Optional[str] = None
    try:
        host_ip = ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        literal_address = str(host_ip.ipv4_mapped if isinstance(host_ip, ipaddress.IPv6Address) and host_ip.ipv4_mapped else host_ip)
        if _is_forbidden_ip(literal_address):
            raise WebhookTargetError("Webhook target host is not allowed")
        return WebhookTarget(hostname=hostname, port=port, path=path, needs_resolution=False, literal_address=literal_address)

    return WebhookTarget(hostname=hostname, port=port, path=path, needs_resolution=True)


def _reject_forbidden_addresses(addresses: List[str]) -> None:
    if any(_is_forbidden_ip(address) for address in addresses):
        raise WebhookTargetError("Webhook target host resolves to a non-public IP address")


def validate_webhook_target_url(url: str, *, resolve: bool = False) -> None:
    """Validate that a webhook URL is HTTPS and does not target private networks."""
    target = _parse_webhook_target(url)

    if not resolve or not target.needs_resolution:
        return

    addresses = _resolve_host_addresses(target.hostname, target.port)
    _reject_forbidden_addresses(addresses)


async def validate_webhook_target_url_async(url: str, *, resolve: bool = False) -> None:
    """Async variant of webhook URL validation for request and delivery paths."""
    target = _parse_webhook_target(url)

    if not resolve or not target.needs_resolution:
        return

    addresses = await _resolve_host_addresses_async(target.hostname, target.port)
    _reject_forbidden_addresses(addresses)


def _validated_target_addresses(target: WebhookTarget, addresses: List[str]) -> List[str]:
    if target.literal_address:
        return [target.literal_address]
    _reject_forbidden_addresses(addresses)
    return [_normalize_ip_address(address) or address for address in addresses]


async def _resolve_target_addresses_async(target: WebhookTarget) -> List[str]:
    if not target.needs_resolution:
        return _validated_target_addresses(target, [])
    return _validated_target_addresses(
        target,
        await _resolve_host_addresses_async(target.hostname, target.port),
    )


def _resolve_target_addresses(target: WebhookTarget) -> List[str]:
    if not target.needs_resolution:
        return _validated_target_addresses(target, [])
    return _validated_target_addresses(target, _resolve_host_addresses(target.hostname, target.port))


def _host_header(target: WebhookTarget) -> str:
    host = target.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    if target.port != 443:
        return f"{host}:{target.port}"
    return host


def _format_http_headers(headers: Dict[str, str]) -> str:
    lines: List[str] = []
    for key, value in headers.items():
        if _contains_control_characters(key) or _contains_control_characters(str(value)):
            raise WebhookTargetError("Webhook request headers must not include control characters")
        lines.append(f"{key}: {value}")
    return "\r\n".join(lines)


def _http_response_status(response_head: bytes) -> int:
    status_line = response_head.split(b"\r\n", 1)[0].decode("ascii", errors="replace")
    parts = status_line.split(" ", 2)
    if len(parts) < 2 or not parts[1].isdigit():
        raise WebhookTargetError("Webhook target returned an invalid HTTP response")
    return int(parts[1])


def _webhook_ssl_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


async def _post_https_pinned_async(
    url: str,
    *,
    content: bytes,
    headers: Dict[str, str],
    timeout: float,
) -> int:
    target = _parse_webhook_target(url)
    addresses = await _resolve_target_addresses_async(target)
    ssl_context = _webhook_ssl_context()
    request_headers = {
        **headers,
        "Host": _host_header(target),
        "Content-Length": str(len(content)),
        "Connection": "close",
    }
    request = (
        f"POST {target.path} HTTP/1.1\r\n"
        + _format_http_headers(request_headers)
        + "\r\n\r\n"
    ).encode("utf-8") + content

    last_error: Optional[Exception] = None
    for address in addresses:
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(
                    address,
                    target.port,
                    ssl=ssl_context,
                    server_hostname=target.hostname,
                ),
                timeout=timeout,
            )
            try:
                writer.write(request)
                await asyncio.wait_for(writer.drain(), timeout=timeout)
                response_head = await asyncio.wait_for(reader.read(1024), timeout=timeout)
                return _http_response_status(response_head)
            finally:
                writer.close()
                await writer.wait_closed()
        except Exception as exc:
            last_error = exc

    if last_error is not None:
        raise last_error
    raise WebhookTargetError("Webhook target host could not be resolved")


def _post_https_pinned_json(url: str, *, payload: Dict[str, Any], timeout: float) -> int:
    target = _parse_webhook_target(url)
    addresses = _resolve_target_addresses(target)
    body = json.dumps(payload, default=str).encode("utf-8")
    ssl_context = _webhook_ssl_context()
    request_headers = {
        "Host": _host_header(target),
        "Content-Type": "application/json",
        "Content-Length": str(len(body)),
        "User-Agent": "Archmorph-Webhooks/1.0",
        "Connection": "close",
    }
    request = (
        f"POST {target.path} HTTP/1.1\r\n"
        + _format_http_headers(request_headers)
        + "\r\n\r\n"
    ).encode("utf-8") + body

    last_error: Optional[Exception] = None
    for address in addresses:
        try:
            with socket.create_connection((address, target.port), timeout=timeout) as sock:
                with ssl_context.wrap_socket(sock, server_hostname=target.hostname) as tls_sock:
                    tls_sock.settimeout(timeout)
                    tls_sock.sendall(request)
                    return _http_response_status(tls_sock.recv(1024))
        except Exception as exc:
            last_error = exc

    if last_error is not None:
        raise last_error
    raise WebhookTargetError("Webhook target host could not be resolved")


def register_webhook(
    url: str,
    events: List[str],
    secret: Optional[str] = None,
    owner_id: str = "system",
    description: str = "",
) -> WebhookRegistration:
    """Register a new webhook endpoint."""
    validate_webhook_target_url(url, resolve=True)

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
            validate_webhook_target_url(url, resolve=True)
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

async def _deliver_payload(
    url: str,
    payload_bytes: bytes,
    signature: str,
    event_type: str,
    delivery_id: str,
) -> DeliveryAttempt:
    """Attempt a single HTTP POST delivery (async)."""
    start = time.monotonic()
    try:
        status_code = await _post_https_pinned_async(
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
        success = 200 <= status_code < 300
        return DeliveryAttempt(
            attempt=0,
            timestamp=datetime.now(timezone.utc).isoformat(),
            status_code=status_code,
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


async def _dispatch_single(wh: WebhookRegistration, event_type: str, payload: Dict[str, Any]) -> DeliveryLog:
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
        result = await _deliver_payload(wh.url, payload_bytes, signature, event_type, delivery_id)
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
            await asyncio.sleep(wait)

    if not log.delivered:
        log.final_status = "failed"
        logger.error("Webhook %s delivery failed after %d attempts", delivery_id, MAX_RETRIES)

    # Store delivery log
    with _lock:
        _delivery_logs.append(log)

    return log


async def dispatch_event(event_type: str, payload: Dict[str, Any]) -> List[DeliveryLog]:
    """Dispatch an event to all subscribed webhooks (async, non-blocking)."""
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

    tasks = [_dispatch_single(wh, event_type, payload) for wh in subscribers]
    logs = await asyncio.gather(*tasks, return_exceptions=True)
    # Filter out exceptions, log them
    result: List[DeliveryLog] = []
    for log in logs:
        if isinstance(log, Exception):
            logger.error("Webhook dispatch error: %s", log)
        else:
            result.append(log)
    return result


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

    if integration_type in {IntegrationType.SLACK, IntegrationType.TEAMS}:
        validate_webhook_target_url(config["webhook_url"], resolve=True)

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
            status_code = _post_https_pinned_json(
                integration.config["webhook_url"],
                payload=payload,
                timeout=10,
            )
            result["status_code"] = status_code
            result["success"] = 200 <= status_code < 300

        elif integration.type == IntegrationType.TEAMS:
            payload = _format_teams_card(event_type, data)
            status_code = _post_https_pinned_json(
                integration.config["webhook_url"],
                payload=payload,
                timeout=10,
            )
            result["status_code"] = status_code
            result["success"] = 200 <= status_code < 300

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

async def emit_event(event_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Emit an event to all subscribers (webhooks + integrations).

    This is the primary API for other modules to trigger webhook delivery.
    """
    webhook_logs = await dispatch_event(event_type, payload)
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
