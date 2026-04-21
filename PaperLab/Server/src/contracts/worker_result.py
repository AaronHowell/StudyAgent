from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class WorkerResult:
    """Structured result returned from one worker to the supervisor."""

    task_id: str
    agent_name: str
    status: str
    summary: str
    artifacts: list[dict[str, Any]]
    confidence: float
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
