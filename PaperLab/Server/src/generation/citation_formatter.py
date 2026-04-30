"""Citation formatting helpers for PaperLab answers."""

from __future__ import annotations

from domain import AssetCitation, Citation


def serialize_citation(citation: Citation) -> dict[str, object]:
    return {
        "document_id": citation.document_id,
        "document_title": citation.document_title,
        "chunk_id": citation.chunk_id,
        "page": citation.page,
        "locator": citation.locator,
    }


def serialize_asset_citation(citation: AssetCitation) -> dict[str, object]:
    return {
        "asset_id": citation.asset_id,
        "document_id": citation.document_id,
        "document_title": citation.document_title,
        "page": citation.page,
        "label": citation.label,
        "locator": citation.locator,
    }
