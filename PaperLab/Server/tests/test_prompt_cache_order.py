from __future__ import annotations

from contracts import AgentTask
from integrations.storage.markdown_memory_store import ChatModelMarkdownMemorySelector
from integrations.storage.markdown_memory_store import ChatModelMarkdownMemoryWriteManager
from domain import MemoryType
from prompts.builders import build_answer_or_continue_prompt
from prompts.builders import build_main_route_messages
from prompts.builders import build_synthesis_prompt
from workers.retriever.agent import _build_retrieval_execution_instruction
from workers.retriever.agent import _build_retrieval_planning_messages
from workers.retriever.agent import _RetrievalIntentPlan


class _RecordingChatModel:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def invoke(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return "Relevant memory:\n- none"


def _assert_before(text: str, earlier: str, later: str) -> None:
    assert text.index(earlier) < text.index(later)


def test_supervisor_prompts_place_stable_instructions_before_dynamic_payload() -> None:
    _system, route_prompt = build_main_route_messages(
        question="What changed?",
        short_term_context="recent turn",
        memory_context="remembered fact",
    )
    _assert_before(route_prompt, "Use each capability according to what kind of information is missing.", "Question:")

    synthesis_prompt = build_synthesis_prompt(
        question="What changed?",
        short_term_context="recent turn",
        memory_context="remembered fact",
        specialist_payloads=["retrieval result"],
    )
    _assert_before(synthesis_prompt, "Return valid JSON with exactly two top-level keys", "Question:")

    answer_or_loop_prompt = build_answer_or_continue_prompt(
        question="What changed?",
        short_term_context="recent turn",
        memory_context="remembered fact",
        specialist_payloads=["retrieval result"],
    )
    _assert_before(answer_or_loop_prompt, "If evidence is enough, return valid JSON", "Question:")


def test_retriever_prompts_place_schema_and_rules_before_task_payload() -> None:
    task = AgentTask(
        task_id="task-1",
        task_type="local_retrieval",
        agent_name="retrieval_agent",
        query="Find uploaded paper titles",
        reason="Need local document inventory.",
        constraints={},
        metadata={},
    )
    planning_messages = _build_retrieval_planning_messages(task=task)
    planning_system = planning_messages[0].content
    planning_human = planning_messages[1].content

    assert "Return valid JSON with exactly these keys" in planning_system
    assert "Task query:" not in planning_system
    assert planning_human.startswith("Dynamic retrieval task:")

    instruction = _build_retrieval_execution_instruction(
        plan=_RetrievalIntentPlan(target_level="document")
    )
    _assert_before(instruction, "Follow this plan strictly.", "Approved retrieval plan:")


def test_markdown_memory_prompts_place_policy_before_dynamic_payload() -> None:
    model = _RecordingChatModel()
    selector = ChatModelMarkdownMemorySelector(chat_model=model)
    selector.select(query="current question", memory_markdown="- stable preference")
    selector_prompt = model.prompts[-1]
    _assert_before(selector_prompt, "Do not answer the user's request.", "User request:")

    write_manager = ChatModelMarkdownMemoryWriteManager(chat_model=model)
    write_manager.decide(
        query="current question",
        memory_markdown="- stable preference",
        candidate_content="User prefers concise answers.",
        memory_type=MemoryType.PREFERENCE,
    )
    write_prompt = model.prompts[-1]
    _assert_before(write_prompt, "Store if it is a new durable preference", "Memory type:")
