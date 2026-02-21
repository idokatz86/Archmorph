"""
Archmorph OpenAI Client — shared Azure OpenAI client factory.

Centralizes OpenAI configuration and client creation to avoid duplication
across vision_analyzer, image_classifier, hld_generator, and iac_chat.
"""

import logging
import os
from typing import Optional

from openai import AzureOpenAI, RateLimitError, APITimeoutError, APIConnectionError
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

logger = logging.getLogger(__name__)

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
