from __future__ import annotations

from types import SimpleNamespace

from api.chat_turns import build_turns_from_messages
from api.chat_turns import build_trace_item


def test_build_turns_ignores_non_answer_ai_messages() -> None:
    messages = [
        SimpleNamespace(
            type="ai",
            id="msg-1",
            content='{"answer":"internal json"}',
            additional_kwargs={"metadata": {"artifact_type": "assessment_raw", "turn_id": "turn-1"}},
        ),
        SimpleNamespace(
            type="ai",
            id="msg-2",
            content="final answer",
            additional_kwargs={"metadata": {"artifact_type": "answer", "turn_id": "turn-1"}},
        ),
    ]

    turns = build_turns_from_messages(messages)

    assert len(turns) == 1
    assert turns[0].answer_text == "final answer"


def test_build_trace_item_maps_long_term_memory_labels() -> None:
    memory_read = SimpleNamespace(
        type="tool",
        id="msg-1",
        content="Relevant memory:\n- foo",
        additional_kwargs={"name": "search_memory", "metadata": {"artifact_type": "memory_result", "turn_id": "turn-1"}},
    )
    memory_write = SimpleNamespace(
        type="tool",
        id="msg-2",
        content="长期记忆写入决策：none",
        additional_kwargs={"name": "store_memory", "metadata": {"artifact_type": "memory_write_result", "turn_id": "turn-1"}},
    )

    read_item = build_trace_item(memory_read, index=0)
    write_item = build_trace_item(memory_write, index=1)

    assert read_item is not None
    assert write_item is not None
    assert read_item.title == "长期记忆检索"
    assert write_item.title == "长期记忆写入"
