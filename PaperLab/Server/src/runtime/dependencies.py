# runtime/dependencies.py
#
# 作用：
#   这是整个后端 Agent 运行时的依赖装配中心，也可以理解为 composition root。
#   它不负责具体业务逻辑，而是负责从配置中创建各种基础设施对象，
#   然后把这些对象注入到 UseCase 和 AgentRuntime 中，供上层 Agent 调用。
#
# 主要流程：
#   1. 从 AgentSettings 读取运行配置。
#   2. 创建 MySQL 相关 Repository：
#        - MySQLDocumentRepository
#        - MySQLDocumentAssetRepository
#        - MySQLChunkRepository
#      并调用 ensure_tables() 确保数据表存在。
#
#   3. 创建 EmbeddingProvider：
#        - OpenAICompatibleEmbeddingProvider
#      用于把 query、chunk、title、summary、caption 等文本转换成向量。
#
#   4. 创建 Qdrant 向量库适配器：
#        - QdrantChunkVectorStore
#      用于向量写入、向量检索、payload 过滤和向量删除。
#
#   5. 根据配置可选创建 RerankerProvider：
#        - OpenAICompatibleRerankerProvider
#      如果没有开启 reranker，则检索流程只使用向量召回和 fusion；
#      如果开启 reranker，则会在召回和融合后增加精排阶段。
#
#   6. 创建 RetrieveEvidenceUseCase：
#      将 embedding_provider、vector_store、document_repository、
#      chunk_repository、asset_repository、reranker_provider 等依赖注入进去。
#      因此 RetrieveEvidenceUseCase 只负责业务编排，不负责自己创建数据库或模型服务。
#
#   7. 创建 ChatOpenAI 作为主聊天模型。
#
#   8. 根据配置可选创建：
#        - memory_store：长期记忆
#        - web_search_provider：网页搜索
#        - mcp_tool_provider：MCP 工具
#        - cache_store：Redis 缓存
#
#   9. 最后返回 AgentRuntime，作为 Agent 系统运行时统一使用的依赖容器。
#
# 设计思想：
#   - 依赖注入：
#       业务类不在内部 new 具体实现，而是由 runtime 层创建后传入。
#
#   - 依赖倒置：
#       UseCase 面向抽象能力编程，具体的 MySQL、Qdrant、Embedding、Reranker
#       都放在 integrations 层实现。
#
#   - 配置解耦：
#       MySQL、Qdrant、LLM、Embedding、Reranker、Memory、Redis、MCP 等配置
#       都来自 AgentSettings，而不是写死在业务代码里。
#
#   - 可选模块：
#       reranker、memory、web_search、MCP、Redis 都可以通过配置开启或关闭。
#
# 注意点：
#   - create_runtime() 如果在应用启动时只调用一次，不加缓存也可以。
#   - 如果它作为 FastAPI dependency 被每个请求调用，可能会重复创建 runtime，
#     更合理的做法是额外提供一个 @lru_cache(maxsize=1) 的 get_runtime()。
#   - AgentRuntime 内部有 speculative_runs 字典，用来管理异步专家任务状态；
#     如果 AgentRuntime 被做成全局单例，需要确认这些状态是否应该跨请求共享。
#   - ensure_tables() 放在运行时初始化中方便开发，但生产环境更推荐使用 migration 工具管理表结构。


from __future__ import annotations

import asyncio
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

from langchain_openai import ChatOpenAI
from qdrant_client import QdrantClient

from usecases import RetrieveEvidenceUseCase
from integrations import (
    DDGSWebSearchConfig,
    DDGSWebSearchProvider,
    ChatModelMarkdownMemorySelector,
    MarkdownMemoryStore,
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
        "model": settings.memory_llm_model,
        "api_key": settings.memory_llm_api_key,
    }
    if settings.memory_llm_provider == "lmstudio":
        config["lmstudio_base_url"] = settings.memory_llm_base_url
        # Mem0 requests json_object by default, but LM Studio-compatible backends in this
        # project only accept json_schema or text. Mem0 already instructs the model to emit
        # JSON and parses free-form text responses, so forcing text keeps the local path working.
        config["lmstudio_response_format"] = {"type": "text"}
    elif settings.memory_llm_provider == "openai":
        config["openai_base_url"] = settings.memory_llm_base_url
    elif settings.memory_llm_provider == "ollama":
        config["ollama_base_url"] = settings.memory_llm_base_url
    elif settings.memory_llm_provider == "vllm":
        config["vllm_base_url"] = settings.memory_llm_base_url
    return config


def _build_memory_chat_model(settings: AgentSettings) -> ChatOpenAI:
    return ChatOpenAI(
        base_url=settings.memory_llm_base_url,
        api_key=settings.memory_llm_api_key,
        model=settings.memory_llm_model,
        streaming=False,
    )


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
            trust_env=resolved.qdrant_trust_env,
            collection_name=resolved.qdrant_chunk_collection_name,
            asset_collection_name=resolved.qdrant_asset_collection_name,
            document_collection_name=resolved.qdrant_document_collection_name,
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
    if resolved.memory_enabled and resolved.memory_backend == "markdown":
        memory_store = MarkdownMemoryStore(
            root_path=Path(resolved.memory_markdown_root).expanduser(),
            selector=ChatModelMarkdownMemorySelector(chat_model=_build_memory_chat_model(resolved)),
        )
    elif resolved.memory_enabled:
        history_db_path = Path(resolved.memory_history_db_path).expanduser()
        history_db_path.parent.mkdir(parents=True, exist_ok=True)
        memory_vector_config: dict[str, object] = {
            "collection_name": resolved.memory_vector_collection_name,
            "embedding_model_dims": resolved.memory_embedding_dims,
            "client": _build_qdrant_client(resolved, parsed_qdrant_url),
        }

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


def _build_qdrant_client(settings: AgentSettings, parsed_qdrant_url) -> QdrantClient:
    """Build a Qdrant client with the same transport policy used by retrieval."""

    if settings.qdrant_url:
        return QdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key or None,
            timeout=settings.qdrant_timeout_seconds,
            trust_env=settings.qdrant_trust_env,
        )
    return QdrantClient(
        host=parsed_qdrant_url.hostname or "127.0.0.1",
        port=parsed_qdrant_url.port or 6333,
        api_key=settings.qdrant_api_key or None,
        timeout=settings.qdrant_timeout_seconds,
        trust_env=settings.qdrant_trust_env,
    )
