"""Role-aware memory policy for supervisor and worker agents."""

from __future__ import annotations

from memory.models import AgentRole
from memory.models import MemoryProfile
from runtime.settings import AgentSettings


def memory_profile_for_role(
    role: AgentRole,
    settings: AgentSettings | None = None,
) -> MemoryProfile:
    """Return the memory envelope allowed for one orchestration role."""

    resolved = settings or AgentSettings.from_env()
    if role == "supervisor":
        return MemoryProfile(
            role="supervisor",
            long_term_enabled=True,
            short_term_enabled=True,
            compression_enabled=True,
            short_term_raw_turns=resolved.short_term_raw_turns,
            short_term_summary_turns=resolved.short_term_summary_turns,
        )
    if role == "retriever":
        return MemoryProfile(
            role="retriever",
            long_term_enabled=False,
            short_term_enabled=True,
            compression_enabled=True,
            short_term_raw_turns=max(2, min(3, resolved.short_term_raw_turns)),
            short_term_summary_turns=max(1, min(2, resolved.short_term_summary_turns)),
        )
    return MemoryProfile(
        role="executor",
        long_term_enabled=False,
        short_term_enabled=True,
        compression_enabled=True,
        short_term_raw_turns=max(2, min(3, resolved.short_term_raw_turns)),
        short_term_summary_turns=max(1, min(2, resolved.short_term_summary_turns)),
    )

