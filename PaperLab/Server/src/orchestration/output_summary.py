"""统一处理主助手和 worker 的进度摘要。"""

from __future__ import annotations

import json
from typing import Any


def build_progress_summary(*, done: str, next: str, pending: str) -> dict[str, str]:
    """构造统一的三段式进度摘要。"""

    return {
        "done": done.strip(),
        "next": next.strip(),
        "pending": pending.strip(),
    }


def normalize_progress_summary(value: Any) -> dict[str, str]:
    """将任意输入收敛成稳定的摘要对象。"""

    if isinstance(value, dict):
        return build_progress_summary(
            done=str(value.get("done") or "").strip(),
            next=str(value.get("next") or "").strip(),
            pending=str(value.get("pending") or "").strip(),
        )
    if isinstance(value, str) and value.strip():
        return build_progress_summary(done=value, next="", pending="")
    return build_progress_summary(done="", next="", pending="")


def parse_structured_assistant_output(raw_output: Any) -> tuple[str, dict[str, str]]:
    """解析主助手结构化输出，失败时回退为纯文本答复。"""

    text = raw_output if isinstance(raw_output, str) else str(raw_output or "")
    stripped = text.strip()
    if not stripped:
        return "", build_progress_summary(done="", next="", pending="")

    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return (
            stripped,
            build_progress_summary(
                done="已生成当前回复",
                next="",
                pending="尚未提供结构化步骤摘要",
            ),
        )

    if not isinstance(payload, dict):
        return (
            stripped,
            build_progress_summary(
                done="已生成当前回复",
                next="",
                pending="结构化输出格式不符合预期",
            ),
        )

    answer = str(payload.get("answer") or payload.get("content") or "").strip()
    summary = normalize_progress_summary(payload.get("summary"))
    if not answer:
        answer = stripped
    if not any(summary.values()):
        summary = build_progress_summary(
            done="已生成当前回复",
            next="",
            pending="结构化输出中缺少步骤摘要",
        )
    return answer, summary
