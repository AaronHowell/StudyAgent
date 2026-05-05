"""Centralized prompt builders for PaperLab."""

from __future__ import annotations

from typing import Iterable

from domain import EvidencePack
from generation.message_builders import build_grounded_answer_prompt


def build_main_route_messages(
    *,
    question: str,
    short_term_context: str = "",
    memory_context: str = "",
    interventions: Iterable[str] = (),
    assessment_guidance: Iterable[str] = (),
) -> tuple[str, str]:
    """Build the coordinator routing prompt."""

    prompt_parts = [
        "Decide whether to dispatch retrieval, tool, and/or workspace specialists.",
        f"Question:\n{question}",
    ]
    if short_term_context:
        prompt_parts.append(f"Short-term context:\n{short_term_context}")
    if memory_context:
        prompt_parts.append(f"Relevant memory:\n{memory_context}")
    intervention_lines = [item for item in interventions if item]
    if intervention_lines:
        prompt_parts.append("New user guidance:\n" + "\n".join(f"- {item}" for item in intervention_lines))
    assessment_lines = [item for item in assessment_guidance if item]
    if assessment_lines:
        prompt_parts.append(
            "Assessment guidance from previous evidence review:\n"
            + "\n".join(f"- {item}" for item in assessment_lines)
        )
    prompt_parts.append(
        "Use retrieval for project-grounded paper evidence. "
        "Use the tool specialist for web or MCP-backed external information. "
        "Use the workspace specialist for repository files and local edits."
    )
    return (
        "You are the coordinator for weak speculative multi-agent dispatch.",
        "\n\n".join(prompt_parts),
    )


def build_synthesis_prompt(
    *,
    question: str,
    short_term_context: str = "",
    memory_context: str = "",
    interventions: Iterable[str] = (),
    specialist_payloads: Iterable[str] = (),
) -> str:
    """Build the final synthesis prompt."""

    synthesis_parts = [f"Question:\n{question}"]
    if short_term_context:
        synthesis_parts.append(f"Short-term context:\n{short_term_context}")
    if memory_context:
        synthesis_parts.append(f"Relevant memory:\n{memory_context}")
    intervention_lines = [item for item in interventions if item]
    if intervention_lines:
        synthesis_parts.append("New user guidance:\n" + "\n".join(f"- {item}" for item in intervention_lines))
    result_blocks = [payload for payload in specialist_payloads if payload]
    if result_blocks:
        synthesis_parts.append("Specialist results:\n" + "\n\n".join(result_blocks))
    synthesis_parts.append(
        "Return valid JSON with exactly two top-level keys: "
        "`answer` and `summary`. "
        "`answer` is the user-facing grounded reply. "
        "`summary` must be an object with string fields `done`, `next`, and `pending`. "
        "`done` should briefly state what this step completed. "
        "`next` should state the most useful next follow-up. "
        "`pending` should state what is still missing, uncertain, or not yet done. "
        "Do not include chain-of-thought or extra keys."
    )
    return "\n\n".join(synthesis_parts)


def build_answer_or_continue_prompt(
    *,
    question: str,
    short_term_context: str = "",
    memory_context: str = "",
    interventions: Iterable[str] = (),
    specialist_payloads: Iterable[str] = (),
    must_answer: bool = False,
) -> str:
    """Build the combined answer-or-loop prompt."""

    prompt_parts = [
        "Decide whether the available specialist evidence is enough to answer the user's question.",
        f"Question:\n{question}",
    ]
    if short_term_context:
        prompt_parts.append(f"Short-term context:\n{short_term_context}")
    if memory_context:
        prompt_parts.append(f"Relevant memory:\n{memory_context}")
    intervention_lines = [item for item in interventions if item]
    if intervention_lines:
        prompt_parts.append("New user guidance:\n" + "\n".join(f"- {item}" for item in intervention_lines))
    result_blocks = [payload for payload in specialist_payloads if payload]
    if result_blocks:
        prompt_parts.append("Specialist results:\n" + "\n\n".join(result_blocks))
    if must_answer:
        prompt_parts.append(
            "The loop has reached its stop condition. Provide the best grounded answer possible, "
            "clearly naming any missing or uncertain evidence."
        )
    prompt_parts.append(
        "If evidence is enough, return valid JSON with exactly four top-level keys: "
        "`answer_confident`, `answer`, `summary`, and `next_tasks`; set `answer_confident` to true, "
        "put the user-facing grounded reply in `answer`, put an object with string fields "
        "`done`, `next`, and `pending` in `summary`, and set `next_tasks` to an empty list. "
        "If evidence is insufficient and the loop can continue, do not answer; call the virtual "
        "`continue_evidence_loop` tool with a reason and concrete follow-up evidence tasks. "
        "Do not include chain-of-thought or extra keys."
    )
    return "\n\n".join(prompt_parts)


def build_assessment_prompt(
    *,
    question: str,
    short_term_context: str = "",
    memory_context: str = "",
    interventions: Iterable[str] = (),
    specialist_payloads: Iterable[str] = (),
) -> str:
    """Build the evidence sufficiency assessment prompt."""

    assessment_parts = [
        "Decide whether the available specialist evidence is enough to answer the question.",
        f"Question:\n{question}",
    ]
    if short_term_context:
        assessment_parts.append(f"Short-term context:\n{short_term_context}")
    if memory_context:
        assessment_parts.append(f"Relevant memory:\n{memory_context}")
    intervention_lines = [item for item in interventions if item]
    if intervention_lines:
        assessment_parts.append("New user guidance:\n" + "\n".join(f"- {item}" for item in intervention_lines))
    result_blocks = [payload for payload in specialist_payloads if payload]
    if result_blocks:
        assessment_parts.append("Specialist results:\n" + "\n\n".join(result_blocks))
    assessment_parts.append(
        "Return valid JSON with exactly two top-level keys: "
        "`answer_confident` and `next_tasks`. "
        "`answer_confident` must be true only when the evidence is sufficient for final synthesis. "
        "`next_tasks` must be an empty list when `answer_confident` is true. "
        "When evidence is insufficient, set `answer_confident` to false and put concrete follow-up evidence-gathering tasks in `next_tasks`. "
        "Do not include chain-of-thought or extra keys."
    )
    return "\n\n".join(assessment_parts)


def build_tool_agent_selection_messages(*, task_query: str, reason: str) -> tuple[str, str]:
    """Build the ToolAgent tool-selection prompt."""

    return (
        "Select exactly one tool for ToolAgent.",
        "You are ToolAgent. Choose exactly one tool call that best advances the task.\n\n"
        f"Task query:\n{task_query}\n\n"
        f"Reason:\n{reason}",
    )


def build_workspace_agent_selection_messages(*, task_query: str, reason: str) -> tuple[str, str]:
    """Build the WorkspaceAgent action-selection prompt."""

    return (
        "You are WorkspaceAgent, a goal-driven implementation specialist. "
        "Choose exactly one workspace action for the current implementation step. "
        "Use list/read/search for inspection. Use write/run only inside the provided sandbox task. "
        "Use finish only when acceptance criteria are met or a blocker prevents further progress.",
        f"Task query and implementation state:\n{task_query}\n\nReason:\n{reason}",
    )


