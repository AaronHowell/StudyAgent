"""EvidencePack assembly helpers."""

from __future__ import annotations

from domain import AssetCitation, AssetHit, ChunkHit, Citation, DocumentHit, EvidencePack


def build_evidence_pack(
    *,
    query: str,
    document_hits: list[DocumentHit],
    chunk_hits: list[ChunkHit],
    asset_hits: list[AssetHit],
) -> EvidencePack:
    """Assemble text and visual evidence with stable citation ids."""

    document_title_by_id = {hit.document_id: hit.title for hit in document_hits}
    citations = [
        Citation(
            document_id=hit.document_id,
            document_title=document_title_by_id.get(hit.document_id, ""),
            chunk_id=hit.chunk_id,
            page=hit.page,
            locator=f"p.{hit.page}" if hit.page is not None else "",
        )
        for hit in chunk_hits
    ]
    asset_citations = [
        AssetCitation(
            asset_id=hit.asset_id,
            document_id=hit.document_id,
            document_title=document_title_by_id.get(hit.document_id, ""),
            page=hit.page_number,
            label=hit.asset_label or hit.file_name,
            locator=f"p.{hit.page_number}" if hit.page_number is not None else "",
        )
        for hit in asset_hits
    ]
    return EvidencePack(
        query=query,
        documents=document_hits,
        text_chunks=chunk_hits,
        assets=asset_hits,
        citations=citations,
        asset_citations=asset_citations,
    )
