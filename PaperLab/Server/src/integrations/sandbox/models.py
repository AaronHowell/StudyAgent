from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


TaskStatus = Literal["created", "running", "finished", "failed", "expired"]


@dataclass(slots=True)
class RunTaskPaths:
    task_root: Path
    workspace: Path
    logs: Path
    outputs: Path
    metadata_file: Path


@dataclass(slots=True)
class RunTaskMetadata:
    task_id: str
    title: str
    objective: str
    status: TaskStatus
    created_by: str
    created_at: str
    updated_at: str
    root_path: str
    workspace_path: str
    logs_path: str
    outputs_path: str
    source_path: str | None = None
    summary: str = ""
    command_count: int = 0
    last_command: str = ""
    last_exit_code: int | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class CommandResult:
    task_id: str
    command: str
    exit_code: int
    status: str
    stdout: str
    stderr: str
    timed_out: bool
    log_path: str
    working_directory: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
