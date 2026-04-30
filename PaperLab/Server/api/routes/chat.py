"""Grounded answer streaming route.

LangGraph chat/session routes still live in ``api.chat``.
"""

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from api.dependencies import get_services
from api.schemas import AgentAnswerStreamRequest

router = APIRouter()


@router.post("/agent/answer/stream")
def stream_agent_answer(payload: AgentAnswerStreamRequest) -> StreamingResponse:
    """Stream one grounded answer as server-sent events."""

    answer_question_use_case = get_services().answer_question_use_case
    if answer_question_use_case is None:
        raise HTTPException(
            status_code=503,
            detail="Agent answering is unavailable because retrieval or LLM is not configured.",
        )

    def event_stream():
        try:
            for event in answer_question_use_case.stream_answer(
                question=payload.question,
                project_id=payload.project_id,
                document_limit=payload.document_limit,
                chunk_limit=payload.chunk_limit,
                asset_limit=payload.asset_limit,
            ):
                yield f"event: {event.event}\n"
                yield f"data: {json.dumps(event.data, ensure_ascii=False)}\n\n"
        except Exception as exc:  # noqa: BLE001
            yield "event: error\n"
            yield f"data: {json.dumps({'message': str(exc)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
