from __future__ import annotations

from dataclasses import dataclass
import asyncio
import os
from typing import Any


@dataclass(frozen=True)
class McpToolResult:
    tool_name: str
    text: str
    structured: Any | None = None
    raw: Any | None = None


async def call_stdio_tool(
    *,
    command: str,
    args: list[str],
    tool_name: str,
    tool_args: dict[str, Any],
    env: dict[str, str] | None = None,
    timeout_seconds: int = 120,
) -> McpToolResult:
    async def _call() -> McpToolResult:
        ClientSession, StdioServerParameters, stdio_client = _mcp_imports()
        server_params = StdioServerParameters(command=command, args=args, env=env or dict(os.environ))
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, tool_args)
        return _normalize_result(tool_name, result)

    return await asyncio.wait_for(_call(), timeout=timeout_seconds)


async def list_stdio_tools(
    *,
    command: str,
    args: list[str],
    env: dict[str, str] | None = None,
    timeout_seconds: int = 120,
) -> list[dict[str, Any]]:
    async def _list() -> list[dict[str, Any]]:
        ClientSession, StdioServerParameters, stdio_client = _mcp_imports()
        server_params = StdioServerParameters(command=command, args=args, env=env or dict(os.environ))
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
        tools = getattr(result, "tools", result)
        return [_tool_to_dict(tool) for tool in tools]

    return await asyncio.wait_for(_list(), timeout=timeout_seconds)


def _mcp_imports():
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ModuleNotFoundError as exc:
        raise RuntimeError("MCP support is not installed. Run `uv sync` after adding the `mcp` dependency.") from exc
    return ClientSession, StdioServerParameters, stdio_client


def _normalize_result(tool_name: str, result: Any) -> McpToolResult:
    content = getattr(result, "content", None) or []
    text_parts: list[str] = []
    for item in content:
        text = getattr(item, "text", None)
        if text:
            text_parts.append(str(text))
    structured = getattr(result, "structuredContent", None)
    if structured is None:
        structured = getattr(result, "structured_content", None)
    return McpToolResult(tool_name=tool_name, text="\n".join(text_parts), structured=structured, raw=result)


def _tool_to_dict(tool: Any) -> dict[str, Any]:
    if hasattr(tool, "model_dump"):
        return tool.model_dump()
    if isinstance(tool, dict):
        return dict(tool)
    return {
        "name": getattr(tool, "name", ""),
        "description": getattr(tool, "description", ""),
        "inputSchema": getattr(tool, "inputSchema", None),
    }
