from __future__ import annotations

from dataclasses import dataclass
import importlib
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from langchain_core.messages import HumanMessage
from langchain_core.messages import ToolMessage

from session_storage.service import SessionStorageService


@dataclass
class _FakeSnapshot:
    values: dict[str, Any]
    interrupts: tuple[Any, ...] = ()
    next: tuple[str, ...] = ()


def _loop_status_message() -> ToolMessage:
    return ToolMessage(
        content="MainRoute prepared retrieval_agent, tool_agent.",
        tool_call_id="tool_turn-1",
        name="loop_status",
        additional_kwargs={
            "name": "loop_status",
            "metadata": {
                "turn_id": "turn-1",
                "artifact_type": "loop_status",
                "phase": "main_route_complete",
                "summary": "MainRoute prepared retrieval_agent, tool_agent.",
            },
        },
    )


def _agent_task_message() -> ToolMessage:
    return ToolMessage(
        content="tool_agent task: 查询最新论文",
        tool_call_id="tool_turn-1",
        name="agent_task",
        additional_kwargs={
            "name": "agent_task",
            "metadata": {
                "turn_id": "turn-1",
                "artifact_type": "agent_task",
                "task": {
                    "agent_name": "tool_agent",
                    "query": "查询最新论文",
                    "reason": "Need external or tool-based information.",
                },
            },
        },
    )


def _assistant_message() -> AIMessage:
    metadata = {
        "turn_id": "turn-1",
        "artifact_type": "answer",
        "summary": {
            "done": "已给出答复",
            "next": "",
            "pending": "",
        },
    }
    return AIMessage(
        content="你好，我还记得这个会话。",
        additional_kwargs={
            "name": "answer",
            "metadata": metadata,
        },
        response_metadata=metadata,
    )


class _FakeGraph:
    def __init__(self) -> None:
        self._states = [
            {
                "messages": [
                    HumanMessage(content="你好"),
                    _loop_status_message(),
                    _agent_task_message(),
                ],
                "active_turn_id": "turn-1",
                "iteration_count": 1,
                "max_iterations": 5,
                "answer_confident": False,
                "stop_reason": "",
                "processed_human_message_count": 1,
                "intervention_count": 0,
            },
            {
                "messages": [
                    HumanMessage(content="你好"),
                    _loop_status_message(),
                    _agent_task_message(),
                    _assistant_message(),
                ],
                "active_turn_id": "turn-1",
                "iteration_count": 1,
                "max_iterations": 5,
                "answer_confident": True,
                "stop_reason": "",
                "processed_human_message_count": 1,
                "intervention_count": 0,
            },
        ]
        self._state = self._states[-1]

    def update_state(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def get_state(self, *_args: Any, **_kwargs: Any) -> _FakeSnapshot:
        return _FakeSnapshot(values=self._state, next=())

    async def astream(self, *_args: Any, **_kwargs: Any):
        for state in self._states:
            yield dict(state)


class _FakeInterruptGraph(_FakeGraph):
    def __init__(self) -> None:
        super().__init__()
        self._state = {
            "messages": [HumanMessage(content="你好")],
            "active_turn_id": "turn-1",
            "iteration_count": 1,
            "max_iterations": 5,
            "answer_confident": False,
            "stop_reason": "",
            "processed_human_message_count": 1,
            "intervention_count": 0,
            "__interrupt__": (
                {
                    "id": "interrupt-1",
                    "value": {
                        "phase": "guidance_gate_pre_assess",
                        "question": "还要继续吗？",
                    },
                },
            ),
        }

    async def astream(self, *_args: Any, **_kwargs: Any):
        yield dict(self._state)


def _build_client(storage_root: Path) -> tuple[TestClient, SessionStorageService]:
    chat_module = importlib.import_module("api.chat")
    service = SessionStorageService(root_dir=storage_root)
    app = FastAPI()
    app.include_router(chat_module.router)
    app.include_router(chat_module.session_router)
    client = TestClient(app)
    return client, service


def test_chat_stream_emits_event_protocol_and_snapshot_endpoint() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        client, service = _build_client(Path(temp_dir) / "sessions")
        chat_module = importlib.import_module("api.chat")

        with patch.object(chat_module, "graph", _FakeGraph()), patch.object(
            chat_module,
            "get_session_storage",
            return_value=service,
        ):
            response = client.post(
                "/chat/stream",
                json={
                    "project_id": "project-a",
                    "thread_id": "thread-1",
                    "input": {"messages": [{"type": "human", "content": "你好"}]},
                },
            )

            assert response.status_code == 200
            assert "event: assistant_turn_started" in response.text
            assert "event: trace_item_started" in response.text
            assert "event: trace_item_delta" in response.text
            assert "event: answer_delta" in response.text
            assert "event: turn_completed" in response.text

            sessions = client.get("/sessions", params={"project_id": "project-a"})
            restored = client.get("/sessions/thread-1/snapshot", params={"project_id": "project-a"})

            assert sessions.status_code == 200
            assert restored.status_code == 200
            assert sessions.json()[0]["session_id"] == "thread-1"
            assert restored.json()["thread_id"] == "thread-1"
            turns = restored.json()["turns"]
            assert turns[0]["role"] == "user"
            assert turns[0]["content"] == "你好"
            assert turns[1]["role"] == "assistant"
            assert turns[1]["answer_text"] == "你好，我还记得这个会话。"
            assert turns[1]["trace_items"][0]["kind"] == "reasoning"
            assert turns[1]["trace_items"][1]["kind"] == "tool_call"


def test_session_worker_logs_endpoint_returns_independent_worker_records() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        client, service = _build_client(Path(temp_dir) / "sessions")
        chat_module = importlib.import_module("api.chat")
        service.append_worker_event(
            project_id="project-a",
            session_id="thread-1",
            agent_id="worker-1",
            worker_type="tool",
            kind="worker_result",
            payload={"status": "ok"},
        )

        with patch.object(chat_module, "get_session_storage", return_value=service):
            response = client.get(
                "/sessions/thread-1/workers/worker-1",
                params={"project_id": "project-a"},
            )

            assert response.status_code == 200
            assert response.json()[0]["worker_type"] == "tool"


def test_chat_stream_emits_interrupt_event_when_graph_pauses() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        client, service = _build_client(Path(temp_dir) / "sessions")
        chat_module = importlib.import_module("api.chat")

        with patch.object(chat_module, "graph", _FakeInterruptGraph()), patch.object(
            chat_module,
            "get_session_storage",
            return_value=service,
        ):
            response = client.post(
                "/chat/stream",
                json={
                    "project_id": "project-a",
                    "thread_id": "thread-1",
                    "input": {"messages": [{"type": "human", "content": "你好"}]},
                },
            )

            assert response.status_code == 200
            assert "event: interrupt" in response.text
