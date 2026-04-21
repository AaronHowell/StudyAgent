"""Memory-domain models shared by the agent orchestration layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from typing import Literal
from typing import Protocol

from domain import MemoryItem
from domain import MemoryType


AgentRole = Literal["supervisor", "retriever", "executor"]


class MemoryBackend(Protocol):
    """Adapter contract for long-term memory backends such as Mem0 or a custom store."""

    def remember_messages(
        self,
        *,
        project_id: str,
        messages: list[dict[str, str]],
        thread_id: str | None = None,
        memory_type: MemoryType | str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> list[MemoryItem]:
        """Persist memories inferred from a short conversation window."""

    def search(self, query: str, project_id: str, limit: int = 5) -> list[MemoryItem]:
        """Search long-term memory scoped to one project."""

    def summarize_for_project(self, project_id: str) -> str:
        """Return a compact long-term memory summary for one project."""


@dataclass(slots=True)
class MemoryProfile:
    """Memory capabilities assigned to one orchestration role."""

    role: AgentRole
    long_term_enabled: bool
    short_term_enabled: bool = True
    compression_enabled: bool = True
    short_term_raw_turns: int = 3
    short_term_summary_turns: int = 4


@dataclass(slots=True)
class MemoryRecallResult:
    """Normalized recall payload returned to the graph layer."""

    summary: str
    hits: list[MemoryItem] = field(default_factory=list)

