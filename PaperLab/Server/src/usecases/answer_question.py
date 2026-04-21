"""Single-turn grounded QA orchestration with streaming output."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from domain import Citation, EvidencePack, LLMProvider
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
    def _build_prompt(
        question: str,
        evidence_pack: EvidencePack,
        memory_summary: str = "",
    ) -> str:
        """Build one grounded QA prompt from retrieved evidence."""
        return build_grounded_answer_prompt(question, evidence_pack, memory_summary)

    @staticmethod
    def _serialize_citation(citation: Citation) -> dict[str, object]:
        return {
            "document_id": citation.document_id,
            "document_title": citation.document_title,
            "chunk_id": citation.chunk_id,
            "page": citation.page,
            "locator": citation.locator,
        }

