"""Optional MCP tool provider adapter for PaperLab ToolAgent."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable

logger = logging.getLogger("paperlab.mcp")

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.client.streamable_http import streamable_http_client
except ImportError:  # pragma: no cover
    ClientSession = Any  # type: ignore[assignment]
    StdioServerParameters = None  # type: ignore[assignment]
    stdio_client = None  # type: ignore[assignment]
    streamable_http_client = None  # type: ignore[assignment]


@dataclass(slots=True)
class McpToolProviderConfig:
    server_id: str = "default"
    transport: str = "stdio"
    command: str = ""
    args: list[str] = field(default_factory=list)
    url: str = ""
    timeout_seconds: int = 20


class McpToolProvider:
    """Minimal MCP client wrapper for listing and calling MCP tools."""

    def __init__(
        self,
        config: McpToolProviderConfig | None = None,
        *,
        session_factory: Callable[[], Any] | None = None,
        configs: list[McpToolProviderConfig] | None = None,
        session_factories: dict[str, Callable[[], Any]] | None = None,
    ) -> None:
        self.config = config or McpToolProviderConfig()
        self.configs = list(configs or [self.config])
        self._session_factory = session_factory
        self._session_factories = dict(session_factories or {})
        if (
            session_factory is None
            and not self._session_factories
            and (ClientSession is Any or StdioServerParameters is None)
        ):
            raise RuntimeError("mcp is not installed. Install the MCP Python SDK to enable MCP tools.")

    @asynccontextmanager
    async def _session(self, config: McpToolProviderConfig) -> AsyncIterator[Any]:
        session_factory = self._session_factories.get(config.server_id, self._session_factory)
        if session_factory is not None:
            async with session_factory() as session:
                yield session
            return

        if ClientSession is Any or StdioServerParameters is None:
            raise RuntimeError("mcp is not installed. Install the MCP Python SDK to enable MCP tools.")

        if config.transport == "stdio":
            if not config.command:
                raise RuntimeError("MCP stdio transport requires a server command.")
            server_params = StdioServerParameters(
                command=config.command,
                args=list(config.args),
            )
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    yield session
            return

        if config.transport == "streamable_http":
            if not config.url:
                raise RuntimeError("MCP streamable_http transport requires a server URL.")
            async with streamable_http_client(config.url) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    yield session
            return

        raise RuntimeError(f"Unsupported MCP transport: {config.transport}")

    async def list_tools(self) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for config in self.configs:
            try:
                async with self._session(config) as session:
                    response = await session.list_tools()
            except Exception as exc:
                logger.warning("MCP server '%s' failed to connect: %s", config.server_id, exc)
                continue
            tools = getattr(response, "tools", []) or []
            for tool in tools:
                tool_name = str(getattr(tool, "name", "") or "")
                normalized.append(
                    {
                        "name": f"{config.server_id}::{tool_name}",
                        "description": f"[{config.server_id}] {str(getattr(tool, 'description', '') or '')}".strip(),
                        "input_schema": dict(getattr(tool, "inputSchema", {}) or {}),
                    }
                )
        return normalized

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        server_id, tool_name = self._split_tool_name(name)
        config = self._find_config(server_id)
        try:
            async with self._session(config) as session:
                result = await session.call_tool(tool_name, arguments=arguments)
        except Exception as exc:
            logger.warning("MCP tool '%s' on server '%s' failed: %s", tool_name, server_id, exc)
            return {
                "tool_name": name,
                "server_id": server_id,
                "text": f"工具调用失败: {exc}",
                "structured_content": None,
                "is_error": True,
                "content": [{"type": "text", "text": f"工具调用失败: {exc}"}],
            }
        content_blocks = getattr(result, "content", []) or []
        texts: list[str] = []
        normalized_content: list[dict[str, Any]] = []
        for block in content_blocks:
            text = getattr(block, "text", None)
            if text is not None:
                texts.append(str(text))
                normalized_content.append({"type": "text", "text": str(text)})
                continue
            resource = getattr(block, "resource", None)
            if resource is not None:
                normalized_content.append(
                    {
                        "type": "resource",
                        "uri": str(getattr(resource, "uri", "") or ""),
                        "text": str(getattr(resource, "text", "") or ""),
                    }
                )
        return {
            "tool_name": name,
            "server_id": server_id,
            "text": "\n".join(texts).strip(),
            "structured_content": getattr(result, "structuredContent", None),
            "is_error": bool(getattr(result, "isError", False)),
            "content": normalized_content,
        }

    def _find_config(self, server_id: str) -> McpToolProviderConfig:
        for config in self.configs:
            if config.server_id == server_id:
                return config
        raise RuntimeError(f"Unknown MCP server id: {server_id}")

    @staticmethod
    def _split_tool_name(name: str) -> tuple[str, str]:
        if "::" not in name:
            return "default", name
        server_id, tool_name = name.split("::", 1)
        return server_id, tool_name

