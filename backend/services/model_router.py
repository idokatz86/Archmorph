from typing import Protocol, List, Dict, Any, AsyncIterator, Optional
import logging
import os

logger = logging.getLogger(__name__)

class ModelClient(Protocol):
    """
    Unified Interface for calling different model providers.
    """
    async def chat(self, messages: List[Dict[str, str]], tools: List[Dict] = None, **kwargs) -> Any:
        pass
        
    async def chat_stream(self, messages: List[Dict[str, str]], tools: List[Dict] = None, **kwargs) -> AsyncIterator[Any]:
        pass
        
    def supports_tools(self) -> bool:
        pass
        
    def supports_vision(self) -> bool:
        pass
        
    def get_context_window(self) -> int:
        pass

# Fake implementations for startup mode

class AzureOpenAIClientImpl:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        from openai import AsyncAzureOpenAI
        self.client = AsyncAzureOpenAI(
            api_key=config.get("api_key", os.getenv("AZURE_OPENAI_API_KEY")),
            api_version=config.get("api_version", "2024-02-15-preview"),
            azure_endpoint=config.get("endpoint", os.getenv("AZURE_OPENAI_ENDPOINT"))
        )
        self.model = config.get("model", "gpt-4o")

    async def chat(self, messages: List[Dict[str, str]], tools: List[Dict] = None, **kwargs) -> Any:
        # Pass through to native Azure wrapper
        return await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools if tools else None,
            **kwargs
        )

    async def chat_stream(self, messages: List[Dict[str, str]], tools: List[Dict] = None, **kwargs) -> AsyncIterator[Any]:
        stream = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools if tools else None,
            stream=True,
            **kwargs
        )
        async for chunk in stream:
            yield chunk

    def supports_tools(self) -> bool: return True
    def supports_vision(self) -> bool: return True
    def get_context_window(self) -> int: return 128000


class AnthropicClientImpl:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        from anthropic import AsyncAnthropic
        self.client = AsyncAnthropic(
            api_key=config.get("api_key", os.getenv("ANTHROPIC_API_KEY")),
        )
        self.model = config.get("model", "claude-3-5-sonnet-latest")

    async def chat(self, messages: List[Dict[str, str]], tools: List[Dict] = None, **kwargs) -> Any:
        # Convert standard OpenAI-ish format to Anthropic format if needed, but assuming calling code adjusts
        # Here we just pass through
        response = await self.client.messages.create(
            model=self.model,
            max_tokens=kwargs.pop("max_tokens", 4096),
            messages=messages,
            tools=tools if tools else None,
            **kwargs
        )
        return response

    async def chat_stream(self, messages: List[Dict[str, str]], tools: List[Dict] = None, **kwargs) -> AsyncIterator[Any]:
        stream = await self.client.messages.create(
            model=self.model,
            max_tokens=kwargs.pop("max_tokens", 4096),
            messages=messages,
            tools=tools if tools else None,
            stream=True,
            **kwargs
        )
        async for chunk in stream:
            yield chunk

    def supports_tools(self) -> bool: return True
    def supports_vision(self) -> bool: return True
    def get_context_window(self) -> int: return 200000


def get_model_client(provider: str, config: Dict[str, Any]) -> ModelClient:
    if provider == "azure-openai" or provider == "openai":
        return AzureOpenAIClientImpl(config)
    elif provider == "anthropic":
        return AnthropicClientImpl(config)
    raise ValueError(f"Unknown provider {provider}")

class ModelRouter:
    """
    Routes model requests to the optimal ModelClient based on strategy.

    Strategies:
      - default / fixed:       First active endpoint (original behavior)
      - fallback_chain:        Try endpoints in priority order, fallback on error
      - cost_optimized:        Select cheapest endpoint by input token cost
      - latency_optimized:     Select endpoint with lowest reported latency
      - round_robin:           Distribute requests evenly across active endpoints
    """

    _rr_counter: int = 0  # class-level round-robin counter

    def __init__(self, db_session, org_id: str):
        self.db = db_session
        self.org_id = org_id

    def _get_active_endpoints(self):
        from models.model_registry import ModelEndpoint

        return self.db.query(ModelEndpoint).filter(
            ModelEndpoint.organization_id == self.org_id,
            ModelEndpoint.is_active.is_(True)
        ).all()

    def route(self, strategy: str = "default", constraints: Dict[str, Any] = None) -> ModelClient:
        constraints = constraints or {}
        endpoints = self._get_active_endpoints()

        if not endpoints:
            logger.info("No active endpoints for org %s, using env fallback", self.org_id)
            return get_model_client("azure-openai", {})

        if strategy in ("default", "fixed"):
            return self._route_fixed(endpoints)
        elif strategy == "fallback_chain":
            return self._route_fallback_chain(endpoints)
        elif strategy == "cost_optimized":
            return self._route_cost_optimized(endpoints, constraints)
        elif strategy == "latency_optimized":
            return self._route_latency_optimized(endpoints)
        elif strategy == "round_robin":
            return self._route_round_robin(endpoints)
        else:
            logger.warning("Unknown routing strategy '%s', using fixed", strategy)
            return self._route_fixed(endpoints)

    def _route_fixed(self, endpoints) -> ModelClient:
        """Pick the first active endpoint."""
        ep = endpoints[0]
        return get_model_client(ep.provider, ep.connection_config)

    def _route_fallback_chain(self, endpoints) -> ModelClient:
        """Return a FallbackClient that tries endpoints in order."""
        clients = [get_model_client(ep.provider, ep.connection_config) for ep in endpoints]
        return FallbackModelClient(clients)

    def _route_cost_optimized(self, endpoints, constraints: Dict[str, Any]) -> ModelClient:
        """Select the cheapest endpoint based on pricing metadata."""
        def _cost_key(ep):
            pricing = ep.pricing or {}
            return pricing.get("input_cost_per_1k", 999.0)

        # Filter by required capabilities if specified
        required_caps = constraints.get("requires", [])
        candidates = endpoints
        if required_caps:
            candidates = [
                ep for ep in endpoints
                if all(ep.capabilities.get(cap) for cap in required_caps)
            ]
            if not candidates:
                candidates = endpoints  # fallback: ignore filter

        cheapest = min(candidates, key=_cost_key)
        logger.debug(
            "Cost-optimized routing selected %s (%s) at $%.4f/1k input",
            cheapest.name, cheapest.provider,
            (cheapest.pricing or {}).get("input_cost_per_1k", 0),
        )
        return get_model_client(cheapest.provider, cheapest.connection_config)

    def _route_latency_optimized(self, endpoints) -> ModelClient:
        """Select the endpoint with lowest reported latency."""
        def _latency_key(ep):
            caps = ep.capabilities or {}
            return caps.get("avg_latency_ms", 9999)

        fastest = min(endpoints, key=_latency_key)
        logger.debug(
            "Latency-optimized routing selected %s (%s) at ~%dms",
            fastest.name, fastest.provider,
            (fastest.capabilities or {}).get("avg_latency_ms", 0),
        )
        return get_model_client(fastest.provider, fastest.connection_config)

    def _route_round_robin(self, endpoints) -> ModelClient:
        """Distribute requests evenly across endpoints."""
        idx = ModelRouter._rr_counter % len(endpoints)
        ModelRouter._rr_counter += 1
        ep = endpoints[idx]
        logger.debug("Round-robin routing selected %s (index %d)", ep.name, idx)
        return get_model_client(ep.provider, ep.connection_config)


class FallbackModelClient:
    """Wraps multiple ModelClients and tries them in order."""

    def __init__(self, clients: List[ModelClient]):
        self._clients = clients

    async def chat(self, messages, tools=None, **kwargs):
        last_error = None
        for i, client in enumerate(self._clients):
            try:
                return await client.chat(messages, tools=tools, **kwargs)
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Fallback client %d/%d failed: %s — trying next",
                    i + 1, len(self._clients), exc,
                )
        raise last_error  # All clients exhausted

    async def chat_stream(self, messages, tools=None, **kwargs):
        last_error = None
        for i, client in enumerate(self._clients):
            try:
                async for chunk in client.chat_stream(messages, tools=tools, **kwargs):
                    yield chunk
                return
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Fallback stream client %d/%d failed: %s — trying next",
                    i + 1, len(self._clients), exc,
                )
        raise last_error

    def supports_tools(self) -> bool:
        return self._clients[0].supports_tools() if self._clients else False

    def supports_vision(self) -> bool:
        return self._clients[0].supports_vision() if self._clients else False

    def get_context_window(self) -> int:
        return self._clients[0].get_context_window() if self._clients else 128000
