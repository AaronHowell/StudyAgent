from __future__ import annotations

from dataclasses import dataclass

from domain import AssetHit, Chunk, ChunkType, Document, DocumentAsset, DocumentStatus, DocumentType, ScoredId
from usecases.answer_question import AnswerQuestionUseCase


class FakeEmbeddingProvider:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[float(index + 1), 0.0] for index, _ in enumerate(texts)]

    def embed_images(self, image_paths: list[str]) -> list[list[float]]:
        return [[0.0, float(index + 1)] for index, _ in enumerate(image_paths)]


class FakeAssetVectorStore:
    def __init__(self) -> None:
        self.ensure_asset_args: dict[str, int | None] = {}
        self.upsert_payload: dict[str, object] = {}

    def ensure_asset_collection(
        self,
        *,
        caption_vector_size: int,
        summary_vector_size: int,
        image_vector_size: int | None = None,
    ) -> None:
        self.ensure_asset_args = {
            "caption_vector_size": caption_vector_size,
            "summary_vector_size": summary_vector_size,
            "image_vector_size": image_vector_size,
        }

    def upsert_assets(
        self,
        *,
        assets: list[DocumentAsset],
        caption_vectors: list[list[float]],
        summary_vectors: list[list[float]],
        image_vectors: list[list[float]] | None = None,
    ) -> None:
        self.upsert_payload = {
            "assets": assets,
            "caption_vectors": caption_vectors,
            "summary_vectors": summary_vectors,
            "image_vectors": image_vectors,
        }


def test_asset_indexer_skips_image_vectors_by_default(tmp_path) -> None:
    from indexing.asset_indexer import AssetIndexer

    image_path = tmp_path / "figure.png"
    image_path.write_bytes(b"fake-image")
    asset = DocumentAsset(
        id="asset-1",
        document_id="doc-1",
        page_number=1,
        file_path=str(image_path),
        file_name="figure.png",
        caption="Caption text",
        summary="Summary text",
        metadata={"project_id": "project-1"},
    )
    vector_store = FakeAssetVectorStore()

    AssetIndexer(
        embedding_provider=FakeEmbeddingProvider(),
        vector_store=vector_store,
    ).index_assets([asset])

    assert vector_store.ensure_asset_args["image_vector_size"] is None
    assert vector_store.upsert_payload["image_vectors"] is None


def test_asset_indexer_writes_image_vectors_when_multimodal_embedding_enabled(tmp_path) -> None:
    from indexing.asset_indexer import AssetIndexer

    image_path = tmp_path / "figure.png"
    image_path.write_bytes(b"fake-image")
    asset = DocumentAsset(
        id="asset-1",
        document_id="doc-1",
        page_number=1,
        file_path=str(image_path),
        file_name="figure.png",
        caption="Caption text",
        summary="Summary text",
        metadata={"project_id": "project-1"},
    )
    vector_store = FakeAssetVectorStore()

    AssetIndexer(
        embedding_provider=FakeEmbeddingProvider(),
        vector_store=vector_store,
        multimodal_embedding_enabled=True,
    ).index_assets([asset])

    assert vector_store.ensure_asset_args["image_vector_size"] == 2
    assert vector_store.upsert_payload["image_vectors"] == [[0.0, 1.0]]


def test_retrieve_assets_fuses_summary_and_caption_hits() -> None:
    from usecases.retrieve_evidence import RetrieveEvidenceUseCase

    asset_summary = _asset("asset-summary", "Summary hit", "Weak caption")
    asset_caption = _asset("asset-caption", "Weak summary", "Caption hit")
    use_case = RetrieveEvidenceUseCase(
        embedding_provider=FakeEmbeddingProvider(),
        vector_store=FakeRetrievalVectorStore(),
        document_repository=FakeDocumentRepository(),
        chunk_repository=FakeChunkRepository(),
        asset_repository=FakeAssetRepository([asset_summary, asset_caption]),
    )

    hits, raw_log = use_case.retrieve_assets(
        query="caption",
        project_id="project-1",
        document_ids=["doc-1"],
        query_vector=[1.0, 0.0],
        limit=2,
    )

    assert [hit.asset_id for hit in hits] == ["asset-caption", "asset-summary"]
    assert "caption" in raw_log
    assert "summary" in raw_log


def test_retrieve_assets_filters_low_value_images_and_uses_rich_rerank_text() -> None:
    from usecases.retrieve_evidence import RetrieveEvidenceUseCase

    informative = _asset(
        "asset-informative",
        "Overview diagram for the Tracer patch tracking pipeline.",
        "Figure 2: Tracer workflow overview.",
        asset_type="workflow_diagram",
    )
    low_value = _asset(
        "asset-low",
        "Title and author information from the academic paper.",
        "",
        asset_type="unknown",
        asset_label="page_0001_image_001.png",
        file_name="page_0001_image_001.png",
        page_number=1,
    )
    reranker = FakeRerankerProvider()
    use_case = RetrieveEvidenceUseCase(
        embedding_provider=FakeEmbeddingProvider(),
        vector_store=FakeFilteredRetrievalVectorStore(),
        document_repository=FakeDocumentRepository(),
        chunk_repository=FakeChunkRepository(),
        asset_repository=FakeAssetRepository([informative, low_value]),
        reranker_provider=reranker,
    )

    hits, _ = use_case.retrieve_assets(
        query="explain the tracer workflow figure",
        project_id="project-1",
        document_ids=["doc-1"],
        query_vector=[1.0, 0.0],
        limit=2,
    )

    assert [hit.asset_id for hit in hits] == ["asset-informative"]
    assert len(reranker.calls) == 1
    assert "label: Figure asset-informative" in reranker.calls[0]["candidates"][0]
    assert "asset_type: workflow_diagram" in reranker.calls[0]["candidates"][0]
    assert "summary: Overview diagram for the Tracer patch tracking pipeline." in reranker.calls[0]["candidates"][0]


def test_answer_done_event_contains_displayable_asset_sources() -> None:
    asset = _asset("asset-1", "Figure summary", "Figure caption")
    evidence_pack = FakeEvidencePack(asset)
    use_case = AnswerQuestionUseCase(
        retrieve_evidence_use_case=FakeAnswerRetriever(evidence_pack),
        llm_provider=FakeStreamingLLM(),
    )

    events = list(
        use_case.stream_answer(
            question="What is shown?",
            project_id="project-1",
        )
    )
    done = events[-1]

    assert done.event == "done"
    assert done.data["asset_sources"][0]["asset_id"] == "asset-1"
    assert done.data["asset_sources"][0]["ref_id"] == "A1"
    assert done.data["asset_sources"][0]["file_url"] == "/documents/assets/asset-1/content"


def test_grounded_answer_prompt_allows_inline_picture_references() -> None:
    from prompts.builders import build_grounded_answer_prompt

    asset = _asset("asset-1", "Figure summary", "Figure caption")
    prompt = build_grounded_answer_prompt("What is shown?", FakeEvidencePack(asset))

    assert "<ref pic>A1</ref pic>" in prompt
    assert "[A1] Figure caption" in prompt


def test_document_profile_uses_metadata_summary_and_keywords() -> None:
    from indexing.document_indexer import DocumentIndexer

    document = Document(
        id="doc-1",
        project_id="project-1",
        path="C:/paper.pdf",
        file_name="paper.pdf",
        doc_type=DocumentType.PDF,
        title="Paper Title",
        status=DocumentStatus.DISCOVERED,
        content_hash="hash",
    )
    chunks = [
        Chunk(
            id="chunk-1",
            document_id="doc-1",
            project_id="project-1",
            chunk_index=0,
            chunk_type=ChunkType.TEXT,
            text="Long chunk fallback text that should not become the profile summary.",
        )
    ]

    profile = DocumentIndexer(
        embedding_provider=FakeEmbeddingProvider(),
        vector_store=FakeAssetVectorStore(),
    ).build_profile(
        document,
        chunks,
        assets=[],
        metadata={
            "summary": "Short LLM paper summary.",
            "keywords": ["metadata", "retrieval"],
            "authors": ["Alice Example"],
            "year": 2026,
        },
    )

    assert profile.summary == "Short LLM paper summary."
    assert profile.keywords[:2] == ["metadata", "retrieval"]
    assert profile.metadata["authors"] == ["Alice Example"]
    assert profile.metadata["year"] == 2026


def _asset(
    asset_id: str,
    summary: str,
    caption: str,
    *,
    asset_type: str = "unknown",
    asset_label: str | None = None,
    file_name: str | None = None,
    page_number: int = 2,
) -> DocumentAsset:
    return DocumentAsset(
        id=asset_id,
        document_id="doc-1",
        page_number=page_number,
        file_path=f"C:/{asset_id}.png",
        file_name=file_name or f"{asset_id}.png",
        asset_label=asset_label or f"Figure {asset_id}",
        caption=caption,
        summary=summary,
        asset_type=asset_type,
        media_type="image/png",
        metadata={"project_id": "project-1"},
    )


class FakeRetrievalVectorStore:
    def search_assets(self, *, vector_name: str, **_: object) -> list[ScoredId]:
        if vector_name == "summary":
            return [ScoredId("asset-summary", 0.7), ScoredId("asset-caption", 0.1)]
        if vector_name == "caption":
            return [ScoredId("asset-caption", 0.95)]
        return []


class FakeFilteredRetrievalVectorStore:
    def search_assets(self, *, vector_name: str, **_: object) -> list[ScoredId]:
        if vector_name == "summary":
            return [ScoredId("asset-low", 0.8), ScoredId("asset-informative", 0.7)]
        if vector_name == "caption":
            return [ScoredId("asset-informative", 0.95)]
        return []


class FakeDocumentRepository:
    pass


class FakeChunkRepository:
    def list_by_document(self, document_id: str) -> list[Chunk]:
        return []


class FakeAssetRepository:
    def __init__(self, assets: list[DocumentAsset]) -> None:
        self.assets = {asset.id: asset for asset in assets}

    def list_by_ids(self, asset_ids: list[str]) -> list[DocumentAsset]:
        return [self.assets[asset_id] for asset_id in asset_ids if asset_id in self.assets]


class FakeRerankerProvider:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def rerank(self, query: str, candidates: list[str], top_k: int) -> list[float]:
        self.calls.append({"query": query, "candidates": candidates, "top_k": top_k})
        return [1.0 for _ in candidates]


class FakeStreamingLLM:
    def generate(self, prompt: str) -> str:
        return "answer"

    def stream_generate(self, prompt: str):
        yield "answer"


class FakeAnswerRetriever:
    def __init__(self, evidence_pack) -> None:
        self.evidence_pack = evidence_pack

    def retrieve(self, **_: object):
        return self.evidence_pack


@dataclass(slots=True)
class FakeEvidencePack:
    asset: DocumentAsset

    @property
    def query(self) -> str:
        return "query"

    @property
    def documents(self):
        document = Document(
            id="doc-1",
            project_id="project-1",
            path="C:/paper.pdf",
            file_name="paper.pdf",
            doc_type=DocumentType.PDF,
            title="Paper",
            status=DocumentStatus.INDEXED,
            content_hash="hash",
        )
        from domain import DocumentHit

        return [DocumentHit(document=document, score=1.0)]

    @property
    def text_chunks(self):
        return []

    @property
    def assets(self):
        return [AssetHit(asset=self.asset, score=1.0)]

    @property
    def citations(self):
        return []

    @property
    def asset_citations(self):
        from domain import AssetCitation

        return [
            AssetCitation(
                asset_id=self.asset.id,
                document_id=self.asset.document_id,
                document_title="Paper",
                page=self.asset.page_number,
                label=self.asset.asset_label,
                locator="p.2",
            )
        ]
