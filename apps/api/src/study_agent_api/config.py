"""Configuration placeholders for the API app."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv


ROOT_ENV_PATH = Path(__file__).resolve().parents[4] / ".env"
load_dotenv(ROOT_ENV_PATH)


@dataclass(slots=True)
class Settings:
    """Minimal runtime settings for the API shell."""

    app_name: str = "StudyAgent API"
    app_env: str = "development"
    host: str = "127.0.0.1"
    port: int = 8000
    mysql_host: str = "10.201.0.86"
    mysql_port: int = 3306
    mysql_database: str = "study_agent"
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
            app_name=os.getenv("STUDY_AGENT_APP_NAME", "StudyAgent API"),
            app_env=os.getenv("STUDY_AGENT_APP_ENV", "development"),
            host=os.getenv("STUDY_AGENT_API_HOST", "127.0.0.1"),
            port=cls._int_env("STUDY_AGENT_API_PORT", 8000),
            mysql_host=os.getenv("STUDY_AGENT_MYSQL_HOST", "10.201.0.86"),
            mysql_port=cls._int_env("STUDY_AGENT_MYSQL_PORT", 3306),
            mysql_database=os.getenv("STUDY_AGENT_MYSQL_DATABASE", "study_agent"),
            mysql_user=os.getenv("STUDY_AGENT_MYSQL_USER", "root"),
            mysql_password=os.getenv("STUDY_AGENT_MYSQL_PASSWORD", ""),
            redis_host=os.getenv("STUDY_AGENT_REDIS_HOST", "10.201.0.86"),
            redis_port=cls._int_env("STUDY_AGENT_REDIS_PORT", 6379),
            redis_password=os.getenv("STUDY_AGENT_REDIS_PASSWORD", ""),
            qdrant_url=os.getenv("STUDY_AGENT_QDRANT_URL", "http://10.201.0.86:6333"),
            qdrant_api_key=os.getenv("STUDY_AGENT_QDRANT_API_KEY", ""),
            qdrant_timeout_seconds=cls._int_env("STUDY_AGENT_QDRANT_TIMEOUT_SECONDS", 120),
            llm_provider=os.getenv("STUDY_AGENT_LLM_PROVIDER", "openai-compatible"),
            llm_base_url=os.getenv("STUDY_AGENT_LLM_BASE_URL", "http://127.0.0.1:11434/v1"),
            llm_api_key=os.getenv("STUDY_AGENT_LLM_API_KEY", "ollama"),
            llm_model=os.getenv("STUDY_AGENT_LLM_MODEL", ""),
            embedding_base_url=os.getenv("STUDY_AGENT_EMBEDDING_BASE_URL", ""),
            embedding_api_key=os.getenv("STUDY_AGENT_EMBEDDING_API_KEY", ""),
            embedding_model=os.getenv("STUDY_AGENT_EMBEDDING_MODEL", ""),
            embedding_max_input_tokens=cls._int_env("STUDY_AGENT_EMBEDDING_MAX_INPUT_TOKENS", 480),
            ingest_worker_count=cls._int_env("STUDY_AGENT_INGEST_WORKER_COUNT", 2),
            ingest_task_timeout_seconds=cls._int_env("STUDY_AGENT_INGEST_TASK_TIMEOUT_SECONDS", 900),
        )
