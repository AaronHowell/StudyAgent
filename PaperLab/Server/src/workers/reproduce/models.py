"""Dataclass state for PaperLab reproduction runs."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(slots=True)
class PlanTask:
    task_id: str
    title: str
    description: str
    task_type: str
    status: str = "pending"
    assigned_to: str | None = None
    blocked_by: list[str] = field(default_factory=list)
    artifact_ids: list[str] = field(default_factory=list)
    attempts: int = 0
    max_attempts: int = 2
    notes: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "PlanTask":
        return cls(**data)


@dataclass(slots=True)
class AgentState:
    agent_name: str
    status: str = "idle"
    current_task_id: str | None = None
    last_message_at: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "AgentState":
        return cls(**data)


@dataclass(slots=True)
class Artifact:
    artifact_id: str
    artifact_type: str
    path: str
    summary: str
    task_id: str | None = None
    created_at: str = field(default_factory=utc_now)
    metadata: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "Artifact":
        return cls(**data)


@dataclass(slots=True)
class MailboxMessage:
    message_id: str
    sender: str
    recipient: str
    message_type: str
    payload: dict[str, object]
    created_at: str = field(default_factory=utc_now)
    read: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "MailboxMessage":
        return cls(**data)


@dataclass(slots=True)
class RunEvent:
    event_id: str
    event_type: str
    message: str
    payload: dict[str, object] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)

    @classmethod
    def create(cls, event_type: str, message: str, payload: dict[str, object] | None = None) -> "RunEvent":
        return cls(event_id=f"event-{uuid4().hex}", event_type=event_type, message=message, payload=payload or {})

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "RunEvent":
        return cls(**data)


@dataclass(slots=True)
class ReproductionRun:
    run_id: str
    project_id: str
    objective: str
    paper_ids: list[str]
    status: str
    tasks: dict[str, PlanTask]
    agents: dict[str, AgentState]
    artifacts: dict[str, Artifact]
    events: list[RunEvent]
    workspace_path: str
    report_path: str
    permission_mode: str = "manual"
    current_iteration: int = 0
    max_iterations: int = 50
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    error: str = ""

    @classmethod
    def create(
        cls,
        *,
        project_id: str,
        objective: str,
        paper_ids: list[str],
        workspace_path: str,
        permission_mode: str = "manual",
    ) -> "ReproductionRun":
        run_id = f"run-{uuid4().hex[:12]}"
        tasks = build_initial_tasks()
        agents = {
            name: AgentState(agent_name=name)
            for name in [
                "plan_agent",
                "method_worker",
                "figure_worker",
                "code_worker",
                "experiment_worker",
                "report_worker",
            ]
        }
        return cls(
            run_id=run_id,
            project_id=project_id,
            objective=objective,
            paper_ids=paper_ids,
            status="created",
            tasks=tasks,
            agents=agents,
            artifacts={},
            events=[RunEvent.create("created", "Reproduction run created.")],
            workspace_path=workspace_path,
            report_path=f"{workspace_path}/report.md",
            permission_mode=permission_mode,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "project_id": self.project_id,
            "objective": self.objective,
            "paper_ids": self.paper_ids,
            "status": self.status,
            "tasks": {key: task.to_dict() for key, task in self.tasks.items()},
            "agents": {key: agent.to_dict() for key, agent in self.agents.items()},
            "artifacts": {key: artifact.to_dict() for key, artifact in self.artifacts.items()},
            "events": [event.to_dict() for event in self.events],
            "workspace_path": self.workspace_path,
            "report_path": self.report_path,
            "permission_mode": self.permission_mode,
            "current_iteration": self.current_iteration,
            "max_iterations": self.max_iterations,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "ReproductionRun":
        raw = dict(data)
        raw["tasks"] = {key: PlanTask.from_dict(value) for key, value in dict(raw["tasks"]).items()}
        raw["agents"] = {key: AgentState.from_dict(value) for key, value in dict(raw["agents"]).items()}
        raw["artifacts"] = {key: Artifact.from_dict(value) for key, value in dict(raw["artifacts"]).items()}
        raw["events"] = [RunEvent.from_dict(value) for value in list(raw["events"])]
        return cls(**raw)


def build_initial_tasks() -> dict[str, PlanTask]:
    specs = [
        ("T1", "Understand paper", "Summarize the paper objective and reproducible scope.", "understand_paper", [], "method_worker"),
        ("T2", "Extract method", "Extract model, algorithm, losses, and experiment settings.", "extract_method", ["T1"], "method_worker"),
        ("T3", "Inspect figures", "Summarize figures and visual evidence relevant to reproduction.", "inspect_figures", ["T1"], "figure_worker"),
        ("T4", "Design reproduction", "Create a minimal reproduction plan.", "design_reproduction", ["T2", "T3"], "code_worker"),
        ("T5", "Create project files", "Write README, requirements, and reproduce.py.", "create_project_files", ["T4"], "code_worker"),
        ("T6", "Run experiment", "Execute the reproduction script in the sandbox workspace.", "run_experiment", ["T5"], "experiment_worker"),
        ("T7", "Analyze results", "Analyze logs and generated outputs.", "analyze_results", ["T6"], "experiment_worker"),
        ("T8", "Write report", "Write the final reproduction report.", "write_report", ["T7"], "report_worker"),
    ]
    return {
        task_id: PlanTask(
            task_id=task_id,
            title=title,
            description=description,
            task_type=task_type,
            blocked_by=blocked_by,
            assigned_to=worker,
        )
        for task_id, title, description, task_type, blocked_by, worker in specs
    }
