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
    disabled_capabilities: Iterable[str] = (),
) -> tuple[str, str]:
    """Build the coordinator routing prompt."""

    instruction_parts = [
        "决定是否需要调用记忆回忆或文档检索专家。",
    ]
    disabled_list = [item for item in disabled_capabilities if item]
    if disabled_list:
        instruction_parts.append(
            "当前工具权限状态：\n" + "\n".join(disabled_list)
        )
    instruction_parts.append(
        "根据缺失的信息类型选择合适的工具：\n"
        "- 记忆回忆：用于找回用户偏好、持久化的项目事实、之前的对话结论。\n"
        "- 文档检索：用于从本地论文/文档库中获取基于证据的信息，包括文档清单、元数据、段落、图表等。\n\n"
        "【重要】文档检索 vs 工作区文件工具：\n"
        "- 文档检索：搜索学术论文/文档库（PDF 论文、研究文档）。\n"
        "- 工作区文件工具（read_file, write_file, list_files, search_text, run_command 等）：操作本地文件系统。\n"
        "- 当用户要求'查看工作区'、'读取文件'、'写入文件'、'列出文件'、'查看文件内容'、'往文件里写入'等文件系统操作时，不要派发检索。\n"
        "- 这些由 supervisor 直接处理，设置 run_retrieval=false。\n"
        "- 只有当用户需要论文/文档库中的信息（论文、文献、研究）时才派发检索。\n\n"
        "【重要】工具/MCP 相关查询 vs 文档检索：\n"
        "- 当用户问'MCP情况如何'、'有哪些MCP工具'、'工具状态'、'有什么可用工具'、'tool search'等，"
        "是在询问系统当前可用的工具，不是在搜索论文。设置 run_retrieval=false，由 supervisor 通过 tool_search 处理。\n"
        "- 只有当用户明确问'MCP相关论文'、'MCP协议的研究'等学术问题时才派发检索。\n\n"
        "根据信息来源和所需依据来路由，不要仅凭表面措辞判断。\n"
        "- 如果用户问当前已知什么、有哪些论文、已上传哪些证据、项目库包含什么，检索通常是正确的来源。\n"
        "- 如果短时上下文和记忆都很薄，但答案可以从项目文档中获取，优先检索而非猜测。\n"
        "- 如果短时上下文或记忆已经足够回答，避免不必要的检索。\n\n"
        "对于多篇论文的综合、比较、综述类问题：\n"
        "- 不要直接把用户的高层综合请求原封不动传给检索。\n"
        "- 先判断需要从论文中获取哪些证据字段（如研究问题、方法/系统、主要发现、局限性、范围）。\n"
        "- 然后派发结构化的证据收集任务，让 supervisor 自己做最终的跨论文综合。\n"
        "- 优先一个批量检索任务，除非用户明确要求逐篇深入。\n\n"
        "检索能力说明：\n"
        "- 每次检索最多返回 5 个文本块和 6 个视觉资源（图表）。此限制是每次检索的，不是每轮的。\n"
        "- 如果第一次检索覆盖不够，可以在同一轮派发另一个检索任务。\n"
        "- 视觉资源（图表、表格、示意图）与文本块一起检索。当问题涉及图表或视觉内容时，确保派发检索任务。"
    )
    dynamic_parts = [
        "请求信息：",
        f"用户问题：\n{question}",
    ]
    if short_term_context:
        dynamic_parts.append(f"短时上下文：\n{short_term_context}")
    if memory_context:
        dynamic_parts.append(f"相关记忆：\n{memory_context}")
    intervention_lines = [item for item in interventions if item]
    if intervention_lines:
        dynamic_parts.append("用户新指令：\n" + "\n".join(f"- {item}" for item in intervention_lines))
    assessment_lines = [item for item in assessment_guidance if item]
    if assessment_lines:
        dynamic_parts.append(
            "上一轮证据审查的评估指导：\n"
            + "\n".join(f"- {item}" for item in assessment_lines)
        )
    return (
        "你是多 Agent 调度的协调者。",
        "\n\n".join([*instruction_parts, *dynamic_parts]),
    )


def build_synthesis_prompt(
    *,
    question: str,
    short_term_context: str = "",
    memory_context: str = "",
    interventions: Iterable[str] = (),
    specialist_payloads: Iterable[str] = (),
    assessment_guidance: Iterable[str] = (),
) -> str:
    """Build the final synthesis prompt."""

    instruction_parts = [
        "请返回包含两个顶层字段的 JSON：`answer` 和 `summary`。\n"
        "`answer` 是面向用户的回答。\n"
        "`summary` 必须是一个对象，包含字符串字段 `done`、`next` 和 `pending`。\n"
        "`done` 简述本轮完成了什么。\n"
        "`next` 指出最有价值的后续方向。\n"
        "`pending` 说明还有哪些不确定或未完成的部分。\n"
        "不要包含思维链或其他额外字段。\n\n"
        "基于现有证据给出适当范围的回答，不要过度扩展范围。"
        "如果当前证据足够给出完整概览，直接回答，让用户决定是否需要深入。\n\n"
        "引用图表时使用行内标签，如 <ref pic>A1</ref pic>、<ref pic>A2</ref pic>。\n"
        "请用中文回答用户的问题。"
    ]
    synthesis_parts = ["综合信息：", f"用户问题：\n{question}"]
    if short_term_context:
        synthesis_parts.append(f"短时上下文：\n{short_term_context}")
    if memory_context:
        synthesis_parts.append(f"相关记忆：\n{memory_context}")
    intervention_lines = [item for item in interventions if item]
    if intervention_lines:
        synthesis_parts.append("用户新指令：\n" + "\n".join(f"- {item}" for item in intervention_lines))
    guidance_lines = [item for item in assessment_guidance if item]
    if guidance_lines:
        synthesis_parts.append(
            "如果证据仍不完整，基于现有证据给出最佳部分结论，"
            "并明确指出最有价值的深入调查方向：\n"
            + "\n".join(f"- {item}" for item in guidance_lines)
        )
    result_blocks = [payload for payload in specialist_payloads if payload]
    if result_blocks:
        synthesis_parts.append("专家结果：\n" + "\n\n".join(result_blocks))
    return "\n\n".join([*instruction_parts, *synthesis_parts])


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

    instruction_parts = [
        "判断现有专家证据是否足以回答用户的问题。",
    ]
    instruction_parts.append(
        "如果证据足够，返回包含四个顶层字段的 JSON："
        "`answer_confident`、`answer`、`summary` 和 `next_tasks`；"
        "将 `answer_confident` 设为 true，`answer` 中放面向用户的回答，"
        "`summary` 中放包含 `done`、`next`、`pending` 字段的对象，`next_tasks` 设为空列表。\n"
        "如果证据不足且可以继续循环，不要回答；调用虚拟工具 `continue_evidence_loop`，"
        "给出原因和具体的后续证据任务。\n"
        "根据缺失信息来源选择后续任务：\n"
        "- 缺失答案应来自本地项目库时，请求检索。\n"
        "- 缺失答案依赖于之前的对话事实或持久化偏好时，请求记忆回忆。\n"
        "对于清单/基本信息类问题（如列出已上传论文或文档标题），文档级元数据即为充分证据。\n"
        "当专家结果已提供连贯、有依据的概览时，优先回答而非请求更多证据。\n"
        "不要默认追求完美完整性。当前证据足够就直接回答，深入调查留给用户后续请求。\n"
        "不要包含思维链或其他额外字段。"
    )
    dynamic_parts = ["回答或继续循环信息：", f"用户问题：\n{question}"]
    if short_term_context:
        dynamic_parts.append(f"短时上下文：\n{short_term_context}")
    if memory_context:
        dynamic_parts.append(f"相关记忆：\n{memory_context}")
    intervention_lines = [item for item in interventions if item]
    if intervention_lines:
        dynamic_parts.append("用户新指令：\n" + "\n".join(f"- {item}" for item in intervention_lines))
    result_blocks = [payload for payload in specialist_payloads if payload]
    if result_blocks:
        dynamic_parts.append("专家结果：\n" + "\n\n".join(result_blocks))
    if must_answer:
        dynamic_parts.append(
            "已达到循环停止条件。请基于现有证据给出最佳回答，明确指出不确定或缺失的部分。"
        )
    return "\n\n".join([*instruction_parts, *dynamic_parts])


def build_tool_agent_selection_messages(
    *,
    task_query: str,
    reason: str,
    available_tools: list[dict[str, object]],
    max_tools: int,
    already_exposed_tools: list[str] | None = None,
) -> tuple[str, str]:
    """Build the ToolAgent tool-selection prompt."""

    return (
        "为 supervisor 选择一组最相关的工具。",
        "你是工具选择器。不要执行工具，只选择最相关的工具供 supervisor 考虑。\n"
        f"最多返回 {max_tools} 个工具。\n"
        "必须包含终止原因：\n"
        "- `completed`：返回的工具足够当前任务使用\n"
        "- `more_available`：因数量限制停止，还有更多工具可用\n"
        "- `no_match`：没有匹配的工具\n\n"
        "工具选择任务：\n"
        f"任务查询：\n{task_query}\n\n"
        f"原因：\n{reason}\n\n"
        f"已暴露的工具：\n{already_exposed_tools or []}\n\n"
        f"可用工具：\n{available_tools}",
    )
