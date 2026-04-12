"""Environment-driven settings for the StudyAgent LangGraph runtime."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv


ROOT_ENV_PATH = Path(__file__).resolve().parents[4] / ".env"
load_dotenv(ROOT_ENV_PATH)


@dataclass(slots=True)
class AgentSettings:
    """Minimal settings required by the LangGraph runtime."""

    assistant_id: str = "study_agent"
    default_project_id: str = "default-project"
    mysql_host: str = "10.201.0.86"
    mysql_port: int = 3306
    mysql_database: str = "study_agent"
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
    def from_env(cls) -> "AgentSettings":
        return cls(
            assistant_id=os.getenv("STUDY_AGENT_LANGGRAPH_ASSISTANT_ID", "study_agent"),
            default_project_id=os.getenv("STUDY_AGENT_DEFAULT_PROJECT_ID", "default-project"),
            mysql_host=os.getenv("STUDY_AGENT_MYSQL_HOST", "10.201.0.86"),
            mysql_port=cls._int_env("STUDY_AGENT_MYSQL_PORT", 3306),
            mysql_database=os.getenv("STUDY_AGENT_MYSQL_DATABASE", "study_agent"),
            mysql_user=os.getenv("STUDY_AGENT_MYSQL_USER", "root"),
            mysql_password=os.getenv("STUDY_AGENT_MYSQL_PASSWORD", ""),
            qdrant_url=os.getenv("STUDY_AGENT_QDRANT_URL", "http://10.201.0.86:6333"),
            qdrant_api_key=os.getenv("STUDY_AGENT_QDRANT_API_KEY", ""),
            qdrant_timeout_seconds=cls._int_env("STUDY_AGENT_QDRANT_TIMEOUT_SECONDS", 120),
            llm_base_url=os.getenv("STUDY_AGENT_LLM_BASE_URL", "http://127.0.0.1:11434/v1"),
            llm_api_key=os.getenv("STUDY_AGENT_LLM_API_KEY", "ollama"),
            llm_model=os.getenv("STUDY_AGENT_LLM_MODEL", ""),
            embedding_base_url=os.getenv("STUDY_AGENT_EMBEDDING_BASE_URL", ""),
            embedding_api_key=os.getenv("STUDY_AGENT_EMBEDDING_API_KEY", ""),
            embedding_model=os.getenv("STUDY_AGENT_EMBEDDING_MODEL", ""),
            embedding_max_input_tokens=cls._int_env("STUDY_AGENT_EMBEDDING_MAX_INPUT_TOKENS", 480),
            retrieval_debug_log_path=os.getenv(
                "STUDY_AGENT_RETRIEVAL_DEBUG_LOG_PATH",
                "logs/retrieval-debug.jsonl",
            ),
            retrieval_reranker_enabled=cls._bool_env("STUDY_AGENT_RETRIEVAL_RERANKER_ENABLED", False),
            retrieval_reranker_base_url=os.getenv("STUDY_AGENT_RETRIEVAL_RERANKER_BASE_URL", ""),
            retrieval_reranker_api_key=os.getenv("STUDY_AGENT_RETRIEVAL_RERANKER_API_KEY", ""),
            retrieval_reranker_model=os.getenv("STUDY_AGENT_RETRIEVAL_RERANKER_MODEL", ""),
            retrieval_document_recall_k=cls._int_env("STUDY_AGENT_RETRIEVAL_DOCUMENT_RECALL_K", 12),
            retrieval_chunk_recall_k=cls._int_env("STUDY_AGENT_RETRIEVAL_CHUNK_RECALL_K", 20),
            retrieval_asset_recall_k=cls._int_env("STUDY_AGENT_RETRIEVAL_ASSET_RECALL_K", 12),
            retrieval_chunk_rerank_neighbor_window=cls._int_env(
                "STUDY_AGENT_RETRIEVAL_CHUNK_RERANK_NEIGHBOR_WINDOW",
                1,
            ),
        )
