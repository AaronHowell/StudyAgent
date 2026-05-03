from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from contracts import AgentArtifact
from contracts import AgentResult
from contracts import AgentTask
from orchestration.output_summary import build_progress_summary


@dataclass(slots=True)
class WorkspaceImplementationState:
    task_id: str
    objective: str
    plan: list[str]
    acceptance_criteria: list[str]
    constraints: list[str]
    max_steps: int
    current_step: str = ""
    completed_steps: list[str] | None = None
    changed_files: list[str] | None = None
    test_results: list[str] | None = None
    blockers: list[str] | None = None
    next_actions: list[str] | None = None
    action_history: list[dict[str, object]] | None = None
    final_report: dict[str, object] | None = None

    def __post_init__(self) -> None:
        self.completed_steps = list(self.completed_steps or [])
        self.changed_files = list(self.changed_files or [])
        self.test_results = list(self.test_results or [])
        self.blockers = list(self.blockers or [])
        self.next_actions = list(self.next_actions or [])
        self.action_history = list(self.action_history or [])
        self.final_report = dict(self.final_report or {})
        if not self.current_step and self.plan:
            self.current_step = self.plan[0]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> WorkspaceImplementationState:
        return cls(
            task_id=str(payload.get("task_id") or ""),
            objective=str(payload.get("objective") or ""),
            plan=_coerce_string_list(payload.get("plan")),
            acceptance_criteria=_coerce_string_list(payload.get("acceptance_criteria")),
            constraints=_coerce_string_list(payload.get("constraints")),
            max_steps=_coerce_positive_int(payload.get("max_steps"), 8),
            current_step=str(payload.get("current_step") or ""),
            completed_steps=_coerce_string_list(payload.get("completed_steps")),
            changed_files=_coerce_string_list(payload.get("changed_files")),
            test_results=_coerce_string_list(payload.get("test_results")),
            blockers=_coerce_string_list(payload.get("blockers")),
            next_actions=_coerce_string_list(payload.get("next_actions")),
            action_history=list(payload.get("action_history", []) or []),
            final_report=dict(payload.get("final_report", {}) or {}),
        )


def build_initial_implementation_state(task: AgentTask) -> WorkspaceImplementationState:
    constraints = dict(task.constraints or {})
    plan = _coerce_string_list(constraints.get("plan")) or [task.query]
    return WorkspaceImplementationState(
        task_id=task.task_id,
        objective=str(constraints.get("objective") or task.query).strip(),
        plan=plan,
        acceptance_criteria=_coerce_string_list(constraints.get("acceptance_criteria")),
        constraints=_coerce_string_list(constraints.get("constraints")),
        max_steps=_coerce_positive_int(constraints.get("max_steps"), 8),
        current_step=plan[0] if plan else task.query,
    )


def record_workspace_observation(
    state: WorkspaceImplementationState,
    *,
    action: str,
    summary: str,
    content: str,
    changed_files: list[str] | None = None,
    test_result: str | None = None,
    blocker: str | None = None,
    next_actions: list[str] | None = None,
) -> WorkspaceImplementationState:
    completed_steps = list(state.completed_steps or [])
    if state.current_step and state.current_step not in completed_steps:
        completed_steps.append(state.current_step)

    changed = _dedupe([*(state.changed_files or []), *(changed_files or [])])
    test_results = list(state.test_results or [])
    if test_result:
        test_results.append(test_result)
    blockers = list(state.blockers or [])
    if blocker:
        blockers.append(blocker)

    action_history = [
        *(state.action_history or []),
        {
            "action": action,
            "summary": summary,
            "content": content,
        },
    ]
    next_step = _next_plan_step(state.plan, completed_steps)
    return WorkspaceImplementationState(
        task_id=state.task_id,
        objective=state.objective,
        plan=list(state.plan),
        acceptance_criteria=list(state.acceptance_criteria),
        constraints=list(state.constraints),
        max_steps=state.max_steps,
        current_step=next_step,
        completed_steps=completed_steps,
        changed_files=changed,
        test_results=test_results,
        blockers=blockers,
        next_actions=list(next_actions or ([] if not next_step else [next_step])),
        action_history=action_history,
        final_report=dict(state.final_report or {}),
    )


def build_implementation_report(
    state: WorkspaceImplementationState,
    *,
    agent_name: str,
    status: str,
) -> AgentResult:
    report = {
        "objective": state.objective,
        "plan": list(state.plan),
        "acceptance_criteria": list(state.acceptance_criteria),
        "completed_steps": list(state.completed_steps or []),
        "changed_files": list(state.changed_files or []),
        "test_results": list(state.test_results or []),
        "blockers": list(state.blockers or []),
        "next_actions": list(state.next_actions or []),
        "action_history": list(state.action_history or []),
    }
    workspace_sources = [
        {
            "kind": "file",
            "path": path,
            "summary": "Changed during WorkspaceAgent implementation",
        }
        for path in report["changed_files"]
    ]
    summary = (
        f"Implementation report for {state.objective}: "
        f"{len(report['completed_steps'])}/{len(state.plan)} steps completed."
    )
    return AgentResult(
        task_id=state.task_id,
        agent_name=agent_name,
        status=status,
        summary=summary,
        artifacts=[
            AgentArtifact(
                artifact_id=f"artifact_workspace_impl_{uuid4().hex[:8]}",
                artifact_type="implementation_report",
                content=summary,
                metadata=report,
            ).to_dict()
        ],
        confidence=0.75 if status == "completed" else 0.45,
        metadata={
            "implementation_report": report,
            "workspace_sources": workspace_sources,
            "progress_summary": build_progress_summary(
                done=", ".join(report["completed_steps"]),
                next=", ".join(report["next_actions"]),
                pending=", ".join(report["blockers"]),
            ),
        },
    )


def _coerce_string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _coerce_positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _next_plan_step(plan: list[str], completed_steps: list[str]) -> str:
    for step in plan:
        if step not in completed_steps:
            return step
    return ""
