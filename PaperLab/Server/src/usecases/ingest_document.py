"""Document ingestion use case implementation."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from typing import Any

from domain import (
    Chunk,
    ChunkBuilder,
    ChunkRepository,
    Document,
    DocumentAsset,
    DocumentAssetRepository,
    DocumentStatus,
    DocumentType,
    DocumentRepository,
    EmbeddingProvider,
    VectorStore,
)
from indexing.asset_indexer import AssetIndexer
from indexing.chunk_indexer import ChunkIndexer
from indexing.document_indexer import DocumentIndexer


@dataclass(slots=True)
class IngestDocumentResult:
    """Structured output of one ingestion run.

    作用:
        表示单篇文档完成解析、分块和持久化后的结果摘要，便于 API 或任务日志直接消费。
    """

    document: Document
    status: str = "indexed"
    message: str = ""
    assets: list[DocumentAsset] = field(default_factory=list)
    chunks: list[Chunk] = field(default_factory=list)


class IngestOutcome(StrEnum):
    """Stable outcome values returned by one ingestion run."""

    INDEXED = "indexed"
    SKIPPED = "skipped"
    UPDATED = "updated"
    FAILED = "failed"


class IngestDocumentUseCase:
    """Single-document ingestion flow coordinator.

    作用:
        把“解析文档 -> 生成视觉资产 -> 生成文本分块 -> 持久化 -> 写入向量索引”
        串成一个清晰的应用层用例。
    """

    def __init__(
        self,
        *,
        document_repository: DocumentRepository,
        asset_repository: DocumentAssetRepository,
        chunk_repository: ChunkRepository,
        pdf_parser: Any,
        chunk_builder: ChunkBuilder,
        embedding_provider: EmbeddingProvider | None = None,
        vector_store: VectorStore | None = None,
    ) -> None:
        """Create one ingestion use case with explicit dependencies.

        Args:
            document_repository: 文档元数据仓储。
            asset_repository: 视觉资产仓储。
            chunk_repository: 文本分块仓储。
            pdf_parser: PDF 解析器（需支持 `parse_pdf` 或 `extract_pdf_pages`）。
            chunk_builder: 文本分块器。
            embedding_provider: 可选嵌入模型适配器。
            vector_store: 可选向量存储适配器。
        """

        self.document_repository = document_repository
        self.asset_repository = asset_repository
        self.chunk_repository = chunk_repository
        self.pdf_parser = pdf_parser
        self.chunk_builder = chunk_builder
        self.embedding_provider = embedding_provider
        self.vector_store = vector_store

    def ingest(self, document: Document, *, export_assets: bool = False) -> IngestDocumentResult:
        """Run the ingestion pipeline for one document.

        作用:
            执行单篇 PDF 的完整摄取流程，并返回结构化结果。

        Args:
            document: 待摄取的文档对象。
            export_assets: 是否将视觉资产导出到文件系统缓存目录。

        Returns:
            IngestDocumentResult: 包含文档、视觉资产和分块的结果对象。

        Raises:
            RuntimeError: 当解析阶段出现不可恢复错误时抛出。
        """

        existing_document = None
        if hasattr(self.document_repository, "get_by_path"):
            existing_document = self.document_repository.get_by_path(
                document.project_id,
                document.path,
            )

        if (
            existing_document is not None
            and existing_document.content_hash == document.content_hash
            and existing_document.status == DocumentStatus.INDEXED
        ):
            return IngestDocumentResult(
                document=existing_document,
                status=IngestOutcome.SKIPPED,
                message="Document already ingested with the same content hash.",
                assets=self.asset_repository.list_by_document(existing_document.id),
                chunks=self.chunk_repository.list_by_document(existing_document.id),
            )

        try:
            if hasattr(self.pdf_parser, "parse_pdf"):
                parse_result = self.pdf_parser.parse_pdf(
                    document,
                    include_images=True,
                    export_image_files=export_assets,
                )
                pages = parse_result.pages
                assets = parse_result.images
            else:
                pages = self.pdf_parser.extract_pdf_pages(Path(document.path))
                assets = []

            chunks = self.chunk_builder.build_chunks(document, pages)

            if existing_document is not None and existing_document.id != document.id:
                self._delete_existing_document(existing_document.id)

            indexed_document = Document(
                id=document.id,
                project_id=document.project_id,
                path=document.path,
                file_name=document.file_name,
                doc_type=document.doc_type,
                title=document.title,
                status=DocumentStatus.INDEXED,
                content_hash=document.content_hash,
            )

            self.document_repository.upsert(indexed_document)
            self.asset_repository.replace_for_document(document.id, assets)
            self.chunk_repository.replace_for_document(document.id, chunks)

            if self.vector_store is not None and self.embedding_provider is not None:
                self._index_vectors(indexed_document, chunks, assets)

            return IngestDocumentResult(
                document=indexed_document,
                status=(
                    IngestOutcome.UPDATED
                    if existing_document is not None
                    else IngestOutcome.INDEXED
                ),
                message=(
                    "Document re-ingested after content change."
                    if existing_document is not None
                    else "Document ingested successfully."
                ),
                assets=assets,
                chunks=chunks,
            )
        except Exception as exc:  # noqa: BLE001 - surface original failure after marking state
            failed_document = Document(
                id=document.id,
                project_id=document.project_id,
                path=document.path,
                file_name=document.file_name,
                doc_type=document.doc_type,
                title=document.title,
                status=DocumentStatus.FAILED,
                content_hash=document.content_hash,
            )
            try:
                self.document_repository.upsert(failed_document)
            except Exception:
                pass
            raise RuntimeError(f"Failed to ingest document: {document.path}") from exc

    def ingest_from_path(self, project_id: str, path: Path) -> IngestDocumentResult:
        """Build one document object from a path and ingest it.

        作用:
            提供更贴近 API 的入口，后续可以在这里接文档扫描器或 title/hash 构建逻辑。

        Args:
            project_id: 所属项目标识。
            path: 文档路径。

        Returns:
            IngestDocumentResult: 摄取结果。

        Raises:
            FileNotFoundError: 当文件不存在时抛出。
            ValueError: 当文件类型不受支持时抛出。
        """

        resolved_path = path.expanduser().resolve()
        if not resolved_path.exists():
            raise FileNotFoundError(f"Document not found: {resolved_path}")

        suffix = resolved_path.suffix.lower()
        if suffix not in {".pdf", ".md", ".markdown"}:
            raise ValueError(f"Unsupported document type: {suffix}")

        content_hash = self._compute_content_hash(resolved_path)
        doc_type = DocumentType.PDF if suffix == ".pdf" else DocumentType.MARKDOWN
        title = resolved_path.stem
        if doc_type == DocumentType.PDF and hasattr(self.pdf_parser, "parse_pdf_metadata"):
            metadata = self.pdf_parser.parse_pdf_metadata(resolved_path)
            title = str(metadata.get("title") or title)

        document = Document(
            id=self._build_document_id(project_id, resolved_path, content_hash),
            project_id=project_id,
            path=str(resolved_path),
            file_name=resolved_path.name,
            doc_type=doc_type,
            title=title,
            status=DocumentStatus.DISCOVERED,
            content_hash=content_hash,
        )
        return self.ingest(document, export_assets=True)

    def _delete_existing_document(self, document_id: str) -> None:
        """Delete previously indexed data for one document before re-ingestion.

        Args:
            document_id: 待替换的旧文档标识。
        """

        self.chunk_repository.delete_by_document(document_id)
        self.asset_repository.delete_by_document(document_id)
        self.document_repository.delete(document_id)
        if self.vector_store is not None:
            if hasattr(self.vector_store, "delete_by_document"):
                self.vector_store.delete_by_document(document_id)
            if hasattr(self.vector_store, "delete_assets_by_document"):
                self.vector_store.delete_assets_by_document(document_id)
            if hasattr(self.vector_store, "delete_document_profile"):
                self.vector_store.delete_document_profile(document_id)

    def _index_vectors(
        self,
        document: Document,
        chunks: list[Chunk],
        assets: list[DocumentAsset],
    ) -> None:
        """Build embeddings and write document, chunk, and asset indexes.

        Args:
            document: 已入库文档。
            chunks: 文本分块列表。
            assets: 视觉资产列表。
        """

        document_indexer = DocumentIndexer(
            embedding_provider=self.embedding_provider,
            vector_store=self.vector_store,
        )
        profile = document_indexer.build_profile(document, chunks, assets)
        document_title_vectors = self.embedding_provider.embed_texts([profile.title])
        vector_size = len(document_title_vectors[0])

        if hasattr(self.vector_store, "ensure_chunk_collection"):
            self.vector_store.ensure_chunk_collection(
                content_vector_size=vector_size,
                title_vector_size=vector_size,
                summary_vector_size=vector_size,
            )
        document_indexer.index_profile(profile)

        ChunkIndexer(
            embedding_provider=self.embedding_provider,
            vector_store=self.vector_store,
        ).index_chunks(document=document, chunks=chunks)

        AssetIndexer(
            embedding_provider=self.embedding_provider,
            vector_store=self.vector_store,
        ).index_assets(assets)

    @staticmethod
    def _compute_content_hash(path: Path) -> str:
        """Compute a stable SHA-256 hash for a file path.

        Args:
            path: 目标文件路径。

        Returns:
            str: 计算后的十六进制摘要字符串。
        """

        hasher = sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1_048_576), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    @staticmethod
    def _build_document_id(project_id: str, path: Path, content_hash: str) -> str:
        """Build a stable document id from core identifiers.

        Args:
            project_id: 项目标识。
            path: 文档路径。
            content_hash: 文档内容摘要。

        Returns:
            str: 可复用的文档 id。
        """

        safe_name = path.stem.replace(" ", "_")
        return f"{project_id}:{safe_name}:{content_hash[:12]}"

