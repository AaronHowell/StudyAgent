from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class ArtifactRef:
    """One structured artifact emitted by a worker."""

    artifact_id: str
    artifact_type: str
    content: str
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
