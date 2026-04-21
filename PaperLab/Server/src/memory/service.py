"""Unified memory service used by LangGraph nodes and worker entrypoints."""

from __future__ import annotations

from typing import Any

from domain import MemoryType

from memory.models import AgentRole
from memory.models import MemoryBackend
from memory.models import MemoryRecallResult
from memory.policy import memory_profile_for_role
from runtime.settings import AgentSettings

try:
    from langchain_core.messages import BaseMessage
except ImportError:  # pragma: no cover
    BaseMessage = Any  # type: ignore[assignment]


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return "".join(parts)
    return str(content)


def _normalize_for_summary(message: BaseMessage) -> str:
    role = getattr(message, "type", "message")
    if role == "human":
        role = "user"
    elif role == "ai":
        role = "assistant"
    return f"{role}: {_message_text(message.content)}"


def _conversation_messages(messages: list[BaseMessage]) -> list[BaseMessage]:
    return [message for message in messages if getattr(message, "type", "") in {"human", "ai"}]


class MemoryService:
    """Role-aware memory facade that hides the concrete backend implementation."""

    def __init__(
        self,
        *,
        backend: MemoryBackend | None,
        settings: AgentSettings | None = None,
    ) -> None:
        self.backend = backend
        self.settings = settings or AgentSettings.from_env()

    def recall(
        self,
        *,
        role: AgentRole,
        query: str,
        project_id: str,
        limit: int,
    ) -> MemoryRecallResult:
        profile = memory_profile_for_role(role, self.settings)
        if not profile.long_term_enabled or self.backend is None:
            return MemoryRecallResult(summary="", hits=[])

        hits = self.backend.search(query, project_id=project_id, limit=limit)
        if hits:
            lines = ["Relevant memory:"]
            lines.extend(f"- {item.content}" for item in hits)
            return MemoryRecallResult(summary="\n".join(lines), hits=hits)

        return MemoryRecallResult(
            summary=self.backend.summarize_for_project(project_id),
            hits=[],
        )

    def store_turn(
        self,
        *,
        role: AgentRole,
        project_id: str,
        thread_id: str | None,
        user_text: str,
        assistant_text: str,
        metadata: dict[str, object],
        memory_type: MemoryType = MemoryType.RESEARCH_EPISODE,
    ) -> bool:
        profile = memory_profile_for_role(role, self.settings)
        if not profile.long_term_enabled or self.backend is None:
            return False

        self.backend.remember_messages(
            project_id=project_id,
            thread_id=thread_id,
            messages=[
                {"role": "user", "content": user_text},
                {"role": "assistant", "content": assistant_text},
            ],
            memory_type=memory_type,
            metadata=metadata,
        )
        return True

    def build_short_term_context(
        self,
        *,
        role: AgentRole,
        messages: list[BaseMessage],
    ) -> str:
        profile = memory_profile_for_role(role, self.settings)
        if not profile.short_term_enabled:
            return ""

        convo_messages = _conversation_messages(messages)
        if not convo_messages:
            return ""

        recent_span = max(2, profile.short_term_raw_turns * 2)
        summary_span = max(0, profile.short_term_summary_turns * 2)
        recent_messages = convo_messages[-recent_span:]
        summary_candidates = (
            convo_messages[-(recent_span + summary_span) : -recent_span] if summary_span else []
        )

        readable_parts: list[str] = []
        if summary_candidates and profile.compression_enabled:
            readable_parts.append(
                "Earlier summary:\n"
                + "\n".join(f"- {_normalize_for_summary(message)}" for message in summary_candidates)
            )
        readable_parts.append(
            "Recent raw turns:\n"
            + "\n".join(f"- {_normalize_for_summary(message)}" for message in recent_messages)
        )
        return "\n\n".join(part for part in readable_parts if part)


def build_memory_service(
    *,
    backend: MemoryBackend | None,
    settings: AgentSettings | None = None,
) -> MemoryService:
    """Factory used by graph nodes and workers to build a consistent memory facade."""

    return MemoryService(backend=backend, settings=settings)

