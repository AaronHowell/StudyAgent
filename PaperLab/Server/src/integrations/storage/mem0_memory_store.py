"""Mem0-backed memory adapter for local self-hosted memory."""

from __future__ import annotations

from dataclasses import dataclass
import inspect
from typing import Any

from mem0 import Memory

from configs import DEFAULT_PROJECT_ID
from domain import MemoryItem, MemoryType


@dataclass(slots=True)
class Mem0MemoryConfig:
    """Configuration values used to construct a Mem0 client."""

    config_dict: dict[str, Any]


class Mem0MemoryStore:
    """Adapt Mem0 OSS to the PaperLab MemoryStore port."""

    def __init__(
        self,
        *,
        client: Any | None = None,
        config: Mem0MemoryConfig | None = None,
    ) -> None:
        if client is not None:
            self.client = client
        elif config is not None:
            self.client = Memory.from_config(config.config_dict)
        else:
            raise ValueError("Mem0MemoryStore requires either a client or a config.")

    def add(self, item: MemoryItem) -> None:
        project_id = _required_entity_id(item.project_id, "project_id")
        self.client.add(
            [{"role": "system", "content": item.content}],
            user_id=project_id,
            metadata={
                **item.metadata,
                "memory_type": item.memory_type.value,
                "importance": item.importance,
            },
            infer=False,
        )

    def remember_messages(
        self,
        *,
        project_id: str,
        messages: list[dict[str, str]],
        thread_id: str | None = None,
        memory_type: MemoryType | str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> list[MemoryItem]:
        resolved_project_id = _required_entity_id(project_id, "project_id")
        resolved_thread_id = _optional_entity_id(thread_id)
        resolved_memory_type = (
            memory_type.value if isinstance(memory_type, MemoryType) else memory_type
        )
        result = self.client.add(
            messages,
            user_id=resolved_project_id,
            run_id=resolved_thread_id,
            metadata={
                **(metadata or {}),
                **(
                    {"memory_type": resolved_memory_type}
                    if resolved_memory_type
                    else {}
                ),
            },
            infer=True,
        )
        result_items = _unwrap_result_items(result)
        return [
            self._to_memory_item(
                resolved_project_id,
                item,
                fallback_metadata=(
                    {"memory_type": resolved_memory_type}
                    if resolved_memory_type
                    else metadata
                ),
            )
            for item in result_items
        ]

    def search(self, query: str, project_id: str, limit: int = 5) -> list[MemoryItem]:
        resolved_project_id = _required_entity_id(project_id, "project_id")
        result = _call_with_result_limit(
            self.client.search,
            limit,
            query,
            **_scope_kwargs(self.client.search, resolved_project_id),
        )
        return [self._to_memory_item(resolved_project_id, item) for item in _unwrap_result_items(result)]

    def summarize_for_project(self, project_id: str) -> str:
        resolved_project_id = _required_entity_id(project_id, "project_id")
        items = [
            self._to_memory_item(resolved_project_id, item)
            for item in _unwrap_result_items(
                _call_with_result_limit(
                    self.client.get_all,
                    10,
                    **_scope_kwargs(self.client.get_all, resolved_project_id),
                )
            )
        ]
        if not items:
            return ""
        lines = ["Relevant memory:"]
        lines.extend(f"- {item.content}" for item in items[:10])
        return "\n".join(lines)

    @staticmethod
    def _to_memory_item(
        project_id: str,
        item: Any,
        *,
        fallback_metadata: dict[str, Any] | None = None,
    ) -> MemoryItem:
        if isinstance(item, str):
            raw_item: dict[str, Any] = {"memory": item}
        else:
            raw_item = item if isinstance(item, dict) else {}
        metadata = dict(
            getattr(item, "metadata", None)
            or raw_item.get("metadata", {})
            or fallback_metadata
            or {}
        )
        memory_type = metadata.get("memory_type", MemoryType.RESEARCH_EPISODE.value)
        return MemoryItem(
            id=str(getattr(item, "id", None) or raw_item.get("id", "")),
            project_id=project_id,
            memory_type=_coerce_memory_type(memory_type),
            content=str(
                getattr(item, "memory", None)
                or getattr(item, "content", None)
                or raw_item.get("memory", "")
                or raw_item.get("content", "")
            ),
            importance=float(
                getattr(item, "score", None) or raw_item.get("score", 0.0) or 0.0
            ),
            metadata=metadata,
        )


def _coerce_memory_type(value: str | MemoryType) -> MemoryType:
    if isinstance(value, MemoryType):
        return value
    try:
        return MemoryType(value)
    except ValueError:
        return MemoryType.RESEARCH_EPISODE


def _unwrap_result_items(result: Any) -> list[Any]:
    if isinstance(result, dict):
        nested = result.get("results", [])
        if isinstance(nested, list):
            return nested
        return []
    if isinstance(result, list):
        return result
    return []


def _call_with_result_limit(method: Any, limit: int, *args: Any, **kwargs: Any) -> Any:
    try:
        parameters = inspect.signature(method).parameters
    except (TypeError, ValueError):
        parameters = {}
    limit_name = "top_k" if "top_k" in parameters else "limit"
    return method(*args, **kwargs, **{limit_name: limit})


def _scope_kwargs(method: Any, project_id: str) -> dict[str, Any]:
    try:
        parameters = inspect.signature(method).parameters
    except (TypeError, ValueError):
        parameters = {}
    if "user_id" in parameters:
        return {"user_id": project_id}
    return {"filters": {"user_id": project_id}}


def _required_entity_id(value: Any, name: str) -> str:
    resolved = str(value or "").strip()
    return resolved or DEFAULT_PROJECT_ID


def _optional_entity_id(value: Any) -> str | None:
    resolved = str(value or "").strip()
    return resolved or None


