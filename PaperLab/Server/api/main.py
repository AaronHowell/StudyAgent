"""FastAPI application assembly for PaperLab."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

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


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Manage API lifecycle resources."""

    try:
        yield
    finally:
        if get_services.cache_info().currsize:
            get_services().ingestion_task_manager.shutdown(wait=False)


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


if __name__ == "__main__":
    uvicorn.run(
        "api.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )
