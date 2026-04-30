"""Text chunk indexing helper."""

from __future__ import annotations

from domain import Chunk, Document, EmbeddingProvider, VectorStore


class ChunkIndexer:
    def __init__(self, *, embedding_provider: EmbeddingProvider, vector_store: VectorStore) -> None:
        self.embedding_provider = embedding_provider
        self.vector_store = vector_store

    def index_chunks(self, *, document: Document, chunks: list[Chunk]) -> None:
        if not chunks or not hasattr(self.vector_store, "upsert_chunk_vectors"):
            return
        chunk_content_texts = [chunk.text for chunk in chunks]
        chunk_title_texts = [chunk.section or document.title for chunk in chunks]
        chunk_summary_texts = [self._summarize_chunk(chunk.text) for chunk in chunks]
        self.vector_store.upsert_chunk_vectors(
            chunks=chunks,
            content_vectors=self.embedding_provider.embed_texts(chunk_content_texts),
            title_vectors=self.embedding_provider.embed_texts(chunk_title_texts),
            summary_vectors=self.embedding_provider.embed_texts(chunk_summary_texts),
        )

    @staticmethod
    def _summarize_chunk(text: str, max_chars: int = 320) -> str:
        return " ".join(text.split())[:max_chars]
