from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class TaskEnvelope:
    """One supervisor-issued task for a worker."""

    task_id: str
    task_type: str
    agent_name: str
    query: str
    reason: str
    constraints: dict[str, Any]
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
