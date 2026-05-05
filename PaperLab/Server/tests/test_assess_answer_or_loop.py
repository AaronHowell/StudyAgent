from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from langchain_core.messages import HumanMessage

from orchestration import supervisor


class _FakeAnswerOrLoopModel:
    def __init__(self, payload: dict[str, Any], tool_calls: list[dict[str, Any]] | None = None) -> None:
        self.payload = payload
        self.tool_calls = tool_calls or []
        self.bound_tools: list[dict[str, object]] | None = None

    def bind_tools(self, tools: list[dict[str, object]]) -> "_FakeAnswerOrLoopModel":
        self.bound_tools = tools
        return self

    async def ainvoke(self, _prompt: str) -> object:
        return SimpleNamespace(
            id="answer-or-loop-1",
            content=json.dumps(self.payload, ensure_ascii=False),
            tool_calls=self.tool_calls,
        )


class _FakeRuntime:
    def __init__(self, chat_model: object) -> None:
        self.chat_model = chat_model


def _state() -> dict[str, Any]:
    return {
        "messages": [HumanMessage(content="这个问题证据够了吗？")],
        "active_turn_id": "turn-1",
        "iteration_count": 1,
        "max_iterations": 3,
        "intervention_count": 0,
        "retrieve_result": {
            "agent_name": "retrieval_agent",
            "metadata": {
                "citations": [{"document_id": "doc-1"}],
                "evidence_counts": {"document_count": 1},
            },
        },
    }


def test_assess_node_returns_answer_when_model_says_evidence_is_enough() -> None:
    model = _FakeAnswerOrLoopModel(
        {
            "answer_confident": True,
            "answer": "证据足够，最终答案。",
            "summary": {"done": "已综合证据", "next": "", "pending": ""},
            "next_tasks": [],
        }
    )

    with patch.object(supervisor, "_runtime", return_value=_FakeRuntime(model)):
        update = asyncio.run(supervisor.assess_node(_state()))

    assert model.bound_tools is not None
    assert {tool["function"]["name"] for tool in model.bound_tools} == {
        "decide_memory_write",
        "continue_evidence_loop",
    }
    assert update["answer_confident"] is True
    assert update["stop_reason"] == ""
    assert update["messages"][0].type == "ai"
    assert update["messages"][0].content == "证据足够，最终答案。"
    assert update["messages"][0].additional_kwargs["metadata"]["summary"]["done"] == "已综合证据"


def test_assess_node_records_optional_memory_tool_decision_when_answering() -> None:
    model = _FakeAnswerOrLoopModel(
        {
            "answer_confident": True,
            "answer": "证据足够，最终答案。",
            "summary": {"done": "已综合证据", "next": "", "pending": ""},
            "next_tasks": [],
        },
        tool_calls=[
            {
                "name": "decide_memory_write",
                "args": {
                    "should_write": True,
                    "memory_type": "project_fact",
                    "content": "本项目偏好 answer-or-loop 节点。",
                    "reason": "Stable project orchestration preference.",
                },
            }
        ],
    )

    with patch.object(supervisor, "_runtime", return_value=_FakeRuntime(model)):
        update = asyncio.run(supervisor.assess_node(_state()))

    metadata = update["messages"][0].additional_kwargs["metadata"]
    assert metadata["memory_write_decision"] == {
        "should_write": True,
        "memory_type": "project_fact",
        "content": "本项目偏好 answer-or-loop 节点。",
        "reason": "Stable project orchestration preference.",
    }


def test_assess_node_loops_when_model_says_evidence_is_not_enough() -> None:
    model = _FakeAnswerOrLoopModel(
        {
            "answer_confident": True,
            "answer": "This content must not be used when the loop tool is called.",
            "summary": {"done": "ignored", "next": "", "pending": ""},
            "next_tasks": [],
        },
        tool_calls=[
            {
                "name": "continue_evidence_loop",
                "args": {
                    "reason": "Need stronger experimental evidence.",
                    "next_tasks": ["Retrieve more experimental detail."],
                },
            }
        ],
    )

    with patch.object(supervisor, "_runtime", return_value=_FakeRuntime(model)):
        update = asyncio.run(supervisor.assess_node(_state()))

    assert update["answer_confident"] is False
    assert update["stop_reason"] == ""
    assert update["messages"][0].type == "tool"
    metadata = update["messages"][0].additional_kwargs["metadata"]
    assert metadata["phase"] == "assess_complete"
    assert metadata["next_tasks"] == ["Retrieve more experimental detail."]
    assert metadata["loop_reason"] == "Need stronger experimental evidence."


def test_route_after_assess_sends_final_answer_to_store_memory() -> None:
    assert supervisor._route_after_assess({"answer_confident": True}) == "store_memory"
