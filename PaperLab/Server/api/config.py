"""Configuration placeholders for the API app."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv


def _load_env_files() -> None:
    """仅加载 Server 本地 `.env`，作为项目唯一环境文件。"""

    server_env = Path(__file__).resolve().parents[1] / ".env"
    if server_env.exists():
        load_dotenv(server_env, override=True)


_load_env_files()


@dataclass(slots=True)
class Settings:
    """Minimal runtime settings for the API shell."""

    app_name: str = "PaperLab API"
    app_env: str = "development"
    host: str = "127.0.0.1"
    port: int = 8000
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
    qdrant_chunk_collection_name: str = "paperlab_chunks"
    qdrant_asset_collection_name: str = "paperlab_assets"
    qdrant_document_collection_name: str = "paperlab_documents"
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
    session_storage_dir: str = "logs/sessions"
    retrieval_reranker_enabled: bool = False
    retrieval_reranker_base_url: str = ""
    retrieval_reranker_api_key: str = ""
    retrieval_reranker_model: str = ""
    retrieval_document_recall_k: int = 12
    retrieval_chunk_recall_k: int = 20
    retrieval_asset_recall_k: int = 12
    retrieval_chunk_rerank_neighbor_window: int = 1
    multimodal_send_image_blocks: bool = False

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
    def from_env(cls) -> "Settings":
        """Load settings from environment variables with simple defaults."""

        return cls(
            app_name=cls._env("PAPERLAB_APP_NAME", "STUDY_AGENT_APP_NAME", default="PaperLab API"),
            app_env=cls._env("PAPERLAB_APP_ENV", "STUDY_AGENT_APP_ENV", default="development"),
            host=cls._env("PAPERLAB_API_HOST", "STUDY_AGENT_API_HOST", default="127.0.0.1"),
            port=cls._int_env("PAPERLAB_API_PORT", "STUDY_AGENT_API_PORT", 8000),
            mysql_host=cls._env("PAPERLAB_MYSQL_HOST", "STUDY_AGENT_MYSQL_HOST", default="127.0.0.1"),
            mysql_port=cls._int_env("PAPERLAB_MYSQL_PORT", "STUDY_AGENT_MYSQL_PORT", 3306),
            mysql_database=cls._env("PAPERLAB_MYSQL_DATABASE", "STUDY_AGENT_MYSQL_DATABASE", default="paperlab"),
            mysql_user=cls._env("PAPERLAB_MYSQL_USER", "STUDY_AGENT_MYSQL_USER", default="root"),
            mysql_password=cls._env("PAPERLAB_MYSQL_PASSWORD", "STUDY_AGENT_MYSQL_PASSWORD", default=""),
            redis_host=cls._env("PAPERLAB_REDIS_HOST", "STUDY_AGENT_REDIS_HOST", default="127.0.0.1"),
            redis_port=cls._int_env("PAPERLAB_REDIS_PORT", "STUDY_AGENT_REDIS_PORT", 6379),
            redis_password=cls._env("PAPERLAB_REDIS_PASSWORD", "STUDY_AGENT_REDIS_PASSWORD", default=""),
            qdrant_url=cls._env("PAPERLAB_QDRANT_URL", "STUDY_AGENT_QDRANT_URL", default="http://127.0.0.1:6333"),
            qdrant_api_key=cls._env("PAPERLAB_QDRANT_API_KEY", "STUDY_AGENT_QDRANT_API_KEY", default=""),
            qdrant_timeout_seconds=cls._int_env("PAPERLAB_QDRANT_TIMEOUT_SECONDS", "STUDY_AGENT_QDRANT_TIMEOUT_SECONDS", 120),
            qdrant_chunk_collection_name=cls._env(
                "PAPERLAB_QDRANT_CHUNK_COLLECTION_NAME",
                "STUDY_AGENT_QDRANT_CHUNK_COLLECTION_NAME",
                default="paperlab_chunks",
            ),
            qdrant_asset_collection_name=cls._env(
                "PAPERLAB_QDRANT_ASSET_COLLECTION_NAME",
                "STUDY_AGENT_QDRANT_ASSET_COLLECTION_NAME",
                default="paperlab_assets",
            ),
            qdrant_document_collection_name=cls._env(
                "PAPERLAB_QDRANT_DOCUMENT_COLLECTION_NAME",
                "STUDY_AGENT_QDRANT_DOCUMENT_COLLECTION_NAME",
                default="paperlab_documents",
            ),
            llm_provider=cls._env("PAPERLAB_LLM_PROVIDER", "STUDY_AGENT_LLM_PROVIDER", default="openai-compatible"),
            llm_base_url=cls._env("PAPERLAB_LLM_BASE_URL", "STUDY_AGENT_LLM_BASE_URL", default="http://127.0.0.1:11434/v1"),
            llm_api_key=cls._env("PAPERLAB_LLM_API_KEY", "STUDY_AGENT_LLM_API_KEY", default="ollama"),
            llm_model=cls._env("PAPERLAB_LLM_MODEL", "STUDY_AGENT_LLM_MODEL", default=""),
            embedding_base_url=cls._env("PAPERLAB_EMBEDDING_BASE_URL", "STUDY_AGENT_EMBEDDING_BASE_URL", default=""),
            embedding_api_key=cls._env("PAPERLAB_EMBEDDING_API_KEY", "STUDY_AGENT_EMBEDDING_API_KEY", default=""),
            embedding_model=cls._env("PAPERLAB_EMBEDDING_MODEL", "STUDY_AGENT_EMBEDDING_MODEL", default=""),
            embedding_max_input_tokens=cls._int_env("PAPERLAB_EMBEDDING_MAX_INPUT_TOKENS", "STUDY_AGENT_EMBEDDING_MAX_INPUT_TOKENS", 480),
            ingest_worker_count=cls._int_env("PAPERLAB_INGEST_WORKER_COUNT", "STUDY_AGENT_INGEST_WORKER_COUNT", 2),
            ingest_task_timeout_seconds=cls._int_env("PAPERLAB_INGEST_TASK_TIMEOUT_SECONDS", "STUDY_AGENT_INGEST_TASK_TIMEOUT_SECONDS", 900),
            retrieval_debug_log_path=cls._env(
                "PAPERLAB_RETRIEVAL_DEBUG_LOG_PATH",
                "STUDY_AGENT_RETRIEVAL_DEBUG_LOG_PATH",
                default="logs/retrieval-debug.jsonl",
            ),
            session_storage_dir=cls._env(
                "PAPERLAB_SESSION_STORAGE_DIR",
                "STUDY_AGENT_SESSION_STORAGE_DIR",
                default="logs/sessions",
            ),
            retrieval_reranker_enabled=cls._bool_env("PAPERLAB_RETRIEVAL_RERANKER_ENABLED", "STUDY_AGENT_RETRIEVAL_RERANKER_ENABLED", False),
            retrieval_reranker_base_url=cls._env("PAPERLAB_RETRIEVAL_RERANKER_BASE_URL", "STUDY_AGENT_RETRIEVAL_RERANKER_BASE_URL", default=""),
            retrieval_reranker_api_key=cls._env("PAPERLAB_RETRIEVAL_RERANKER_API_KEY", "STUDY_AGENT_RETRIEVAL_RERANKER_API_KEY", default=""),
            retrieval_reranker_model=cls._env("PAPERLAB_RETRIEVAL_RERANKER_MODEL", "STUDY_AGENT_RETRIEVAL_RERANKER_MODEL", default=""),
            retrieval_document_recall_k=cls._int_env("PAPERLAB_RETRIEVAL_DOCUMENT_RECALL_K", "STUDY_AGENT_RETRIEVAL_DOCUMENT_RECALL_K", 12),
            retrieval_chunk_recall_k=cls._int_env("PAPERLAB_RETRIEVAL_CHUNK_RECALL_K", "STUDY_AGENT_RETRIEVAL_CHUNK_RECALL_K", 20),
            retrieval_asset_recall_k=cls._int_env("PAPERLAB_RETRIEVAL_ASSET_RECALL_K", "STUDY_AGENT_RETRIEVAL_ASSET_RECALL_K", 12),
            retrieval_chunk_rerank_neighbor_window=cls._int_env(
                "PAPERLAB_RETRIEVAL_CHUNK_RERANK_NEIGHBOR_WINDOW",
                "STUDY_AGENT_RETRIEVAL_CHUNK_RERANK_NEIGHBOR_WINDOW",
                1,
            ),
            multimodal_send_image_blocks=cls._bool_env(
                "PAPERLAB_MULTIMODAL_SEND_IMAGE_BLOCKS",
                "STUDY_AGENT_MULTIMODAL_SEND_IMAGE_BLOCKS",
                False,
            ),
        )



