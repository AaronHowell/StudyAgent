"""Protocol-based ports for PaperLab implementations."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Protocol

from domain.models import (
    AssetHit,
    Chunk,
    ChunkHit,
    Citation,
    Document,
    DocumentAsset,
    DocumentHit,
    EvidencePack,
    MemoryItem,
    MemoryType,
    PdfPage,
    Project,
    ScoredId,
    ScanSummary,
    TaskCard,
)


class LLMProvider(Protocol):
    """Text generation interface used by higher-level application services."""

    def generate(self, prompt: str) -> str:
        """Generate a single text response for a prompt."""

    def stream_generate(self, prompt: str) -> Iterable[str]:
        """Stream response fragments for a prompt."""


class EmbeddingProvider(Protocol):
    """Embedding interface for text and image inputs."""

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of text inputs."""

    def embed_images(self, image_paths: list[str]) -> list[list[float]]:
        """Embed a list of image paths or image identifiers."""


class RerankerProvider(Protocol):
    """Cross-encoder style reranker interface used after vector recall."""

    def rerank(self, query: str, candidates: list[str], top_k: int) -> list[float]:
        """Return one relevance score per candidate for a query."""


class VectorStore(Protocol):
    """Vector persistence and retrieval contract."""

    def upsert_chunks(self, chunks: list[Chunk]) -> None:
        """Insert or update indexed chunks."""

    def search(self, query: str, project_id: str, limit: int = 5) -> list[Chunk]:
        """Search for the most relevant chunks in a project."""

    def search_documents(
        self,
        *,
        query_vector: list[float],
        project_id: str,
        vector_name: str = "summary",
        limit: int = 5,
    ) -> list[ScoredId]:
        """Search document-profile hits for one project."""

    def search_chunks(
        self,
        *,
        query_vector: list[float],
        project_id: str,
        vector_name: str = "content",
        document_ids: list[str] | None = None,
        limit: int = 5,
    ) -> list[ScoredId]:
        """Search chunk hits for one project, optionally scoped to candidate documents."""

    def search_assets(
        self,
        *,
        query_vector: list[float],
        project_id: str,
        vector_name: str = "summary",
        document_ids: list[str] | None = None,
        limit: int = 5,
    ) -> list[ScoredId]:
        """Search visual-asset hits for one project, optionally scoped to candidate documents."""

    def delete_by_document(self, document_id: str) -> None:
        """Delete indexed data related to one document."""


class ProjectRepository(Protocol):
    """Persistence contract for project metadata."""

    def create(self, project: Project) -> None:
        """Persist one project record."""

    def get_by_id(self, project_id: str) -> Project | None:
        """Load one project by identifier."""

    def list_all(self) -> list[Project]:
        """Return all stored projects."""

    def delete(self, project_id: str) -> None:
        """Delete one project by identifier."""


class DocumentRepository(Protocol):
    """Persistence contract for document metadata."""

    def upsert(self, document: Document) -> None:
        """Insert or update one document record."""

    def get_by_id(self, document_id: str) -> Document | None:
        """Load one document by identifier."""

    def get_by_path(self, project_id: str, path: str) -> Document | None:
        """Load one document by project and canonical path."""

    def get_by_content_hash(self, project_id: str, content_hash: str) -> Document | None:
        """Load one document by project and immutable content hash."""

    def list_by_project(self, project_id: str) -> list[Document]:
        """Return all documents that belong to one project."""

    def list_by_ids(self, document_ids: list[str]) -> list[Document]:
        """Return all matching documents for one id list."""

    def delete(self, document_id: str) -> None:
        """Delete one document record."""


class DocumentAssetRepository(Protocol):
    """Persistence contract for extracted visual assets."""

    def replace_for_document(self, document_id: str, assets: list[DocumentAsset]) -> None:
        """Replace all stored visual assets for one document."""

    def list_by_document(self, document_id: str) -> list[DocumentAsset]:
        """Return all extracted visual assets for one document."""

    def list_by_ids(self, asset_ids: list[str]) -> list[DocumentAsset]:
        """Return all matching visual assets for one id list."""

    def load_content(self, asset_id: str) -> tuple[str | None, bytes] | None:
        """Return one asset binary payload and media type."""

    def delete_by_document(self, document_id: str) -> None:
        """Delete all visual assets linked to one document."""


class ChunkRepository(Protocol):
    """Persistence contract for normalized text chunks."""

    def replace_for_document(self, document_id: str, chunks: list[Chunk]) -> None:
        """Replace all stored chunks for one document."""

    def list_by_document(self, document_id: str) -> list[Chunk]:
        """Return all chunks for one document."""

    def list_by_ids(self, chunk_ids: list[str]) -> list[Chunk]:
        """Return all matching chunks for one id list."""

    def delete_by_document(self, document_id: str) -> None:
        """Delete all chunks linked to one document."""


class DocumentParser(Protocol):
    """Document parsing contract for different file types."""

    def supports(self, path: Path) -> bool:
        """Return whether this parser supports the given path."""

    def parse(self, path: Path) -> Document:
        """Parse document metadata or content from a file path."""


class DocumentScanner(Protocol):
    """Project-level scanner that discovers supported source files."""

    def scan_project(self, project: Project) -> ScanSummary:
        """Scan one project root and return a structured summary."""


class PdfTextExtractor(Protocol):
    """PDF extraction contract focused on page-level text access."""

    def parse_pdf_metadata(self, path: Path) -> dict[str, object]:
        """Extract lightweight PDF metadata such as title and page count."""

    def extract_pdf_pages(self, path: Path) -> list[PdfPage]:
        """Extract normalized plain text content page by page."""


class ChunkBuilder(Protocol):
    """Contract for turning parsed document content into text chunks."""

    def build_chunks(self, document: Document, pages: list[PdfPage]) -> list[Chunk]:
        """Create normalized chunks suitable for later embedding."""


class MemoryStore(Protocol):
    """Long-term memory persistence and lookup contract."""

    def add(self, item: MemoryItem) -> None:
        """Store one memory item."""

    def remember_messages(
        self,
        *,
        project_id: str,
        messages: list[dict[str, str]],
        thread_id: str | None = None,
        memory_type: MemoryType | str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> list[MemoryItem]:
        """Store memories inferred from one short conversation snippet."""

    def search(self, query: str, project_id: str, limit: int = 5) -> list[MemoryItem]:
        """Search relevant memories for a project."""

    def summarize_for_project(self, project_id: str) -> str:
        """Return a compact memory summary for planner input."""


class WebSearchProvider(Protocol):
    """External web search interface."""

    def search(self, query: str, limit: int = 5) -> list[Chunk]:
        """Search the web and return normalized web chunks."""

    def fetch(self, url: str) -> Chunk:
        """Fetch one URL and return a normalized web chunk."""


class TaskPlanner(Protocol):
    """Planner interface for converting a user question into a task card."""

    def plan(self, question: str, project_summary: str, memory_summary: str) -> TaskCard:
        """Produce a planner task card for downstream agents."""


class AnswerWriter(Protocol):
    """Writer interface for turning evidence into an answer draft."""

    def write(self, question: str, evidence_pack: EvidencePack, output_format: str) -> str:
        """Write an answer, summary, or comparison table."""


class AnswerCritic(Protocol):
    """Critic interface for checking answer quality and citation coverage."""

    def review(self, question: str, draft: str, citations: list[Citation]) -> str:
        """Return a review result such as pass, revise, or retrieve_more."""

