"""Debug logger for PaperLab orchestration.

Captures all messages, tool calls, and inter-agent communication
for debugging and analysis.

Enable via environment variable: PAPERLAB_DEBUG_LOG_ENABLED=true
Logs are written to logs/orchestration-debug.jsonl
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("paperlab.debug")

_enabled: bool | None = None
_log_path: Path | None = None


def _is_enabled() -> bool:
    global _enabled
    if _enabled is None:
        _enabled = os.getenv("PAPERLAB_DEBUG_LOG_ENABLED", "false").lower() in {"true", "1", "yes"}
    return _enabled


def _get_log_path() -> Path:
    global _log_path
    if _log_path is None:
        log_dir = Path(os.getenv("PAPERLAB_DEBUG_LOG_DIR", "logs"))
        log_dir.mkdir(parents=True, exist_ok=True)
        _log_path = log_dir / "orchestration-debug.jsonl"
    return _log_path


def _write_event(event: dict[str, Any]) -> None:
    if not _is_enabled():
        return
    event["timestamp"] = datetime.now(timezone.utc).isoformat()
    try:
        with open(_get_log_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
    except Exception:
        logger.exception("Failed to write debug log event")


def log_routing_decision(
    *,
    turn_id: str,
    question: str,
    run_retrieval: bool,
    run_memory: bool,
    retrieval_query: str,
    disabled_capabilities: list[str],
) -> None:
    _write_event({
        "event": "routing_decision",
        "turn_id": turn_id,
        "question": question,
        "run_retrieval": run_retrieval,
        "run_memory": run_memory,
        "retrieval_query": retrieval_query,
        "disabled_capabilities": disabled_capabilities,
    })


def log_specialist_dispatch(
    *,
    turn_id: str,
    agent_name: str,
    task_id: str,
    query: str,
    reason: str,
) -> None:
    _write_event({
        "event": "specialist_dispatch",
        "turn_id": turn_id,
        "agent_name": agent_name,
        "task_id": task_id,
        "query": query,
        "reason": reason,
    })


def log_specialist_result(
    *,
    turn_id: str,
    agent_name: str,
    task_id: str,
    status: str,
    summary: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    _write_event({
        "event": "specialist_result",
        "turn_id": turn_id,
        "agent_name": agent_name,
        "task_id": task_id,
        "status": status,
        "summary": summary,
        "metadata": metadata,
    })


def log_tool_call(
    *,
    turn_id: str,
    tool_name: str,
    args: dict[str, Any],
    source: str = "supervisor",
) -> None:
    _write_event({
        "event": "tool_call",
        "turn_id": turn_id,
        "tool_name": tool_name,
        "args": args,
        "source": source,
    })


def log_tool_result(
    *,
    turn_id: str,
    tool_name: str,
    status: str,
    summary: str,
    content_preview: str = "",
) -> None:
    _write_event({
        "event": "tool_result",
        "turn_id": turn_id,
        "tool_name": tool_name,
        "status": status,
        "summary": summary,
        "content_preview": content_preview[:500],
    })


def log_llm_call(
    *,
    turn_id: str,
    stage: str,
    prompt_preview: str = "",
    response_preview: str = "",
    tool_count: int = 0,
) -> None:
    _write_event({
        "event": "llm_call",
        "turn_id": turn_id,
        "stage": stage,
        "prompt_preview": prompt_preview[:500],
        "response_preview": response_preview[:500],
        "tool_count": tool_count,
    })


def log_assess_decision(
    *,
    turn_id: str,
    iteration: int,
    answer_confident: bool,
    should_loop: bool,
    answer_preview: str = "",
) -> None:
    _write_event({
        "event": "assess_decision",
        "turn_id": turn_id,
        "iteration": iteration,
        "answer_confident": answer_confident,
        "should_loop": should_loop,
        "answer_preview": answer_preview[:500],
    })


def log_synthesis(
    *,
    turn_id: str,
    question: str,
    answer_text: str,
    tool_observations_count: int,
    has_retrieval: bool,
) -> None:
    _write_event({
        "event": "synthesis",
        "turn_id": turn_id,
        "question": question,
        "answer_text": answer_text[:1000],
        "tool_observations_count": tool_observations_count,
        "has_retrieval": has_retrieval,
    })


def log_error(
    *,
    turn_id: str,
    stage: str,
    error: str,
) -> None:
    _write_event({
        "event": "error",
        "turn_id": turn_id,
        "stage": stage,
        "error": error,
    })
