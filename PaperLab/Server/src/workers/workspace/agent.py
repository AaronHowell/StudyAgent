"""Workspace specialist subgraph for PaperLab."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

from contracts import AgentResult
from contracts import AgentTask
from integrations.sandbox import get_sandbox_manager
from integrations.sandbox import get_sandbox_runner
from orchestration.graph_messages import _build_agent_result_message
from orchestration.graph_messages import _coerce_tool_call_args
from orchestration.graph_messages import _extract_tool_calls
from orchestration.graph_state import WorkspaceAgentGraphState
from orchestration.request_config import _coerce_positive_int
from orchestration.runtime_access import _runtime
from prompts.builders import build_workspace_agent_selection_messages
from workers.workspace.implementation import WorkspaceImplementationState
from workers.workspace.implementation import build_implementation_report
from workers.workspace.implementation import build_initial_implementation_state
from workers.workspace.implementation import record_workspace_observation

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
                "name": "list",
                "description": "List repository paths or sandbox task paths.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "task_id": {"type": "string"},
                        "recursive": {"type": "boolean"},
                        "limit": {"type": "integer"},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "read",
                "description": "Read one repository file or sandbox task file.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "task_id": {"type": "string"},
                        "max_chars": {"type": "integer"},
                    },
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search",
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
                "name": "run",
                "description": "Run one whitelisted command inside the sandbox task workspace.",
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
                "name": "write",
                "description": "Write or overwrite a text file inside the sandbox task workspace.",
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
                "name": "finish",
                "description": "Finish the implementation loop with a structured status and summary.",
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
    """Execute a goal-driven workspace implementation task."""

    implementation_state = build_initial_implementation_state(task)
    try:
        workspace_task_id = await asyncio.to_thread(_create_workspace_task, task, implementation_state)
    except Exception as exc:
        implementation_state = record_workspace_observation(
            implementation_state,
            action="plan",
            summary=f"WorkspaceAgent could not create a sandbox task: {exc}",
            content="",
            blocker=str(exc),
        )
        return build_implementation_report(implementation_state, agent_name=task.agent_name, status="failed")

    status = "completed"
    while _should_continue(implementation_state):
        tool_call = await _select_workspace_action(
            implementation_state,
            task=task,
            workspace_task_id=workspace_task_id,
        )
        if tool_call is None:
            implementation_state = record_workspace_observation(
                implementation_state,
                action="finish",
                summary="WorkspaceAgent did not select another action.",
                content="",
                blocker="No workspace action selected.",
            )
            status = "blocked"
            break

        action = str(tool_call.get("name") or "")
        args = _coerce_tool_call_args(tool_call)
        if workspace_task_id and action in {"write", "run", "finish"} and not args.get("task_id"):
            args["task_id"] = workspace_task_id
        if action == "finish":
            implementation_state = record_workspace_observation(
                implementation_state,
                action=action,
                summary=str(args.get("summary") or "WorkspaceAgent finished implementation."),
                content="",
                blocker=None if str(args.get("status") or "finished") == "finished" else str(args.get("summary") or ""),
                next_actions=[],
            )
            status = "completed" if str(args.get("status") or "finished") == "finished" else "blocked"
            break

        try:
            result = await asyncio.to_thread(_execute_workspace_action, action, args)
        except Exception as exc:
            implementation_state = record_workspace_observation(
                implementation_state,
                action=action,
                summary=f"WorkspaceAgent failed while running {action}: {exc}",
                content="",
                blocker=str(exc),
            )
            status = "failed"
            break

        implementation_state = record_workspace_observation(
            implementation_state,
            action=action,
            summary=str(result.get("summary") or ""),
            content=str(result.get("content") or ""),
            changed_files=list(result.get("changed_files", []) or []),
            test_result=str(result.get("test_result") or "") or None,
            blocker=str(result.get("blocker") or "") or None,
            next_actions=list(result.get("next_actions", []) or []),
        )

    if _should_continue(implementation_state):
        status = "partial"
    elif implementation_state.blockers and status == "completed":
        status = "blocked"
    return build_implementation_report(implementation_state, agent_name=task.agent_name, status=status)


def _create_workspace_task(task: AgentTask, state: WorkspaceImplementationState) -> str:
    source_path = str(task.constraints.get("source_path") or ".")
    created = _sandbox_manager().create_run_task(
        title=f"Workspace implementation: {task.query}",
        objective=state.objective,
        source_path=source_path,
    )
    return str(created.task_id)


async def _select_workspace_action(
    state: WorkspaceImplementationState,
    *,
    task: AgentTask,
    workspace_task_id: str,
) -> dict[str, Any] | None:
    selection_model = _graph_runtime().chat_model.bind_tools(_workspace_choice_schema())
    state_text = _format_implementation_state(state, workspace_task_id=workspace_task_id)
    system_prompt, user_prompt = build_workspace_agent_selection_messages(
        task_query=f"{task.query}\n\nImplementation state:\n{state_text}",
        reason=task.reason,
    )
    selection_response = await selection_model.ainvoke(
        [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
    )
    selection_calls = _extract_tool_calls(selection_response)
    return selection_calls[0] if selection_calls else None


def _format_implementation_state(state: WorkspaceImplementationState, *, workspace_task_id: str) -> str:
    return (
        f"objective: {state.objective}\n"
        f"workspace_task_id: {workspace_task_id}\n"
        f"current_step: {state.current_step}\n"
        f"plan: {state.plan}\n"
        f"acceptance_criteria: {state.acceptance_criteria}\n"
        f"constraints: {state.constraints}\n"
        f"completed_steps: {state.completed_steps}\n"
        f"changed_files: {state.changed_files}\n"
        f"test_results: {state.test_results}\n"
        f"blockers: {state.blockers}\n"
        f"next_actions: {state.next_actions}\n"
        "Choose exactly one action. Use finish only when the acceptance criteria are met or a blocker prevents progress."
    )


def _should_continue(state: WorkspaceImplementationState) -> bool:
    if state.blockers:
        return False
    if not state.current_step:
        return False
    return len(state.action_history or []) < state.max_steps


def _execute_workspace_action(action: str, args: dict[str, Any]) -> dict[str, object]:
    if action in {"list", "list_workspace"}:
        path_text = str(args.get("path") or ".")
        task_id = str(args.get("task_id") or "").strip()
        recursive = bool(args.get("recursive", False))
        limit = _coerce_positive_int(args.get("limit"), 50)
        if task_id:
            entries = _sandbox_manager().list_task_files(
                task_id,
                relative_path=path_text,
                recursive=recursive,
                limit=limit,
            )
        else:
            entries = _sandbox_manager().list_repo(path=path_text, recursive=recursive, limit=limit)
        return {
            "summary": f"WorkspaceAgent listed {len(entries)} workspace paths under {path_text}.",
            "content": "\n".join(entries),
            "workspace_sources": [
                _serialize_source(path_text, summary=f"{len(entries)} repository paths listed", kind="directory")
            ],
            "confidence": 0.45,
        }

    if action in {"read", "read_file"}:
        path_text = str(args.get("path") or "")
        task_id = str(args.get("task_id") or "").strip()
        max_chars = _coerce_positive_int(args.get("max_chars"), 12_000)
        if task_id:
            content = _sandbox_manager().read_task_file(
                task_id,
                relative_path=path_text,
                max_chars=max_chars,
            )
        else:
            content = _sandbox_manager().read_repo_file(path=path_text, max_chars=max_chars)
        return {
            "summary": f"WorkspaceAgent read workspace file {path_text}.",
            "content": content,
            "workspace_sources": [
                _serialize_source(path_text, summary="Repository file content read", kind="file")
            ],
            "confidence": 0.7,
        }

    if action in {"search", "search_workspace"}:
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

    if action in {"run", "run_task_command"}:
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
            "test_result": f"{command}: exit_code={result.exit_code}",
            "confidence": 0.75 if result.exit_code == 0 else 0.45,
        }

    if action in {"write", "write_task_file"}:
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
            "changed_files": [relative_path],
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

    if action in {"finish", "finish_task"}:
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


def workspace_agent_plan_node(state: WorkspaceAgentGraphState) -> WorkspaceAgentGraphState:
    """Initialize the implementation state and sandbox task."""

    task = state.get("workspace_task")
    if task is None:
        return {}
    implementation_state = build_initial_implementation_state(task)
    try:
        workspace_task_id = _create_workspace_task(task, implementation_state)
    except Exception as exc:
        implementation_state = record_workspace_observation(
            implementation_state,
            action="plan",
            summary=f"WorkspaceAgent could not create a sandbox task: {exc}",
            content="",
            blocker=str(exc),
        )
        workspace_task_id = ""
    return {
        "implementation_state": implementation_state.to_dict(),
        "workspace_task_id": workspace_task_id,
    }


async def workspace_agent_act_node(state: WorkspaceAgentGraphState) -> WorkspaceAgentGraphState:
    """Select the next workspace action for the current implementation step."""

    task = state.get("workspace_task")
    implementation_payload = dict(state.get("implementation_state", {}) or {})
    if task is None or not implementation_payload:
        return {}
    implementation_state = WorkspaceImplementationState.from_dict(implementation_payload)
    tool_call = await _select_workspace_action(
        implementation_state,
        task=task,
        workspace_task_id=str(state.get("workspace_task_id") or ""),
    )
    return {"pending_action": dict(tool_call or {})}


def workspace_agent_observe_node(state: WorkspaceAgentGraphState) -> WorkspaceAgentGraphState:
    """Execute the selected action and capture its observation."""

    tool_call = dict(state.get("pending_action", {}) or {})
    if not tool_call:
        return {
            "observation": {
                "action": "finish",
                "summary": "WorkspaceAgent did not select another action.",
                "content": "",
                "blocker": "No workspace action selected.",
            }
        }
    action = str(tool_call.get("name") or "")
    args = _coerce_tool_call_args(tool_call)
    workspace_task_id = str(state.get("workspace_task_id") or "")
    if workspace_task_id and action in {"write", "run", "finish"} and not args.get("task_id"):
        args["task_id"] = workspace_task_id
    if action == "finish":
        return {
            "observation": {
                "action": action,
                "summary": str(args.get("summary") or "WorkspaceAgent finished implementation."),
                "content": "",
                "blocker": None if str(args.get("status") or "finished") == "finished" else str(args.get("summary") or ""),
                "next_actions": [],
            }
        }
    try:
        result = _execute_workspace_action(action, args)
        return {"observation": {"action": action, **result}}
    except Exception as exc:
        return {
            "observation": {
                "action": action,
                "summary": f"WorkspaceAgent failed while running {action}: {exc}",
                "content": "",
                "blocker": str(exc),
            }
        }


def workspace_agent_assess_node(state: WorkspaceAgentGraphState) -> WorkspaceAgentGraphState:
    """Update implementation progress after the latest observation."""

    implementation_payload = dict(state.get("implementation_state", {}) or {})
    observation = dict(state.get("observation", {}) or {})
    if not implementation_payload or not observation:
        return {}
    implementation_state = WorkspaceImplementationState.from_dict(implementation_payload)
    updated = record_workspace_observation(
        implementation_state,
        action=str(observation.get("action") or ""),
        summary=str(observation.get("summary") or ""),
        content=str(observation.get("content") or ""),
        changed_files=list(observation.get("changed_files", []) or []),
        test_result=str(observation.get("test_result") or "") or None,
        blocker=str(observation.get("blocker") or "") or None,
        next_actions=list(observation.get("next_actions", []) or []),
    )
    return {"implementation_state": updated.to_dict()}


async def workspace_agent_report_node(state: WorkspaceAgentGraphState) -> WorkspaceAgentGraphState:
    """Build the final implementation report inside the workspace subgraph."""

    task = state.get("workspace_task")
    implementation_payload = dict(state.get("implementation_state", {}) or {})
    if task is None or not implementation_payload:
        return {}
    turn_id = str(state.get("active_turn_id") or f"turn_{uuid4().hex[:8]}")
    implementation_state = WorkspaceImplementationState.from_dict(implementation_payload)
    status = "completed"
    if implementation_state.blockers:
        status = "blocked"
    elif implementation_state.current_step:
        status = "partial"
    result = build_implementation_report(implementation_state, agent_name=task.agent_name, status=status)
    return {
        "workspace_result": result.to_dict(),
        "messages": [_build_agent_result_message(turn_id=turn_id, result=result)],
    }


def _route_workspace_after_assess(state: WorkspaceAgentGraphState) -> str:
    implementation_payload = dict(state.get("implementation_state", {}) or {})
    if not implementation_payload:
        return "report"
    implementation_state = WorkspaceImplementationState.from_dict(implementation_payload)
    return "act" if _should_continue(implementation_state) else "report"


def build_workspace_agent_graph():
    """Create the workspace specialist subgraph with isolated specialist state."""

    if StateGraph is None:
        return None

    builder = StateGraph(WorkspaceAgentGraphState)
    builder.add_node("plan", workspace_agent_plan_node)
    builder.add_node("act", workspace_agent_act_node)
    builder.add_node("observe", workspace_agent_observe_node)
    builder.add_node("assess", workspace_agent_assess_node)
    builder.add_node("report", workspace_agent_report_node)
    builder.add_edge(START, "plan")
    builder.add_edge("plan", "act")
    builder.add_edge("act", "observe")
    builder.add_edge("observe", "assess")
    builder.add_conditional_edges(
        "assess",
        _route_workspace_after_assess,
        {
            "act": "act",
            "report": "report",
        },
    )
    builder.add_edge("report", END)
    return builder.compile(name="workspace_agent")
