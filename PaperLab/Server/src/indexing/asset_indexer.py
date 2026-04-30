"""Visual asset indexing helper."""

from __future__ import annotations

from pathlib import Path

from domain import DocumentAsset, EmbeddingProvider, VectorStore


class AssetIndexer:
    """Index visual assets with caption, summary, and optional image vectors."""

    def __init__(self, *, embedding_provider: EmbeddingProvider, vector_store: VectorStore) -> None:
        self.embedding_provider = embedding_provider
        self.vector_store = vector_store

    def index_assets(self, assets: list[DocumentAsset]) -> None:
        if not assets or not hasattr(self.vector_store, "upsert_assets"):
            return

        caption_texts = [asset.caption or asset.asset_label or asset.file_name for asset in assets]
        summary_texts = [asset.summary or asset.caption or asset.asset_type for asset in assets]
        caption_vectors = self.embedding_provider.embed_texts(caption_texts)
        summary_vectors = self.embedding_provider.embed_texts(summary_texts)
        image_vectors = self._try_embed_images(assets)

        vector_size = len(caption_vectors[0]) if caption_vectors else 0
        image_vector_size = len(image_vectors[0]) if image_vectors else None
        if vector_size and hasattr(self.vector_store, "ensure_asset_collection"):
            self.vector_store.ensure_asset_collection(
                caption_vector_size=vector_size,
                summary_vector_size=vector_size,
                image_vector_size=image_vector_size,
            )

        self.vector_store.upsert_assets(
            assets=assets,
            caption_vectors=caption_vectors,
            summary_vectors=summary_vectors,
            image_vectors=image_vectors,
        )

    def _try_embed_images(self, assets: list[DocumentAsset]) -> list[list[float]] | None:
        image_paths = [asset.file_path for asset in assets if asset.file_path and Path(asset.file_path).exists()]
        if len(image_paths) != len(assets) or not hasattr(self.embedding_provider, "embed_images"):
            return None
        try:
            return self.embedding_provider.embed_images(image_paths)
        except (NotImplementedError, RuntimeError, ValueError):
            return None
