"""Minimal FastAPI entrypoint for Step 1."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from urllib.parse import urlparse

from fastapi import FastAPI
from fastapi import HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import pymysql

from study_agent_application import IngestDocumentUseCase
from study_agent_documents import LocalDocumentScanner, PdfParser, TextChunkBuilder
from study_agent_domain import DocumentStatus, DocumentType
from study_agent_integrations import (
    MySQLChunkRepository,
    MySQLConnectionConfig,
    MySQLDocumentAssetRepository,
    MySQLDocumentRepository,
    OpenAICompatibleEmbeddingConfig,
    OpenAICompatibleEmbeddingProvider,
    QdrantChunkVectorStore,
    QdrantConnectionConfig,
)

from study_agent_api.config import Settings
from study_agent_api.ingestion import IngestionTaskManager
from study_agent_api.schemas import (
    BatchIngestDocumentsRequest,
    BatchIngestDocumentsResponse,
    DocumentImageItem,
    DocumentIngestionStatusRequest,
    DocumentIngestionStatusResponse,
    DocumentImagesRequest,
    DocumentImagesResponse,
    DocumentListItem,
    HealthResponse,
    IngestDocumentRequest,
    IngestDocumentResponse,
    IngestionTaskSummary,
    ScanDocumentsRequest,
    ScanDocumentsResponse,
)


settings = Settings.from_env()
app = FastAPI(title=settings.app_name)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

document_scanner = LocalDocumentScanner()
pdf_parser = PdfParser()
mysql_config = MySQLConnectionConfig(
    host=settings.mysql_host,
    port=settings.mysql_port,
    user=settings.mysql_user,
    password=settings.mysql_password,
    database=settings.mysql_database,
)
document_repository = MySQLDocumentRepository(
    mysql_config
)
asset_repository = MySQLDocumentAssetRepository(mysql_config)
chunk_repository = MySQLChunkRepository(mysql_config)
document_chunk_builder = TextChunkBuilder()
embedding_provider = None
vector_store = None

embedding_base_url = settings.embedding_base_url or settings.llm_base_url
embedding_api_key = settings.embedding_api_key or settings.llm_api_key
if settings.embedding_model and embedding_base_url:
    embedding_provider = OpenAICompatibleEmbeddingProvider(
        OpenAICompatibleEmbeddingConfig(
            base_url=embedding_base_url,
            api_key=embedding_api_key,
            model=settings.embedding_model,
            max_input_tokens=settings.embedding_max_input_tokens,
        )
    )

if settings.qdrant_url:
    parsed_qdrant_url = urlparse(settings.qdrant_url)
    vector_store = QdrantChunkVectorStore(
        QdrantConnectionConfig(
            url=settings.qdrant_url,
            host=parsed_qdrant_url.hostname or "127.0.0.1",
            port=parsed_qdrant_url.port or 6333,
            api_key=settings.qdrant_api_key,
            timeout_seconds=settings.qdrant_timeout_seconds,
        )
    )

ingest_document_use_case = IngestDocumentUseCase(
    document_repository=document_repository,
    asset_repository=asset_repository,
    chunk_repository=chunk_repository,
    pdf_parser=pdf_parser,
    chunk_builder=document_chunk_builder,
    embedding_provider=embedding_provider,
    vector_store=vector_store,
)
ingestion_task_manager = IngestionTaskManager(
    ingest_document_use_case,
    max_workers=settings.ingest_worker_count,
    task_timeout_seconds=settings.ingest_task_timeout_seconds,
)

document_repository.ensure_tables()
asset_repository.ensure_tables()
chunk_repository.ensure_tables()


def is_document_ingested(document_id: str) -> bool:
    """Return whether one document id already exists in MySQL.

    作用:
        为前端文档列表和单篇文档状态查询提供统一的入库判定逻辑。

    Args:
        document_id: 文档标识。

    Returns:
        bool: 若文档已存在于 `documents` 表则返回 `True`，否则返回 `False`。
    """

    try:
        return document_repository.get_by_id(document_id) is not None
    except pymysql.MySQLError:
        return False


def to_ingestion_task_summary(task_id: str) -> IngestionTaskSummary:
    """Convert one internal ingestion task into an API response model.

    Args:
        task_id: 任务标识。

    Returns:
        IngestionTaskSummary: 结构化任务摘要。

    Raises:
        HTTPException: 当任务不存在时抛出 404。
    """

    task = ingestion_task_manager.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Ingestion task not found: {task_id}")

    return IngestionTaskSummary(
        task_id=task.id,
        project_id=task.project_id,
        path=task.path,
        state=task.state,
        created_at=task.created_at,
        started_at=task.started_at,
        finished_at=task.finished_at,
        result=task.result,
        error_message=task.error_message,
        error_type=task.error_type,
        error_code=task.error_code,
        retryable=task.retryable,
        timed_out=task.timed_out,
    )


@app.on_event("shutdown")
def shutdown_task_manager() -> None:
    """Shutdown the in-process ingestion executor on API exit."""

    ingestion_task_manager.shutdown(wait=False)


@app.get("/healthz", response_model=HealthResponse)
def healthz() -> HealthResponse:
    """Return a minimal health payload for local smoke tests."""

    return HealthResponse(
        status="ok",
        service=settings.app_name,
        environment=settings.app_env,
    )


@app.post("/documents/scan", response_model=ScanDocumentsResponse)
def scan_documents(payload: ScanDocumentsRequest) -> ScanDocumentsResponse:
    """Scan a local folder and return discovered PDF documents."""

    root_path = Path(payload.root_path).expanduser().resolve()
    try:
        discovered_paths = document_scanner.scan_project_documents(root_path)
    except (FileNotFoundError, NotADirectoryError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    document_items: list[DocumentListItem] = []
    for path in discovered_paths:
        if path.suffix.lower() != ".pdf":
            continue

        try:
            document = document_scanner.build_document_record("frontend-project", path)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to build document record: {exc}") from exc

        modified_at = datetime.fromtimestamp(path.stat().st_mtime).isoformat()
        document_items.append(
            DocumentListItem(
                id=document.id,
                title=document.title,
                file_name=document.file_name,
                path=document.path,
                doc_type=document.doc_type.value,
                status=document.status.value,
                ingested=is_document_ingested(document.id),
                modified_at=modified_at,
                content_hash=document.content_hash,
            )
        )

    return ScanDocumentsResponse(root_path=str(root_path), documents=document_items)


@app.post("/documents/images", response_model=DocumentImagesResponse)
def get_document_images(payload: DocumentImagesRequest) -> DocumentImagesResponse:
    """Extract lightweight image information for one PDF document."""

    pdf_path = Path(payload.path).expanduser().resolve()
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail=f"Document not found: {pdf_path}")
    if pdf_path.suffix.lower() != ".pdf":
        raise HTTPException(status_code=400, detail="Only PDF documents are supported for image extraction.")

    document = document_scanner.build_document_record("frontend-project", pdf_path)
    document = type(document)(
        id=document.id,
        project_id=document.project_id,
        path=document.path,
        file_name=document.file_name,
        doc_type=DocumentType.PDF,
        title=document.title,
        status=DocumentStatus.DISCOVERED,
        content_hash=document.content_hash,
    )
    parse_result = pdf_parser.parse_pdf(document, include_images=True, export_image_files=True)

    image_items = [
        DocumentImageItem(
            id=image.id,
            document_id=image.document_id,
            page_number=image.page_number,
            file_name=image.file_name,
            file_path=image.file_path,
            file_url=f"/documents/file?path={quote(image.file_path)}" if image.file_path else "",
            asset_kind=image.asset_kind,
            asset_label=image.asset_label,
            asset_index=image.asset_index,
            figure_label=image.figure_label,
            figure_index=image.figure_index,
            caption=image.caption,
            summary=image.summary,
            asset_type=image.asset_type,
            keywords=image.keywords,
        )
        for image in parse_result.images
    ]

    return DocumentImagesResponse(path=str(pdf_path), images=image_items)


@app.post("/documents/ingestion-status", response_model=DocumentIngestionStatusResponse)
def get_document_ingestion_status(
    payload: DocumentIngestionStatusRequest,
) -> DocumentIngestionStatusResponse:
    """Check whether one local document has already been ingested.

    作用:
        根据文档路径构造稳定的文档 id，并查询该文档是否已存在于数据库中。

    Args:
        payload: 包含本地文档路径的请求体。

    Returns:
        DocumentIngestionStatusResponse: 当前文档的入库状态响应。
    """

    document_path = Path(payload.path).expanduser().resolve()
    if not document_path.exists():
        raise HTTPException(status_code=404, detail=f"Document not found: {document_path}")

    try:
        document = document_scanner.build_document_record("frontend-project", document_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to build document record: {exc}") from exc

    return DocumentIngestionStatusResponse(
        document_id=document.id,
        path=document.path,
        ingested=is_document_ingested(document.id),
    )


@app.post("/documents/ingest", response_model=IngestDocumentResponse)
def ingest_document(payload: IngestDocumentRequest) -> IngestDocumentResponse:
    """Queue one local document for background ingestion.

    作用:
        将入库流程放到后台线程池中执行，避免前端请求被长时间阻塞。

    Args:
        payload: 文档路径和目标项目的请求体。

    Returns:
        IngestDocumentResponse: 新建或复用的任务信息。
    """

    document_path = Path(payload.path).expanduser().resolve()
    if not document_path.exists():
        raise HTTPException(status_code=404, detail=f"Document not found: {document_path}")

    task = ingestion_task_manager.submit(payload.project_id, document_path)
    return IngestDocumentResponse(task=to_ingestion_task_summary(task.id))


@app.get("/documents/ingest/{task_id}", response_model=IngestionTaskSummary)
def get_ingestion_task(task_id: str) -> IngestionTaskSummary:
    """Return current status for one background ingestion task."""

    return to_ingestion_task_summary(task_id)


@app.get("/documents/ingest", response_model=list[IngestionTaskSummary])
def list_ingestion_tasks() -> list[IngestionTaskSummary]:
    """Return recent ingestion tasks for the desktop UI."""

    return [to_ingestion_task_summary(task.id) for task in ingestion_task_manager.list_recent()]


@app.post("/documents/ingest/batch", response_model=BatchIngestDocumentsResponse)
def batch_ingest_documents(payload: BatchIngestDocumentsRequest) -> BatchIngestDocumentsResponse:
    """Queue multiple documents for background ingestion.

    作用:
        为文档库页提供批量入库入口，适合同一项目下把多篇论文一起送入后台线程池。
    """

    tasks = []
    for raw_path in payload.paths:
        document_path = Path(raw_path).expanduser().resolve()
        if not document_path.exists():
            continue
        task = ingestion_task_manager.submit(payload.project_id, document_path)
        tasks.append(to_ingestion_task_summary(task.id))

    return BatchIngestDocumentsResponse(tasks=tasks)


@app.get("/documents/file")
def get_document_file(path: str = Query(..., description="Absolute path to a local file")) -> FileResponse:
    """Serve a local file for PDF preview or image preview."""

    target_path = Path(path).expanduser().resolve()
    if not target_path.exists() or not target_path.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {target_path}")
    return FileResponse(target_path)
