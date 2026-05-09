from __future__ import annotations

import asyncio
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import patch

from contracts import AgentTask
from domain import Chunk
from domain import ChunkType
from domain import Document
from domain import DocumentStatus
from domain import DocumentType
from orchestration.request_config import AgentRequestConfig
from workers.retriever import agent as retriever_agent


class _FakePlannerModel:
    def __init__(self) -> None:
        self.bound_tools: list[dict[str, object]] | None = None
        self.plan_calls = 0
        self.tool_calls_count = 0

    def bind_tools(self, tools: list[dict[str, object]]) -> "_FakePlannerModel":
        self.bound_tools = tools
        return self

    async def ainvoke(self, _messages: list[object]) -> object:
        if self.bound_tools is None:
            self.plan_calls += 1
            return SimpleNamespace(
                content='{"intent":"evidence","target_level":"chunk","need_semantic_search":true,"need_chunk_fetch":true,"need_asset_search":false,"max_steps":5,"rationale":"Need chunk-level method evidence."}'
            )
        self.tool_calls_count += 1
        if self.tool_calls_count == 1:
            return SimpleNamespace(
                content="Search candidate docs.",
                tool_calls=[
                    {
                        "id": "call-1",
                        "name": "search_documents_mysql",
                        "args": {"keyword": "transformer", "limit": 3},
                    }
                ],
            )
        if self.tool_calls_count == 2:
            return SimpleNamespace(
                content="Load concrete chunks.",
                tool_calls=[
                    {
                        "id": "call-2",
                        "name": "fetch_document_chunks_mysql",
                        "args": {"document_id": "doc-1", "limit": 2},
                    }
                ],
            )
        return SimpleNamespace(
            content="Finish retrieval.",
            tool_calls=[
                {
                    "id": "call-3",
                    "name": "finish_retrieval",
                    "args": {
                        "document_ids": ["doc-1"],
                        "chunk_ids": ["chunk-1"],
                        "asset_ids": [],
                        "summary": "Narrowed by metadata, then loaded exact chunks.",
                    },
                }
            ],
        )


class _FakeInventoryPlannerModel:
    def __init__(self) -> None:
        self.bound_tools: list[dict[str, object]] | None = None
        self.plan_calls = 0
        self.tool_calls_count = 0

    def bind_tools(self, tools: list[dict[str, object]]) -> "_FakeInventoryPlannerModel":
        self.bound_tools = tools
        return self

    async def ainvoke(self, _messages: list[object]) -> object:
        if self.bound_tools is None:
            self.plan_calls += 1
            return SimpleNamespace(
                content='{"intent":"inventory","target_level":"document","need_semantic_search":false,"need_chunk_fetch":false,"need_asset_search":false,"max_steps":3,"rationale":"The task only asks for titles and basic document metadata."}'
            )
        self.tool_calls_count += 1
        if self.tool_calls_count == 1:
            return SimpleNamespace(
                content="List document metadata only.",
                tool_calls=[
                    {
                        "id": "call-1",
                        "name": "search_documents_mysql",
                        "args": {"keyword": "", "limit": 50},
                    }
                ],
            )
        return SimpleNamespace(
            content="Finish after document-level inventory.",
            tool_calls=[
                {
                    "id": "call-2",
                    "name": "finish_retrieval",
                    "args": {
                        "document_ids": ["doc-1"],
                        "chunk_ids": [],
                        "asset_ids": [],
                        "summary": "Listed project documents from metadata only.",
                    },
                }
            ],
        )


@dataclass
class _FakeEmbeddingProvider:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2] for _ in texts]


class _FakeDocumentRepository:
    def __init__(self) -> None:
        self.documents = [
            Document(
                id="doc-1",
                project_id="project-a",
                path="/tmp/transformer.pdf",
                file_name="transformer.pdf",
                doc_type=DocumentType.PDF,
                title="Transformer Notes",
                status=DocumentStatus.INDEXED,
                content_hash="hash-1",
            )
        ]

    def list_by_project(self, _project_id: str) -> list[Document]:
        return list(self.documents)

    def list_by_ids(self, document_ids: list[str]) -> list[Document]:
        return [document for document in self.documents if document.id in document_ids]


class _FakeChunkRepository:
    def __init__(self) -> None:
        self.chunks = [
            Chunk(
                id="chunk-1",
                project_id="project-a",
                document_id="doc-1",
                chunk_index=0,
                chunk_type=ChunkType.TEXT,
                text="Transformer evidence chunk",
                page=3,
                section="Method",
            )
            ,
            Chunk(
                id="chunk-2",
                project_id="project-a",
                document_id="doc-1",
                chunk_index=1,
                chunk_type=ChunkType.TEXT,
                text="Transformer abstract summary chunk",
                page=1,
                section="Abstract",
            )
        ]

    def list_by_document(self, document_id: str) -> list[Chunk]:
        return [chunk for chunk in self.chunks if chunk.document_id == document_id]

    def list_by_ids(self, chunk_ids: list[str]) -> list[Chunk]:
        return [chunk for chunk in self.chunks if chunk.id in chunk_ids]


class _FakeAssetRepository:
    def list_by_ids(self, _asset_ids: list[str]) -> list[object]:
        return []


class _FakeUseCase:
    def __init__(self) -> None:
        self.embedding_provider = _FakeEmbeddingProvider()
        self.document_repository = _FakeDocumentRepository()
        self.chunk_repository = _FakeChunkRepository()
        self.asset_repository = _FakeAssetRepository()
        self.vector_store = object()
        self.document_recall_k = 12
        self.chunk_recall_k = 20
        self.asset_recall_k = 12

    def build_evidence_pack(self, *, query: str, document_hits: list[object], chunk_hits: list[object], asset_hits: list[object]) -> object:
        return SimpleNamespace(
            query=query,
            documents=document_hits,
            text_chunks=chunk_hits,
            assets=asset_hits,
            citations=[
                SimpleNamespace(
                    document_id="doc-1",
                    document_title="Transformer Notes",
                    chunk_id="chunk-1",
                    page=3,
                    locator="p.3",
                )
            ],
            asset_citations=[],
        )

    def _append_debug_log(self, **_kwargs: object) -> None:
        return None


class _FakeRuntime:
    def __init__(self) -> None:
        self.retrieve_evidence_use_case = _FakeUseCase()
        self.chat_model = _FakePlannerModel()
        self.cache_store = None


def test_retrieve_agent_uses_orchestrated_tools_and_finishes_with_selected_evidence() -> None:
    task = AgentTask(
        task_id="task-1",
        task_type="local_retrieval",
        agent_name="retrieval_agent",
        query="Find transformer method evidence",
        reason="Need local support",
        constraints={},
        metadata={},
    )
    runtime = _FakeRuntime()

    with patch.object(retriever_agent, "_graph_runtime", return_value=runtime):
        result = asyncio.run(
            retriever_agent.run_retrieve_specialist(
                task=task,
                request_config=AgentRequestConfig(project_id="project-a"),
            )
        )

    assert runtime.chat_model.bound_tools is not None
    tool_names = {tool["function"]["name"] for tool in runtime.chat_model.bound_tools}
    assert "search_documents_mysql" in tool_names
    assert "finish_retrieval" in tool_names
    assert result.status == "completed"
    assert result.metadata["evidence_counts"]["chunk_count"] == 1
    assert result.metadata["retrieval_plan"]["intent_plan"]["target_level"] == "chunk"
    assert result.metadata["retrieval_plan"]["chunk_ids"] == ["chunk-1"]


def test_retrieve_agent_stays_at_document_level_for_inventory_queries() -> None:
    task = AgentTask(
        task_id="task-2",
        task_type="local_retrieval",
        agent_name="retrieval_agent",
        query="现在有哪些论文？",
        reason="列出系统中所有已上传/存储的论文文档标题和基本信息",
        constraints={},
        metadata={},
    )
    runtime = _FakeRuntime()
    runtime.chat_model = _FakeInventoryPlannerModel()

    with patch.object(retriever_agent, "_graph_runtime", return_value=runtime):
        result = asyncio.run(
            retriever_agent.run_retrieve_specialist(
                task=task,
                request_config=AgentRequestConfig(project_id="project-a"),
            )
        )

    assert runtime.chat_model.bound_tools is not None
    tool_names = {tool["function"]["name"] for tool in runtime.chat_model.bound_tools}
    assert "search_documents_mysql" in tool_names
    assert result.summary == "Found project document metadata."
    assert result.metadata["metadata_only_sufficient"] is True
    assert result.metadata["evidence_counts"]["document_count"] == 1
    assert result.metadata["evidence_counts"]["chunk_count"] == 0
    assert result.metadata["retrieval_plan"]["intent_plan"]["target_level"] == "document"
    assert result.metadata["retrieval_plan"]["document_ids"] == ["doc-1"]
    assert result.metadata["retrieval_plan"]["chunk_ids"] == []


def test_normalize_langchain_tool_calls_emits_openai_compatible_shape() -> None:
    calls = retriever_agent._normalize_langchain_tool_calls(
        [
            {
                "id": "call-1",
                "name": "search_documents_mysql",
                "args": {"keyword": "transformer"},
            }
        ]
    )

    assert calls == [
        {
            "id": "call-1",
            "name": "search_documents_mysql",
            "args": {"keyword": "transformer"},
            "type": "tool_call",
        }
    ]


def test_parse_retrieval_intent_plan_respects_model_output() -> None:
    raw = SimpleNamespace(
        content='{"intent":"inventory","target_level":"document","need_semantic_search":false,"need_chunk_fetch":false,"need_asset_search":false,"max_steps":3,"rationale":"metadata only"}'
    )

    plan = retriever_agent._parse_retrieval_intent_plan(raw)

    assert plan.intent == "inventory"
    assert plan.target_level == "document"
    assert plan.need_semantic_search is False
    assert plan.need_chunk_fetch is False
    assert plan.need_asset_search is False
    assert plan.max_steps == 3


def test_execute_retrieval_tool_supports_batch_mysql_chunk_fetch() -> None:
    runtime = _FakeRuntime()
    state = retriever_agent._RetrievalPlanState()
    task = AgentTask(
        task_id="task-3",
        task_type="local_retrieval",
        agent_name="retrieval_agent",
        query="Summarize the corpus",
        reason="Need early pages from multiple documents",
        constraints={},
        metadata={},
    )

    result = asyncio.run(
        retriever_agent._execute_retrieval_tool(
            tool_name="fetch_documents_chunks_mysql",
            args={"document_ids": ["doc-1"], "page_from": 1, "page_to": 3, "limit_per_document": 3, "total_limit": 5},
            use_case=runtime.retrieve_evidence_use_case,
            request_config=AgentRequestConfig(project_id="project-a"),
            plan_state=state,
            task=task,
        )
    )

    assert len(result["chunks"]) >= 2
    assert any(item["section"] == "Abstract" for item in result["chunks"])


def test_execute_retrieval_tool_supports_mysql_chunk_text_search() -> None:
    runtime = _FakeRuntime()
    state = retriever_agent._RetrievalPlanState()
    task = AgentTask(
        task_id="task-4",
        task_type="local_retrieval",
        agent_name="retrieval_agent",
        query="Find abstract",
        reason="Need literal keyword search",
        constraints={},
        metadata={},
    )

    result = asyncio.run(
        retriever_agent._execute_retrieval_tool(
            tool_name="search_chunks_mysql",
            args={"keyword": "abstract", "limit": 5},
            use_case=runtime.retrieve_evidence_use_case,
            request_config=AgentRequestConfig(project_id="project-a"),
            plan_state=state,
            task=task,
        )
    )

    assert len(result["chunks"]) == 1
    assert result["chunks"][0]["chunk_id"] == "chunk-2"
