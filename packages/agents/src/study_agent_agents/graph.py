"""StudyAgent LangGraph graph and helper functions."""

from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated
from typing import Any
from typing import TypedDict

from study_agent_application.answer_question_use_case import AnswerQuestionUseCase
from study_agent_domain import Citation
from study_agent_domain import EvidencePack

from study_agent_agents.runtime import AgentRuntime
from study_agent_agents.runtime import create_runtime
from study_agent_agents.settings import AgentSettings

try:
    from langchain_core.messages import AIMessage
    from langchain_core.messages import BaseMessage
    from langchain_core.messages import HumanMessage
    from langchain_core.runnables import RunnableConfig
    from langgraph.graph import END
    from langgraph.graph import START
    from langgraph.graph import StateGraph
    from langgraph.graph.message import add_messages
except ImportError:  # pragma: no cover - handled during dependency installation
    AIMessage = Any  # type: ignore[assignment]
    BaseMessage = Any  # type: ignore[assignment]
    HumanMessage = Any  # type: ignore[assignment]
    RunnableConfig = dict[str, Any]  # type: ignore[assignment]
    END = "__end__"
    START = "__start__"
    StateGraph = None  # type: ignore[assignment]
    add_messages = None  # type: ignore[assignment]


@dataclass(slots=True)
class AgentRequestConfig:
    """Normalized request settings resolved from LangGraph configurable values."""

    project_id: str = "default-project"
    document_limit: int = 5
    chunk_limit: int = 8
    asset_limit: int = 6


class StudyAgentGraphState(TypedDict, total=False):
    """Minimal LangGraph state for single-turn grounded QA."""

    messages: list[BaseMessage]
    citations: list[dict[str, object]]
    evidence_counts: dict[str, int]
    grounded_prompt: str


def resolve_agent_request_config(config: dict[str, Any] | None) -> AgentRequestConfig:
    """Normalize LangGraph configurable request values into one typed object."""

    configurable = (config or {}).get("configurable", {})
    project_id = str(
        configurable.get("project_id") or AgentSettings.from_env().default_project_id
    )
    return AgentRequestConfig(
        project_id=project_id,
        document_limit=_coerce_positive_int(configurable.get("document_limit"), 5),
        chunk_limit=_coerce_positive_int(configurable.get("chunk_limit"), 8),
        asset_limit=_coerce_positive_int(configurable.get("asset_limit"), 6),
    )


def build_assistant_metadata(citations: list[Citation]) -> dict[str, object]:
    """Serialize evidence citations into assistant-message metadata."""

    return {
        "citations": [
            {
                "document_id": citation.document_id,
                "document_title": citation.document_title,
                "chunk_id": citation.chunk_id,
                "page": citation.page,
                "locator": citation.locator,
            }
            for citation in citations
        ]
    }


def _coerce_positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _latest_human_text(messages: list[BaseMessage]) -> str:
    for message in reversed(messages):
        if hasattr(HumanMessage, "is_instance") and HumanMessage.is_instance(message):
            return _message_text(message.content)
        if getattr(message, "type", "") == "human":
            return _message_text(message.content)
    raise ValueError("No human message found in graph state")


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
    return str(content)


def _build_grounded_prompt(question: str, evidence_pack: EvidencePack) -> str:
    return AnswerQuestionUseCase._build_prompt(question, evidence_pack)


def _build_evidence_counts(evidence_pack: EvidencePack) -> dict[str, int]:
    return {
        "document_count": len(evidence_pack.documents),
        "chunk_count": len(evidence_pack.text_chunks),
        "asset_count": len(evidence_pack.assets),
    }


@lru_cache(maxsize=1)
def _runtime() -> AgentRuntime:
    return create_runtime()


def retrieve_evidence_node(
    state: StudyAgentGraphState,
    config: RunnableConfig | None = None,
) -> StudyAgentGraphState:
    """Retrieve grounding evidence for the latest user question."""

    request_config = resolve_agent_request_config(dict(config or {}))
    question = _latest_human_text(state.get("messages", []))
    evidence_pack = _runtime().retrieve_evidence_use_case.retrieve(
        query=question,
        project_id=request_config.project_id,
        document_limit=request_config.document_limit,
        chunk_limit=request_config.chunk_limit,
        asset_limit=request_config.asset_limit,
    )
    return {
        "citations": build_assistant_metadata(evidence_pack.citations)["citations"],
        "evidence_counts": _build_evidence_counts(evidence_pack),
        "grounded_prompt": _build_grounded_prompt(question, evidence_pack),
    }


async def answer_question_node(
    state: StudyAgentGraphState,
    _: RunnableConfig | None = None,
) -> StudyAgentGraphState:
    """Generate the final assistant message from grounded evidence."""

    grounded_prompt = state.get("grounded_prompt", "")
    if not grounded_prompt:
        raise ValueError("Grounded prompt missing from graph state")

    raw_answer = await _runtime().chat_model.ainvoke(grounded_prompt)
    answer_text = _message_text(raw_answer.content)
    metadata = {
        **build_assistant_metadata_from_state(state),
        "evidence_counts": state.get("evidence_counts", {}),
    }
    answer_message = AIMessage(
        content=answer_text,
        additional_kwargs=metadata,
        response_metadata=metadata,
        id=getattr(raw_answer, "id", None),
    )
    return {
        "messages": [answer_message],
    }


def build_assistant_metadata_from_state(state: StudyAgentGraphState) -> dict[str, object]:
    return {
        "citations": list(state.get("citations", [])),
    }


def build_graph():
    """Create the compiled StudyAgent LangGraph if LangGraph is installed."""

    if StateGraph is None or add_messages is None:
        return None

    class GraphState(TypedDict, total=False):
        messages: Annotated[list[BaseMessage], add_messages]
        citations: list[dict[str, object]]
        evidence_counts: dict[str, int]
        grounded_prompt: str

    builder = StateGraph(GraphState)
    builder.add_node("retrieve_evidence", retrieve_evidence_node)
    builder.add_node("answer_question", answer_question_node)
    builder.add_edge(START, "retrieve_evidence")
    builder.add_edge("retrieve_evidence", "answer_question")
    builder.add_edge("answer_question", END)
    return builder.compile()


graph = build_graph()
