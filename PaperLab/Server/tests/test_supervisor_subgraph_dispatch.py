from __future__ import annotations

import asyncio
from typing import Any

import pytest

from contracts import AgentResult
from contracts import AgentTask
from orchestration import supervisor


class _FakeSubgraph:
    def __init__(self, *, result_key: str, task_key: str, result: AgentResult) -> None:
        self.result_key = result_key
        self.task_key = task_key
        self.result = result
        self.calls: list[dict[str, Any]] = []

    async def ainvoke(self, state: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
        self.calls.append({"state": state, "config": config})
        task = state[self.task_key]
        assert isinstance(task, AgentTask)
        return {
            self.result_key: self.result.to_dict(),
            "messages": [
                supervisor._build_agent_result_message(
                    turn_id=str(state["active_turn_id"]),
                    result=self.result,
                )
            ],
        }


def _task(task_id: str, agent_name: str) -> AgentTask:
    return AgentTask(
        task_id=task_id,
        task_type="specialist",
        agent_name=agent_name,
        query=f"{agent_name} query",
        reason=f"{agent_name} reason",
        constraints={},
        metadata={},
    )


def _result(task_id: str, agent_name: str) -> AgentResult:
    return AgentResult(
        task_id=task_id,
        agent_name=agent_name,
        status="completed",
        summary=f"{agent_name} completed via subgraph",
        artifacts=[],
        confidence=0.9,
        metadata={},
    )


@pytest.mark.parametrize(
    ("direct_name", "graph_name", "task_key", "result_key", "agent_name"),
    [
        ("run_retrieve_specialist", "retrieve_agent_graph", "retrieve_task", "retrieve_result", "retrieval_agent"),
        ("run_tool_specialist", "tool_agent_graph", "tool_task", "tool_result", "tool_agent"),
        ("run_workspace_specialist", "workspace_agent_graph", "workspace_task", "workspace_result", "workspace_agent"),
    ],
)
def test_parallel_specialists_dispatches_each_worker_through_subgraph(
    monkeypatch: pytest.MonkeyPatch,
    direct_name: str,
    graph_name: str,
    task_key: str,
    result_key: str,
    agent_name: str,
) -> None:
    async def fail_direct_call(**_kwargs: object) -> AgentResult:
        raise AssertionError("parent graph must dispatch through specialist subgraphs")

    task = _task(f"task-{agent_name}", agent_name)
    result = _result(task.task_id, agent_name)
    fake_graph = _FakeSubgraph(result_key=result_key, task_key=task_key, result=result)
    monkeypatch.setattr(supervisor, direct_name, fail_direct_call)
    monkeypatch.setattr(supervisor, graph_name, fake_graph)

    update = asyncio.run(
        supervisor.parallel_specialists_node(
            {
                "messages": [],
                "active_turn_id": "turn-1",
                task_key: task,
                "iteration_count": 1,
            },
            {"configurable": {"project_id": "project-a", "thread_id": "thread-1"}},
        )
    )

    assert len(fake_graph.calls) == 1
    assert fake_graph.calls[0]["state"] == {"active_turn_id": "turn-1", task_key: task}
    assert fake_graph.calls[0]["config"] == {
        "configurable": {"project_id": "project-a", "thread_id": "thread-1"}
    }
    assert update[result_key] == result.to_dict()
    assert update["messages"][0].additional_kwargs["metadata"]["result"] == result.to_dict()
