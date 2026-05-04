from __future__ import annotations

from pathlib import Path

from domain import MemoryType
from integrations.storage.markdown_memory_store import MarkdownMemoryStore


class _RecordingSelector:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[dict[str, str]] = []

    def select(self, *, query: str, memory_markdown: str) -> str:
        self.calls.append({"query": query, "memory_markdown": memory_markdown})
        return self.response


def test_markdown_memory_store_treats_missing_file_as_empty(tmp_path: Path) -> None:
    store = MarkdownMemoryStore(root_path=tmp_path)

    assert store.search("anything", project_id="project-a", limit=5) == []
    assert store.summarize_for_project("project-a") == ""


def test_markdown_memory_store_creates_project_memory_file(tmp_path: Path) -> None:
    store = MarkdownMemoryStore(root_path=tmp_path)

    stored = store.remember_messages(
        project_id="project-a",
        thread_id="thread-1",
        messages=[{"role": "assistant", "content": "用户偏好简洁回答"}],
        memory_type=MemoryType.PREFERENCE,
        metadata={},
    )

    memory_file = tmp_path / "project-a" / "memory.md"
    assert len(stored) == 1
    assert memory_file.exists()
    assert "## Preferences" in memory_file.read_text(encoding="utf-8")
    assert "用户偏好简洁回答" in memory_file.read_text(encoding="utf-8")


def test_markdown_memory_store_keeps_projects_isolated(tmp_path: Path) -> None:
    store = MarkdownMemoryStore(root_path=tmp_path)

    store.remember_messages(
        project_id="project-a",
        messages=[{"role": "assistant", "content": "A memory"}],
        memory_type=MemoryType.PROJECT_FACT,
    )
    store.remember_messages(
        project_id="project-b",
        messages=[{"role": "assistant", "content": "B memory"}],
        memory_type=MemoryType.PROJECT_FACT,
    )

    assert "A memory" in (tmp_path / "project-a" / "memory.md").read_text(encoding="utf-8")
    assert "B memory" in (tmp_path / "project-b" / "memory.md").read_text(encoding="utf-8")
    assert "B memory" not in (tmp_path / "project-a" / "memory.md").read_text(encoding="utf-8")


def test_markdown_memory_store_skips_empty_and_duplicate_entries(tmp_path: Path) -> None:
    store = MarkdownMemoryStore(root_path=tmp_path)

    first = store.remember_messages(
        project_id="project-a",
        messages=[{"role": "assistant", "content": "Stable project fact"}],
        memory_type=MemoryType.PROJECT_FACT,
    )
    second = store.remember_messages(
        project_id="project-a",
        messages=[{"role": "assistant", "content": "Stable project fact"}],
        memory_type=MemoryType.PROJECT_FACT,
    )
    empty = store.remember_messages(
        project_id="project-a",
        messages=[{"role": "assistant", "content": "   "}],
        memory_type=MemoryType.PROJECT_FACT,
    )

    content = (tmp_path / "project-a" / "memory.md").read_text(encoding="utf-8")
    assert len(first) == 1
    assert second == []
    assert empty == []
    assert content.count("Stable project fact") == 1


def test_markdown_memory_store_uses_clean_selector_input(tmp_path: Path) -> None:
    selector = _RecordingSelector("Relevant memory:\n- Use short answers")
    store = MarkdownMemoryStore(root_path=tmp_path, selector=selector)
    store.remember_messages(
        project_id="project-a",
        messages=[{"role": "assistant", "content": "Use short answers"}],
        memory_type=MemoryType.PREFERENCE,
    )

    hits = store.search("How should you answer?", project_id="project-a", limit=5)

    assert len(hits) == 1
    assert hits[0].content == "Use short answers"
    assert selector.calls == [
        {
            "query": "How should you answer?",
            "memory_markdown": (tmp_path / "project-a" / "memory.md").read_text(encoding="utf-8"),
        }
    ]
