from app.providers.anthropic_provider import AnthropicProvider
from app.providers.base import LLMProvider
from app.providers.openai_provider import OpenAIProvider
from app.settings import Settings


def create_provider(settings: Settings) -> LLMProvider:
    provider = settings.llm_provider.lower()
    if provider == "openai":
        return OpenAIProvider(api_key=settings.openai_api_key, model=settings.openai_model)
    if provider == "anthropic":
        return AnthropicProvider(api_key=settings.anthropic_api_key, model=settings.anthropic_model)
    raise ValueError(f"Unsupported LLM_PROVIDER: {settings.llm_provider}")

