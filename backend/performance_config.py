"""Performance optimization middleware and config (Issue #116).

Multi-worker configuration, response compression, parallel pricing,
connection pooling, and auto-scaling hints.
"""

import logging
import os
from typing import Dict, Any

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────
# Gunicorn / Uvicorn multi-worker config
# ─────────────────────────────────────────────────────────
WORKERS = int(os.getenv("WEB_CONCURRENCY", "4"))
WORKER_CLASS = os.getenv("WORKER_CLASS", "uvicorn.workers.UvicornWorker")
WORKER_TIMEOUT = int(os.getenv("WORKER_TIMEOUT", "120"))
KEEP_ALIVE = int(os.getenv("KEEP_ALIVE", "5"))
MAX_REQUESTS = int(os.getenv("MAX_REQUESTS", "1000"))
MAX_REQUESTS_JITTER = int(os.getenv("MAX_REQUESTS_JITTER", "100"))
BACKLOG = int(os.getenv("BACKLOG", "2048"))


def get_gunicorn_config() -> Dict[str, Any]:
    """Return gunicorn configuration dict for production."""
    return {
        "bind": f"0.0.0.0:{os.getenv('PORT', '8000')}",
        "workers": WORKERS,
        "worker_class": WORKER_CLASS,
        "timeout": WORKER_TIMEOUT,
        "keepalive": KEEP_ALIVE,
        "max_requests": MAX_REQUESTS,
        "max_requests_jitter": MAX_REQUESTS_JITTER,
        "backlog": BACKLOG,
        "accesslog": "-",
        "errorlog": "-",
        "loglevel": os.getenv("LOG_LEVEL", "info"),
        "preload_app": True,
        "graceful_timeout": 30,
    }


# ─────────────────────────────────────────────────────────
# Connection pool settings
# ─────────────────────────────────────────────────────────
DB_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "10"))
DB_MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "20"))
DB_POOL_RECYCLE = int(os.getenv("DB_POOL_RECYCLE", "3600"))
DB_POOL_PRE_PING = True

REDIS_MAX_CONNECTIONS = int(os.getenv("REDIS_MAX_CONNECTIONS", "50"))
REDIS_SOCKET_TIMEOUT = int(os.getenv("REDIS_SOCKET_TIMEOUT", "5"))
REDIS_RETRY_ON_TIMEOUT = True


# ─────────────────────────────────────────────────────────
# Response compression settings (already in main.py via GZip)
# ─────────────────────────────────────────────────────────
GZIP_MINIMUM_SIZE = int(os.getenv("GZIP_MINIMUM_SIZE", "1000"))  # bytes


# ─────────────────────────────────────────────────────────
# Caching strategies
# ─────────────────────────────────────────────────────────
CACHE_TTL_MAPPINGS = int(os.getenv("CACHE_TTL_MAPPINGS", "3600"))  # 1h
CACHE_TTL_PRICING = int(os.getenv("CACHE_TTL_PRICING", "1800"))  # 30min
CACHE_TTL_ANALYSIS = int(os.getenv("CACHE_TTL_ANALYSIS", "7200"))  # 2h
CACHE_MAX_SIZE = int(os.getenv("CACHE_MAX_SIZE", "512"))


# ─────────────────────────────────────────────────────────
# Rate limiting tiers
# ─────────────────────────────────────────────────────────
RATE_LIMITS: Dict[str, Dict[str, str]] = {
    "free": {
        "analyze": "5/minute",
        "generate_iac": "3/minute",
        "generate_hld": "2/minute",
        "suggest": "10/minute",
        "default": "30/minute",
    },
    "team": {
        "analyze": "20/minute",
        "generate_iac": "15/minute",
        "generate_hld": "10/minute",
        "suggest": "30/minute",
        "default": "100/minute",
    },
    "enterprise": {
        "analyze": "100/minute",
        "generate_iac": "50/minute",
        "generate_hld": "30/minute",
        "suggest": "100/minute",
        "default": "500/minute",
    },
}


# ─────────────────────────────────────────────────────────
# Auto-scaling hints for Container App
# ─────────────────────────────────────────────────────────
AUTOSCALE_CONFIG: Dict[str, Any] = {
    "min_replicas": int(os.getenv("MIN_REPLICAS", "1")),
    "max_replicas": int(os.getenv("MAX_REPLICAS", "10")),
    "cpu_threshold": int(os.getenv("CPU_THRESHOLD", "70")),  # percent
    "concurrent_requests": int(os.getenv("CONCURRENT_REQUESTS", "25")),
    "scale_up_cooldown": 60,  # seconds
    "scale_down_cooldown": 300,  # seconds
}


# ─────────────────────────────────────────────────────────
# SLA targets (used by load testing)
# ─────────────────────────────────────────────────────────
SLA_TARGETS: Dict[str, Any] = {
    "availability": 99.9,  # percent
    "p50_latency_ms": 200,
    "p95_latency_ms": 2000,
    "p99_latency_ms": 5000,
    "max_error_rate": 1.0,  # percent
    "rps_target": 100,  # requests per second
}


def get_performance_report() -> Dict[str, Any]:
    """Return current performance configuration summary."""
    return {
        "workers": WORKERS,
        "worker_class": WORKER_CLASS,
        "db_pool_size": DB_POOL_SIZE,
        "db_max_overflow": DB_MAX_OVERFLOW,
        "redis_max_connections": REDIS_MAX_CONNECTIONS,
        "cache_ttl_mappings": CACHE_TTL_MAPPINGS,
        "cache_ttl_pricing": CACHE_TTL_PRICING,
        "gzip_min_size": GZIP_MINIMUM_SIZE,
        "autoscale": AUTOSCALE_CONFIG,
        "sla_targets": SLA_TARGETS,
    }
