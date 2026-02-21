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
from typing import Any, Dict, List, Optional

from openai import AzureOpenAI, RateLimitError, APITimeoutError, APIConnectionError, BadRequestError, AuthenticationError
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
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")
AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_API_KEY", "") or os.getenv("AZURE_OPENAI_KEY", "")

# Singleton client (reused across requests for connection pooling)
_client: Optional[AzureOpenAI] = None

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

    if AZURE_OPENAI_KEY:
        logger.info("Creating Azure OpenAI client with API key auth")
        _client = AzureOpenAI(
            azure_endpoint=AZURE_OPENAI_ENDPOINT,
            api_key=AZURE_OPENAI_KEY,
            api_version=AZURE_OPENAI_API_VERSION,
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
_cache_hits = 0
_cache_misses = 0


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
    _response_cache.clear()
    _cache_hits = 0
    _cache_misses = 0


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

    # Check cache (unless bypassed)
    if not bypass_cache and cache_key in _response_cache:
        _cache_hits += 1
        logger.debug("GPT cache HIT (key=%s…)", cache_key[:12])
        _emit_cache_metric("hit")
        return _response_cache[cache_key]

    _cache_misses += 1
    logger.debug("GPT cache MISS (key=%s…)", cache_key[:12])
    _emit_cache_metric("miss")

    # Make the actual API call
    client = get_openai_client()
    response = client.chat.completions.create(**api_kwargs)

    # Cache the result
    _response_cache[cache_key] = response

    return response


def _emit_cache_metric(event_type: str):
    """Record cache hit/miss in the observability system (best-effort)."""
    try:
        from observability import increment_counter
        increment_counter(f"gpt_cache.{event_type}", tags={"component": "openai_client"})
    except Exception:
        pass  # Observability is optional

