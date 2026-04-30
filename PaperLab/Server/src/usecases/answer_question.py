"""Single-turn grounded QA orchestration with streaming output."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote
from typing import Iterable

from domain import AssetCitation, Citation, EvidencePack, LLMProvider
from generation.citation_formatter import serialize_asset_citation, serialize_citation
from prompts.builders import build_grounded_answer_prompt


@dataclass(slots=True)
class AnswerStreamEvent:
    """One structured event emitted during answer streaming."""

    event: str
    data: dict[str, object]


class AnswerQuestionUseCase:
    """Minimal question-answer orchestration for grounded responses.

    作用:
        先检索证据，再将证据组织成 prompt，最后通过 LLM 流式生成回答。
    """

    def __init__(
        self,
        *,
        retrieve_evidence_use_case: object,
        llm_provider: LLMProvider,
    ) -> None:
        self.retrieve_evidence_use_case = retrieve_evidence_use_case
        self.llm_provider = llm_provider

    def stream_answer(
        self,
        *,
        question: str,
        project_id: str,
        document_limit: int = 5,
        chunk_limit: int = 8,
        asset_limit: int = 6,
    ) -> Iterable[AnswerStreamEvent]:
        """Stream one grounded answer from retrieval through generation."""

        evidence_pack = self.retrieve_evidence_use_case.retrieve(
            query=question,
            project_id=project_id,
            document_limit=document_limit,
            chunk_limit=chunk_limit,
            asset_limit=asset_limit,
        )
        prompt = self._build_prompt(question, evidence_pack)
        yield AnswerStreamEvent(
            event="meta",
            data={
                "question": question,
                "document_count": len(evidence_pack.documents),
                "chunk_count": len(evidence_pack.text_chunks),
                "asset_count": len(evidence_pack.assets),
                "multimodal": False,
                "visual_evidence_mode": "metadata",
            },
        )

        answer_parts: list[str] = []
        for delta in self.llm_provider.stream_generate(prompt):
            answer_parts.append(delta)
            yield AnswerStreamEvent(event="delta", data={"text": delta})

        final_answer = "".join(answer_parts)
        yield AnswerStreamEvent(
            event="done",
            data={
                "answer": final_answer,
                "citations": [self._serialize_citation(citation) for citation in evidence_pack.citations],
                "asset_citations": [
                    self._serialize_asset_citation(citation)
                    for citation in evidence_pack.asset_citations
                ],
                "asset_sources": [self._serialize_asset_source(hit) for hit in evidence_pack.assets],
            },
        )

    @staticmethod
    def _build_prompt(
        question: str,
        evidence_pack: EvidencePack,
        memory_summary: str = "",
    ) -> str:
        """Build one grounded QA prompt from retrieved evidence."""
        return build_grounded_answer_prompt(question, evidence_pack, memory_summary)

    @staticmethod
    def _serialize_citation(citation: Citation) -> dict[str, object]:
        return serialize_citation(citation)

    @staticmethod
    def _serialize_asset_citation(citation: AssetCitation) -> dict[str, object]:
        return serialize_asset_citation(citation)

    @staticmethod
    def _serialize_asset_source(hit) -> dict[str, object]:
        return {
            "asset_id": hit.asset_id,
            "document_id": hit.document_id,
            "page_number": hit.page_number,
            "asset_label": hit.asset_label,
            "caption": hit.caption,
            "summary": hit.summary,
            "asset_type": hit.asset_type,
            "file_name": hit.file_name,
            "file_url": f"/documents/assets/{quote(hit.asset_id)}/content",
        }

