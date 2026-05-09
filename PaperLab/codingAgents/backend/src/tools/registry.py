"""工具注册表 — Agent 可用的工具定义与调度。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Awaitable


@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]           # JSON Schema
    handler: Callable[..., Awaitable[dict[str, Any]]]
    requires_approval: bool = False       # 是否需要用户确认
    risk_level: str = "low"              # low / medium / high

    def to_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    """管理所有可用工具。"""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    def list_tools(self) -> list[ToolDefinition]:
        return list(self._tools.values())

    def to_schemas(self) -> list[dict[str, Any]]:
        return [t.to_schema() for t in self._tools.values()]

    async def execute(
        self,
        name: str,
        args: dict[str, Any],
        *,
        skip_approval: bool = False,
    ) -> dict[str, Any]:
        tool = self._tools.get(name)
        if tool is None:
            return {"error": f"Unknown tool: {name}"}
        if tool.requires_approval and not skip_approval:
            return {
                "needs_approval": True,
                "tool_name": name,
                "args": args,
                "risk_level": tool.risk_level,
            }
        try:
            return await tool.handler(**args)
        except Exception as e:
            return {"error": str(e)}
