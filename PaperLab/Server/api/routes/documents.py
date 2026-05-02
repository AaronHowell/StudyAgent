from __future__ import annotations

import base64
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import pymysql
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from api.dependencies import get_services
from api.schemas import (
    DocumentImageItem,
    DocumentImagesRequest,
    DocumentImagesResponse,
    DocumentIngestionStatusRequest,
    DocumentIngestionStatusResponse,
    DocumentListItem,
    ScanDocumentsRequest,
    ScanDocumentsResponse,
)
from domain import DocumentStatus, DocumentType

router = APIRouter()


def is_document_ingested(document_id: str) -> bool:
    """Return whether one document id already exists in MySQL."""

    try:
        return get_services().document_repository.get_by_id(document_id) is not None
    except pymysql.MySQLError:
        return False


@router.post("/documents/scan", response_model=ScanDocumentsResponse)
def scan_documents(payload: ScanDocumentsRequest) -> ScanDocumentsResponse:
    """Scan a local folder and return discovered PDF documents."""

    root_path = Path(payload.root_path).expanduser().resolve()
    try:
        discovered_paths = get_services().document_scanner.scan_project_documents(root_path)
    except (FileNotFoundError, NotADirectoryError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    document_items: list[DocumentListItem] = []
    for path in discovered_paths:
        if path.suffix.lower() != ".pdf":
            continue

        try:
            document = get_services().document_scanner.build_document_record("frontend-project", path)
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


@router.post("/documents/images", response_model=DocumentImagesResponse)
def get_document_images(payload: DocumentImagesRequest) -> DocumentImagesResponse:
    """Extract lightweight image information for one PDF document."""

    pdf_path = Path(payload.path).expanduser().resolve()
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail=f"Document not found: {pdf_path}")
    if pdf_path.suffix.lower() != ".pdf":
        raise HTTPException(status_code=400, detail="Only PDF documents are supported for image extraction.")

    services = get_services()
    document = services.document_scanner.build_document_record("frontend-project", pdf_path)
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
        document = get_services().document_scanner.build_document_record("frontend-project", document_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to build document record: {exc}") from exc

    return DocumentIngestionStatusResponse(
        document_id=document.id,
        path=document.path,
        ingested=is_document_ingested(document.id),
    )


@router.get("/documents/file")
def get_document_file(path: str = Query(..., description="Absolute path to a local file")) -> FileResponse:
    """Serve a local file for PDF preview or image preview. 为了让前端能够打开特定的PDF，把文件编辑编辑发一下给"""

    target_path = Path(path).expanduser().resolve()
    if not target_path.exists() or not target_path.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {target_path}")
    return FileResponse(target_path)
