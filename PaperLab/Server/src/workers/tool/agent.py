"""Tool specialist subgraph for PaperLab."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

from prompts.builders import build_tool_agent_selection_messages
from contracts import AgentArtifact
from contracts import AgentResult
from contracts import AgentTask
from orchestration.graph_messages import _build_agent_result_message
from orchestration.graph_messages import _coerce_tool_call_args
from orchestration.graph_messages import _extract_tool_calls
from orchestration.graph_state import ToolAgentGraphState
from orchestration.request_config import _coerce_positive_int
from orchestration.runtime_access import _runtime
from runtime import CancellationToken

try:
    from langchain_core.messages import HumanMessage
    from langchain_core.messages import SystemMessage
    from langchain_core.runnables import RunnableConfig
    from langgraph.graph import END
    from langgraph.graph import START
    from langgraph.graph import StateGraph
except ImportError:  # pragma: no cover
    HumanMessage = Any  # type: ignore[assignment]
    SystemMessage = Any  # type: ignore[assignment]
    RunnableConfig = dict[str, Any]  # type: ignore[assignment]
    END = "__end__"
    START = "__start__"
    StateGraph = None  # type: ignore[assignment]


def _graph_settings():
    from orchestration import supervisor as graph_module

    return graph_module.AgentSettings.from_env()


def _graph_runtime():
    return _runtime()


def _tool_agent_choice_schema(mcp_tools: list[dict[str, Any]]) -> list[dict[str, object]]:
    schemas: list[dict[str, object]] = [
        {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "Search the public web for external information.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "top_k": {"type": "integer"},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "url_fetch",
                "description": "Fetch the body text for one explicit URL.",
                "parameters": {
                    "type": "object",
                    "properties": {"url": {"type": "string"}},
                    "required": ["url"],
                },
            },
        },
    ]
    for tool in mcp_tools:
        schemas.append(
            {
                "type": "function",
                "function": {
                    "name": str(tool.get("name") or ""),
                    "description": str(tool.get("description") or "Call one MCP tool."),
                    "parameters": dict(
                        tool.get("input_schema", {}) or {"type": "object", "properties": {}}
                    ),
                },
            }
        )
    return schemas


def _serialize_tool_source(
    *,
    kind: str,
    title: str,
    url: str = "",
    summary: str = "",
    tool_name: str = "",
) -> dict[str, object]:
    return {
        "kind": kind,
        "title": title,
        "url": url,
        "summary": summary,
        "tool_name": tool_name,
    }


def _serialize_web_chunk(chunk: Any) -> dict[str, object]:
    metadata = dict(getattr(chunk, "metadata", {}) or {})
    return {
        "id": getattr(chunk, "id", ""),
        "url": metadata.get("url", getattr(chunk, "document_id", "")),
        "title": metadata.get("title", ""),
        "snippet": metadata.get("snippet", ""),
        "excerpt": metadata.get("excerpt", ""),
        "content": getattr(chunk, "text", ""),
    }


async def run_tool_specialist(
    *,
    task: AgentTask,
    cancel_token: CancellationToken | None = None,
) -> AgentResult:
    """Execute one tool specialist task."""

    def _cancelled_result(message: str) -> AgentResult:
        return AgentResult(
            task_id=task.task_id,
            agent_name=task.agent_name,
            status="cancelled",
            summary=message,
            artifacts=[],
            confidence=0.0,
            metadata={"web_sources": [], "tool_sources": [], "cancelled": True},
        )

    if cancel_token is not None and cancel_token.is_cancelled():
        return _cancelled_result("ToolAgent speculative run cancelled before execution.")

    cache_store = _graph_runtime().cache_store
    if cache_store is not None:
        cached = cache_store.load_cached_web_search(task.query)
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

    web_provider = _graph_runtime().web_search_provider
    mcp_provider = _graph_runtime().mcp_tool_provider
    mcp_tools = await mcp_provider.list_tools() if mcp_provider is not None else []

    selected_name = "web_search"
    selected_args: dict[str, Any] = {
        "query": task.query,
        "top_k": _coerce_positive_int(
            task.constraints.get("top_k"), _graph_settings().web_search_result_limit
        ),
    }
    if mcp_tools:
        if len(mcp_tools) == 1 and web_provider is None:
            selected_name = str(mcp_tools[0].get("name") or "")
            selected_args = {}
        else:
            selection_model = _graph_runtime().chat_model.bind_tools(_tool_agent_choice_schema(mcp_tools))
            system_prompt, user_prompt = build_tool_agent_selection_messages(
                task_query=task.query,
                reason=task.reason,
            )
            selection_response = await selection_model.ainvoke(
                [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=user_prompt),
                ]
            )
            selection_calls = _extract_tool_calls(selection_response)
            if selection_calls:
                selected_name = str(selection_calls[0].get("name") or selected_name)
                selected_args = _coerce_tool_call_args(selection_calls[0])

    if selected_name in {"web_search", "url_fetch"}:
        result = await _run_web_flow(
            task=task,
            selected_name=selected_name,
            selected_args=selected_args,
            web_provider=web_provider,
            cancel_token=cancel_token,
        )
    elif mcp_provider is not None:
        if cancel_token is not None and cancel_token.is_cancelled():
            return _cancelled_result("ToolAgent speculative run cancelled before MCP call.")
        call_result = await mcp_provider.call_tool(selected_name, selected_args)
        text = str(call_result.get("text") or "")
        result = AgentResult(
            task_id=task.task_id,
            agent_name=task.agent_name,
            status="failed" if bool(call_result.get("is_error")) else "completed",
            summary=f"ToolAgent called MCP tool '{selected_name}'.",
            artifacts=[
                AgentArtifact(
                    artifact_id=f"artifact_mcp_{uuid4().hex[:8]}",
                    artifact_type="mcp_tool_result",
                    content=text,
                    metadata={
                        "tool_name": selected_name,
                        "structured_content": call_result.get("structured_content"),
                        "content": call_result.get("content", []),
                    },
                ).to_dict()
            ],
            confidence=0.6 if not bool(call_result.get("is_error")) else 0.1,
            metadata={
                "web_sources": [],
                "tool_sources": [
                    _serialize_tool_source(
                        kind="mcp",
                        title=selected_name,
                        summary=text[:800],
                        tool_name=selected_name,
                    )
                ],
                "mcp_tool_name": selected_name,
                "structured_content": call_result.get("structured_content"),
            },
        )
    else:
        result = AgentResult(
            task_id=task.task_id,
            agent_name=task.agent_name,
            status="skipped",
            summary="ToolAgent had no available tool provider.",
            artifacts=[],
            confidence=0.0,
            metadata={"web_sources": [], "tool_sources": []},
        )

    if cache_store is not None and selected_name in {"web_search", "url_fetch"}:
        cache_store.save_cached_web_search(
            task.query,
            result.to_dict(),
            ttl_seconds=_graph_settings().redis_web_cache_ttl,
        )
    return result


async def _run_web_flow(
    *,
    task: AgentTask,
    selected_name: str,
    selected_args: dict[str, Any],
    web_provider: Any,
    cancel_token: CancellationToken | None,
) -> AgentResult:
    if cancel_token is not None and cancel_token.is_cancelled():
        return AgentResult(
            task_id=task.task_id,
            agent_name=task.agent_name,
            status="cancelled",
            summary="ToolAgent speculative run cancelled before web execution.",
            artifacts=[],
            confidence=0.0,
            metadata={"web_sources": [], "tool_sources": [], "cancelled": True},
        )

    if web_provider is None:
        return AgentResult(
            task_id=task.task_id,
            agent_name=task.agent_name,
            status="skipped",
            summary="ToolAgent could not run because no external tool provider is available.",
            artifacts=[],
            confidence=0.0,
            metadata={"web_sources": [], "tool_sources": []},
        )

    if selected_name == "url_fetch":
        url = str(selected_args.get("url") or "")
        if not url:
            return AgentResult(
                task_id=task.task_id,
                agent_name=task.agent_name,
                status="skipped",
                summary="ToolAgent could not fetch a URL because no URL was provided.",
                artifacts=[],
                confidence=0.0,
                metadata={"web_sources": [], "tool_sources": []},
            )
        fetched = await asyncio.to_thread(web_provider.fetch, url)
        page = _serialize_web_chunk(fetched)
        return AgentResult(
            task_id=task.task_id,
            agent_name=task.agent_name,
            status="completed",
            summary="ToolAgent fetched one web page.",
            artifacts=[
                AgentArtifact(
                    artifact_id=f"artifact_web_page_{uuid4().hex[:8]}",
                    artifact_type="web_page_result",
                    content=str(getattr(fetched, "text", "") or ""),
                    metadata={"page": page},
                ).to_dict()
            ],
            confidence=0.55,
            metadata={
                "web_sources": [page],
                "tool_sources": [
                    _serialize_tool_source(
                        kind="web",
                        title=str(page.get("title") or page.get("url") or "Fetched page"),
                        url=str(page.get("url") or ""),
                        summary=str(page.get("excerpt") or ""),
                        tool_name="url_fetch",
                    )
                ],
            },
        )

    results = await asyncio.to_thread(
        web_provider.search,
        str(selected_args.get("query") or task.query),
        _coerce_positive_int(selected_args.get("top_k"), _graph_settings().web_search_result_limit),
    )
    if cancel_token is not None and cancel_token.is_cancelled():
        return AgentResult(
            task_id=task.task_id,
            agent_name=task.agent_name,
            status="cancelled",
            summary="ToolAgent speculative run cancelled after web search.",
            artifacts=[],
            confidence=0.0,
            metadata={"web_sources": [], "tool_sources": [], "cancelled": True},
        )

    web_sources = [_serialize_web_chunk(result) for result in results]
    artifacts: list[dict[str, Any]] = [
        AgentArtifact(
            artifact_id=f"artifact_web_search_{uuid4().hex[:8]}",
            artifact_type="web_search_result",
            content=f"Found {len(results)} web results for: {task.query}",
            metadata={"web_sources": web_sources},
        ).to_dict()
    ]
    if results and bool(task.constraints.get("fetch_top_url", True)):
        top_url = str(web_sources[0].get("url", "") or "")
        if top_url:
            fetched = await asyncio.to_thread(web_provider.fetch, top_url)
            artifacts.append(
                AgentArtifact(
                    artifact_id=f"artifact_web_page_{uuid4().hex[:8]}",
                    artifact_type="web_page_result",
                    content=str(getattr(fetched, "text", "") or ""),
                    metadata={"page": _serialize_web_chunk(fetched)},
                ).to_dict()
            )
            web_sources = [dict(_serialize_web_chunk(fetched))]

    return AgentResult(
        task_id=task.task_id,
        agent_name=task.agent_name,
        status="completed",
        summary=(
            "ToolAgent found external web evidence."
            if web_sources
            else "ToolAgent web search returned weak evidence."
        ),
        artifacts=artifacts,
        confidence=0.65 if web_sources else 0.15,
        metadata={
            "web_sources": web_sources,
            "tool_sources": [
                _serialize_tool_source(
                    kind="web",
                    title=str(item.get("title") or item.get("url") or "Web source"),
                    url=str(item.get("url") or ""),
                    summary=str(item.get("snippet") or item.get("excerpt") or ""),
                    tool_name="web_search",
                )
                for item in web_sources
            ],
        },
    )


async def tool_agent_execute_node(state: ToolAgentGraphState) -> ToolAgentGraphState:
    """Execute the tool specialist inside its own subgraph state."""

    task = state.get("tool_task")
    if task is None:
        return {}
    turn_id = str(state.get("active_turn_id") or f"turn_{uuid4().hex[:8]}")
    result = await run_tool_specialist(task=task)
    return {
        "tool_result": result.to_dict(),
        "messages": [_build_agent_result_message(turn_id=turn_id, result=result)],
    }


def build_tool_agent_graph():
    """Create the tool specialist subgraph with isolated specialist state."""

    if StateGraph is None:
        return None

    builder = StateGraph(ToolAgentGraphState)
    builder.add_node("execute", tool_agent_execute_node)
    builder.add_edge(START, "execute")
    builder.add_edge("execute", END)
    return builder.compile(name="tool_agent")


