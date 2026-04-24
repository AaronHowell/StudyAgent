"""Workspace specialist subgraph for PaperLab."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

from contracts import AgentArtifact
from contracts import AgentResult
from contracts import AgentTask
from integrations.sandbox import get_sandbox_manager
from integrations.sandbox import get_sandbox_runner
from orchestration.graph_messages import _build_agent_result_message
from orchestration.graph_messages import _coerce_tool_call_args
from orchestration.graph_messages import _extract_tool_calls
from orchestration.output_summary import build_progress_summary
from orchestration.graph_state import WorkspaceAgentGraphState
from orchestration.request_config import _coerce_positive_int
from orchestration.runtime_access import _runtime
from prompts.builders import build_workspace_agent_selection_messages

try:
    from langchain_core.messages import HumanMessage
    from langchain_core.messages import SystemMessage
    from langgraph.graph import END
    from langgraph.graph import START
    from langgraph.graph import StateGraph
except ImportError:  # pragma: no cover
    HumanMessage = Any  # type: ignore[assignment]
    SystemMessage = Any  # type: ignore[assignment]
    END = "__end__"
    START = "__start__"
    StateGraph = None  # type: ignore[assignment]


def _graph_runtime():
    return _runtime()


def _sandbox_manager():
    return get_sandbox_manager()


def _sandbox_runner():
    return get_sandbox_runner()


def _coerce_final_task_status(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in {"finished", "failed", "expired"}:
        raise ValueError("finish_task status must be one of: finished, failed, expired.")
    return normalized


def _serialize_source(path_text: str, *, summary: str, kind: str, task_id: str | None = None) -> dict[str, object]:
    payload: dict[str, object] = {
        "kind": kind,
        "path": path_text,
        "summary": summary,
    }
    if task_id:
        payload["task_id"] = task_id
    return payload


def _workspace_choice_schema() -> list[dict[str, object]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "list_workspace",
                "description": "List files or directories under one repository path in read-only mode.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "recursive": {"type": "boolean"},
                        "limit": {"type": "integer"},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read one repository file in read-only mode.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "max_chars": {"type": "integer"},
                    },
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_workspace",
                "description": "Search the repository with ripgrep in read-only mode.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string"},
                        "path": {"type": "string"},
                        "limit": {"type": "integer"},
                    },
                    "required": ["pattern"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "create_run_task",
                "description": "Create a sandboxed task workspace for local coding or execution.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "objective": {"type": "string"},
                        "source_path": {"type": "string"},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "run_task_command",
                "description": "Run one whitelisted command inside a sandbox task workspace.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string"},
                        "command": {"type": "string"},
                        "timeout_seconds": {"type": "integer"},
                    },
                    "required": ["task_id", "command"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "write_task_file",
                "description": "Write or overwrite a text file inside one sandbox task workspace.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string"},
                        "relative_path": {"type": "string"},
                        "content": {"type": "string"},
                        "overwrite": {"type": "boolean"},
                    },
                    "required": ["task_id", "relative_path", "content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "read_task_file",
                "description": "Read one text file from a sandbox task workspace.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string"},
                        "relative_path": {"type": "string"},
                        "max_chars": {"type": "integer"},
                    },
                    "required": ["task_id", "relative_path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_task_files",
                "description": "List files or directories inside a sandbox task workspace.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string"},
                        "relative_path": {"type": "string"},
                        "recursive": {"type": "boolean"},
                        "limit": {"type": "integer"},
                    },
                    "required": ["task_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "finish_task",
                "description": "Mark a sandbox task as finished, failed, or expired with a short summary.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string"},
                        "summary": {"type": "string"},
                        "status": {"type": "string"},
                    },
                    "required": ["task_id", "summary", "status"],
                },
            },
        },
    ]


async def run_workspace_specialist(*, task: AgentTask) -> AgentResult:
    """Execute one workspace specialist task."""

    selection_model = _graph_runtime().chat_model.bind_tools(_workspace_choice_schema())
    system_prompt, user_prompt = build_workspace_agent_selection_messages(
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
    if not selection_calls:
        return AgentResult(
            task_id=task.task_id,
            agent_name=task.agent_name,
            status="skipped",
            summary="WorkspaceAgent did not select a workspace action.",
            artifacts=[],
            confidence=0.0,
            metadata={
                "workspace_sources": [],
                "workspace_action": "",
                "progress_summary": build_progress_summary(
                    done="已尝试规划工作区动作，但未选出可执行项",
                    next="可补充更明确的工作区任务",
                    pending="工作区信息尚未获取",
                ),
            },
        )

    tool_call = selection_calls[0]
    action = str(tool_call.get("name") or "")
    args = _coerce_tool_call_args(tool_call)
    try:
        result = await asyncio.to_thread(_execute_workspace_action, action, args)
    except Exception as exc:
        return AgentResult(
            task_id=task.task_id,
            agent_name=task.agent_name,
            status="failed",
            summary=f"WorkspaceAgent failed while running {action}: {exc}",
            artifacts=[],
            confidence=0.0,
            metadata={
                "workspace_sources": [],
                "workspace_action": action,
                "error": str(exc),
                "progress_summary": build_progress_summary(
                    done=f"已尝试执行工作区动作 {action}",
                    next="修正参数或环境后可重试",
                    pending="目标工作区结果尚未拿到",
                ),
            },
        )

    return AgentResult(
        task_id=task.task_id,
        agent_name=task.agent_name,
        status="completed",
        summary=result["summary"],
        artifacts=[
            AgentArtifact(
                artifact_id=f"artifact_workspace_{uuid4().hex[:8]}",
                artifact_type="workspace_result",
                content=str(result.get("content") or ""),
                metadata={
                    "workspace_action": action,
                    "workspace_sources": result.get("workspace_sources", []),
                },
            ).to_dict()
        ],
        confidence=float(result.get("confidence", 0.6) or 0.6),
        metadata={
            "workspace_action": action,
            "workspace_sources": result.get("workspace_sources", []),
            "progress_summary": build_progress_summary(
                done=str(result.get("summary") or ""),
                next="可继续根据工作区结果做综合回答或下一步修改",
                pending="尚未确认是否还需要更多仓库上下文或执行结果",
            ),
        },
    )


def _execute_workspace_action(action: str, args: dict[str, Any]) -> dict[str, object]:
    if action == "list_workspace":
        path_text = str(args.get("path") or ".")
        recursive = bool(args.get("recursive", False))
        limit = _coerce_positive_int(args.get("limit"), 50)
        entries = _sandbox_manager().list_repo(path=path_text, recursive=recursive, limit=limit)
        return {
            "summary": f"WorkspaceAgent listed {len(entries)} repository paths under {path_text}.",
            "content": "\n".join(entries),
            "workspace_sources": [
                _serialize_source(path_text, summary=f"{len(entries)} repository paths listed", kind="directory")
            ],
            "confidence": 0.45,
        }

    if action == "read_file":
        path_text = str(args.get("path") or "")
        max_chars = _coerce_positive_int(args.get("max_chars"), 12_000)
        content = _sandbox_manager().read_repo_file(path=path_text, max_chars=max_chars)
        return {
            "summary": f"WorkspaceAgent read repository file {path_text}.",
            "content": content,
            "workspace_sources": [
                _serialize_source(path_text, summary="Repository file content read", kind="file")
            ],
            "confidence": 0.7,
        }

    if action == "search_workspace":
        pattern = str(args.get("pattern") or "").strip()
        path_text = str(args.get("path") or ".")
        limit = _coerce_positive_int(args.get("limit"), 30)
        content = _sandbox_manager().search_repo(pattern=pattern, path=path_text, limit=limit)
        return {
            "summary": f"WorkspaceAgent searched the repository for '{pattern}'.",
            "content": content,
            "workspace_sources": [
                _serialize_source(path_text, summary=f"ripgrep pattern: {pattern}", kind="search")
            ],
            "confidence": 0.65 if content else 0.25,
        }

    if action == "create_run_task":
        title = str(args.get("title") or "").strip() or "Workspace task"
        objective = str(args.get("objective") or "").strip() or title
        source_path = str(args.get("source_path") or "").strip() or None
        task = _sandbox_manager().create_run_task(
            title=title,
            objective=objective,
            source_path=source_path,
        )
        return {
            "summary": f"WorkspaceAgent created sandbox task {task.task_id}.",
            "content": (
                f"task_id: {task.task_id}\n"
                f"workspace_path: {task.workspace_path}\n"
                f"status: {task.status}"
            ),
            "workspace_sources": [
                _serialize_source(task.workspace_path, summary=task.objective, kind="task", task_id=task.task_id)
            ],
            "confidence": 0.8,
        }

    if action == "run_task_command":
        task_id = str(args.get("task_id") or "").strip()
        command = str(args.get("command") or "").strip()
        result = _sandbox_runner().run_task_command(
            task_id,
            command=command,
            timeout_seconds=_coerce_positive_int(args.get("timeout_seconds"), 120),
        )
        return {
            "summary": f"WorkspaceAgent ran sandbox command for {task_id} with status {result.status}.",
            "content": (
                f"exit_code: {result.exit_code}\n"
                f"stdout:\n{result.stdout}\n\n"
                f"stderr:\n{result.stderr}\n\n"
                f"log_path: {result.log_path}"
            ),
            "workspace_sources": [
                _serialize_source(result.log_path, summary=result.command, kind="task_log", task_id=task_id)
            ],
            "confidence": 0.75 if result.exit_code == 0 else 0.45,
        }

    if action == "write_task_file":
        task_id = str(args.get("task_id") or "").strip()
        relative_path = str(args.get("relative_path") or "").strip()
        target = _sandbox_manager().write_task_file(
            task_id,
            relative_path=relative_path,
            content=str(args.get("content") or ""),
            overwrite=bool(args.get("overwrite", True)),
        )
        return {
            "summary": f"WorkspaceAgent wrote {relative_path} in sandbox task {task_id}.",
            "content": str(target),
            "workspace_sources": [
                _serialize_source(str(target), summary="Sandbox task file written", kind="task_file", task_id=task_id)
            ],
            "confidence": 0.8,
        }

    if action == "read_task_file":
        task_id = str(args.get("task_id") or "").strip()
        relative_path = str(args.get("relative_path") or "").strip()
        max_chars = _coerce_positive_int(args.get("max_chars"), 12_000)
        content = _sandbox_manager().read_task_file(
            task_id,
            relative_path=relative_path,
            max_chars=max_chars,
        )
        return {
            "summary": f"WorkspaceAgent read {relative_path} from sandbox task {task_id}.",
            "content": content,
            "workspace_sources": [
                _serialize_source(relative_path, summary="Sandbox task file content read", kind="task_file", task_id=task_id)
            ],
            "confidence": 0.7,
        }

    if action == "list_task_files":
        task_id = str(args.get("task_id") or "").strip()
        relative_path = str(args.get("relative_path") or ".")
        recursive = bool(args.get("recursive", False))
        limit = _coerce_positive_int(args.get("limit"), 50)
        entries = _sandbox_manager().list_task_files(
            task_id,
            relative_path=relative_path,
            recursive=recursive,
            limit=limit,
        )
        return {
            "summary": f"WorkspaceAgent listed {len(entries)} files in sandbox task {task_id}.",
            "content": "\n".join(entries),
            "workspace_sources": [
                _serialize_source(relative_path, summary=f"{len(entries)} sandbox paths listed", kind="task_directory", task_id=task_id)
            ],
            "confidence": 0.5,
        }

    if action == "finish_task":
        task_id = str(args.get("task_id") or "").strip()
        summary = str(args.get("summary") or "").strip()
        status = _coerce_final_task_status(str(args.get("status") or "finished"))
        metadata = _sandbox_manager().finish_task(task_id, summary=summary, status=status)
        return {
            "summary": f"WorkspaceAgent marked sandbox task {task_id} as {metadata.status}.",
            "content": f"task_id: {task_id}\nstatus: {metadata.status}\nsummary: {metadata.summary}",
            "workspace_sources": [
                _serialize_source(metadata.workspace_path, summary=metadata.summary, kind="task", task_id=task_id)
            ],
            "confidence": 0.75,
        }

    raise ValueError(f"Unsupported workspace action '{action}'.")


async def workspace_agent_execute_node(state: WorkspaceAgentGraphState) -> WorkspaceAgentGraphState:
    """Execute the workspace specialist inside its own subgraph state."""

    task = state.get("workspace_task")
    if task is None:
        return {}
    turn_id = str(state.get("active_turn_id") or f"turn_{uuid4().hex[:8]}")
    result = await run_workspace_specialist(task=task)
    return {
        "workspace_result": result.to_dict(),
        "messages": [_build_agent_result_message(turn_id=turn_id, result=result)],
    }


def build_workspace_agent_graph():
    """Create the workspace specialist subgraph with isolated specialist state."""

    if StateGraph is None:
        return None

    builder = StateGraph(WorkspaceAgentGraphState)
    builder.add_node("execute", workspace_agent_execute_node)
    builder.add_edge(START, "execute")
    builder.add_edge("execute", END)
    return builder.compile(name="workspace_agent")
