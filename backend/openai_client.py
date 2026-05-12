"""
Archmorph OpenAI Client — shared Azure OpenAI client factory.

Centralizes OpenAI configuration and client creation to avoid duplication
across vision_analyzer, image_classifier, hld_generator, and iac_chat.

Includes content-hash caching to reduce redundant GPT-4o API calls
(Issue #77).
"""

import hashlib
import json
import logging
import math
import os
import random
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Optional

from openai import AzureOpenAI, RateLimitError, APITimeoutError, APIConnectionError, BadRequestError, AuthenticationError, APIStatusError, Timeout as OpenAITimeout
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from cachetools import TTLCache
from tenacity import (
    retry,
    stop_after_attempt,
    retry_if_exception,
    before_sleep_log,
)

logger = logging.getLogger(__name__)


class OpenAIServiceError(Exception):
    """Unified error for all OpenAI service failures."""

    def __init__(self, message: str, *, retryable: bool = False, status_code: int = 502):
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code


def handle_openai_error(exc: Exception, context: str = "OpenAI call") -> OpenAIServiceError:
    """Map raw OpenAI exceptions to a unified OpenAIServiceError.

    Parameters
    ----------
    exc : Exception
        The original exception from the OpenAI SDK.
    context : str
        Human-readable description of what was being attempted.

    Returns
    -------
    OpenAIServiceError
        A normalized error with ``retryable`` and ``status_code`` attributes.
    """
    if isinstance(exc, RateLimitError):
        logger.warning("%s rate-limited: %s", context, exc)
        return OpenAIServiceError(
            f"{context} is temporarily rate-limited. Please retry shortly.",
            retryable=True, status_code=429,
        )
    if isinstance(exc, (APITimeoutError, APIConnectionError, TimeoutError)):
        logger.error("%s connection failure: %s", context, exc)
        return OpenAIServiceError(
            f"{context} timed out or lost connectivity. Please retry.",
            retryable=True, status_code=504,
        )
    if isinstance(exc, AuthenticationError):
        logger.error("%s authentication failed: %s", context, exc)
        return OpenAIServiceError(
            f"{context} authentication error. Contact support.",
            retryable=False, status_code=502,
        )
    if isinstance(exc, BadRequestError):
        logger.warning("%s bad request: %s", context, exc)
        return OpenAIServiceError(
            f"{context} received an invalid request. Check your input.",
            retryable=False, status_code=400,
        )
    # Fallback for unexpected errors
    logger.error("%s unexpected error: %s", context, exc, exc_info=True)
    return OpenAIServiceError(
        f"{context} failed unexpectedly. Please try again.",
        retryable=True, status_code=502,
    )

# ─────────────────────────────────────────────────────────────
# Azure OpenAI Configuration (single source of truth)
# ─────────────────────────────────────────────────────────────
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "")
if not AZURE_OPENAI_ENDPOINT:
    logger.warning("AZURE_OPENAI_ENDPOINT not set — OpenAI features will be unavailable")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4.1")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2025-04-01-preview")
AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_API_KEY", "") or os.getenv("AZURE_OPENAI_KEY", "")

# Fallback model deployment — used when the primary model fails (Issue #285).
# Set to gpt-4o as a proven fallback for resilience.
AZURE_OPENAI_FALLBACK_DEPLOYMENT = os.getenv("AZURE_OPENAI_FALLBACK_DEPLOYMENT", "gpt-4o")

# Singleton client (reused across requests for connection pooling)
_client: Optional[AzureOpenAI] = None
_client_lock = threading.Lock()

# Default timeout for all OpenAI API calls — configurable to prevent
# thread pool starvation (Issue #298).  Reduced from 120s to 60s.
_OPENAI_TIMEOUT_SECONDS = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "120"))
_OPENAI_CONNECT_TIMEOUT = float(os.getenv("OPENAI_CONNECT_TIMEOUT", "30"))
_OPENAI_TIMEOUT = OpenAITimeout(timeout=_OPENAI_TIMEOUT_SECONDS, connect=_OPENAI_CONNECT_TIMEOUT)

# ─────────────────────────────────────────────────────────────
# Retry decorator — shared across all OpenAI callers
# ─────────────────────────────────────────────────────────────
def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _worker_count() -> int:
    return max(
        1,
        _env_int("WEB_CONCURRENCY", _env_int("GUNICORN_WORKERS", _env_int("UVICORN_WORKERS", 1))),
    )


def _openai_per_worker_limit() -> int:
    explicit = os.getenv("OPENAI_MAX_INFLIGHT_PER_WORKER")
    if explicit:
        return max(1, _env_int("OPENAI_MAX_INFLIGHT_PER_WORKER", 4))
    deployment_total = max(1, _env_int("OPENAI_MAX_INFLIGHT_DEPLOYMENT", 16))
    return max(1, math.ceil(deployment_total / _worker_count()))


OPENAI_MAX_INFLIGHT_PER_WORKER = _openai_per_worker_limit()
OPENAI_ADMISSION_TIMEOUT_SECONDS = max(0.1, float(os.getenv("OPENAI_ADMISSION_TIMEOUT_SECONDS", "2")))
_openai_inflight = threading.BoundedSemaphore(OPENAI_MAX_INFLIGHT_PER_WORKER)


RETRYABLE_EXCEPTIONS = (RateLimitError, APITimeoutError, APIConnectionError, TimeoutError, APIStatusError)


def _retryable_status(exc: Exception) -> bool:
    if isinstance(exc, RateLimitError):
        return True
    status_code = getattr(exc, "status_code", None)
    return status_code in {429, 500, 502, 503, 504}


def _is_retryable_exception(exc: Exception) -> bool:
    if isinstance(exc, (APITimeoutError, APIConnectionError, TimeoutError)):
        return True
    if isinstance(exc, APIStatusError):
        return _retryable_status(exc)
    return isinstance(exc, RateLimitError)


def _parse_retry_after_seconds(exc: Exception) -> Optional[float]:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None) or {}
    raw = headers.get("Retry-After") or headers.get("retry-after")
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        pass
    try:
        retry_at = parsedate_to_datetime(str(raw))
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=timezone.utc)
        return max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())
    except Exception:
        return None


def _retry_wait_seconds(retry_state) -> float:
    # Exponential backoff (2, 4, 8...) with jitter, capped at 30s.
    attempt = max(1, retry_state.attempt_number)
    base = min(30.0, float(2 ** attempt))
    delay = base + random.uniform(0, 0.5)
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if exc is not None and _retryable_status(exc):
        provider_delay = _parse_retry_after_seconds(exc)
        if provider_delay is not None:
            delay = max(delay, provider_delay)
    return min(120.0, delay)


@contextmanager
def openai_admission_slot():
    acquired = _openai_inflight.acquire(timeout=OPENAI_ADMISSION_TIMEOUT_SECONDS)
    if not acquired:
        raise TimeoutError("OpenAI admission queue timed out")
    try:
        yield
    finally:
        _openai_inflight.release()


_retry_impl = retry(
    retry=retry_if_exception(_is_retryable_exception),
    stop=stop_after_attempt(3),
    wait=_retry_wait_seconds,
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)


def openai_retry(fn):
    """Retry wrapper with deployment-aware admission control."""
    wrapped = _retry_impl(fn)

    def guarded(*args, **kwargs):
        with openai_admission_slot():
            return wrapped(*args, **kwargs)

    return guarded



def get_openai_client() -> AzureOpenAI:
    """
    Return a shared Azure OpenAI client instance.

    Uses API key auth if AZURE_OPENAI_KEY is set, otherwise falls back
    to DefaultAzureCredential (Managed Identity / az login).

    The client is created once and reused for connection pooling.
    """
    global _client
    if _client is not None:
        return _client

    with _client_lock:
        if _client is not None:
            return _client

        if AZURE_OPENAI_KEY:
            logger.info("Creating Azure OpenAI client with API key auth")
            _client = AzureOpenAI(
                azure_endpoint=AZURE_OPENAI_ENDPOINT,
                api_key=AZURE_OPENAI_KEY,
                api_version=AZURE_OPENAI_API_VERSION,
                timeout=_OPENAI_TIMEOUT,
            )
        else:
            logger.info("Creating Azure OpenAI client with DefaultAzureCredential")
            credential = DefaultAzureCredential()
            token_provider = get_bearer_token_provider(
                credential, "https://cognitiveservices.azure.com/.default"
            )
            _client = AzureOpenAI(
                azure_endpoint=AZURE_OPENAI_ENDPOINT,
                azure_ad_token_provider=token_provider,
                api_version=AZURE_OPENAI_API_VERSION,
                timeout=_OPENAI_TIMEOUT,
            )

    return _client


def reset_client():
    """Reset the singleton client (useful for testing)."""
    global _client
    _client = None


# ─────────────────────────────────────────────────────────────
# GPT Response Cache (Issue #77)
# ─────────────────────────────────────────────────────────────
GPT_CACHE_TTL_SECONDS = int(os.getenv("GPT_CACHE_TTL_SECONDS", "3600"))
GPT_CACHE_MAX_SIZE = int(os.getenv("GPT_CACHE_MAX_SIZE", "256"))

_response_cache: TTLCache = TTLCache(maxsize=GPT_CACHE_MAX_SIZE, ttl=GPT_CACHE_TTL_SECONDS)
_cache_lock = threading.Lock()   # guards _cache_hits, _cache_misses, and cache reads/writes
_cache_hits = 0
_cache_misses = 0
# Per-key locks prevent thundering-herd for the SAME cache key
# without blocking requests for DIFFERENT keys (Issue #293)
# Bounded to prevent unbounded growth — evicts oldest entries.
_MAX_KEY_LOCKS = 512
_key_locks: dict[str, threading.Lock] = {}
_key_locks_lock = threading.Lock()


def _compute_cache_key(**kwargs) -> str:
    """Compute a deterministic hash key from chat completion kwargs."""
    # Normalize the input for consistent hashing
    key_data = {
        "messages": kwargs.get("messages", []),
        "model": kwargs.get("model", AZURE_OPENAI_DEPLOYMENT),
        "temperature": kwargs.get("temperature"),
        "max_tokens": kwargs.get("max_tokens"),
        "response_format": str(kwargs.get("response_format", "")),
    }
    raw = json.dumps(key_data, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def get_cache_stats() -> Dict[str, Any]:
    """Return cache hit/miss statistics for observability."""
    with _cache_lock:
        total = _cache_hits + _cache_misses
        return {
            "hits": _cache_hits,
            "misses": _cache_misses,
            "total": total,
            "hit_rate": round(_cache_hits / total, 4) if total > 0 else 0.0,
            "size": len(_response_cache),
            "max_size": GPT_CACHE_MAX_SIZE,
            "ttl_seconds": GPT_CACHE_TTL_SECONDS,
        }


def reset_cache():
    """Clear the response cache and reset stats (useful for testing)."""
    global _cache_hits, _cache_misses
    with _cache_lock:
        _response_cache.clear()
        _cache_hits = 0
        _cache_misses = 0
    with _key_locks_lock:
        _key_locks.clear()


def cached_chat_completion(
    messages: List[Dict[str, Any]],
    *,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    response_format: Any = None,
    bypass_cache: bool = False,
    **extra_kwargs,
) -> Any:
    """
    Cached wrapper around Azure OpenAI chat completions.

    Hashes the input (messages + params) and returns a cached response
    if available.  Otherwise makes the API call, caches, and returns.

    Args:
        messages: Chat messages list
        model: Deployment name (defaults to AZURE_OPENAI_DEPLOYMENT)
        temperature: Sampling temperature
        max_tokens: Max tokens in response
        response_format: Response format hint
        bypass_cache: If True, skip cache lookup (but still store result)
        **extra_kwargs: Additional kwargs passed to the API

    Returns:
        The chat completion response object.
    """
    global _cache_hits, _cache_misses

    deployment = model or AZURE_OPENAI_DEPLOYMENT

    # Build kwargs for the API call
    api_kwargs: Dict[str, Any] = {"model": deployment, "messages": messages}
    if temperature is not None:
        api_kwargs["temperature"] = temperature
    if max_tokens is not None:
        api_kwargs["max_tokens"] = max_tokens
    if response_format is not None:
        api_kwargs["response_format"] = response_format
    api_kwargs.update(extra_kwargs)

    # Compute cache key
    cache_key = _compute_cache_key(**api_kwargs)

    # Fast-path: check cache under a brief lock (Issue #293 — no contention
    # between different keys).
    if not bypass_cache:
        with _cache_lock:
            if cache_key in _response_cache:
                _cache_hits += 1
                logger.debug("GPT cache HIT (key=%s…)", cache_key[:12])
                _emit_cache_metric("hit")
                return _response_cache[cache_key]

    # Acquire per-key lock to prevent thundering-herd for the SAME prompt
    # while allowing different prompts to proceed concurrently (#293).
    with _key_locks_lock:
        key_lock = _key_locks.setdefault(cache_key, threading.Lock())
        # Evict oldest entries when the lock dict grows too large
        if len(_key_locks) > _MAX_KEY_LOCKS:
            excess = len(_key_locks) - _MAX_KEY_LOCKS
            for old_key in list(_key_locks)[:excess]:
                _key_locks.pop(old_key, None)

    with key_lock:
        # Double-check cache after acquiring per-key lock (another thread
        # may have populated it while we waited).
        if not bypass_cache:
            with _cache_lock:
                if cache_key in _response_cache:
                    _cache_hits += 1
                    logger.debug("GPT cache HIT (key=%s…, after lock)", cache_key[:12])
                    _emit_cache_metric("hit")
                    return _response_cache[cache_key]

        with _cache_lock:
            _cache_misses += 1
        logger.debug("GPT cache MISS (key=%s…)", cache_key[:12])
        _emit_cache_metric("miss")

        # Make the actual API call (outside cache lock — different keys
        # are fully concurrent now).
        client = get_openai_client()

        # ── OpenTelemetry LLM span (#502) ────────────────────
        from observability import trace_span
        with trace_span("llm.chat_completion", attributes={
            "llm.model": deployment,
            "llm.temperature": temperature or 0,
            "llm.max_tokens": max_tokens or 0,
            "llm.message_count": len(messages),
        }) as span:
            try:
                response = openai_retry(client.chat.completions.create)(**api_kwargs)
            except RETRYABLE_EXCEPTIONS as primary_exc:
                # If a fallback model is configured, try it before giving up (#285)
                if AZURE_OPENAI_FALLBACK_DEPLOYMENT and AZURE_OPENAI_FALLBACK_DEPLOYMENT != deployment:
                    logger.warning(
                        "Primary model %s failed (%s), falling back to %s",
                        deployment, primary_exc, AZURE_OPENAI_FALLBACK_DEPLOYMENT,
                    )
                    fallback_kwargs = {**api_kwargs, "model": AZURE_OPENAI_FALLBACK_DEPLOYMENT}
                    response = openai_retry(client.chat.completions.create)(**fallback_kwargs)
                    if span:
                        span.set_attribute("llm.fallback", True)
                        span.set_attribute("llm.fallback_model", AZURE_OPENAI_FALLBACK_DEPLOYMENT)
                else:
                    raise

            # Record token usage on the span
            usage = getattr(response, "usage", None)
            if usage and span:
                span.set_attribute("llm.prompt_tokens", usage.prompt_tokens or 0)
                span.set_attribute("llm.completion_tokens", usage.completion_tokens or 0)
                span.set_attribute("llm.total_tokens", (usage.prompt_tokens or 0) + (usage.completion_tokens or 0))

        # Detect GPT output truncation — finish_reason "length" means the
        # response was cut off at max_tokens (Issue #278).
        if response.choices and response.choices[0].finish_reason == "length":
            logger.warning(  # nosemgrep: python-logger-credential-disclosure — no secrets in this message
                "GPT output TRUNCATED (finish_reason=length, model=%s, max_tokens=%s). "
                "Response may be incomplete — consider increasing max_tokens.",
                deployment,
                api_kwargs.get("max_tokens", "default"),
            )
            # Attach truncation flag so callers can detect & handle it
            response._truncated = True
        else:
            response._truncated = False

        # Store result
        with _cache_lock:
            _response_cache[cache_key] = response

        # ── Cost metering (Issue #392) — transparent, best-effort ──
        _meter_response(response, deployment)

    return response


def _emit_cache_metric(event_type: str):
    """Record cache hit/miss in the observability system (best-effort)."""
    try:
        from observability import increment_counter
        increment_counter(f"gpt_cache.{event_type}", tags={"component": "openai_client"})
    except Exception:
        pass  # nosec B110 — Observability is optional


def _meter_response(response: Any, model: str, caller: str = "cached_chat_completion") -> None:
    """Record token usage from an OpenAI response in the cost meter (best-effort)."""
    try:
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        from cost_metering import CostMeter
        CostMeter.instance().record(
            model=model,
            prompt_tokens=usage.prompt_tokens or 0,
            completion_tokens=usage.completion_tokens or 0,
            caller=caller,
        )
    except Exception:
        pass  # nosec B110 — Cost metering must never break request handling


def meter_openai_response(response: Any, model: str, caller: str) -> None:
    """Public metering hook for direct OpenAI call-sites."""
    _meter_response(response, model, caller)
