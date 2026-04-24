"""FastAPI chat bridge that drives the compiled LangGraph directly."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter
from fastapi import HTTPException
from fastapi import Query
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage
from langchain_core.messages import BaseMessage
from langchain_core.messages import HumanMessage
from langchain_core.messages import SystemMessage
from langgraph.types import Command

from api.schemas import ChatInterruptPayload
from api.schemas import ChatMessageInput
from api.schemas import ChatMessagePayload
from api.schemas import ChatRunRequest
from api.schemas import ChatStateResponse
from orchestration.supervisor import graph


router = APIRouter(prefix="/chat", tags=["chat"])


def _thread_config(*, project_id: str, thread_id: str) -> dict[str, Any]:
    return {
        "configurable": {
            "project_id": project_id,
            "thread_id": thread_id,
        }
    }


def _coerce_message(message: ChatMessageInput) -> BaseMessage:
    if message.type in {"human", "user"}:
        return HumanMessage(content=message.content)
    if message.type in {"system"}:
        return SystemMessage(content=message.content)
    return AIMessage(content=message.content)


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
    value = getattr(raw_interrupt, "value", {}) or {}
    if not isinstance(value, dict):
        value = {"value": value}
    return ChatInterruptPayload(
        id=str(getattr(raw_interrupt, "id", "")),
        value=value,
    )


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
    if interrupts:
        interrupt_payload = _serialize_interrupt(interrupts[0])
    return ChatStateResponse(
        thread_id=thread_id,
        project_id=project_id,
        messages=[_serialize_message(message) for message in raw_messages],
        interrupt=interrupt_payload,
        next_nodes=list(next_nodes or []),
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


@router.post("/stream")
async def stream_chat_run(request: ChatRunRequest) -> StreamingResponse:
    config = _thread_config(project_id=request.project_id, thread_id=request.thread_id)
    graph_input = _coerce_graph_input(request)

    async def event_stream():
        try:
            _apply_command_update(request)
            async for state in graph.astream(graph_input, config=config, stream_mode="values"):
                values = dict(state or {})
                interrupts = list(values.pop("__interrupt__", ()) or ())
                payload = _serialize_state_snapshot(
                    thread_id=request.thread_id,
                    project_id=request.project_id,
                    values=values,
                    interrupts=interrupts,
                )
                yield _sse_frame("state", payload.model_dump())

            snapshot = graph.get_state(config)
            payload = _serialize_state_snapshot(
                thread_id=request.thread_id,
                project_id=request.project_id,
                values=dict(snapshot.values or {}),
                interrupts=list(snapshot.interrupts or ()),
                next_nodes=list(snapshot.next or ()),
            )
            yield _sse_frame("done", payload.model_dump())
        except Exception as exc:  # noqa: BLE001
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
