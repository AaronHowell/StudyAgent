from __future__ import annotations

from typing import Any
from typing import TypedDict

from contracts import AgentTask

try:
    from langchain_core.messages import BaseMessage
except ImportError:  # pragma: no cover
    BaseMessage = Any  # type: ignore[assignment]


class PaperLabGraphState(TypedDict, total=False):
    """Message-ledger-first LangGraph state."""

    # LangGraph 消息账本，保存用户问题、上下文、任务、结果、循环状态和最终答案。
    messages: list[BaseMessage]
    # 当前用户问题归属的 turn id，用来把同一轮中的任务、结果和干预消息关联起来。
    active_turn_id: str
    # 当前会话线程的 Redis 锁 key，用于防止同一 thread 并发生成多个答案。
    thread_lock_key: str
    # 当前 turn 已经完成的主路由/专家执行迭代次数。
    iteration_count: int
    # 当前 turn 允许的最大迭代次数，达到后会进入最终综合而不再继续路由。
    max_iterations: int
    # 评估节点调用大模型判断现有专家结果是否足够支撑最终回答。
    answer_confident: bool
    # 停止继续迭代的原因，例如达到最大轮数或专家均无法完成。
    stop_reason: str
    # 本轮是否需要读取长期记忆。
    run_memory: bool
    # 记忆检索使用的查询。
    memory_query: str
    # 触发记忆检索的原因说明。
    memory_reason: str
    # 本轮分发给检索专家的任务；未启用检索时为 None。
    retrieve_task: AgentTask | None
    # 本轮分发给外部工具专家的任务；未启用工具检索时为 None。
    tool_task: AgentTask | None
    # 检索专家返回的结构化结果，通常包含摘要、置信度、引用和证据统计。
    retrieve_result: dict[str, Any] | None
    # 工具专家返回的结构化结果，通常包含外部来源、工具调用产物和置信度。
    tool_result: dict[str, Any] | None
    # 已经纳入当前 turn 处理的人类消息数量，用于区分新追加的用户干预。
    processed_human_message_count: int
    # 当前 turn 中已经捕获的用户干预消息数量，用于最终元数据和循环状态展示。
    intervention_count: int


class RetrieveAgentGraphState(TypedDict, total=False):
    # 父图传入的当前 turn id，用来给检索专家结果消息打上同一轮标识。
    active_turn_id: str
    # 检索专家需要执行的任务，包含检索 query、原因和召回限制等约束。
    retrieve_task: AgentTask | None
    # 检索专家执行后的结构化结果。
    retrieve_result: dict[str, Any] | None
    # 检索子图自己的消息账本，用于记录专家任务和结果消息。
    messages: list[BaseMessage]


class ToolAgentGraphState(TypedDict, total=False):
    # 父图传入的当前 turn id，用来给工具专家结果消息打上同一轮标识。
    active_turn_id: str
    # 工具专家需要执行的任务，包含外部/MCP 工具查询和执行原因。
    tool_task: AgentTask | None
    # 工具专家执行后的结构化结果。
    tool_result: dict[str, Any] | None
    # 工具子图自己的消息账本，用于记录工具选择和结果消息。
    messages: list[BaseMessage]
