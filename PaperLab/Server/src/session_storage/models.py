"""会话持久化模型。"""

from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class SessionMessageRecord:
    """一条可恢复的聊天消息。"""

    id: str | None
    type: str | None
    role: str | None
    content: Any
    additional_kwargs: dict[str, object]
    response_metadata: dict[str, object]
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SessionMessageRecord":
        return cls(
            id=payload.get("id"),
            type=payload.get("type"),
            role=payload.get("role"),
            content=payload.get("content"),
            additional_kwargs=dict(payload.get("additional_kwargs", {}) or {}),
            response_metadata=dict(payload.get("response_metadata", {}) or {}),
            created_at=str(payload.get("created_at") or ""),
        )


@dataclass(slots=True)
class SessionCheckpoint:
    """最近一次可恢复的会话快照。"""

    session_id: str
    project_id: str
    thread_id: str
    updated_at: str
    interrupt: dict[str, object] | None
    next_nodes: list[str]
    resume_capable: bool
    active_turn_id: str = ""
    iteration_count: int = 0
    max_iterations: int = 0
    answer_confident: bool = False
    stop_reason: str = ""
    processed_human_message_count: int = 0
    intervention_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SessionCheckpoint":
        return cls(
            session_id=str(payload.get("session_id") or ""),
            project_id=str(payload.get("project_id") or ""),
            thread_id=str(payload.get("thread_id") or ""),
            updated_at=str(payload.get("updated_at") or ""),
            interrupt=dict(payload.get("interrupt", {}) or {}) or None,
            next_nodes=[str(item) for item in payload.get("next_nodes", []) or []],
            resume_capable=bool(payload.get("resume_capable", False)),
            active_turn_id=str(payload.get("active_turn_id") or ""),
            iteration_count=int(payload.get("iteration_count", 0) or 0),
            max_iterations=int(payload.get("max_iterations", 0) or 0),
            answer_confident=bool(payload.get("answer_confident", False)),
            stop_reason=str(payload.get("stop_reason") or ""),
            processed_human_message_count=int(payload.get("processed_human_message_count", 0) or 0),
            intervention_count=int(payload.get("intervention_count", 0) or 0),
        )


@dataclass(slots=True)
class SessionSummary:
    """会话列表页展示所需的摘要。"""

    session_id: str
    project_id: str
    title: str
    updated_at: str
    message_count: int
    resume_capable: bool


@dataclass(slots=True)
class WorkerEventRecord:
    """独立 worker/subagent 日志项。"""

    event_id: str
    session_id: str
    project_id: str
    agent_id: str
    worker_type: str
    kind: str
    payload: dict[str, Any]
    created_at: str

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "WorkerEventRecord":
        return cls(
            event_id=str(payload.get("event_id") or ""),
            session_id=str(payload.get("session_id") or ""),
            project_id=str(payload.get("project_id") or ""),
            agent_id=str(payload.get("agent_id") or ""),
            worker_type=str(payload.get("worker_type") or ""),
            kind=str(payload.get("kind") or ""),
            payload=dict(payload.get("payload", {}) or {}),
            created_at=str(payload.get("created_at") or ""),
        )


@dataclass(slots=True)
class RestoredSession:
    """恢复结果。"""

    session_id: str
    project_id: str
    thread_id: str
    messages: list[SessionMessageRecord]
    checkpoint: SessionCheckpoint | None
