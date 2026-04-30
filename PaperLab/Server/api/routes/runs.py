from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException

from api.dependencies import get_services
from api.schemas import (
    CreateReproductionRunRequest,
    CreateReproductionRunResponse,
    ReproductionRunEventResponse,
    ReproductionRunResponse,
)
from workers.reproduce.mailbox import FileMailbox
from workers.reproduce.models import ReproductionRun
from workers.reproduce.plan_agent import PlanAgent
from workers.reproduce.store import FileReproductionStore
from workers.reproduce.workers import build_default_workers
from workers.reproduce.locks import NullReproductionLock, RedisReproductionLock

router = APIRouter()

RUN_ROOT = Path("logs/reproduction_runs").resolve()
_background_tasks: dict[str, asyncio.Task] = {}


def _build_plan_agent() -> PlanAgent:
    store = FileReproductionStore(RUN_ROOT)
    lock = _lock()
    mailbox = FileMailbox(RUN_ROOT, lock=lock)
    return PlanAgent(
        store=store,
        mailbox=mailbox,
        workers=build_default_workers(store=store, mailbox=mailbox),
        sandbox_root=RUN_ROOT,
        lock=lock,
    )


def _store() -> FileReproductionStore:
    return FileReproductionStore(RUN_ROOT)


def _lock() -> object:
    try:
        services = get_services()
    except Exception:  # noqa: BLE001 - run API should still work without Redis/MySQL readiness in tests
        return NullReproductionLock()
    if services.cache_store is None:
        return NullReproductionLock()
    return RedisReproductionLock(services.cache_store)


@router.post("/runs/reproduce", response_model=CreateReproductionRunResponse)
async def create_reproduction_run(payload: CreateReproductionRunRequest) -> CreateReproductionRunResponse:
    agent = _build_plan_agent()
    run = await agent.create_run(
        project_id=payload.project_id,
        objective=payload.objective,
        paper_ids=payload.paper_ids,
        permission_mode=payload.permission_mode,
    )
    _background_tasks[run.run_id] = asyncio.create_task(agent.run(run.run_id))
    return CreateReproductionRunResponse(
        run_id=run.run_id,
        status="running",
        workspace_path=run.workspace_path,
        report_path=run.report_path,
    )


@router.get("/runs/{run_id}", response_model=ReproductionRunResponse)
def get_reproduction_run(run_id: str) -> ReproductionRunResponse:
    run = _load_run_or_404(run_id)
    return _to_run_response(run)


@router.get("/runs/{run_id}/events", response_model=list[ReproductionRunEventResponse])
def get_reproduction_run_events(run_id: str) -> list[ReproductionRunEventResponse]:
    run = _load_run_or_404(run_id)
    return [
        ReproductionRunEventResponse(
            event_id=event.event_id,
            event_type=event.event_type,
            message=event.message,
            payload=event.payload,
            created_at=event.created_at,
        )
        for event in run.events
    ]


@router.post("/runs/{run_id}/pause", response_model=ReproductionRunResponse)
def pause_reproduction_run(run_id: str) -> ReproductionRunResponse:
    run = _load_run_or_404(run_id)
    run.status = "paused"
    _store().save(run)
    return _to_run_response(run)


@router.post("/runs/{run_id}/resume", response_model=CreateReproductionRunResponse)
async def resume_reproduction_run(run_id: str) -> CreateReproductionRunResponse:
    run = _load_run_or_404(run_id)
    run.status = "running"
    _store().save(run)
    agent = _build_plan_agent()
    _background_tasks[run.run_id] = asyncio.create_task(agent.run(run.run_id))
    return CreateReproductionRunResponse(
        run_id=run.run_id,
        status=run.status,
        workspace_path=run.workspace_path,
        report_path=run.report_path,
    )


@router.post("/runs/{run_id}/cancel", response_model=ReproductionRunResponse)
def cancel_reproduction_run(run_id: str) -> ReproductionRunResponse:
    run = _load_run_or_404(run_id)
    run.status = "cancelled"
    task = _background_tasks.get(run_id)
    if task is not None:
        task.cancel()
    _store().save(run)
    return _to_run_response(run)


def _load_run_or_404(run_id: str) -> ReproductionRun:
    run = _store().load(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Reproduction run not found: {run_id}")
    return run


def _to_run_response(run: ReproductionRun) -> ReproductionRunResponse:
    return ReproductionRunResponse(
        run_id=run.run_id,
        project_id=run.project_id,
        objective=run.objective,
        status=run.status,
        tasks={key: task.to_dict() for key, task in run.tasks.items()},
        artifacts={key: artifact.to_dict() for key, artifact in run.artifacts.items()},
        workspace_path=run.workspace_path,
        report_path=run.report_path,
        error=run.error,
    )
