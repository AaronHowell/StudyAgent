"""Qdrant vector store implementation."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.http import exceptions as qdrant_exceptions
from qdrant_client.http import models

from study_agent_domain import Chunk, ChunkType, DocumentAsset, DocumentProfile


CHUNK_VECTOR_CONTENT = "content"
CHUNK_VECTOR_TITLE = "title"
CHUNK_VECTOR_SUMMARY = "summary"
DOCUMENT_VECTOR_TITLE = "title"
DOCUMENT_VECTOR_SUMMARY = "summary"
ASSET_VECTOR_CAPTION = "caption"
ASSET_VECTOR_SUMMARY = "summary"


@dataclass(slots=True)
class QdrantConnectionConfig:
    """Qdrant connection parameters used by vector adapters.

    作用:
        统一承载 Qdrant 连接参数，避免向量存储实现到处拼接配置。

    Attributes:
        url: 完整 Qdrant URL，优先使用。
        host: Qdrant 主机地址。
        port: Qdrant 端口。
        api_key: 可选 API Key。
        collection_name: chunk collection 名称，保留为兼容字段。
        asset_collection_name: 视觉资产 collection 名称。
        document_collection_name: 文档级画像 collection 名称。
    """

    host: str
    port: int
    url: str = ""
    api_key: str = ""
    timeout_seconds: float = 120.0
    collection_name: str = "study_agent_chunks"
    asset_collection_name: str = "study_agent_assets"
    document_collection_name: str = "study_agent_documents"


class QdrantChunkVectorStore:
    """Qdrant-backed vector store for document chunks and retrieval profiles.

    作用:
        管理三层索引：
        - 文档级画像索引
        - 正文 chunk 索引
        - 视觉资产索引

        并支持 named vectors，让标题、摘要、正文分别参与检索。
    """

    def __init__(self, config: QdrantConnectionConfig) -> None:
        """Create a vector store bound to one Qdrant connection config.

        Args:
            config: Qdrant 连接配置。
        """

        self.config = config
        if config.url:
            self.client = QdrantClient(
                url=config.url,
                api_key=config.api_key or None,
                timeout=config.timeout_seconds,
            )
        else:
            self.client = QdrantClient(
                host=config.host,
                port=config.port,
                api_key=config.api_key or None,
                timeout=config.timeout_seconds,
            )

    def ensure_collection(self, vector_size: int) -> None:
        """Ensure the chunk collection exists with a default named-vector layout.

        作用:
            保留旧接口兼容性。当前默认会创建一个 chunk collection，
            其中正文 `content`、标题 `title`、摘要 `summary` 共用同一维度。

        Args:
            vector_size: 向量维度大小。
        """

        self.ensure_chunk_collection(
            content_vector_size=vector_size,
            title_vector_size=vector_size,
            summary_vector_size=vector_size,
        )

    def ensure_chunk_collection(
        self,
        *,
        content_vector_size: int,
        title_vector_size: int | None = None,
        summary_vector_size: int | None = None,
    ) -> None:
        """Ensure the chunk collection exists with named vectors.

        作用:
            为正文 chunk 创建 named vector collection，使正文、标题和摘要可分别检索。

        Args:
            content_vector_size: 正文向量维度。
            title_vector_size: 标题向量维度，默认回退到正文维度。
            summary_vector_size: 摘要向量维度，默认回退到正文维度。
        """

        self._ensure_named_vector_collection(
            collection_name=self.config.collection_name,
            vectors_config={
                CHUNK_VECTOR_CONTENT: content_vector_size,
                CHUNK_VECTOR_TITLE: title_vector_size or content_vector_size,
                CHUNK_VECTOR_SUMMARY: summary_vector_size or content_vector_size,
            },
        )

    def ensure_document_collection(
        self,
        *,
        title_vector_size: int,
        summary_vector_size: int,
    ) -> None:
        """Ensure the document-profile collection exists with named vectors.

        作用:
            为整篇论文的标题和摘要建立文档级索引，支持先找候选论文再深入正文。

        Args:
            title_vector_size: 文档标题向量维度。
            summary_vector_size: 文档摘要向量维度。
        """

        self._ensure_named_vector_collection(
            collection_name=self.config.document_collection_name,
            vectors_config={
                DOCUMENT_VECTOR_TITLE: title_vector_size,
                DOCUMENT_VECTOR_SUMMARY: summary_vector_size,
            },
        )

    def ensure_asset_collection(
        self,
        *,
        caption_vector_size: int,
        summary_vector_size: int,
    ) -> None:
        """Ensure the visual-asset collection exists with named vectors.

        作用:
            为图表资产建立 caption 和 summary 两套向量，支持视觉资产级检索。

        Args:
            caption_vector_size: 图注向量维度。
            summary_vector_size: 摘要向量维度。
        """

        self._ensure_named_vector_collection(
            collection_name=self.config.asset_collection_name,
            vectors_config={
                ASSET_VECTOR_CAPTION: caption_vector_size,
                ASSET_VECTOR_SUMMARY: summary_vector_size,
            },
        )

    def upsert_chunks(self, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        """Insert or update chunk vectors in Qdrant using one content vector.

        作用:
            保留旧接口兼容性。仅写入正文 `content` 向量。

        Args:
            chunks: 对应的 chunk 列表。
            vectors: 与 chunk 一一对应的正文向量列表。
        """

        self.upsert_chunk_vectors(chunks=chunks, content_vectors=vectors)

    def upsert_chunk_vectors(
        self,
        *,
        chunks: list[Chunk],
        content_vectors: list[list[float]],
        title_vectors: list[list[float]] | None = None,
        summary_vectors: list[list[float]] | None = None,
    ) -> None:
        """Insert or update chunk vectors with named vector support.

        作用:
            同时写入正文、标题、摘要向量，支持更灵活的 chunk 检索策略。

        Args:
            chunks: chunk 列表。
            content_vectors: 正文向量列表。
            title_vectors: 标题向量列表，可选。
            summary_vectors: 摘要向量列表，可选。

        Raises:
            ValueError: 当输入列表长度不一致时抛出。
        """

        self._validate_vector_lengths(chunks, content_vectors, title_vectors, summary_vectors)
        if not chunks:
            return

        points = []
        for index, chunk in enumerate(chunks):
            vector_map: dict[str, list[float]] = {
                CHUNK_VECTOR_CONTENT: content_vectors[index],
            }
            if title_vectors is not None:
                vector_map[CHUNK_VECTOR_TITLE] = title_vectors[index]
            if summary_vectors is not None:
                vector_map[CHUNK_VECTOR_SUMMARY] = summary_vectors[index]

            points.append(
                models.PointStruct(
                    id=self._to_point_id(chunk.id),
                    vector=vector_map,
                    payload={
                        "chunk_id": chunk.id,
                        "project_id": chunk.project_id,
                        "document_id": chunk.document_id,
                        "chunk_index": chunk.chunk_index,
                        "chunk_type": chunk.chunk_type.value,
                        "page": chunk.page,
                        "section": chunk.section,
                    },
                )
            )

        self.client.upsert(
            collection_name=self.config.collection_name,
            points=points,
            wait=True,
        )

    def upsert_document_profiles(
        self,
        *,
        profiles: list[DocumentProfile],
        title_vectors: list[list[float]],
        summary_vectors: list[list[float]],
    ) -> None:
        """Insert or update document-level retrieval profiles.

        作用:
            将论文级画像写入 Qdrant，让系统能先检索相关论文，再进入正文细查。

        Args:
            profiles: 文档画像列表。
            title_vectors: 文档标题向量列表。
            summary_vectors: 文档摘要向量列表。

        Raises:
            ValueError: 当输入列表长度不一致时抛出。
        """

        self._validate_vector_lengths(profiles, title_vectors, summary_vectors)
        if not profiles:
            return

        points = [
            models.PointStruct(
                id=self._to_point_id(profile.document_id),
                vector={
                    DOCUMENT_VECTOR_TITLE: title_vectors[index],
                    DOCUMENT_VECTOR_SUMMARY: summary_vectors[index],
                },
                payload={
                    "document_id": profile.document_id,
                    "project_id": profile.project_id,
                    "title": profile.title,
                    "file_name": profile.file_name,
                    "path": profile.path,
                    "keywords": profile.keywords,
                },
            )
            for index, profile in enumerate(profiles)
        ]

        self.client.upsert(
            collection_name=self.config.document_collection_name,
            points=points,
            wait=True,
        )

    def upsert_assets(
        self,
        *,
        assets: list[DocumentAsset],
        caption_vectors: list[list[float]],
        summary_vectors: list[list[float]],
    ) -> None:
        """Insert or update visual-asset vectors.

        作用:
            将图表资产的 caption 和 summary 两套向量写入 Qdrant，支持视觉资产级检索。

        Args:
            assets: 视觉资产列表。
            caption_vectors: 图注向量列表。
            summary_vectors: 摘要向量列表。

        Raises:
            ValueError: 当输入列表长度不一致时抛出。
        """

        self._validate_vector_lengths(assets, caption_vectors, summary_vectors)
        if not assets:
            return

        points = [
            models.PointStruct(
                id=self._to_point_id(asset.id),
                vector={
                    ASSET_VECTOR_CAPTION: caption_vectors[index],
                    ASSET_VECTOR_SUMMARY: summary_vectors[index],
                },
                payload={
                    "asset_id": asset.id,
                    "document_id": asset.document_id,
                    "project_id": asset.metadata.get("project_id", ""),
                    "page_number": asset.page_number,
                    "asset_kind": asset.asset_kind,
                    "asset_label": asset.asset_label,
                    "asset_type": asset.asset_type,
                    "file_name": asset.file_name,
                },
            )
            for index, asset in enumerate(assets)
        ]

        self.client.upsert(
            collection_name=self.config.asset_collection_name,
            points=points,
            wait=True,
        )

    def search(self, query_vector: list[float], project_id: str, limit: int = 5) -> list[str]:
        """Search chunk ids by the default `content` vector.

        作用:
            保留旧接口兼容性，默认使用正文向量检索 chunk。

        Args:
            query_vector: 查询向量。
            project_id: 项目标识。
            limit: 返回上限。

        Returns:
            list[str]: 命中的 chunk id 列表。
        """

        return self.search_chunks(
            query_vector=query_vector,
            project_id=project_id,
            vector_name=CHUNK_VECTOR_CONTENT,
            limit=limit,
        )

    def search_chunks(
        self,
        *,
        query_vector: list[float],
        project_id: str,
        vector_name: str = CHUNK_VECTOR_CONTENT,
        document_ids: list[str] | None = None,
        limit: int = 5,
    ) -> list[str]:
        """Search relevant chunk ids inside one project.

        作用:
            在指定项目和可选文档集合内，按指定 named vector 检索相关 chunk。

        Args:
            query_vector: 查询向量。
            project_id: 项目标识。
            vector_name: 使用的 named vector 名称。
            document_ids: 可选候选文档列表。
            limit: 返回上限。

        Returns:
            list[str]: 命中的 chunk id 列表。
        """

        filter_conditions: list[models.FieldCondition] = [
            models.FieldCondition(
                key="project_id",
                match=models.MatchValue(value=project_id),
            )
        ]
        if document_ids:
            filter_conditions.append(
                models.FieldCondition(
                    key="document_id",
                    match=models.MatchAny(any=document_ids),
                )
            )

        results = self.client.query_points(
            collection_name=self.config.collection_name,
            query=query_vector,
            using=vector_name,
            query_filter=models.Filter(must=filter_conditions),
            limit=limit,
        )
        return [
            str(point.payload.get("chunk_id"))
            for point in results.points
            if point.payload is not None and point.payload.get("chunk_id") is not None
        ]

    def search_documents(
        self,
        *,
        query_vector: list[float],
        project_id: str,
        vector_name: str = DOCUMENT_VECTOR_SUMMARY,
        limit: int = 5,
    ) -> list[str]:
        """Search relevant document ids at the document-profile level.

        作用:
            用标题或摘要向量先找候选论文，适合用户直接在整个文档库里提问。

        Args:
            query_vector: 查询向量。
            project_id: 项目标识。
            vector_name: 使用的 named vector 名称。
            limit: 返回上限。

        Returns:
            list[str]: 候选文档 id 列表。
        """

        results = self.client.query_points(
            collection_name=self.config.document_collection_name,
            query=query_vector,
            using=vector_name,
            query_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="project_id",
                        match=models.MatchValue(value=project_id),
                    )
                ]
            ),
            limit=limit,
        )
        return [
            str(point.payload.get("document_id"))
            for point in results.points
            if point.payload is not None and point.payload.get("document_id") is not None
        ]

    def search_assets(
        self,
        *,
        query_vector: list[float],
        project_id: str,
        vector_name: str = ASSET_VECTOR_SUMMARY,
        document_ids: list[str] | None = None,
        limit: int = 5,
    ) -> list[str]:
        """Search relevant visual asset ids.

        作用:
            用图注或摘要向量检索视觉资产，支持图表先行的证据召回。

        Args:
            query_vector: 查询向量。
            project_id: 项目标识。
            vector_name: 使用的 named vector 名称。
            document_ids: 可选候选文档列表。
            limit: 返回上限。

        Returns:
            list[str]: 命中的视觉资产 id 列表。
        """

        filter_conditions: list[models.FieldCondition] = [
            models.FieldCondition(
                key="project_id",
                match=models.MatchValue(value=project_id),
            )
        ]
        if document_ids:
            filter_conditions.append(
                models.FieldCondition(
                    key="document_id",
                    match=models.MatchAny(any=document_ids),
                )
            )

        results = self.client.query_points(
            collection_name=self.config.asset_collection_name,
            query=query_vector,
            using=vector_name,
            query_filter=models.Filter(must=filter_conditions),
            limit=limit,
        )
        return [
            str(point.payload.get("asset_id"))
            for point in results.points
            if point.payload is not None and point.payload.get("asset_id") is not None
        ]

    def delete_by_document(self, document_id: str) -> None:
        """Delete all chunk vectors linked to one document.

        作用:
            保留旧接口兼容性，仅删除 chunk collection 中属于该文档的点。

        Args:
            document_id: 文档标识。
        """

        self._delete_points_by_document(self.config.collection_name, document_id)

    def delete_document_profile(self, document_id: str) -> None:
        """Delete one document-level retrieval profile.

        Args:
            document_id: 文档标识。
        """

        self.client.delete(
            collection_name=self.config.document_collection_name,
            points_selector=models.PointIdsList(points=[self._to_point_id(document_id)]),
            wait=True,
        )

    def delete_assets_by_document(self, document_id: str) -> None:
        """Delete all visual asset vectors linked to one document.

        Args:
            document_id: 文档标识。
        """

        self._delete_points_by_document(self.config.asset_collection_name, document_id)

    def _ensure_named_vector_collection(
        self,
        *,
        collection_name: str,
        vectors_config: dict[str, int],
    ) -> None:
        """Ensure one named-vector collection exists.

        作用:
            统一创建 named vector collection，减少重复 collection 初始化逻辑。

        Args:
            collection_name: collection 名称。
            vectors_config: `vector_name -> size` 映射。
        """

        try:
            collection_info = self.client.get_collection(collection_name)
            existing_vectors = self._read_named_vector_sizes(collection_info)
            if existing_vectors == vectors_config:
                return

            # 开发阶段优先保证真实入库链路可恢复；若 collection 维度被旧测试污染，则重建。
            self.client.delete_collection(collection_name=collection_name)
        except qdrant_exceptions.UnexpectedResponse as exc:
            if exc.status_code != 404:
                raise

        self.client.create_collection(
            collection_name=collection_name,
            vectors_config={
                name: models.VectorParams(size=size, distance=models.Distance.COSINE)
                for name, size in vectors_config.items()
            },
        )

    @staticmethod
    def _read_named_vector_sizes(collection_info: object) -> dict[str, int]:
        """Extract named-vector sizes from one Qdrant collection description.

        Args:
            collection_info: `get_collection()` 返回的 collection 描述对象。

        Returns:
            dict[str, int]: `vector_name -> size` 映射。若无法解析则返回空字典。
        """

        try:
            params = getattr(collection_info.config, "params", None)
            vectors = getattr(params, "vectors", None)
            if vectors is None:
                return {}

            if isinstance(vectors, dict):
                return {
                    str(name): int(getattr(vector_params, "size"))
                    for name, vector_params in vectors.items()
                }

            vector_size = getattr(vectors, "size", None)
            if vector_size is not None:
                return {"default": int(vector_size)}
        except Exception:
            return {}

        return {}

    def _delete_points_by_document(self, collection_name: str, document_id: str) -> None:
        """Delete all points of one document from a target collection.

        Args:
            collection_name: 目标 collection 名称。
            document_id: 文档标识。
        """

        self.client.delete(
            collection_name=collection_name,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="document_id",
                            match=models.MatchValue(value=document_id),
                        )
                    ]
                )
            ),
            wait=True,
        )

    @staticmethod
    def _to_point_id(raw_id: str) -> str:
        """Convert one business id into a stable UUID string.

        作用:
            将任意字符串业务 id 映射成 Qdrant 可接受的 point id，避免普通文本 id 被拒绝。

        Args:
            raw_id: 原始业务对象 id。

        Returns:
            str: 稳定的 UUID 字符串。
        """

        return str(uuid5(NAMESPACE_URL, raw_id))

    @staticmethod
    def _validate_vector_lengths(
        items: list[object],
        primary_vectors: list[list[float]],
        *optional_vectors: list[list[float]] | None,
    ) -> None:
        """Validate vector list lengths before batch upsert.

        作用:
            确保每个对象都有一组对应向量，避免批量写入时出现错位。

        Args:
            items: 主对象列表。
            primary_vectors: 第一组必需向量。
            *optional_vectors: 其它可选向量组。

        Raises:
            ValueError: 当任意向量列表长度和对象数量不一致时抛出。
        """

        expected_length = len(items)
        if len(primary_vectors) != expected_length:
            raise ValueError("Primary vectors must have the same length as items.")
        for vector_group in optional_vectors:
            if vector_group is not None and len(vector_group) != expected_length:
                raise ValueError("Optional vectors must have the same length as items.")


if __name__ == "__main__":
    from urllib.parse import urlparse
    from uuid import uuid4

    root_env_path = Path(__file__).resolve().parents[4] / ".env"
    load_dotenv(root_env_path)

    qdrant_url = os.getenv("STUDY_AGENT_QDRANT_URL", "http://127.0.0.1:6333")
    parsed_url = urlparse(qdrant_url)
    qdrant_host = parsed_url.hostname or "127.0.0.1"
    qdrant_port = parsed_url.port or 6333
    qdrant_api_key = os.getenv("STUDY_AGENT_QDRANT_API_KEY", "")
    test_vector_size = 4

    test_collection_suffix = uuid4().hex[:8]
    qdrant_config = QdrantConnectionConfig(
        url=qdrant_url,
        host=qdrant_host,
        port=qdrant_port,
        api_key=qdrant_api_key,
        collection_name=f"study_agent_chunks_test_{test_collection_suffix}",
        asset_collection_name=f"study_agent_assets_test_{test_collection_suffix}",
        document_collection_name=f"study_agent_documents_test_{test_collection_suffix}",
    )

    vector_store = QdrantChunkVectorStore(qdrant_config)
    vector_store.ensure_chunk_collection(
        content_vector_size=test_vector_size,
        title_vector_size=test_vector_size,
        summary_vector_size=test_vector_size,
    )
    vector_store.ensure_document_collection(
        title_vector_size=test_vector_size,
        summary_vector_size=test_vector_size,
    )
    vector_store.ensure_asset_collection(
        caption_vector_size=test_vector_size,
        summary_vector_size=test_vector_size,
    )

    test_suffix = uuid4().hex[:8]
    test_project_id = f"test-project-{test_suffix}"
    test_document_id = f"test-document-{test_suffix}"
    test_chunk_id = f"test-chunk-{test_suffix}"
    test_asset_id = f"test-asset-{test_suffix}"

    test_chunk = Chunk(
        id=test_chunk_id,
        project_id=test_project_id,
        document_id=test_document_id,
        chunk_index=1,
        chunk_type=ChunkType.TEXT,
        text="Sample chunk content for Qdrant integration test.",
        page=1,
        section="Introduction",
        metadata={},
    )
    test_profile = DocumentProfile(
        document_id=test_document_id,
        project_id=test_project_id,
        title="Sample Retrieval Profile",
        summary="A short summary used to test document-level retrieval.",
        keywords=["sample", "retrieval", "test"],
        file_name="sample.pdf",
        path="C:/sample.pdf",
    )
    test_asset = DocumentAsset(
        id=test_asset_id,
        document_id=test_document_id,
        page_number=1,
        file_path="C:/sample.png",
        file_name="sample.png",
        asset_kind="figure",
        asset_label="Figure 1",
        asset_index=1,
        caption="Figure 1: Sample caption.",
        summary="Sample visual asset summary for Qdrant integration test.",
        asset_type="result_plot",
        keywords=["sample", "asset", "test"],
        related_chunk_ids=[test_chunk_id],
        media_type="image/png",
        metadata={"project_id": test_project_id},
    )

    sample_vector_a = [0.1, 0.2, 0.3, 0.4]
    sample_vector_b = [0.2, 0.1, 0.4, 0.3]
    sample_vector_c = [0.4, 0.3, 0.2, 0.1]

    print("Upserting sample chunk/profile/asset vectors...")
    vector_store.upsert_chunk_vectors(
        chunks=[test_chunk],
        content_vectors=[sample_vector_a],
        title_vectors=[sample_vector_b],
        summary_vectors=[sample_vector_c],
    )
    vector_store.upsert_document_profiles(
        profiles=[test_profile],
        title_vectors=[sample_vector_b],
        summary_vectors=[sample_vector_c],
    )
    vector_store.upsert_assets(
        assets=[test_asset],
        caption_vectors=[sample_vector_b],
        summary_vectors=[sample_vector_c],
    )

    print("Searching inserted vectors...")
    chunk_hits = vector_store.search_chunks(
        query_vector=sample_vector_a,
        project_id=test_project_id,
        vector_name=CHUNK_VECTOR_CONTENT,
        limit=3,
    )
    document_hits = vector_store.search_documents(
        query_vector=sample_vector_c,
        project_id=test_project_id,
        vector_name=DOCUMENT_VECTOR_SUMMARY,
        limit=3,
    )
    asset_hits = vector_store.search_assets(
        query_vector=sample_vector_c,
        project_id=test_project_id,
        vector_name=ASSET_VECTOR_SUMMARY,
        limit=3,
    )

    print("Chunk hits:", chunk_hits)
    print("Document hits:", document_hits)
    print("Asset hits:", asset_hits)

    print("Cleaning up inserted test points...")
    vector_store.delete_by_document(test_document_id)
    vector_store.delete_assets_by_document(test_document_id)
    vector_store.delete_document_profile(test_document_id)
    print("Cleanup completed.")
