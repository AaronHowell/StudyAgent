"""Shared runtime factory for the StudyAgent LangGraph graph."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from langchain_openai import ChatOpenAI

from study_agent_application import RetrieveEvidenceUseCase
from study_agent_integrations import (
    MySQLChunkRepository,
    MySQLConnectionConfig,
    MySQLDocumentAssetRepository,
    MySQLDocumentRepository,
    OpenAICompatibleEmbeddingConfig,
    OpenAICompatibleEmbeddingProvider,
    OpenAICompatibleRerankerConfig,
    OpenAICompatibleRerankerProvider,
    QdrantChunkVectorStore,
    QdrantConnectionConfig,
)

from study_agent_agents.settings import AgentSettings


@dataclass(slots=True)
class AgentRuntime:
    """Concrete dependencies used by the LangGraph runtime."""

    retrieve_evidence_use_case: RetrieveEvidenceUseCase
    chat_model: ChatOpenAI


def create_runtime(settings: AgentSettings | None = None) -> AgentRuntime:
    """Build one retrieval + chat runtime from environment settings."""

    resolved = settings or AgentSettings.from_env()
    mysql_config = MySQLConnectionConfig(
        host=resolved.mysql_host,
        port=resolved.mysql_port,
        user=resolved.mysql_user,
        password=resolved.mysql_password,
        database=resolved.mysql_database,
    )
    document_repository = MySQLDocumentRepository(mysql_config)
    asset_repository = MySQLDocumentAssetRepository(mysql_config)
    chunk_repository = MySQLChunkRepository(mysql_config)
    document_repository.ensure_tables()
    asset_repository.ensure_tables()
    chunk_repository.ensure_tables()

    embedding_base_url = resolved.embedding_base_url or resolved.llm_base_url
    embedding_api_key = resolved.embedding_api_key or resolved.llm_api_key
    embedding_provider = OpenAICompatibleEmbeddingProvider(
        OpenAICompatibleEmbeddingConfig(
            base_url=embedding_base_url,
            api_key=embedding_api_key,
            model=resolved.embedding_model,
            max_input_tokens=resolved.embedding_max_input_tokens,
        )
    )

    parsed_qdrant_url = urlparse(resolved.qdrant_url)
    vector_store = QdrantChunkVectorStore(
        QdrantConnectionConfig(
            url=resolved.qdrant_url,
            host=parsed_qdrant_url.hostname or "127.0.0.1",
            port=parsed_qdrant_url.port or 6333,
            api_key=resolved.qdrant_api_key,
            timeout_seconds=resolved.qdrant_timeout_seconds,
        )
    )

    reranker_provider = None
    if (
        resolved.retrieval_reranker_enabled
        and resolved.retrieval_reranker_base_url
        and resolved.retrieval_reranker_model
    ):
        reranker_provider = OpenAICompatibleRerankerProvider(
            OpenAICompatibleRerankerConfig(
                base_url=resolved.retrieval_reranker_base_url,
                api_key=resolved.retrieval_reranker_api_key,
                model=resolved.retrieval_reranker_model,
            )
        )

    retrieve_evidence_use_case = RetrieveEvidenceUseCase(
        embedding_provider=embedding_provider,
        vector_store=vector_store,
        document_repository=document_repository,
        chunk_repository=chunk_repository,
        asset_repository=asset_repository,
        reranker_provider=reranker_provider,
        debug_log_path=Path(resolved.retrieval_debug_log_path).expanduser(),
        document_recall_k=resolved.retrieval_document_recall_k,
        chunk_recall_k=resolved.retrieval_chunk_recall_k,
        asset_recall_k=resolved.retrieval_asset_recall_k,
        chunk_rerank_neighbor_window=resolved.retrieval_chunk_rerank_neighbor_window,
    )
    chat_model = ChatOpenAI(
        base_url=resolved.llm_base_url,
        api_key=resolved.llm_api_key,
        model=resolved.llm_model,
        streaming=True,
    )
    return AgentRuntime(
        retrieve_evidence_use_case=retrieve_evidence_use_case,
        chat_model=chat_model,
    )
