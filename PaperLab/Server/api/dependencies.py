"""API dependency assembly for PaperLab routes. 外部依赖，用来统一处理FastAPI中对外需求的服务"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from api.config import Settings
from api.ingestion import IngestionTaskManager
from documents import LocalDocumentScanner, PdfParser, TextChunkBuilder
from integrations import (
    MySQLChunkRepository,
    MySQLConnectionConfig,
    MySQLDocumentAssetRepository,
    MySQLDocumentRepository,
    OpenAICompatibleEmbeddingConfig,
    OpenAICompatibleEmbeddingProvider,
    OpenAICompatibleLLMConfig,
    OpenAICompatibleLLMProvider,
    OpenAICompatibleRerankerConfig,
    OpenAICompatibleRerankerProvider,
    QdrantChunkVectorStore,
    QdrantConnectionConfig,
    RedisCacheConfig,
    RedisCacheStore,
)
from usecases import AnswerQuestionUseCase, IngestDocumentUseCase, RetrieveEvidenceUseCase


settings = Settings.from_env()


@dataclass(slots=True)
class ApiServices:
    document_scanner: LocalDocumentScanner
    pdf_parser: PdfParser
    document_repository: MySQLDocumentRepository
    asset_repository: MySQLDocumentAssetRepository
    chunk_repository: MySQLChunkRepository
    cache_store: RedisCacheStore | None
    retrieve_evidence_use_case: RetrieveEvidenceUseCase | None
    answer_question_use_case: AnswerQuestionUseCase | None
    ingestion_task_manager: IngestionTaskManager


@lru_cache(maxsize=1)
def get_services() -> ApiServices:
    document_scanner = LocalDocumentScanner()
    pdf_parser = PdfParser()
    mysql_config = MySQLConnectionConfig(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_user,
        password=settings.mysql_password,
        database=settings.mysql_database,
    )
    document_repository = MySQLDocumentRepository(mysql_config)
    asset_repository = MySQLDocumentAssetRepository(mysql_config)
    chunk_repository = MySQLChunkRepository(mysql_config)
    document_chunk_builder = TextChunkBuilder()

    embedding_provider = None
    vector_store = None
    reranker_provider = None
    llm_provider = None

    embedding_base_url = settings.embedding_base_url or settings.llm_base_url
    embedding_api_key = settings.embedding_api_key or settings.llm_api_key
    if settings.embedding_model and embedding_base_url:
        embedding_provider = OpenAICompatibleEmbeddingProvider(
            OpenAICompatibleEmbeddingConfig(
                base_url=embedding_base_url,
                api_key=embedding_api_key,
                model=settings.embedding_model,
                max_input_tokens=settings.embedding_max_input_tokens,
            )
        )

    if settings.llm_model and settings.llm_base_url:
        llm_provider = OpenAICompatibleLLMProvider(
            OpenAICompatibleLLMConfig(
                base_url=settings.llm_base_url,
                api_key=settings.llm_api_key,
                model=settings.llm_model,
            )
        )

    if settings.qdrant_url:
        parsed_qdrant_url = urlparse(settings.qdrant_url)
        vector_store = QdrantChunkVectorStore(
            QdrantConnectionConfig(
                url=settings.qdrant_url,
                host=parsed_qdrant_url.hostname or "127.0.0.1",
                port=parsed_qdrant_url.port or 6333,
                api_key=settings.qdrant_api_key,
                timeout_seconds=settings.qdrant_timeout_seconds,
                collection_name=settings.qdrant_chunk_collection_name,
                asset_collection_name=settings.qdrant_asset_collection_name,
                document_collection_name=settings.qdrant_document_collection_name,
            )
        )

    if (
        settings.retrieval_reranker_enabled
        and settings.retrieval_reranker_base_url
        and settings.retrieval_reranker_model
    ):
        reranker_provider = OpenAICompatibleRerankerProvider(
            OpenAICompatibleRerankerConfig(
                base_url=settings.retrieval_reranker_base_url,
                api_key=settings.retrieval_reranker_api_key,
                model=settings.retrieval_reranker_model,
            )
        )

    document_repository.ensure_tables()
    asset_repository.ensure_tables()
    chunk_repository.ensure_tables()

    ingest_document_use_case = IngestDocumentUseCase(
        document_repository=document_repository,
        asset_repository=asset_repository,
        chunk_repository=chunk_repository,
        pdf_parser=pdf_parser,
        chunk_builder=document_chunk_builder,
        embedding_provider=embedding_provider,
        vector_store=vector_store,
    )
    retrieve_evidence_use_case = None
    answer_question_use_case = None
    if embedding_provider is not None and vector_store is not None:
        retrieve_evidence_use_case = RetrieveEvidenceUseCase(
            embedding_provider=embedding_provider,
            vector_store=vector_store,
            document_repository=document_repository,
            chunk_repository=chunk_repository,
            asset_repository=asset_repository,
            reranker_provider=reranker_provider,
            debug_log_path=Path(settings.retrieval_debug_log_path).expanduser(),
            document_recall_k=settings.retrieval_document_recall_k,
            chunk_recall_k=settings.retrieval_chunk_recall_k,
            asset_recall_k=settings.retrieval_asset_recall_k,
            chunk_rerank_neighbor_window=settings.retrieval_chunk_rerank_neighbor_window,
        )
    if retrieve_evidence_use_case is not None and llm_provider is not None:
        answer_question_use_case = AnswerQuestionUseCase(
            retrieve_evidence_use_case=retrieve_evidence_use_case,
            llm_provider=llm_provider,
        )

    cache_store = None
    if settings.redis_host:
        try:
            cache_store = RedisCacheStore(
                RedisCacheConfig(
                    host=settings.redis_host,
                    port=settings.redis_port,
                    password=settings.redis_password,
                )
            )
        except RuntimeError:
            cache_store = None

    return ApiServices(
        document_scanner=document_scanner,
        pdf_parser=pdf_parser,
        document_repository=document_repository,
        asset_repository=asset_repository,
        chunk_repository=chunk_repository,
        cache_store=cache_store,
        retrieve_evidence_use_case=retrieve_evidence_use_case,
        answer_question_use_case=answer_question_use_case,
        ingestion_task_manager=IngestionTaskManager(
            ingest_document_use_case,
            max_workers=settings.ingest_worker_count,
            task_timeout_seconds=settings.ingest_task_timeout_seconds,
        ),
    )
