from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from contracts import AgentResult
from contracts import AgentTask

try:
    from langchain_core.messages import AIMessage
    from langchain_core.messages import BaseMessage
    from langchain_core.messages import HumanMessage
    from langchain_core.messages import ToolMessage
except ImportError:  # pragma: no cover
    AIMessage = Any  # type: ignore[assignment]
    BaseMessage = Any  # type: ignore[assignment]
    HumanMessage = Any  # type: ignore[assignment]
    ToolMessage = Any  # type: ignore[assignment]


def message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return "".join(parts)
    return str(content)


def message_meta(message: BaseMessage) -> dict[str, Any]:
    return dict(getattr(message, "additional_kwargs", {}) or {}).get("metadata", {}) or {}


def message_name(message: BaseMessage) -> str:
    additional_kwargs = dict(getattr(message, "additional_kwargs", {}) or {})
    return str(additional_kwargs.get("name") or getattr(message, "name", "") or "")


def message_id(message: BaseMessage) -> str:
    explicit_id = str(getattr(message, "id", "") or "")
    if explicit_id:
        return explicit_id
    metadata = message_meta(message)
    turn_id = str(metadata.get("turn_id", "") or "")
    name = message_name(message)
    if turn_id and name:
        return f"{name}_{turn_id}"
    return ""


def latest_human_text(messages: list[BaseMessage]) -> str:
    for message in reversed(messages):
        if hasattr(HumanMessage, "is_instance") and HumanMessage.is_instance(message):
            return message_text(message.content)
        if getattr(message, "type", "") == "human":
            return message_text(message.content)
    raise ValueError("No human message found in graph state")


def human_messages(messages: list[BaseMessage]) -> list[BaseMessage]:
    return [message for message in messages if getattr(message, "type", "") == "human"]


def latest_messages_by_artifact(
    messages: list[BaseMessage],
    artifact_type: str,
    *,
    turn_id: str,
) -> list[BaseMessage]:
    return [
        message
        for message in messages
        if message_meta(message).get("artifact_type") == artifact_type
        and str(message_meta(message).get("turn_id") or "") == turn_id
    ]


def latest_tool_message(
    messages: list[BaseMessage],
    name: str,
    *,
    turn_id: str | None = None,
) -> BaseMessage | None:
    for message in reversed(messages):
        if getattr(message, "type", "") != "tool" or message_name(message) != name:
            continue
        if turn_id is not None and str(message_meta(message).get("turn_id") or "") != turn_id:
            continue
        return message
    return None


def stringify_for_prompt(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, indent=2)
    except TypeError:
        return str(value)


def coerce_tool_call_args(tool_call: dict[str, Any]) -> dict[str, Any]:
    args = tool_call.get("args", {})
    if isinstance(args, dict):
        return args
    if isinstance(args, str) and args.strip():
        try:
            parsed = json.loads(args)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return {}
    return {}


def extract_tool_calls(message: BaseMessage) -> list[dict[str, Any]]:
    tool_calls = list(getattr(message, "tool_calls", []) or [])
    if tool_calls:
        return tool_calls
    additional_kwargs = dict(getattr(message, "additional_kwargs", {}) or {})
    return list(additional_kwargs.get("tool_calls", []) or [])


def result_status(result: dict[str, Any]) -> str:
    return str(result.get("status") or "")


def dispatch_schema() -> list[dict[str, object]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "dispatch_specialists",
                "description": "Choose whether to launch memory recall and/or retrieval specialist tasks.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "run_memory": {"type": "boolean"},
                        "memory_query": {"type": "string"},
                        "memory_reason": {"type": "string"},
                        "run_retrieval": {"type": "boolean"},
                        "retrieval_query": {"type": "string"},
                        "retrieval_reason": {"type": "string"},
                    },
                    "required": [
                        "run_memory",
                        "memory_query",
                        "memory_reason",
                        "run_retrieval",
                        "retrieval_query",
                        "retrieval_reason",
                    ],
                },
            },
        }
    ]


def build_tool_message(
    *,
    turn_id: str,
    name: str,
    content: str,
    metadata: dict[str, object],
    tool_call_id: str | None = None,
) -> ToolMessage:
    message_metadata = {"turn_id": turn_id, **metadata}
    return ToolMessage(
        id=f"{name}_{turn_id}_{uuid4().hex[:8]}",
        tool_call_id=tool_call_id or f"tool_{turn_id}",
        name=name,
        content=content,
        additional_kwargs={"name": name, "metadata": message_metadata},
        artifact=message_metadata,
    )


def build_assistant_message(
    *,
    turn_id: str,
    content: str,
    metadata: dict[str, object],
    raw_id: str | None = None,
    additional_kwargs: dict[str, Any] | None = None,
    response_metadata: dict[str, Any] | None = None,
) -> AIMessage:
    message_metadata = {"turn_id": turn_id, **metadata}
    assistant_kwargs = {"name": "answer", "metadata": message_metadata, **dict(additional_kwargs or {})}
    assistant_response_metadata = {**dict(response_metadata or {}), **message_metadata}
    return AIMessage(
        id=raw_id or f"answer_{turn_id}_{uuid4().hex[:8]}",
        content=content,
        additional_kwargs=assistant_kwargs,
        response_metadata=assistant_response_metadata,
    )


def build_agent_task_message(*, turn_id: str, task: AgentTask) -> ToolMessage:
    return build_tool_message(
        turn_id=turn_id,
        name="agent_task",
        content=f"{task.agent_name} task: {task.query}",
        metadata={"artifact_type": "agent_task", "task": task.to_dict(), "reusable": False},
    )


def build_agent_result_message(*, turn_id: str, result: AgentResult) -> ToolMessage:
    return build_tool_message(
        turn_id=turn_id,
        name=f"{result.agent_name}_result",
        content=result.summary,
        metadata={"artifact_type": "agent_result", "result": result.to_dict(), "reusable": True},
    )


def build_intervention_message(
    *,
    turn_id: str,
    content: str,
    project_id: str,
    thread_id: str | None,
) -> HumanMessage:
    return HumanMessage(
        id=f"intervention_{turn_id}_{uuid4().hex[:8]}",
        content=content,
        additional_kwargs={
            "name": "intervention",
            "metadata": {
                "artifact_type": "intervention",
                "turn_id": turn_id,
                "project_id": project_id,
                "thread_id": thread_id,
            },
        },
    )


def build_loop_status_message(
    *,
    turn_id: str,
    phase: str,
    summary: str,
    iteration_count: int,
    metadata: dict[str, object] | None = None,
) -> ToolMessage:
    extra = dict(metadata or {})
    return build_tool_message(
        turn_id=turn_id,
        name="loop_status",
        content=summary,
        metadata={
            "artifact_type": "loop_status",
            "phase": phase,
            "iteration_count": iteration_count,
            "summary": summary,
            "reusable": False,
            **extra,
        },
    )


def _message_text(content: Any) -> str:
    return message_text(content)


def _message_meta(message: BaseMessage) -> dict[str, Any]:
    return message_meta(message)


def _message_name(message: BaseMessage) -> str:
    return message_name(message)


def _message_id(message: BaseMessage) -> str:
    return message_id(message)


def _latest_human_text(messages: list[BaseMessage]) -> str:
    return latest_human_text(messages)


def _human_messages(messages: list[BaseMessage]) -> list[BaseMessage]:
    return human_messages(messages)


def _latest_messages_by_artifact(
    messages: list[BaseMessage],
    artifact_type: str,
    *,
    turn_id: str,
) -> list[BaseMessage]:
    return latest_messages_by_artifact(messages, artifact_type, turn_id=turn_id)


def _latest_tool_message(
    messages: list[BaseMessage],
    name: str,
    *,
    turn_id: str | None = None,
) -> BaseMessage | None:
    return latest_tool_message(messages, name, turn_id=turn_id)


def _stringify_for_prompt(value: Any) -> str:
    return stringify_for_prompt(value)


def _coerce_tool_call_args(tool_call: dict[str, Any]) -> dict[str, Any]:
    return coerce_tool_call_args(tool_call)


def _extract_tool_calls(message: BaseMessage) -> list[dict[str, Any]]:
    return extract_tool_calls(message)


def _result_status(result: dict[str, Any]) -> str:
    return result_status(result)


def _dispatch_schema() -> list[dict[str, object]]:
    return dispatch_schema()


def _build_tool_message(
    *,
    turn_id: str,
    name: str,
    content: str,
    metadata: dict[str, object],
    tool_call_id: str | None = None,
) -> ToolMessage:
    return build_tool_message(
        turn_id=turn_id,
        name=name,
        content=content,
        metadata=metadata,
        tool_call_id=tool_call_id,
    )


def _build_assistant_message(
    *,
    turn_id: str,
    content: str,
    metadata: dict[str, object],
    raw_id: str | None = None,
    additional_kwargs: dict[str, Any] | None = None,
    response_metadata: dict[str, Any] | None = None,
) -> AIMessage:
    return build_assistant_message(
        turn_id=turn_id,
        content=content,
        metadata=metadata,
        raw_id=raw_id,
        additional_kwargs=additional_kwargs,
        response_metadata=response_metadata,
    )


def _build_agent_task_message(*, turn_id: str, task: AgentTask) -> ToolMessage:
    return build_agent_task_message(turn_id=turn_id, task=task)


def _build_agent_result_message(*, turn_id: str, result: AgentResult) -> ToolMessage:
    return build_agent_result_message(turn_id=turn_id, result=result)


def _build_intervention_message(
    *,
    turn_id: str,
    content: str,
    project_id: str,
    thread_id: str | None,
) -> HumanMessage:
    return build_intervention_message(
        turn_id=turn_id,
        content=content,
        project_id=project_id,
        thread_id=thread_id,
    )


def _build_loop_status_message(
    *,
    turn_id: str,
    phase: str,
    summary: str,
    iteration_count: int,
    metadata: dict[str, object] | None = None,
) -> ToolMessage:
    return build_loop_status_message(
        turn_id=turn_id,
        phase=phase,
        summary=summary,
        iteration_count=iteration_count,
        metadata=metadata,
    )
