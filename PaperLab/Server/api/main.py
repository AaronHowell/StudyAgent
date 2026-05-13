"""FastAPI application assembly for PaperLab."""

from __future__ import annotations

from contextlib import asynccontextmanager
import logging
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from api.chat import router as graph_chat_router
from api.chat import session_router
from api.dependencies import get_services, settings
from api.routes.assets import router as assets_router
from api.routes.chat import router as answer_router
from api.routes.documents import router as documents_router
from api.routes.health import router as health_router
from api.routes.ingestion import router as ingestion_router
from api.routes.retrieval import router as retrieval_router
from api.routes.runs import router as runs_router
from api.schemas import SelectProjectFolderRequest, SelectProjectFolderResponse
from configs import AgentSettings, Settings


logger = logging.getLogger("uvicorn.error")


def _select_directory_path(current_path: str | None = None) -> str:
    """Open a native folder picker and return one absolute path."""

    try:
        from tkinter import Tk
        from tkinter import filedialog
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("Native folder picker is unavailable in the current environment.") from exc

    initial_dir = ""
    if current_path:
        candidate = Path(current_path).expanduser()
        if candidate.exists():
            initial_dir = str(candidate.resolve())

    root = Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        selected = filedialog.askdirectory(initialdir=initial_dir or str(Path.home()))
    finally:
        root.destroy()

    return str(Path(selected).expanduser().resolve()) if selected else ""


def _redis_target_from_url(url: str, *, fallback_host: str, fallback_port: int, fallback_db: int) -> tuple[str, int, int]:
    if not url:
        return fallback_host, fallback_port, fallback_db
    parsed = urlparse(url)
    return (
        parsed.hostname or fallback_host,
        parsed.port or fallback_port,
        int(parsed.path.lstrip("/") or fallback_db),
    )


def _startup_config_summary(*, api_settings: Settings, agent_settings: AgentSettings) -> list[str]:
    embedding_base_url = api_settings.embedding_base_url or api_settings.llm_base_url
    embedding_model = api_settings.embedding_model or "(not configured)"
    api_redis = (
        f"{api_settings.redis_host}:{api_settings.redis_port}"
        if api_settings.redis_host
        else "disabled"
    )
    agent_redis = (
        f"enabled {agent_settings.redis_host}:{agent_settings.redis_port} db={agent_settings.redis_db}"
        if agent_settings.redis_enabled
        else "disabled"
    )
    checkpoint_host, checkpoint_port, checkpoint_db = _redis_target_from_url(
        agent_settings.checkpoint_redis_url,
        fallback_host=agent_settings.redis_host,
        fallback_port=agent_settings.redis_port,
        fallback_db=agent_settings.redis_db,
    )
    checkpoint_redis = (
        f"enabled {checkpoint_host}:{checkpoint_port} db={checkpoint_db}"
        if agent_settings.checkpoint_redis_enabled
        else "disabled"
    )
    return [
        f"MySQL: {api_settings.mysql_host}:{api_settings.mysql_port}/{api_settings.mysql_database} user={api_settings.mysql_user}",
        f"Qdrant: {api_settings.qdrant_url}",
        f"LLM: provider={api_settings.llm_provider} base_url={api_settings.llm_base_url} model={api_settings.llm_model or '(not configured)'}",
        f"Embedding: base_url={embedding_base_url} model={embedding_model}",
        f"API Redis: {api_redis}",
        f"Agent Redis: {agent_redis}",
        f"Checkpoint Redis: {checkpoint_redis}",
    ]


def _log_startup_config() -> None:
    agent_settings = AgentSettings.from_env()
    logger.info("PaperLab backend startup configuration:")
    for line in _startup_config_summary(
        api_settings=settings,
        agent_settings=agent_settings,
    ):
        logger.info("  %s", line)


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Manage API lifecycle resources."""

    _log_startup_config()
    try:
        yield
    finally:
        if get_services.cache_info().currsize:
            get_services().ingestion_task_manager.shutdown(wait=True) #把文档入库的任务进行终端


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(documents_router)
app.include_router(ingestion_router)
app.include_router(assets_router)
app.include_router(retrieval_router)
app.include_router(answer_router)
app.include_router(runs_router)
app.include_router(graph_chat_router)
app.include_router(session_router)


@app.post("/desktop/project-folder/select", response_model=SelectProjectFolderResponse)
def select_project_folder(payload: SelectProjectFolderRequest) -> SelectProjectFolderResponse:
    """Open a native folder picker and return the selected absolute path."""

    try:
        selected_path = _select_directory_path(payload.current_path)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return SelectProjectFolderResponse(path=selected_path)


@app.get("/mcp/servers")
def list_mcp_servers() -> dict[str, object]:
    """Return the configured MCP servers from environment settings."""

    agent_settings = AgentSettings.from_env()
    servers: list[dict[str, object]] = []

    if not agent_settings.mcp_enabled:
        return {"enabled": False, "servers": servers}

    if agent_settings.mcp_servers:
        for item in agent_settings.mcp_servers:
            servers.append({
                "server_id": str(item.get("server_id") or item.get("id") or "default"),
                "transport": str(item.get("transport") or "stdio"),
                "command": str(item.get("command") or ""),
            })
    else:
        servers.append({
            "server_id": "default",
            "transport": agent_settings.mcp_transport,
            "command": agent_settings.mcp_server_command,
        })

    return {"enabled": True, "servers": servers}


if __name__ == "__main__":
    uvicorn.run(
        "api.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )
