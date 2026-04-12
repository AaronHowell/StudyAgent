"""Single-turn grounded QA orchestration with streaming output."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from study_agent_domain import Citation, EvidencePack, LLMProvider


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
            },
        )

    @staticmethod
    def _build_prompt(question: str, evidence_pack: EvidencePack) -> str:
        """Build one grounded QA prompt from retrieved evidence."""

        document_lines = [
            f"- {index + 1}. {hit.title} ({hit.path})"
            for index, hit in enumerate(evidence_pack.documents)
        ]
        chunk_lines = [
            (
                f"[{index + 1}] {hit.text}\n"
                f"source: {hit.document_id} page={hit.page} section={hit.section or ''}".strip()
            )
            for index, hit in enumerate(evidence_pack.text_chunks)
        ]
        asset_lines = [
            (
                f"[A{index + 1}] {hit.caption or hit.summary or hit.asset_label}\n"
                f"source: {hit.document_id} page={hit.page_number}"
            )
            for index, hit in enumerate(evidence_pack.assets)
        ]

        return (
            "You are StudyAgent. Answer only from the provided evidence.\n"
            "Rules:\n"
            "1. Do not invent facts not present in the evidence.\n"
            "2. When making a factual claim, cite it with [n] using the chunk references.\n"
            "3. If evidence is insufficient, say so clearly.\n\n"
            f"Question:\n{question}\n\n"
            f"Candidate documents:\n{chr(10).join(document_lines) or '- none'}\n\n"
            f"Text evidence:\n{chr(10).join(chunk_lines) or '- none'}\n\n"
            f"Asset evidence:\n{chr(10).join(asset_lines) or '- none'}\n"
        )

    @staticmethod
    def _serialize_citation(citation: Citation) -> dict[str, object]:
        return {
            "document_id": citation.document_id,
            "document_title": citation.document_title,
            "chunk_id": citation.chunk_id,
            "page": citation.page,
            "locator": citation.locator,
        }
