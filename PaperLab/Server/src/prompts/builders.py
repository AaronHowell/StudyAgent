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
        "You are WorkspaceAgent. Choose exactly one workspace tool call. "
        "Repository access is read-only. Before running local commands or writing files, create a sandbox task. "
        "All mutable work must stay inside that task workspace.",
        f"Task query:\n{task_query}\n\nReason:\n{reason}",
    )


