"""CodingAgent 配置 — 从环境变量或 .env 加载。"""

from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── LLM ──
    llm_base_url: str = "http://10.128.202.100:3010/v1"
    llm_api_key: str = ""
    llm_model: str = "qwen3.5-397b-a17b"
    llm_timeout: int = 120

    # ── Docker ──
    docker_image: str = "python:3.11-slim"
    docker_network: str = "none"           # 默认无网络，安全第一
    docker_memory_limit: str = "2g"
    docker_cpu_period: int = 100_000
    docker_cpu_quota: int = 100_000        # 1 CPU
    docker_timeout: int = 300              # 单次执行超时 5min
    docker_workspace: str = "/workspace"

    # ── Agent ──
    max_iterations: int = 30
    approve_mode: bool = True              # 默认 approve 模式

    # ── Server ──
    host: str = "0.0.0.0"
    port: int = 8001

    # ── 上游 PaperLab Server ──
    paperlab_api_url: str = "http://127.0.0.1:8000"

    model_config = {"env_prefix": "CODING_", "env_file": ".env"}


def get_settings() -> Settings:
    return Settings()
