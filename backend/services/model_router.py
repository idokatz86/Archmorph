from typing import Protocol, List, Dict, Any, AsyncIterator
import os

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
        # pseudo anthropic
    async def chat(self, messages, tools=None, **kwargs):
        raise NotImplementedError("Anthropic native client not installed yet.")

    async def chat_stream(self, messages, tools=None, **kwargs):
        raise NotImplementedError("Anthropic native client not installed yet.")

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
    Given constraints and strategy, routes the request to the correct ModelClient.
    """
    def __init__(self, db_session, org_id: str):
        self.db = db_session
        self.org_id = org_id

    def route(self, strategy: str, constraints: Dict[str, Any] = None) -> ModelClient:
        from models.model_registry import ModelEndpoint
        
        # simplified priority router
        endpoints = self.db.query(ModelEndpoint).filter(
            ModelEndpoint.organization_id == self.org_id,
            ModelEndpoint.is_active == True
        ).all()
        
        if not endpoints:
            # Fallback to dev local env
            return get_model_client("azure-openai", {})

        # pick first available
        best_endpoint = endpoints[0]
        return get_model_client(best_endpoint.provider, best_endpoint.connection_config)
