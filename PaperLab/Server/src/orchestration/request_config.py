from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from configs import DEFAULT_PROJECT_ID
from configs import DEFAULT_THREAD_ID
from runtime import AgentSettings


@dataclass(slots=True)
class AgentRequestConfig:
    """Normalized request settings resolved from LangGraph configurable values."""

    project_id: str = DEFAULT_PROJECT_ID
    document_limit: int = 10
    chunk_limit: int = 8
    asset_limit: int = 6
    memory_limit: int = 5
    thread_id: str | None = DEFAULT_THREAD_ID
    max_iterations: int = 2
    workspace_root: str | None = None
    allow_web_search: bool = False
    allow_file_read: bool = False
    allow_file_write: bool = False
    allow_mcp: bool = False
    allow_shell: bool = False


def coerce_positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def coerce_non_empty_str(value: Any, default: str) -> str:
    parsed = str(value or "").strip()
    return parsed or default


def coerce_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def resolve_agent_request_config(config: dict[str, Any] | None) -> AgentRequestConfig:
    configurable = (config or {}).get("configurable", {})
    default_project_id = AgentSettings.from_env().default_project_id or DEFAULT_PROJECT_ID
    project_id = coerce_non_empty_str(configurable.get("project_id"), default_project_id)
    return AgentRequestConfig(
        project_id=project_id,
        document_limit=coerce_positive_int(configurable.get("document_limit"), 5),
        chunk_limit=coerce_positive_int(configurable.get("chunk_limit"), 8),
        asset_limit=coerce_positive_int(configurable.get("asset_limit"), 6),
        memory_limit=coerce_positive_int(configurable.get("memory_limit"), 5),
        thread_id=coerce_non_empty_str(configurable.get("thread_id"), DEFAULT_THREAD_ID),
        max_iterations=coerce_positive_int(configurable.get("max_iterations"), 2),
        workspace_root=str(configurable.get("workspace_root") or "").strip() or None,
        allow_web_search=coerce_bool(configurable.get("allow_web_search"), False),
        allow_file_read=coerce_bool(configurable.get("allow_file_read"), False),
        allow_file_write=coerce_bool(configurable.get("allow_file_write"), False),
        allow_mcp=coerce_bool(configurable.get("allow_mcp"), False),
        allow_shell=coerce_bool(configurable.get("allow_shell"), False),
    )


def _coerce_positive_int(value: Any, default: int) -> int:
    return coerce_positive_int(value, default)
