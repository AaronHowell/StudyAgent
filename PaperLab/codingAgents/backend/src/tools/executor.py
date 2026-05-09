"""代码执行工具 — 在沙箱中运行命令。"""

from __future__ import annotations

from typing import Any

from container.manager import ContainerManager, SandboxSession
from tools.registry import ToolDefinition


def build_executor_tools(
    container_mgr: ContainerManager,
    session: SandboxSession,
) -> list[ToolDefinition]:
    """构建代码执行相关的工具定义。"""

    async def run_command(
        command: str,
        timeout: int = 120,
    ) -> dict[str, Any]:
        result = await container_mgr.execute(session, command, timeout=timeout)
        return {
            "exit_code": result.exit_code,
            "stdout": result.stdout[-10_000:],    # 截断避免过长
            "stderr": result.stderr[-5_000:] if result.stderr else "",
            "timed_out": result.timed_out,
            "success": result.success,
        }

    async def install_packages(packages: str) -> dict[str, Any]:
        """安装 Python 包。"""
        cmd = f"pip install {packages} -q 2>&1 | tail -5"
        result = await container_mgr.execute(session, cmd, timeout=180)
        return {
            "exit_code": result.exit_code,
            "output": result.stdout[-3_000:],
            "success": result.success,
        }

    async def run_python(script: str, timeout: int = 120) -> dict[str, Any]:
        """执行 Python 代码片段。"""
        # 写入临时文件再执行，避免 shell 转义问题
        await container_mgr.write_file(session, "__run_tmp.py", script)
        result = await container_mgr.execute(
            session,
            "python __run_tmp.py 2>&1",
            timeout=timeout,
        )
        return {
            "exit_code": result.exit_code,
            "output": result.stdout[-10_000:],
            "timed_out": result.timed_out,
            "success": result.success,
        }

    return [
        ToolDefinition(
            name="run_command",
            description="在沙箱中执行 shell 命令",
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "要执行的命令"},
                    "timeout": {"type": "integer", "description": "超时秒数", "default": 120},
                },
                "required": ["command"],
            },
            handler=run_command,
            requires_approval=True,
            risk_level="high",
        ),
        ToolDefinition(
            name="install_packages",
            description="安装 Python 包（pip install）",
            parameters={
                "type": "object",
                "properties": {
                    "packages": {"type": "string", "description": "包名，如 'numpy pandas torch'"},
                },
                "required": ["packages"],
            },
            handler=install_packages,
            requires_approval=True,
            risk_level="high",
        ),
        ToolDefinition(
            name="run_python",
            description="执行 Python 代码",
            parameters={
                "type": "object",
                "properties": {
                    "script": {"type": "string", "description": "Python 代码"},
                    "timeout": {"type": "integer", "description": "超时秒数", "default": 120},
                },
                "required": ["script"],
            },
            handler=run_python,
            requires_approval=True,
            risk_level="high",
        ),
    ]
