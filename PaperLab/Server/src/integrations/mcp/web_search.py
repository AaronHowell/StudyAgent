"""Simple DDGS-backed web search and URL fetch provider."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha1
from typing import Any

try:
    from ddgs import DDGS
except ImportError:  # pragma: no cover - exercised only when dependency is missing at runtime
    DDGS = None  # type: ignore[assignment]

from domain import Chunk, ChunkType


@dataclass(slots=True)
class DDGSWebSearchConfig:
    timeout_seconds: int = 20


class DDGSWebSearchProvider:
    """Normalize DDGS search and extract results into web chunks."""

    def __init__(
        self,
        config: DDGSWebSearchConfig | None = None,
        *,
        client: Any | None = None,
    ) -> None:
        self.config = config or DDGSWebSearchConfig()
        if client is not None:
            self.client = client
        else:
            if DDGS is None:
                raise RuntimeError(
                    "ddgs is not installed. Install it to enable DuckDuckGo web search."
                )
            self.client = DDGS(timeout=self.config.timeout_seconds)

    def search(self, query: str, limit: int = 5) -> list[Chunk]:
        rows = list(self.client.text(query, max_results=limit) or [])
        chunks: list[Chunk] = []
        for index, row in enumerate(rows):
            url = str(row.get("href", "") or row.get("url", ""))
            title = str(row.get("title", "") or "")
            snippet = str(row.get("body", "") or row.get("snippet", "") or "")
            chunks.append(
                Chunk(
                    id=_stable_web_chunk_id(url or f"search:{query}:{index}"),
                    project_id="web",
                    document_id=url or f"search:{query}",
                    chunk_index=index,
                    chunk_type=ChunkType.WEB,
                    text=snippet,
                    metadata={
                        "title": title,
                        "url": url,
                        "snippet": snippet,
                        "query": query,
                    },
                )
            )
        return chunks

    def fetch(self, url: str) -> Chunk:
        rows = list(self.client.extract([url]) or [])
        if not rows:
            return Chunk(
                id=_stable_web_chunk_id(url),
                project_id="web",
                document_id=url,
                chunk_index=0,
                chunk_type=ChunkType.WEB,
                text="",
                metadata={"title": "", "url": url, "excerpt": ""},
            )

        row = rows[0]
        body = str(row.get("body", "") or row.get("content", "") or "")
        title = str(row.get("title", "") or "")
        excerpt = body[:800]
        return Chunk(
            id=_stable_web_chunk_id(url),
            project_id="web",
            document_id=url,
            chunk_index=0,
            chunk_type=ChunkType.WEB,
            text=body,
            metadata={
                "title": title,
                "url": url,
                "excerpt": excerpt,
            },
        )


def _stable_web_chunk_id(value: str) -> str:
    return f"web_{sha1(value.encode('utf-8')).hexdigest()[:12]}"

