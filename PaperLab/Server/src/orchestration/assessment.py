from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any


@dataclass(slots=True)
class AnswerOrContinueDecision:
    answer_confident: bool
    next_tasks: list[str]
    answer: str
    summary: dict[str, str]


def parse_answer_or_continue_decision(raw_output: Any) -> AnswerOrContinueDecision:
    """Parse the model's combined answer-or-loop decision."""

    payload = _load_json_object(str(raw_output))
    answer_confident = _coerce_bool(payload.get("answer_confident", False))
    if answer_confident:
        return AnswerOrContinueDecision(
            answer_confident=True,
            next_tasks=[],
            answer=str(payload.get("answer") or payload.get("content") or "").strip(),
            summary=_coerce_summary(payload.get("summary")),
        )
    return AnswerOrContinueDecision(
        answer_confident=False,
        next_tasks=[],
        answer="",
        summary={"done": "", "next": "", "pending": ""},
    )


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


def _coerce_summary(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {"done": "", "next": "", "pending": ""}
    return {
        "done": str(value.get("done") or "").strip(),
        "next": str(value.get("next") or "").strip(),
        "pending": str(value.get("pending") or "").strip(),
    }
