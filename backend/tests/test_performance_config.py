"""
Archmorph — Performance Config Unit Tests
Tests for performance_config.py (Issue #116)
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from performance_config import (
    WORKERS,
    WORKER_CLASS,
    DB_POOL_SIZE,
    DB_MAX_OVERFLOW,
    DB_POOL_RECYCLE,
    REDIS_MAX_CONNECTIONS,
    RATE_LIMITS,
    AUTOSCALE_CONFIG,
    SLA_TARGETS,
)


# ====================================================================
# Gunicorn config
# ====================================================================

class TestGunicornConfig:
    def test_workers_positive(self):
        assert WORKERS >= 1

    def test_worker_class_valid(self):
        assert WORKER_CLASS in ("uvicorn.workers.UvicornWorker", "gthread", "sync", "gevent")


# ====================================================================
# Database pool
# ====================================================================

class TestDatabasePool:
    def test_pool_size(self):
        assert DB_POOL_SIZE >= 1

    def test_max_overflow(self):
        assert DB_MAX_OVERFLOW >= 0

    def test_pool_recycle(self):
        assert DB_POOL_RECYCLE >= 60  # At least 60 seconds


# ====================================================================
# Redis
# ====================================================================

class TestRedisConfig:
    def test_redis_connections(self):
        assert REDIS_MAX_CONNECTIONS >= 10


# ====================================================================
# Rate limits
# ====================================================================

class TestRateLimits:
    def test_tiers_defined(self):
        assert "free" in RATE_LIMITS
        assert "pro" in RATE_LIMITS
        assert "enterprise" in RATE_LIMITS

    def test_enterprise_has_more_keys(self):
        # Enterprise tier should have at least as many config keys as free
        assert len(RATE_LIMITS["enterprise"]) >= len(RATE_LIMITS["free"])


# ====================================================================
# Autoscale config
# ====================================================================

class TestAutoscaleConfig:
    def test_min_replicas(self):
        assert AUTOSCALE_CONFIG.get("min_replicas", 1) >= 1

    def test_max_replicas(self):
        assert AUTOSCALE_CONFIG.get("max_replicas", 1) >= AUTOSCALE_CONFIG.get("min_replicas", 1)


# ====================================================================
# SLA targets
# ====================================================================

class TestSLATargets:
    def test_availability(self):
        assert SLA_TARGETS.get("availability", 0) >= 99.0

    def test_p95_latency(self):
        assert SLA_TARGETS.get("p95_latency_ms", 0) > 0

    def test_error_rate(self):
        assert SLA_TARGETS.get("max_error_rate", 100) < 5
