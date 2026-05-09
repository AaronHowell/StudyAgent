"""Coding Agent 主循环 — 读论文 → 规划 → 写代码 → 执行 → 修复。"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

from agent.llm_client import LLMClient
from agent.state import AgentAction, AgentPhase, AgentState
from configs.settings import Settings
from container.manager import ContainerManager, SandboxSession
from tools.executor import build_executor_tools
from tools.file_ops import build_file_tools
from tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a research paper reproduction agent. Your job is to reproduce the experiments described in a research paper by writing and executing code inside a Docker sandbox.

## Capabilities
- Read/write/edit files in the sandbox
- Run shell commands and Python scripts
- Install Python packages
- Search through code

## Workflow
1. First, understand the paper's methodology from the provided context
2. Create a reproduction plan (what to implement, what data to use, what metrics to measure)
3. Write the implementation code step by step
4. Execute and test each component
5. If errors occur, analyze them and fix the code
6. Produce a final report comparing your results with the paper's claims

## Rules
- Always write clean, well-commented code
- Start with minimal viable implementations, then iterate
- When something fails, read the error carefully before attempting a fix
- Keep the user informed of your progress
- If you're stuck, explain what you've tried and ask for guidance

## Output Format
For each step, explain your reasoning, then call the appropriate tool.
When you're done, call `finish` with a summary of what was accomplished.
"""


class CodingAgentLoop:
    """Coding Agent 的核心循环。"""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        llm: LLMClient | None = None,
        container_mgr: ContainerManager | None = None,
        on_action: Any = None,           # 回调：新动作（用于 SSE 推送）
        on_approval: Any = None,         # 回调：需要审批
        on_message: Any = None,          # 回调：消息更新
    ) -> None:
        self.settings = settings or Settings()
        self.llm = llm or LLMClient(self.settings)
        self.container_mgr = container_mgr or ContainerManager(self.settings)
        self.on_action = on_action
        self.on_approval = on_approval
        self.on_message = on_message
        self._sessions: dict[str, tuple[AgentState, SandboxSession, ToolRegistry]] = {}

    def create_session(
        self,
        session_id: str | None = None,
        paper_context: str = "",
    ) -> tuple[AgentState, SandboxSession]:
        """创建一个新的 coding 会话。"""
        sid = session_id or f"code-{uuid.uuid4().hex[:8]}"
        sandbox = self.container_mgr.create_session(sid)
        state = AgentState(session_id=sid, paper_context=paper_context)

        # 构建工具集
        registry = ToolRegistry()
        for tool in build_file_tools(self.container_mgr, sandbox):
            registry.register(tool)
        for tool in build_executor_tools(self.container_mgr, sandbox):
            registry.register(tool)

        # 注册 finish 工具
        registry.register(self._build_finish_tool(state))

        self._sessions[sid] = (state, sandbox, registry)
        return state, sandbox

    async def step(self, session_id: str) -> AgentState:
        """执行一步 Agent 循环。返回当前状态。"""
        state, sandbox, registry = self._sessions[session_id]
        state.iteration += 1

        if state.iteration > self.settings.max_iterations:
            state.phase = AgentPhase.FAILED
            state.error = f"超过最大迭代次数 ({self.settings.max_iterations})"
            return state

        # ── 构建消息 ──
        messages = self._build_messages(state)

        # ── 调用 LLM ──
        try:
            response = await self.llm.chat(
                messages=messages,
                tools=registry.to_schemas(),
            )
        except Exception as e:
            state.phase = AgentPhase.FAILED
            state.error = f"LLM 调用失败: {e}"
            return state

        # ── 处理回复 ──
        content = response.get("content", "")
        tool_calls = response.get("tool_calls", [])

        if content:
            await self._emit_message(session_id, content, "assistant")

        if not tool_calls:
            # LLM 没有调用工具，可能在思考或已完成
            if state.phase == AgentPhase.INIT:
                state.phase = AgentPhase.PLANNING
            return state

        # ── 处理工具调用 ──
        for call in tool_calls:
            func = call.get("function", {})
            tool_name = func.get("name", "")
            try:
                args = json.loads(func.get("arguments", "{}"))
            except json.JSONDecodeError:
                args = {}

            action = AgentAction(
                action_id=f"act-{uuid.uuid4().hex[:8]}",
                tool_name=tool_name,
                args=args,
                timestamp=time.time(),
            )

            # ── 执行工具（approve 模式检查） ──
            result = await registry.execute(
                tool_name, args,
                skip_approval=not self.settings.approve_mode,
            )

            if result.get("needs_approval"):
                # 需要用户确认
                state.phase = AgentPhase.WAITING_APPROVAL
                state.pending_action = action
                action.approved = None
                if self.on_approval:
                    await self.on_approval(session_id, action, result)
                return state

            # 工具执行完成
            action.result = result
            action.approved = True
            state.actions.append(action)

            if self.on_action:
                await self.on_action(session_id, action)

            # 更新 phase
            if tool_name in ("run_command", "run_python", "install_packages"):
                state.phase = AgentPhase.EXECUTING
            elif tool_name in ("write_file", "edit_file"):
                state.phase = AgentPhase.CODING

        return state

    async def approve_action(
        self,
        session_id: str,
        approved: bool,
    ) -> AgentState:
        """用户对 pending_action 做出审批。"""
        state, sandbox, registry = self._sessions[session_id]
        pending = state.pending_action
        if pending is None:
            return state

        if approved:
            pending.approved = True
            # 重新执行工具
            result = await registry.execute(
                pending.tool_name, pending.args, skip_approval=True,
            )
            pending.result = result
            state.actions.append(pending)

            if self.on_action:
                await self.on_action(session_id, pending)

            # 如果是 finish 工具，结束
            if pending.tool_name == "finish":
                state.phase = AgentPhase.DONE
                state.summary = result.get("summary", "")
        else:
            pending.approved = False
            pending.result = {"rejected": True, "reason": "User rejected this action"}
            state.actions.append(pending)
            await self._emit_message(session_id, f"操作被拒绝: {pending.tool_name}", "system")

        state.pending_action = None
        state.phase = AgentPhase.CODING if state.phase == AgentPhase.WAITING_APPROVAL else state.phase
        return state

    async def run_until_blocked(self, session_id: str) -> AgentState:
        """持续运行直到需要审批或完成。"""
        while True:
            state = await self.step(session_id)
            if state.phase in (
                AgentPhase.WAITING_APPROVAL,
                AgentPhase.DONE,
                AgentPhase.FAILED,
            ):
                return state
            if state.iteration >= self.settings.max_iterations:
                return state

    def _build_messages(self, state: AgentState) -> list[dict[str, Any]]:
        """构建 LLM 消息列表。"""
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
        ]

        # 论文上下文
        if state.paper_context:
            messages.append({
                "role": "user",
                "content": f"## Paper Context\n\n{state.paper_context}",
            })

        # 复现计划
        if state.plan:
            messages.append({
                "role": "assistant",
                "content": f"## Reproduction Plan\n\n{state.plan}",
            })

        # 历史动作
        for action in state.actions:
            if action.tool_name == "finish":
                continue
            # 工具调用
            messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": action.action_id,
                    "type": "function",
                    "function": {
                        "name": action.tool_name,
                        "arguments": json.dumps(action.args, ensure_ascii=False),
                    },
                }],
            })
            # 工具结果
            result_text = json.dumps(action.result or {}, ensure_ascii=False, indent=2)
            if len(result_text) > 8000:
                result_text = result_text[:8000] + "\n... (truncated)"
            messages.append({
                "role": "tool",
                "tool_call_id": action.action_id,
                "content": result_text,
            })

        return messages

    def _build_finish_tool(self, state: AgentState):
        """构建 finish 工具。"""
        async def finish(summary: str) -> dict[str, Any]:
            state.phase = AgentPhase.DONE
            state.summary = summary
            return {"summary": summary, "status": "completed"}

        from tools.registry import ToolDefinition
        return ToolDefinition(
            name="finish",
            description="完成复现任务，提交最终总结",
            parameters={
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "复现结果总结"},
                },
                "required": ["summary"],
            },
            handler=finish,
            requires_approval=False,
        )

    async def _emit_message(self, session_id: str, content: str, role: str) -> None:
        if self.on_message:
            await self.on_message(session_id, content, role)

    def get_state(self, session_id: str) -> AgentState | None:
        entry = self._sessions.get(session_id)
        return entry[0] if entry else None

    def destroy_session(self, session_id: str) -> None:
        entry = self._sessions.pop(session_id, None)
        if entry:
            _, sandbox, _ = entry
            self.container_mgr.destroy_session(sandbox)
