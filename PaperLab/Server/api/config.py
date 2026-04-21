"""Configuration placeholders for the API app."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv


ROOT_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(ROOT_ENV_PATH)


@dataclass(slots=True)
class Settings:
    """Minimal runtime settings for the API shell."""

    app_name: str = "PaperLab API"
    app_env: str = "development"
    host: str = "127.0.0.1"
    port: int = 8000
    mysql_host: str = "10.201.0.86"
    mysql_port: int = 3306
    mysql_database: str = "paperlab"
    mysql_user: str = "root"
    mysql_password: str = ""
    redis_host: str = "10.201.0.86"
    redis_port: int = 6379
    redis_password: str = ""
    qdrant_url: str = "http://10.201.0.86:6333"
    qdrant_api_key: str = ""
    qdrant_timeout_seconds: int = 120
    llm_provider: str = "openai-compatible"
    llm_base_url: str = "http://127.0.0.1:11434/v1"
    llm_api_key: str = "ollama"
    llm_model: str = ""
    embedding_base_url: str = ""
    embedding_api_key: str = ""
    embedding_model: str = ""
    embedding_max_input_tokens: int = 480
    ingest_worker_count: int = 2
    ingest_task_timeout_seconds: int = 900
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

    @classmethod
    def from_env(cls) -> "Settings":
        """Load settings from environment variables with simple defaults."""

        return cls(
            app_name=os.getenv("PAPERLAB_APP_NAME", "PaperLab API"),
            app_env=os.getenv("PAPERLAB_APP_ENV", "development"),
            host=os.getenv("PAPERLAB_API_HOST", "127.0.0.1"),
            port=cls._int_env("PAPERLAB_API_PORT", 8000),
            mysql_host=os.getenv("PAPERLAB_MYSQL_HOST", "10.201.0.86"),
            mysql_port=cls._int_env("PAPERLAB_MYSQL_PORT", 3306),
            mysql_database=os.getenv("PAPERLAB_MYSQL_DATABASE", "paperlab"),
            mysql_user=os.getenv("PAPERLAB_MYSQL_USER", "root"),
            mysql_password=os.getenv("PAPERLAB_MYSQL_PASSWORD", ""),
            redis_host=os.getenv("PAPERLAB_REDIS_HOST", "10.201.0.86"),
            redis_port=cls._int_env("PAPERLAB_REDIS_PORT", 6379),
            redis_password=os.getenv("PAPERLAB_REDIS_PASSWORD", ""),
            qdrant_url=os.getenv("PAPERLAB_QDRANT_URL", "http://10.201.0.86:6333"),
            qdrant_api_key=os.getenv("PAPERLAB_QDRANT_API_KEY", ""),
            qdrant_timeout_seconds=cls._int_env("PAPERLAB_QDRANT_TIMEOUT_SECONDS", 120),
            llm_provider=os.getenv("PAPERLAB_LLM_PROVIDER", "openai-compatible"),
            llm_base_url=os.getenv("PAPERLAB_LLM_BASE_URL", "http://127.0.0.1:11434/v1"),
            llm_api_key=os.getenv("PAPERLAB_LLM_API_KEY", "ollama"),
            llm_model=os.getenv("PAPERLAB_LLM_MODEL", ""),
            embedding_base_url=os.getenv("PAPERLAB_EMBEDDING_BASE_URL", ""),
            embedding_api_key=os.getenv("PAPERLAB_EMBEDDING_API_KEY", ""),
            embedding_model=os.getenv("PAPERLAB_EMBEDDING_MODEL", ""),
            embedding_max_input_tokens=cls._int_env("PAPERLAB_EMBEDDING_MAX_INPUT_TOKENS", 480),
            ingest_worker_count=cls._int_env("PAPERLAB_INGEST_WORKER_COUNT", 2),
            ingest_task_timeout_seconds=cls._int_env("PAPERLAB_INGEST_TASK_TIMEOUT_SECONDS", 900),
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
        )



