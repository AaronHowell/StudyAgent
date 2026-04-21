"""Shared runtime factory for the PaperLab LangGraph graph."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

from langchain_openai import ChatOpenAI

from usecases import RetrieveEvidenceUseCase
from integrations import (
    DDGSWebSearchConfig,
    DDGSWebSearchProvider,
    Mem0MemoryConfig,
    Mem0MemoryStore,
    McpToolProvider,
    McpToolProviderConfig,
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
    RedisCacheConfig,
    RedisCacheStore,
)

from contracts import AgentResult
from contracts import AgentTask
from memory.models import MemoryBackend
from runtime.settings import AgentSettings


@dataclass(slots=True)
class CancellationToken:
    """Cooperative cancellation token for speculative specialist work."""

    cancelled: bool = False

    def cancel(self) -> None:
        self.cancelled = True

    def is_cancelled(self) -> bool:
        return self.cancelled


@dataclass(slots=True)
class SpeculativeRunRecord:
    """One in-process speculative specialist run."""

    run_id: str
    turn_id: str
    task: AgentTask
    token: CancellationToken
    task_handle: asyncio.Task[AgentResult] | None = None
    result: AgentResult | None = None
    error: BaseException | None = None
    discard_when_done: bool = False


@dataclass(slots=True)
class AgentRuntime:
    """Concrete dependencies used by the LangGraph runtime."""

    retrieve_evidence_use_case: RetrieveEvidenceUseCase
    chat_model: ChatOpenAI
    memory_store: MemoryBackend | None = None
    web_search_provider: DDGSWebSearchProvider | None = None
    mcp_tool_provider: McpToolProvider | None = None
    cache_store: RedisCacheStore | None = None
    speculative_runs: dict[str, SpeculativeRunRecord] = field(default_factory=dict)

    @property
    def memory_backend(self) -> MemoryBackend | None:
        """Expose the configured long-term memory backend through a stable name."""

        return self.memory_store

    def start_speculative_run(
        self,
        *,
        turn_id: str,
        task: AgentTask,
        runner: callable,
    ) -> SpeculativeRunRecord:
        """Start one speculative specialist run and keep its handle in-memory."""

        token = CancellationToken()
        run_id = f"spec_{uuid4().hex[:8]}"
        record = SpeculativeRunRecord(
            run_id=run_id,
            turn_id=turn_id,
            task=task,
            token=token,
        )

        async def wrapped() -> AgentResult:
            return await runner(token)

        task_handle = asyncio.create_task(wrapped(), name=f"{task.agent_name}:{run_id}")
        record.task_handle = task_handle
        self.speculative_runs[run_id] = record

        def _capture_result(done: asyncio.Task[AgentResult]) -> None:
            current = self.speculative_runs.get(run_id)
            if current is None:
                return
            try:
                current.result = done.result()
            except BaseException as exc:  # noqa: BLE001
                current.error = exc
            current.task_handle = None
            if current.discard_when_done:
                self.speculative_runs.pop(run_id, None)

        task_handle.add_done_callback(_capture_result)
        return record

    def list_speculative_runs(self, turn_id: str) -> list[SpeculativeRunRecord]:
        return [
            record
            for record in self.speculative_runs.values()
            if record.turn_id == turn_id
        ]

    def cancel_speculative_run(self, run_id: str) -> None:
        record = self.speculative_runs.get(run_id)
        if record is None:
            return
        record.token.cancel()

    async def await_speculative_result(self, run_id: str) -> AgentResult | None:
        record = self.speculative_runs.get(run_id)
        if record is None:
            return None
        if record.task_handle is not None:
            try:
                await record.task_handle
            except BaseException:
                pass
        if record.error is not None:
            raise record.error
        return record.result

    def mark_speculative_run_for_cleanup(self, run_id: str) -> None:
        record = self.speculative_runs.get(run_id)
        if record is None:
            return
        record.discard_when_done = True
        if record.task_handle is None:
            self.speculative_runs.pop(run_id, None)

    def cleanup_speculative_run(self, run_id: str) -> None:
        self.speculative_runs.pop(run_id, None)


def _build_mem0_llm_config(settings: AgentSettings) -> dict[str, object]:
    config: dict[str, object] = {
        "model": settings.llm_model,
        "api_key": settings.llm_api_key,
    }
    if settings.memory_llm_provider == "lmstudio":
        config["lmstudio_base_url"] = settings.llm_base_url
        # Mem0 requests json_object by default, but LM Studio-compatible backends in this
        # project only accept json_schema or text. Mem0 already instructs the model to emit
        # JSON and parses free-form text responses, so forcing text keeps the local path working.
        config["lmstudio_response_format"] = {"type": "text"}
    elif settings.memory_llm_provider == "openai":
        config["openai_base_url"] = settings.llm_base_url
    elif settings.memory_llm_provider == "ollama":
        config["ollama_base_url"] = settings.llm_base_url
    elif settings.memory_llm_provider == "vllm":
        config["vllm_base_url"] = settings.llm_base_url
    return config


def _build_mem0_embedder_config(settings: AgentSettings) -> dict[str, object]:
    base_url = settings.embedding_base_url or settings.llm_base_url
    config: dict[str, object] = {
        "model": settings.embedding_model,
        "api_key": settings.embedding_api_key or settings.llm_api_key,
        "embedding_dims": settings.memory_embedding_dims,
    }
    if settings.memory_embedder_provider == "lmstudio":
        config["lmstudio_base_url"] = base_url
    elif settings.memory_embedder_provider == "openai":
        config["openai_base_url"] = base_url
    elif settings.memory_embedder_provider == "ollama":
        config["ollama_base_url"] = base_url
    return config


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
    memory_store = None
    if resolved.memory_enabled:
        history_db_path = Path(resolved.memory_history_db_path).expanduser()
        history_db_path.parent.mkdir(parents=True, exist_ok=True)
        memory_vector_config: dict[str, object] = {
            "collection_name": resolved.memory_vector_collection_name,
            "embedding_model_dims": resolved.memory_embedding_dims,
        }
        if resolved.qdrant_api_key:
            memory_vector_config["url"] = resolved.qdrant_url
            memory_vector_config["api_key"] = resolved.qdrant_api_key
        else:
            memory_vector_config["host"] = parsed_qdrant_url.hostname or "127.0.0.1"
            memory_vector_config["port"] = parsed_qdrant_url.port or 6333

        memory_store = Mem0MemoryStore(
            config=Mem0MemoryConfig(
                config_dict={
                    "vector_store": {
                        "provider": "qdrant",
                        "config": memory_vector_config,
                    },
                    "history_db_path": str(history_db_path),
                    "llm": {
                        "provider": resolved.memory_llm_provider,
                        "config": _build_mem0_llm_config(resolved),
                    },
                    "embedder": {
                        "provider": resolved.memory_embedder_provider,
                        "config": _build_mem0_embedder_config(resolved),
                    },
                }
            )
        )
    web_search_provider = None
    if resolved.web_search_enabled:
        try:
            web_search_provider = DDGSWebSearchProvider(
                DDGSWebSearchConfig(timeout_seconds=resolved.qdrant_timeout_seconds)
            )
        except RuntimeError:
            web_search_provider = None
    mcp_tool_provider = None
    if resolved.mcp_enabled:
        try:
            mcp_configs = []
            if resolved.mcp_servers:
                for item in resolved.mcp_servers:
                    mcp_configs.append(
                        McpToolProviderConfig(
                            server_id=str(item.get("server_id") or item.get("id") or "default"),
                            transport=str(item.get("transport") or "stdio"),
                            command=str(item.get("command") or ""),
                            args=list(item.get("args") or []),
                            url=str(item.get("url") or ""),
                            timeout_seconds=int(item.get("timeout_seconds") or resolved.mcp_timeout_seconds),
                        )
                    )
            if not mcp_configs:
                mcp_configs = [
                    McpToolProviderConfig(
                        server_id="default",
                        transport=resolved.mcp_transport,
                        command=resolved.mcp_server_command,
                        args=list(resolved.mcp_server_args or []),
                        url=resolved.mcp_server_url,
                        timeout_seconds=resolved.mcp_timeout_seconds,
                    )
                ]
            mcp_tool_provider = McpToolProvider(
                configs=mcp_configs
            )
        except RuntimeError:
            mcp_tool_provider = None
    cache_store = None
    if resolved.redis_enabled:
        try:
            cache_store = RedisCacheStore(
                RedisCacheConfig(
                    host=resolved.redis_host,
                    port=resolved.redis_port,
                    password=resolved.redis_password,
                    db=resolved.redis_db,
                )
            )
        except RuntimeError:
            cache_store = None
    return AgentRuntime(
        retrieve_evidence_use_case=retrieve_evidence_use_case,
        chat_model=chat_model,
        memory_store=memory_store,
        web_search_provider=web_search_provider,
        mcp_tool_provider=mcp_tool_provider,
        cache_store=cache_store,
    )


