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
        "Decide whether to dispatch memory recall, retrieval, and/or external tool specialists.",
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
        "Use each capability according to what kind of information is missing.\n"
        "- Memory recall is for prior user preferences, durable project facts, or earlier conversation conclusions.\n"
        "- Retrieval is for project-grounded information that should come from the local paper/document corpus, including document inventory, metadata, passages, figures, tables, and evidence-backed project state.\n"
        "- Tool specialist is for web or MCP-backed external information that is not expected to live in the local project corpus.\n"
        "- If local file tools are enabled later in the answer stage, use them directly instead of dispatching a workspace specialist.\n\n"
        "Route by information source and required grounding, not by surface phrasing alone.\n"
        "- If the user is asking what is currently known, what papers are available, what evidence has already been uploaded, or what the project corpus currently contains, retrieval is usually the correct source because the answer should be grounded in local documents even if the question sounds broad.\n"
        "- If short-term context and memory are thin but the answer could be established from project documents, prefer retrieval over guessing or looping without specialists.\n"
        "- If the answer can already be given from short-term context or memory, avoid unnecessary retrieval.\n\n"
        "For broad synthesis, comparison, survey, or research-landscape questions over multiple local papers:\n"
        "- Do not pass the user's high-level synthesis request to retrieval unchanged.\n"
        "- First decide what evidence fields are needed from the papers, such as research problem, method/system, main findings, limitations, and scope.\n"
        "- Then dispatch retrieval with a structured evidence-gathering task that asks for those fields, so the supervisor can do the final cross-paper synthesis itself.\n"
        "- Prefer one batched retrieval task with explicit evidence needs over many per-paper micro-tasks unless the user explicitly asks for paper-by-paper deep dives.\n\n"
        "Retrieval capacity notes:\n"
        "- Each retrieval call returns up to 5 text chunks and 6 visual assets (figures, tables). "
        "This limit is per-retrieval, not per-turn.\n"
        "- If the first retrieval does not cover enough ground, you can dispatch another retrieval task "
        "with a different query to gather additional evidence in the same turn.\n"
        "- Visual assets (figures, tables, diagrams) are retrieved alongside text chunks. "
        "When the question references figures, tables, or visual content, make sure to dispatch a retrieval task."
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
        "Do not include chain-of-thought or extra keys.\n\n"
        "Default to a useful, appropriately scoped answer based on the available grounded evidence. "
        "Do not over-investigate or expand the scope on your own just because deeper detail might exist. "
        "If the current evidence is enough for a solid overview, answer now and let the user decide whether to go deeper in a follow-up.\n\n"
        "When referencing figures, tables, or diagrams from the retrieved assets, "
        "use inline tags like <ref pic>A1</ref pic>, <ref pic>A2</ref pic>, etc. "
        "where the ref_id matches the asset's ref_id from the retrieval results. "
        "This allows the frontend to render the image inline with your answer."
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
        "Choose follow-up evidence tasks by the missing information source.\n"
        "- Ask for retrieval when the missing answer should come from the local project corpus, including broad project-state questions that need document-backed grounding.\n"
        "- Ask for memory recall only when the missing answer depends on prior conversation facts or durable user/project preferences.\n"
        "- Ask for external tool use only when the missing answer is not expected to be in local documents.\n"
        "For inventory/basic-info questions such as listing uploaded papers or document titles, document-level metadata is sufficient evidence; do not require chunk quotations or asset retrieval. "
        "For corpus-level thematic overviews, a document-level synthesis grounded in titles and summaries can also be sufficient when the user did not ask for passage-level proof. "
        "When the available specialist results already provide a coherent, grounded overview that directly addresses the user's scope, prefer answering now instead of requesting more evidence. Do not demand exhaustive per-document or passage-level support unless the user explicitly asks for it. "
        "Do not chase perfect completeness by default. If the current evidence is enough for a useful answer, stop and answer. Leave optional deeper investigation as a follow-up the user can request later. "
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
        "If a specialist already returned a useful completed portion plus only optional deeper follow-up in its progress summary or retrieval completion fields, treat that as sufficient and answer now. "
        "Do not request more evidence just because a deeper per-paper or per-passage exploration might still be possible. "
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
