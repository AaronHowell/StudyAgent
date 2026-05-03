from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any


@dataclass(slots=True)
class AssessmentDecision:
    answer_confident: bool
    next_tasks: list[str]


def parse_assessment_decision(raw_output: Any) -> AssessmentDecision:
    """Parse the model's evidence-sufficiency decision."""

    payload = _load_json_object(str(raw_output))
    answer_confident = _coerce_bool(payload.get("answer_confident", False))
    next_tasks = [] if answer_confident else _coerce_next_tasks(payload.get("next_tasks", []))
    return AssessmentDecision(answer_confident=answer_confident, next_tasks=next_tasks)


def _load_json_object(raw_output: str) -> dict[str, Any]:
    text = raw_output.strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return {}
        try:
            parsed = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return {}
    return parsed if isinstance(parsed, dict) else {}


def _coerce_next_tasks(value: Any) -> list[str]:
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    if not isinstance(value, list):
        return []

    tasks: list[str] = []
    for item in value:
        task = _coerce_task(item)
        if task:
            tasks.append(task)
    return tasks


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "1"}:
            return True
        if normalized in {"false", "no", "0", ""}:
            return False
    return bool(value)


def _coerce_task(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if not isinstance(value, dict):
        return ""

    task_text = str(value.get("task") or value.get("query") or value.get("reason") or "").strip()
    if not task_text:
        return ""
    agent_name = str(value.get("agent") or value.get("agent_name") or "").strip()
    if agent_name:
        return f"{agent_name}: {task_text}"
    return task_text
