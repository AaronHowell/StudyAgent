from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from study_agent_application.retrieve_evidence_use_case import RetrieveEvidenceUseCase
from study_agent_domain import (
    Chunk,
    ChunkType,
    Document,
    DocumentAsset,
    DocumentStatus,
    DocumentType,
    ScoredId,
)


class StubEmbeddingProvider:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        return [[0.1, 0.2, 0.3] for _ in texts]

    def embed_images(self, image_paths: list[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3] for _ in image_paths]


class StubVectorStore:
    def __init__(self) -> None:
        self.document_search_calls: list[dict[str, object]] = []
        self.chunk_search_calls: list[dict[str, object]] = []
        self.asset_search_calls: list[dict[str, object]] = []

    def search_documents(
        self,
        *,
        query_vector: list[float],
        project_id: str,
        vector_name: str = "summary",
        limit: int = 5,
    ) -> list[ScoredId]:
        self.document_search_calls.append(
            {
                "query_vector": query_vector,
                "project_id": project_id,
                "vector_name": vector_name,
                "limit": limit,
            }
        )
        if vector_name == "title":
            return [
                ScoredId(entity_id="doc-1", score=0.95),
                ScoredId(entity_id="doc-2", score=0.60),
            ]
        return [
            ScoredId(entity_id="doc-2", score=0.92),
            ScoredId(entity_id="doc-1", score=0.81),
        ]

    def search_chunks(
        self,
        *,
        query_vector: list[float],
        project_id: str,
        vector_name: str = "content",
        document_ids: list[str] | None = None,
        limit: int = 5,
    ) -> list[ScoredId]:
        self.chunk_search_calls.append(
            {
                "query_vector": query_vector,
                "project_id": project_id,
                "vector_name": vector_name,
                "document_ids": document_ids,
                "limit": limit,
            }
        )
        return [
            ScoredId(entity_id="chunk-2", score=0.76),
            ScoredId(entity_id="chunk-3", score=0.75),
            ScoredId(entity_id="chunk-1", score=0.50),
        ]

    def search_assets(
        self,
        *,
        query_vector: list[float],
        project_id: str,
        vector_name: str = "summary",
        document_ids: list[str] | None = None,
        limit: int = 5,
    ) -> list[ScoredId]:
        self.asset_search_calls.append(
            {
                "query_vector": query_vector,
                "project_id": project_id,
                "vector_name": vector_name,
                "document_ids": document_ids,
                "limit": limit,
            }
        )
        return [
            ScoredId(entity_id="asset-1", score=0.66),
            ScoredId(entity_id="asset-2", score=0.67),
        ]


class StubDocumentRepository:
    def list_by_ids(self, document_ids: list[str]) -> list[Document]:
        all_documents = {
            "doc-1": Document(
                id="doc-1",
                project_id="project-1",
                path="C:/docs/a.pdf",
                file_name="a.pdf",
                doc_type=DocumentType.PDF,
                title="Paper A",
                status=DocumentStatus.INDEXED,
                content_hash="hash-a",
            ),
            "doc-2": Document(
                id="doc-2",
                project_id="project-1",
                path="C:/docs/b.pdf",
                file_name="b.pdf",
                doc_type=DocumentType.PDF,
                title="Paper B",
                status=DocumentStatus.INDEXED,
                content_hash="hash-b",
            ),
        }
        return [all_documents[document_id] for document_id in document_ids if document_id in all_documents]


class StubChunkRepository:
    def list_by_ids(self, chunk_ids: list[str]) -> list[Chunk]:
        all_chunks = {
            "chunk-1": Chunk(
                id="chunk-1",
                project_id="project-1",
                document_id="doc-1",
                chunk_index=2,
                chunk_type=ChunkType.TEXT,
                text="Chunk evidence from paper A.",
                page=2,
                section="Method",
            ),
            "chunk-2": Chunk(
                id="chunk-2",
                project_id="project-1",
                document_id="doc-2",
                chunk_index=3,
                chunk_type=ChunkType.TEXT,
                text="Chunk evidence from paper B.",
                page=8,
                section="Results",
            ),
            "chunk-3": Chunk(
                id="chunk-3",
                project_id="project-1",
                document_id="doc-2",
                chunk_index=4,
                chunk_type=ChunkType.TEXT,
                text="Adjacent chunk evidence from paper B.",
                page=9,
                section="Results",
            ),
        }
        return [all_chunks[chunk_id] for chunk_id in chunk_ids if chunk_id in all_chunks]

    def list_by_document(self, document_id: str) -> list[Chunk]:
        chunks_by_document = {
            "doc-1": [
                Chunk(
                    id="chunk-0",
                    project_id="project-1",
                    document_id="doc-1",
                    chunk_index=1,
                    chunk_type=ChunkType.TEXT,
                    text="Previous context from paper A.",
                    page=1,
                    section="Method",
                ),
                Chunk(
                    id="chunk-1",
                    project_id="project-1",
                    document_id="doc-1",
                    chunk_index=2,
                    chunk_type=ChunkType.TEXT,
                    text="Chunk evidence from paper A.",
                    page=2,
                    section="Method",
                ),
                Chunk(
                    id="chunk-4",
                    project_id="project-1",
                    document_id="doc-1",
                    chunk_index=3,
                    chunk_type=ChunkType.TEXT,
                    text="Next context from paper A.",
                    page=3,
                    section="Method",
                ),
            ],
            "doc-2": [
                Chunk(
                    id="chunk-5",
                    project_id="project-1",
                    document_id="doc-2",
                    chunk_index=2,
                    chunk_type=ChunkType.TEXT,
                    text="Previous context from paper B.",
                    page=7,
                    section="Results",
                ),
                Chunk(
                    id="chunk-2",
                    project_id="project-1",
                    document_id="doc-2",
                    chunk_index=3,
                    chunk_type=ChunkType.TEXT,
                    text="Chunk evidence from paper B.",
                    page=8,
                    section="Results",
                ),
                Chunk(
                    id="chunk-3",
                    project_id="project-1",
                    document_id="doc-2",
                    chunk_index=4,
                    chunk_type=ChunkType.TEXT,
                    text="Adjacent chunk evidence from paper B.",
                    page=9,
                    section="Results",
                ),
            ],
        }
        return chunks_by_document.get(document_id, [])


class StubAssetRepository:
    def list_by_ids(self, asset_ids: list[str]) -> list[DocumentAsset]:
        all_assets = {
            "asset-1": DocumentAsset(
                id="asset-1",
                document_id="doc-2",
                page_number=9,
                file_path="C:/cache/figure1.png",
                file_name="figure1.png",
                asset_kind="figure",
                asset_label="Figure 1",
                asset_index=1,
                caption="Figure 1: Retrieval pipeline.",
                summary="Pipeline diagram.",
                asset_type="workflow_diagram",
                metadata={"project_id": "project-1"},
            ),
            "asset-2": DocumentAsset(
                id="asset-2",
                document_id="doc-2",
                page_number=9,
                file_path="C:/cache/figure2.png",
                file_name="figure2.png",
                asset_kind="figure",
                asset_label="",
                asset_index=2,
                caption="",
                summary="",
                asset_type="workflow_diagram",
                metadata={"project_id": "project-1"},
            )
        }
        return [all_assets[asset_id] for asset_id in asset_ids if asset_id in all_assets]


class StubRerankerProvider:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def rerank(self, query: str, candidates: list[str], top_k: int) -> list[float]:
        self.calls.append(
            {
                "query": query,
                "candidates": candidates,
                "top_k": top_k,
            }
        )
        scores_by_candidate = {
            "Paper A": 0.99,
            "Paper B": 0.70,
            "Chunk evidence from paper A.": 0.95,
            "Chunk evidence from paper B.": 0.80,
            "Adjacent chunk evidence from paper B.": 0.30,
            "Figure 1: Retrieval pipeline.": 0.88,
            "workflow_diagram": 0.10,
        }
        return [scores_by_candidate.get(candidate, 0.0) for candidate in candidates]

class RetrieveEvidenceUseCaseTest(unittest.TestCase):
    def test_builds_scored_evidence_pack(self) -> None:
        use_case = RetrieveEvidenceUseCase(
            embedding_provider=StubEmbeddingProvider(),
            vector_store=StubVectorStore(),
            document_repository=StubDocumentRepository(),
            chunk_repository=StubChunkRepository(),
            asset_repository=StubAssetRepository(),
            reranker_provider=StubRerankerProvider(),
        )

        result = use_case.retrieve(
            query="How does the retrieval pipeline work?",
            project_id="project-1",
            document_limit=2,
            chunk_limit=3,
            asset_limit=4,
        )

        self.assertEqual(result.query, "How does the retrieval pipeline work?")
        self.assertEqual([hit.document.id for hit in result.documents], ["doc-1", "doc-2"])
        self.assertGreater(result.documents[0].score, result.documents[1].score)
        self.assertEqual([hit.chunk.id for hit in result.text_chunks], ["chunk-1", "chunk-2"])
        self.assertEqual(result.text_chunks[0].page, 2)
        self.assertEqual([hit.asset.id for hit in result.assets], ["asset-1"])
        self.assertEqual(result.assets[0].asset_label, "Figure 1")
        self.assertEqual(result.citations[0].document_id, "doc-1")
        self.assertEqual(result.citations[0].locator, "p.2")

    def test_uses_candidate_documents_to_scope_chunk_and_asset_search(self) -> None:
        vector_store = StubVectorStore()
        use_case = RetrieveEvidenceUseCase(
            embedding_provider=StubEmbeddingProvider(),
            vector_store=vector_store,
            document_repository=StubDocumentRepository(),
            chunk_repository=StubChunkRepository(),
            asset_repository=StubAssetRepository(),
            reranker_provider=StubRerankerProvider(),
        )

        use_case.retrieve(
            query="retrieval",
            project_id="project-1",
            document_limit=2,
            chunk_limit=3,
            asset_limit=4,
        )

        self.assertEqual(vector_store.chunk_search_calls[0]["document_ids"], ["doc-1", "doc-2"])
        self.assertEqual(vector_store.asset_search_calls[0]["document_ids"], ["doc-1", "doc-2"])

    def test_writes_debug_log_as_jsonl(self) -> None:
        with TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "retrieval-debug.jsonl"
            use_case = RetrieveEvidenceUseCase(
                embedding_provider=StubEmbeddingProvider(),
                vector_store=StubVectorStore(),
                document_repository=StubDocumentRepository(),
                chunk_repository=StubChunkRepository(),
                asset_repository=StubAssetRepository(),
                reranker_provider=StubRerankerProvider(),
                debug_log_path=log_path,
            )

            use_case.retrieve(
                query="retrieval",
                project_id="project-1",
                document_limit=2,
                chunk_limit=3,
                asset_limit=4,
            )

            log_lines = log_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(log_lines), 1)
            self.assertIn('"query": "retrieval"', log_lines[0])
            self.assertIn('"raw_document_hits"', log_lines[0])
            self.assertIn('"reranked_document_hits"', log_lines[0])
            self.assertIn('"final_documents"', log_lines[0])

    def test_uses_reranker_top_k_controls(self) -> None:
        reranker = StubRerankerProvider()
        use_case = RetrieveEvidenceUseCase(
            embedding_provider=StubEmbeddingProvider(),
            vector_store=StubVectorStore(),
            document_repository=StubDocumentRepository(),
            chunk_repository=StubChunkRepository(),
            asset_repository=StubAssetRepository(),
            reranker_provider=reranker,
        )

        result = use_case.retrieve(
            query="retrieval",
            project_id="project-1",
            document_limit=1,
            chunk_limit=1,
            asset_limit=1,
        )

        self.assertEqual(len(result.documents), 1)
        self.assertEqual(len(result.text_chunks), 1)
        self.assertEqual(len(result.assets), 1)
        self.assertEqual(reranker.calls[0]["top_k"], 1)
        self.assertEqual(reranker.calls[1]["top_k"], 1)
        self.assertEqual(reranker.calls[2]["top_k"], 1)

    def test_chunk_rerank_uses_neighbor_window_text(self) -> None:
        reranker = StubRerankerProvider()
        use_case = RetrieveEvidenceUseCase(
            embedding_provider=StubEmbeddingProvider(),
            vector_store=StubVectorStore(),
            document_repository=StubDocumentRepository(),
            chunk_repository=StubChunkRepository(),
            asset_repository=StubAssetRepository(),
            reranker_provider=reranker,
            chunk_rerank_neighbor_window=1,
        )

        use_case.retrieve(
            query="retrieval",
            project_id="project-1",
            document_limit=2,
            chunk_limit=2,
            asset_limit=1,
        )

        chunk_rerank_candidates = reranker.calls[1]["candidates"]
        paper_a_window = next(
            candidate
            for candidate in chunk_rerank_candidates
            if "Chunk evidence from paper A." in candidate
        )
        self.assertIn("Previous context from paper A.", paper_a_window)
        self.assertIn("Chunk evidence from paper A.", paper_a_window)
        self.assertIn("Next context from paper A.", paper_a_window)


if __name__ == "__main__":
    unittest.main()
