"""Document profile indexing helper."""

from __future__ import annotations

from typing import Any

from domain import Chunk, Document, DocumentAsset, DocumentProfile, EmbeddingProvider, VectorStore


class DocumentIndexer:
    def __init__(self, *, embedding_provider: EmbeddingProvider, vector_store: VectorStore) -> None:
        self.embedding_provider = embedding_provider
        self.vector_store = vector_store

    def build_profile(
        self,
        document: Document,
        chunks: list[Chunk],
        assets: list[DocumentAsset],
        metadata: dict[str, Any] | None = None,
    ) -> DocumentProfile:
        metadata = dict(metadata or {})
        llm_summary = str(metadata.get("summary") or "").strip()
        chunk_preview = " ".join(chunk.text.strip() for chunk in chunks[:3]).strip()
        asset_labels = [asset.asset_label or asset.asset_type for asset in assets[:5] if asset.asset_label or asset.asset_type]
        summary_parts = [part for part in [chunk_preview[:1200], "; ".join(asset_labels)] if part]
        profile_metadata = {
            "chunk_count": len(chunks),
            "asset_count": len(assets),
            **{
                key: value
                for key, value in metadata.items()
                if key in {"authors", "venue", "year"}
            },
        }
        return DocumentProfile(
            document_id=document.id,
            project_id=document.project_id,
            title=document.title,
            summary=llm_summary or " ".join(summary_parts).strip(),
            keywords=self._extract_profile_keywords(document, chunks, assets, metadata),
            file_name=document.file_name,
            path=document.path,
            metadata=profile_metadata,
        )

    def index_profile(self, profile: DocumentProfile) -> None:
        if not hasattr(self.vector_store, "upsert_document_profiles"):
            return
        title_vectors = self.embedding_provider.embed_texts([profile.title])
        summary_vectors = self.embedding_provider.embed_texts([profile.summary])
        vector_size = len(title_vectors[0])
        if hasattr(self.vector_store, "ensure_document_collection"):
            self.vector_store.ensure_document_collection(
                title_vector_size=vector_size,
                summary_vector_size=vector_size,
            )
        self.vector_store.upsert_document_profiles(
            profiles=[profile],
            title_vectors=title_vectors,
            summary_vectors=summary_vectors,
        )

    @staticmethod
    def _extract_profile_keywords(
        document: Document,
        chunks: list[Chunk],
        assets: list[DocumentAsset],
        metadata: dict[str, Any] | None = None,
    ) -> list[str]:
        candidates: list[str] = []
        seen: set[str] = set()

        for keyword in _normalize_metadata_keywords((metadata or {}).get("keywords")):
            if keyword in seen:
                continue
            candidates.append(keyword)
            seen.add(keyword)
            if len(candidates) >= 10:
                return candidates

        for token in document.title.split():
            normalized = token.strip(" ,.;:()[]{}").lower()
            if len(normalized) < 3 or normalized in seen:
                continue
            candidates.append(normalized)
            seen.add(normalized)
            if len(candidates) >= 5:
                break

        for asset in assets:
            for keyword in asset.keywords:
                normalized = keyword.lower()
                if normalized in seen:
                    continue
                candidates.append(normalized)
                seen.add(normalized)
                if len(candidates) >= 10:
                    return candidates

        for chunk in chunks[:5]:
            for token in chunk.text.split():
                normalized = token.strip(" ,.;:()[]{}").lower()
                if len(normalized) < 5 or normalized in seen:
                    continue
                candidates.append(normalized)
                seen.add(normalized)
                if len(candidates) >= 10:
                    return candidates
        return candidates


def _normalize_metadata_keywords(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    keywords: list[str] = []
    for item in value:
        normalized = str(item).strip().lower()
        if len(normalized) < 3 or normalized in keywords:
            continue
        keywords.append(normalized)
    return keywords
