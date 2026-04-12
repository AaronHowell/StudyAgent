"""Core domain models for StudyAgent."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class DocumentType(StrEnum):
    """Document types supported by the project."""

    PDF = "pdf"
    MARKDOWN = "markdown"


class DocumentStatus(StrEnum):
    """Lifecycle states for documents inside a project."""

    DISCOVERED = "discovered"
    INDEXED = "indexed"
    FAILED = "failed"


class ChunkType(StrEnum):
    """Chunk modalities stored in the knowledge base."""

    TEXT = "text"
    IMAGE = "image"
    WEB = "web"


class MemoryType(StrEnum):
    """Memory categories kept intentionally small for early iterations."""

    PREFERENCE = "preference"
    PROJECT_FACT = "project_fact"
    RESEARCH_EPISODE = "research_episode"


class ScanStatus(StrEnum):
    """Outcome status for one document discovered during a scan."""

    DISCOVERED = "discovered"
    SKIPPED = "skipped"
    ERROR = "error"


@dataclass(slots=True)
class Project:
    """A research workspace bound to a local document folder."""

    id: str
    name: str
    root_path: str
    description: str = ""


@dataclass(slots=True)
class PdfPage:
    """Plain-text representation of one PDF page after extraction."""

    page_number: int
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DocumentAsset:
    """One extracted visual asset from a document page.

    作用:
        统一表示论文中的可检索视觉资产，例如 figure、table 或其它渲染出的视觉区域。
        该对象当前同时承担解析结果、持久化实体和检索载荷三种职责，这是刻意保留的
        轻量方案，避免在项目早期把同一份资产数据拆散到多个对象中。
    """

    id: str
    document_id: str
    page_number: int
    file_path: str
    file_name: str
    asset_kind: str = "visual"
    asset_label: str = ""
    asset_index: int | None = None
    caption: str = ""
    summary: str = ""
    asset_type: str = "unknown"
    keywords: list[str] = field(default_factory=list)
    related_chunk_ids: list[str] = field(default_factory=list)
    media_type: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def figure_label(self) -> str:
        """Return the legacy figure label for compatibility with old callers."""

        return self.asset_label if self.asset_kind == "figure" else ""

    @property
    def figure_index(self) -> int | None:
        """Return the legacy figure index for compatibility with old callers."""

        return self.asset_index if self.asset_kind == "figure" else None


@dataclass(slots=True)
class Document:
    """A source document tracked by the system."""

    id: str
    project_id: str
    path: str
    file_name: str
    doc_type: DocumentType
    title: str
    status: DocumentStatus
    content_hash: str


@dataclass(slots=True)
class DocumentProfile:
    """A document-level retrieval profile used before chunk retrieval.

    作用:
        表示一篇论文在整库检索阶段的摘要画像，便于先找相关论文，再深入正文和视觉资产。
        通常会将 `title`、`summary` 做嵌入，其它字段作为 payload 参与过滤和回查。
    """

    document_id: str
    project_id: str
    title: str
    summary: str = ""
    keywords: list[str] = field(default_factory=list)
    file_name: str = ""
    path: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DocumentDiscoveryResult:
    """One scan result row describing what happened to a file path."""

    path: str
    status: ScanStatus
    document: Document | None = None
    reason: str = ""


@dataclass(slots=True)
class ScanSummary:
    """Aggregated scan output returned by a project-level document scan."""

    project_id: str
    discovered_documents: list[Document] = field(default_factory=list)
    results: list[DocumentDiscoveryResult] = field(default_factory=list)

    @property
    def discovered_count(self) -> int:
        """Return the number of successfully discovered documents."""

        return sum(1 for result in self.results if result.status == ScanStatus.DISCOVERED)

    @property
    def skipped_count(self) -> int:
        """Return the number of skipped files."""

        return sum(1 for result in self.results if result.status == ScanStatus.SKIPPED)

    @property
    def error_count(self) -> int:
        """Return the number of files that failed during scan."""

        return sum(1 for result in self.results if result.status == ScanStatus.ERROR)


@dataclass(slots=True)
class Chunk:
    """A normalized knowledge unit extracted from a document or the web."""

    id: str
    project_id: str
    document_id: str
    chunk_index: int
    chunk_type: ChunkType
    text: str
    page: int | None = None
    section: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Citation:
    """A lightweight pointer back to the original source."""

    document_id: str
    document_title: str
    chunk_id: str
    page: int | None = None
    locator: str = ""


@dataclass(slots=True)
class ScoredId:
    """One vector-search hit that only contains a business id and score."""

    entity_id: str
    score: float


@dataclass(slots=True)
class DocumentHit:
    """One scored document-level retrieval result."""

    document: Document
    score: float

    @property
    def document_id(self) -> str:
        return self.document.id

    @property
    def title(self) -> str:
        return self.document.title

    @property
    def file_name(self) -> str:
        return self.document.file_name

    @property
    def path(self) -> str:
        return self.document.path

    @property
    def status(self) -> str:
        return self.document.status.value


@dataclass(slots=True)
class ChunkHit:
    """One scored chunk-level retrieval result."""

    chunk: Chunk
    score: float

    @property
    def chunk_id(self) -> str:
        return self.chunk.id

    @property
    def document_id(self) -> str:
        return self.chunk.document_id

    @property
    def chunk_index(self) -> int:
        return self.chunk.chunk_index

    @property
    def page(self) -> int | None:
        return self.chunk.page

    @property
    def section(self) -> str | None:
        return self.chunk.section

    @property
    def text(self) -> str:
        return self.chunk.text


@dataclass(slots=True)
class AssetHit:
    """One scored visual-asset retrieval result."""

    asset: DocumentAsset
    score: float

    @property
    def asset_id(self) -> str:
        return self.asset.id

    @property
    def document_id(self) -> str:
        return self.asset.document_id

    @property
    def page_number(self) -> int:
        return self.asset.page_number

    @property
    def asset_label(self) -> str:
        return self.asset.asset_label

    @property
    def caption(self) -> str:
        return self.asset.caption

    @property
    def summary(self) -> str:
        return self.asset.summary

    @property
    def asset_type(self) -> str:
        return self.asset.asset_type

    @property
    def file_name(self) -> str:
        return self.asset.file_name

    @property
    def file_path(self) -> str:
        return self.asset.file_path


@dataclass(slots=True)
class TaskCard:
    """A planner-produced task description for the agent workflow."""

    intent: str
    sub_questions: list[str] = field(default_factory=list)
    need_web: bool = False
    output_format: str = "answer"


@dataclass(slots=True)
class EvidencePack:
    """Retrieved evidence passed from retrieval to generation."""

    query: str
    documents: list[DocumentHit] = field(default_factory=list)
    text_chunks: list[ChunkHit] = field(default_factory=list)
    assets: list[AssetHit] = field(default_factory=list)
    image_chunks: list[Chunk] = field(default_factory=list)
    web_snippets: list[Chunk] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)


@dataclass(slots=True)
class MemoryItem:
    """A stored memory record scoped to a project."""

    id: str
    project_id: str
    memory_type: MemoryType
    content: str
    importance: float
    metadata: dict[str, Any] = field(default_factory=dict)
