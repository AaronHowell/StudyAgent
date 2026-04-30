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


class SelectProjectFolderRequest(BaseModel):
    """Request payload for opening a local folder picker."""

    current_path: str | None = Field(default=None, description="Current project path")


class SelectProjectFolderResponse(BaseModel):
    """Response payload for one local folder selection."""

    path: str = Field("", description="Selected absolute path, or empty when cancelled")


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
    preview_data_url: str = ""
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


class CreateReproductionRunRequest(BaseModel):
    project_id: str
    objective: str
    paper_ids: list[str] = Field(default_factory=list)
    permission_mode: str = "manual"


class CreateReproductionRunResponse(BaseModel):
    run_id: str
    status: str
    workspace_path: str
    report_path: str


class ReproductionRunResponse(BaseModel):
    run_id: str
    project_id: str
    objective: str
    status: str
    tasks: dict[str, dict[str, object]]
    artifacts: dict[str, dict[str, object]]
    workspace_path: str
    report_path: str
    error: str = ""


class ReproductionRunEventResponse(BaseModel):
    event_id: str
    event_type: str
    message: str
    payload: dict[str, object] = Field(default_factory=dict)
    created_at: str


class ChatMessageInput(BaseModel):
    """Frontend message item accepted by the chat bridge."""

    type: str = Field("human", description="LangChain-compatible message type")
    content: str = Field(..., description="User-visible message content")


class ChatStateUpdate(BaseModel):
    """State fragment applied before a resume command."""

    messages: list[ChatMessageInput] = Field(default_factory=list)


class ChatResumeCommand(BaseModel):
    """Opaque resume payload passed back into one interrupted graph."""

    action: str | None = None


class ChatCommandInput(BaseModel):
    """Frontend command payload used for guidance injection and resume."""

    update: ChatStateUpdate | None = None
    resume: dict[str, object] | ChatResumeCommand | None = None


class ChatRunRequest(BaseModel):
    """Request payload for one direct LangGraph-backed chat run."""

    project_id: str = Field(..., description="Target project identifier")
    thread_id: str = Field(..., description="Persistent graph thread identifier")
    input: dict[str, object] | None = Field(
        default=None,
        description="Initial graph input, typically {messages: [...]}",
    )
    command: ChatCommandInput | None = None


class ChatInterruptPayload(BaseModel):
    """Serializable interrupt record returned to the frontend."""

    id: str
    value: dict[str, object]


class ChatMessagePayload(BaseModel):
    """Serialized LangChain message returned to the desktop UI."""

    id: str | None = None
    type: str | None = None
    role: str | None = None
    content: object
    additional_kwargs: dict[str, object] = Field(default_factory=dict)
    response_metadata: dict[str, object] = Field(default_factory=dict)


class ChatStateResponse(BaseModel):
    """Thread snapshot returned by the FastAPI chat bridge."""

    thread_id: str
    project_id: str
    messages: list[ChatMessagePayload] = Field(default_factory=list)
    interrupt: ChatInterruptPayload | None = None
    next_nodes: list[str] = Field(default_factory=list)


class ChatTraceItemResponse(BaseModel):
    """One trace item attached to an assistant turn."""

    id: str
    kind: str
    title: str = ""
    text: str = ""
    status: str = "completed"
    created_at: str = ""


class ChatTurnResponse(BaseModel):
    """One user or assistant turn restored for the frontend."""

    id: str
    role: str
    created_at: str = ""
    content: str = ""
    answer_text: str = ""
    status: str = "completed"
    collapsed: bool = False
    summary: dict[str, str] = Field(default_factory=dict)
    citations: list[dict[str, object]] = Field(default_factory=list)
    asset_citations: list[dict[str, object]] = Field(default_factory=list)
    asset_sources: list[dict[str, object]] = Field(default_factory=list)
    web_sources: list[dict[str, object]] = Field(default_factory=list)
    tool_sources: list[dict[str, object]] = Field(default_factory=list)
    trace_items: list[ChatTraceItemResponse] = Field(default_factory=list)


class ChatSessionSnapshotResponse(BaseModel):
    """Complete session snapshot for restoring event-driven chat UIs."""

    session_id: str
    thread_id: str
    project_id: str
    turns: list[ChatTurnResponse] = Field(default_factory=list)
    interrupt: ChatInterruptPayload | None = None
    next_nodes: list[str] = Field(default_factory=list)
    checkpoint: dict[str, object] | None = None


class SessionSummaryResponse(BaseModel):
    """会话列表项。"""

    session_id: str
    project_id: str
    title: str
    updated_at: str
    message_count: int
    resume_capable: bool


class SessionRestoreResponse(ChatStateResponse):
    """恢复一个会话所需的完整响应。"""

    session_id: str
    checkpoint: dict[str, object] | None = None


class WorkerEventResponse(BaseModel):
    """独立 worker 日志项。"""

    event_id: str
    session_id: str
    project_id: str
    agent_id: str
    worker_type: str
    kind: str
    payload: dict[str, object] = Field(default_factory=dict)
    created_at: str
