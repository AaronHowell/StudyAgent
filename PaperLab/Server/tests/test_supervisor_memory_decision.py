from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import patch

from domain import MemoryType
from orchestration import supervisor


class _FakeSynthesisModel:
    def __init__(
        self,
        *,
        tool_calls: list[dict[str, object]] | None = None,
        reasoning_content: str | None = None,
        content: dict[str, object] | str | None = None,
    ) -> None:
        self.bound_tools: list[dict[str, object]] | None = None
        self.tool_calls = tool_calls or []
        self.reasoning_content = reasoning_content
        self.content = content or {
            "answer": "Final answer",
            "summary": {"done": "done", "next": "", "pending": ""},
        }

    def bind_tools(self, tools: list[dict[str, object]]) -> "_FakeSynthesisModel":
        self.bound_tools = tools
        return self

    async def ainvoke(self, prompt: str) -> object:
        payload = self.content if isinstance(self.content, str) else json.dumps(self.content)
        return SimpleNamespace(
            id="answer-1",
            content=payload,
            tool_calls=self.tool_calls,
            reasoning_content=self.reasoning_content,
            additional_kwargs={"reasoning_content": self.reasoning_content} if self.reasoning_content else {},
            response_metadata={"reasoning_content": self.reasoning_content} if self.reasoning_content else {},
        )


class _FakeRuntime:
    def __init__(self, *, chat_model: object, memory_backend: object | None = None) -> None:
        self.chat_model = chat_model
        self.memory_backend = memory_backend


class _RecordingBackend:
    def __init__(self) -> None:
        self.remember_calls: list[dict[str, object]] = []

    def remember_messages(self, **kwargs: object) -> list[object]:
        self.remember_calls.append(kwargs)
        return []

    def search(self, *_args: object, **_kwargs: object) -> list[object]:
        return []

    def summarize_for_project(self, _project_id: str) -> str:
        return ""


def _question() -> object:
    return supervisor.HumanMessage(content="How should memory work?")


def test_synthesize_node_binds_cautious_memory_decision_tool() -> None:
    model = _FakeSynthesisModel()
    runtime = _FakeRuntime(chat_model=model)

    with patch.object(supervisor, "_runtime", return_value=runtime):
        result = asyncio.run(supervisor.synthesize_node({"messages": [_question()]}))

    assert model.bound_tools is not None
    assert model.bound_tools[0]["function"]["name"] == "decide_memory_write"
    assert result["messages"][0].additional_kwargs["metadata"]["memory_write_decision"]["action"] == "none"
    assert result["messages"][0].additional_kwargs["metadata"]["memory_write_decision"]["should_write"] is False


def test_synthesize_node_records_true_memory_write_decision() -> None:
    model = _FakeSynthesisModel(
        tool_calls=[
            {
                "name": "decide_memory_write",
                "args": {
                    "action": "store",
                    "memory_type": "preference",
                    "content": "用户偏好简洁回答。",
                    "reason": "Stable user preference.",
                },
            }
        ]
    )
    runtime = _FakeRuntime(chat_model=model)

    with patch.object(supervisor, "_runtime", return_value=runtime):
        result = asyncio.run(supervisor.synthesize_node({"messages": [_question()]}))

    metadata = result["messages"][0].additional_kwargs["metadata"]
    assert metadata["memory_write_decision"] == {
        "action": "store",
        "should_write": True,
        "memory_type": "preference",
        "content": "用户偏好简洁回答。",
        "reason": "Stable user preference.",
    }


def test_synthesize_node_preserves_reasoning_content_for_follow_up_turns() -> None:
    model = _FakeSynthesisModel(reasoning_content="internal chain")
    runtime = _FakeRuntime(chat_model=model)

    with patch.object(supervisor, "_runtime", return_value=runtime):
        result = asyncio.run(supervisor.synthesize_node({"messages": [_question()]}))

    answer = result["messages"][0]
    assert answer.additional_kwargs["reasoning_content"] == "internal chain"
    assert answer.response_metadata["reasoning_content"] == "internal chain"


def test_synthesize_node_falls_back_to_retrieval_summary_when_model_returns_empty_answer() -> None:
    model = _FakeSynthesisModel(
        content={"answer": "", "summary": {"done": "", "next": "", "pending": ""}},
        tool_calls=[
            {
                "name": "decide_memory_write",
                "args": {
                    "action": "none",
                    "memory_type": "research_episode",
                    "content": "",
                    "reason": "No stable cross-session memory.",
                },
            }
        ],
    )
    runtime = _FakeRuntime(chat_model=model)
    state = {
        "messages": [_question()],
        "retrieve_result": {
            "metadata": {
                "progress_summary": {"done": "Found 2 project documents.", "next": "", "pending": ""},
                "evidence_pack": {
                    "documents": [
                        {"title": "Paper A", "source_path": "a.pdf"},
                        {"title": "Paper B", "source_path": "b.pdf"},
                    ]
                },
            }
        },
    }

    with patch.object(supervisor, "_runtime", return_value=runtime):
        result = asyncio.run(supervisor.synthesize_node(state))

    answer = result["messages"][0]
    assert answer.content
    assert "Paper A" in answer.content
    assert "Paper B" in answer.content


def test_synthesize_node_includes_next_step_guidance_when_loop_hit_stop_condition() -> None:
    model = _FakeSynthesisModel(
        content={
            "answer": "目前只能先给出部分结论，仍缺少出处信息。",
            "summary": {
                "done": "已基于现有证据回答当前问题",
                "next": "继续抽取每篇论文首页的作者、年份与出处",
                "pending": "部分书目信息尚未确认",
            },
        }
    )
    runtime = _FakeRuntime(chat_model=model)
    state = {
        "messages": [_question()],
        "stop_reason": "max_iterations_reached",
        "assessment_loop_reason": "Need venue and author metadata.",
        "assessment_next_tasks": [
            "Fetch the title page or abstract section for each paper.",
            "Extract venue and year from the first page metadata.",
        ],
    }

    with patch.object(supervisor, "_runtime", return_value=runtime):
        result = asyncio.run(supervisor.synthesize_node(state))

    answer = result["messages"][0]
    metadata = answer.additional_kwargs["metadata"]
    assert answer.content == "目前只能先给出部分结论，仍缺少出处信息。"
    assert metadata["summary"]["next"] == "继续抽取每篇论文首页的作者、年份与出处"


def test_store_memory_node_skips_false_memory_decision() -> None:
    backend = _RecordingBackend()
    runtime = _FakeRuntime(chat_model=object(), memory_backend=backend)
    answer = supervisor._build_assistant_message(
        turn_id="turn-1",
        content="Final answer",
        metadata={
            "artifact_type": "answer",
            "memory_write_decision": {"action": "none", "should_write": False, "content": "", "reason": "No stable cross-session memory."},
        },
    )

    with patch.object(supervisor, "_runtime", return_value=runtime):
        result = asyncio.run(supervisor.store_memory_node({"messages": [_question(), answer], "active_turn_id": "turn-1"}))

    assert backend.remember_calls == []
    assert len(result["messages"]) == 1
    assert "长期记忆写入决策：none" in result["messages"][0].content


def test_store_memory_node_writes_true_memory_decision() -> None:
    backend = _RecordingBackend()
    runtime = _FakeRuntime(chat_model=object(), memory_backend=backend)
    answer = supervisor._build_assistant_message(
        turn_id="turn-1",
        content="Final answer",
        metadata={
            "artifact_type": "answer",
            "memory_write_decision": {
                "action": "store",
                "should_write": True,
                "memory_type": "project_fact",
                "content": "Project uses markdown memory.",
                "reason": "Stable project fact.",
            },
        },
    )

    with patch.object(supervisor, "_runtime", return_value=runtime):
        result = asyncio.run(supervisor.store_memory_node({"messages": [_question(), answer], "active_turn_id": "turn-1"}))

    assert len(backend.remember_calls) == 1
    assert backend.remember_calls[0]["messages"] == [
        {"role": "assistant", "content": "Project uses markdown memory."}
    ]
    assert backend.remember_calls[0]["memory_type"] == MemoryType.PROJECT_FACT
    assert len(result["messages"]) == 1
    assert "长期记忆写入决策：store" in result["messages"][0].content
