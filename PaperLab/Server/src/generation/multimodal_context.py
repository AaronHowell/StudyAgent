"""Build short-lived text and image evidence context for answer generation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from domain import EvidencePack


@dataclass(slots=True)
class TextEvidenceItem:
    ref_id: str
    chunk_id: str
    document_id: str
    page: int | None
    text: str


@dataclass(slots=True)
class ImageEvidenceItem:
    ref_id: str
    asset_id: str
    document_id: str
    page: int | None
    caption: str
    summary: str
    media_type: str
    image_bytes: bytes | None
    image_path: str | None


@dataclass(slots=True)
class MultimodalEvidenceContext:
    question: str
    text_items: list[TextEvidenceItem]
    image_items: list[ImageEvidenceItem]


def build_multimodal_context(
    *,
    question: str,
    evidence_pack: EvidencePack,
    asset_repository: object | None = None,
    max_images: int = 4,
    load_image_bytes: bool = False,
) -> MultimodalEvidenceContext:
    """Create answer context from retrieved evidence.

    By default this does not load image bytes. PaperLab first displays recalled
    visual evidence in the UI and gives the model caption/summary metadata.
    Vision-model image blocks can be enabled by setting ``load_image_bytes``.
    """

    text_items = [
        TextEvidenceItem(
            ref_id=f"C{index + 1}",
            chunk_id=hit.chunk_id,
            document_id=hit.document_id,
            page=hit.page,
            text=hit.text,
        )
        for index, hit in enumerate(evidence_pack.text_chunks)
    ]
    image_items = []
    for index, hit in enumerate(evidence_pack.assets[:max_images]):
        media_type = hit.asset.media_type or "application/octet-stream"
        image_bytes = None
        if load_image_bytes:
            image_bytes = _load_asset_bytes(hit.asset_id, hit.file_path, asset_repository)
        image_items.append(
            ImageEvidenceItem(
                ref_id=f"A{index + 1}",
                asset_id=hit.asset_id,
                document_id=hit.document_id,
                page=hit.page_number,
                caption=hit.caption,
                summary=hit.summary,
                media_type=media_type,
                image_bytes=image_bytes,
                image_path=hit.file_path or None,
            )
        )
    return MultimodalEvidenceContext(question=question, text_items=text_items, image_items=image_items)


def _load_asset_bytes(asset_id: str, file_path: str, asset_repository: object | None) -> bytes | None:
    if asset_repository is not None and hasattr(asset_repository, "load_content"):
        payload = asset_repository.load_content(asset_id)
        if payload is not None:
            return payload[1]
    if file_path:
        path = Path(file_path)
        if path.exists() and path.is_file():
            return path.read_bytes()
    return None
