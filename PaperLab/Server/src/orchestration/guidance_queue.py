"""Thread-scoped guidance queue for non-blocking user intervention."""

from __future__ import annotations

from collections import defaultdict
from threading import Lock


_lock = Lock()
_queues: dict[tuple[str, str], list[str]] = defaultdict(list)


def push_guidance_message(*, project_id: str, thread_id: str, content: str) -> None:
    normalized = content.strip()
    if not normalized:
        return
    key = (_normalize_key(project_id), _normalize_key(thread_id))
    with _lock:
        _queues[key].append(normalized)


def pop_guidance_messages(*, project_id: str, thread_id: str) -> list[str]:
    key = (_normalize_key(project_id), _normalize_key(thread_id))
    with _lock:
        messages = list(_queues.pop(key, []))
    return messages


def _normalize_key(value: str) -> str:
    return str(value or "").strip() or "default"
