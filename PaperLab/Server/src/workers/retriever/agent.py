"""Retrieval specialist subgraph for PaperLab."""

import asyncio
from dataclasses import dataclass, field
import json
from typing import Any
from uuid import uuid4

from contracts import AgentArtifact
from contracts import AgentResult
from contracts import AgentTask
from domain import AssetHit
from domain import ChunkHit
from domain import DocumentHit
from domain import ScoredId
from orchestration.graph_messages import _build_agent_result_message
from orchestration.graph_messages import _build_tool_message
from orchestration.graph_messages import _coerce_tool_call_args
from orchestration.graph_messages import _extract_tool_calls
from orchestration.output_summary import build_progress_summary
from orchestration.graph_serialization import _build_evidence_counts
from orchestration.graph_serialization import _serialize_evidence_pack
from orchestration.graph_serialization import build_asset_citations_metadata
from orchestration.graph_serialization import build_asset_sources_metadata
from orchestration.graph_serialization import build_assistant_metadata
from orchestration.graph_state import RetrieveAgentGraphState
from orchestration.request_config import AgentRequestConfig
from orchestration.request_config import _coerce_positive_int
from orchestration.runtime_access import _runtime
from runtime import CancellationToken

try:
    from langchain_core.messages import AIMessage
    from langchain_core.messages import BaseMessage
    from langchain_core.messages import HumanMessage
    from langchain_core.messages import SystemMessage
    from langchain_core.messages import ToolMessage
    from langchain_core.runnables import RunnableConfig
    from langgraph.graph import END
    from langgraph.graph import START
    from langgraph.graph import StateGraph
except ImportError:  # pragma: no cover
    AIMessage = Any  # type: ignore[assignment]
    BaseMessage = Any  # type: ignore[assignment]
    HumanMessage = Any  # type: ignore[assignment]
    SystemMessage = Any  # type: ignore[assignment]
    ToolMessage = Any  # type: ignore[assignment]
    RunnableConfig = dict[str, Any]  # type: ignore[assignment]
    END = "__end__"
    START = "__start__"
    StateGraph = None  # type: ignore[assignment]


@dataclass(slots=True)
class _RetrievalPlanState:
    query_vector: list[float] | None = None
    document_hits: dict[str, DocumentHit] = field(default_factory=dict)
    chunk_hits: dict[str, ChunkHit] = field(default_factory=dict)
    asset_hits: dict[str, AssetHit] = field(default_factory=dict)
    raw_document_hits: dict[str, list[dict[str, object]]] = field(default_factory=dict)
    raw_chunk_hits: dict[str, object] = field(default_factory=dict)
    raw_asset_hits: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class _RetrievalIntentPlan:
    intent: str = "evidence"
    target_level: str = "chunk"
    need_semantic_search: bool = True
    need_chunk_fetch: bool = True
    need_asset_search: bool = False
    max_steps: int = 5
    rationale: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "intent": self.intent,
            "target_level": self.target_level,
            "need_semantic_search": self.need_semantic_search,
            "need_chunk_fetch": self.need_chunk_fetch,
            "need_asset_search": self.need_asset_search,
            "max_steps": self.max_steps,
            "rationale": self.rationale,
        }


def _graph_settings():
    from orchestration import supervisor as graph_module

    return graph_module.AgentSettings.from_env()


def _graph_runtime():
    return _runtime()


def _retrieval_tool_schema() -> list[dict[str, object]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "search_documents_mysql",
                "description": "Literal substring filter over `documents.title`, `documents.file_name`, and `documents.llm_title`. This is not semantic search. For full project inventory, pass an empty keyword string.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "keyword": {"type": "string"},
                        "limit": {"type": "integer"},
                    },
                    "required": ["keyword"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_documents_qdrant",
                "description": "Semantic document-profile retrieval from Qdrant using title or summary vectors.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "vector_name": {"type": "string", "enum": ["title", "summary"]},
                        "limit": {"type": "integer"},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_chunks_qdrant",
                "description": "Semantic chunk retrieval from Qdrant, optionally scoped to candidate document ids.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "document_ids": {"type": "array", "items": {"type": "string"}},
                        "limit": {"type": "integer"},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "fetch_document_chunks_mysql",
                "description": "Load concrete chunks from MySQL for one document, optionally narrowed by page range.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "document_id": {"type": "string"},
                        "page_from": {"type": "integer"},
                        "page_to": {"type": "integer"},
                        "limit": {"type": "integer"},
                    },
                    "required": ["document_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "fetch_chunks_mysql",
                "description": "Load exact chunk rows from MySQL by chunk ids.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "chunk_ids": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["chunk_ids"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_assets_qdrant",
                "description": "Semantic asset retrieval from Qdrant using caption or summary vectors.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "document_ids": {"type": "array", "items": {"type": "string"}},
                        "vector_name": {"type": "string", "enum": ["caption", "summary"]},
                        "limit": {"type": "integer"},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "fetch_assets_mysql",
                "description": "Load exact asset rows from MySQL by asset ids.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "asset_ids": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["asset_ids"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "finish_retrieval",
                "description": "Finish retrieval and submit the selected document, chunk, and asset ids for evidence assembly.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "document_ids": {"type": "array", "items": {"type": "string"}},
                        "chunk_ids": {"type": "array", "items": {"type": "string"}},
                        "asset_ids": {"type": "array", "items": {"type": "string"}},
                        "summary": {"type": "string"},
                    },
                    "required": ["document_ids", "chunk_ids", "asset_ids", "summary"],
                },
            },
        },
    ]


def _retrieval_schema_summary() -> str:
    return (
        "Retrieval database schema and indexes:\n"
        "- MySQL table `documents`: id, project_id, path, file_name, title, llm_title, status, content_hash\n"
        "- MySQL table `chunks`: id, project_id, document_id, chunk_index, chunk_type, page, section, text\n"
        "- MySQL table `document_assets`: id, document_id, page_number, file_name, asset_kind, asset_label, caption, summary, asset_type\n"
        "- Qdrant collection `paperlab_documents`: named vectors `title`, `summary`; payload is document-level metadata keyed by document_id\n"
        "- Qdrant collection `paperlab_chunks`: named vector `content`; payload is chunk-level metadata keyed by chunk_id and document_id\n"
        "- Qdrant collection `paperlab_assets`: named vectors `caption`, `summary`; payload is asset-level metadata keyed by asset_id and document_id\n\n"
        "Field usage guidance:\n"
        "- Use `documents.title`, `documents.file_name`, and `documents.llm_title` to narrow candidate papers by keyword.\n"
        "- `search_documents_mysql` is exact substring matching on metadata only. It does not infer topics or categories.\n"
        "- The `documents` table has no taxonomy field such as `paper`, `research`, `literature`, or `document_type_label`.\n"
        "- For full local document listing, use `search_documents_mysql` with `keyword=\"\"` instead of guessing generic words.\n"
        "- Use `chunks.text` when you need exact supporting passages; use `page` and `chunk_index` to keep nearby evidence coherent.\n"
        "- Use `document_assets.caption` and `document_assets.summary` when the question references figures, tables, charts, or diagrams.\n"
        "- `project_id` scopes all retrieval to the active project; do not assume cross-project access.\n\n"
        "Tool mapping:\n"
        "- `search_documents_mysql`: metadata filtering over `documents`\n"
        "- `search_documents_qdrant`: semantic retrieval over document title/summary vectors\n"
        "- `search_chunks_qdrant`: semantic retrieval over chunk content vectors\n"
        "- `fetch_document_chunks_mysql` and `fetch_chunks_mysql`: exact chunk row loading from MySQL\n"
        "- `search_assets_qdrant`: semantic retrieval over asset caption/summary vectors\n"
        "- `fetch_assets_mysql`: exact asset row loading from MySQL\n\n"
        "Structural routing policy:\n"
        "- Work by level: documents -> chunks -> assets.\n"
        "- Stay at the document level when the task asks for titles, counts, file names, upload status, or basic metadata.\n"
        "- Only go to chunks when the task asks for content, passage text, quote, method, result, claim, page, section, or detailed evidence.\n"
        "- Only go to assets when the task explicitly asks about figures, tables, charts, diagrams, or visual content.\n"
        "- Do not fetch chunks or assets just to confirm that a document exists.\n"
        "- For listing/inventory tasks, prefer `search_documents_mysql` with an empty keyword to enumerate project documents, then call `finish_retrieval` immediately.\n\n"
        "- Avoid low-signal MySQL keywords like `paper`, `research`, `literature`, or `document` for inventory tasks. Those are not structural fields in the database.\n\n"
        "Execution policy:\n"
        "- Database access is read-only. You cannot insert, update, delete, or run arbitrary SQL.\n"
        "- Use MySQL tools for structured filtering and exact row loading.\n"
        "- Use Qdrant tools for semantic candidate retrieval.\n"
        "- Prefer narrowing candidate documents before chunk or asset retrieval when possible.\n"
        "- Prefer exact MySQL fetch after semantic Qdrant recall when the answer needs quotable supporting evidence.\n"
        "- Call finish_retrieval once you have enough evidence ids."
    )


def _extract_json_object(raw: str) -> dict[str, Any] | None:
    candidate = raw.strip()
    if not candidate:
        return None
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            parsed = json.loads(candidate[start : end + 1])
        except json.JSONDecodeError:
            return None
    return parsed if isinstance(parsed, dict) else None


def _parse_bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "1"}:
            return True
        if normalized in {"false", "no", "0"}:
            return False
    return default


def _parse_retrieval_intent_plan(raw_output: object) -> _RetrievalIntentPlan:
    content = str(getattr(raw_output, "content", raw_output) or "")
    payload = _extract_json_object(content) or {}
    target_level = str(payload.get("target_level") or "chunk").strip().lower()
    if target_level not in {"document", "chunk", "asset"}:
        target_level = "chunk"
    intent = str(payload.get("intent") or "evidence").strip().lower() or "evidence"
    need_semantic_search_default = target_level != "document"
    need_chunk_fetch_default = target_level == "chunk"
    need_asset_search_default = target_level == "asset"
    max_steps_default = 3 if target_level == "document" else 5
    return _RetrievalIntentPlan(
        intent=intent,
        target_level=target_level,
        need_semantic_search=_parse_bool(payload.get("need_semantic_search"), need_semantic_search_default),
        need_chunk_fetch=_parse_bool(payload.get("need_chunk_fetch"), need_chunk_fetch_default),
        need_asset_search=_parse_bool(payload.get("need_asset_search"), need_asset_search_default),
        max_steps=max(2, min(8, _coerce_positive_int(payload.get("max_steps"), max_steps_default))),
        rationale=str(payload.get("rationale") or "").strip(),
    )


def _build_retrieval_planning_messages(*, task: AgentTask) -> list[Any]:
    return [
        SystemMessage(
            content=(
                "You are RetrievalAgent. Before calling any retrieval tools, decide the retrieval intent and the "
                "lowest database level needed to answer the task.\n\n"
                + _retrieval_schema_summary()
                + "\n\nReturn valid JSON with exactly these keys: "
                "`intent`, `target_level`, `need_semantic_search`, `need_chunk_fetch`, `need_asset_search`, `max_steps`, `rationale`.\n"
                "- `intent` must be one of `inventory`, `evidence`, `visual`, `mixed`.\n"
                "- `target_level` must be one of `document`, `chunk`, `asset`.\n"
                "- Use `document` for titles/counts/basic metadata.\n"
                "- Use `chunk` for passages, methods, results, claims, page-level evidence.\n"
                "- Use `asset` for figures, tables, diagrams, or visual content.\n"
                "- If `target_level` is `document`, default to metadata lookup and avoid semantic search unless clearly needed.\n"
                "- Do not include markdown or any text outside the JSON object."
            )
        ),
        HumanMessage(
            content=(
                f"Task query:\n{task.query}\n\n"
                f"Reason:\n{task.reason}\n\n"
                "Think about the task semantics, not just keywords, and choose the minimal retrieval level that can answer it."
            )
        ),
    ]


def _build_retrieval_execution_instruction(*, plan: _RetrievalIntentPlan) -> str:
    lines = [
        "Approved retrieval plan:",
        json.dumps(plan.to_dict(), ensure_ascii=False, indent=2),
        "Follow this plan strictly.",
    ]
    if plan.target_level == "document":
        lines.append(
            "Stay at the document level. Use `search_documents_mysql` with `keyword=\"\"` for full project inventory or a literal metadata keyword when the task names a specific title/file. Do not fetch chunks or assets."
        )
    elif plan.target_level == "chunk":
        lines.append(
            "You may use document narrowing plus chunk retrieval. Fetch exact chunks only when chunk-level evidence is required."
        )
    else:
        lines.append(
            "You may use document narrowing plus asset retrieval. Do not fetch chunk text unless the visual task also requires textual support."
        )
    if not plan.need_semantic_search:
        lines.append("Avoid Qdrant semantic search unless metadata lookup fails to satisfy the plan.")
    if not plan.need_chunk_fetch:
        lines.append("Do not call chunk-fetch tools.")
    if not plan.need_asset_search:
        lines.append("Do not call asset-search tools.")
    return "\n".join(lines)


async def _ensure_query_vector(*, state: _RetrievalPlanState, use_case: Any, query: str) -> list[float]:
    if state.query_vector is None:
        state.query_vector = (await asyncio.to_thread(use_case.embedding_provider.embed_texts, [query]))[0]
    return state.query_vector


def _serialize_document_rows(hits: list[DocumentHit]) -> list[dict[str, object]]:
    return [
        {
            "document_id": hit.document_id,
            "title": hit.title,
            "file_name": hit.file_name,
            "score": hit.score,
            "status": hit.status,
        }
        for hit in hits
    ]


def _serialize_chunk_rows(hits: list[ChunkHit]) -> list[dict[str, object]]:
    return [
        {
            "chunk_id": hit.chunk_id,
            "document_id": hit.document_id,
            "page": hit.page,
            "chunk_index": hit.chunk_index,
            "section": hit.section,
            "score": hit.score,
            "text": hit.text[:500],
        }
        for hit in hits
    ]


def _serialize_asset_rows(hits: list[AssetHit]) -> list[dict[str, object]]:
    return [
        {
            "asset_id": hit.asset_id,
            "document_id": hit.document_id,
            "page_number": hit.page_number,
            "asset_label": hit.asset_label,
            "score": hit.score,
            "caption": hit.caption[:300],
            "summary": hit.summary[:300],
        }
        for hit in hits
    ]


def _document_hits_from_documents(documents: list[Any]) -> list[DocumentHit]:
    return [DocumentHit(document=document, score=0.0) for document in documents]


def _normalize_langchain_tool_calls(tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for call in tool_calls:
        normalized.append(
            {
                "name": str(call.get("name") or ""),
                "args": dict(_coerce_tool_call_args(call)),
                "id": str(call.get("id") or f"tool_{uuid4().hex[:8]}"),
                "type": "tool_call",
            }
        )
    return normalized


def _build_retrieval_reasoning_message(*, turn_id: str, content: str) -> ToolMessage:
    return _build_tool_message(
        turn_id=turn_id,
        name="retrieval_reasoning",
        content=content,
        metadata={"artifact_type": "retrieval_reasoning", "reusable": False},
    )


def _build_retrieval_tool_call_message(
    *,
    turn_id: str,
    tool_name: str,
    args: dict[str, Any],
    tool_call_id: str,
) -> ToolMessage:
    return _build_tool_message(
        turn_id=turn_id,
        name="retrieval_tool_call",
        content=json.dumps({"tool": tool_name, "args": args}, ensure_ascii=False, indent=2),
        metadata={
            "artifact_type": "retrieval_tool_call",
            "tool_name": tool_name,
            "args": args,
            "reusable": False,
        },
        tool_call_id=tool_call_id,
    )


def _build_retrieval_tool_result_message(
    *,
    turn_id: str,
    tool_name: str,
    result: dict[str, object],
    tool_call_id: str,
) -> ToolMessage:
    return _build_tool_message(
        turn_id=turn_id,
        name="retrieval_tool_result",
        content=json.dumps(result, ensure_ascii=False, indent=2),
        metadata={
            "artifact_type": "retrieval_tool_result",
            "tool_name": tool_name,
            "reusable": False,
        },
        tool_call_id=tool_call_id,
    )


async def _execute_retrieval_tool(
    *,
    tool_name: str,
    args: dict[str, Any],
    use_case: Any,
    request_config: AgentRequestConfig,
    plan_state: _RetrievalPlanState,
    task: AgentTask,
) -> dict[str, object]:
    if tool_name == "search_documents_mysql":
        keyword = str(args.get("keyword") or "").strip().lower()
        limit = _coerce_positive_int(args.get("limit"), request_config.document_limit)
        documents = list(use_case.document_repository.list_by_project(request_config.project_id))
        filtered = [
            document
            for document in documents
            if keyword in document.title.lower()
            or keyword in document.file_name.lower()
            or keyword in str(document.llm_title or "").lower()
        ][:limit]
        hits = _document_hits_from_documents(filtered)
        for hit in hits:
            plan_state.document_hits[hit.document_id] = hit
        return {"documents": _serialize_document_rows(hits)}

    if tool_name == "search_documents_qdrant":
        query = str(args.get("query") or task.query)
        vector_name = str(args.get("vector_name") or "summary")
        limit = _coerce_positive_int(args.get("limit"), request_config.document_limit)
        query_vector = await _ensure_query_vector(state=plan_state, use_case=use_case, query=query)
        raw_hits = await asyncio.to_thread(
            use_case.vector_store.search_documents,
            query_vector=query_vector,
            project_id=request_config.project_id,
            vector_name=vector_name,
            limit=max(limit, use_case.document_recall_k),
        )
        documents = await asyncio.to_thread(
            use_case.document_repository.list_by_ids,
            [hit.entity_id for hit in raw_hits[:limit]],
        )
        documents_by_id = {document.id: document for document in documents}
        hits = [
            DocumentHit(document=documents_by_id[hit.entity_id], score=hit.score)
            for hit in raw_hits[:limit]
            if hit.entity_id in documents_by_id
        ]
        for hit in hits:
            plan_state.document_hits[hit.document_id] = hit
        plan_state.raw_document_hits[vector_name] = use_case._serialize_scored_ids(raw_hits)
        return {"documents": _serialize_document_rows(hits)}

    if tool_name == "search_chunks_qdrant":
        query = str(args.get("query") or task.query)
        limit = _coerce_positive_int(args.get("limit"), request_config.chunk_limit)
        requested_document_ids = [str(item) for item in list(args.get("document_ids", []) or []) if str(item)]
        query_vector = await _ensure_query_vector(state=plan_state, use_case=use_case, query=query)
        raw_hits = await asyncio.to_thread(
            use_case.vector_store.search_chunks,
            query_vector=query_vector,
            project_id=request_config.project_id,
            vector_name="content",
            document_ids=requested_document_ids or list(plan_state.document_hits.keys()) or None,
            limit=max(limit, use_case.chunk_recall_k),
        )
        chunks = await asyncio.to_thread(
            use_case.chunk_repository.list_by_ids,
            [hit.entity_id for hit in raw_hits[:limit]],
        )
        chunks_by_id = {chunk.id: chunk for chunk in chunks}
        hits = [
            ChunkHit(chunk=chunks_by_id[hit.entity_id], score=hit.score)
            for hit in raw_hits[:limit]
            if hit.entity_id in chunks_by_id
        ]
        for hit in hits:
            plan_state.chunk_hits[hit.chunk_id] = hit
        plan_state.raw_chunk_hits = use_case._serialize_chunk_rerank_log(raw_hits, hits)
        return {"chunks": _serialize_chunk_rows(hits)}

    if tool_name == "fetch_document_chunks_mysql":
        document_id = str(args.get("document_id") or "").strip()
        page_from = args.get("page_from")
        page_to = args.get("page_to")
        limit = _coerce_positive_int(args.get("limit"), request_config.chunk_limit)
        chunks = list(use_case.chunk_repository.list_by_document(document_id))
        selected = []
        for chunk in chunks:
            page = chunk.page
            if page_from is not None and page is not None and page < int(page_from):
                continue
            if page_to is not None and page is not None and page > int(page_to):
                continue
            selected.append(ChunkHit(chunk=chunk, score=0.0))
            if len(selected) >= limit:
                break
        for hit in selected:
            plan_state.chunk_hits[hit.chunk_id] = hit
        return {"chunks": _serialize_chunk_rows(selected)}

    if tool_name == "fetch_chunks_mysql":
        chunk_ids = [str(item) for item in list(args.get("chunk_ids", []) or []) if str(item)]
        chunks = await asyncio.to_thread(use_case.chunk_repository.list_by_ids, chunk_ids)
        hits = [ChunkHit(chunk=chunk, score=plan_state.chunk_hits.get(chunk.id, ChunkHit(chunk=chunk, score=0.0)).score) for chunk in chunks]
        for hit in hits:
            plan_state.chunk_hits[hit.chunk_id] = hit
        return {"chunks": _serialize_chunk_rows(hits)}

    if tool_name == "search_assets_qdrant":
        query = str(args.get("query") or task.query)
        vector_name = str(args.get("vector_name") or "summary")
        limit = _coerce_positive_int(args.get("limit"), request_config.asset_limit)
        requested_document_ids = [str(item) for item in list(args.get("document_ids", []) or []) if str(item)]
        query_vector = await _ensure_query_vector(state=plan_state, use_case=use_case, query=query)
        raw_hits = await asyncio.to_thread(
            use_case.vector_store.search_assets,
            query_vector=query_vector,
            project_id=request_config.project_id,
            vector_name=vector_name,
            document_ids=requested_document_ids or list(plan_state.document_hits.keys()) or None,
            limit=max(limit, use_case.asset_recall_k),
        )
        assets = await asyncio.to_thread(
            use_case.asset_repository.list_by_ids,
            [hit.entity_id for hit in raw_hits[:limit]],
        )
        assets_by_id = {asset.id: asset for asset in assets}
        hits = [
            AssetHit(asset=assets_by_id[hit.entity_id], score=hit.score)
            for hit in raw_hits[:limit]
            if hit.entity_id in assets_by_id
        ]
        for hit in hits:
            plan_state.asset_hits[hit.asset_id] = hit
        plan_state.raw_asset_hits = use_case._serialize_asset_rerank_log(raw_hits, hits)
        return {"assets": _serialize_asset_rows(hits)}

    if tool_name == "fetch_assets_mysql":
        asset_ids = [str(item) for item in list(args.get("asset_ids", []) or []) if str(item)]
        assets = await asyncio.to_thread(use_case.asset_repository.list_by_ids, asset_ids)
        hits = [AssetHit(asset=asset, score=plan_state.asset_hits.get(asset.id, AssetHit(asset=asset, score=0.0)).score) for asset in assets]
        for hit in hits:
            plan_state.asset_hits[hit.asset_id] = hit
        return {"assets": _serialize_asset_rows(hits)}

    raise ValueError(f"Unsupported retrieval tool: {tool_name}")


async def _build_evidence_pack_from_selection(
    *,
    query: str,
    use_case: Any,
    plan_state: _RetrievalPlanState,
    selected_document_ids: list[str],
    selected_chunk_ids: list[str],
    selected_asset_ids: list[str],
) -> Any:
    document_ids = list(dict.fromkeys([
        *selected_document_ids,
        *[plan_state.chunk_hits[chunk_id].document_id for chunk_id in selected_chunk_ids if chunk_id in plan_state.chunk_hits],
        *[plan_state.asset_hits[asset_id].document_id for asset_id in selected_asset_ids if asset_id in plan_state.asset_hits],
    ]))
    documents = await asyncio.to_thread(use_case.document_repository.list_by_ids, document_ids)
    chunks = await asyncio.to_thread(use_case.chunk_repository.list_by_ids, selected_chunk_ids)
    assets = await asyncio.to_thread(use_case.asset_repository.list_by_ids, selected_asset_ids)

    document_hits = [
        plan_state.document_hits.get(document.id, DocumentHit(document=document, score=0.0))
        for document in documents
    ]
    chunk_hits = [
        plan_state.chunk_hits.get(chunk.id, ChunkHit(chunk=chunk, score=0.0))
        for chunk in chunks
    ]
    asset_hits = [
        plan_state.asset_hits.get(asset.id, AssetHit(asset=asset, score=0.0))
        for asset in assets
    ]
    return await asyncio.to_thread(
        use_case.build_evidence_pack,
        query=query,
        document_hits=document_hits,
        chunk_hits=chunk_hits,
        asset_hits=asset_hits,
    )


async def _run_retrieve_specialist_with_trace(
    *,
    task: AgentTask,
    request_config: AgentRequestConfig,
    turn_id: str,
    cancel_token: CancellationToken | None = None,
) -> tuple[AgentResult, list[BaseMessage]]:
    """Execute one retrieval specialist task."""

    def _cancelled_result(message: str) -> tuple[AgentResult, list[BaseMessage]]:
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
        ), [_build_retrieval_reasoning_message(turn_id=turn_id, content=message)]

    if cancel_token is not None and cancel_token.is_cancelled():
        return _cancelled_result("RetrievalAgent speculative run cancelled before execution.")

    cache_store = _graph_runtime().cache_store
    if cache_store is not None:
        cached = cache_store.load_cached_retrieval(request_config.project_id, task.query)
        if cached is not None:
            result = AgentResult(
                task_id=str(cached.get("task_id") or task.task_id),
                agent_name=str(cached.get("agent_name") or task.agent_name),
                status=str(cached.get("status") or "completed"),
                summary=str(cached.get("summary") or ""),
                artifacts=list(cached.get("artifacts", [])),
                confidence=float(cached.get("confidence", 0.0) or 0.0),
                metadata=dict(cached.get("metadata", {}) or {}),
            )
            return result, [_build_retrieval_reasoning_message(turn_id=turn_id, content="Loaded retrieval result from cache.")]

    runtime = _graph_runtime()
    use_case = runtime.retrieve_evidence_use_case
    base_model = runtime.chat_model
    trace_messages: list[BaseMessage] = []
    raw_intent_plan = await base_model.ainvoke(_build_retrieval_planning_messages(task=task))
    intent_plan = _parse_retrieval_intent_plan(raw_intent_plan)
    planner_model = base_model.bind_tools(_retrieval_tool_schema())
    trace_messages.append(
        _build_retrieval_reasoning_message(
            turn_id=turn_id,
            content="Retrieval intent plan:\n" + json.dumps(intent_plan.to_dict(), ensure_ascii=False, indent=2),
        )
    )
    tool_messages: list[Any] = [
        SystemMessage(
            content=(
                "You are RetrievalAgent. Your job is to gather local evidence with retrieval tools and then "
                "finish with the strongest document/chunk/asset ids.\n\n"
                + _retrieval_schema_summary()
                + "\n\n"
                + _build_retrieval_execution_instruction(plan=intent_plan)
            )
        ),
        HumanMessage(
            content=(
                f"Task query:\n{task.query}\n\n"
                f"Reason:\n{task.reason}\n\n"
                "Plan the retrieval path yourself. You may use MySQL-only lookup, Qdrant-only lookup, "
                "or a multi-step flow such as document narrowing then chunk retrieval. "
                "When enough evidence has been gathered, call finish_retrieval."
            )
        ),
    ]
    plan_state = _RetrievalPlanState()
    finish_payload: dict[str, Any] | None = None
    max_steps = max(2, min(8, _coerce_positive_int(task.constraints.get("max_steps"), intent_plan.max_steps)))

    for _ in range(max_steps):
        if cancel_token is not None and cancel_token.is_cancelled():
            return _cancelled_result("RetrievalAgent speculative run cancelled during tool orchestration.")
        planner_response = await planner_model.ainvoke(tool_messages)
        tool_calls = _extract_tool_calls(planner_response)
        planner_content = str(getattr(planner_response, "content", "") or "").strip()
        if planner_content:
            trace_messages.append(_build_retrieval_reasoning_message(turn_id=turn_id, content=planner_content))
        tool_messages.append(
            AIMessage(
                content=str(getattr(planner_response, "content", "") or ""),
                tool_calls=_normalize_langchain_tool_calls(tool_calls),
            )
        )
        if not tool_calls:
            break

        tool_call = tool_calls[0]
        tool_name = str(tool_call.get("name") or "")
        args = _coerce_tool_call_args(tool_call)
        tool_call_id = str(tool_call.get("id") or f"tool_{uuid4().hex[:8]}")
        if tool_name == "finish_retrieval":
            finish_payload = args
            trace_messages.append(
                _build_retrieval_tool_call_message(
                    turn_id=turn_id,
                    tool_name=tool_name,
                    args=args,
                    tool_call_id=tool_call_id,
                )
            )
            break
        trace_messages.append(
            _build_retrieval_tool_call_message(
                turn_id=turn_id,
                tool_name=tool_name,
                args=args,
                tool_call_id=tool_call_id,
            )
        )
        tool_result = await _execute_retrieval_tool(
            tool_name=tool_name,
            args=args,
            use_case=use_case,
            request_config=request_config,
            plan_state=plan_state,
            task=task,
        )
        trace_messages.append(
            _build_retrieval_tool_result_message(
                turn_id=turn_id,
                tool_name=tool_name,
                result=tool_result,
                tool_call_id=tool_call_id,
            )
        )
        tool_messages.append(
            ToolMessage(
                content=json.dumps(tool_result, ensure_ascii=False),
                tool_call_id=tool_call_id,
                name=tool_name,
            )
        )

    if finish_payload is None:
        finish_payload = {
            "document_ids": list(plan_state.document_hits.keys())[: request_config.document_limit],
            "chunk_ids": list(plan_state.chunk_hits.keys())[: request_config.chunk_limit],
            "asset_ids": list(plan_state.asset_hits.keys())[: request_config.asset_limit],
            "summary": "Fallback finish from accumulated retrieval tool results.",
        }

    evidence_pack = await _build_evidence_pack_from_selection(
        query=task.query,
        use_case=use_case,
        plan_state=plan_state,
        selected_document_ids=[str(item) for item in list(finish_payload.get("document_ids", []) or []) if str(item)],
        selected_chunk_ids=[str(item) for item in list(finish_payload.get("chunk_ids", []) or []) if str(item)],
        selected_asset_ids=[str(item) for item in list(finish_payload.get("asset_ids", []) or []) if str(item)],
    )
    if hasattr(use_case, "_append_debug_log"):
        await asyncio.to_thread(
            use_case._append_debug_log,
            query=task.query,
            project_id=request_config.project_id,
            raw_document_hits=plan_state.raw_document_hits,
            raw_chunk_hits=plan_state.raw_chunk_hits,
            raw_asset_hits=plan_state.raw_asset_hits,
            evidence_pack=evidence_pack,
        )

    result = _build_result(task=task, evidence_pack=evidence_pack, intent_plan=intent_plan)
    result.metadata["retrieval_plan"] = {
        "intent_plan": intent_plan.to_dict(),
        "summary": str(finish_payload.get("summary") or ""),
        "document_ids": list(finish_payload.get("document_ids", []) or []),
        "chunk_ids": list(finish_payload.get("chunk_ids", []) or []),
        "asset_ids": list(finish_payload.get("asset_ids", []) or []),
    }
    if cache_store is not None:
        cache_store.save_cached_retrieval(
            request_config.project_id,
            task.query,
            result.to_dict(),
            ttl_seconds=_graph_settings().redis_retrieval_cache_ttl,
        )
    return result, trace_messages


async def run_retrieve_specialist(
    *,
    task: AgentTask,
    request_config: AgentRequestConfig,
    cancel_token: CancellationToken | None = None,
) -> AgentResult:
    result, _trace_messages = await _run_retrieve_specialist_with_trace(
        task=task,
        request_config=request_config,
        turn_id=f"turn_{uuid4().hex[:8]}",
        cancel_token=cancel_token,
    )
    return result


def _build_result(*, task: AgentTask, evidence_pack: Any, intent_plan: _RetrievalIntentPlan) -> AgentResult:
    metadata = {
        "citations": build_assistant_metadata(evidence_pack.citations)["citations"],
        "asset_citations": build_asset_citations_metadata(evidence_pack.asset_citations),
        "asset_sources": build_asset_sources_metadata(evidence_pack.assets),
        "evidence_counts": _build_evidence_counts(evidence_pack),
        "evidence_pack": _serialize_evidence_pack(evidence_pack),
    }
    metadata_only_sufficient = intent_plan.target_level == "document" and bool(evidence_pack.documents)
    summary = "Found local supporting evidence."
    if metadata_only_sufficient:
        summary = "Found project document metadata."
    elif not evidence_pack.citations:
        summary = "Local retrieval returned weak evidence."
    metadata["progress_summary"] = build_progress_summary(
        done=summary,
        next="可继续基于引用展开回答或比较证据",
        pending=(
            "还没有足够强的本地引用证据"
            if not evidence_pack.citations and not metadata_only_sufficient
            else "尚未结合外部工具或工作区信息"
        ),
    )
    metadata["metadata_only_sufficient"] = metadata_only_sufficient
    artifact = AgentArtifact(
        artifact_id=f"artifact_ret_{uuid4().hex[:8]}",
        artifact_type="retrieval_evidence",
        content=(
            f"Retrieved {len(evidence_pack.documents)} documents, "
            f"{len(evidence_pack.text_chunks)} chunks, {len(evidence_pack.assets)} assets."
        ),
        metadata=metadata,
    )
    return AgentResult(
        task_id=task.task_id,
        agent_name=task.agent_name,
        status="completed",
        summary=summary,
        artifacts=[artifact.to_dict()],
        confidence=0.8 if evidence_pack.citations else (0.7 if metadata_only_sufficient else 0.25),
        metadata=metadata,
    )


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
    result, trace_messages = await _run_retrieve_specialist_with_trace(
        task=task,
        request_config=request_config,
        turn_id=turn_id,
    )
    return {
        "retrieve_result": result.to_dict(),
        "messages": [*trace_messages, _build_agent_result_message(turn_id=turn_id, result=result)],
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
