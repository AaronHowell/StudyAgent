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


def test_asset_indexer_writes_caption_summary_and_optional_image_vectors(tmp_path) -> None:
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
    assert done.data["asset_sources"][0]["file_url"] == "/documents/assets/asset-1/content"


def _asset(asset_id: str, summary: str, caption: str) -> DocumentAsset:
    return DocumentAsset(
        id=asset_id,
        document_id="doc-1",
        page_number=2,
        file_path=f"C:/{asset_id}.png",
        file_name=f"{asset_id}.png",
        asset_label=f"Figure {asset_id}",
        caption=caption,
        summary=summary,
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
