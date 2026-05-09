from __future__ import annotations

from pathlib import Path

from domain import MemoryType
from integrations.storage.markdown_memory_store import MarkdownMemoryWriteDecision
from integrations.storage.markdown_memory_store import MarkdownMemoryStore


class _RecordingSelector:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[dict[str, str]] = []

    def select(self, *, query: str, memory_markdown: str) -> str:
        self.calls.append({"query": query, "memory_markdown": memory_markdown})
        return self.response


class _RecordingWriteManager:
    def __init__(self, decision: MarkdownMemoryWriteDecision) -> None:
        self.decision = decision
        self.calls: list[dict[str, str]] = []

    def decide(
        self,
        *,
        query: str,
        memory_markdown: str,
        candidate_content: str,
        memory_type: MemoryType,
    ) -> MarkdownMemoryWriteDecision:
        self.calls.append(
            {
                "query": query,
                "memory_markdown": memory_markdown,
                "candidate_content": candidate_content,
                "memory_type": memory_type.value,
            }
        )
        return self.decision


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


def test_markdown_memory_store_write_manager_can_skip_candidate(tmp_path: Path) -> None:
    manager = _RecordingWriteManager(
        MarkdownMemoryWriteDecision(action="skip", content="", reason="Duplicate durable preference."),
    )
    store = MarkdownMemoryStore(root_path=tmp_path, write_manager=manager)

    stored = store.remember_messages(
        project_id="project-a",
        messages=[{"role": "assistant", "content": "以后称呼用户为 AaronHowell"}],
        memory_type=MemoryType.PREFERENCE,
        metadata={"source_question": "我叫 AaronHowell"},
    )

    assert stored == []
    assert not (tmp_path / "project-a" / "memory.md").exists()
    assert manager.calls[0]["candidate_content"] == "以后称呼用户为 AaronHowell"


def test_markdown_memory_store_write_manager_can_merge_candidate(tmp_path: Path) -> None:
    manager = _RecordingWriteManager(
        MarkdownMemoryWriteDecision(
            action="merge",
            content="用户偏好被称呼为 AaronHowell；主要研究方向为模糊测试与软件安全。",
            reason="Merged durable preference and direction.",
        ),
    )
    store = MarkdownMemoryStore(root_path=tmp_path, write_manager=manager)

    stored = store.remember_messages(
        project_id="project-a",
        messages=[{"role": "assistant", "content": "以后称呼用户为 Aaron Howell，研究方向是模糊测试和软件安全"}],
        memory_type=MemoryType.PREFERENCE,
        metadata={"source_question": "我叫 AaronHowell，以后研究方向是模糊测试和软件安全"},
    )

    content = (tmp_path / "project-a" / "memory.md").read_text(encoding="utf-8")
    assert len(stored) == 1
    assert "用户偏好被称呼为 AaronHowell；主要研究方向为模糊测试与软件安全。" in content
