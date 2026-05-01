"""Agent-specific settings for the PaperLab LangGraph runtime."""

from __future__ import annotations

from dataclasses import dataclass
import json
import shlex
from urllib.parse import quote

from configs.settings.base import BaseSettings, _load_env_files


@dataclass(slots=True)
class AgentSettings(BaseSettings):
    """Runtime settings required by the LangGraph agent runtime."""

    default_project_id: str = "default-project"
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
    def from_env(cls) -> "AgentSettings":
        mcp_servers = cls._json_env("PAPERLAB_MCP_SERVERS_JSON", "STUDY_AGENT_MCP_SERVERS_JSON")
        return cls(
            **cls._shared_env_values(),
            default_project_id=cls._env("PAPERLAB_DEFAULT_PROJECT_ID", "STUDY_AGENT_DEFAULT_PROJECT_ID", default="default-project"),
            memory_enabled=cls._bool_env("PAPERLAB_MEMORY_ENABLED", "STUDY_AGENT_MEMORY_ENABLED", False),
            memory_recall_limit=cls._int_env("PAPERLAB_MEMORY_RECALL_LIMIT", "STUDY_AGENT_MEMORY_RECALL_LIMIT", 5),
            memory_history_db_path=cls._env("PAPERLAB_MEMORY_HISTORY_DB_PATH", "STUDY_AGENT_MEMORY_HISTORY_DB_PATH", default=".mem0/history.db"),
            memory_vector_collection_name=cls._env(
                "PAPERLAB_MEMORY_VECTOR_COLLECTION_NAME",
                "STUDY_AGENT_MEMORY_VECTOR_COLLECTION_NAME",
                default="paperlab_memory",
            ),
            memory_embedding_dims=cls._int_env("PAPERLAB_MEMORY_EMBEDDING_DIMS", "STUDY_AGENT_MEMORY_EMBEDDING_DIMS", 1024),
            memory_llm_provider=cls._env("PAPERLAB_MEMORY_LLM_PROVIDER", "STUDY_AGENT_MEMORY_LLM_PROVIDER", default="lmstudio"),
            memory_embedder_provider=cls._env(
                "PAPERLAB_MEMORY_EMBEDDER_PROVIDER",
                "STUDY_AGENT_MEMORY_EMBEDDER_PROVIDER",
                default="lmstudio",
            ),
            redis_enabled=cls._bool_env("PAPERLAB_REDIS_ENABLED", "STUDY_AGENT_REDIS_ENABLED", False),
            redis_db=cls._int_env("PAPERLAB_REDIS_DB", "STUDY_AGENT_REDIS_DB", 0),
            redis_thread_context_ttl=cls._int_env("PAPERLAB_REDIS_THREAD_CONTEXT_TTL", "STUDY_AGENT_REDIS_THREAD_CONTEXT_TTL", 21600),
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
            short_term_raw_turns=cls._int_env("PAPERLAB_SHORT_TERM_RAW_TURNS", "STUDY_AGENT_SHORT_TERM_RAW_TURNS", 3),
            short_term_summary_turns=cls._int_env("PAPERLAB_SHORT_TERM_SUMMARY_TURNS", "STUDY_AGENT_SHORT_TERM_SUMMARY_TURNS", 4),
        )
