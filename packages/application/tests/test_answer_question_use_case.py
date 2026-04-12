from __future__ import annotations

import unittest

from study_agent_application.answer_question_use_case import AnswerQuestionUseCase
from study_agent_domain import (
    Chunk,
    ChunkHit,
    Citation,
    Document,
    DocumentHit,
    DocumentStatus,
    DocumentType,
    EvidencePack,
)


class StubRetrieveEvidenceUseCase:
    def retrieve(
        self,
        *,
        query: str,
        project_id: str,
        document_limit: int = 5,
        chunk_limit: int = 8,
        asset_limit: int = 6,
    ) -> EvidencePack:
        document = Document(
            id="doc-1",
            project_id=project_id,
            path="C:/docs/paper.pdf",
            file_name="paper.pdf",
            doc_type=DocumentType.PDF,
            title="Grounded Retrieval Paper",
            status=DocumentStatus.INDEXED,
            content_hash="hash-1",
        )
        chunk = Chunk(
            id="chunk-1",
            project_id=project_id,
            document_id=document.id,
            chunk_index=0,
            chunk_type="text",  # type: ignore[arg-type]
            text="Cross-encoder reranking improves evidence selection for grounded question answering.",
            page=3,
            section="Results",
        )
        return EvidencePack(
            query=query,
            documents=[DocumentHit(document=document, score=0.95)],
            text_chunks=[ChunkHit(chunk=chunk, score=0.88)],
            citations=[
                Citation(
                    document_id=document.id,
                    document_title=document.title,
                    chunk_id=chunk.id,
                    page=3,
                    locator="p.3",
                )
            ],
        )


class StubLLMProvider:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return "full answer"

    def stream_generate(self, prompt: str):
        self.prompts.append(prompt)
        yield "Grounded "
        yield "answer [1]"


class AnswerQuestionUseCaseTest(unittest.TestCase):
    def test_stream_answer_emits_answer_tokens_and_done_event(self) -> None:
        llm_provider = StubLLMProvider()
        use_case = AnswerQuestionUseCase(
            retrieve_evidence_use_case=StubRetrieveEvidenceUseCase(),
            llm_provider=llm_provider,
        )

        events = list(
            use_case.stream_answer(
                question="How does reranking help?",
                project_id="project-1",
            )
        )

        self.assertEqual(events[0].event, "meta")
        self.assertEqual(events[1].event, "delta")
        self.assertEqual(events[1].data["text"], "Grounded ")
        self.assertEqual(events[2].event, "delta")
        self.assertEqual(events[3].event, "done")
        self.assertEqual(events[3].data["answer"], "Grounded answer [1]")
        self.assertEqual(events[3].data["citations"][0]["locator"], "p.3")
        self.assertIn("Grounded Retrieval Paper", llm_provider.prompts[0])
        self.assertIn("Cross-encoder reranking improves evidence selection", llm_provider.prompts[0])


if __name__ == "__main__":
    unittest.main()
