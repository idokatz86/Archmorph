from error_envelope import ArchmorphException
"""
Admin Authentication, Metrics, Monitoring, Audit, Observability, Analytics routes.
"""

from fastapi import APIRouter, HTTPException, Depends, Header, Query, Request
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
import time
import logging

from routers.shared import limiter, verify_admin_key
from admin_auth import (
    verify_admin_secret, create_session_token,
    revoke_token, is_configured as admin_is_configured,
)
from usage_metrics import (
    get_metrics_summary, get_daily_metrics, get_recent_events,
    get_funnel_metrics,
)
from audit_logging import (
    log_audit_event, get_audit_logs, get_audit_summary, clear_audit_logs,
    AuditEventType, AuditSeverity,
)
from observability import get_metrics
from feedback import get_feedback_summary, get_nps_trend
from auth import get_leads_summary
from analytics import (
    get_analytics_summary, get_performance_metrics,
    get_feature_metrics, get_conversion_funnel,
)

logger = logging.getLogger(__name__)

router = APIRouter()


class AdminLoginRequest(BaseModel):
    """Body for POST /api/admin/login."""
    key: str = Field(..., min_length=1, description="Admin secret key")


@router.post("/api/admin/login")
@limiter.limit("5/minute")
async def admin_login(request: Request, body: AdminLoginRequest):
    """Authenticate with the admin key and receive a session JWT."""
    if not admin_is_configured():
        raise ArchmorphException(503, "Admin API not configured")
    if not verify_admin_secret(body.key):
        raise ArchmorphException(403, "Invalid admin key")
    token = create_session_token()
    return {"token": token, "expires_in_minutes": 60}


@router.post("/api/admin/logout")
@limiter.limit("10/minute")
async def admin_logout(request: Request, authorization: Optional[str] = Header(None)):
    """Revoke the current admin session token."""
    if not authorization or not authorization.startswith("Bearer "):
        raise ArchmorphException(400, "No token provided")
    token = authorization[7:]
    revoke_token(token)
    return {"status": "logged_out"}


@router.get("/api/admin/metrics")
@limiter.limit("30/minute")
async def admin_metrics_summary(request: Request, _admin=Depends(verify_admin_key)):
    """Return aggregate usage metrics (admin only)."""
    return get_metrics_summary()


@router.get("/api/admin/metrics/funnel")
@limiter.limit("30/minute")
async def admin_funnel(request: Request, _admin=Depends(verify_admin_key)):
    """Return conversion funnel data (admin only)."""
    return get_funnel_metrics()


@router.get("/api/admin/metrics/daily")
@limiter.limit("30/minute")
async def admin_metrics_daily(request: Request, days: int = Query(30, ge=1, le=365), _admin=Depends(verify_admin_key)):
    """Return daily metrics for the last N days (admin only)."""
    return {"days": days, "data": get_daily_metrics(days)}


@router.get("/api/admin/metrics/recent")
@limiter.limit("30/minute")
async def admin_metrics_recent(request: Request, limit: int = Query(50, ge=1, le=200), _admin=Depends(verify_admin_key)):
    """Return the most recent usage events (admin only)."""
    return {"events": get_recent_events(limit)}


@router.get("/api/admin/costs")
@limiter.limit("30/minute")
async def admin_cost_dashboard(request: Request, _admin=Depends(verify_admin_key)):
    """
    Return estimated monthly Azure costs for the Archmorph platform itself.
    Based on actual deployed resource SKUs (not user diagrams).
    """
    # Estimated costs per resource (USD/month, pay-as-you-go North Europe)
    resources = [
        {"name": "Container Apps (0.5 vCPU, 1Gi)", "category": "Compute", "monthly_usd": 36.50, "notes": "Always-on single instance"},
        {"name": "Azure OpenAI (GPT-4o)", "category": "AI", "monthly_usd": 0.0, "notes": "Pay-per-token: ~$2.50/1K images analyzed"},
        {"name": "Static Web Apps (Free)", "category": "Frontend", "monthly_usd": 0.0, "notes": "Free tier"},
        {"name": "Container Registry (Basic)", "category": "Containers", "monthly_usd": 5.0, "notes": "Basic SKU"},
        {"name": "Log Analytics (PerGB2018)", "category": "Monitoring", "monthly_usd": 2.76, "notes": "~1 GB/month ingest"},
        {"name": "Storage Account (LRS)", "category": "Storage", "monthly_usd": 0.50, "notes": "Blob storage for metrics"},
        {"name": "PostgreSQL Flex (B1ms)", "category": "Database", "monthly_usd": 12.90, "notes": "Burstable B1ms, 32GB storage"},
        {"name": "Key Vault (Standard)", "category": "Security", "monthly_usd": 0.03, "notes": "3 secrets"},
    ]

    # Compute per-token OpenAI cost estimate from actual usage
    metrics = get_metrics_summary()
    analyses = metrics["totals"].get("analyses_run", 0)
    iac_generated = metrics["totals"].get("iac_generated_terraform", 0) + metrics["totals"].get("iac_generated_bicep", 0)
    hld_count = metrics["totals"].get("hld_generated", 0)
    chat_msgs = metrics["totals"].get("iac_chat_messages", 0) + metrics["totals"].get("chat_messages", 0)

    # Rough token estimates: vision ~1500 tokens in + 4000 out, IaC ~2000 in + 8000 out
    input_tokens = analyses * 2000 + iac_generated * 2000 + hld_count * 2000 + chat_msgs * 500
    output_tokens = analyses * 4000 + iac_generated * 8000 + hld_count * 8000 + chat_msgs * 1000
    # GPT-4o pricing: $2.50/1M input, $10/1M output
    openai_cost = round(input_tokens * 2.50 / 1_000_000 + output_tokens * 10.0 / 1_000_000, 2)
    resources[1]["monthly_usd"] = openai_cost
    resources[1]["notes"] = f"~{input_tokens:,} in + {output_tokens:,} out tokens used"

    total = round(sum(r["monthly_usd"] for r in resources), 2)

    return {
        "total_monthly_usd": total,
        "currency": "USD",
        "region": "North Europe",
        "resources": resources,
        "usage_based": {
            "analyses_run": analyses,
            "iac_generated": iac_generated,
            "hld_generated": hld_count,
            "chat_messages": chat_msgs,
            "estimated_input_tokens": input_tokens,
            "estimated_output_tokens": output_tokens,
            "openai_cost_usd": openai_cost,
        },
    }


@router.get("/api/admin/monitoring")
@limiter.limit("30/minute")
async def admin_monitoring_dashboard(request: Request, _admin=Depends(verify_admin_key)):
    """
    Return real-time application monitoring data for the admin dashboard.

    Aggregates in-memory observability metrics (request counts, latency
    histograms, error rates, endpoint performance) into a structured
    read-only payload.  No Azure subscription IDs are exposed.
    """
    raw = get_metrics()

    # ── Request traffic ──
    total_requests = 0
    total_errors = 0
    status_breakdown: Dict[str, int] = {}
    endpoint_stats: Dict[str, Dict[str, Any]] = {}

    for key, counter in raw.get("counters", {}).items():
        tags = counter.get("tags", {})
        val = counter.get("value", 0)

        if key == "http.requests.total":
            total_requests += val
            path = tags.get("path", "unknown")
            method = tags.get("method", "")
            ep_key = f"{method} {path}"
            endpoint_stats.setdefault(ep_key, {"requests": 0, "errors": 0})
            endpoint_stats[ep_key]["requests"] += val

        elif key == "http.errors.total":
            total_errors += val
            status = tags.get("status", "unknown")
            status_breakdown[status] = status_breakdown.get(status, 0) + val
            path = tags.get("path", "unknown")
            method = tags.get("method", "")
            ep_key = f"{method} {path}"
            endpoint_stats.setdefault(ep_key, {"requests": 0, "errors": 0})
            endpoint_stats[ep_key]["errors"] += val

    # ── Latency ──
    latency_global = {}
    for key, hist in raw.get("histograms", {}).items():
        if key == "http.request.duration_ms":
            latency_global = {
                "avg_ms": round(hist.get("avg", 0), 1),
                "p50_ms": round(hist.get("p50", 0), 1),
                "p95_ms": round(hist.get("p95", 0), 1),
                "p99_ms": round(hist.get("p99", 0), 1),
                "max_ms": round(hist.get("max", 0), 1),
                "total_samples": hist.get("count", 0),
            }
            # Attach latency to matching endpoint
            tags = hist.get("tags", {})
            path = tags.get("path", "")
            method = tags.get("method", "")
            if path:
                ep_key = f"{method} {path}"
                if ep_key in endpoint_stats:
                    endpoint_stats[ep_key]["avg_ms"] = round(hist.get("avg", 0), 1)
                    endpoint_stats[ep_key]["p95_ms"] = round(hist.get("p95", 0), 1)

    # ── Top endpoints by request volume ──
    top_endpoints = sorted(
        [
            {"endpoint": k, **v}
            for k, v in endpoint_stats.items()
            if not k.endswith("/health") and not k.endswith("/favicon.ico")
        ],
        key=lambda x: x["requests"],
        reverse=True,
    )[:20]

    # ── Error rate ──
    error_rate = round((total_errors / total_requests) * 100, 2) if total_requests > 0 else 0

    # ── Uptime (process) ──
    try:
        import psutil  # noqa: E402 — lazy import, psutil only needed for system-info endpoint
        process = psutil.Process()
        uptime_seconds = int(time.time() - process.create_time())
        memory_mb = round(process.memory_info().rss / (1024 * 1024), 1)
        cpu_percent = process.cpu_percent(interval=0)
    except Exception:
        uptime_seconds = 0
        memory_mb = 0
        cpu_percent = 0

    uptime_hours = uptime_seconds // 3600
    uptime_mins = (uptime_seconds % 3600) // 60

    return {
        "overview": {
            "total_requests": total_requests,
            "total_errors": total_errors,
            "error_rate_pct": error_rate,
            "uptime": f"{uptime_hours}h {uptime_mins}m",
            "uptime_seconds": uptime_seconds,
            "memory_mb": memory_mb,
            "cpu_percent": cpu_percent,
        },
        "latency": latency_global,
        "status_codes": status_breakdown,
        "top_endpoints": top_endpoints,
    }


# ─────────────────────────────────────────────────────────────
# Audit Logging (Admin)
# ─────────────────────────────────────────────────────────────
@router.get("/api/admin/audit")
@limiter.limit("30/minute")
async def admin_audit_logs(
    request: Request,
    event_type: Optional[str] = None,
    user_id: Optional[str] = None,
    severity: Optional[str] = None,
    limit: int = Query(100, ge=1, le=1000),
    _admin=Depends(verify_admin_key),
):
    """
    Query audit logs with optional filters.
    
    Returns recent audit events for compliance and security monitoring.
    """
    return {
        "logs": get_audit_logs(
            event_type=event_type,
            user_id=user_id,
            severity=severity,
            limit=limit,
        )
    }


@router.get("/api/admin/audit/summary")
@limiter.limit("30/minute")
async def admin_audit_summary(request: Request, _admin=Depends(verify_admin_key)):
    """Get audit log summary statistics."""
    return get_audit_summary()


@router.delete("/api/admin/audit")
@limiter.limit("3/minute")
async def admin_clear_audit(request: Request, _admin=Depends(verify_admin_key)):
    """Clear all audit logs (destructive operation)."""
    cleared = clear_audit_logs()
    log_audit_event(
        AuditEventType.ADMIN_CONFIG_CHANGE,
        details={"action": "audit_logs_cleared", "count": cleared},
        severity=AuditSeverity.WARNING,
    )
    return {"cleared": cleared, "message": "Audit logs cleared"}


# ─────────────────────────────────────────────────────────────
# Observability & Metrics
# ─────────────────────────────────────────────────────────────
@router.get("/api/admin/observability")
@limiter.limit("30/minute")
async def admin_observability(request: Request, _admin=Depends(verify_admin_key)):
    """
    Get observability metrics.
    
    Returns counters, histograms, and gauges for system health monitoring.
    """
    return get_metrics()


@router.get("/api/admin/observability/spans")
@limiter.limit("30/minute")
async def admin_span_metrics(request: Request, _admin=Depends(verify_admin_key)):
    """Get span timing metrics for distributed tracing."""
    metrics = get_metrics()
    spans = {
        k: v for k, v in metrics.get("histograms", {}).items()
        if k.startswith("span.")
    }
    return {"spans": spans}


# ─────────────────────────────────────────────────────────────
# Feedback Summary (Admin)
# ─────────────────────────────────────────────────────────────
@router.get("/api/admin/feedback")
@limiter.limit("30/minute")
async def get_feedback_summary_endpoint(request: Request, _admin=Depends(verify_admin_key)):
    """Get feedback summary (admin only)."""
    summary = get_feedback_summary()
    summary["nps_trend"] = get_nps_trend(30)
    return summary


# ─────────────────────────────────────────────────────────────
# Leads Summary (Admin)
# ─────────────────────────────────────────────────────────────
@router.get("/api/admin/leads")
@limiter.limit("30/minute")
async def get_leads_endpoint(request: Request, _admin=Depends(verify_admin_key)):
    """Get captured leads summary (admin only)."""
    return get_leads_summary()


# ─────────────────────────────────────────────────────────────
# Application Analytics (v2.9.0)
# ─────────────────────────────────────────────────────────────
@router.get("/api/admin/analytics")
@limiter.limit("30/minute")
async def get_analytics_summary_endpoint(
    request: Request,
    hours: int = Query(24, ge=1, le=168),
    _admin=Depends(verify_admin_key),
):
    """Get comprehensive analytics summary (admin only)."""
    return get_analytics_summary(hours)


@router.get("/api/admin/analytics/performance")
@limiter.limit("30/minute")
async def get_performance_metrics_endpoint(request: Request, _admin=Depends(verify_admin_key)):
    """Get API performance metrics (admin only)."""
    return get_performance_metrics()


@router.get("/api/admin/analytics/features")
@limiter.limit("30/minute")
async def get_feature_metrics_endpoint(request: Request, _admin=Depends(verify_admin_key)):
    """Get feature usage metrics (admin only)."""
    return get_feature_metrics()


@router.get("/api/admin/analytics/funnel")
@limiter.limit("30/minute")
async def get_conversion_funnel_endpoint(request: Request, _admin=Depends(verify_admin_key)):
    """Get conversion funnel metrics (admin only)."""
    return get_conversion_funnel()
