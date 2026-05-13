"""PaperLab main LangGraph orchestration graph."""

import asyncio
import json
import math
import warnings

warnings.filterwarnings("ignore", message=".*Deserializing unregistered type.*TaskEnvelope.*")
from pathlib import Path
from typing import Annotated
from typing import Any
from typing import Literal
from typing import TypedDict
from urllib.parse import quote
from uuid import uuid4

from domain import MemoryType
from prompts.builders import build_answer_or_continue_prompt
from prompts.builders import build_main_route_messages
from prompts.builders import build_synthesis_prompt

from contracts import AgentResult
from contracts import AgentTask
from memory import build_memory_service
from orchestration.assessment import parse_answer_or_continue_decision
from orchestration.graph_messages import (
    _build_agent_result_message,
    _build_agent_task_message,
    _build_assistant_message,
    _build_intervention_message,
    _build_loop_status_message,
    _build_tool_message,
    _coerce_tool_call_args,
    _dispatch_schema,
    _extract_tool_calls,
    _human_messages,
    _latest_human_text,
    _latest_messages_by_artifact,
    _latest_tool_message,
    _message_id,
    _message_meta,
    _message_name,
    _message_text,
    _result_status,
    _stringify_for_prompt,
)
from orchestration.guidance_queue import pop_guidance_messages
from orchestration.graph_serialization import (
    _serialize_memory_item,
)
from orchestration.output_summary import parse_structured_assistant_output
from orchestration.graph_state import PaperLabGraphState
from orchestration.debug_logger import (
    log_assess_decision,
    log_error,
    log_llm_call,
    log_routing_decision,
    log_specialist_dispatch,
    log_specialist_result,
    log_synthesis,
    log_tool_call,
    log_tool_result,
)
from orchestration.request_config import AgentRequestConfig
from orchestration.request_config import _coerce_positive_int
from orchestration.request_config import resolve_agent_request_config
from orchestration.runtime_access import _runtime
from runtime import AgentSettings
from runtime import CancellationToken
from workers.retriever.agent import build_retrieve_agent_graph
from workers.retriever.agent import run_retrieve_specialist
from workers.tool.agent import build_tool_agent_graph
from workers.tool.agent import run_tool_specialist
from workspace.tools import build_tool_approval_request
from workspace.tools import build_workspace_policy
from workspace.tools import execute_workspace_tool

try:
    from langchain_core.messages import AIMessage
    from langchain_core.messages import BaseMessage
    from langchain_core.messages import HumanMessage
    from langchain_core.messages import SystemMessage
    from langchain_core.runnables import RunnableConfig
    from langgraph.graph import END
    from langgraph.graph import START
    from langgraph.graph import StateGraph
    from langgraph.graph.message import add_messages
    from langgraph.types import Command
    from langgraph.types import interrupt
except ImportError:  # pragma: no cover
    AIMessage = Any  # type: ignore[assignment]
    BaseMessage = Any  # type: ignore[assignment]
    HumanMessage = Any  # type: ignore[assignment]
    SystemMessage = Any  # type: ignore[assignment]
    RunnableConfig = dict[str, Any]  # type: ignore[assignment]
    END = "__end__"
    START = "__start__"
    StateGraph = None  # type: ignore[assignment]
    add_messages = None  # type: ignore[assignment]
    Command = Any  # type: ignore[assignment]
    interrupt = None  # type: ignore[assignment]

try:
    from langgraph.checkpoint.redis import RedisSaver
except ImportError:  # pragma: no cover
    RedisSaver = None  # type: ignore[assignment]

try:
    from langgraph.checkpoint.memory import InMemorySaver
except ImportError:  # pragma: no cover
    InMemorySaver = None  # type: ignore[assignment]


class LoopInterruptPayload(TypedDict, total=False):
    phase: str
    turn_id: str
    iteration_count: int
    question: str
    pending_user_messages: int
    retrieve_task: dict[str, Any] | None
    retrieve_result_status: str


def _checkpoint_redis_url(settings: AgentSettings) -> str:
    explicit_url = settings.checkpoint_redis_url.strip()
    if explicit_url:
        return explicit_url
    auth = f":{quote(settings.redis_password, safe='')}@" if settings.redis_password else ""
    return f"redis://{auth}{settings.redis_host}:{settings.redis_port}/{settings.redis_db}"


def _checkpoint_ttl_config(settings: AgentSettings) -> dict[str, Any] | None:
    if settings.checkpoint_redis_ttl_minutes <= 0:
        return None
    return {
        "default_ttl": settings.checkpoint_redis_ttl_minutes,
        "refresh_on_read": settings.checkpoint_redis_refresh_on_read,
    }


def _build_checkpointer(settings: AgentSettings | None = None) -> Any | None:
    resolved = settings or AgentSettings.from_env()
    _allowed_msgpack = [("contracts.task_envelope", "TaskEnvelope")]
    if not resolved.checkpoint_redis_enabled:
        if InMemorySaver is None:
            return None
        try:
            from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
            serde = JsonPlusSerializer(allowed_msgpack_modules=_allowed_msgpack)
        except Exception:
            serde = None
        return InMemorySaver(serde=serde)
    if RedisSaver is None:
        raise ImportError(
            "langgraph-checkpoint-redis is required when PAPERLAB_CHECKPOINT_REDIS_ENABLED=true."
        )
    saver = RedisSaver(
        redis_url=_checkpoint_redis_url(resolved),
        ttl=_checkpoint_ttl_config(resolved),
        checkpoint_prefix=resolved.checkpoint_redis_checkpoint_prefix,
        checkpoint_write_prefix=resolved.checkpoint_redis_checkpoint_write_prefix,
    )
    saver.setup()
    return saver


def _build_loop_interrupt_payload(
    *,
    state: PaperLabGraphState,
    phase: str,
) -> LoopInterruptPayload:
    messages = list(state.get("messages", []))
    human_messages = _human_messages(messages)
    processed_count = int(state.get("processed_human_message_count", 0) or 0)
    retrieve_result = dict(state.get("retrieve_result", {}) or {})
    return {
        "phase": phase,
        "turn_id": str(state.get("active_turn_id") or ""),
        "iteration_count": int(state.get("iteration_count", 0) or 0),
        "question": _message_text(_latest_human_text(messages)) if messages else "",
        "pending_user_messages": max(0, len(human_messages) - processed_count),
        "retrieve_task": state.get("retrieve_task").to_dict() if state.get("retrieve_task") else None,
        "retrieve_result_status": _result_status(retrieve_result),
    }


def _memory_backend() -> Any | None:
    """Return the configured long-term memory backend with compatibility for older runtimes."""

    runtime = _runtime()
    return getattr(runtime, "memory_backend", getattr(runtime, "memory_store", None))


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm <= 0.0 or right_norm <= 0.0:
        return 0.0
    return numerator / (left_norm * right_norm)


def _token_overlap_score(left: str, right: str) -> float:
    left_tokens = {token for token in left.casefold().replace("_", " ").split() if token}
    right_tokens = {token for token in right.casefold().replace("_", " ").split() if token}
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / max(len(left_tokens), len(right_tokens))


def _speculative_query_match(
    *,
    runtime: Any,
    formal_query: str,
    speculative_query: str,
    settings: AgentSettings | None = None,
) -> dict[str, Any]:
    formal = " ".join(str(formal_query or "").split())
    speculative = " ".join(str(speculative_query or "").split())
    if not formal or not speculative:
        return {"matched": False, "method": "empty", "score": 0.0}
    if formal.casefold() == speculative.casefold():
        return {"matched": True, "method": "exact", "score": 1.0}

    resolved_settings = settings or AgentSettings.from_env()
    use_case = getattr(runtime, "retrieve_evidence_use_case", None)
    reranker = getattr(use_case, "reranker_provider", None)
    if reranker is not None:
        try:
            scores = reranker.rerank(formal, [speculative], 1)
            score = float(scores[0]) if scores else 0.0
            return {
                "matched": score >= float(resolved_settings.speculative_reranker_threshold),
                "method": "reranker",
                "score": score,
            }
        except Exception:  # noqa: BLE001
            pass

    embedding_provider = getattr(use_case, "embedding_provider", None)
    if embedding_provider is not None:
        try:
            vectors = embedding_provider.embed_texts([formal, speculative])
            score = _cosine_similarity(list(vectors[0]), list(vectors[1])) if len(vectors) >= 2 else 0.0
            return {
                "matched": score >= float(resolved_settings.speculative_embedding_threshold),
                "method": "embedding",
                "score": score,
            }
        except Exception:  # noqa: BLE001
            pass

    score = _token_overlap_score(formal, speculative)
    return {"matched": score >= 0.75, "method": "token_overlap", "score": score}


def _formal_constraints_fit_speculative(
    *,
    formal: dict[str, Any],
    speculative: dict[str, Any],
) -> bool:
    for key in ("document_limit", "chunk_limit", "asset_limit", "top_k"):
        if key not in formal:
            continue
        formal_value = formal.get(key)
        speculative_value = speculative.get(key)
        if formal_value is None or speculative_value is None:
            continue
        try:
            if int(speculative_value) < int(formal_value):
                return False
        except (TypeError, ValueError):
            return False
    return True


def _cleanup_speculative_run(runtime: Any, run_id: str) -> None:
    if hasattr(runtime, "cleanup_speculative_run"):
        runtime.cleanup_speculative_run(run_id)


def _discard_speculative_run(runtime: Any, run_id: str) -> None:
    if hasattr(runtime, "cancel_speculative_run"):
        runtime.cancel_speculative_run(run_id)
    if hasattr(runtime, "mark_speculative_run_for_cleanup"):
        runtime.mark_speculative_run_for_cleanup(run_id)
    else:
        _cleanup_speculative_run(runtime, run_id)


async def _run_speculative_memory_task(
    *,
    task: AgentTask,
    request_config: AgentRequestConfig,
    cancel_token: CancellationToken | None = None,
) -> AgentResult:
    if cancel_token is not None and cancel_token.is_cancelled():
        return AgentResult(
            task_id=task.task_id,
            agent_name=task.agent_name,
            status="cancelled",
            summary="Speculative memory recall cancelled before execution.",
            artifacts=[],
            confidence=0.0,
            metadata={"cancelled": True, "query": task.query, "memory_hits": []},
        )
    memory_service = build_memory_service(
        backend=_memory_backend(),
        settings=AgentSettings.from_env(),
    )
    limit = int(task.constraints.get("limit") or request_config.memory_limit)
    recall_result = await asyncio.to_thread(
        memory_service.recall,
        role="supervisor",
        query=task.query,
        project_id=request_config.project_id,
        limit=limit,
    )
    summary = recall_result.summary or "Relevant memory:\n- none"
    return AgentResult(
        task_id=task.task_id,
        agent_name=task.agent_name,
        status="completed",
        summary=summary,
        artifacts=[],
        confidence=1.0,
        metadata={
            "query": task.query,
            "reason": task.reason,
            "memory_hits": [_serialize_memory_item(item) for item in recall_result.hits],
            "summary": recall_result.summary,
        },
    )


def _start_speculative_runs(
    *,
    runtime: Any,
    turn_id: str,
    question: str,
    request_config: AgentRequestConfig,
    settings: AgentSettings,
) -> dict[str, dict[str, Any] | None]:
    if not settings.speculative_execution_enabled:
        return {"speculative_memory": None, "speculative_retrieval": None}

    started: dict[str, dict[str, Any] | None] = {"speculative_memory": None, "speculative_retrieval": None}
    if not hasattr(runtime, "start_speculative_run"):
        return started

    memory_task = AgentTask(
        task_id=f"task_mem_spec_{uuid4().hex[:8]}",
        task_type="memory_recall",
        agent_name="memory_agent",
        query=question,
        reason="Speculative memory recall from raw user input.",
        constraints={"limit": request_config.memory_limit},
        metadata={"project_id": request_config.project_id},
    )
    memory_record = runtime.start_speculative_run(
        turn_id=turn_id,
        task=memory_task,
        runner=lambda token: _run_speculative_memory_task(
            task=memory_task,
            request_config=request_config,
            cancel_token=token,
        ),
    )
    started["speculative_memory"] = {
        "run_id": memory_record.run_id,
        "query": memory_task.query,
        "reason": memory_task.reason,
        "constraints": dict(memory_task.constraints),
    }

    if getattr(runtime, "retrieve_evidence_use_case", None) is not None:
        retrieve_task = AgentTask(
            task_id=f"task_ret_spec_{uuid4().hex[:8]}",
            task_type="local_retrieval",
            agent_name="retrieval_agent",
            query=question,
            reason="Speculative retrieval from raw user input.",
            constraints={
                "document_limit": request_config.document_limit,
                "chunk_limit": request_config.chunk_limit,
                "asset_limit": request_config.asset_limit,
            },
            metadata={"project_id": request_config.project_id, "speculative": True},
        )
        retrieve_record = runtime.start_speculative_run(
            turn_id=turn_id,
            task=retrieve_task,
            runner=lambda token: run_retrieve_specialist(
                task=retrieve_task,
                request_config=request_config,
                cancel_token=token,
            ),
        )
        started["speculative_retrieval"] = {
            "run_id": retrieve_record.run_id,
            "query": retrieve_task.query,
            "reason": retrieve_task.reason,
            "constraints": dict(retrieve_task.constraints),
        }
    return started


def _memory_write_schema() -> list[dict[str, object]]:
    return [_memory_write_tool_schema()]


def _answer_or_loop_schema() -> list[dict[str, object]]:
    return [
        _memory_write_tool_schema(),
        {
            "type": "function",
            "function": {
                "name": "continue_evidence_loop",
                "description": (
                    "Call this virtual tool when the current evidence is not enough to answer. "
                    "Provide concrete follow-up evidence tasks for the next routing loop."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "reason": {"type": "string"},
                        "next_tasks": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "required": ["reason", "next_tasks"],
                },
            },
        },
    ]


def _main_workspace_tool_schema(request_config: AgentRequestConfig) -> list[dict[str, object]]:
    schemas: list[dict[str, object]] = [
        {
            "type": "function",
            "function": {
                "name": "get_current_time",
                "description": "获取当前日期和时间，包括本地时间、UTC时间、星期和时区信息。",
                "parameters": {"type": "object", "properties": {}},
            },
        },
    ]
    if request_config.allow_file_read:
        schemas.extend(
            [
                {
                    "type": "function",
                    "function": {
                        "name": "detect_platform",
                        "description": "Detect the current server operating system and available file search tools.",
                        "parameters": {"type": "object", "properties": {}},
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "list_files",
                        "description": "List files or directories under the workspace root.",
                        "parameters": {
                            "type": "object",
                            "properties": {"path": {"type": "string"}},
                            "required": ["path"],
                        },
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "find_files",
                        "description": "Find files by pattern under the workspace root.",
                        "parameters": {
                            "type": "object",
                            "properties": {"pattern": {"type": "string"}, "limit": {"type": "integer"}},
                        },
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "search_text",
                        "description": "Search text in workspace files.",
                        "parameters": {
                            "type": "object",
                            "properties": {"pattern": {"type": "string"}, "path": {"type": "string"}, "limit": {"type": "integer"}},
                            "required": ["pattern"],
                        },
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "description": "Read one UTF-8 workspace file.",
                        "parameters": {
                            "type": "object",
                            "properties": {"path": {"type": "string"}, "max_chars": {"type": "integer"}},
                            "required": ["path"],
                        },
                    },
                },
            ]
        )
    if request_config.allow_file_write:
        schemas.extend(
            [
                {
                    "type": "function",
                    "function": {
                        "name": "write_file",
                        "description": "Write a UTF-8 file under the workspace root. Requires user approval.",
                        "parameters": {
                            "type": "object",
                            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                            "required": ["path", "content"],
                        },
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "delete_file",
                        "description": "Delete one file or directory under the workspace root. Requires user approval.",
                        "parameters": {
                            "type": "object",
                            "properties": {"path": {"type": "string"}},
                            "required": ["path"],
                        },
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "run_command",
                        "description": "Run one allowed command with cwd fixed to the workspace root. Requires user approval.",
                        "parameters": {
                            "type": "object",
                            "properties": {"command": {"type": "string"}, "timeout_seconds": {"type": "integer"}},
                            "required": ["command"],
                        },
                    },
                },
            ]
        )
    return schemas


def _tool_search_virtual_schema() -> dict[str, object]:
    return {
        "type": "function",
        "function": {
            "name": "tool_search",
            "description": "Search for additional tools when none of the currently available tools fit the task.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["query", "reason"],
            },
        },
    }


def _external_tool_schemas_from_result(
    tool_result: dict[str, Any],
    *,
    request_config: AgentRequestConfig,
) -> list[dict[str, object]]:
    if not (request_config.allow_web_search or request_config.allow_mcp):
        return []
    metadata = dict(tool_result.get("metadata", {}) or {})
    recommended = list(metadata.get("recommended_tools", []) or [])
    schemas: list[dict[str, object]] = []
    for item in recommended:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        kind = str(item.get("kind") or "").strip()
        if kind == "web" and not request_config.allow_web_search:
            continue
        if kind == "mcp" and not request_config.allow_mcp:
            continue
        schemas.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": str(item.get("description") or ""),
                    "parameters": dict(item.get("input_schema", {}) or {"type": "object", "properties": {}}),
                },
            }
        )
    return schemas


def _memory_write_tool_schema() -> dict[str, object]:
    return {
        "type": "function",
        "function": {
            "name": "decide_memory_write",
            "description": (
                "Decide whether to write a cross-session long-term memory from this completed turn. "
                "This memory is durable across future sessions, so default to no write unless the content is clearly stable and reusable."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["none", "store"]},
                    "memory_type": {
                        "type": "string",
                        "enum": [
                            MemoryType.PREFERENCE.value,
                            MemoryType.PROJECT_FACT.value,
                            MemoryType.RESEARCH_EPISODE.value,
                        ],
                    },
                    "content": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["action", "memory_type", "content", "reason"],
            },
        },
    }


def _parse_continue_loop_decision(raw_answer: Any) -> dict[str, object]:
    tool_calls = [
        call
        for call in _extract_tool_calls(raw_answer)
        if str(call.get("name") or "") == "continue_evidence_loop"
    ]
    if not tool_calls:
        return {"should_loop": False, "reason": "", "next_tasks": []}
    args = _coerce_tool_call_args(tool_calls[0])
    next_tasks = []
    for item in list(args.get("next_tasks", []) or []):
        text = str(item).strip()
        if text:
            next_tasks.append(text)
    return {
        "should_loop": True,
        "reason": str(args.get("reason") or "").strip(),
        "next_tasks": next_tasks,
    }


def _default_memory_write_decision() -> dict[str, object]:
    return {
        "action": "none",
        "should_write": False,
        "memory_type": MemoryType.RESEARCH_EPISODE.value,
        "content": "",
        "reason": "No explicit long-term memory write decision.",
    }


def _parse_memory_write_decision(raw_answer: Any) -> dict[str, object]:
    tool_calls = [
        call
        for call in _extract_tool_calls(raw_answer)
        if str(call.get("name") or "") == "decide_memory_write"
    ]
    if not tool_calls:
        return _default_memory_write_decision()

    args = _coerce_tool_call_args(tool_calls[0])
    action = str(args.get("action") or "none").strip().lower()
    if action not in {"none", "store"}:
        action = "none"
    should_write = action == "store"
    content = str(args.get("content") or "").strip()
    memory_type = str(args.get("memory_type") or MemoryType.RESEARCH_EPISODE.value)
    if memory_type not in {item.value for item in MemoryType}:
        memory_type = MemoryType.RESEARCH_EPISODE.value
    if not content:
        should_write = False
        action = "none"
    return {
        "action": action,
        "should_write": should_write,
        "memory_type": memory_type,
        "content": content if should_write else "",
        "reason": str(args.get("reason") or "").strip(),
    }


def _coerce_tool_approval_decision(value: Any) -> dict[str, object]:
    if not isinstance(value, dict):
        return {"action": "reject"}
    action = str(value.get("action") or "").strip().lower()
    if action not in {"approve", "reject", "edit"}:
        action = "reject"
    if action == "edit" and isinstance(value.get("args"), dict):
        return {"action": "edit", "args": dict(value["args"])}
    return {"action": action}


def _execute_main_workspace_tool(
    tool_call: dict[str, Any],
    *,
    request_config: AgentRequestConfig,
    skip_approval: bool = False,
) -> dict[str, object]:
    tool_name = str(tool_call.get("name") or "")
    args = _coerce_tool_call_args(tool_call)
    workspace_root = Path(request_config.workspace_root or Path.cwd())
    policy = build_workspace_policy(
        root=workspace_root,
        allow_file_read=request_config.allow_file_read,
        allow_file_write=request_config.allow_file_write,
        allow_shell=request_config.allow_shell,
    )
    approval = build_tool_approval_request(
        tool_call_id=str(tool_call.get("id") or f"main_tool_{uuid4().hex[:8]}"),
        tool_name=tool_name,
        args=args,
    )
    if approval is not None and interrupt is not None and not skip_approval:
        resume_value = interrupt(
            {
                "type": "tool_approval",
                "question": approval.preview,
                "approval": approval.to_dict(),
            }
        )
        decision = _coerce_tool_approval_decision(resume_value)
        if decision["action"] == "reject":
            return {
                "tool_name": tool_name,
                "args": args,
                "status": "rejected",
                "summary": f"Tool call rejected: {approval.preview}",
                "content": "",
            }
        if isinstance(decision.get("args"), dict):
            args = dict(decision["args"])
    result = execute_workspace_tool(
        root=workspace_root,
        tool_name=tool_name,
        args=args,
        policy=policy,
    )
    return {
        "tool_name": tool_name,
        "args": args,
        "status": "completed",
        **result,
    }


async def _execute_selected_external_tool(
    tool_call: dict[str, Any],
    *,
    request_config: AgentRequestConfig,
) -> dict[str, object]:
    tool_name = str(tool_call.get("name") or "")
    args = _coerce_tool_call_args(tool_call)
    if tool_name == "web_search":
        if not request_config.allow_web_search:
            raise ValueError("Tool 'web_search' is not enabled.")
        web_provider = _runtime().web_search_provider
        if web_provider is None:
            raise ValueError("Web search provider is unavailable.")
        query = str(args.get("query") or "").strip()
        if not query:
            raise ValueError("web_search requires a query.")
        top_k = _coerce_positive_int(args.get("top_k"), AgentSettings.from_env().web_search_result_limit)
        results = await asyncio.to_thread(web_provider.search, query, top_k)
        web_sources = []
        for item in results:
            metadata = dict(getattr(item, "metadata", {}) or {})
            web_sources.append(
                {
                    "title": str(metadata.get("title") or ""),
                    "url": str(metadata.get("url") or ""),
                    "snippet": str(metadata.get("snippet") or ""),
                }
            )
        return {
            "tool_name": tool_name,
            "args": args,
            "status": "completed",
            "summary": f"web_search returned {len(web_sources)} result(s).",
            "content": json.dumps(web_sources, ensure_ascii=False, indent=2),
            "web_sources": web_sources,
        }
    if tool_name == "url_fetch":
        if not request_config.allow_web_search:
            raise ValueError("Tool 'url_fetch' is not enabled.")
        web_provider = _runtime().web_search_provider
        if web_provider is None:
            raise ValueError("Web search provider is unavailable.")
        url = str(args.get("url") or "").strip()
        if not url:
            raise ValueError("url_fetch requires a url.")
        result = await asyncio.to_thread(web_provider.fetch, url)
        metadata = dict(getattr(result, "metadata", {}) or {})
        page = {
            "title": str(metadata.get("title") or ""),
            "url": str(metadata.get("url") or url),
            "excerpt": str(metadata.get("excerpt") or ""),
        }
        return {
            "tool_name": tool_name,
            "args": args,
            "status": "completed",
            "summary": "Fetched one web page.",
            "content": str(getattr(result, "text", "") or ""),
            "web_sources": [page],
        }
    if not request_config.allow_mcp:
        raise ValueError(f"Tool '{tool_name}' is not enabled.")
    mcp_provider = _runtime().mcp_tool_provider
    if mcp_provider is None:
        raise ValueError("MCP provider is unavailable.")
    result = await mcp_provider.call_tool(tool_name, args)
    return {
        "tool_name": tool_name,
        "args": args,
        "status": "failed" if bool(result.get("is_error")) else "completed",
        "summary": f"Called MCP tool '{tool_name}'.",
        "content": str(result.get("text") or ""),
        "structured_content": result.get("structured_content"),
        "tool_sources": [
            {
                "kind": "mcp",
                "title": tool_name,
                "tool_name": tool_name,
                "summary": str(result.get("text") or "")[:800],
            }
        ],
    }


def _coerce_memory_type(value: object) -> MemoryType:
    try:
        return MemoryType(str(value))
    except ValueError:
        return MemoryType.RESEARCH_EPISODE


def _is_cross_paper_synthesis_question(question: str) -> bool:
    normalized = str(question or "").strip().lower()
    if not normalized:
        return False
    cues = (
        "综合",
        "综述",
        "现状",
        "研究现状",
        "研究图景",
        "研究脉络",
        "比较",
        "对比",
        "landscape",
        "survey",
        "state of the art",
        "state-of-the-art",
        "research state",
        "research landscape",
        "compare",
        "comparison",
    )
    return any(cue in normalized for cue in cues)


def _structure_retrieval_task_for_synthesis(
    *,
    question: str,
    retrieval_query: str,
    retrieval_reason: str,
) -> tuple[str, str, dict[str, Any]]:
    if not _is_cross_paper_synthesis_question(question):
        return retrieval_query, retrieval_reason, {}

    structured_query = (
        "Cross-paper evidence gathering for final synthesis.\n"
        f"User question:\n{question}\n\n"
        "For each relevant paper in the local corpus, gather the minimum evidence needed for synthesis:\n"
        "1. research problem / target task\n"
        "2. core method, framework, or system\n"
        "3. main findings or claimed improvements\n"
        "4. scope, assumptions, or limitations if visible from abstract/introduction/conclusion\n\n"
        "Then organize the retrieved evidence into a compact comparative view grouped by theme, such as:\n"
        "- agent or AI skill security\n"
        "- vulnerability detection and analysis\n"
        "- exploit generation or offensive automation\n"
        "- patch tracking or vulnerability management\n\n"
        "Do not write the final literature review. Focus on evidence collection and structured paper-level findings that the supervisor can synthesize."
    )
    structured_reason = (
        "Need structured cross-paper evidence rather than a direct literature review. "
        "Retrieve per-paper problem/method/findings/scope so the supervisor can synthesize the final research-state answer."
    )
    return structured_query, structured_reason, {
        "retrieval_mode": "cross_paper_synthesis",
        "evidence_fields": [
            "research_problem",
            "method_or_system",
            "main_findings",
            "scope_or_limitations",
        ],
        "synthesis_axes": [
            "agent_security",
            "vulnerability_detection",
            "exploit_generation",
            "patch_management",
        ],
    }


def _materialize_intervention_update(
    *,
    state: PaperLabGraphState,
    config: RunnableConfig | None,
    phase: str,
    resume_value: Any = None,
) -> dict[str, Any]:
    request_config = resolve_agent_request_config(dict(config or {}))
    turn_id = str(state.get("active_turn_id") or f"turn_{uuid4().hex[:8]}")
    messages = list(state.get("messages", []))
    human_messages = _human_messages(messages)
    processed_count = int(state.get("processed_human_message_count", 0) or 0)
    unseen_humans = human_messages[processed_count:]

    new_interventions: list[HumanMessage] = []
    intervention_texts: list[str] = []
    for message in [*unseen_humans, *_pending_human_messages_from_resume(resume_value)]:
        artifact_type = str(_message_meta(message).get("artifact_type") or "")
        if artifact_type in {"question", "intervention"}:
            continue
        text = _message_text(message.content).strip()
        if not text:
            continue
        if text in intervention_texts:
            continue
        new_interventions.append(
            _build_intervention_message(
                turn_id=turn_id,
                content=text,
                project_id=request_config.project_id,
                thread_id=request_config.thread_id,
            )
        )
        intervention_texts.append(text)

    summary = (
        f"Captured {len(new_interventions)} new user guidance message(s) at {phase}."
        if new_interventions
        else f"Loop checkpoint reached at {phase}."
    )
    loop_status = _build_loop_status_message(
        turn_id=turn_id,
        phase=phase,
        summary=summary,
        iteration_count=int(state.get("iteration_count", 0) or 0),
        metadata={
            "intervention_count": int(state.get("intervention_count", 0) or 0)
            + len(new_interventions),
            "guidance_messages": intervention_texts,
        },
    )
    return {
        "messages": [*new_interventions, loop_status],
        "processed_human_message_count": len(human_messages) + len(new_interventions),
        "intervention_count": int(state.get("intervention_count", 0) or 0)
        + len(new_interventions),
        "answer_confident": False,
        "stop_reason": "",
    }


def _pending_human_messages_from_resume(resume_value: Any) -> list[HumanMessage]:
    if not isinstance(resume_value, dict):
        return []
    raw_messages = list(resume_value.get("pending_messages", []) or [])
    pending: list[HumanMessage] = []
    for raw_message in raw_messages:
        if not isinstance(raw_message, dict):
            continue
        if str(raw_message.get("type") or "human") != "human":
            continue
        content = str(raw_message.get("content") or "").strip()
        if not content:
            continue
        pending.append(HumanMessage(content=content))
    return pending


def _resume_value_from_guidance_queue(
    *,
    config: RunnableConfig | None,
) -> dict[str, object]:
    request_config = resolve_agent_request_config(dict(config or {}))
    queued_messages = pop_guidance_messages(
        project_id=request_config.project_id,
        thread_id=request_config.thread_id,
    )
    if not queued_messages:
        return {"action": "continue"}
    return {
        "action": "continue_with_guidance",
        "pending_messages": [
            {"type": "human", "content": message}
            for message in queued_messages
        ],
    }


async def thread_lock_node(
    state: PaperLabGraphState,
    config: RunnableConfig | None = None,
) -> PaperLabGraphState:
    """Wait for the per-thread answer lock before starting specialist dispatch."""

    request_config = resolve_agent_request_config(dict(config or {}))
    cache_store = _runtime().cache_store
    if cache_store is None or not request_config.thread_id:
        return {}

    settings = AgentSettings.from_env()
    lock_key = cache_store.thread_lock_key(request_config.thread_id)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + max(0, settings.redis_thread_lock_wait_seconds)
    poll_seconds = max(0.001, settings.redis_thread_lock_poll_ms / 1000.0)

    while True:
        if cache_store.acquire_lock(lock_key, settings.redis_lock_ttl):
            return {"thread_lock_key": lock_key}
        if loop.time() >= deadline:
            raise TimeoutError("Thread is still busy after waiting.")
        await asyncio.sleep(poll_seconds)


def release_thread_lock_node(
    state: PaperLabGraphState,
    config: RunnableConfig | None = None,
) -> PaperLabGraphState:
    """Release the per-thread answer lock after the answer pipeline finishes."""

    request_config = resolve_agent_request_config(dict(config or {}))
    cache_store = _runtime().cache_store
    if cache_store is None or not request_config.thread_id:
        return {}

    lock_key = str(
        state.get("thread_lock_key") or cache_store.thread_lock_key(request_config.thread_id)
    )
    if lock_key:
        cache_store.release_lock(lock_key)
    return {"thread_lock_key": ""}


def prepare_turn_node(
    state: PaperLabGraphState,
    config: RunnableConfig | None = None,
) -> PaperLabGraphState:
    """Normalize the latest user input into one structured message.

    prepare_turn_node 是主 Agent 图每一轮开始前的初始化节点。它会从当前 messages 中找到最新的用户输入，如果这条消息还没有被标准化，
    就把它包装成带有 artifact_type="question"、turn_id、project_id、thread_id 等元数据的 HumanMessage，并把它作为本轮正式问题写回 state。
    同时，它会初始化这一轮运行所需的控制状态，例如 active_turn_id、iteration_count=0、max_iterations、answer_confident=False、stop_reason=""、
    processed_human_message_count 和 intervention_count。如果最新消息已经是标准化后的 question，它不会重复创建消息，只会恢复并重置本轮状态。
    整体来说，这个函数负责把普通用户输入转换成 graph 内部可追踪、可恢复、可关联后续任务结果的标准 turn。
    
    """

    request_config = resolve_agent_request_config(dict(config or {}))
    messages = list(state.get("messages", []))
    latest_human = next(
        (message for message in reversed(messages) if getattr(message, "type", "") == "human"),
        None,
    )
    if latest_human is None:
        return {}

    human_count = len(_human_messages(messages))
    existing_meta = _message_meta(latest_human)
    if existing_meta.get("artifact_type") == "question":
        turn_id = str(
            existing_meta.get("turn_id")
            or state.get("active_turn_id")
            or f"turn_{uuid4().hex[:8]}"
        )
        return {
            "active_turn_id": turn_id,
            "iteration_count": 0,
            "max_iterations": request_config.max_iterations,
            "answer_confident": False,
            "stop_reason": "",
            "processed_human_message_count": human_count,
            "intervention_count": 0,
        }

    turn_id = f"turn_{uuid4().hex[:8]}"
    structured_question = HumanMessage(
        id=f"question_{turn_id}_{uuid4().hex[:8]}",
        content=_message_text(latest_human.content),
        additional_kwargs={
            "name": "question",
            "metadata": {
                "artifact_type": "question",
                "turn_id": turn_id,
                "project_id": request_config.project_id,
                "thread_id": request_config.thread_id,
            },
        },
    )
    return {
        "messages": [structured_question],
        "active_turn_id": turn_id,
        "iteration_count": 0,
        "max_iterations": request_config.max_iterations,
        "answer_confident": False,
        "stop_reason": "",
        "processed_human_message_count": human_count + 1,
        "intervention_count": 0,
    }


def build_short_term_context_node(
    state: PaperLabGraphState,
    config: RunnableConfig | None = None,
) -> PaperLabGraphState:
    """Build a short-term context artifact from recent conversation turns.
    
构建当前对话轮次的短期上下文。
这个节点会读取当前 graph state 里的 messages，
从中提取最近几轮 human / ai 对话内容，
然后整理成一段 short_term_context 文本。

它的目的不是回答问题，也不是检索论文，
而是帮助后续节点理解用户当前问题的上下文。
例如用户说“那下一个呢”“这个函数呢”时，
后续节点可以通过短期上下文知道用户指的是什么。

这里虽然使用了 MemoryService，
但传入的是 backend=None，
所以它不会查询长期记忆，也不会访问向量数据库。
它只是复用 MemoryService 里的短期上下文整理逻辑。

如果成功生成上下文，就会创建一条特殊的 ToolMessage：
name = "build_short_term_context"
artifact_type = "short_term_context"

这条消息会被追加回 state["messages"]，
后面的 main_route_node 会用它来判断该调用哪些专家，
最后的 answer-or-loop assess_node 也会用它来辅助判断是否直接生成最终回答。

简单理解：
prepare_turn_node 负责确定“这一轮用户问了什么”；
build_short_term_context_node 负责补充“这一轮之前聊过什么”。
# """

    request_config = resolve_agent_request_config(dict(config or {}))
    settings = AgentSettings.from_env()
    turn_id = str(state.get("active_turn_id") or f"turn_{uuid4().hex[:8]}")
    memory_service = build_memory_service(
        backend=None,
        settings=settings,
    )
    context_text = memory_service.build_short_term_context(
        role="supervisor",
        messages=list(state.get("messages", [])),
    )
    if not context_text:
        return {}

    lines = [line.strip() for line in context_text.splitlines() if line.strip()]
    recent_payload = [
        {"role": "system", "content": line.removeprefix("- ").strip()}
        for line in lines
        if line.startswith("- ")
    ]
    conversation_summary = (
        context_text.split("Recent raw turns:\n", maxsplit=1)[0].strip()
        if "Recent raw turns:\n" in context_text
        else ""
    )

    context_message = _build_tool_message(
        turn_id=turn_id,
        name="build_short_term_context",
        content=context_text or "No recent conversation context.",
        metadata={
            "artifact_type": "short_term_context",
            "recent_messages": recent_payload,
            "conversation_summary": conversation_summary,
            "project_id": request_config.project_id,
            "thread_id": request_config.thread_id,
            "reusable": False,
        },
    )

    if request_config.thread_id and _runtime().cache_store is not None:
        _runtime().cache_store.save_thread_context(
            request_config.thread_id,
            {
                "turn_id": turn_id,
                "recent_messages": recent_payload,
                "conversation_summary": conversation_summary,
            },
            ttl_seconds=settings.redis_thread_context_ttl,
        )
    return {"messages": [context_message]}


def guidance_gate_pre_route_node(
    state: PaperLabGraphState,
    config: RunnableConfig | None = None,
) -> Command[Literal["main_route"]]:
    """Pause before main routing so the UI can inject new guidance."""

    resume_value = _resume_value_from_guidance_queue(config=config)
    return Command(
        update=_materialize_intervention_update(
            state=state,
            config=config,
            phase="guidance_gate_pre_route",
            resume_value=resume_value,
        ),
        goto="main_route",
    )


async def main_route_node(
    state: PaperLabGraphState,
    config: RunnableConfig | None = None,
) -> PaperLabGraphState:
    """Turn the latest conversation state into specialist tasks."""

    request_config = resolve_agent_request_config(dict(config or {}))
    settings = AgentSettings.from_env()
    runtime = _runtime()
    turn_id = str(state.get("active_turn_id") or f"turn_{uuid4().hex[:8]}")
    messages = list(state.get("messages", []))
    question = _latest_human_text(messages)
    speculative_runs = _start_speculative_runs(
        runtime=runtime,
        turn_id=turn_id,
        question=question,
        request_config=request_config,
        settings=settings,
    )
    short_term_message = _latest_tool_message(messages, "build_short_term_context", turn_id=turn_id)
    memory_message = _latest_tool_message(messages, "search_memory", turn_id=turn_id)
    intervention_messages = _latest_messages_by_artifact(messages, "intervention", turn_id=turn_id)
    assessment_guidance = _latest_assessment_guidance(messages, turn_id=turn_id)

    tool_status_lines = [
        f"- 网络搜索: {'ON' if request_config.allow_web_search else 'OFF'}",
        f"- MCP 外部工具: {'ON' if request_config.allow_mcp else 'OFF'}",
        f"- 文件读取: {'ON' if request_config.allow_file_read else 'OFF'}",
        f"- 文件写入: {'ON' if request_config.allow_file_write else 'OFF'}",
    ]

    system_prompt, user_prompt = build_main_route_messages(
        question=question,
        short_term_context=_message_text(short_term_message.content) if short_term_message is not None else "",
        memory_context=_message_text(memory_message.content) if memory_message is not None else "",
        interventions=[_message_text(message.content) for message in intervention_messages],
        assessment_guidance=assessment_guidance,
        disabled_capabilities=tool_status_lines,
    )
    bound_model = runtime.chat_model.bind_tools(_dispatch_schema())
    response = await bound_model.ainvoke(
        [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
    )
    tool_calls = _extract_tool_calls(response)
    args = _coerce_tool_call_args(tool_calls[0]) if tool_calls else {}

    run_memory = bool(args.get("run_memory", False))
    memory_query = str(args.get("memory_query") or question)
    memory_reason = str(args.get("memory_reason") or "Need earlier user or project context.")
    run_retrieval = bool(args.get("run_retrieval", False))
    retrieval_query = str(args.get("retrieval_query") or question)
    retrieval_reason = str(args.get("retrieval_reason") or "Need project-grounded evidence.")
    task_messages: list[BaseMessage] = []
    retrieve_task: AgentTask | None = None

    log_routing_decision(
        turn_id=turn_id,
        question=question,
        run_retrieval=run_retrieval,
        run_memory=run_memory,
        retrieval_query=retrieval_query,
        disabled_capabilities=[cap for cap in tool_status_lines if "OFF" in cap],
    )

    if run_retrieval:
        retrieval_query, retrieval_reason, retrieval_metadata = _structure_retrieval_task_for_synthesis(
            question=question,
            retrieval_query=retrieval_query,
            retrieval_reason=retrieval_reason,
        )
        retrieve_task = AgentTask(
            task_id=f"task_ret_{uuid4().hex[:8]}",
            task_type="local_retrieval",
            agent_name="retrieval_agent",
            query=retrieval_query,
            reason=retrieval_reason,
            constraints={
                "document_limit": request_config.document_limit,
                "chunk_limit": request_config.chunk_limit,
                "asset_limit": request_config.asset_limit,
            },
            metadata={"project_id": request_config.project_id, **retrieval_metadata},
        )
        task_messages.append(_build_agent_task_message(turn_id=turn_id, task=retrieve_task))
        log_specialist_dispatch(
            turn_id=turn_id,
            agent_name="retrieval_agent",
            task_id=retrieve_task.task_id,
            query=retrieval_query,
            reason=retrieval_reason,
        )

    if not run_memory and speculative_runs.get("speculative_memory"):
        _discard_speculative_run(runtime, str(speculative_runs["speculative_memory"].get("run_id") or ""))
        speculative_runs["speculative_memory"] = None
    if not run_retrieval and speculative_runs.get("speculative_retrieval"):
        _discard_speculative_run(runtime, str(speculative_runs["speculative_retrieval"].get("run_id") or ""))
        speculative_runs["speculative_retrieval"] = None

    dispatched_agents = [
        task.agent_name
        for task in (retrieve_task,)
        if task is not None
    ]
    task_messages.append(
        _build_loop_status_message(
            turn_id=turn_id,
            phase="main_route_complete",
            summary=(
                "MainRoute prepared "
                + ("memory recall, " if run_memory else "")
                + (", ".join(dispatched_agents) if dispatched_agents else "no specialists")
                + "."
            ),
            iteration_count=int(state.get("iteration_count", 0) or 0) + 1,
            metadata={"dispatched_agents": dispatched_agents, "run_memory": run_memory},
        )
    )
    return {
        "messages": task_messages,
        "iteration_count": int(state.get("iteration_count", 0) or 0) + 1,
        "run_memory": run_memory,
        "memory_query": memory_query,
        "memory_reason": memory_reason,
        "retrieve_task": retrieve_task,
        "speculative_memory": speculative_runs.get("speculative_memory"),
        "speculative_retrieval": speculative_runs.get("speculative_retrieval"),
        "retrieve_result": None,
        "tool_result": None,
        "answer_confident": False,
        "stop_reason": "",
    }


def guidance_gate_post_route_node(
    state: PaperLabGraphState,
    config: RunnableConfig | None = None,
) -> Command[Literal["parallel_specialists"]]:
    """Pause after routing and before specialist execution."""

    resume_value = _resume_value_from_guidance_queue(config=config)
    return Command(
        update=_materialize_intervention_update(
            state=state,
            config=config,
            phase="guidance_gate_post_route",
            resume_value=resume_value,
        ),
        goto="parallel_specialists",
    )


async def parallel_specialists_node(
    state: PaperLabGraphState,
    config: RunnableConfig | None = None,
) -> PaperLabGraphState:
    """Run retrieval and external tool specialists concurrently for one routing iteration."""

    turn_id = str(state.get("active_turn_id") or f"turn_{uuid4().hex[:8]}")
    retrieve_task = state.get("retrieve_task")

    async def run_retrieval() -> tuple[AgentResult | None, list[BaseMessage]]:
        if retrieve_task is None:
            return None, []
        speculative_retrieval = dict(state.get("speculative_retrieval", {}) or {})
        speculative_run_id = str(speculative_retrieval.get("run_id") or "")
        if speculative_run_id and _formal_constraints_fit_speculative(
            formal=dict(retrieve_task.constraints or {}),
            speculative=dict(speculative_retrieval.get("constraints", {}) or {}),
        ):
            runtime = _runtime()
            settings = AgentSettings.from_env()
            match = _speculative_query_match(
                runtime=runtime,
                formal_query=retrieve_task.query,
                speculative_query=str(speculative_retrieval.get("query") or ""),
                settings=settings,
            )
            if bool(match.get("matched", False)) and hasattr(runtime, "await_speculative_result"):
                speculative_result = await runtime.await_speculative_result(speculative_run_id)
                _cleanup_speculative_run(runtime, speculative_run_id)
                if speculative_result is not None and speculative_result.status == "completed":
                    metadata = dict(speculative_result.metadata or {})
                    metadata.update(
                        {
                            "speculative_reused": True,
                            "speculative_run_id": speculative_run_id,
                            "speculative_query": str(speculative_retrieval.get("query") or ""),
                            "speculative_match": match,
                        }
                    )
                    reused = AgentResult(
                        task_id=retrieve_task.task_id,
                        agent_name=retrieve_task.agent_name,
                        status=speculative_result.status,
                        summary=speculative_result.summary,
                        artifacts=list(speculative_result.artifacts or []),
                        confidence=speculative_result.confidence,
                        metadata=metadata,
                    )
                    return reused, [_build_agent_result_message(turn_id=turn_id, result=reused)]
            _discard_speculative_run(runtime, speculative_run_id)
        return await _invoke_specialist_subgraph(
            graph=retrieve_agent_graph,
            task_key="retrieve_task",
            result_key="retrieve_result",
            task=retrieve_task,
            turn_id=turn_id,
            config=config,
        )

    retrieval_result, retrieval_messages = await run_retrieval()

    output_messages: list[BaseMessage] = list(retrieval_messages)
    if retrieval_result is not None:
        output_messages.extend(
            _fallback_agent_result_messages(
                turn_id=turn_id,
                result=retrieval_result,
                existing_messages=retrieval_messages,
            )
        )
    output_messages.append(
        _build_loop_status_message(
            turn_id=turn_id,
            phase="parallel_specialists_complete",
            summary="Specialist execution finished.",
            iteration_count=int(state.get("iteration_count", 0) or 0),
            metadata={
                "completed_agents": [
                    agent_name
                    for agent_name, result in [
                        ("retrieval_agent", retrieval_result),
                    ]
                    if result is not None
                ],
            },
        )
    )
    return {
        "messages": output_messages,
        "retrieve_result": retrieval_result.to_dict() if retrieval_result is not None else None,
        "tool_result": None,
        "speculative_retrieval": None,
    }


async def _invoke_specialist_subgraph(
    *,
    graph: Any,
    task_key: str,
    result_key: str,
    task: AgentTask,
    turn_id: str,
    config: RunnableConfig | None,
) -> tuple[AgentResult | None, list[BaseMessage]]:
    if graph is None:
        return None, []
    child_state = await graph.ainvoke(
        {
            "active_turn_id": turn_id,
            task_key: task,
        },
        config=config,
    )
    if not isinstance(child_state, dict):
        return None, []
    messages = [
        message
        for message in list(child_state.get("messages", []) or [])
        if getattr(message, "type", "") == "tool"
    ]
    result = _agent_result_from_payload(child_state.get(result_key))
    return result, messages


def _fallback_agent_result_messages(
    *,
    turn_id: str,
    result: AgentResult,
    existing_messages: list[BaseMessage],
) -> list[BaseMessage]:
    for message in existing_messages:
        metadata = _message_meta(message)
        payload = dict(metadata.get("result", {}) or {})
        if payload.get("task_id") == result.task_id and payload.get("agent_name") == result.agent_name:
            return []
    return [_build_agent_result_message(turn_id=turn_id, result=result)]


def _agent_result_from_payload(payload: Any) -> AgentResult | None:
    if isinstance(payload, AgentResult):
        return payload
    if not isinstance(payload, dict):
        return None
    return AgentResult(
        task_id=str(payload.get("task_id") or ""),
        agent_name=str(payload.get("agent_name") or ""),
        status=str(payload.get("status") or ""),
        summary=str(payload.get("summary") or ""),
        artifacts=list(payload.get("artifacts", []) or []),
        confidence=float(payload.get("confidence", 0.0) or 0.0),
        metadata=dict(payload.get("metadata", {}) or {}),
    )


def _latest_assessment_guidance(messages: list[BaseMessage], *, turn_id: str) -> list[str]:
    guidance: list[str] = []
    for message in _latest_messages_by_artifact(messages, "loop_status", turn_id=turn_id):
        metadata = _message_meta(message)
        if metadata.get("phase") != "assess_complete":
            continue
        for task in list(metadata.get("next_tasks", []) or []):
            text = str(task).strip()
            if text:
                guidance.append(text)
    return guidance


def _route_after_assess(state: PaperLabGraphState) -> str:
    if bool(state.get("answer_confident", False)):
        return "store_memory"
    if str(state.get("stop_reason") or ""):
        return "store_memory"
    iteration_count = int(state.get("iteration_count", 0) or 0)
    max_iterations = int(state.get("max_iterations", 1) or 1)
    if iteration_count >= max_iterations:
        return "store_memory"
    return "guidance_gate_pre_route"


def guidance_gate_pre_assess_node(
    state: PaperLabGraphState,
    config: RunnableConfig | None = None,
) -> Command[Literal["assess"]]:
    """Pause after specialists complete so the UI can inject guidance before assessment."""

    resume_value = _resume_value_from_guidance_queue(config=config)
    return Command(
        update=_materialize_intervention_update(
            state=state,
            config=config,
            phase="guidance_gate_pre_assess",
            resume_value=resume_value,
        ),
        goto="assess",
    )


async def assess_node(
    state: PaperLabGraphState,
    config: RunnableConfig | None = None,
) -> PaperLabGraphState:
    """Ask the model whether to answer now or continue the evidence loop."""
    turn_id = str(state.get("active_turn_id") or f"turn_{uuid4().hex[:8]}")
    messages = list(state.get("messages", []))
    question = _latest_human_text(messages)
    short_term_message = _latest_tool_message(messages, "build_short_term_context", turn_id=turn_id)
    memory_message = _latest_tool_message(messages, "search_memory", turn_id=turn_id)
    intervention_messages = _latest_messages_by_artifact(messages, "intervention", turn_id=turn_id)
    retrieve_result = dict(state.get("retrieve_result", {}) or {})

    iteration_count = int(state.get("iteration_count", 0) or 0)
    max_iterations = int(state.get("max_iterations", 1) or 1)
    must_answer = iteration_count >= max_iterations
    answer_or_continue_prompt = build_answer_or_continue_prompt(
        question=question,
        short_term_context=_message_text(short_term_message.content) if short_term_message is not None else "",
        memory_context=_message_text(memory_message.content) if memory_message is not None else "",
        interventions=[_message_text(message.content) for message in intervention_messages],
        specialist_payloads=[
            _stringify_for_prompt(retrieve_result) if retrieve_result else "",
        ],
        must_answer=must_answer,
    )
    memory_decision_prompt = _append_memory_write_policy(answer_or_continue_prompt)
    bound_model = _runtime().chat_model.bind_tools(_answer_or_loop_schema())
    raw_assessment = await bound_model.ainvoke(memory_decision_prompt)
    loop_decision = _parse_continue_loop_decision(raw_assessment)
    decision = parse_answer_or_continue_decision(
        _message_text(getattr(raw_assessment, "content", raw_assessment))
    )
    answer_confident = decision.answer_confident and not bool(loop_decision.get("should_loop", False))
    next_tasks = (
        []
        if answer_confident
        else list(loop_decision.get("next_tasks", []) or [])
    )
    if not answer_confident and not next_tasks:
        next_tasks = [f"Gather additional evidence that directly answers: {question}"]

    stop_reason = ""
    if must_answer and not answer_confident:
        stop_reason = "max_iterations_reached"
        return await synthesize_node(
            {
                **state,
                "answer_confident": True,
                "stop_reason": stop_reason,
                "retrieve_result": retrieve_result,
                "tool_result": None,
                "assessment_next_tasks": next_tasks,
                "assessment_loop_reason": str(loop_decision.get("reason") or ""),
            },
            config,
        )
    if answer_confident:
        return await synthesize_node(
            {
                **state,
                "answer_confident": True,
                "stop_reason": stop_reason,
                "retrieve_result": retrieve_result,
                "tool_result": None,
            },
            config,
        )
    if answer_confident:
        status_summary = "Assess found enough evidence for synthesis."
    elif stop_reason:
        status_summary = "Assess requested more evidence, but the loop reached its stop condition."
    else:
        status_summary = "Assess requested another routing iteration with new evidence tasks."
    return {
        "messages": [
            _build_loop_status_message(
                turn_id=turn_id,
                phase="assess_complete",
                summary=status_summary,
                iteration_count=iteration_count,
                metadata={
                    "answer_confident": answer_confident,
                    "stop_reason": stop_reason,
                    "next_tasks": next_tasks,
                    "loop_reason": str(loop_decision.get("reason") or ""),
                },
            )
        ],
        "answer_confident": answer_confident,
        "stop_reason": stop_reason,
    }


def _append_memory_write_policy(prompt: str) -> str:
    return (
        prompt
        + "\n\nMemory write policy:\n"
        + "- You must call `decide_memory_write` exactly once after producing the final answer.\n"
        + "- This memory is long-term and cross-session, not short-term scratch space.\n"
        + "- Default to `action=none`.\n"
        + "- Use `action=store` only for stable long-term user preferences, durable project facts, shared project constraints, or reusable research lessons.\n"
        + "- Stable name/preferred form of address, enduring collaboration preferences, and declared long-term research directions are valid long-term memory candidates.\n"
        + "- Do not store ordinary answers, temporary tasks, uncertain claims, private/sensitive data, or details that can simply be re-retrieved from papers later.\n"
        + "- If you say in the answer that you will remember, have remembered, or will use this preference later, the tool call must be `action=store` with the exact durable fact to persist.\n"
        + "- If not storing, do not claim that the information has been remembered across sessions.\n"
        + "- If unsure, call `decide_memory_write` with `action=none`."
    )


def _fallback_answer_from_specialist_results(
    *,
    retrieve_result: dict[str, Any],
    tool_result: dict[str, Any] | None = None,
) -> str:
    retrieve_metadata = dict(retrieve_result.get("metadata", {}) or {})
    evidence_pack = dict(retrieve_metadata.get("evidence_pack", {}) or {})
    documents = list(evidence_pack.get("documents", []) or [])
    if documents:
        lines = [f"当前项目库中共有 {len(documents)} 篇论文："]
        for index, document in enumerate(documents, start=1):
            if not isinstance(document, dict):
                continue
            title = str(document.get("title") or document.get("id") or "").strip()
            source_path = str(document.get("source_path") or "").strip()
            suffix = f" ({source_path})" if source_path else ""
            if title:
                lines.append(f"{index}. {title}{suffix}")
        if len(lines) > 1:
            return "\n".join(lines)

    retrieve_summary = str(
        retrieve_result.get("summary")
        or retrieve_metadata.get("retrieval_conclusion")
        or dict(retrieve_metadata.get("progress_summary", {}) or {}).get("done")
        or ""
    ).strip()
    if retrieve_summary:
        return retrieve_summary

    tool_result = tool_result or {}
    tool_metadata = dict(tool_result.get("metadata", {}) or {})
    tool_summary = str(
        tool_result.get("summary")
        or tool_metadata.get("summary")
        or dict(tool_metadata.get("progress_summary", {}) or {}).get("done")
        or ""
    ).strip()
    return tool_summary


def _build_assistant_answer_update(
    *,
    state: PaperLabGraphState,
    raw_answer: Any,
    answer_text: str,
    progress_summary: dict[str, str],
    retrieve_result: dict[str, Any],
    tool_result: dict[str, Any],
    turn_id: str,
    question: str,
    short_term_message: BaseMessage | None,
    memory_message: BaseMessage | None,
    intervention_messages: list[BaseMessage],
    answer_confident: bool,
    stop_reason: str,
) -> PaperLabGraphState:
    del question
    dependencies: list[str] = []
    if short_term_message is not None:
        dependencies.append(_message_id(short_term_message))
    if memory_message is not None:
        dependencies.append(_message_id(memory_message))
    messages = list(state.get("messages", []))
    result_messages = _latest_messages_by_artifact(messages, "agent_result", turn_id=turn_id)
    dependencies.extend(_message_id(message) for message in result_messages if _message_id(message))
    dependencies.extend(_message_id(message) for message in intervention_messages if _message_id(message))

    retrieve_metadata = dict(retrieve_result.get("metadata", {}) or {})
    tool_metadata = dict(tool_result.get("metadata", {}) or {})
    answer_additional_kwargs = dict(getattr(raw_answer, "additional_kwargs", {}) or {})
    answer_response_metadata = dict(getattr(raw_answer, "response_metadata", {}) or {})
    answer_reasoning = getattr(raw_answer, "reasoning_content", None) or answer_additional_kwargs.get("reasoning_content")
    if answer_reasoning:
        answer_additional_kwargs["reasoning_content"] = answer_reasoning
        answer_response_metadata["reasoning_content"] = answer_reasoning
    assistant_message = _build_assistant_message(
        turn_id=turn_id,
        content=answer_text,
        metadata={
            "artifact_type": "answer",
            "depends_on": dependencies,
            "citations": list(retrieve_metadata.get("citations", [])),
            "asset_citations": list(retrieve_metadata.get("asset_citations", [])),
            "asset_sources": list(retrieve_metadata.get("asset_sources", [])),
            "memory_hits": list(_message_meta(memory_message).get("memory_hits", []))
            if memory_message
            else [],
            "evidence_counts": dict(retrieve_metadata.get("evidence_counts", {})),
            "web_sources": list(tool_metadata.get("web_sources", [])),
            "tool_sources": list(tool_metadata.get("tool_sources", [])),
            "workspace_sources": [],
            "reusable": True,
            "orchestration": "weak_speculative_multi_agent",
            "answer_confident": answer_confident,
            "stop_reason": stop_reason,
            "intervention_count": int(state.get("intervention_count", 0) or 0),
            "summary": progress_summary,
            "memory_write_decision": _parse_memory_write_decision(raw_answer),
            "worker_progress": {
                "retrieval": dict(retrieve_metadata.get("progress_summary", {}) or {}),
                "tool": dict(tool_metadata.get("progress_summary", {}) or {}),
                "workspace": {},
            },
        },
        raw_id=getattr(raw_answer, "id", None),
        additional_kwargs=answer_additional_kwargs,
        response_metadata=answer_response_metadata,
    )
    return {
        "messages": [assistant_message],
        "answer_confident": answer_confident,
        "stop_reason": stop_reason,
    }


async def synthesize_node(
    state: PaperLabGraphState,
    config: RunnableConfig | None = None,
) -> PaperLabGraphState:
    """Synthesize specialist results into the final assistant answer."""

    request_config = resolve_agent_request_config(dict(config or {}))
    turn_id = str(state.get("active_turn_id") or f"turn_{uuid4().hex[:8]}")
    messages = list(state.get("messages", []))
    question = _latest_human_text(messages)
    short_term_message = _latest_tool_message(messages, "build_short_term_context", turn_id=turn_id)
    memory_message = _latest_tool_message(messages, "search_memory", turn_id=turn_id)
    intervention_messages = _latest_messages_by_artifact(messages, "intervention", turn_id=turn_id)

    dependencies: list[str] = []
    if short_term_message is not None:
        dependencies.append(_message_id(short_term_message))
    if memory_message is not None:
        dependencies.append(_message_id(memory_message))
    result_messages = _latest_messages_by_artifact(messages, "agent_result", turn_id=turn_id)
    dependencies.extend(_message_id(message) for message in result_messages if _message_id(message))
    dependencies.extend(_message_id(message) for message in intervention_messages if _message_id(message))

    retrieve_result = dict(state.get("retrieve_result", {}) or {})
    if not retrieve_result:
        for message in result_messages:
            result_payload = dict(_message_meta(message).get("result", {}) or {})
            if result_payload.get("agent_name") == "retrieval_agent":
                retrieve_result = result_payload
                break

    assessment_guidance_list = []
    loop_reason = str(state.get("assessment_loop_reason") or "").strip()
    if loop_reason:
        assessment_guidance_list.append(f"证据不完整的原因: {loop_reason}")
    for item in list(state.get("assessment_next_tasks", []) or []):
        item_str = str(item).strip()
        if item_str:
            assessment_guidance_list.append(item_str)

    synthesis_prompt = build_synthesis_prompt(
        question=question,
        short_term_context=_message_text(short_term_message.content) if short_term_message is not None else "",
        memory_context=_message_text(memory_message.content) if memory_message is not None else "",
        interventions=[_message_text(message.content) for message in intervention_messages],
        specialist_payloads=[_stringify_for_prompt(retrieve_result) if retrieve_result else ""],
        assessment_guidance=assessment_guidance_list,
    )
    memory_decision_prompt = synthesis_prompt + (
        "\n\n【重要】你的消息内容中必须包含面向用户的文本回答。"
        "不要只返回工具调用而不包含文本内容。"
        "文本内容应基于所有可用证据和工具结果，向用户汇报结果。\n\n"
        "记忆写入策略：\n"
        "- 生成最终回答后，必须调用一次 decide_memory_write。\n"
        "- 记忆是长期的、跨会话的，不是短期临时空间。\n"
        "- 默认 action=none。\n"
        "- 仅在以下情况使用 action=store：稳定的用户偏好、持久化的项目事实、共享的项目约束、可复用的研究经验。\n"
        "- 不要存储普通回答、临时任务、不确定的声明、隐私数据、重复记忆。\n"
        "- 如果不存储，不要声称信息已被跨会话记住。\n"
        "- 不确定时，调用 decide_memory_write 并设 action=none。"
    )
    if str(state.get("stop_reason") or "") == "max_iterations_reached":
        memory_decision_prompt += (
            "\n\n证据循环已达到停止条件。"
            "请基于当前工具和证据给出最佳回答，不要推迟回答。"
            "如果重要信息仍缺失，明确说明不确定的部分，并在回答和摘要中推荐最有价值的后续调查方向。"
        )
    tool_observations: list[dict[str, object]] = []
    tool_trace_messages: list[BaseMessage] = []
    workspace_tool_schemas = _main_workspace_tool_schema(request_config)
    external_tool_schemas: list[dict[str, object]] = []
    raw_answer: Any | None = None
    current_prompt = memory_decision_prompt
    tool_search_exhausted = False
    tool_status_lines = [
        f"- 网络搜索: {'ON' if request_config.allow_web_search else 'OFF'}",
        f"- MCP 外部工具: {'ON' if request_config.allow_mcp else 'OFF'}",
        f"- 文件读取: {'ON' if request_config.allow_file_read else 'OFF'}",
        f"- 文件写入: {'ON' if request_config.allow_file_write else 'OFF'}",
    ]
    current_prompt += "\n\n当前工具权限：\n" + "\n".join(tool_status_lines)
    if workspace_tool_schemas or external_tool_schemas or request_config.allow_web_search or request_config.allow_mcp:
        current_prompt += (
            "\n\n你有一组可用工具。任务匹配时直接使用。"
            "如果当前工具都不适合，调用 `tool_search` 发现更多工具。"
            "不要猜测工具名称或编造工具能力——只使用实际暴露给你的工具。"
            "如果搜索后仍没有合适工具，如实告知用户你无法做什么，以及需要什么工具或能力。"
            "\n\n【重要】你有两种模式：工具调用模式和回答模式。"
            "当前是工具调用模式——继续调用工具，不要生成最终回答。"
            "只有当用户要求的所有操作都完成后，才切换到回答模式。"
            "例如：用户要求'查看文件并写入记录'，你必须先调用读取工具，再调用写入工具，两者都完成后才生成回答。"
            "如果你只完成了读取但没有写入，说明任务未完成，继续调用写入工具。"
        )
    has_actionable_tools = bool(workspace_tool_schemas or external_tool_schemas or request_config.allow_web_search or request_config.allow_mcp)
    for _ in range(10):
        bound_tools = [*_memory_write_schema(), *workspace_tool_schemas, *external_tool_schemas]
        if not tool_search_exhausted and (request_config.allow_web_search or request_config.allow_mcp):
            bound_tools.append(_tool_search_virtual_schema())
        if len(bound_tools) <= 1:
            break
        tool_answer = await _runtime().chat_model.bind_tools(bound_tools).ainvoke(current_prompt)
        log_llm_call(
            turn_id=turn_id,
            stage="assess_tool_loop",
            prompt_preview=current_prompt[:500],
            response_preview=str(getattr(tool_answer, "content", ""))[:500],
            tool_count=len(bound_tools),
        )
        actionable_calls = [
            call
            for call in _extract_tool_calls(tool_answer)
            if str(call.get("name") or "") != "decide_memory_write"
        ]
        if not actionable_calls:
            raw_answer = tool_answer
            break
        new_observations: list[dict[str, object]] = []
        known_external_names = {
            str(schema.get("function", {}).get("name") or "")
            for schema in external_tool_schemas
        }
        for call in actionable_calls[:4]:
            tool_name = str(call.get("name") or "")
            call_args = _coerce_tool_call_args(call)
            log_tool_call(turn_id=turn_id, tool_name=tool_name, args=call_args, source="assess_loop")
            if tool_name == "tool_search":
                call_args = _coerce_tool_call_args(call)
                search_task = AgentTask(
                    task_id=f"task_tool_inline_{uuid4().hex[:8]}",
                    task_type="tool_research",
                    agent_name="tool_agent",
                    query=str(call_args.get("query") or question),
                    reason=str(call_args.get("reason") or "Need additional external tool options."),
                    constraints={"max_tools": 4},
                    metadata={
                        "allow_web_search": request_config.allow_web_search,
                        "allow_mcp": request_config.allow_mcp,
                        "already_exposed_tools": sorted(known_external_names),
                    },
                )
                search_result = await run_tool_specialist(task=search_task)
                result_metadata = dict(search_result.metadata or {})
                termination_reason = str(result_metadata.get("termination_reason") or "")
                new_schemas = _external_tool_schemas_from_result(
                    {"metadata": result_metadata},
                    request_config=request_config,
                )
                existing_names = {
                    str(schema.get("function", {}).get("name") or "")
                    for schema in external_tool_schemas
                }
                for schema in new_schemas:
                    name = str(schema.get("function", {}).get("name") or "")
                    if name and name not in existing_names:
                        external_tool_schemas.append(schema)
                        existing_names.add(name)
                if termination_reason == "no_match" or search_result.status == "skipped":
                    tool_search_exhausted = True
                    observation = {
                        "tool_name": "tool_search",
                        "args": call_args,
                        "status": "no_match",
                        "summary": "No matching tools found.",
                        "content": (
                            "No matching tools were found for this query. "
                            "Do not call tool_search again. "
                            "Answer with the tools already available, or tell the user honestly "
                            "that the requested capability is not available."
                        ),
                    }
                else:
                    recommended = list(result_metadata.get("recommended_tools", []) or [])
                    readable_lines = []
                    for tool in recommended:
                        name = str(tool.get("name") or "")
                        desc = str(tool.get("description") or "")
                        why = str(tool.get("why_selected") or "")
                        readable_lines.append(f"- **{name}**: {desc}")
                        if why:
                            readable_lines.append(f"  选择理由: {why}")
                    observation = {
                        "tool_name": "tool_search",
                        "args": call_args,
                        "status": search_result.status,
                        "summary": search_result.summary,
                        "content": "\n".join(readable_lines) if readable_lines else "No tools found.",
                        "recommended_tools": recommended,
                    }
            elif tool_name in {
                "get_current_time",
                "detect_platform",
                "list_files",
                "find_files",
                "search_text",
                "read_file",
                "write_file",
                "delete_file",
                "run_command",
            }:
                try:
                    observation = _execute_main_workspace_tool(call, request_config=request_config)
                except Exception as exc:
                    if interrupt is not None and "Interrupt" in type(exc).__name__:
                        raise
                    observation = {
                        "tool_name": tool_name,
                        "args": call_args,
                        "status": "error",
                        "summary": f"工具调用失败: {exc}",
                        "content": f"错误信息: {exc}",
                    }
            elif tool_name in known_external_names:
                try:
                    observation = await _execute_selected_external_tool(call, request_config=request_config)
                except Exception as exc:
                    if interrupt is not None and "Interrupt" in type(exc).__name__:
                        raise
                    observation = {
                        "tool_name": tool_name,
                        "args": call_args,
                        "status": "error",
                        "summary": f"工具调用失败: {exc}",
                        "content": f"错误信息: {exc}",
                    }
            else:
                continue
            new_observations.append(observation)
            log_tool_result(
                turn_id=turn_id,
                tool_name=tool_name,
                status=str(observation.get("status") or ""),
                summary=str(observation.get("summary") or ""),
                content_preview=str(observation.get("content") or "")[:300],
            )
            trace_text = str(observation.get("summary") or "")
            trace_content = str(observation.get("content") or "")
            if trace_content:
                trace_text = f"{trace_text}\n\n{trace_content}" if trace_text else trace_content
            is_workspace = tool_name in {
                "get_current_time",
                "detect_platform",
                "list_files",
                "find_files",
                "search_text",
                "read_file",
                "write_file",
                "delete_file",
                "run_command",
            }
            trace_metadata: dict[str, Any] = {
                "artifact_type": "workspace_tool_result" if is_workspace else "external_tool_result",
                "tool_name": str(observation.get("tool_name") or tool_name),
                "args": dict(observation.get("args", {}) or {}),
                "status": str(observation.get("status") or ""),
                "reusable": False,
            }
            if tool_name == "tool_search":
                trace_metadata["recommended_tools"] = list(observation.get("recommended_tools", []) or [])
            tool_trace_messages.append(
                _build_tool_message(
                    turn_id=turn_id,
                    name="workspace_tool" if is_workspace else "external_tool",
                    content=trace_text,
                    metadata=trace_metadata,
                    tool_call_id=str(call.get("id") or ""),
                )
            )
        if not new_observations:
            raw_answer = tool_answer
            break
        tool_observations.extend(new_observations)
        current_prompt = (
            memory_decision_prompt
            + "\n\nTool observations:\n"
            + _stringify_for_prompt(tool_observations)
        )

    if raw_answer is None:
        if has_actionable_tools:
            bound_model = _runtime().chat_model.bind_tools(_memory_write_schema())
            raw_answer = await bound_model.ainvoke(current_prompt)
        else:
            raw_answer = await _runtime().chat_model.ainvoke(current_prompt)
    memory_write_decision = _parse_memory_write_decision(raw_answer)
    answer_text, progress_summary = parse_structured_assistant_output(
        _message_text(getattr(raw_answer, "content", raw_answer))
    )
    if not answer_text.strip():
        answer_text = _fallback_answer_from_specialist_results(
            retrieve_result=retrieve_result,
        )
    if not answer_text.strip() and tool_observations:
        summary_prompt = (
            "以下工具操作已执行完毕。"
            "请用中文向用户清晰、简洁地汇报结果。\n\n"
            + _stringify_for_prompt(tool_observations)
        )
        summary_response = await _runtime().chat_model.ainvoke(summary_prompt)
        answer_text = _message_text(getattr(summary_response, "content", summary_response))

    log_synthesis(
        turn_id=turn_id,
        question=question,
        answer_text=answer_text,
        tool_observations_count=len(tool_observations),
        has_retrieval=bool(retrieve_result),
    )

    retrieve_metadata = dict(retrieve_result.get("metadata", {}) or {})
    tool_metadata: dict[str, Any] = {}
    workspace_sources: list[dict[str, object]] = []
    changed_files: list[str] = []
    executed_external_sources: list[dict[str, object]] = []
    for observation in tool_observations:
        for path in list(observation.get("changed_files", []) or []):
            changed_files.append(str(path))
        tool_name = str(observation.get("tool_name") or "")
        if tool_name in {"web_search", "url_fetch"}:
            for source in list(observation.get("web_sources", []) or []):
                if isinstance(source, dict):
                    executed_external_sources.append(
                        {
                            "kind": "web",
                            "title": str(source.get("title") or source.get("url") or tool_name),
                            "url": str(source.get("url") or ""),
                            "summary": str(source.get("snippet") or source.get("excerpt") or ""),
                            "tool_name": tool_name,
                        }
                    )
        elif tool_name not in {"get_current_time", "detect_platform", "list_files", "find_files", "search_text", "read_file", "write_file", "delete_file", "run_command", "tool_search"}:
            for source in list(observation.get("tool_sources", []) or []):
                if isinstance(source, dict):
                    executed_external_sources.append(dict(source))
    if tool_observations:
        workspace_sources.extend(
            {
                "kind": "tool_call",
                "path": str(observation.get("tool_name") or ""),
                "summary": str(observation.get("summary") or ""),
            }
            for observation in tool_observations
        )
    answer_additional_kwargs = dict(getattr(raw_answer, "additional_kwargs", {}) or {})
    answer_response_metadata = dict(getattr(raw_answer, "response_metadata", {}) or {})
    answer_reasoning = getattr(raw_answer, "reasoning_content", None) or answer_additional_kwargs.get("reasoning_content")
    if answer_reasoning:
        answer_additional_kwargs["reasoning_content"] = answer_reasoning
        answer_response_metadata["reasoning_content"] = answer_reasoning
    assistant_message = _build_assistant_message(
        turn_id=turn_id,
        content=answer_text,
        metadata={
            "artifact_type": "answer",
            "depends_on": dependencies,
            "citations": list(retrieve_metadata.get("citations", [])),
            "asset_citations": list(retrieve_metadata.get("asset_citations", [])),
            "asset_sources": list(retrieve_metadata.get("asset_sources", [])),
            "memory_hits": list(_message_meta(memory_message).get("memory_hits", []))
            if memory_message
            else [],
            "evidence_counts": dict(retrieve_metadata.get("evidence_counts", {})),
            "web_sources": list(tool_metadata.get("web_sources", [])),
            "tool_sources": [*list(tool_metadata.get("tool_sources", [])), *executed_external_sources],
            "workspace_sources": workspace_sources,
            "workspace_tool_calls": tool_observations,
            "changed_files": changed_files,
            "reusable": True,
            "orchestration": "weak_speculative_multi_agent",
            "answer_confident": bool(state.get("answer_confident", False)),
            "stop_reason": str(state.get("stop_reason") or ""),
            "intervention_count": int(state.get("intervention_count", 0) or 0),
            "summary": progress_summary,
            "memory_write_decision": memory_write_decision,
            "worker_progress": {
                "retrieval": dict(retrieve_metadata.get("progress_summary", {}) or {}),
                "tool": dict(tool_metadata.get("progress_summary", {}) or {}),
                "workspace": {},
            },
        },
        raw_id=getattr(raw_answer, "id", None),
        additional_kwargs=answer_additional_kwargs,
        response_metadata=answer_response_metadata,
    )
    return {
        "messages": [*tool_trace_messages, assistant_message],
        "answer_confident": bool(state.get("answer_confident", False)),
        "stop_reason": str(state.get("stop_reason") or ""),
    }


async def recall_memory_node(
    state: PaperLabGraphState,
    config: RunnableConfig | None = None,
) -> PaperLabGraphState:
    """Recall project-scoped memory and append it as a tool artifact message."""

    request_config = resolve_agent_request_config(dict(config or {}))
    if not bool(state.get("run_memory", False)):
        return {}
    turn_id = str(state.get("active_turn_id") or f"turn_{uuid4().hex[:8]}")
    runtime = _runtime()
    settings = AgentSettings.from_env()
    question = str(state.get("memory_query") or _latest_human_text(state.get("messages", [])))
    speculative_memory = dict(state.get("speculative_memory", {}) or {})
    speculative_run_id = str(speculative_memory.get("run_id") or "")
    if speculative_run_id:
        match = _speculative_query_match(
            runtime=runtime,
            formal_query=question,
            speculative_query=str(speculative_memory.get("query") or ""),
            settings=settings,
        )
        if bool(match.get("matched", False)) and hasattr(runtime, "await_speculative_result"):
            speculative_result = await runtime.await_speculative_result(speculative_run_id)
            _cleanup_speculative_run(runtime, speculative_run_id)
            if speculative_result is not None and speculative_result.status == "completed":
                result_metadata = dict(speculative_result.metadata or {})
                message = _build_tool_message(
                    turn_id=turn_id,
                    name="search_memory",
                    content=speculative_result.summary or "Relevant memory:\n- none",
                    metadata={
                        "artifact_type": "memory_result",
                        "query": question,
                        "memory_hits": list(result_metadata.get("memory_hits", []) or []),
                        "summary": result_metadata.get("summary", speculative_result.summary),
                        "reusable": True,
                        "speculative_reused": True,
                        "speculative_run_id": speculative_run_id,
                        "speculative_query": str(speculative_memory.get("query") or ""),
                        "speculative_match": match,
                    },
                )
                return {"messages": [message], "speculative_memory": None}
        _discard_speculative_run(runtime, speculative_run_id)

    memory_service = build_memory_service(
        backend=_memory_backend(),
        settings=settings,
    )
    recall_result = await asyncio.to_thread(
        memory_service.recall,
        role="supervisor",
        query=question,
        project_id=request_config.project_id,
        limit=request_config.memory_limit,
    )

    message = _build_tool_message(
        turn_id=turn_id,
        name="search_memory",
        content=recall_result.summary or "Relevant memory:\n- none",
        metadata={
            "artifact_type": "memory_result",
            "query": question,
            "memory_hits": [_serialize_memory_item(item) for item in recall_result.hits],
            "summary": recall_result.summary,
            "reusable": True,
            "speculative_reused": False,
        },
    )
    return {"messages": [message], "speculative_memory": None}


def _memory_write_trace_message(
    *,
    turn_id: str,
    decision: dict[str, object],
    stored: bool,
) -> BaseMessage:
    action = str(decision.get("action") or "none")
    reason = str(decision.get("reason") or "").strip()
    content = str(decision.get("content") or "").strip()
    memory_type = str(decision.get("memory_type") or "").strip()
    if action != "store":
        body = "长期记忆写入决策：none"
        if reason:
            body += f"\nReason: {reason}"
        return _build_tool_message(
            turn_id=turn_id,
            name="store_memory",
            content=body,
            metadata={
                "artifact_type": "memory_write_result",
                "action": "none",
                "stored": False,
                "reason": reason,
                "reusable": False,
            },
        )

    body = "长期记忆写入决策：store"
    if memory_type:
        body += f"\nType: {memory_type}"
    if reason:
        body += f"\nReason: {reason}"
    if content:
        body += f"\nContent: {content}"
    body += f"\nStatus: {'stored' if stored else 'skipped'}"
    return _build_tool_message(
        turn_id=turn_id,
        name="store_memory",
        content=body,
        metadata={
            "artifact_type": "memory_write_result",
            "action": "store",
            "stored": stored,
            "memory_type": memory_type,
            "reason": reason,
            "content": content,
            "reusable": False,
        },
    )


async def store_memory_node(
    state: PaperLabGraphState,
    config: RunnableConfig | None = None,
) -> PaperLabGraphState:
    """Persist one completed question-answer turn into long-term memory."""

    request_config = resolve_agent_request_config(dict(config or {}))
    messages = state.get("messages", [])
    if len(messages) < 2:
        return {}

    user_text = _latest_human_text(messages)
    assistant_message = next(
        (message for message in reversed(messages) if getattr(message, "type", "") == "ai"),
        None,
    )
    if assistant_message is None:
        return {}

    assistant_meta = _message_meta(assistant_message)
    memory_decision = dict(assistant_meta.get("memory_write_decision", {}) or {})
    turn_id = str(state.get("active_turn_id") or f"turn_{uuid4().hex[:8]}")
    if not bool(memory_decision.get("should_write", False)):
        return {"messages": [_memory_write_trace_message(turn_id=turn_id, decision=memory_decision, stored=False)]}
    memory_content = str(memory_decision.get("content") or "").strip()
    if not memory_content:
        return {"messages": [_memory_write_trace_message(turn_id=turn_id, decision=memory_decision, stored=False)]}

    memory_service = build_memory_service(
        backend=_memory_backend(),
        settings=AgentSettings.from_env(),
    )
    stored = memory_service.store_memory(
        role="supervisor",
        project_id=request_config.project_id,
        thread_id=request_config.thread_id,
        content=memory_content,
        metadata={
            "reason": str(memory_decision.get("reason") or ""),
            "source_question": user_text,
            "citations": list(assistant_meta.get("citations", [])),
            "evidence_counts": dict(assistant_meta.get("evidence_counts", {})),
            "depends_on": list(assistant_meta.get("depends_on", [])),
        },
        memory_type=_coerce_memory_type(memory_decision.get("memory_type")),
    )
    return {"messages": [_memory_write_trace_message(turn_id=turn_id, decision=memory_decision, stored=stored)]}


def build_graph():
    """Create the compiled PaperLab LangGraph if LangGraph is installed."""

    if StateGraph is None or add_messages is None:
        return None

    class GraphState(TypedDict, total=False):
        messages: Annotated[list[BaseMessage], add_messages]
        active_turn_id: str
        thread_lock_key: str
        iteration_count: int
        max_iterations: int
        answer_confident: bool
        stop_reason: str
        run_memory: bool
        memory_query: str
        memory_reason: str
        retrieve_task: AgentTask | None
        tool_task: AgentTask | None
        speculative_memory: dict[str, Any] | None
        speculative_retrieval: dict[str, Any] | None
        retrieve_result: dict[str, Any] | None
        tool_result: dict[str, Any] | None
        processed_human_message_count: int
        intervention_count: int

    builder = StateGraph(GraphState)
    builder.add_node("prepare_turn", prepare_turn_node)
    builder.add_node("build_short_term_context", build_short_term_context_node)
    builder.add_node("recall_memory", recall_memory_node)
    builder.add_node("thread_lock", thread_lock_node)
    builder.add_node("guidance_gate_pre_route", guidance_gate_pre_route_node)
    builder.add_node("main_route", main_route_node)
    builder.add_node("guidance_gate_post_route", guidance_gate_post_route_node)
    builder.add_node("parallel_specialists", parallel_specialists_node)
    builder.add_node("guidance_gate_pre_assess", guidance_gate_pre_assess_node)
    builder.add_node("assess", assess_node)
    builder.add_node("store_memory", store_memory_node)
    builder.add_node("release_thread_lock", release_thread_lock_node)

    builder.add_edge(START, "prepare_turn")
    builder.add_edge("prepare_turn", "thread_lock")
    builder.add_edge("thread_lock", "build_short_term_context")
    builder.add_edge("build_short_term_context", "guidance_gate_pre_route")
    builder.add_edge("guidance_gate_pre_route", "main_route")
    builder.add_edge("main_route", "recall_memory")
    builder.add_edge("recall_memory", "guidance_gate_post_route")
    builder.add_edge("guidance_gate_post_route", "parallel_specialists")
    builder.add_edge("parallel_specialists", "guidance_gate_pre_assess")
    builder.add_edge("guidance_gate_pre_assess", "assess")
    builder.add_conditional_edges(
        "assess",
        _route_after_assess,
        {
            "guidance_gate_pre_route": "guidance_gate_pre_route",
            "store_memory": "store_memory",
        },
    )
    builder.add_edge("store_memory", "release_thread_lock")
    builder.add_edge("release_thread_lock", END)
    return builder.compile(checkpointer=_build_checkpointer())


retrieve_agent_graph = build_retrieve_agent_graph(
    resolve_request_config=resolve_agent_request_config
)
tool_agent_graph = build_tool_agent_graph()
graph = build_graph()
