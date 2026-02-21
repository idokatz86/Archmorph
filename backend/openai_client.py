"""
Archmorph OpenAI Client — shared Azure OpenAI client factory.

Centralizes OpenAI configuration and client creation to avoid duplication
across vision_analyzer, image_classifier, hld_generator, and iac_chat.
"""

import logging
import os
from typing import Optional

from openai import AzureOpenAI, RateLimitError, APITimeoutError, APIConnectionError, BadRequestError, AuthenticationError
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
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
