from __future__ import annotations

from pathlib import Path


def test_domain_compat_exports_remain_available() -> None:
    from domain import AssetCitation, Chunk, DocumentAsset, EvidencePack
    from domain.documents import Document
    from domain.evidence import ScoredId

    assert Chunk.__name__ == "Chunk"
    assert Document.__name__ == "Document"
    assert DocumentAsset.__name__ == "DocumentAsset"
    assert EvidencePack.__name__ == "EvidencePack"
    assert AssetCitation.__name__ == "AssetCitation"
    assert ScoredId(entity_id="asset-1", score=1.0).entity_id == "asset-1"


def test_api_route_modules_import() -> None:
    from api.routes import assets, chat, documents, health, ingestion, retrieval, runs

    route_paths = {
        route.path
        for router in [assets.router, chat.router, documents.router, health.router, ingestion.router, retrieval.router, runs.router]
        for route in router.routes
    }
    assert "/healthz" in route_paths
    assert "/documents/scan" in route_paths
    assert "/documents/ingest" in route_paths
    assert "/documents/assets/{asset_id}/content" in route_paths
    assert "/retrieval/evidence" in route_paths
    assert "/runs/reproduce" in route_paths


def test_asset_hit_fusion_prefers_image_and_deduplicates() -> None:
    from domain import ScoredId
    from retrieval.fusion import fuse_asset_hits

    fused = fuse_asset_hits(
        summary_hits=[ScoredId("asset-a", 0.7), ScoredId("asset-b", 0.5)],
        caption_hits=[ScoredId("asset-b", 0.8)],
        image_hits=[ScoredId("asset-a", 0.9), ScoredId("asset-c", 0.4)],
        limit=3,
    )

    assert [hit.entity_id for hit in fused] == ["asset-a", "asset-b", "asset-c"]
    assert len({hit.entity_id for hit in fused}) == 3


def test_multimodal_message_builder_uses_image_blocks_only_when_enabled() -> None:
    from generation.message_builders import build_multimodal_answer_messages
    from generation.multimodal_context import (
        ImageEvidenceItem,
        MultimodalEvidenceContext,
        TextEvidenceItem,
    )

    context = MultimodalEvidenceContext(
        question="What does the figure show?",
        text_items=[
            TextEvidenceItem(
                ref_id="C1",
                chunk_id="chunk-1",
                document_id="doc-1",
                document_title="Example Paper",
                page=2,
                text="The paper reports the result in Figure 1.",
            )
        ],
        image_items=[
            ImageEvidenceItem(
                ref_id="A1",
                asset_id="asset-1",
                document_id="doc-1",
                document_title="Example Paper",
                page=3,
                caption="Figure 1: Accuracy comparison.",
                summary="A line chart comparing accuracy.",
                media_type="image/png",
                image_bytes=b"fake-image-bytes",
                image_path=None,
            )
        ],
    )

    text_only_messages = build_multimodal_answer_messages(context)
    text_only_content = text_only_messages[1]["content"]

    assert isinstance(text_only_content, str)
    assert "<text_evidence>" in text_only_content
    assert "<image_evidence>" in text_only_content
    assert "Figure 1: Accuracy comparison." in text_only_content

    messages = build_multimodal_answer_messages(context, include_image_blocks=True)
    user_content = messages[1]["content"]

    assert "<text_evidence>" in user_content[0]["text"]
    assert "<image_evidence>" in user_content[0]["text"]
    assert any(block.get("type") == "image_url" for block in user_content)


def test_multimodal_context_filters_low_value_images() -> None:
    from domain import AssetHit, Document, DocumentAsset, DocumentHit, DocumentStatus, DocumentType
    from generation.multimodal_context import build_multimodal_context

    document = Document(
        id="doc-1",
        project_id="project-1",
        path="paper.pdf",
        file_name="paper.pdf",
        doc_type=DocumentType.PDF,
        title="Example Paper",
        status=DocumentStatus.INDEXED,
        content_hash="hash",
    )
    informative_asset = DocumentAsset(
        id="asset-figure",
        document_id="doc-1",
        page_number=4,
        file_path="C:/asset-figure.png",
        file_name="asset-figure.png",
        asset_label="Figure 2",
        caption="Figure 2: Tracer workflow overview.",
        summary="Workflow diagram showing how Tracer tracks patches.",
        asset_type="workflow_diagram",
    )
    low_value_asset = DocumentAsset(
        id="asset-logo",
        document_id="doc-1",
        page_number=1,
        file_path="C:/asset-logo.png",
        file_name="page_0001_image_001.png",
        asset_label="page_0001_image_001.png",
        caption="",
        summary="Title and author information from the academic paper.",
        asset_type="unknown",
    )

    context = build_multimodal_context(
        question="Explain the workflow in the figure.",
        evidence_pack=type(
            "_FakeEvidencePack",
            (),
            {
                "documents": [DocumentHit(document=document, score=1.0)],
                "text_chunks": [],
                "assets": [
                    AssetHit(asset=low_value_asset, score=0.99),
                    AssetHit(asset=informative_asset, score=0.95),
                ],
            },
        )(),
    )

    assert [item.asset_id for item in context.image_items] == ["asset-figure"]


def test_reproduce_scaffold_files_are_reserved() -> None:
    root = Path(__file__).resolve().parents[1]

    assert (root / "src/workers/reproduce/README.md").exists()
    assert (root / "src/workspace/command_policy.py").exists()
