from __future__ import annotations

from domain import Citation
from domain import EvidencePack
from domain import MemoryItem


def build_assistant_metadata(citations: list[Citation]) -> dict[str, object]:
    return {
        "citations": [
            {
                "document_id": citation.document_id,
                "document_title": citation.document_title,
                "chunk_id": citation.chunk_id,
                "page": citation.page,
                "locator": citation.locator,
            }
            for citation in citations
        ]
    }


def serialize_memory_item(item: MemoryItem) -> dict[str, object]:
    return {
        "id": item.id,
        "content": item.content,
        "memory_type": item.memory_type.value,
        "importance": item.importance,
        "metadata": item.metadata,
    }


def serialize_evidence_pack(evidence_pack: EvidencePack) -> dict[str, object]:
    return {
        "documents": [
            {
                "id": getattr(document, "id", getattr(document, "document_id", "")),
                "project_id": getattr(document, "project_id", getattr(getattr(document, "document", None), "project_id", "")),
                "title": getattr(document, "title", ""),
                "summary": getattr(document, "summary", ""),
                "source_path": getattr(document, "source_path", getattr(document, "path", "")),
            }
            for document in evidence_pack.documents
        ],
        "text_chunks": [
            {
                "id": getattr(chunk, "id", getattr(chunk, "chunk_id", "")),
                "document_id": getattr(chunk, "document_id", ""),
                "page_start": getattr(chunk, "page_start", getattr(chunk, "page", None)),
                "page_end": getattr(chunk, "page_end", getattr(chunk, "page", None)),
                "section": getattr(chunk, "section", None),
                "content": getattr(chunk, "content", getattr(chunk, "text", "")),
            }
            for chunk in evidence_pack.text_chunks
        ],
        "assets": [
            {
                "id": getattr(asset, "id", getattr(asset, "asset_id", "")),
                "document_id": getattr(asset, "document_id", ""),
                "page": getattr(asset, "page", getattr(asset, "page_number", None)),
                "label": getattr(asset, "label", getattr(asset, "asset_label", "")),
                "summary": getattr(asset, "summary", ""),
                "caption": getattr(asset, "caption", ""),
            }
            for asset in evidence_pack.assets
        ],
    }


def build_evidence_counts(evidence_pack: EvidencePack) -> dict[str, int]:
    return {
        "document_count": len(evidence_pack.documents),
        "chunk_count": len(evidence_pack.text_chunks),
        "asset_count": len(evidence_pack.assets),
    }


def _serialize_memory_item(item: MemoryItem) -> dict[str, object]:
    return serialize_memory_item(item)


def _serialize_evidence_pack(evidence_pack: EvidencePack) -> dict[str, object]:
    return serialize_evidence_pack(evidence_pack)


def _build_evidence_counts(evidence_pack: EvidencePack) -> dict[str, int]:
    return build_evidence_counts(evidence_pack)
