"""Application-layer retrieval use case."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path

from study_agent_domain import (
    AssetHit,
    ChunkHit,
    ChunkRepository,
    Citation,
    DocumentAssetRepository,
    DocumentHit,
    DocumentRepository,
    EmbeddingProvider,
    EvidencePack,
    RerankerProvider,
    ScoredId,
    VectorStore,
)


@dataclass(slots=True)
class RetrieveEvidenceRequest:
    """Input payload for one retrieval run."""

    query: str
    project_id: str
    document_limit: int = 5
    chunk_limit: int = 8
    asset_limit: int = 6


class RetrieveEvidenceUseCase:
    """Three-stage evidence retrieval orchestrator.

    作用:
        把 query 依次送入文档级、chunk 级、asset 级检索，
        然后将命中结果组装成统一 `EvidencePack`。
    """

    def __init__(
        self,
        *,
        embedding_provider: EmbeddingProvider,
        vector_store: VectorStore,
        document_repository: DocumentRepository,
        chunk_repository: ChunkRepository,
        asset_repository: DocumentAssetRepository,
        reranker_provider: RerankerProvider | None = None,
        debug_log_path: Path | None = None,
        document_recall_k: int = 12,
        chunk_recall_k: int = 20,
        asset_recall_k: int = 12,
        chunk_rerank_neighbor_window: int = 1,
    ) -> None:
        self.embedding_provider = embedding_provider
        self.vector_store = vector_store
        self.document_repository = document_repository
        self.chunk_repository = chunk_repository
        self.asset_repository = asset_repository
        self.reranker_provider = reranker_provider
        self.debug_log_path = debug_log_path
        self.document_recall_k = document_recall_k
        self.chunk_recall_k = chunk_recall_k
        self.asset_recall_k = asset_recall_k
        self.chunk_rerank_neighbor_window = max(chunk_rerank_neighbor_window, 0)

    def retrieve(
        self,
        *,
        query: str,
        project_id: str,
        document_limit: int = 5,
        chunk_limit: int = 8,
        asset_limit: int = 6,
    ) -> EvidencePack:
        """Run one full retrieval pass and return a unified evidence pack.

        输入:
            - query: 用户问题文本。
            - project_id: 检索作用域项目。
            - document_limit: 文档级返回上限。
            - chunk_limit: chunk 级返回上限。
            - asset_limit: asset 级返回上限。

        输出:
            - EvidencePack: 包含文档、正文证据、图表证据和引用。
        """

        query_vector = self.embedding_provider.embed_texts([query])[0]
        document_hits, raw_document_hits = self.retrieve_documents(
            query=query,
            project_id=project_id,
            query_vector=query_vector,
            limit=document_limit,
        )
        candidate_document_ids = [hit.document_id for hit in document_hits]
        chunk_hits, raw_chunk_hits = self.retrieve_chunks(
            query=query,
            project_id=project_id,
            query_vector=query_vector,
            document_ids=candidate_document_ids,
            limit=chunk_limit,
        )
        asset_hits, raw_asset_hits = self.retrieve_assets(
            query=query,
            project_id=project_id,
            query_vector=query_vector,
            document_ids=candidate_document_ids,
            limit=asset_limit,
        )
        evidence_pack = self.build_evidence_pack(
            query=query,
            document_hits=document_hits,
            chunk_hits=chunk_hits,
            asset_hits=asset_hits,
        )
        self._append_debug_log(
            query=query,
            project_id=project_id,
            raw_document_hits=raw_document_hits,
            raw_chunk_hits=raw_chunk_hits,
            raw_asset_hits=raw_asset_hits,
            evidence_pack=evidence_pack,
        )
        return evidence_pack

    def retrieve_documents(
        self,
        *,
        query: str,
        project_id: str,
        query_vector: list[float] | None = None,
        limit: int = 5,
    ) -> tuple[list[DocumentHit], dict[str, list[dict[str, object]]]]:
        """Retrieve scored candidate documents for one query.

        输入:
            - query: 用户问题文本。
            - project_id: 检索作用域项目。
            - query_vector: 可复用的查询向量；为空时内部生成。
            - limit: 返回上限。

        输出:
            - tuple[list[DocumentHit], dict[str, list[dict[str, object]]]]:
              融合后的文档命中，以及 title/summary 原始召回日志数据。
        """

        resolved_query_vector = query_vector or self.embedding_provider.embed_texts([query])[0]
        recall_limit = max(limit, self.document_recall_k)
        title_hits = self.vector_store.search_documents(
            query_vector=resolved_query_vector,
            project_id=project_id,
            vector_name="title",
            limit=recall_limit,
        )
        summary_hits = self.vector_store.search_documents(
            query_vector=resolved_query_vector,
            project_id=project_id,
            vector_name="summary",
            limit=recall_limit,
        )
        fused_ids = self._fuse_document_hits(
            title_hits=title_hits,
            summary_hits=summary_hits,
            limit=recall_limit,
        )
        documents = self.document_repository.list_by_ids([hit.entity_id for hit in fused_ids])
        documents_by_id = {document.id: document for document in documents}
        document_hits = [
            DocumentHit(document=documents_by_id[hit.entity_id], score=hit.score)
            for hit in fused_ids
            if hit.entity_id in documents_by_id
        ]
        reranked_document_hits = self._rerank_document_hits(
            query=query,
            document_hits=document_hits,
            top_k=limit,
        )
        return reranked_document_hits, {
            "title": self._serialize_scored_ids(title_hits),
            "summary": self._serialize_scored_ids(summary_hits),
            "reranked": self._serialize_document_hits(reranked_document_hits),
        }

    def retrieve_chunks(
        self,
        *,
        query: str,
        project_id: str,
        document_ids: list[str],
        query_vector: list[float] | None = None,
        limit: int = 8,
    ) -> tuple[list[ChunkHit], dict[str, object]]:
        """Retrieve scored text chunks inside candidate documents.

        输入:
            - query: 用户问题文本。
            - project_id: 检索作用域项目。
            - document_ids: 文档级召回出的候选文档 id 列表。
            - query_vector: 可复用的查询向量；为空时内部生成。
            - limit: 返回上限。

        输出:
            - tuple[list[ChunkHit], list[dict[str, object]]]:
              重排后的正文证据，以及原始召回日志数据。
        """

        if not document_ids:
            return [], []

        resolved_query_vector = query_vector or self.embedding_provider.embed_texts([query])[0]
        recall_limit = max(limit, self.chunk_recall_k)
        scored_ids = self.vector_store.search_chunks(
            query_vector=resolved_query_vector,
            project_id=project_id,
            vector_name="content",
            document_ids=document_ids,
            limit=recall_limit,
        )
        chunks = self.chunk_repository.list_by_ids([hit.entity_id for hit in scored_ids])
        chunks_by_id = {chunk.id: chunk for chunk in chunks}
        chunk_hits = [
            ChunkHit(chunk=chunks_by_id[hit.entity_id], score=hit.score)
            for hit in scored_ids
            if hit.entity_id in chunks_by_id
        ]
        reranked_chunk_hits = self._rerank_chunk_hits(
            query=query,
            chunk_hits=chunk_hits,
            document_ids=document_ids,
            top_k=limit,
        )
        return reranked_chunk_hits, self._serialize_chunk_rerank_log(scored_ids, reranked_chunk_hits)

    def retrieve_assets(
        self,
        *,
        query: str,
        project_id: str,
        document_ids: list[str],
        query_vector: list[float] | None = None,
        limit: int = 6,
    ) -> tuple[list[AssetHit], dict[str, object]]:
        """Retrieve scored visual assets inside candidate documents.

        输入:
            - query: 用户问题文本。
            - project_id: 检索作用域项目。
            - document_ids: 文档级召回出的候选文档 id 列表。
            - query_vector: 可复用的查询向量；为空时内部生成。
            - limit: 返回上限。

        输出:
            - tuple[list[AssetHit], list[dict[str, object]]]:
              重排后的图表证据，以及原始召回日志数据。
        """

        if not document_ids:
            return [], []

        resolved_query_vector = query_vector or self.embedding_provider.embed_texts([query])[0]
        recall_limit = max(limit, self.asset_recall_k)
        scored_ids = self.vector_store.search_assets(
            query_vector=resolved_query_vector,
            project_id=project_id,
            vector_name="summary",
            document_ids=document_ids,
            limit=recall_limit,
        )
        assets = self.asset_repository.list_by_ids([hit.entity_id for hit in scored_ids])
        assets_by_id = {asset.id: asset for asset in assets}
        asset_hits = [
            AssetHit(asset=assets_by_id[hit.entity_id], score=hit.score)
            for hit in scored_ids
            if hit.entity_id in assets_by_id
        ]
        reranked_asset_hits = self._rerank_asset_hits(
            query=query,
            asset_hits=asset_hits,
            document_ids=document_ids,
            top_k=limit,
        )
        return reranked_asset_hits, self._serialize_asset_rerank_log(scored_ids, reranked_asset_hits)

    def build_evidence_pack(
        self,
        *,
        query: str,
        document_hits: list[DocumentHit],
        chunk_hits: list[ChunkHit],
        asset_hits: list[AssetHit],
    ) -> EvidencePack:
        """Assemble a unified evidence pack from all retrieval layers.

        输入:
            - query: 用户问题文本。
            - document_hits: 文档级命中。
            - chunk_hits: chunk 级命中。
            - asset_hits: asset 级命中。

        输出:
            - EvidencePack: 后续 Agent / API 可直接消费的证据包。
        """

        document_title_by_id = {
            hit.document_id: hit.title
            for hit in document_hits
        }
        citations = [
            Citation(
                document_id=hit.document_id,
                document_title=document_title_by_id.get(hit.document_id, ""),
                chunk_id=hit.chunk_id,
                page=hit.page,
                locator=f"p.{hit.page}" if hit.page is not None else "",
            )
            for hit in chunk_hits
        ]
        return EvidencePack(
            query=query,
            documents=document_hits,
            text_chunks=chunk_hits,
            assets=asset_hits,
            citations=citations,
        )

    @staticmethod
    def _fuse_document_hits(
        *,
        title_hits: list[ScoredId],
        summary_hits: list[ScoredId],
        limit: int,
    ) -> list[ScoredId]:
        """Fuse title and summary document retrieval results into one ranked list."""

        aggregated: dict[str, float] = {}
        for rank, hit in enumerate(title_hits, start=1):
            aggregated[hit.entity_id] = aggregated.get(hit.entity_id, 0.0) + (0.7 * hit.score) + (1.0 / (rank + 1))
        for rank, hit in enumerate(summary_hits, start=1):
            aggregated[hit.entity_id] = aggregated.get(hit.entity_id, 0.0) + (1.0 * hit.score) + (1.0 / (rank + 1))

        fused_hits = [ScoredId(entity_id=entity_id, score=score) for entity_id, score in aggregated.items()]
        fused_hits.sort(key=lambda item: item.score, reverse=True)
        return fused_hits[:limit]

    def _rerank_document_hits(
        self,
        *,
        query: str,
        document_hits: list[DocumentHit],
        top_k: int,
    ) -> list[DocumentHit]:
        """Rerank document hits with a cross-encoder when configured."""

        if not document_hits:
            return []
        if self.reranker_provider is None:
            return document_hits[:top_k]

        candidates = [hit.title for hit in document_hits]
        scores = self.reranker_provider.rerank(query, candidates, top_k)
        rescored_hits = []
        for index, hit in enumerate(document_hits):
            rerank_score = scores[index] if index < len(scores) else -1.0
            rescored_hits.append((rerank_score, hit))
        rescored_hits.sort(key=lambda item: item[0], reverse=True)
        return [hit for _, hit in rescored_hits[:top_k]]

    def _rerank_chunk_hits(
        self,
        *,
        query: str,
        chunk_hits: list[ChunkHit],
        document_ids: list[str],
        top_k: int,
    ) -> list[ChunkHit]:
        """Rerank chunks with cross-encoder scores and page-level diversity."""

        document_rank = {document_id: index for index, document_id in enumerate(document_ids)}
        rerank_scores = None
        if self.reranker_provider is not None:
            rerank_scores = self.reranker_provider.rerank(
                query,
                [self._build_chunk_rerank_text(hit) for hit in chunk_hits],
                top_k,
            )

        rescored_hits = []
        for index, hit in enumerate(chunk_hits):
            score = hit.score + (0.15 / (document_rank.get(hit.document_id, len(document_ids)) + 1))
            if rerank_scores is not None and index < len(rerank_scores):
                score = rerank_scores[index] + (0.05 / (document_rank.get(hit.document_id, len(document_ids)) + 1))
            rescored_hits.append((score, hit))
        rescored_hits.sort(key=lambda item: item[0], reverse=True)
        sorted_hits = [hit for _, hit in rescored_hits]

        selected_hits: list[ChunkHit] = []
        seen_chunk_ids: set[str] = set()
        selected_pages_by_document: dict[str, list[int]] = {}
        for hit in sorted_hits:
            if hit.chunk_id in seen_chunk_ids:
                continue
            page = hit.page
            if page is not None and any(abs(page - existing_page) <= 1 for existing_page in selected_pages_by_document.get(hit.document_id, [])):
                continue
            selected_hits.append(hit)
            seen_chunk_ids.add(hit.chunk_id)
            if page is not None:
                selected_pages_by_document.setdefault(hit.document_id, []).append(page)
            if len(selected_hits) >= top_k:
                break
        return selected_hits

    def _build_chunk_rerank_text(self, hit: ChunkHit) -> str:
        """Build one rerank text window centered on the current chunk."""

        if self.chunk_rerank_neighbor_window <= 0 or not hasattr(self.chunk_repository, "list_by_document"):
            return hit.text

        document_chunks = self.chunk_repository.list_by_document(hit.document_id)
        if not document_chunks:
            return hit.text

        chunks_by_index = {chunk.chunk_index: chunk for chunk in document_chunks}
        start_index = hit.chunk_index - self.chunk_rerank_neighbor_window
        end_index = hit.chunk_index + self.chunk_rerank_neighbor_window
        window_texts: list[str] = []
        for chunk_index in range(start_index, end_index + 1):
            chunk = chunks_by_index.get(chunk_index)
            if chunk is None:
                continue
            window_texts.append(chunk.text.strip())

        combined_text = "\n".join(text for text in window_texts if text)
        return combined_text or hit.text

    def _rerank_asset_hits(
        self,
        *,
        query: str,
        asset_hits: list[AssetHit],
        document_ids: list[str],
        top_k: int,
    ) -> list[AssetHit]:
        """Rerank assets with cross-encoder scores and text-quality filtering."""

        document_rank = {document_id: index for index, document_id in enumerate(document_ids)}
        candidates = [hit.caption or hit.summary or hit.asset_type for hit in asset_hits if hit.caption.strip() or hit.summary.strip()]
        rerank_scores = None
        if self.reranker_provider is not None and candidates:
            rerank_scores = self.reranker_provider.rerank(query, candidates, top_k)
        rescored_hits = []
        rerank_index = 0
        for hit in asset_hits:
            if not hit.caption.strip() and not hit.summary.strip():
                continue
            score = hit.score + (0.12 / (document_rank.get(hit.document_id, len(document_ids)) + 1))
            if rerank_scores is not None and rerank_index < len(rerank_scores):
                score = rerank_scores[rerank_index] + (0.04 / (document_rank.get(hit.document_id, len(document_ids)) + 1))
            rerank_index += 1
            rescored_hits.append((score, hit))

        rescored_hits.sort(key=lambda item: item[0], reverse=True)
        selected_hits: list[AssetHit] = []
        seen_signatures: set[tuple[str, int, str]] = set()
        for _, hit in rescored_hits:
            signature = (hit.document_id, hit.page_number, hit.asset_label or hit.file_name)
            if signature in seen_signatures:
                continue
            seen_signatures.add(signature)
            selected_hits.append(hit)
            if len(selected_hits) >= top_k:
                break
        return selected_hits

    @staticmethod
    def _serialize_scored_ids(hits: list[ScoredId]) -> list[dict[str, object]]:
        """Convert scored ids into JSON-friendly rows for retrieval debugging."""

        return [
            {
                "entity_id": hit.entity_id,
                "score": hit.score,
            }
            for hit in hits
        ]

    def _append_debug_log(
        self,
        *,
        query: str,
        project_id: str,
        raw_document_hits: dict[str, list[dict[str, object]]],
        raw_chunk_hits: dict[str, object],
        raw_asset_hits: dict[str, object],
        evidence_pack: EvidencePack,
    ) -> None:
        """Append one retrieval trace into the shared JSONL debug log."""

        if self.debug_log_path is None:
            return

        self.debug_log_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "query": query,
            "project_id": project_id,
            "raw_document_hits": raw_document_hits,
            "raw_chunk_hits": raw_chunk_hits,
            "raw_asset_hits": raw_asset_hits,
            "reranked_document_hits": raw_document_hits.get("reranked", []),
            "final_documents": [
                {
                    "document_id": hit.document_id,
                    "score": hit.score,
                    "title": hit.title,
                }
                for hit in evidence_pack.documents
            ],
            "final_text_chunks": [
                {
                    "chunk_id": hit.chunk_id,
                    "document_id": hit.document_id,
                    "score": hit.score,
                    "page": hit.page,
                }
                for hit in evidence_pack.text_chunks
            ],
            "final_assets": [
                {
                    "asset_id": hit.asset_id,
                    "document_id": hit.document_id,
                    "score": hit.score,
                    "page_number": hit.page_number,
                    "asset_label": hit.asset_label,
                }
                for hit in evidence_pack.assets
            ],
            "citations": [
                {
                    "document_id": citation.document_id,
                    "chunk_id": citation.chunk_id,
                    "page": citation.page,
                    "locator": citation.locator,
                }
                for citation in evidence_pack.citations
            ],
        }
        with self.debug_log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    @staticmethod
    def _serialize_document_hits(hits: list[DocumentHit]) -> list[dict[str, object]]:
        return [
            {
                "document_id": hit.document_id,
                "score": hit.score,
                "title": hit.title,
            }
            for hit in hits
        ]

    @staticmethod
    def _serialize_chunk_rerank_log(
        raw_hits: list[ScoredId],
        reranked_hits: list[ChunkHit],
    ) -> dict[str, object]:
        return {
            "raw_vector_hits": RetrieveEvidenceUseCase._serialize_scored_ids(raw_hits),
            "reranked_hits": [
                {
                    "chunk_id": hit.chunk_id,
                    "document_id": hit.document_id,
                    "score": hit.score,
                    "page": hit.page,
                }
                for hit in reranked_hits
            ],
        }

    @staticmethod
    def _serialize_asset_rerank_log(
        raw_hits: list[ScoredId],
        reranked_hits: list[AssetHit],
    ) -> dict[str, object]:
        return {
            "raw_vector_hits": RetrieveEvidenceUseCase._serialize_scored_ids(raw_hits),
            "reranked_hits": [
                {
                    "asset_id": hit.asset_id,
                    "document_id": hit.document_id,
                    "score": hit.score,
                    "page_number": hit.page_number,
                }
                for hit in reranked_hits
            ],
        }
