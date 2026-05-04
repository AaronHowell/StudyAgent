"""Markdown-backed long-term memory store."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
from pathlib import Path
import re
from typing import Any, Protocol

from domain import MemoryItem, MemoryType


MEMORY_TEMPLATE = """# PaperLab Memory

## Preferences

## Project Facts

## Research Episodes
"""


SECTION_BY_TYPE = {
    MemoryType.PREFERENCE: "Preferences",
    MemoryType.PROJECT_FACT: "Project Facts",
    MemoryType.RESEARCH_EPISODE: "Research Episodes",
}


class MarkdownMemorySelector(Protocol):
    """Select relevant memory from raw markdown for one clean user query."""

    def select(self, *, query: str, memory_markdown: str) -> str:
        """Return a short relevant-memory markdown snippet."""


@dataclass(slots=True)
class ChatModelMarkdownMemorySelector:
    """LLM selector that receives only the current query and raw memory markdown."""

    chat_model: Any

    def select(self, *, query: str, memory_markdown: str) -> str:
        if not memory_markdown.strip():
            return ""
        prompt = (
            "You select long-term memory for the current answer.\n"
            "Be conservative. Return only memory entries that are directly useful for this user request.\n"
            "Return at most 5 bullets. If nothing is relevant, return exactly: Relevant memory:\\n- none\n"
            "Do not answer the user's request. Do not infer new facts. Do not include unrelated memory.\n\n"
            f"User request:\n{query}\n\n"
            f"Full memory.md:\n{memory_markdown}"
        )
        response = self.chat_model.invoke(prompt)
        return _message_text(getattr(response, "content", response))


class MarkdownMemoryStore:
    """Project-scoped local memory saved as append-only ``memory.md`` files."""

    def __init__(
        self,
        *,
        root_path: str | Path,
        selector: MarkdownMemorySelector | None = None,
    ) -> None:
        self.root_path = Path(root_path)
        self.selector = selector

    def remember_messages(
        self,
        *,
        project_id: str,
        messages: list[dict[str, str]],
        thread_id: str | None = None,
        memory_type: MemoryType | str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> list[MemoryItem]:
        del thread_id
        resolved_type = _coerce_memory_type(memory_type)
        content = _memory_content_from_messages(messages)
        if not content:
            return []

        memory_file = self._memory_file(project_id)
        existing = self._read_memory(memory_file)
        if _contains_memory(existing, content):
            return []

        memory_file.parent.mkdir(parents=True, exist_ok=True)
        updated = _append_entry(
            existing or MEMORY_TEMPLATE,
            memory_type=resolved_type,
            content=content,
            today=date.today().isoformat(),
        )
        memory_file.write_text(updated, encoding="utf-8")
        item = _build_item(project_id, resolved_type, content, metadata or {})
        return [item]

    def search(self, query: str, project_id: str, limit: int = 5) -> list[MemoryItem]:
        memory_markdown = self._read_memory(self._memory_file(project_id))
        if not memory_markdown.strip():
            return []
        selected = (
            self.selector.select(query=query, memory_markdown=memory_markdown)
            if self.selector is not None
            else memory_markdown
        )
        return [
            _build_item(project_id, MemoryType.RESEARCH_EPISODE, content, {"source": "memory.md"})
            for content in _extract_bullets(selected)[: max(0, limit)]
        ]

    def summarize_for_project(self, project_id: str) -> str:
        del project_id
        return ""

    def _memory_file(self, project_id: str) -> Path:
        safe_project_id = _safe_project_id(project_id)
        return self.root_path / safe_project_id / "memory.md"

    @staticmethod
    def _read_memory(memory_file: Path) -> str:
        if not memory_file.exists():
            return ""
        return memory_file.read_text(encoding="utf-8")


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return "".join(parts)
    return str(content or "")


def _safe_project_id(project_id: str) -> str:
    value = (project_id or "default-project").strip() or "default-project"
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._") or "default-project"


def _coerce_memory_type(value: MemoryType | str | None) -> MemoryType:
    if isinstance(value, MemoryType):
        return value
    if isinstance(value, str):
        try:
            return MemoryType(value)
        except ValueError:
            return MemoryType.RESEARCH_EPISODE
    return MemoryType.RESEARCH_EPISODE


def _memory_content_from_messages(messages: list[dict[str, str]]) -> str:
    for message in reversed(messages):
        content = str(message.get("content") or "").strip()
        if content:
            return _normalize_entry_content(content)
    return ""


def _normalize_entry_content(content: str) -> str:
    return re.sub(r"\s+", " ", content).strip(" -\t\r\n")


def _contains_memory(memory_markdown: str, content: str) -> bool:
    normalized_existing = _normalize_entry_content(memory_markdown).casefold()
    normalized_content = _normalize_entry_content(content).casefold()
    return bool(normalized_content) and normalized_content in normalized_existing


def _append_entry(
    memory_markdown: str,
    *,
    memory_type: MemoryType,
    content: str,
    today: str,
) -> str:
    section = SECTION_BY_TYPE[memory_type]
    entry = f"- {today}: {content}"
    heading = f"## {section}"
    if heading not in memory_markdown:
        memory_markdown = memory_markdown.rstrip() + f"\n\n{heading}\n"
    pattern = re.compile(rf"(^## {re.escape(section)}\n)", re.MULTILINE)
    match = pattern.search(memory_markdown)
    if match is None:
        return memory_markdown.rstrip() + f"\n{entry}\n"
    insert_at = match.end()
    return memory_markdown[:insert_at] + f"{entry}\n" + memory_markdown[insert_at:]


def _extract_bullets(text: str) -> list[str]:
    bullets: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue
        content = _normalize_entry_content(stripped.removeprefix("- "))
        if not content or content.casefold() == "none":
            continue
        content = re.sub(r"^\d{4}-\d{2}-\d{2}:\s*", "", content)
        bullets.append(content)
    return bullets


def _build_item(
    project_id: str,
    memory_type: MemoryType,
    content: str,
    metadata: dict[str, Any],
) -> MemoryItem:
    digest = hashlib.sha1(f"{project_id}:{memory_type.value}:{content}".encode("utf-8")).hexdigest()
    return MemoryItem(
        id=f"md_{digest[:12]}",
        project_id=project_id,
        memory_type=memory_type,
        content=content,
        importance=1.0,
        metadata=dict(metadata),
    )
