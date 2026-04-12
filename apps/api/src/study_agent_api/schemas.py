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


class RetrieveEvidenceRequest(BaseModel):
    """Request payload for one retrieval run."""

    query: str = Field(..., description="Natural-language retrieval query")
    project_id: str = Field(..., description="Target project identifier")
    document_limit: int = Field(5, ge=1, le=20, description="Max document hits to return")
    chunk_limit: int = Field(8, ge=1, le=50, description="Max chunk hits to return")
    asset_limit: int = Field(6, ge=1, le=50, description="Max asset hits to return")


class RetrievalDocumentItem(BaseModel):
    """One scored document hit returned by the retrieval endpoint."""

    document_id: str
    score: float
    title: str
    file_name: str
    path: str
    status: str


class RetrievalChunkItem(BaseModel):
    """One scored chunk hit returned by the retrieval endpoint."""

    chunk_id: str
    document_id: str
    score: float
    chunk_index: int
    page: int | None = None
    section: str | None = None
    text: str


class RetrievalAssetItem(BaseModel):
    """One scored visual-asset hit returned by the retrieval endpoint."""

    asset_id: str
    document_id: str
    score: float
    page_number: int
    asset_label: str
    caption: str
    summary: str
    asset_type: str
    file_name: str
    file_path: str


class RetrievalCitationItem(BaseModel):
    """One citation emitted from retrieved chunk evidence."""

    document_id: str
    document_title: str
    chunk_id: str
    page: int | None = None
    locator: str = ""


class RetrievalEvidenceResponse(BaseModel):
    """Response payload for one evidence retrieval request."""

    query: str
    documents: list[RetrievalDocumentItem]
    text_chunks: list[RetrievalChunkItem]
    assets: list[RetrievalAssetItem]
    citations: list[RetrievalCitationItem]


class AgentAnswerStreamRequest(BaseModel):
    """Request payload for one streaming grounded-answer run."""

    question: str = Field(..., description="User question for grounded QA")
    project_id: str = Field(..., description="Target project identifier")
    document_limit: int = Field(5, ge=1, le=20)
    chunk_limit: int = Field(8, ge=1, le=50)
    asset_limit: int = Field(6, ge=1, le=50)
