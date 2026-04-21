from __future__ import annotations

from typing import Any
from typing import TypedDict

from contracts import AgentTask

try:
    from langchain_core.messages import BaseMessage
except ImportError:  # pragma: no cover
    BaseMessage = Any  # type: ignore[assignment]


class PaperLabGraphState(TypedDict, total=False):
    """Message-ledger-first LangGraph state."""

    messages: list[BaseMessage]
    active_turn_id: str
    thread_lock_key: str
    iteration_count: int
    max_iterations: int
    answer_confident: bool
    stop_reason: str
    retrieve_task: AgentTask | None
    tool_task: AgentTask | None
    workspace_task: AgentTask | None
    retrieve_result: dict[str, Any] | None
    tool_result: dict[str, Any] | None
    workspace_result: dict[str, Any] | None
    processed_human_message_count: int
    intervention_count: int


class RetrieveAgentGraphState(TypedDict, total=False):
    active_turn_id: str
    retrieve_task: AgentTask | None
    retrieve_result: dict[str, Any] | None
    messages: list[BaseMessage]


class ToolAgentGraphState(TypedDict, total=False):
    active_turn_id: str
    tool_task: AgentTask | None
    tool_result: dict[str, Any] | None
    messages: list[BaseMessage]


class WorkspaceAgentGraphState(TypedDict, total=False):
    active_turn_id: str
    workspace_task: AgentTask | None
    workspace_result: dict[str, Any] | None
    messages: list[BaseMessage]
