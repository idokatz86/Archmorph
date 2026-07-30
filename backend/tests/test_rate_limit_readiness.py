"""Fail-closed rate-limit readiness regressions for Redis/scale configuration."""

from __future__ import annotations

import pytest

from routers import shared


_SCALE_ENV_VARS = (
    "WEB_CONCURRENCY",
    "UVICORN_WORKERS",
    "CONTAINER_APP_REPLICA_COUNT",
    "CONTAINER_APP_MIN_REPLICAS",
    "CONTAINER_APP_MAX_REPLICAS",
    "MAX_REPLICAS",
)


@pytest.fixture(autouse=True)
def _isolated_rate_limit_environment(monkeypatch: pytest.MonkeyPatch):
    for name in (
        "ENV",
        "REDIS_HOST",
        "REDIS_URL",
        "RATE_LIMIT_STORAGE",
        *_SCALE_ENV_VARS,
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")


@pytest.mark.parametrize("environment", ["production", "prod", "staging"])
def test_redis_host_requires_shared_adapter_at_single_replica(
    monkeypatch: pytest.MonkeyPatch,
    environment: str,
):
    monkeypatch.setenv("ENVIRONMENT", environment)
    monkeypatch.setenv("REDIS_HOST", "managed-redis.example.invalid")
    monkeypatch.setenv("WEB_CONCURRENCY", "1")
    monkeypatch.setenv("CONTAINER_APP_MIN_REPLICAS", "1")

    readiness = shared.rate_limit_readiness()

    assert readiness["production_like"] is True
    assert readiness["declared_replica_count"] == 1
    assert readiness["multi_worker"] is False
    assert readiness["shared"] is False
    assert readiness["shared_required"] is True
    assert readiness["entra_host_requires_adapter"] is True
    assert readiness["ready"] is False


@pytest.mark.parametrize(
    ("indicator", "value"),
    [
        ("CONTAINER_APP_REPLICA_COUNT", "2"),
        ("CONTAINER_APP_MIN_REPLICAS", "2"),
        ("WEB_CONCURRENCY", "2"),
        ("UVICORN_WORKERS", "2"),
        ("CONTAINER_APP_MAX_REPLICAS", "3"),
        ("MAX_REPLICAS", "4"),
    ],
)
def test_horizontal_or_autoscale_indicators_fail_closed_without_shared_storage(
    monkeypatch: pytest.MonkeyPatch,
    indicator: str,
    value: str,
):
    monkeypatch.setenv(indicator, value)

    readiness = shared.rate_limit_readiness()

    assert readiness["shared"] is False
    assert readiness["shared_required"] is True
    assert readiness["ready"] is False
    if indicator in {"CONTAINER_APP_MAX_REPLICAS", "MAX_REPLICAS"}:
        assert readiness["autoscale_possible"] is True
        assert readiness["declared_max_replica_count"] == int(value)


@pytest.mark.parametrize(
    "storage_uri",
    [
        "redis://rate-limit.example.invalid:6379/1",
        "rediss://rate-limit.example.invalid:6380/1",
    ],
)
def test_valid_explicit_shared_storage_passes_with_redis_host(
    monkeypatch: pytest.MonkeyPatch,
    storage_uri: str,
):
    monkeypatch.setenv("REDIS_HOST", "managed-redis.example.invalid")
    monkeypatch.setenv("RATE_LIMIT_STORAGE", storage_uri)
    monkeypatch.setenv("CONTAINER_APP_MAX_REPLICAS", "5")

    readiness = shared.rate_limit_readiness()

    assert readiness["storage"] == "shared"
    assert readiness["shared"] is True
    assert readiness["shared_required"] is True
    assert readiness["entra_host_requires_adapter"] is False
    assert readiness["ready"] is True


def test_supported_redis_url_is_a_real_shared_adapter(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("REDIS_HOST", "managed-redis.example.invalid")
    monkeypatch.setenv("REDIS_URL", "rediss://rate-limit.example.invalid:6380/2")

    readiness = shared.rate_limit_readiness()

    assert readiness["shared"] is True
    assert readiness["entra_host_requires_adapter"] is False
    assert readiness["ready"] is True


@pytest.mark.parametrize(
    "unsupported_uri",
    [
        "memory://",
        "redis://",
        "azure-redis://managed-redis.example.invalid:6380",
    ],
)
def test_unsupported_storage_never_claims_a_shared_adapter(
    monkeypatch: pytest.MonkeyPatch,
    unsupported_uri: str,
):
    monkeypatch.setenv("REDIS_HOST", "managed-redis.example.invalid")
    monkeypatch.setenv("RATE_LIMIT_STORAGE", unsupported_uri)

    readiness = shared.rate_limit_readiness()

    assert readiness["shared"] is False
    assert readiness["entra_host_requires_adapter"] is True
    assert readiness["ready"] is False


def test_disabled_rate_limiting_does_not_require_shared_storage(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("REDIS_HOST", "managed-redis.example.invalid")
    monkeypatch.setenv("CONTAINER_APP_MAX_REPLICAS", "5")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")

    readiness = shared.rate_limit_readiness()

    assert readiness["enabled"] is False
    assert readiness["shared_required"] is False
    assert readiness["entra_host_requires_adapter"] is False
    assert readiness["ready"] is True


def test_development_single_replica_allows_redis_host_without_rate_adapter(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("REDIS_HOST", "developer-redis.example.invalid")

    readiness = shared.rate_limit_readiness()

    assert readiness["production_like"] is False
    assert readiness["shared"] is False
    assert readiness["shared_required"] is False
    assert readiness["ready"] is True


def test_production_single_replica_without_redis_host_is_rate_limit_ready():
    readiness = shared.rate_limit_readiness()

    assert readiness["production_like"] is True
    assert readiness["shared"] is False
    assert readiness["shared_required"] is False
    assert readiness["entra_host_requires_adapter"] is False
    assert readiness["ready"] is True
