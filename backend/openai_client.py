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
import os
import threading
from typing import Any, Dict, List, Optional

from openai import AzureOpenAI, RateLimitError, APITimeoutError, APIConnectionError, BadRequestError, AuthenticationError, Timeout as OpenAITimeout
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from cachetools import TTLCache
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
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
RETRYABLE_EXCEPTIONS = (RateLimitError, APITimeoutError, APIConnectionError, TimeoutError)

openai_retry = retry(
    retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)


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
            else:
                raise

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

    return response


def _emit_cache_metric(event_type: str):
    """Record cache hit/miss in the observability system (best-effort)."""
    try:
        from observability import increment_counter
        increment_counter(f"gpt_cache.{event_type}", tags={"component": "openai_client"})
    except Exception:
        pass  # nosec B110 — Observability is optional

