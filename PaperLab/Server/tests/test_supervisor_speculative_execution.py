from __future__ import annotations

import asyncio
from typing import Any

from contracts import AgentResult
from contracts import AgentTask
from orchestration import supervisor


class _FakeReranker:
    def __init__(self, score: float) -> None:
        self.score = score
        self.calls: list[dict[str, Any]] = []

    def rerank(self, query: str, candidates: list[str], top_k: int) -> list[float]:
        self.calls.append({"query": query, "candidates": candidates, "top_k": top_k})
        return [self.score]


class _FakeRuntime:
    def __init__(self, result: AgentResult | None = None) -> None:
        self.retrieve_evidence_use_case = type(
            "UseCase",
            (),
            {
                "reranker_provider": _FakeReranker(0.91),
                "embedding_provider": None,
            },
        )()
        self.speculative_runs: dict[str, Any] = {}
        self.result = result
        self.cleanup_calls: list[str] = []

    async def await_speculative_result(self, run_id: str) -> AgentResult | None:
        return self.result

    def cleanup_speculative_run(self, run_id: str) -> None:
        self.cleanup_calls.append(run_id)

    def mark_speculative_run_for_cleanup(self, run_id: str) -> None:
        self.cleanup_calls.append(run_id)


def _task(query: str = "compare transformer retrieval methods") -> AgentTask:
    return AgentTask(
        task_id="task-ret-formal",
        task_type="local_retrieval",
        agent_name="retrieval_agent",
        query=query,
        reason="Need project-grounded evidence.",
        constraints={"document_limit": 3, "chunk_limit": 5, "asset_limit": 2},
        metadata={},
    )


def _result(task_id: str = "task-ret-spec", agent_name: str = "retrieval_agent") -> AgentResult:
    return AgentResult(
        task_id=task_id,
        agent_name=agent_name,
        status="completed",
        summary="Speculative result",
        artifacts=[],
        confidence=0.8,
        metadata={"progress_summary": {"done": "done", "next": "", "pending": ""}},
    )


def test_speculative_similarity_uses_cross_encoder_reranker() -> None:
    runtime = _FakeRuntime()

    decision = supervisor._speculative_query_match(
        runtime=runtime,
        formal_query="compare transformer retrieval methods",
        speculative_query="How do transformer retrieval methods compare?",
    )

    assert decision["matched"] is True
    assert decision["method"] == "reranker"
    assert decision["score"] == 0.91
    assert runtime.retrieve_evidence_use_case.reranker_provider.calls == [
        {
            "query": "compare transformer retrieval methods",
            "candidates": ["How do transformer retrieval methods compare?"],
            "top_k": 1,
        }
    ]


def test_recall_memory_node_reuses_matching_speculative_memory(monkeypatch) -> None:
    result = AgentResult(
        task_id="task-mem-spec",
        agent_name="memory_agent",
        status="completed",
        summary="Relevant memory:\n- User prefers concise answers.",
        artifacts=[],
        confidence=1.0,
        metadata={
            "query": "How should we answer?",
            "memory_hits": [],
            "summary": "Relevant memory:\n- User prefers concise answers.",
        },
    )
    runtime = _FakeRuntime(result=result)
    monkeypatch.setattr(supervisor, "_runtime", lambda: runtime)

    update = asyncio.run(
        supervisor.recall_memory_node(
            {
                "messages": [],
                "active_turn_id": "turn-1",
                "run_memory": True,
                "memory_query": "answer preference",
                "memory_reason": "Need remembered user preference.",
                "speculative_memory": {
                    "run_id": "spec-mem-1",
                    "query": "How should we answer?",
                    "reason": "Speculative memory recall from raw user input.",
                },
            },
            {"configurable": {"project_id": "project-a", "memory_limit": 5}},
        )
    )

    message = update["messages"][0]
    metadata = message.additional_kwargs["metadata"]
    assert message.content == "Relevant memory:\n- User prefers concise answers."
    assert metadata["artifact_type"] == "memory_result"
    assert metadata["speculative_reused"] is True
    assert metadata["speculative_run_id"] == "spec-mem-1"
    assert runtime.cleanup_calls == ["spec-mem-1"]


def test_parallel_specialists_reuses_matching_speculative_retrieval(monkeypatch) -> None:
    speculative_result = _result()
    runtime = _FakeRuntime(result=speculative_result)

    async def fail_invoke(**_kwargs: object) -> tuple[None, list[object]]:
        raise AssertionError("matching speculative retrieval should be reused")

    monkeypatch.setattr(supervisor, "_runtime", lambda: runtime)
    monkeypatch.setattr(supervisor, "_invoke_specialist_subgraph", fail_invoke)

    update = asyncio.run(
        supervisor.parallel_specialists_node(
            {
                "messages": [],
                "active_turn_id": "turn-1",
                "retrieve_task": _task(),
                "iteration_count": 1,
                "speculative_retrieval": {
                    "run_id": "spec-ret-1",
                    "query": "How do transformer retrieval methods compare?",
                    "reason": "Speculative retrieval from raw user input.",
                    "constraints": {"document_limit": 3, "chunk_limit": 5, "asset_limit": 2},
                },
            },
            {"configurable": {"project_id": "project-a", "thread_id": "thread-1"}},
        )
    )

    assert update["retrieve_result"]["task_id"] == "task-ret-formal"
    assert update["retrieve_result"]["summary"] == "Speculative result"
    result_messages = [
        message
        for message in update["messages"]
        if message.additional_kwargs["metadata"].get("artifact_type") == "agent_result"
    ]
    assert result_messages[0].additional_kwargs["metadata"]["result"]["metadata"]["speculative_reused"] is True
    assert runtime.cleanup_calls == ["spec-ret-1"]
