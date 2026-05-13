"""Tool specialist subgraph for PaperLab."""

from __future__ import annotations

import json
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
from orchestration.output_summary import build_progress_summary
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


def _tool_search_selection_schema() -> list[dict[str, object]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "recommend_tools",
                "description": "Select the most relevant tools for the supervisor to consider next.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "selected_names": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "reasons": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "why_selected": {"type": "string"},
                                },
                                "required": ["name", "why_selected"],
                            },
                        },
                        "termination_reason": {"type": "string"},
                    },
                    "required": ["selected_names", "reasons", "termination_reason"],
                },
            },
        }
    ]


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


def _available_tool_catalog(
    *,
    allow_web_search: bool,
    allow_mcp: bool,
    mcp_tools: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    catalog: list[dict[str, Any]] = []
    if allow_web_search:
        catalog.extend(
            [
                {
                    "name": "web_search",
                    "description": "Search the public web for external information.",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"},
                            "top_k": {"type": "integer"},
                        },
                        "required": ["query"],
                    },
                    "kind": "web",
                },
                {
                    "name": "url_fetch",
                    "description": "Fetch the body text for one explicit URL.",
                    "input_schema": {
                        "type": "object",
                        "properties": {"url": {"type": "string"}},
                        "required": ["url"],
                    },
                    "kind": "web",
                },
            ]
        )
    if allow_mcp:
        for tool in mcp_tools:
            catalog.append(
                {
                    "name": str(tool.get("name") or ""),
                    "description": str(tool.get("description") or "Call one MCP tool."),
                    "input_schema": dict(tool.get("input_schema", {}) or {"type": "object", "properties": {}}),
                    "kind": "mcp",
                }
            )
    return catalog


def _fallback_recommendations(
    *,
    catalog: list[dict[str, Any]],
    limit: int,
) -> tuple[list[dict[str, Any]], str]:
    selected = catalog[:limit]
    termination_reason = "more_available" if len(catalog) > len(selected) else "completed"
    return selected, termination_reason


def _recommendation_reason_map(args: dict[str, Any]) -> dict[str, str]:
    reason_map: dict[str, str] = {}
    for item in list(args.get("reasons", []) or []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        why_selected = str(item.get("why_selected") or "").strip()
        if name and why_selected:
            reason_map[name] = why_selected
    return reason_map


async def run_tool_specialist(
    *,
    task: AgentTask,
    cancel_token: CancellationToken | None = None,
) -> AgentResult:
    """Select a small set of external tools for the supervisor."""

    if cancel_token is not None and cancel_token.is_cancelled():
        return AgentResult(
            task_id=task.task_id,
            agent_name=task.agent_name,
            status="cancelled",
            summary="Tool search was cancelled.",
            artifacts=[],
            confidence=0.0,
            metadata={
                "recommended_tools": [],
                "tool_sources": [],
                "termination_reason": "cancelled",
                "cancelled": True,
                "progress_summary": build_progress_summary(
                    done="工具筛选在开始前被取消",
                    next="等待新的工具搜索任务",
                    pending="尚未返回任何外部工具",
                ),
            },
        )

    metadata = dict(task.metadata or {})
    already_exposed = {str(item).strip() for item in list(metadata.get("already_exposed_tools", []) or []) if str(item).strip()}
    allow_web_search = bool(metadata.get("allow_web_search", True))
    allow_mcp = bool(metadata.get("allow_mcp", False))
    max_tools = _coerce_positive_int(task.constraints.get("max_tools"), 4)

    mcp_provider = _graph_runtime().mcp_tool_provider
    mcp_tools = await mcp_provider.list_tools() if (allow_mcp and mcp_provider is not None) else []
    catalog = [
        item
        for item in _available_tool_catalog(
            allow_web_search=allow_web_search,
            allow_mcp=allow_mcp,
            mcp_tools=mcp_tools,
        )
        if str(item.get("name") or "") not in already_exposed
    ]

    if not catalog:
        return AgentResult(
            task_id=task.task_id,
            agent_name=task.agent_name,
            status="skipped",
            summary="No additional tools available to expose.",
            artifacts=[],
            confidence=0.0,
            metadata={
                "recommended_tools": [],
                "tool_sources": [],
                "termination_reason": "no_match",
                "progress_summary": build_progress_summary(
                    done="已检查可用 Web/MCP 工具",
                    next="可改用本地检索、记忆或文件工具",
                    pending="当前没有新的外部工具可暴露",
                ),
            },
        )

    selected_tools, termination_reason = _fallback_recommendations(catalog=catalog, limit=max_tools)
    system_prompt, user_prompt = build_tool_agent_selection_messages(
        task_query=task.query,
        reason=task.reason,
        available_tools=catalog,
        max_tools=max_tools,
        already_exposed_tools=sorted(already_exposed),
    )

    try:
        selection_model = _graph_runtime().worker_model.bind_tools(_tool_search_selection_schema())
        selection_response = await selection_model.ainvoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt),
            ]
        )
        selection_calls = _extract_tool_calls(selection_response)
        if selection_calls:
            args = _coerce_tool_call_args(selection_calls[0])
            reason_map = _recommendation_reason_map(args)
            selected_names = [
                str(item).strip()
                for item in list(args.get("selected_names", []) or [])
                if str(item).strip()
            ]
            if selected_names:
                selected_lookup = {str(item.get("name") or ""): item for item in catalog}
                filtered = [
                    {
                        **selected_lookup[name],
                        "why_selected": reason_map.get(name, "Matched the stated tool requirements."),
                    }
                    for name in selected_names
                    if name in selected_lookup
                ][:max_tools]
                if filtered:
                    selected_tools = filtered
            parsed_termination = str(args.get("termination_reason") or "").strip()
            if parsed_termination:
                termination_reason = parsed_termination
    except Exception:  # noqa: BLE001
        pass

    for tool in selected_tools:
        if not str(tool.get("why_selected") or "").strip():
            tool["why_selected"] = "Matched the stated tool requirements."

    summary = (
        f"Found {len(selected_tools)} additional tool(s) matching your query."
        if selected_tools
        else "No matching tools were found."
    )
    artifact_payload = {
        "recommended_tools": selected_tools,
        "termination_reason": termination_reason,
    }
    return AgentResult(
        task_id=task.task_id,
        agent_name=task.agent_name,
        status="completed" if selected_tools else "skipped",
        summary=summary,
        artifacts=[
            AgentArtifact(
                artifact_id=f"artifact_tool_search_{uuid4().hex[:8]}",
                artifact_type="tool_search_result",
                content=json.dumps(artifact_payload, ensure_ascii=False, indent=2),
                metadata=artifact_payload,
            ).to_dict()
        ],
        confidence=0.7 if selected_tools else 0.0,
        metadata={
            "recommended_tools": selected_tools,
            "tool_sources": [
                _serialize_tool_source(
                    kind=str(item.get("kind") or "external"),
                    title=str(item.get("name") or ""),
                    summary=str(item.get("why_selected") or ""),
                    tool_name=str(item.get("name") or ""),
                )
                for item in selected_tools
            ],
            "termination_reason": termination_reason,
            "progress_summary": build_progress_summary(
                done="已完成工具筛选并返回候选工具",
                next="supervisor 可直接调用这些工具，或再次 tool_search 获取更多候选",
                pending=(
                    "由于数量限制，仍有未披露工具"
                    if termination_reason == "more_available"
                    else "暂无额外工具待披露"
                ),
            ),
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
