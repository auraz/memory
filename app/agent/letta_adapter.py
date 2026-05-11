import asyncio
import json
import urllib.request
from typing import Any

from app.agent.core_memory import CoreMemory, CoreMemoryBlock, render_core_memory


class LettaCoreMemory:
    def __init__(
        self,
        agent_id: str,
        api_key: str = "",
        base_url: str = "",
        fallback: CoreMemory | None = None,
    ):
        self.agent_id = agent_id
        self.api_key = api_key
        self.base_url = base_url
        self.fallback = fallback

    async def list_blocks(self) -> list[CoreMemoryBlock]:
        try:
            return await asyncio.to_thread(self._list_blocks_sync)
        except Exception:
            if self.fallback is None:
                raise
            return await self.fallback.list_blocks()

    async def set_block(
        self,
        label: str,
        value: str,
        description: str | None = None,
        char_limit: int | None = None,
    ) -> None:
        try:
            await asyncio.to_thread(self._set_block_sync, label, value)
        except Exception:
            if self.fallback is None:
                raise
            await self.fallback.set_block(label, value, description=description, char_limit=char_limit)
            return
        if self.fallback is not None:
            await self.fallback.set_block(label, value, description=description, char_limit=char_limit)

    async def render(self, max_chars: int) -> str:
        return render_core_memory(await self.list_blocks(), max_chars=max_chars)

    def _client(self):
        try:
            from letta_client import Letta
        except ImportError as exc:
            raise RuntimeError("letta-client is not installed. Install with `pip install letta-client`.") from exc
        kwargs: dict[str, str] = {}
        if self.api_key:
            kwargs["api_key"] = self.api_key
        if self.base_url:
            kwargs["base_url"] = self.base_url
        return Letta(**kwargs)

    def _list_blocks_sync(self) -> list[CoreMemoryBlock]:
        raw_blocks = self._request_json(
            f"/v1/agents/{self.agent_id}/core-memory/blocks",
            method="GET",
        )
        return [self._normalize_block(block) for block in raw_blocks]

    def _set_block_sync(self, label: str, value: str) -> None:
        self._request_json(
            f"/v1/agents/{self.agent_id}/core-memory/blocks/{label}",
            method="PATCH",
            payload={"value": value},
        )

    def _request_json(self, path: str, method: str, payload: dict[str, Any] | None = None) -> Any:
        base_url = (self.base_url or "http://localhost:8283").rstrip("/")
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(
            f"{base_url}{path}",
            data=data,
            headers=headers,
            method=method,
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.load(response)

    def _normalize_block(self, block: Any) -> CoreMemoryBlock:
        label = str(_field(block, "label", ""))
        description = str(_field(block, "description", ""))
        value = str(_field(block, "value", ""))
        char_limit = _field(block, "limit", None) or _field(block, "char_limit", None) or len(value) or 2000
        return CoreMemoryBlock(
            label=label,
            description=description,
            value=value,
            char_limit=int(char_limit),
        )


def _field(value: Any, name: str, default: Any) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)
