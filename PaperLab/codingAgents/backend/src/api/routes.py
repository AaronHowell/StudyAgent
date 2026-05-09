"""CodingAgent API 路由。"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from agent.loop import CodingAgentLoop
from api.schemas import (
    ApprovalRequest,
    CreateSessionRequest,
    CreateSessionResponse,
    SendMessageRequest,
    SessionStateResponse,
    StepRequest,
)
from configs.settings import Settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/coding", tags=["coding-agent"])

# 全局 Agent 实例（生产环境应注入）
_agent: CodingAgentLoop | None = None


def get_agent() -> CodingAgentLoop:
    global _agent
    if _agent is None:
        settings = Settings()
        _agent = CodingAgentLoop(settings=settings)
    return _agent


# ── SSE 事件队列 ──
_event_queues: dict[str, list[asyncio.Queue]] = {}


def _get_queue(session_id: str) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue()
    _event_queues.setdefault(session_id, []).append(q)
    return q


async def _push_event(session_id: str, event: dict[str, Any]) -> None:
    queues = _event_queues.get(session_id, [])
    for q in queues:
        await q.put(event)


# ── 回调函数 ──

async def _on_action(session_id: str, action: Any) -> None:
    await _push_event(session_id, {
        "event": "action",
        "data": action.to_dict() if hasattr(action, "to_dict") else str(action),
    })


async def _on_approval(session_id: str, action: Any, result: dict) -> None:
    await _push_event(session_id, {
        "event": "approval_required",
        "data": {
            "action": action.to_dict() if hasattr(action, "to_dict") else str(action),
            "tool_name": result.get("tool_name"),
            "args": result.get("args"),
            "risk_level": result.get("risk_level"),
        },
    })


async def _on_message(session_id: str, content: str, role: str) -> None:
    await _push_event(session_id, {
        "event": "message",
        "data": {"role": role, "content": content},
    })


# ── 路由 ──

@router.post("/sessions", response_model=CreateSessionResponse)
async def create_session(payload: CreateSessionRequest) -> CreateSessionResponse:
    agent = get_agent()
    agent.on_action = _on_action
    agent.on_approval = _on_approval
    agent.on_message = _on_message

    state, sandbox = agent.create_session(
        session_id=payload.session_id,
        paper_context=payload.paper_context,
    )
    return CreateSessionResponse(session_id=state.session_id, status="created")


@router.get("/sessions/{session_id}", response_model=SessionStateResponse)
async def get_session(session_id: str) -> SessionStateResponse:
    agent = get_agent()
    state = agent.get_state(session_id)
    if state is None:
        from fastapi import HTTPException
        raise HTTPException(404, f"Session not found: {session_id}")
    return SessionStateResponse(**state.to_dict())


@router.post("/sessions/{session_id}/step")
async def run_step(session_id: str) -> SessionStateResponse:
    """执行一步 Agent 循环。"""
    agent = get_agent()
    state = await agent.step(session_id)
    return SessionStateResponse(**state.to_dict())


@router.post("/sessions/{session_id}/run")
async def run_until_blocked(session_id: str) -> SessionStateResponse:
    """持续运行直到需要审批或完成。"""
    agent = get_agent()
    state = await agent.run_until_blocked(session_id)
    return SessionStateResponse(**state.to_dict())


@router.post("/sessions/{session_id}/approve")
async def approve_action(session_id: str, payload: ApprovalRequest) -> SessionStateResponse:
    """审批一个 pending action。"""
    agent = get_agent()
    state = await agent.approve_action(session_id, payload.approved)
    return SessionStateResponse(**state.to_dict())


@router.post("/sessions/{session_id}/message")
async def send_message(session_id: str, payload: SendMessageRequest) -> SessionStateResponse:
    """用户发送消息（注入上下文）。"""
    agent = get_agent()
    state = agent.get_state(session_id)
    if state is None:
        from fastapi import HTTPException
        raise HTTPException(404, f"Session not found: {session_id}")
    # 将用户消息作为额外上下文注入
    state.paper_context += f"\n\n## User Guidance\n{payload.message}"
    return SessionStateResponse(**state.to_dict())


@router.get("/sessions/{session_id}/events")
async def stream_events(session_id: str):
    """SSE 事件流。"""
    queue = _get_queue(session_id)

    async def event_generator():
        try:
            while True:
                event = await queue.get()
                yield f"event: {event['event']}\ndata: {json.dumps(event['data'], ensure_ascii=False)}\n\n"
        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.delete("/sessions/{session_id}")
async def destroy_session(session_id: str) -> dict[str, str]:
    agent = get_agent()
    agent.destroy_session(session_id)
    _event_queues.pop(session_id, None)
    return {"status": "destroyed", "session_id": session_id}
