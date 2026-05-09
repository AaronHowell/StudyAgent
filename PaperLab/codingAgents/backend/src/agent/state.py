"""Agent 状态管理。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AgentPhase(str, Enum):
    INIT = "init"
    PLANNING = "planning"
    CODING = "coding"
    EXECUTING = "executing"
    FIXING = "fixing"
    DONE = "done"
    FAILED = "failed"
    WAITING_APPROVAL = "waiting_approval"


@dataclass
class AgentAction:
    """一次 Agent 动作记录。"""
    action_id: str
    tool_name: str
    args: dict[str, Any]
    result: dict[str, Any] | None = None
    approved: bool | None = None    # None=待确认, True=批准, False=拒绝
    timestamp: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "tool_name": self.tool_name,
            "args": self._sanitize_args(self.args),
            "result": self.result,
            "approved": self.approved,
            "timestamp": self.timestamp,
        }

    @staticmethod
    def _sanitize_args(args: dict[str, Any]) -> dict[str, Any]:
        """截断过长的参数值。"""
        sanitized = {}
        for k, v in args.items():
            if isinstance(v, str) and len(v) > 2000:
                sanitized[k] = v[:2000] + f"... ({len(v)} chars total)"
            else:
                sanitized[k] = v
        return sanitized


@dataclass
class AgentState:
    """Coding Agent 的完整状态。"""
    session_id: str
    phase: AgentPhase = AgentPhase.INIT
    paper_context: str = ""             # 论文上下文（摘要、方法等）
    plan: str = ""                      # 复现计划
    iteration: int = 0
    actions: list[AgentAction] = field(default_factory=list)
    pending_action: AgentAction | None = None   # 等待用户确认的动作
    error: str = ""
    summary: str = ""                   # 最终总结

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "phase": self.phase.value,
            "paper_context": self.paper_context[:500] + "..." if len(self.paper_context) > 500 else self.paper_context,
            "plan": self.plan,
            "iteration": self.iteration,
            "actions": [a.to_dict() for a in self.actions],
            "pending_action": self.pending_action.to_dict() if self.pending_action else None,
            "error": self.error,
            "summary": self.summary,
        }
