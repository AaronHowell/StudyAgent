"""Retrieval specialist subgraph for PaperLab."""

import asyncio
from typing import Any
from uuid import uuid4

from contracts import AgentArtifact
from contracts import AgentResult
from contracts import AgentTask
from orchestration.graph_messages import _build_agent_result_message
from orchestration.output_summary import build_progress_summary
from orchestration.graph_serialization import _build_evidence_counts
from orchestration.graph_serialization import _serialize_evidence_pack
from orchestration.graph_serialization import build_assistant_metadata
from orchestration.graph_state import RetrieveAgentGraphState
from orchestration.request_config import AgentRequestConfig
from orchestration.request_config import _coerce_positive_int
from orchestration.runtime_access import _runtime
from runtime import CancellationToken

try:
    from langchain_core.messages import BaseMessage
    from langchain_core.runnables import RunnableConfig
    from langgraph.graph import END
    from langgraph.graph import START
    from langgraph.graph import StateGraph
except ImportError:  # pragma: no cover
    BaseMessage = Any  # type: ignore[assignment]
    RunnableConfig = dict[str, Any]  # type: ignore[assignment]
    END = "__end__"
    START = "__start__"
    StateGraph = None  # type: ignore[assignment]


def _graph_settings():
    from orchestration import supervisor as graph_module

    return graph_module.AgentSettings.from_env()


def _graph_runtime():
    return _runtime()


async def run_retrieve_specialist(
    *,
    task: AgentTask,
    request_config: AgentRequestConfig,
    cancel_token: CancellationToken | None = None,
) -> AgentResult:
    """Execute one retrieval specialist task."""

    def _cancelled_result(message: str) -> AgentResult:
        return AgentResult(
            task_id=task.task_id,
            agent_name=task.agent_name,
            status="cancelled",
            summary=message,
            artifacts=[],
            confidence=0.0,
            metadata={
                "cancelled": True,
                "progress_summary": build_progress_summary(
                    done=message,
                    next="等待新的检索任务",
                    pending="当前检索未完成",
                ),
            },
        )

    if cancel_token is not None and cancel_token.is_cancelled():
        return _cancelled_result("RetrievalAgent speculative run cancelled before execution.")

    cache_store = _graph_runtime().cache_store
    if cache_store is not None:
        cached = cache_store.load_cached_retrieval(request_config.project_id, task.query)
        if cached is not None:
            return AgentResult(
                task_id=str(cached.get("task_id") or task.task_id),
                agent_name=str(cached.get("agent_name") or task.agent_name),
                status=str(cached.get("status") or "completed"),
                summary=str(cached.get("summary") or ""),
                artifacts=list(cached.get("artifacts", [])),
                confidence=float(cached.get("confidence", 0.0) or 0.0),
                metadata=dict(cached.get("metadata", {}) or {}),
            )

    use_case = _graph_runtime().retrieve_evidence_use_case
    if not all(
        hasattr(use_case, attr)
        for attr in (
            "embedding_provider",
            "retrieve_documents",
            "retrieve_chunks",
            "retrieve_assets",
            "build_evidence_pack",
        )
    ):
        evidence_pack = await asyncio.to_thread(
            use_case.retrieve,
            query=task.query,
            project_id=request_config.project_id,
            document_limit=_coerce_positive_int(
                task.constraints.get("document_limit"), request_config.document_limit
            ),
            chunk_limit=_coerce_positive_int(
                task.constraints.get("chunk_limit"), request_config.chunk_limit
            ),
            asset_limit=_coerce_positive_int(
                task.constraints.get("asset_limit"), request_config.asset_limit
            ),
        )
        result = _build_result(task=task, evidence_pack=evidence_pack)
        if cache_store is not None:
            cache_store.save_cached_retrieval(
                request_config.project_id,
                task.query,
                result.to_dict(),
                ttl_seconds=_graph_settings().redis_retrieval_cache_ttl,
            )
        return result

    query_vector = (await asyncio.to_thread(use_case.embedding_provider.embed_texts, [task.query]))[0]
    if cancel_token is not None and cancel_token.is_cancelled():
        return _cancelled_result("RetrievalAgent speculative run cancelled after embedding.")

    document_hits, raw_document_hits = await asyncio.to_thread(
        use_case.retrieve_documents,
        query=task.query,
        project_id=request_config.project_id,
        query_vector=query_vector,
        limit=_coerce_positive_int(
            task.constraints.get("document_limit"), request_config.document_limit
        ),
    )
    if cancel_token is not None and cancel_token.is_cancelled():
        return _cancelled_result("RetrievalAgent speculative run cancelled after document retrieval.")

    document_ids = [hit.document_id for hit in document_hits]
    chunk_hits, raw_chunk_hits = await asyncio.to_thread(
        use_case.retrieve_chunks,
        query=task.query,
        project_id=request_config.project_id,
        document_ids=document_ids,
        query_vector=query_vector,
        limit=_coerce_positive_int(task.constraints.get("chunk_limit"), request_config.chunk_limit),
    )
    if cancel_token is not None and cancel_token.is_cancelled():
        return _cancelled_result("RetrievalAgent speculative run cancelled after chunk retrieval.")

    asset_hits, raw_asset_hits = await asyncio.to_thread(
        use_case.retrieve_assets,
        query=task.query,
        project_id=request_config.project_id,
        document_ids=document_ids,
        query_vector=query_vector,
        limit=_coerce_positive_int(task.constraints.get("asset_limit"), request_config.asset_limit),
    )
    if cancel_token is not None and cancel_token.is_cancelled():
        return _cancelled_result("RetrievalAgent speculative run cancelled after asset retrieval.")

    evidence_pack = await asyncio.to_thread(
        use_case.build_evidence_pack,
        query=task.query,
        document_hits=document_hits,
        chunk_hits=chunk_hits,
        asset_hits=asset_hits,
    )
    if hasattr(use_case, "_append_debug_log"):
        await asyncio.to_thread(
            use_case._append_debug_log,
            query=task.query,
            project_id=request_config.project_id,
            raw_document_hits=raw_document_hits,
            raw_chunk_hits=raw_chunk_hits,
            raw_asset_hits=raw_asset_hits,
            evidence_pack=evidence_pack,
        )

    result = _build_result(task=task, evidence_pack=evidence_pack)
    if cache_store is not None:
        cache_store.save_cached_retrieval(
            request_config.project_id,
            task.query,
            result.to_dict(),
            ttl_seconds=_graph_settings().redis_retrieval_cache_ttl,
        )
    return result


def _build_result(*, task: AgentTask, evidence_pack: Any) -> AgentResult:
    artifact = AgentArtifact(
        artifact_id=f"artifact_ret_{uuid4().hex[:8]}",
        artifact_type="retrieval_evidence",
        content=(
            f"Retrieved {len(evidence_pack.documents)} documents, "
            f"{len(evidence_pack.text_chunks)} chunks, {len(evidence_pack.assets)} assets."
        ),
        metadata={
            "citations": build_assistant_metadata(evidence_pack.citations)["citations"],
            "evidence_counts": _build_evidence_counts(evidence_pack),
            "evidence_pack": _serialize_evidence_pack(evidence_pack),
        },
    )
    return AgentResult(
        task_id=task.task_id,
        agent_name=task.agent_name,
        status="completed",
        summary=(
            "Found local supporting evidence."
            if evidence_pack.citations
            else "Local retrieval returned weak evidence."
        ),
        artifacts=[artifact.to_dict()],
        confidence=0.8 if evidence_pack.citations else 0.25,
        metadata=artifact.metadata,
    )
    result.metadata["progress_summary"] = build_progress_summary(
        done=result.summary,
        next="可继续基于引用展开回答或比较证据",
        pending=(
            "还没有足够强的本地引用证据"
            if not evidence_pack.citations
            else "尚未结合外部工具或工作区信息"
        ),
    )
    return result
    

async def retrieve_agent_execute_node(
    state: RetrieveAgentGraphState,
    config: RunnableConfig | None = None,
    *,
    resolve_request_config,
) -> RetrieveAgentGraphState:
    """Execute the retrieval specialist inside its own subgraph state."""

    task = state.get("retrieve_task")
    if task is None:
        return {}
    request_config = resolve_request_config(dict(config or {}))
    turn_id = str(state.get("active_turn_id") or f"turn_{uuid4().hex[:8]}")
    result = await run_retrieve_specialist(task=task, request_config=request_config)
    return {
        "retrieve_result": result.to_dict(),
        "messages": [_build_agent_result_message(turn_id=turn_id, result=result)],
    }


def build_retrieve_agent_graph(*, resolve_request_config):
    """Create the retrieval specialist subgraph with isolated specialist state."""

    if StateGraph is None:
        return None

    async def execute(
        state: RetrieveAgentGraphState,
        config: RunnableConfig | None = None,
    ) -> RetrieveAgentGraphState:
        return await retrieve_agent_execute_node(
            state,
            config,
            resolve_request_config=resolve_request_config,
        )

    builder = StateGraph(RetrieveAgentGraphState)
    builder.add_node("execute", execute)
    builder.add_edge(START, "execute")
    builder.add_edge("execute", END)
    return builder.compile(name="retrieve_agent")


