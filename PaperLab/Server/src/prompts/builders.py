"""Centralized prompt builders for PaperLab."""

from __future__ import annotations

from typing import Iterable

from domain import EvidencePack


def build_grounded_answer_prompt(
    question: str,
    evidence_pack: EvidencePack,
    memory_summary: str = "",
) -> str:
    """Build the legacy grounded QA prompt from retrieved evidence."""

    document_lines = [
        f"- {index + 1}. {hit.title} ({hit.path})"
        for index, hit in enumerate(evidence_pack.documents)
    ]
    chunk_lines = [
        (
            f"[{index + 1}] {hit.text}\n"
            f"source: {hit.document_id} page={hit.page} section={hit.section or ''}".strip()
        )
        for index, hit in enumerate(evidence_pack.text_chunks)
    ]
    asset_lines = [
        (
            f"[A{index + 1}] {hit.caption or hit.summary or hit.asset_label}\n"
            f"source: {hit.document_id} page={hit.page_number}"
        )
        for index, hit in enumerate(evidence_pack.assets)
    ]

    return (
        "You are PaperLab. Answer only from the provided evidence.\n"
        "Rules:\n"
        "1. Do not invent facts not present in the evidence.\n"
        "2. When making a factual claim, cite it with [n] using the chunk references.\n"
        "3. If evidence is insufficient, say so clearly.\n\n"
        f"Question:\n{question}\n\n"
        f"Relevant memory:\n{memory_summary or '- none'}\n\n"
        f"Candidate documents:\n{chr(10).join(document_lines) or '- none'}\n\n"
        f"Text evidence:\n{chr(10).join(chunk_lines) or '- none'}\n\n"
        f"Asset evidence:\n{chr(10).join(asset_lines) or '- none'}\n"
    )


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
    synthesis_parts.append("Write one grounded answer using the strongest available evidence.")
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


