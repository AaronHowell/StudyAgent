from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass


@dataclass(slots=True)
class CitationRef:
    """Minimal citation reference shared between workers and API responses."""

    document_id: str
    document_title: str
    chunk_id: str
    page: int | None = None
    locator: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
