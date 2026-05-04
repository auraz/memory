from anthropic import AsyncAnthropic

from app.providers.base import LLMProvider


class AnthropicProvider(LLMProvider):
    def __init__(self, api_key: str, model: str):
        self.client = AsyncAnthropic(api_key=api_key)
        self.model = model

    async def complete(self, system: str, user: str) -> str:
        response = await self.client.messages.create(
            model=self.model,
            max_tokens=1200,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(block.text for block in response.content if block.type == "text")

