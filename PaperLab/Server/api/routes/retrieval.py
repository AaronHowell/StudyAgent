from fastapi import APIRouter, HTTPException

from api.dependencies import get_services
from api.schemas import (
    RetrievalAssetItem,
    RetrievalChunkItem,
    RetrievalCitationItem,
    RetrievalDocumentItem,
    RetrievalEvidenceResponse,
    RetrieveEvidenceRequest,
)

router = APIRouter()


@router.post("/retrieval/evidence", response_model=RetrievalEvidenceResponse)
def retrieve_evidence(payload: RetrieveEvidenceRequest) -> RetrievalEvidenceResponse:
    """Run document, chunk, and asset retrieval and return one evidence pack."""

    retrieve_evidence_use_case = get_services().retrieve_evidence_use_case
    if retrieve_evidence_use_case is None:
        raise HTTPException(
            status_code=503,
            detail="Retrieval is unavailable because embedding or vector store is not configured.",
        )

    evidence_pack = retrieve_evidence_use_case.retrieve(
        query=payload.query,
        project_id=payload.project_id,
        document_limit=payload.document_limit,
        chunk_limit=payload.chunk_limit,
        asset_limit=payload.asset_limit,
    )
    return RetrievalEvidenceResponse(
        query=evidence_pack.query,
        documents=[
            RetrievalDocumentItem(
                document_id=hit.document_id,
                score=hit.score,
                title=hit.title,
                file_name=hit.file_name,
                path=hit.path,
                status=hit.status,
            )
            for hit in evidence_pack.documents
        ],
        text_chunks=[
            RetrievalChunkItem(
                chunk_id=hit.chunk_id,
                document_id=hit.document_id,
                score=hit.score,
                chunk_index=hit.chunk_index,
                page=hit.page,
                section=hit.section,
                text=hit.text,
            )
            for hit in evidence_pack.text_chunks
        ],
        assets=[
            RetrievalAssetItem(
                asset_id=hit.asset_id,
                document_id=hit.document_id,
                score=hit.score,
                page_number=hit.page_number,
                asset_label=hit.asset_label,
                caption=hit.caption,
                summary=hit.summary,
                asset_type=hit.asset_type,
                file_name=hit.file_name,
                file_path=hit.file_path,
            )
            for hit in evidence_pack.assets
        ],
        citations=[
            RetrievalCitationItem(
                document_id=citation.document_id,
                document_title=citation.document_title,
                chunk_id=citation.chunk_id,
                page=citation.page,
                locator=citation.locator,
            )
            for citation in evidence_pack.citations
        ],
    )
