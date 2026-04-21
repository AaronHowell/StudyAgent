"""Mem0-backed memory adapter for local self-hosted memory."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mem0 import Memory

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
        self.client.add(
            [{"role": "system", "content": item.content}],
            user_id=item.project_id,
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
        resolved_memory_type = (
            memory_type.value if isinstance(memory_type, MemoryType) else memory_type
        )
        result = self.client.add(
            messages,
            user_id=project_id,
            run_id=thread_id,
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
                project_id,
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
        result = self.client.search(query, user_id=project_id, limit=limit)
        return [self._to_memory_item(project_id, item) for item in _unwrap_result_items(result)]

    def summarize_for_project(self, project_id: str) -> str:
        items = [
            self._to_memory_item(project_id, item)
            for item in _unwrap_result_items(self.client.get_all(user_id=project_id, limit=10))
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


