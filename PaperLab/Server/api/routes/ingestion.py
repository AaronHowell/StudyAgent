from pathlib import Path

from fastapi import APIRouter, HTTPException

from api.dependencies import get_services
from api.schemas import (
    BatchIngestDocumentsRequest,
    BatchIngestDocumentsResponse,
    IngestDocumentRequest,
    IngestDocumentResponse,
    IngestionTaskSummary,
)

router = APIRouter()


def to_ingestion_task_summary(task_id: str) -> IngestionTaskSummary:
    """Convert one internal ingestion task into an API response model."""

    task = get_services().ingestion_task_manager.get(task_id)
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


@router.post("/documents/ingest", response_model=IngestDocumentResponse)
def ingest_document(payload: IngestDocumentRequest) -> IngestDocumentResponse:
    """Queue one local document for background ingestion."""

    document_path = Path(payload.path).expanduser().resolve()
    if not document_path.exists():
        raise HTTPException(status_code=404, detail=f"Document not found: {document_path}")

    task = get_services().ingestion_task_manager.submit(payload.project_id, document_path)
    return IngestDocumentResponse(task=to_ingestion_task_summary(task.id))


@router.get("/documents/ingest/{task_id}", response_model=IngestionTaskSummary)
def get_ingestion_task(task_id: str) -> IngestionTaskSummary:
    """Return current status for one background ingestion task."""

    return to_ingestion_task_summary(task_id)


@router.get("/documents/ingest", response_model=list[IngestionTaskSummary])
def list_ingestion_tasks() -> list[IngestionTaskSummary]:
    """Return recent ingestion tasks for the desktop UI."""

    return [to_ingestion_task_summary(task.id) for task in get_services().ingestion_task_manager.list_recent()]


@router.post("/documents/ingest/batch", response_model=BatchIngestDocumentsResponse)
def batch_ingest_documents(payload: BatchIngestDocumentsRequest) -> BatchIngestDocumentsResponse:
    """Queue multiple documents for background ingestion."""

    tasks = []
    for raw_path in payload.paths:
        document_path = Path(raw_path).expanduser().resolve()
        if not document_path.exists():
            continue
        task = get_services().ingestion_task_manager.submit(payload.project_id, document_path)
        tasks.append(to_ingestion_task_summary(task.id))

    return BatchIngestDocumentsResponse(tasks=tasks)
