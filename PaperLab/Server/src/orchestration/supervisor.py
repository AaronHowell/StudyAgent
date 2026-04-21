"""PaperLab main LangGraph orchestration graph."""

from __future__ import annotations

import asyncio
from typing import Annotated
from typing import Any
from typing import Literal
from typing import TypedDict
from urllib.parse import quote
from uuid import uuid4

from domain import MemoryType
from prompts.builders import build_main_route_messages
from prompts.builders import build_synthesis_prompt

from contracts import AgentResult
from contracts import AgentTask
from memory import build_memory_service
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
    _result_confidence,
    _result_status,
    _stringify_for_prompt,
)
from orchestration.graph_serialization import (
    build_assistant_metadata,
    _serialize_evidence_pack,
    _serialize_memory_item,
)
from orchestration.graph_state import PaperLabGraphState
from orchestration.request_config import AgentRequestConfig
from orchestration.request_config import resolve_agent_request_config
from orchestration.runtime_access import _runtime
from runtime import AgentSettings
from workers.retriever.agent import build_retrieve_agent_graph
from workers.retriever.agent import run_retrieve_specialist
from workers.tool.agent import build_tool_agent_graph
from workers.tool.agent import run_tool_specialist
from workers.workspace.agent import build_workspace_agent_graph
from workers.workspace.agent import run_workspace_specialist

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
    tool_task: dict[str, Any] | None
    workspace_task: dict[str, Any] | None
    retrieve_result_status: str
    tool_result_status: str
    workspace_result_status: str


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


def _build_checkpointer() -> Any | None:
    settings = AgentSettings.from_env()
    if not settings.checkpoint_redis_enabled:
        if InMemorySaver is None:
            return None
        return InMemorySaver()
    if RedisSaver is None:
        raise ImportError(
            "langgraph-checkpoint-redis is required when PAPERLAB_CHECKPOINT_REDIS_ENABLED=true."
        )
    saver = RedisSaver(
        redis_url=_checkpoint_redis_url(settings),
        ttl=_checkpoint_ttl_config(settings),
        checkpoint_prefix=settings.checkpoint_redis_checkpoint_prefix,
        checkpoint_write_prefix=settings.checkpoint_redis_checkpoint_write_prefix,
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
    tool_result = dict(state.get("tool_result", {}) or {})
    workspace_result = dict(state.get("workspace_result", {}) or {})
    return {
        "phase": phase,
        "turn_id": str(state.get("active_turn_id") or ""),
        "iteration_count": int(state.get("iteration_count", 0) or 0),
        "question": _message_text(_latest_human_text(messages)) if messages else "",
        "pending_user_messages": max(0, len(human_messages) - processed_count),
        "retrieve_task": state.get("retrieve_task").to_dict() if state.get("retrieve_task") else None,
        "tool_task": state.get("tool_task").to_dict() if state.get("tool_task") else None,
        "workspace_task": (
            state.get("workspace_task").to_dict() if state.get("workspace_task") else None
        ),
        "retrieve_result_status": _result_status(retrieve_result),
        "tool_result_status": _result_status(tool_result),
        "workspace_result_status": _result_status(workspace_result),
    }


def _memory_backend() -> Any | None:
    """Return the configured long-term memory backend with compatibility for older runtimes."""

    runtime = _runtime()
    return getattr(runtime, "memory_backend", getattr(runtime, "memory_store", None))


def _materialize_intervention_update(
    *,
    state: PaperLabGraphState,
    config: RunnableConfig | None,
    phase: str,
) -> dict[str, Any]:
    request_config = resolve_agent_request_config(dict(config or {}))
    turn_id = str(state.get("active_turn_id") or f"turn_{uuid4().hex[:8]}")
    messages = list(state.get("messages", []))
    human_messages = _human_messages(messages)
    processed_count = int(state.get("processed_human_message_count", 0) or 0)
    unseen_humans = human_messages[processed_count:]

    new_interventions: list[HumanMessage] = []
    intervention_texts: list[str] = []
    for message in unseen_humans:
        artifact_type = str(_message_meta(message).get("artifact_type") or "")
        if artifact_type in {"question", "intervention"}:
            continue
        text = _message_text(message.content).strip()
        if not text:
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
    """Normalize the latest user input into one structured message."""

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
    """Build a short-term context artifact from recent conversation turns."""

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

    if interrupt is not None:
        interrupt(_build_loop_interrupt_payload(state=state, phase="guidance_gate_pre_route"))
    return Command(
        update=_materialize_intervention_update(
            state=state,
            config=config,
            phase="guidance_gate_pre_route",
        ),
        goto="main_route",
    )


async def main_route_node(
    state: PaperLabGraphState,
    config: RunnableConfig | None = None,
) -> PaperLabGraphState:
    """Turn the latest conversation state into specialist tasks."""

    request_config = resolve_agent_request_config(dict(config or {}))
    turn_id = str(state.get("active_turn_id") or f"turn_{uuid4().hex[:8]}")
    messages = list(state.get("messages", []))
    question = _latest_human_text(messages)
    short_term_message = _latest_tool_message(messages, "build_short_term_context")
    memory_message = _latest_tool_message(messages, "search_memory")
    intervention_messages = _latest_messages_by_artifact(messages, "intervention", turn_id=turn_id)

    system_prompt, user_prompt = build_main_route_messages(
        question=question,
        short_term_context=_message_text(short_term_message.content) if short_term_message is not None else "",
        memory_context=_message_text(memory_message.content) if memory_message is not None else "",
        interventions=[_message_text(message.content) for message in intervention_messages],
    )
    bound_model = _runtime().chat_model.bind_tools(_dispatch_schema())
    response = await bound_model.ainvoke(
        [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
    )
    tool_calls = _extract_tool_calls(response)
    args = _coerce_tool_call_args(tool_calls[0]) if tool_calls else {}

    run_retrieval = bool(args.get("run_retrieval", True))
    retrieval_query = str(args.get("retrieval_query") or question)
    retrieval_reason = str(args.get("retrieval_reason") or "Need project-grounded evidence.")
    run_tool = bool(args.get("run_tool", False))
    tool_query = str(args.get("tool_query") or question)
    tool_reason = str(args.get("tool_reason") or "Need external or tool-based information.")
    run_workspace = bool(args.get("run_workspace", False))
    workspace_query = str(args.get("workspace_query") or question)
    workspace_reason = str(args.get("workspace_reason") or "Need local workspace inspection.")

    task_messages: list[BaseMessage] = []
    retrieve_task: AgentTask | None = None
    tool_task: AgentTask | None = None
    workspace_task: AgentTask | None = None

    if run_retrieval:
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
            metadata={"project_id": request_config.project_id},
        )
        task_messages.append(_build_agent_task_message(turn_id=turn_id, task=retrieve_task))

    if run_tool:
        tool_task = AgentTask(
            task_id=f"task_tool_{uuid4().hex[:8]}",
            task_type="tool_research",
            agent_name="tool_agent",
            query=tool_query,
            reason=tool_reason,
            constraints={
                "top_k": AgentSettings.from_env().web_search_result_limit,
                "fetch_top_url": True,
            },
            metadata={},
        )
        task_messages.append(_build_agent_task_message(turn_id=turn_id, task=tool_task))

    if run_workspace:
        workspace_task = AgentTask(
            task_id=f"task_workspace_{uuid4().hex[:8]}",
            task_type="workspace_ops",
            agent_name="workspace_agent",
            query=workspace_query,
            reason=workspace_reason,
            constraints={"workspace_root": "."},
            metadata={},
        )
        task_messages.append(_build_agent_task_message(turn_id=turn_id, task=workspace_task))

    dispatched_agents = [
        task.agent_name
        for task in (retrieve_task, tool_task, workspace_task)
        if task is not None
    ]
    task_messages.append(
        _build_loop_status_message(
            turn_id=turn_id,
            phase="main_route_complete",
            summary=(
                "MainRoute prepared "
                + (", ".join(dispatched_agents) if dispatched_agents else "no specialists")
                + "."
            ),
            iteration_count=int(state.get("iteration_count", 0) or 0) + 1,
            metadata={"dispatched_agents": dispatched_agents},
        )
    )
    return {
        "messages": task_messages,
        "iteration_count": int(state.get("iteration_count", 0) or 0) + 1,
        "retrieve_task": retrieve_task,
        "tool_task": tool_task,
        "workspace_task": workspace_task,
        "retrieve_result": None,
        "tool_result": None,
        "workspace_result": None,
        "answer_confident": False,
        "stop_reason": "",
    }


def guidance_gate_post_route_node(
    state: PaperLabGraphState,
    config: RunnableConfig | None = None,
) -> Command[Literal["parallel_specialists"]]:
    """Pause after routing and before specialist execution."""

    if interrupt is not None:
        interrupt(_build_loop_interrupt_payload(state=state, phase="guidance_gate_post_route"))
    return Command(
        update=_materialize_intervention_update(
            state=state,
            config=config,
            phase="guidance_gate_post_route",
        ),
        goto="parallel_specialists",
    )


async def parallel_specialists_node(
    state: PaperLabGraphState,
    config: RunnableConfig | None = None,
) -> PaperLabGraphState:
    """Run retrieval, tool, and workspace specialists concurrently for one routing iteration."""

    request_config = resolve_agent_request_config(dict(config or {}))
    turn_id = str(state.get("active_turn_id") or f"turn_{uuid4().hex[:8]}")
    retrieve_task = state.get("retrieve_task")
    tool_task = state.get("tool_task")
    workspace_task = state.get("workspace_task")

    async def run_retrieval() -> AgentResult | None:
        if retrieve_task is None:
            return None
        return await run_retrieve_specialist(task=retrieve_task, request_config=request_config)

    async def run_tool() -> AgentResult | None:
        if tool_task is None:
            return None
        return await run_tool_specialist(task=tool_task)

    async def run_workspace() -> AgentResult | None:
        if workspace_task is None:
            return None
        return await run_workspace_specialist(task=workspace_task)

    retrieval_result, tool_result, workspace_result = await asyncio.gather(
        run_retrieval(),
        run_tool(),
        run_workspace(),
    )

    output_messages: list[BaseMessage] = []
    if retrieval_result is not None:
        output_messages.append(_build_agent_result_message(turn_id=turn_id, result=retrieval_result))
    if tool_result is not None:
        output_messages.append(_build_agent_result_message(turn_id=turn_id, result=tool_result))
    if workspace_result is not None:
        output_messages.append(_build_agent_result_message(turn_id=turn_id, result=workspace_result))

    output_messages.append(
        _build_loop_status_message(
            turn_id=turn_id,
            phase="parallel_specialists_complete",
            summary="Parallel specialist execution finished.",
            iteration_count=int(state.get("iteration_count", 0) or 0),
            metadata={
                "completed_agents": [
                    agent_name
                    for agent_name, result in [
                        ("retrieval_agent", retrieval_result),
                        ("tool_agent", tool_result),
                        ("workspace_agent", workspace_result),
                    ]
                    if result is not None
                ],
            },
        )
    )
    return {
        "messages": output_messages,
        "retrieve_result": retrieval_result.to_dict() if retrieval_result is not None else None,
        "tool_result": tool_result.to_dict() if tool_result is not None else None,
        "workspace_result": workspace_result.to_dict() if workspace_result is not None else None,
    }


def _has_strong_retrieval_support(result: dict[str, Any]) -> bool:
    metadata = dict(result.get("metadata", {}) or {})
    citations = list(metadata.get("citations", []))
    evidence_counts = dict(metadata.get("evidence_counts", {}) or {})
    return (
        bool(citations)
        and _result_confidence(result) >= 0.7
        and int(evidence_counts.get("chunk_count", 0) or 0) > 0
    )


def _has_strong_tool_support(result: dict[str, Any]) -> bool:
    metadata = dict(result.get("metadata", {}) or {})
    web_sources = list(metadata.get("web_sources", []))
    tool_sources = list(metadata.get("tool_sources", []))
    return bool(web_sources or tool_sources) and _result_confidence(result) >= 0.6


def _has_strong_workspace_support(result: dict[str, Any]) -> bool:
    metadata = dict(result.get("metadata", {}) or {})
    workspace_sources = list(metadata.get("workspace_sources", []))
    return bool(workspace_sources) and _result_confidence(result) >= 0.6


def _answer_is_confident(
    *,
    retrieve_result: dict[str, Any],
    tool_result: dict[str, Any],
    workspace_result: dict[str, Any],
) -> bool:
    return (
        _has_strong_retrieval_support(retrieve_result)
        or _has_strong_tool_support(tool_result)
        or _has_strong_workspace_support(workspace_result)
    )


def _agents_cannot_complete(
    *,
    retrieve_task: AgentTask | None,
    tool_task: AgentTask | None,
    workspace_task: AgentTask | None,
    retrieve_result: dict[str, Any],
    tool_result: dict[str, Any],
    workspace_result: dict[str, Any],
) -> bool:
    requested_agents = [
        item for item in (retrieve_task, tool_task, workspace_task) if item is not None
    ]
    if not requested_agents:
        return not _answer_is_confident(
            retrieve_result=retrieve_result,
            tool_result=tool_result,
            workspace_result=workspace_result,
        )

    terminal_failures = {"failed", "skipped", "cancelled"}
    for task in requested_agents:
        if task.agent_name == "retrieval_agent":
            result = retrieve_result
        elif task.agent_name == "tool_agent":
            result = tool_result
        else:
            result = workspace_result
        if not result:
            return False
        if _result_status(result) not in terminal_failures:
            return False
    return not _answer_is_confident(
        retrieve_result=retrieve_result,
        tool_result=tool_result,
        workspace_result=workspace_result,
    )


def _route_after_assess(state: PaperLabGraphState) -> str:
    if bool(state.get("answer_confident", False)):
        return "synthesize"
    if str(state.get("stop_reason") or ""):
        return "synthesize"
    iteration_count = int(state.get("iteration_count", 0) or 0)
    max_iterations = int(state.get("max_iterations", 1) or 1)
    if iteration_count >= max_iterations:
        return "synthesize"
    return "guidance_gate_pre_route"


def guidance_gate_pre_assess_node(
    state: PaperLabGraphState,
    config: RunnableConfig | None = None,
) -> Command[Literal["assess"]]:
    """Pause after specialists complete so the UI can inject guidance before assessment."""

    if interrupt is not None:
        interrupt(_build_loop_interrupt_payload(state=state, phase="guidance_gate_pre_assess"))
    return Command(
        update=_materialize_intervention_update(
            state=state,
            config=config,
            phase="guidance_gate_pre_assess",
        ),
        goto="assess",
    )


def assess_node(
    state: PaperLabGraphState,
    config: RunnableConfig | None = None,
) -> PaperLabGraphState:
    """Assess whether the loop should continue or proceed to final synthesis."""

    del config
    turn_id = str(state.get("active_turn_id") or f"turn_{uuid4().hex[:8]}")
    retrieve_result = dict(state.get("retrieve_result", {}) or {})
    tool_result = dict(state.get("tool_result", {}) or {})
    workspace_result = dict(state.get("workspace_result", {}) or {})
    answer_confident = _answer_is_confident(
        retrieve_result=retrieve_result,
        tool_result=tool_result,
        workspace_result=workspace_result,
    )
    stop_reason = ""
    if _agents_cannot_complete(
        retrieve_task=state.get("retrieve_task"),
        tool_task=state.get("tool_task"),
        workspace_task=state.get("workspace_task"),
        retrieve_result=retrieve_result,
        tool_result=tool_result,
        workspace_result=workspace_result,
    ):
        stop_reason = "agent_cannot_complete"
    elif (
        int(state.get("iteration_count", 0) or 0)
        >= int(state.get("max_iterations", 1) or 1)
        and not answer_confident
    ):
        stop_reason = "max_iterations_reached"
    status_summary = (
        "Assess found enough evidence for synthesis."
        if answer_confident or stop_reason
        else "Assess requested another routing iteration."
    )
    return {
        "messages": [
            _build_loop_status_message(
                turn_id=turn_id,
                phase="assess_complete",
                summary=status_summary,
                iteration_count=int(state.get("iteration_count", 0) or 0),
                metadata={
                    "answer_confident": answer_confident,
                    "stop_reason": stop_reason,
                },
            )
        ],
        "answer_confident": answer_confident,
        "stop_reason": stop_reason,
    }


async def synthesize_node(
    state: PaperLabGraphState,
    config: RunnableConfig | None = None,
) -> PaperLabGraphState:
    """Synthesize specialist results into the final assistant answer."""

    del config
    turn_id = str(state.get("active_turn_id") or f"turn_{uuid4().hex[:8]}")
    messages = list(state.get("messages", []))
    question = _latest_human_text(messages)
    short_term_message = _latest_tool_message(messages, "build_short_term_context")
    memory_message = _latest_tool_message(messages, "search_memory")
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
    tool_result = dict(state.get("tool_result", {}) or {})
    workspace_result = dict(state.get("workspace_result", {}) or {})
    if not retrieve_result and not tool_result and not workspace_result:
        for message in result_messages:
            result_payload = dict(_message_meta(message).get("result", {}) or {})
            if result_payload.get("agent_name") == "retrieval_agent" and not retrieve_result:
                retrieve_result = result_payload
            elif result_payload.get("agent_name") == "tool_agent" and not tool_result:
                tool_result = result_payload
            elif result_payload.get("agent_name") == "workspace_agent" and not workspace_result:
                workspace_result = result_payload

    synthesis_prompt = build_synthesis_prompt(
        question=question,
        short_term_context=_message_text(short_term_message.content) if short_term_message is not None else "",
        memory_context=_message_text(memory_message.content) if memory_message is not None else "",
        interventions=[_message_text(message.content) for message in intervention_messages],
        specialist_payloads=[
            _stringify_for_prompt(retrieve_result) if retrieve_result else "",
            _stringify_for_prompt(tool_result) if tool_result else "",
            _stringify_for_prompt(workspace_result) if workspace_result else "",
        ],
    )
    raw_answer = await _runtime().chat_model.ainvoke(synthesis_prompt)

    retrieve_metadata = dict(retrieve_result.get("metadata", {}) or {})
    tool_metadata = dict(tool_result.get("metadata", {}) or {})
    workspace_metadata = dict(workspace_result.get("metadata", {}) or {})
    assistant_message = _build_assistant_message(
        turn_id=turn_id,
        content=_message_text(getattr(raw_answer, "content", raw_answer)),
        metadata={
            "artifact_type": "answer",
            "depends_on": dependencies,
            "citations": list(retrieve_metadata.get("citations", [])),
            "memory_hits": list(_message_meta(memory_message).get("memory_hits", []))
            if memory_message
            else [],
            "evidence_counts": dict(retrieve_metadata.get("evidence_counts", {})),
            "web_sources": list(tool_metadata.get("web_sources", [])),
            "tool_sources": list(tool_metadata.get("tool_sources", [])),
            "workspace_sources": list(workspace_metadata.get("workspace_sources", [])),
            "reusable": True,
            "orchestration": "weak_speculative_multi_agent",
            "answer_confident": bool(state.get("answer_confident", False)),
            "stop_reason": str(state.get("stop_reason") or ""),
            "intervention_count": int(state.get("intervention_count", 0) or 0),
        },
        raw_id=getattr(raw_answer, "id", None),
    )
    return {
        "messages": [assistant_message],
        "answer_confident": bool(state.get("answer_confident", False)),
        "stop_reason": str(state.get("stop_reason") or ""),
    }


def recall_memory_node(
    state: PaperLabGraphState,
    config: RunnableConfig | None = None,
) -> PaperLabGraphState:
    """Recall project-scoped memory and append it as a tool artifact message."""

    request_config = resolve_agent_request_config(dict(config or {}))
    turn_id = str(state.get("active_turn_id") or f"turn_{uuid4().hex[:8]}")
    memory_service = build_memory_service(
        backend=_memory_backend(),
        settings=AgentSettings.from_env(),
    )
    question = _latest_human_text(state.get("messages", []))
    recall_result = memory_service.recall(
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
        },
    )
    return {"messages": [message]}


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
    memory_service = build_memory_service(
        backend=_memory_backend(),
        settings=AgentSettings.from_env(),
    )
    memory_service.store_turn(
        role="supervisor",
        project_id=request_config.project_id,
        thread_id=request_config.thread_id,
        user_text=user_text,
        assistant_text=_message_text(assistant_message.content),
        metadata={
            "citations": list(assistant_meta.get("citations", [])),
            "evidence_counts": dict(assistant_meta.get("evidence_counts", {})),
            "depends_on": list(assistant_meta.get("depends_on", [])),
        },
    )
    return {}


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
        retrieve_task: AgentTask | None
        tool_task: AgentTask | None
        workspace_task: AgentTask | None
        retrieve_result: dict[str, Any] | None
        tool_result: dict[str, Any] | None
        workspace_result: dict[str, Any] | None
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
    builder.add_node("synthesize", synthesize_node)
    builder.add_node("store_memory", store_memory_node)
    builder.add_node("release_thread_lock", release_thread_lock_node)

    builder.add_edge(START, "prepare_turn")
    builder.add_edge("prepare_turn", "build_short_term_context")
    builder.add_edge("build_short_term_context", "recall_memory")
    builder.add_edge("recall_memory", "thread_lock")
    builder.add_edge("thread_lock", "guidance_gate_pre_route")
    builder.add_edge("guidance_gate_pre_route", "main_route")
    builder.add_edge("main_route", "guidance_gate_post_route")
    builder.add_edge("guidance_gate_post_route", "parallel_specialists")
    builder.add_edge("parallel_specialists", "guidance_gate_pre_assess")
    builder.add_edge("guidance_gate_pre_assess", "assess")
    builder.add_conditional_edges(
        "assess",
        _route_after_assess,
        {
            "guidance_gate_pre_route": "guidance_gate_pre_route",
            "synthesize": "synthesize",
        },
    )
    builder.add_edge("synthesize", "store_memory")
    builder.add_edge("store_memory", "release_thread_lock")
    builder.add_edge("release_thread_lock", END)
    return builder.compile(checkpointer=_build_checkpointer())


retrieve_agent_graph = build_retrieve_agent_graph(
    resolve_request_config=resolve_agent_request_config
)
tool_agent_graph = build_tool_agent_graph()
workspace_agent_graph = build_workspace_agent_graph()
graph = build_graph()



