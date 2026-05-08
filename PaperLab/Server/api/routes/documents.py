from __future__ import annotations

import base64
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

import pymysql
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from api.dependencies import _build_pdf_parser, settings
from api.dependencies import get_services
from api.schemas import (
    DocumentImageItem,
    DocumentImagesRequest,
    DocumentImagesResponse,
    DocumentIngestionStatusRequest,
    DocumentIngestionStatusResponse,
    DocumentListItem,
    RefreshDocumentMetadataRequest,
    RefreshDocumentMetadataResponse,
    ScanDocumentsRequest,
    ScanDocumentsResponse,
)
from configs import DEFAULT_PROJECT_ID
from documents import DocumentScanOptions, LocalDocumentScanner, PdfParser
from domain import Document, DocumentStatus, DocumentType
from integrations import MySQLConnectionConfig, MySQLDocumentRepository

router = APIRouter()


@lru_cache(maxsize=1)
def get_scan_document_scanner() -> LocalDocumentScanner:
    """Return the lightweight scanner used by the desktop paper list."""

    return LocalDocumentScanner(pdf_parser=PdfParser())


@lru_cache(maxsize=1)
def get_llm_metadata_scanner() -> LocalDocumentScanner:
    """Return a scanner whose PDF parser may call the configured LLM."""

    return LocalDocumentScanner(
        options=DocumentScanOptions(use_llm_metadata=True),
        pdf_parser=_build_pdf_parser(settings),
    )


@lru_cache(maxsize=1)
def get_scan_document_repository() -> MySQLDocumentRepository:
    """Return the lightweight document repository used by scan endpoints."""

    mysql_config = MySQLConnectionConfig(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_user,
        password=settings.mysql_password,
        database=settings.mysql_database,
    )
    repository = MySQLDocumentRepository(mysql_config)
    repository.ensure_tables()
    return repository


def load_stored_document(project_id: str, content_hash: str) -> Document | None:
    """Best-effort load of a document row without initializing heavy services."""

    try:
        return get_scan_document_repository().get_by_content_hash(project_id, content_hash)
    except (pymysql.MySQLError, RuntimeError):
        return None


def save_document_row(document: Document) -> None:
    """Best-effort document-row persistence for manual metadata refreshes."""

    try:
        get_scan_document_repository().upsert(document)
    except (pymysql.MySQLError, RuntimeError):
        return


def is_document_ingested(document_id: str, *, initialize_services: bool = False) -> bool:
    """Return whether one document id already exists in MySQL."""

    cache_info = getattr(get_services, "cache_info", None)
    if not initialize_services and (not callable(cache_info) or cache_info().currsize == 0):
        try:
            document = get_scan_document_repository().get_by_id(document_id)
        except (pymysql.MySQLError, RuntimeError):
            return False
        return document is not None and document.status == DocumentStatus.INDEXED
    try:
        document = get_services().document_repository.get_by_id(document_id)
        return document is not None and document.status == DocumentStatus.INDEXED
    except pymysql.MySQLError:
        return False


def resolve_project_id(project_id: str | None) -> str:
    """Return the request project id or the shared application default."""

    return (project_id or "").strip() or DEFAULT_PROJECT_ID


def build_document_list_item(
    document: Document,
    path: Path,
    *,
    metadata_source: str = "pdf",
    metadata_cached: bool = False,
) -> DocumentListItem:
    """Build one API list item from a scanned document plus metadata cache state."""

    return DocumentListItem(
        id=document.id,
        title=document.title,
        file_name=document.file_name,
        path=document.path,
        doc_type=document.doc_type.value,
        status=document.status.value,
        ingested=is_document_ingested(document.id),
        modified_at=datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
        content_hash=document.content_hash,
        metadata_source=metadata_source,
        metadata_cached=metadata_cached,
    )


@router.post("/documents/scan", response_model=ScanDocumentsResponse)
def scan_documents(payload: ScanDocumentsRequest) -> ScanDocumentsResponse:
    """Scan a local folder and return discovered PDF documents."""

    root_path = Path(payload.root_path).expanduser().resolve()
    project_id = resolve_project_id(payload.project_id)
    scanner = get_scan_document_scanner()
    try:
        discovered_paths = scanner.scan_project_documents(root_path)
    except (FileNotFoundError, NotADirectoryError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    document_items: list[DocumentListItem] = []
    for path in discovered_paths:
        if path.suffix.lower() != ".pdf":
            continue

        try:
            document = scanner.build_document_record(project_id, path)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to build document record: {exc}") from exc

        stored_document = load_stored_document(project_id, document.content_hash)
        llm_title = stored_document.llm_title.strip() if stored_document is not None else ""
        if llm_title:
            document = type(document)(
                id=document.id,
                project_id=document.project_id,
                path=document.path,
                file_name=document.file_name,
                doc_type=document.doc_type,
                title=llm_title,
                status=document.status,
                content_hash=document.content_hash,
                llm_title=llm_title,
                llm_metadata=dict(stored_document.llm_metadata),
            )
        document_items.append(
            build_document_list_item(
                document,
                path,
                metadata_source="llm" if llm_title else "pdf",
                metadata_cached=bool(llm_title),
            )
        )

    return ScanDocumentsResponse(root_path=str(root_path), documents=document_items)


@router.post("/documents/images", response_model=DocumentImagesResponse)
def get_document_images(payload: DocumentImagesRequest) -> DocumentImagesResponse:
    """Extract lightweight image information for one PDF document."""

    pdf_path = Path(payload.path).expanduser().resolve()
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail=f"Document not found: {pdf_path}")
    if pdf_path.suffix.lower() != ".pdf":
        raise HTTPException(status_code=400, detail="Only PDF documents are supported for image extraction.")

    services = get_services()
    project_id = resolve_project_id(payload.project_id)
    document = services.document_scanner.build_document_record(project_id, pdf_path)
    stored_document = services.document_repository.get_by_id(document.id)
    if stored_document is not None:
        images = services.asset_repository.list_by_document(stored_document.id)
    else:
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
        parse_result = services.pdf_parser.parse_pdf(
            document,
            include_images=True,
            export_image_files=False,
        )
        images = parse_result.images

    image_items = []
    for image in images:
        preview_data_url = ""
        if image.content_bytes:
            encoded = base64.b64encode(image.content_bytes).decode("ascii")
            preview_data_url = f"data:{image.media_type or 'application/octet-stream'};base64,{encoded}"
        image_items.append(
            DocumentImageItem(
                id=image.id,
                document_id=image.document_id,
                page_number=image.page_number,
                file_name=image.file_name,
                file_path=image.file_path,
                file_url=f"/documents/assets/{quote(image.id)}/content",
                preview_data_url=preview_data_url,
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
        )

    return DocumentImagesResponse(path=str(pdf_path), images=image_items)


@router.post("/documents/ingestion-status", response_model=DocumentIngestionStatusResponse)
def get_document_ingestion_status(
    payload: DocumentIngestionStatusRequest,
) -> DocumentIngestionStatusResponse:
    """Check whether one local document has already been ingested."""

    document_path = Path(payload.path).expanduser().resolve()
    if not document_path.exists():
        raise HTTPException(status_code=404, detail=f"Document not found: {document_path}")

    try:
        document = get_services().document_scanner.build_document_record(
            resolve_project_id(payload.project_id),
            document_path,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to build document record: {exc}") from exc

    return DocumentIngestionStatusResponse(
        document_id=document.id,
        path=document.path,
        ingested=is_document_ingested(document.id, initialize_services=True),
    )


@router.post("/documents/metadata/refresh", response_model=RefreshDocumentMetadataResponse)
def refresh_document_metadata(payload: RefreshDocumentMetadataRequest) -> RefreshDocumentMetadataResponse:
    """Reparse one PDF's metadata with the configured LLM when available."""

    pdf_path = Path(payload.path).expanduser().resolve()
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail=f"Document not found: {pdf_path}")
    if pdf_path.suffix.lower() != ".pdf":
        raise HTTPException(status_code=400, detail="Only PDF documents are supported for metadata refresh.")

    project_id = resolve_project_id(payload.project_id)
    try:
        base_document = get_scan_document_scanner().build_document_record(project_id, pdf_path)
        llm_document = get_llm_metadata_scanner().build_document_record(project_id, pdf_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to refresh document metadata: {exc}") from exc

    existing_document = load_stored_document(project_id, base_document.content_hash)
    stored_document = Document(
        id=base_document.id,
        project_id=base_document.project_id,
        path=base_document.path,
        file_name=base_document.file_name,
        doc_type=base_document.doc_type,
        title=base_document.title,
        status=existing_document.status if existing_document is not None else DocumentStatus.DISCOVERED,
        content_hash=base_document.content_hash,
        llm_title=llm_document.title,
        llm_metadata={"title": llm_document.title},
    )
    save_document_row(stored_document)

    response_document = Document(
        id=base_document.id,
        project_id=base_document.project_id,
        path=base_document.path,
        file_name=base_document.file_name,
        doc_type=base_document.doc_type,
        title=llm_document.title,
        status=stored_document.status,
        content_hash=base_document.content_hash,
        llm_title=llm_document.title,
        llm_metadata=dict(stored_document.llm_metadata),
    )

    return RefreshDocumentMetadataResponse(
        document=build_document_list_item(
            response_document,
            pdf_path,
            metadata_source="llm",
            metadata_cached=True,
        )
    )


@router.get("/documents/file")
def get_document_file(path: str = Query(..., description="Absolute path to a local file")) -> FileResponse:
    """Serve a local file for PDF preview or image preview. 为了让前端能够打开特定的PDF，把文件编辑编辑发一下给"""

    target_path = Path(path).expanduser().resolve()
    if not target_path.exists() or not target_path.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {target_path}")
    return FileResponse(target_path)
