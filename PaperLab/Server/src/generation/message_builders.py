"""Prompt and message builders for grounded PaperLab answers."""

from __future__ import annotations

import base64

from domain import EvidencePack
from generation.multimodal_context import MultimodalEvidenceContext


def build_grounded_answer_prompt(
    question: str,
    evidence_pack: EvidencePack,
    memory_summary: str = "",
) -> str:
    document_title_by_id = {hit.document_id: hit.title for hit in evidence_pack.documents}
    document_lines = [
        f"- {index + 1}. {hit.title} ({hit.path})"
        for index, hit in enumerate(evidence_pack.documents)
    ]
    chunk_lines = [
        (
            f"[C{index + 1}] {hit.text}\n"
            f"source: title=\"{document_title_by_id.get(hit.document_id, hit.document_id)}\" "
            f"page={hit.page} section={hit.section or ''}".strip()
        )
        for index, hit in enumerate(evidence_pack.text_chunks)
    ]
    asset_lines = [
        (
            f"[A{index + 1}] {hit.caption or hit.summary or hit.asset_label}\n"
            f"source: title=\"{document_title_by_id.get(hit.document_id, hit.document_id)}\" "
            f"page={hit.page_number}"
        )
        for index, hit in enumerate(evidence_pack.assets)
    ]
    return (
        "You are PaperLab. Answer only from the provided evidence.\n"
        "Rules:\n"
        "1. Do not invent facts not present in the evidence.\n"
        "2. Cite text evidence with [C1], [C2], and visual evidence with [A1], [A2].\n"
        "3. When a recalled visual is directly useful, place it in the answer with exactly <ref pic>A1</ref pic> using the matching visual evidence id.\n"
        "4. Visual evidence is recalled and shown to the user; use its caption/summary unless image blocks are explicitly provided.\n"
        "5. If evidence is insufficient, say so clearly.\n\n"
        f"Question:\n{question}\n\n"
        f"Relevant memory:\n{memory_summary or '- none'}\n\n"
        f"Candidate documents:\n{chr(10).join(document_lines) or '- none'}\n\n"
        f"Text evidence:\n{chr(10).join(chunk_lines) or '- none'}\n\n"
        f"Visual evidence:\n{chr(10).join(asset_lines) or '- none'}\n"
    )


def build_multimodal_answer_messages(
    context: MultimodalEvidenceContext,
    *,
    include_image_blocks: bool = False,
) -> list[dict[str, object]]:
    """Build OpenAI-compatible chat messages.

    ``include_image_blocks`` is off by default. The normal PaperLab flow recalls
    image assets for UI display and supplies only their metadata to the model.
    """

    text_prompt = _build_multimodal_text_prompt(context)
    system = {
        "role": "system",
        "content": (
            "You are PaperLab, a paper-grounded research assistant. "
            "Answer only from provided text and visual evidence. "
            "Use [C1] for text citations and [A1] for visual citations."
        ),
    }
    if not include_image_blocks:
        return [system, {"role": "user", "content": text_prompt}]

    user_content: list[dict[str, object]] = [{"type": "text", "text": text_prompt}]
    for item in context.image_items:
        if not item.image_bytes:
            continue
        encoded = base64.b64encode(item.image_bytes).decode("ascii")
        user_content.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{item.media_type};base64,{encoded}",
                    "detail": "auto",
                },
            }
        )
    return [system, {"role": "user", "content": user_content}]


def _build_multimodal_text_prompt(context: MultimodalEvidenceContext) -> str:
    text_evidence = "\n".join(
        (
            f'<chunk ref="{item.ref_id}" title="{item.document_title}" page="{item.page}">\n'
            f"{item.text}\n"
            "</chunk>"
        )
        for item in context.text_items
    )
    image_evidence = "\n".join(
        (
            f'<image ref="{item.ref_id}" asset_id="{item.asset_id}" title="{item.document_title}" page="{item.page}">\n'
            f"caption: {item.caption}\n"
            f"summary: {item.summary}\n"
            "</image>"
        )
        for item in context.image_items
    )
    return (
        f"<question>\n{context.question}\n</question>\n\n"
        f"<text_evidence>\n{text_evidence or '- none'}\n</text_evidence>\n\n"
        f"<image_evidence>\n{image_evidence or '- none'}\n</image_evidence>"
    )
