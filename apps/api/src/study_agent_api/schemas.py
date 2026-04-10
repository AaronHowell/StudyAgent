"""Pydantic schemas used by the API shell."""

from __future__ import annotations

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Response payload for the health check endpoint."""

    status: str = Field(..., description="Service health status")
    service: str = Field(..., description="Human-readable service name")
    environment: str = Field(..., description="Current application environment")


class ScanDocumentsRequest(BaseModel):
    """Request payload for scanning a local folder."""

    root_path: str = Field(..., description="Local folder path to scan")


class DocumentListItem(BaseModel):
    """One scanned document item returned to the frontend."""

    id: str
    title: str
    file_name: str
    path: str
    doc_type: str
    status: str
    ingested: bool = False
    modified_at: str
    content_hash: str


class ScanDocumentsResponse(BaseModel):
    """Response payload for scanned documents in one folder."""

    root_path: str
    documents: list[DocumentListItem]


class DocumentImagesRequest(BaseModel):
    """Request payload for extracting images from one document."""

    path: str = Field(..., description="Absolute path to one PDF document")


class DocumentImageItem(BaseModel):
    """One extracted image preview item."""

    id: str
    document_id: str
    page_number: int
    file_name: str
    file_path: str
    file_url: str
    asset_kind: str = "visual"
    asset_label: str = ""
    asset_index: int | None = None
    figure_label: str
    figure_index: int | None = None
    caption: str
    summary: str
    asset_type: str = "unknown"
    keywords: list[str]


class DocumentImagesResponse(BaseModel):
    """Response payload for extracted images of one PDF document."""

    path: str
    images: list[DocumentImageItem]


class DocumentIngestionStatusRequest(BaseModel):
    """Request payload for checking whether one document has been ingested."""

    path: str = Field(..., description="Absolute path to one local document")


class DocumentIngestionStatusResponse(BaseModel):
    """Response payload for one document ingestion-status query."""

    document_id: str
    path: str
    ingested: bool


class IngestDocumentRequest(BaseModel):
    """Request payload for scheduling ingestion of one local document."""

    project_id: str = Field(..., description="Target project identifier")
    path: str = Field(..., description="Absolute path to one local document")


class BatchIngestDocumentsRequest(BaseModel):
    """Request payload for scheduling multiple local documents at once."""

    project_id: str = Field(..., description="Target project identifier")
    paths: list[str] = Field(..., description="Absolute paths to local documents")


class IngestionTaskSummary(BaseModel):
    """One ingestion task status item returned to the frontend."""

    task_id: str
    project_id: str
    path: str
    state: str
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    result: dict[str, object] | None = None
    error_message: str = ""
    error_type: str = ""
    error_code: str = ""
    retryable: bool = False
    timed_out: bool = False


class IngestDocumentResponse(BaseModel):
    """Response payload for one queued ingestion request."""

    task: IngestionTaskSummary


class BatchIngestDocumentsResponse(BaseModel):
    """Response payload for one batch ingestion request."""

    tasks: list[IngestionTaskSummary]
