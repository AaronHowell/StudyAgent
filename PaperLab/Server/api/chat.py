"""FastAPI chat bridge that drives the compiled LangGraph directly."""

from __future__ import annotations

from functools import lru_cache
import json
import logging
from pathlib import Path
from typing import Any
from datetime import UTC
from datetime import datetime

from fastapi import APIRouter
from fastapi import HTTPException
from fastapi import Query
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage
from langchain_core.messages import BaseMessage
from langchain_core.messages import HumanMessage
from langchain_core.messages import SystemMessage
from langgraph.types import Command

from api.schemas import ChatGuidanceRequest
from api.schemas import ChatInterruptPayload
from api.schemas import ChatMessageInput
from api.schemas import ChatMessagePayload
from api.schemas import ChatRunRequest
from api.schemas import ChatSessionSnapshotResponse
from api.schemas import ChatStateResponse
from api.schemas import SessionRestoreResponse
from api.schemas import SessionSummaryResponse
from api.schemas import WorkerEventResponse
from api.chat_turns import build_assistant_turn_payload
from api.chat_turns import build_turns_from_messages
from api.chat_turns import serialize_trace_message_event
from api.config import Settings
from configs import DEFAULT_PROJECT_ID
from configs import DEFAULT_THREAD_ID
from orchestration.guidance_queue import push_guidance_message
from orchestration.supervisor import graph
from session_storage import SessionCheckpoint
from session_storage import SessionMessageRecord
from session_storage import SessionStorageService


router = APIRouter(prefix="/chat", tags=["chat"])
session_router = APIRouter(tags=["sessions"])
logger = logging.getLogger("uvicorn.error")


@lru_cache(maxsize=1)
def get_session_storage() -> SessionStorageService:
    """返回服务端会话持久化服务。"""

    settings = Settings.from_env()
    return SessionStorageService(root_dir=Path(settings.session_storage_dir).expanduser())


def _thread_config(
    *,
    project_id: str,
    thread_id: str,
    tools_enabled: bool = False,
    tool_settings: dict[str, object] | None = None,
) -> dict[str, Any]:
    resolved_project_id = str(project_id or "").strip() or DEFAULT_PROJECT_ID
    resolved_thread_id = str(thread_id or "").strip() or DEFAULT_THREAD_ID
    normalized_settings = dict(tool_settings or {})
    return {
        "configurable": {
            "project_id": resolved_project_id,
            "thread_id": resolved_thread_id,
            "tools_enabled": tools_enabled,
            **normalized_settings,
        }
    }


def _coerce_message(message: ChatMessageInput) -> BaseMessage:
    if message.type in {"human", "user"}:
        return HumanMessage(content=message.content)
    if message.type in {"system"}:
        return SystemMessage(content=message.content)
    return AIMessage(content=message.content)


def _restore_message(message: SessionMessageRecord) -> BaseMessage:
    payload = {
        "content": message.content,
        "id": message.id,
        "additional_kwargs": dict(message.additional_kwargs or {}),
        "response_metadata": dict(message.response_metadata or {}),
    }
    message_type = str(message.type or message.role or "human").strip().lower()
    if message_type in {"human", "user"}:
        return HumanMessage(**payload)
    if message_type == "system":
        return SystemMessage(**payload)
    return AIMessage(**payload)


def _serialize_message(message: BaseMessage) -> ChatMessagePayload:
    role = getattr(message, "type", None)
    return ChatMessagePayload(
        id=getattr(message, "id", None),
        type=role,
        role=role,
        content=message.content,
        additional_kwargs=dict(getattr(message, "additional_kwargs", {}) or {}),
        response_metadata=dict(getattr(message, "response_metadata", {}) or {}),
    )


def _serialize_interrupt(raw_interrupt: Any) -> ChatInterruptPayload:
    if isinstance(raw_interrupt, dict):
        value = raw_interrupt.get("value", raw_interrupt) or {}
        if not isinstance(value, dict):
            value = {"value": value}
        return ChatInterruptPayload(
            id=str(raw_interrupt.get("id", "")),
            value=value,
        )
    value = getattr(raw_interrupt, "value", {}) or {}
    if not isinstance(value, dict):
        value = {"value": value}
    return ChatInterruptPayload(
        id=str(getattr(raw_interrupt, "id", "")),
        value=value,
    )


def _restore_checkpoint_values(checkpoint: SessionCheckpoint | None) -> dict[str, Any]:
    if checkpoint is None:
        return {}
    return {
        "active_turn_id": checkpoint.active_turn_id,
        "iteration_count": checkpoint.iteration_count,
        "max_iterations": checkpoint.max_iterations,
        "answer_confident": checkpoint.answer_confident,
        "stop_reason": checkpoint.stop_reason,
        "processed_human_message_count": checkpoint.processed_human_message_count,
        "intervention_count": checkpoint.intervention_count,
    }


def _hydrate_graph_from_restored_session(
    *,
    project_id: str,
    thread_id: str,
    restored_messages: list[BaseMessage],
    checkpoint: SessionCheckpoint | None,
) -> None:
    config = _thread_config(project_id=project_id, thread_id=thread_id)
    snapshot = graph.get_state(config)
    existing_messages = list(dict(snapshot.values or {}).get("messages", []) or [])
    if existing_messages:
        return
    update: dict[str, Any] = {"messages": restored_messages}
    update.update(_restore_checkpoint_values(checkpoint))
    graph.update_state(config, update)


def _serialize_state_snapshot(
    *,
    thread_id: str,
    project_id: str,
    values: dict[str, Any] | None,
    interrupts: tuple[Any, ...] | list[Any] | None = None,
    next_nodes: tuple[str, ...] | list[str] | None = None,
) -> ChatStateResponse:
    state_values = values or {}
    raw_messages = list(state_values.get("messages", []) or [])
    interrupt_payload = None
    effective_interrupts = list(interrupts or ())
    if not effective_interrupts and state_values.get("__interrupt__"):
        effective_interrupts = list(state_values.get("__interrupt__", ()) or ())
    if effective_interrupts:
        interrupt_payload = _serialize_interrupt(effective_interrupts[0])
    return ChatStateResponse(
        thread_id=thread_id,
        project_id=project_id,
        messages=[_serialize_message(message) for message in raw_messages],
        interrupt=interrupt_payload,
        next_nodes=list(next_nodes or []),
    )


def _session_restore_response(
    *,
    session_id: str,
    project_id: str,
    thread_id: str,
    values: dict[str, Any] | None,
    interrupts: tuple[Any, ...] | list[Any] | None = None,
    next_nodes: tuple[str, ...] | list[str] | None = None,
    checkpoint: dict[str, object] | None = None,
) -> SessionRestoreResponse:
    payload = _serialize_state_snapshot(
        thread_id=thread_id,
        project_id=project_id,
        values=values,
        interrupts=interrupts,
        next_nodes=next_nodes,
    )
    return SessionRestoreResponse(
        session_id=session_id,
        thread_id=payload.thread_id,
        project_id=payload.project_id,
        messages=payload.messages,
        interrupt=payload.interrupt,
        next_nodes=payload.next_nodes,
        checkpoint=checkpoint,
    )


def _session_snapshot_response(
    *,
    session_id: str,
    project_id: str,
    thread_id: str,
    values: dict[str, Any] | None,
    interrupts: tuple[Any, ...] | list[Any] | None = None,
    next_nodes: tuple[str, ...] | list[str] | None = None,
    checkpoint: dict[str, object] | None = None,
) -> ChatSessionSnapshotResponse:
    payload = _serialize_state_snapshot(
        thread_id=thread_id,
        project_id=project_id,
        values=values,
        interrupts=interrupts,
        next_nodes=next_nodes,
    )
    return ChatSessionSnapshotResponse(
        session_id=session_id,
        thread_id=payload.thread_id,
        project_id=payload.project_id,
        turns=build_turns_from_messages(list(values.get("messages", []) or []) if values else []),
        interrupt=payload.interrupt,
        next_nodes=payload.next_nodes,
        checkpoint=checkpoint,
    )


def _sse_frame(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _coerce_graph_input(request: ChatRunRequest) -> dict[str, Any] | Command | None:
    if request.command is not None:
        resume_value = (
            request.command.resume.model_dump()
            if hasattr(request.command.resume, "model_dump")
            else request.command.resume
        )
        if resume_value is None:
            return None
        if request.command.update is not None and request.command.update.messages:
            if not isinstance(resume_value, dict):
                resume_value = {"value": resume_value}
            resume_value = dict(resume_value)
            resume_value["pending_messages"] = [
                message.model_dump()
                if hasattr(message, "model_dump")
                else {"type": message.type, "content": message.content}
                for message in request.command.update.messages
            ]
        return Command(resume=resume_value)

    raw_input = request.input or {}
    raw_messages = list(raw_input.get("messages", []) or [])
    if not raw_messages:
        return None
    return {
        "messages": [
            _coerce_message(ChatMessageInput.model_validate(message))
            for message in raw_messages
        ]
    }


def _apply_command_update(request: ChatRunRequest) -> None:
    if request.command is None or request.command.update is None:
        return

    messages = [
        _coerce_message(message)
        for message in request.command.update.messages
    ]
    if not messages:
        return

    graph.update_state(
        _thread_config(project_id=request.project_id, thread_id=request.thread_id),
        {"messages": messages},
    )


def _persist_session_snapshot(
    *,
    request: ChatRunRequest,
    snapshot: ChatStateResponse,
    values: dict[str, Any],
) -> None:
    service = get_session_storage()
    restored = service.load_session(
        project_id=request.project_id,
        session_id=request.thread_id,
    )
    # Persist tool trace messages as well so restored sessions can rebuild
    # the reasoning panel from storage.
    persistable = [
        m
        for m in snapshot.messages
        if (m.role or m.type) in {"human", "user", "ai", "assistant", "tool", "system"}
    ]
    existing_count = len(restored.messages)
    for message in persistable[existing_count:]:
        service.append_message(
            project_id=request.project_id,
            session_id=request.thread_id,
            role=message.role,
            message_id=message.id,
            content=message.content,
            additional_kwargs=message.additional_kwargs,
            response_metadata=message.response_metadata,
            message_type=message.type,
        )

    service.write_checkpoint(
        project_id=request.project_id,
        session_id=request.thread_id,
        checkpoint=SessionCheckpoint(
            session_id=request.thread_id,
            project_id=request.project_id,
            thread_id=request.thread_id,
            updated_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            interrupt=snapshot.interrupt.model_dump() if snapshot.interrupt else None,
            next_nodes=list(snapshot.next_nodes or []),
            resume_capable=bool(snapshot.interrupt or snapshot.next_nodes),
            active_turn_id=str(values.get("active_turn_id") or ""),
            iteration_count=int(values.get("iteration_count", 0) or 0),
            max_iterations=int(values.get("max_iterations", 0) or 0),
            answer_confident=bool(values.get("answer_confident", False)),
            stop_reason=str(values.get("stop_reason") or ""),
            processed_human_message_count=int(values.get("processed_human_message_count", 0) or 0),
            intervention_count=int(values.get("intervention_count", 0) or 0),
        ),
    )


@router.get("/state", response_model=ChatStateResponse)
def get_chat_state(
    *,
    project_id: str = Query(..., description="Target project identifier"),
    thread_id: str = Query(..., description="Graph thread identifier"),
) -> ChatStateResponse:
    snapshot = graph.get_state(_thread_config(project_id=project_id, thread_id=thread_id))
    return _serialize_state_snapshot(
        thread_id=thread_id,
        project_id=project_id,
        values=dict(snapshot.values or {}),
        interrupts=list(snapshot.interrupts or ()),
        next_nodes=list(snapshot.next or ()),
    )


@session_router.get("/sessions", response_model=list[SessionSummaryResponse])
def list_sessions(
    *,
    project_id: str = Query(..., description="Target project identifier"),
) -> list[SessionSummaryResponse]:
    summaries = get_session_storage().list_sessions(project_id=project_id)
    return [
        SessionSummaryResponse(
            session_id=item.session_id,
            project_id=item.project_id,
            title=item.title,
            updated_at=item.updated_at,
            message_count=item.message_count,
            resume_capable=item.resume_capable,
        )
        for item in summaries
    ]


@session_router.get("/sessions/{session_id}", response_model=SessionRestoreResponse)
def restore_session(
    *,
    session_id: str,
    project_id: str = Query(..., description="Target project identifier"),
) -> SessionRestoreResponse:
    restored = get_session_storage().load_session(project_id=project_id, session_id=session_id)
    restored_messages = [_restore_message(message) for message in restored.messages]
    _hydrate_graph_from_restored_session(
        project_id=project_id,
        thread_id=restored.thread_id,
        restored_messages=restored_messages,
        checkpoint=restored.checkpoint,
    )
    return _session_restore_response(
        session_id=session_id,
        project_id=project_id,
        thread_id=restored.thread_id,
        values={"messages": restored_messages},
        interrupts=[restored.checkpoint.interrupt] if restored.checkpoint and restored.checkpoint.interrupt else [],
        next_nodes=restored.checkpoint.next_nodes if restored.checkpoint else [],
        checkpoint=restored.checkpoint.to_dict() if restored.checkpoint else None,
    )


@session_router.get("/sessions/{session_id}/snapshot", response_model=ChatSessionSnapshotResponse)
def restore_session_snapshot(
    *,
    session_id: str,
    project_id: str = Query(..., description="Target project identifier"),
) -> ChatSessionSnapshotResponse:
    restored = get_session_storage().load_session(project_id=project_id, session_id=session_id)
    restored_messages = [_restore_message(message) for message in restored.messages]
    _hydrate_graph_from_restored_session(
        project_id=project_id,
        thread_id=restored.thread_id,
        restored_messages=restored_messages,
        checkpoint=restored.checkpoint,
    )
    return _session_snapshot_response(
        session_id=session_id,
        project_id=project_id,
        thread_id=restored.thread_id,
        values={"messages": restored_messages},
        interrupts=[restored.checkpoint.interrupt] if restored.checkpoint and restored.checkpoint.interrupt else [],
        next_nodes=restored.checkpoint.next_nodes if restored.checkpoint else [],
        checkpoint=restored.checkpoint.to_dict() if restored.checkpoint else None,
    )


@session_router.delete("/sessions/{session_id}")
def delete_session(
    *,
    session_id: str,
    project_id: str = Query(..., description="Target project identifier"),
) -> dict[str, bool]:
    deleted = get_session_storage().delete_session(project_id=project_id, session_id=session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"deleted": True}


@session_router.get(
    "/sessions/{session_id}/workers/{agent_id}",
    response_model=list[WorkerEventResponse],
)
def get_worker_events(
    *,
    session_id: str,
    agent_id: str,
    project_id: str = Query(..., description="Target project identifier"),
) -> list[WorkerEventResponse]:
    events = get_session_storage().load_worker_events(
        project_id=project_id,
        session_id=session_id,
        agent_id=agent_id,
    )
    return [
        WorkerEventResponse(
            event_id=item.event_id,
            session_id=item.session_id,
            project_id=item.project_id,
            agent_id=item.agent_id,
            worker_type=item.worker_type,
            kind=item.kind,
            payload=item.payload,
            created_at=item.created_at,
        )
        for item in events
    ]


@router.post("/stream")
async def stream_chat_run(request: ChatRunRequest) -> StreamingResponse:
    config = _thread_config(
        project_id=request.project_id,
        thread_id=request.thread_id,
        tools_enabled=request.tools_enabled,
        tool_settings=request.tool_settings,
    )
    graph_input = _coerce_graph_input(request)

    async def event_stream():
        started_turn_ids: set[str] = set()
        completed_turn_ids: set[str] = set()
        try:
            _apply_command_update(request)
            baseline_snapshot = graph.get_state(config)
            previous_messages: list[BaseMessage] = list(dict(baseline_snapshot.values or {}).get("messages", []) or [])
            async for state in graph.astream(graph_input, config=config, stream_mode="values"):
                values = dict(state or {})
                interrupts = list(values.get("__interrupt__", ()) or ())
                raw_messages = list(values.get("messages", []) or [])
                for index, message in enumerate(raw_messages[len(previous_messages):], start=len(previous_messages)):
                    role = str(getattr(message, "type", "") or "")
                    metadata = dict(getattr(message, "additional_kwargs", {}) or {}).get("metadata", {}) or {}
                    if role == "tool":
                        turn_id = str(metadata.get("turn_id") or "")
                        if turn_id and turn_id not in started_turn_ids:
                            started_turn_ids.add(turn_id)
                            yield _sse_frame(
                                "assistant_turn_started",
                                {
                                    "turn_id": turn_id,
                                    "created_at": str(metadata.get("created_at") or ""),
                                },
                            )
                        trace_event = serialize_trace_message_event(message, index=index)
                        if trace_event is not None:
                            started_payload, delta_payload, completed_payload = trace_event
                            yield _sse_frame("trace_item_started", started_payload)
                            if delta_payload.get("delta"):
                                yield _sse_frame("trace_item_delta", delta_payload)
                            yield _sse_frame("trace_item_completed", completed_payload)
                    elif role == "ai":
                        if str(metadata.get("artifact_type") or "") != "answer":
                            continue
                        turn_id = str(metadata.get("turn_id") or getattr(message, "id", "") or f"turn_{index}")
                        if turn_id not in started_turn_ids:
                            started_turn_ids.add(turn_id)
                            yield _sse_frame(
                                "assistant_turn_started",
                                {
                                    "turn_id": turn_id,
                                    "created_at": str(metadata.get("created_at") or ""),
                                },
                            )
                        content = getattr(message, "content", "")
                        if content:
                            yield _sse_frame(
                                "answer_delta",
                                {
                                    "turn_id": turn_id,
                                    "delta": content,
                                },
                            )
                if interrupts:
                    yield _sse_frame("interrupt", _serialize_interrupt(interrupts[0]).model_dump())
                previous_messages = raw_messages

            snapshot = graph.get_state(config)
            values = dict(snapshot.values or {})
            payload = _serialize_state_snapshot(
                thread_id=request.thread_id,
                project_id=request.project_id,
                values=values,
                interrupts=list(snapshot.interrupts or ()),
                next_nodes=list(snapshot.next or ()),
            )
            _persist_session_snapshot(
                request=request,
                snapshot=payload,
                values=values,
            )
            turns = build_turns_from_messages(list(values.get("messages", []) or []))
            for turn in turns:
                if turn.role != "assistant" or not turn.answer_text or turn.id in completed_turn_ids:
                    continue
                completed_turn_ids.add(turn.id)
                yield _sse_frame(
                    "turn_completed",
                    {
                        "turn_id": turn.id,
                        "summary": turn.summary,
                        "citations": turn.citations,
                        "web_sources": turn.web_sources,
                        "tool_sources": turn.tool_sources,
                        "turn": build_assistant_turn_payload(turn),
                    },
                )
            if payload.interrupt is not None:
                yield _sse_frame("interrupt", payload.interrupt.model_dump())
        except Exception as exc:  # noqa: BLE001
            logger.exception("Chat stream failed.")
            try:
                from orchestration.debug_logger import log_error
                log_error(turn_id="", stage="chat_stream", error=str(exc))
            except Exception:
                pass
            yield _sse_frame("error", {"message": str(exc)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/guidance")
async def queue_chat_guidance(request: ChatGuidanceRequest) -> dict[str, bool]:
    content = request.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="Guidance content cannot be empty.")
    push_guidance_message(
        project_id=request.project_id,
        thread_id=request.thread_id,
        content=content,
    )
    return {"queued": True}
