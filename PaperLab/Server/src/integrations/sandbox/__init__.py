
"""本包提供任务级沙箱运行环境的创建与命令执行入口。"""

from __future__ import annotations

from functools import lru_cache

from integrations.sandbox.runner import SandboxRunner
from integrations.sandbox.task_manager import SandboxManager


@lru_cache(maxsize=1)
def get_sandbox_manager() -> SandboxManager:
    return SandboxManager()


@lru_cache(maxsize=1)
def get_sandbox_runner() -> SandboxRunner:
    return SandboxRunner(manager=get_sandbox_manager())


__all__ = [
    "SandboxManager",
    "SandboxRunner",
    "get_sandbox_manager",
    "get_sandbox_runner",
]
