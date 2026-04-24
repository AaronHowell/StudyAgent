"""Environment-driven settings for the PaperLab LangGraph runtime."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shlex
from urllib.parse import quote

from dotenv import load_dotenv


ROOT_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(ROOT_ENV_PATH)


@dataclass(slots=True)
class AgentSettings:
    """Minimal settings required by the LangGraph runtime."""

    default_project_id: str = "default-project"
    mysql_host: str = "10.201.0.86"
    mysql_port: int = 3306
    mysql_database: str = "paperlab"
    mysql_user: str = "root"
    mysql_password: str = ""
    qdrant_url: str = "http://10.201.0.86:6333"
    qdrant_api_key: str = ""
    qdrant_timeout_seconds: int = 120
    llm_base_url: str = "http://127.0.0.1:11434/v1"
    llm_api_key: str = "ollama"
    llm_model: str = ""
    embedding_base_url: str = ""
    embedding_api_key: str = ""
    embedding_model: str = ""
    embedding_max_input_tokens: int = 480
    retrieval_debug_log_path: str = "logs/retrieval-debug.jsonl"
    retrieval_reranker_enabled: bool = False
    retrieval_reranker_base_url: str = ""
    retrieval_reranker_api_key: str = ""
    retrieval_reranker_model: str = ""
    retrieval_document_recall_k: int = 12
    retrieval_chunk_recall_k: int = 20
    retrieval_asset_recall_k: int = 12
    retrieval_chunk_rerank_neighbor_window: int = 1
    memory_enabled: bool = False
    memory_recall_limit: int = 5
    memory_history_db_path: str = ".mem0/history.db"
    memory_vector_collection_name: str = "paperlab_memory"
    memory_embedding_dims: int = 1024
    memory_llm_provider: str = "lmstudio"
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
    redis_enabled: bool = False
    redis_host: str = "127.0.0.1"
    redis_port: int = 6379
    redis_password: str = ""
    redis_db: int = 0
    redis_thread_context_ttl: int = 21600
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

    @staticmethod
    def _bool_env(name: str, default: bool) -> bool:
        value = os.getenv(name)
        if value is None:
            return default
        return value.strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _int_env(name: str, default: int) -> int:
        value = os.getenv(name, str(default))
        try:
            return int(value)
        except ValueError:
            return default

    @staticmethod
    def _json_env(name: str) -> list[dict[str, object]] | None:
        value = os.getenv(name, "").strip()
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
    def from_env(cls) -> "AgentSettings":
        mcp_servers = cls._json_env("PAPERLAB_MCP_SERVERS_JSON")
        return cls(
            default_project_id=os.getenv("PAPERLAB_DEFAULT_PROJECT_ID", "default-project"),
            mysql_host=os.getenv("PAPERLAB_MYSQL_HOST", "10.201.0.86"),
            mysql_port=cls._int_env("PAPERLAB_MYSQL_PORT", 3306),
            mysql_database=os.getenv("PAPERLAB_MYSQL_DATABASE", "paperlab"),
            mysql_user=os.getenv("PAPERLAB_MYSQL_USER", "root"),
            mysql_password=os.getenv("PAPERLAB_MYSQL_PASSWORD", ""),
            qdrant_url=os.getenv("PAPERLAB_QDRANT_URL", "http://10.201.0.86:6333"),
            qdrant_api_key=os.getenv("PAPERLAB_QDRANT_API_KEY", ""),
            qdrant_timeout_seconds=cls._int_env("PAPERLAB_QDRANT_TIMEOUT_SECONDS", 120),
            llm_base_url=os.getenv("PAPERLAB_LLM_BASE_URL", "http://127.0.0.1:11434/v1"),
            llm_api_key=os.getenv("PAPERLAB_LLM_API_KEY", "ollama"),
            llm_model=os.getenv("PAPERLAB_LLM_MODEL", ""),
            embedding_base_url=os.getenv("PAPERLAB_EMBEDDING_BASE_URL", ""),
            embedding_api_key=os.getenv("PAPERLAB_EMBEDDING_API_KEY", ""),
            embedding_model=os.getenv("PAPERLAB_EMBEDDING_MODEL", ""),
            embedding_max_input_tokens=cls._int_env("PAPERLAB_EMBEDDING_MAX_INPUT_TOKENS", 480),
            retrieval_debug_log_path=os.getenv(
                "PAPERLAB_RETRIEVAL_DEBUG_LOG_PATH",
                "logs/retrieval-debug.jsonl",
            ),
            retrieval_reranker_enabled=cls._bool_env("PAPERLAB_RETRIEVAL_RERANKER_ENABLED", False),
            retrieval_reranker_base_url=os.getenv("PAPERLAB_RETRIEVAL_RERANKER_BASE_URL", ""),
            retrieval_reranker_api_key=os.getenv("PAPERLAB_RETRIEVAL_RERANKER_API_KEY", ""),
            retrieval_reranker_model=os.getenv("PAPERLAB_RETRIEVAL_RERANKER_MODEL", ""),
            retrieval_document_recall_k=cls._int_env("PAPERLAB_RETRIEVAL_DOCUMENT_RECALL_K", 12),
            retrieval_chunk_recall_k=cls._int_env("PAPERLAB_RETRIEVAL_CHUNK_RECALL_K", 20),
            retrieval_asset_recall_k=cls._int_env("PAPERLAB_RETRIEVAL_ASSET_RECALL_K", 12),
            retrieval_chunk_rerank_neighbor_window=cls._int_env(
                "PAPERLAB_RETRIEVAL_CHUNK_RERANK_NEIGHBOR_WINDOW",
                1,
            ),
            memory_enabled=cls._bool_env("PAPERLAB_MEMORY_ENABLED", False),
            memory_recall_limit=cls._int_env("PAPERLAB_MEMORY_RECALL_LIMIT", 5),
            memory_history_db_path=os.getenv("PAPERLAB_MEMORY_HISTORY_DB_PATH", ".mem0/history.db"),
            memory_vector_collection_name=os.getenv(
                "PAPERLAB_MEMORY_VECTOR_COLLECTION_NAME",
                "paperlab_memory",
            ),
            memory_embedding_dims=cls._int_env("PAPERLAB_MEMORY_EMBEDDING_DIMS", 1024),
            memory_llm_provider=os.getenv("PAPERLAB_MEMORY_LLM_PROVIDER", "lmstudio"),
            memory_embedder_provider=os.getenv(
                "PAPERLAB_MEMORY_EMBEDDER_PROVIDER",
                "lmstudio",
            ),
            redis_enabled=cls._bool_env("PAPERLAB_REDIS_ENABLED", False),
            redis_host=os.getenv("PAPERLAB_REDIS_HOST", "127.0.0.1"),
            redis_port=cls._int_env("PAPERLAB_REDIS_PORT", 6379),
            redis_password=os.getenv("PAPERLAB_REDIS_PASSWORD", ""),
            redis_db=cls._int_env("PAPERLAB_REDIS_DB", 0),
            redis_thread_context_ttl=cls._int_env("PAPERLAB_REDIS_THREAD_CONTEXT_TTL", 21600),
            redis_retrieval_cache_ttl=cls._int_env("PAPERLAB_REDIS_RETRIEVAL_CACHE_TTL", 3600),
            redis_web_cache_ttl=cls._int_env("PAPERLAB_REDIS_WEB_CACHE_TTL", 1800),
            redis_lock_ttl=cls._int_env("PAPERLAB_REDIS_LOCK_TTL", 120),
            redis_thread_lock_wait_seconds=cls._int_env("PAPERLAB_REDIS_THREAD_LOCK_WAIT_SECONDS", 30),
            redis_thread_lock_poll_ms=cls._int_env("PAPERLAB_REDIS_THREAD_LOCK_POLL_MS", 250),
            checkpoint_redis_enabled=cls._bool_env("PAPERLAB_CHECKPOINT_REDIS_ENABLED", False),
            checkpoint_redis_url=os.getenv("PAPERLAB_CHECKPOINT_REDIS_URL", "").strip(),
            checkpoint_redis_ttl_minutes=cls._int_env("PAPERLAB_CHECKPOINT_REDIS_TTL_MINUTES", 0),
            checkpoint_redis_refresh_on_read=cls._bool_env(
                "PAPERLAB_CHECKPOINT_REDIS_REFRESH_ON_READ",
                True,
            ),
            checkpoint_redis_checkpoint_prefix=os.getenv(
                "PAPERLAB_CHECKPOINT_REDIS_CHECKPOINT_PREFIX",
                "checkpoint",
            ),
            checkpoint_redis_checkpoint_write_prefix=os.getenv(
                "PAPERLAB_CHECKPOINT_REDIS_CHECKPOINT_WRITE_PREFIX",
                "checkpoint_write",
            ),
            web_search_enabled=cls._bool_env("PAPERLAB_WEB_SEARCH_ENABLED", True),
            web_search_result_limit=cls._int_env("PAPERLAB_WEB_SEARCH_RESULT_LIMIT", 5),
            mcp_enabled=cls._bool_env("PAPERLAB_MCP_ENABLED", False),
            mcp_transport=os.getenv("PAPERLAB_MCP_TRANSPORT", "stdio"),
            mcp_server_command=os.getenv("PAPERLAB_MCP_SERVER_COMMAND", ""),
            mcp_server_args=shlex.split(os.getenv("PAPERLAB_MCP_SERVER_ARGS", "")),
            mcp_server_url=os.getenv("PAPERLAB_MCP_SERVER_URL", ""),
            mcp_timeout_seconds=cls._int_env("PAPERLAB_MCP_TIMEOUT_SECONDS", 20),
            mcp_servers=mcp_servers,
            agent_loop_max_steps=cls._int_env("PAPERLAB_AGENT_LOOP_MAX_STEPS", 5),
            short_term_raw_turns=cls._int_env("PAPERLAB_SHORT_TERM_RAW_TURNS", 3),
            short_term_summary_turns=cls._int_env("PAPERLAB_SHORT_TERM_SUMMARY_TURNS", 4),
        )



