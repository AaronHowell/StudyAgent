"""API-specific settings for the PaperLab FastAPI shell."""

from __future__ import annotations

from dataclasses import dataclass

from configs.settings.base import BaseSettings, _load_env_files


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
