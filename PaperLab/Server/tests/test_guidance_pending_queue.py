from __future__ import annotations

from langchain_core.messages import HumanMessage
from langchain_core.messages import ToolMessage

from orchestration import supervisor


def _question() -> HumanMessage:
    return HumanMessage(
        content="原始问题",
        additional_kwargs={
            "name": "question",
            "metadata": {
                "artifact_type": "question",
                "turn_id": "turn-1",
                "project_id": "project-a",
                "thread_id": "thread-1",
            },
        },
    )


def test_materialize_intervention_update_consumes_resume_pending_messages() -> None:
    update = supervisor._materialize_intervention_update(
        state={
            "messages": [_question()],
            "active_turn_id": "turn-1",
            "processed_human_message_count": 1,
            "intervention_count": 0,
        },
        config={"configurable": {"project_id": "project-a", "thread_id": "thread-1"}},
        phase="guidance_gate_pre_assess",
        resume_value={
            "action": "continue_with_guidance",
            "pending_messages": [{"type": "human", "content": "请优先检查方法部分"}],
        },
    )

    messages = update["messages"]
    assert len(messages) == 2
    assert isinstance(messages[0], HumanMessage)
    assert messages[0].content == "请优先检查方法部分"
    assert messages[0].additional_kwargs["metadata"]["artifact_type"] == "intervention"
    assert isinstance(messages[1], ToolMessage)
    assert messages[1].additional_kwargs["metadata"]["guidance_messages"] == ["请优先检查方法部分"]
    assert update["intervention_count"] == 1
    assert update["processed_human_message_count"] == 2


def test_materialize_intervention_update_deduplicates_state_and_resume_guidance() -> None:
    pending = HumanMessage(content="请优先检查方法部分")

    update = supervisor._materialize_intervention_update(
        state={
            "messages": [_question(), pending],
            "active_turn_id": "turn-1",
            "processed_human_message_count": 1,
            "intervention_count": 0,
        },
        config={"configurable": {"project_id": "project-a", "thread_id": "thread-1"}},
        phase="guidance_gate_pre_route",
        resume_value={
            "action": "continue_with_guidance",
            "pending_messages": [{"type": "human", "content": "请优先检查方法部分"}],
        },
    )

    intervention_messages = [
        message
        for message in update["messages"]
        if getattr(message, "type", "") == "human"
        and message.additional_kwargs["metadata"]["artifact_type"] == "intervention"
    ]
    assert len(intervention_messages) == 1
    assert update["processed_human_message_count"] == 3
