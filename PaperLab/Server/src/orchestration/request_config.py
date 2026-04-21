from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from runtime import AgentSettings


@dataclass(slots=True)
class AgentRequestConfig:
    """Normalized request settings resolved from LangGraph configurable values."""

    project_id: str = "default-project"
    document_limit: int = 10
    chunk_limit: int = 8
    asset_limit: int = 6
    memory_limit: int = 5
    thread_id: str | None = None
    max_iterations: int = 2


def coerce_positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def resolve_agent_request_config(config: dict[str, Any] | None) -> AgentRequestConfig:
    configurable = (config or {}).get("configurable", {})
    project_id = str(configurable.get("project_id") or AgentSettings.from_env().default_project_id)
    return AgentRequestConfig(
        project_id=project_id,
        document_limit=coerce_positive_int(configurable.get("document_limit"), 5),
        chunk_limit=coerce_positive_int(configurable.get("chunk_limit"), 8),
        asset_limit=coerce_positive_int(configurable.get("asset_limit"), 6),
        memory_limit=coerce_positive_int(configurable.get("memory_limit"), 5),
        thread_id=str(configurable.get("thread_id")) if configurable.get("thread_id") is not None else None,
        max_iterations=coerce_positive_int(configurable.get("max_iterations"), 2),
    )


def _coerce_positive_int(value: Any, default: int) -> int:
    return coerce_positive_int(value, default)
