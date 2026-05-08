"""Helpers for projecting LangChain messages into UI turns and trace events."""

from __future__ import annotations

from typing import Any

from api.schemas import ChatTraceItemResponse
from api.schemas import ChatTurnResponse
from orchestration.graph_messages import message_meta
from orchestration.graph_messages import message_name
from orchestration.graph_messages import message_text

try:
    from langchain_core.messages import BaseMessage
except ImportError:  # pragma: no cover
    BaseMessage = Any  # type: ignore[assignment]


def build_turns_from_messages(messages: list[BaseMessage]) -> list[ChatTurnResponse]:
    turns: list[ChatTurnResponse] = []
    assistant_by_turn: dict[str, ChatTurnResponse] = {}

    for index, message in enumerate(messages):
        role = str(getattr(message, "type", "") or "")
        metadata = dict(message_meta(message))
        artifact_type = str(metadata.get("artifact_type") or "")
        content = message_text(getattr(message, "content", ""))
        created_at = str(metadata.get("created_at") or "")
        raw_id = str(getattr(message, "id", "") or f"msg-{index}")

        if role in {"human", "user"}:
            if artifact_type in {"question", "intervention"}:
                continue
            turns.append(
                ChatTurnResponse(
                    id=raw_id,
                    role="user",
                    content=content,
                    created_at=created_at,
                )
            )
            continue

        if role == "tool":
            turn_id = str(metadata.get("turn_id") or "")
            if not turn_id:
                continue
            assistant_turn = assistant_by_turn.get(turn_id)
            if assistant_turn is None:
                assistant_turn = ChatTurnResponse(
                    id=turn_id,
                    role="assistant",
                    status="streaming",
                    collapsed=False,
                    created_at=created_at,
                )
                assistant_by_turn[turn_id] = assistant_turn
                turns.append(assistant_turn)
            trace_item = build_trace_item(message, index=index)
            if trace_item is not None:
                assistant_turn.trace_items.append(trace_item)
            continue

        if role == "ai":
            turn_id = str(metadata.get("turn_id") or raw_id)
            assistant_turn = assistant_by_turn.get(turn_id)
            if assistant_turn is None:
                assistant_turn = ChatTurnResponse(
                    id=turn_id,
                    role="assistant",
                    created_at=created_at,
                )
                assistant_by_turn[turn_id] = assistant_turn
                turns.append(assistant_turn)
            assistant_turn.answer_text = content
            assistant_turn.status = "completed"
            assistant_turn.collapsed = bool(assistant_turn.trace_items)
            assistant_turn.summary = _normalize_summary(metadata.get("summary"))
            assistant_turn.citations = _normalize_list_of_dicts(metadata.get("citations"))
            assistant_turn.asset_citations = _normalize_list_of_dicts(metadata.get("asset_citations"))
            assistant_turn.asset_sources = _normalize_list_of_dicts(metadata.get("asset_sources"))
            assistant_turn.web_sources = _normalize_list_of_dicts(metadata.get("web_sources"))
            assistant_turn.tool_sources = _normalize_list_of_dicts(metadata.get("tool_sources"))

    return turns


def build_trace_item(message: BaseMessage, *, index: int) -> ChatTraceItemResponse | None:
    metadata = dict(message_meta(message))
    artifact_type = str(metadata.get("artifact_type") or "")
    content = message_text(getattr(message, "content", ""))
    if not content and artifact_type not in {"agent_task"}:
        return None

    name = message_name(message)
    kind = "reasoning"
    title = name
    if artifact_type == "agent_task":
        kind = "tool_call"
        task = dict(metadata.get("task", {}) or {})
        title = str(task.get("agent_name") or name or "tool")
    elif artifact_type == "agent_result":
        kind = "tool_result"
        result = dict(metadata.get("result", {}) or {})
        title = str(result.get("agent_name") or name or "tool")
    elif artifact_type == "loop_status":
        title = str(metadata.get("phase") or "思考")
    elif artifact_type == "memory_result":
        title = "记忆检索"
    elif artifact_type == "short_term_context":
        title = "短时上下文"
    elif artifact_type == "workspace_tool_result":
        kind = "tool_result"
        title = str(metadata.get("tool_name") or "工具结果")
    elif artifact_type == "retrieval_reasoning":
        title = "检索思路"
    elif artifact_type == "retrieval_tool_call":
        kind = "tool_call"
        title = str(metadata.get("tool_name") or "检索工具")
    elif artifact_type == "retrieval_tool_result":
        kind = "tool_result"
        title = str(metadata.get("tool_name") or "检索结果")

    return ChatTraceItemResponse(
        id=str(getattr(message, "id", "") or f"trace-{index}"),
        kind=kind,
        title=title,
        text=content,
        status="completed",
        created_at=str(metadata.get("created_at") or ""),
    )


def serialize_trace_message_event(message: BaseMessage, *, index: int) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]] | None:
    metadata = dict(message_meta(message))
    turn_id = str(metadata.get("turn_id") or "")
    if not turn_id:
        return None
    trace_item = build_trace_item(message, index=index)
    if trace_item is None:
        return None
    item_payload = trace_item.model_dump()
    return (
        {"turn_id": turn_id, "item": item_payload},
        {"turn_id": turn_id, "item_id": trace_item.id, "delta": trace_item.text},
        {"turn_id": turn_id, "item_id": trace_item.id},
    )


def build_assistant_turn_payload(turn: ChatTurnResponse) -> dict[str, Any]:
    return turn.model_dump()


def _normalize_summary(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {
        "done": str(value.get("done") or ""),
        "next": str(value.get("next") or ""),
        "pending": str(value.get("pending") or ""),
    }


def _normalize_list_of_dicts(value: Any) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    items: list[dict[str, object]] = []
    for item in value:
        if isinstance(item, dict):
            items.append(dict(item))
    return items
