"""Single configuration module for PaperLab server."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shlex
from urllib.parse import quote

from dotenv import load_dotenv


DEFAULT_PROJECT_ID = "default-project"
DEFAULT_THREAD_ID = "default-thread"


AGENT_CONFIGS: dict[str, dict[str, object]] = {
    "supervisor": {
        "role": "supervisor",
        "long_term_memory": True,
        "short_term_compression": True,
        "parallel_workers": ["retriever", "tool", "workspace"],
    },
    "retriever_worker": {
        "role": "retriever",
        "long_term_memory": False,
        "short_term_compression": True,
        "capabilities": ["retrieval"],
    },
    "tool_worker": {
        "role": "tool",
        "long_term_memory": False,
        "short_term_compression": True,
        "capabilities": ["mcp", "skills"],
    },
    "workspace_worker": {
        "role": "workspace",
        "long_term_memory": False,
        "short_term_compression": True,
        "capabilities": ["filesystem", "sandbox"],
    },
}


POLICIES: dict[str, dict[str, object]] = {
    "filesystem": {
        "workspace_root": ".",
        "allow_write": True,
        "allow_recursive_delete": False,
    },
    "mcp": {
        "enabled": False,
        "transport": "stdio",
    },
    "memory": {
        "supervisor_long_term": True,
        "worker_long_term": False,
        "short_term_raw_turns": 3,
        "short_term_summary_turns": 4,
    },
    "retrieval": {
        "document_limit": 5,
        "chunk_limit": 8,
        "asset_limit": 6,
    },
    "sandbox": {
        "enabled": True,
        "timeout_seconds": 120,
    },
}


def _load_env_files() -> None:
    """仅加载 Server 本地 `.env`，作为项目唯一环境文件。"""

    server_env = Path(__file__).resolve().parent / ".env"
    if server_env.exists():
        load_dotenv(server_env, override=True)


_load_env_files()


@dataclass(slots=True)
class BaseSettings:
    """Shared settings and environment parsing for API and Agent runtime."""

    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_database: str = "paperlab"
    mysql_user: str = "root"
    mysql_password: str = ""
    redis_host: str = "127.0.0.1"
    redis_port: int = 6379
    redis_password: str = ""
    qdrant_url: str = "http://127.0.0.1:6333"
    qdrant_api_key: str = ""
    qdrant_timeout_seconds: int = 120
    qdrant_trust_env: bool = False
    qdrant_chunk_collection_name: str = "paperlab_chunks"
    qdrant_asset_collection_name: str = "paperlab_assets"
    qdrant_document_collection_name: str = "paperlab_documents"
    llm_base_url: str = "http://127.0.0.1:11434/v1"
    llm_api_key: str = "ollama"
    llm_model: str = ""
    embedding_base_url: str = ""
    embedding_api_key: str = ""
    embedding_model: str = ""
    embedding_max_input_tokens: int = 480
    multimodal_embedding_enabled: bool = False
    retrieval_debug_log_path: str = "logs/retrieval-debug.jsonl"
    retrieval_reranker_enabled: bool = False
    retrieval_reranker_base_url: str = ""
    retrieval_reranker_api_key: str = ""
    retrieval_reranker_model: str = ""
    retrieval_document_recall_k: int = 12
    retrieval_chunk_recall_k: int = 20
    retrieval_asset_recall_k: int = 12
    retrieval_chunk_rerank_neighbor_window: int = 1

    @staticmethod
    def _env(*names: str, default: str) -> str:
        for name in names:
            value = os.getenv(name)
            if value not in (None, ""):
                return value
        return default

    @classmethod
    def _bool_env(cls, paperlab_name: str, legacy_name: str, default: bool) -> bool:
        value = cls._env(paperlab_name, legacy_name, default="")
        if value is None:
            return default
        return value.strip().lower() in {"1", "true", "yes", "on"}

    @classmethod
    def _int_env(cls, paperlab_name: str, legacy_name: str, default: int) -> int:
        value = cls._env(paperlab_name, legacy_name, default=str(default))
        try:
            return int(value)
        except ValueError:
            return default

    @classmethod
    def _float_env(cls, paperlab_name: str, legacy_name: str, default: float) -> float:
        value = cls._env(paperlab_name, legacy_name, default=str(default))
        try:
            return float(value)
        except ValueError:
            return default

    @classmethod
    def _shared_env_values(cls) -> dict[str, object]:
        return {
            "mysql_host": cls._env("PAPERLAB_MYSQL_HOST", "STUDY_AGENT_MYSQL_HOST", default="127.0.0.1"),
            "mysql_port": cls._int_env("PAPERLAB_MYSQL_PORT", "STUDY_AGENT_MYSQL_PORT", 3306),
            "mysql_database": cls._env("PAPERLAB_MYSQL_DATABASE", "STUDY_AGENT_MYSQL_DATABASE", default="paperlab"),
            "mysql_user": cls._env("PAPERLAB_MYSQL_USER", "STUDY_AGENT_MYSQL_USER", default="root"),
            "mysql_password": cls._env("PAPERLAB_MYSQL_PASSWORD", "STUDY_AGENT_MYSQL_PASSWORD", default=""),
            "redis_host": cls._env("PAPERLAB_REDIS_HOST", "STUDY_AGENT_REDIS_HOST", default="127.0.0.1"),
            "redis_port": cls._int_env("PAPERLAB_REDIS_PORT", "STUDY_AGENT_REDIS_PORT", 6379),
            "redis_password": cls._env("PAPERLAB_REDIS_PASSWORD", "STUDY_AGENT_REDIS_PASSWORD", default=""),
            "qdrant_url": cls._env("PAPERLAB_QDRANT_URL", "STUDY_AGENT_QDRANT_URL", default="http://127.0.0.1:6333"),
            "qdrant_api_key": cls._env("PAPERLAB_QDRANT_API_KEY", "STUDY_AGENT_QDRANT_API_KEY", default=""),
            "qdrant_timeout_seconds": cls._int_env("PAPERLAB_QDRANT_TIMEOUT_SECONDS", "STUDY_AGENT_QDRANT_TIMEOUT_SECONDS", 120),
            "qdrant_trust_env": cls._bool_env("PAPERLAB_QDRANT_TRUST_ENV", "STUDY_AGENT_QDRANT_TRUST_ENV", False),
            "qdrant_chunk_collection_name": cls._env(
                "PAPERLAB_QDRANT_CHUNK_COLLECTION_NAME",
                "STUDY_AGENT_QDRANT_CHUNK_COLLECTION_NAME",
                default="paperlab_chunks",
            ),
            "qdrant_asset_collection_name": cls._env(
                "PAPERLAB_QDRANT_ASSET_COLLECTION_NAME",
                "STUDY_AGENT_QDRANT_ASSET_COLLECTION_NAME",
                default="paperlab_assets",
            ),
            "qdrant_document_collection_name": cls._env(
                "PAPERLAB_QDRANT_DOCUMENT_COLLECTION_NAME",
                "STUDY_AGENT_QDRANT_DOCUMENT_COLLECTION_NAME",
                default="paperlab_documents",
            ),
            "llm_base_url": cls._env("PAPERLAB_LLM_BASE_URL", "STUDY_AGENT_LLM_BASE_URL", default="http://127.0.0.1:11434/v1"),
            "llm_api_key": cls._env("PAPERLAB_LLM_API_KEY", "STUDY_AGENT_LLM_API_KEY", default="ollama"),
            "llm_model": cls._env("PAPERLAB_LLM_MODEL", "STUDY_AGENT_LLM_MODEL", default=""),
            "embedding_base_url": cls._env("PAPERLAB_EMBEDDING_BASE_URL", "STUDY_AGENT_EMBEDDING_BASE_URL", default=""),
            "embedding_api_key": cls._env("PAPERLAB_EMBEDDING_API_KEY", "STUDY_AGENT_EMBEDDING_API_KEY", default=""),
            "embedding_model": cls._env("PAPERLAB_EMBEDDING_MODEL", "STUDY_AGENT_EMBEDDING_MODEL", default=""),
            "embedding_max_input_tokens": cls._int_env("PAPERLAB_EMBEDDING_MAX_INPUT_TOKENS", "STUDY_AGENT_EMBEDDING_MAX_INPUT_TOKENS", 480),
            "multimodal_embedding_enabled": cls._bool_env(
                "PAPERLAB_MULTIMODAL_EMBEDDING_ENABLED",
                "STUDY_AGENT_MULTIMODAL_EMBEDDING_ENABLED",
                False,
            ),
            "retrieval_debug_log_path": cls._env(
                "PAPERLAB_RETRIEVAL_DEBUG_LOG_PATH",
                "STUDY_AGENT_RETRIEVAL_DEBUG_LOG_PATH",
                default="logs/retrieval-debug.jsonl",
            ),
            "retrieval_reranker_enabled": cls._bool_env("PAPERLAB_RETRIEVAL_RERANKER_ENABLED", "STUDY_AGENT_RETRIEVAL_RERANKER_ENABLED", False),
            "retrieval_reranker_base_url": cls._env("PAPERLAB_RETRIEVAL_RERANKER_BASE_URL", "STUDY_AGENT_RETRIEVAL_RERANKER_BASE_URL", default=""),
            "retrieval_reranker_api_key": cls._env("PAPERLAB_RETRIEVAL_RERANKER_API_KEY", "STUDY_AGENT_RETRIEVAL_RERANKER_API_KEY", default=""),
            "retrieval_reranker_model": cls._env("PAPERLAB_RETRIEVAL_RERANKER_MODEL", "STUDY_AGENT_RETRIEVAL_RERANKER_MODEL", default=""),
            "retrieval_document_recall_k": cls._int_env("PAPERLAB_RETRIEVAL_DOCUMENT_RECALL_K", "STUDY_AGENT_RETRIEVAL_DOCUMENT_RECALL_K", 12),
            "retrieval_chunk_recall_k": cls._int_env("PAPERLAB_RETRIEVAL_CHUNK_RECALL_K", "STUDY_AGENT_RETRIEVAL_CHUNK_RECALL_K", 20),
            "retrieval_asset_recall_k": cls._int_env("PAPERLAB_RETRIEVAL_ASSET_RECALL_K", "STUDY_AGENT_RETRIEVAL_ASSET_RECALL_K", 12),
            "retrieval_chunk_rerank_neighbor_window": cls._int_env(
                "PAPERLAB_RETRIEVAL_CHUNK_RERANK_NEIGHBOR_WINDOW",
                "STUDY_AGENT_RETRIEVAL_CHUNK_RERANK_NEIGHBOR_WINDOW",
                1,
            ),
        }


@dataclass(slots=True)
class Settings(BaseSettings):
    """Runtime settings for the API shell."""

    app_name: str = "PaperLab API"
    app_env: str = "development"
    host: str = "127.0.0.1"
    port: int = 8000
    llm_provider: str = "openai-compatible"
    ingest_worker_count: int = 2
    ingest_task_timeout_seconds: int = 900
    session_storage_dir: str = "logs/sessions"
    multimodal_send_image_blocks: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        """Load API settings from environment variables."""

        return cls(
            **cls._shared_env_values(),
            app_name=cls._env("PAPERLAB_APP_NAME", "STUDY_AGENT_APP_NAME", default="PaperLab API"),
            app_env=cls._env("PAPERLAB_APP_ENV", "STUDY_AGENT_APP_ENV", default="development"),
            host=cls._env("PAPERLAB_API_HOST", "STUDY_AGENT_API_HOST", default="127.0.0.1"),
            port=cls._int_env("PAPERLAB_API_PORT", "STUDY_AGENT_API_PORT", 8000),
            llm_provider=cls._env("PAPERLAB_LLM_PROVIDER", "STUDY_AGENT_LLM_PROVIDER", default="openai-compatible"),
            ingest_worker_count=cls._int_env("PAPERLAB_INGEST_WORKER_COUNT", "STUDY_AGENT_INGEST_WORKER_COUNT", 2),
            ingest_task_timeout_seconds=cls._int_env("PAPERLAB_INGEST_TASK_TIMEOUT_SECONDS", "STUDY_AGENT_INGEST_TASK_TIMEOUT_SECONDS", 900),
            session_storage_dir=cls._env(
                "PAPERLAB_SESSION_STORAGE_DIR",
                "STUDY_AGENT_SESSION_STORAGE_DIR",
                default="logs/sessions",
            ),
            multimodal_send_image_blocks=cls._bool_env(
                "PAPERLAB_MULTIMODAL_SEND_IMAGE_BLOCKS",
                "STUDY_AGENT_MULTIMODAL_SEND_IMAGE_BLOCKS",
                False,
            ),
        )


@dataclass(slots=True)
class AgentSettings(BaseSettings):
    """Runtime settings required by the LangGraph agent runtime."""

    default_project_id: str = DEFAULT_PROJECT_ID
    memory_enabled: bool = False
    memory_backend: str = "mem0"
    memory_markdown_root: str = "data/memory"
    memory_recall_limit: int = 5
    memory_history_db_path: str = ".mem0/history.db"
    memory_vector_collection_name: str = "paperlab_memory"
    memory_embedding_dims: int = 1024
    memory_llm_provider: str = "lmstudio"
    memory_llm_base_url: str = ""
    memory_llm_api_key: str = ""
    memory_llm_model: str = ""
    memory_embedder_provider: str = "lmstudio"
    web_search_enabled: bool = True
    web_search_result_limit: int = 5
    mcp_enabled: bool = False
    mcp_transport: str = "stdio"
    mcp_server_command: str = ""
    mcp_server_args: list[str] | None = None
    mcp_server_url: str = ""
    mcp_timeout_seconds: int = 20
    mcp_servers: list[dict[str, object]] | None = None
    agent_loop_max_steps: int = 5
    retrieval_agent_max_steps: int = 5
    redis_enabled: bool = False
    redis_db: int = 0
    redis_thread_context_ttl: int = 21600
    redis_retrieval_context_ttl: int = 21600
    redis_retrieval_cache_ttl: int = 3600
    redis_web_cache_ttl: int = 1800
    redis_lock_ttl: int = 120
    redis_thread_lock_wait_seconds: int = 30
    redis_thread_lock_poll_ms: int = 250
    checkpoint_redis_enabled: bool = False
    checkpoint_redis_url: str = ""
    checkpoint_redis_ttl_minutes: int = 0
    checkpoint_redis_refresh_on_read: bool = True
    checkpoint_redis_checkpoint_prefix: str = "checkpoint"
    checkpoint_redis_checkpoint_write_prefix: str = "checkpoint_write"
    short_term_raw_turns: int = 3
    short_term_summary_turns: int = 4
    retrieval_context_queue_size: int = 8
    speculative_execution_enabled: bool = True
    speculative_reranker_threshold: float = 0.65
    speculative_embedding_threshold: float = 0.82

    def __post_init__(self) -> None:
        if not self.memory_llm_base_url:
            self.memory_llm_base_url = self.llm_base_url
        if not self.memory_llm_api_key:
            self.memory_llm_api_key = self.llm_api_key
        if not self.memory_llm_model:
            self.memory_llm_model = self.llm_model

    @classmethod
    def _json_env(cls, paperlab_name: str, legacy_name: str) -> list[dict[str, object]] | None:
        value = cls._env(paperlab_name, legacy_name, default="").strip()
        if not value:
            return None
        try:
            payload = json.loads(value)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, list):
            return None
        normalized: list[dict[str, object]] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            normalized.append(dict(item))
        return normalized or None

    @staticmethod
    def _redis_url(*, host: str, port: int, password: str, db: int) -> str:
        auth = f":{quote(password, safe='')}@" if password else ""
        return f"redis://{auth}{host}:{port}/{db}"

    @classmethod
    def _memory_backend_env(cls) -> str:
        value = cls._env("PAPERLAB_MEMORY_BACKEND", "STUDY_AGENT_MEMORY_BACKEND", default="mem0").strip().lower()
        if value in {"mem0", "markdown"}:
            return value
        return "mem0"

    @classmethod
    def from_env(cls) -> "AgentSettings":
        mcp_servers = cls._json_env("PAPERLAB_MCP_SERVERS_JSON", "STUDY_AGENT_MCP_SERVERS_JSON")
        return cls(
            **cls._shared_env_values(),
            default_project_id=cls._env("PAPERLAB_DEFAULT_PROJECT_ID", "STUDY_AGENT_DEFAULT_PROJECT_ID", default=DEFAULT_PROJECT_ID),
            memory_enabled=cls._bool_env("PAPERLAB_MEMORY_ENABLED", "STUDY_AGENT_MEMORY_ENABLED", False),
            memory_backend=cls._memory_backend_env(),
            memory_markdown_root=cls._env(
                "PAPERLAB_MEMORY_MARKDOWN_ROOT",
                "STUDY_AGENT_MEMORY_MARKDOWN_ROOT",
                default="data/memory",
            ),
            memory_recall_limit=cls._int_env("PAPERLAB_MEMORY_RECALL_LIMIT", "STUDY_AGENT_MEMORY_RECALL_LIMIT", 5),
            memory_history_db_path=cls._env("PAPERLAB_MEMORY_HISTORY_DB_PATH", "STUDY_AGENT_MEMORY_HISTORY_DB_PATH", default=".mem0/history.db"),
            memory_vector_collection_name=cls._env(
                "PAPERLAB_MEMORY_VECTOR_COLLECTION_NAME",
                "STUDY_AGENT_MEMORY_VECTOR_COLLECTION_NAME",
                default="paperlab_memory",
            ),
            memory_embedding_dims=cls._int_env("PAPERLAB_MEMORY_EMBEDDING_DIMS", "STUDY_AGENT_MEMORY_EMBEDDING_DIMS", 1024),
            memory_llm_provider=cls._env("PAPERLAB_MEMORY_LLM_PROVIDER", "STUDY_AGENT_MEMORY_LLM_PROVIDER", default="lmstudio"),
            memory_llm_base_url=cls._env("PAPERLAB_MEMORY_LLM_BASE_URL", "STUDY_AGENT_MEMORY_LLM_BASE_URL", default=""),
            memory_llm_api_key=cls._env("PAPERLAB_MEMORY_LLM_API_KEY", "STUDY_AGENT_MEMORY_LLM_API_KEY", default=""),
            memory_llm_model=cls._env("PAPERLAB_MEMORY_LLM_MODEL", "STUDY_AGENT_MEMORY_LLM_MODEL", default=""),
            memory_embedder_provider=cls._env(
                "PAPERLAB_MEMORY_EMBEDDER_PROVIDER",
                "STUDY_AGENT_MEMORY_EMBEDDER_PROVIDER",
                default="lmstudio",
            ),
            redis_enabled=cls._bool_env("PAPERLAB_REDIS_ENABLED", "STUDY_AGENT_REDIS_ENABLED", False),
            redis_db=cls._int_env("PAPERLAB_REDIS_DB", "STUDY_AGENT_REDIS_DB", 0),
            redis_thread_context_ttl=cls._int_env("PAPERLAB_REDIS_THREAD_CONTEXT_TTL", "STUDY_AGENT_REDIS_THREAD_CONTEXT_TTL", 21600),
            redis_retrieval_context_ttl=cls._int_env(
                "PAPERLAB_REDIS_RETRIEVAL_CONTEXT_TTL",
                "STUDY_AGENT_REDIS_RETRIEVAL_CONTEXT_TTL",
                21600,
            ),
            redis_retrieval_cache_ttl=cls._int_env("PAPERLAB_REDIS_RETRIEVAL_CACHE_TTL", "STUDY_AGENT_REDIS_RETRIEVAL_CACHE_TTL", 3600),
            redis_web_cache_ttl=cls._int_env("PAPERLAB_REDIS_WEB_CACHE_TTL", "STUDY_AGENT_REDIS_WEB_CACHE_TTL", 1800),
            redis_lock_ttl=cls._int_env("PAPERLAB_REDIS_LOCK_TTL", "STUDY_AGENT_REDIS_LOCK_TTL", 120),
            redis_thread_lock_wait_seconds=cls._int_env("PAPERLAB_REDIS_THREAD_LOCK_WAIT_SECONDS", "STUDY_AGENT_REDIS_THREAD_LOCK_WAIT_SECONDS", 30),
            redis_thread_lock_poll_ms=cls._int_env("PAPERLAB_REDIS_THREAD_LOCK_POLL_MS", "STUDY_AGENT_REDIS_THREAD_LOCK_POLL_MS", 250),
            checkpoint_redis_enabled=cls._bool_env("PAPERLAB_CHECKPOINT_REDIS_ENABLED", "STUDY_AGENT_CHECKPOINT_REDIS_ENABLED", False),
            checkpoint_redis_url=cls._env("PAPERLAB_CHECKPOINT_REDIS_URL", "STUDY_AGENT_CHECKPOINT_REDIS_URL", default="").strip(),
            checkpoint_redis_ttl_minutes=cls._int_env("PAPERLAB_CHECKPOINT_REDIS_TTL_MINUTES", "STUDY_AGENT_CHECKPOINT_REDIS_TTL_MINUTES", 0),
            checkpoint_redis_refresh_on_read=cls._bool_env(
                "PAPERLAB_CHECKPOINT_REDIS_REFRESH_ON_READ",
                "STUDY_AGENT_CHECKPOINT_REDIS_REFRESH_ON_READ",
                True,
            ),
            checkpoint_redis_checkpoint_prefix=cls._env(
                "PAPERLAB_CHECKPOINT_REDIS_CHECKPOINT_PREFIX",
                "STUDY_AGENT_CHECKPOINT_REDIS_CHECKPOINT_PREFIX",
                default="checkpoint",
            ),
            checkpoint_redis_checkpoint_write_prefix=cls._env(
                "PAPERLAB_CHECKPOINT_REDIS_CHECKPOINT_WRITE_PREFIX",
                "STUDY_AGENT_CHECKPOINT_REDIS_CHECKPOINT_WRITE_PREFIX",
                default="checkpoint_write",
            ),
            web_search_enabled=cls._bool_env("PAPERLAB_WEB_SEARCH_ENABLED", "STUDY_AGENT_WEB_SEARCH_ENABLED", True),
            web_search_result_limit=cls._int_env("PAPERLAB_WEB_SEARCH_RESULT_LIMIT", "STUDY_AGENT_WEB_SEARCH_RESULT_LIMIT", 5),
            mcp_enabled=cls._bool_env("PAPERLAB_MCP_ENABLED", "STUDY_AGENT_MCP_ENABLED", False),
            mcp_transport=cls._env("PAPERLAB_MCP_TRANSPORT", "STUDY_AGENT_MCP_TRANSPORT", default="stdio"),
            mcp_server_command=cls._env("PAPERLAB_MCP_SERVER_COMMAND", "STUDY_AGENT_MCP_SERVER_COMMAND", default=""),
            mcp_server_args=shlex.split(cls._env("PAPERLAB_MCP_SERVER_ARGS", "STUDY_AGENT_MCP_SERVER_ARGS", default="")),
            mcp_server_url=cls._env("PAPERLAB_MCP_SERVER_URL", "STUDY_AGENT_MCP_SERVER_URL", default=""),
            mcp_timeout_seconds=cls._int_env("PAPERLAB_MCP_TIMEOUT_SECONDS", "STUDY_AGENT_MCP_TIMEOUT_SECONDS", 20),
            mcp_servers=mcp_servers,
            agent_loop_max_steps=cls._int_env("PAPERLAB_AGENT_LOOP_MAX_STEPS", "STUDY_AGENT_AGENT_LOOP_MAX_STEPS", 5),
            retrieval_agent_max_steps=cls._int_env(
                "PAPERLAB_RETRIEVAL_AGENT_MAX_STEPS",
                "STUDY_AGENT_RETRIEVAL_AGENT_MAX_STEPS",
                5,
            ),
            short_term_raw_turns=cls._int_env("PAPERLAB_SHORT_TERM_RAW_TURNS", "STUDY_AGENT_SHORT_TERM_RAW_TURNS", 3),
            short_term_summary_turns=cls._int_env("PAPERLAB_SHORT_TERM_SUMMARY_TURNS", "STUDY_AGENT_SHORT_TERM_SUMMARY_TURNS", 4),
            retrieval_context_queue_size=cls._int_env(
                "PAPERLAB_RETRIEVAL_CONTEXT_QUEUE_SIZE",
                "STUDY_AGENT_RETRIEVAL_CONTEXT_QUEUE_SIZE",
                8,
            ),
            speculative_execution_enabled=cls._bool_env(
                "PAPERLAB_SPECULATIVE_EXECUTION_ENABLED",
                "STUDY_AGENT_SPECULATIVE_EXECUTION_ENABLED",
                True,
            ),
            speculative_reranker_threshold=cls._float_env(
                "PAPERLAB_SPECULATIVE_RERANKER_THRESHOLD",
                "STUDY_AGENT_SPECULATIVE_RERANKER_THRESHOLD",
                0.65,
            ),
            speculative_embedding_threshold=cls._float_env(
                "PAPERLAB_SPECULATIVE_EMBEDDING_THRESHOLD",
                "STUDY_AGENT_SPECULATIVE_EMBEDDING_THRESHOLD",
                0.82,
            ),
        )


__all__ = [
    "AGENT_CONFIGS",
    "DEFAULT_PROJECT_ID",
    "DEFAULT_THREAD_ID",
    "POLICIES",
    "AgentSettings",
    "BaseSettings",
    "Settings",
    "_load_env_files",
]
