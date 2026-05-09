"""Docker 容器生命周期管理 — 沙箱执行环境。"""

from __future__ import annotations

import asyncio
import os
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import docker
from docker.models.containers import Container

from configs.settings import Settings


@dataclass
class ExecResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False

    @property
    def success(self) -> bool:
        return self.exit_code == 0


@dataclass
class SandboxSession:
    """一次复现会话的沙箱环境。"""
    session_id: str
    container: Container
    workspace_host: str        # 宿主机挂载路径
    workspace_guest: str       # 容器内路径
    _active: bool = True

    @property
    def active(self) -> bool:
        return self._active


class ContainerManager:
    """管理 Docker 容器的创建、执行、销毁。"""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        self._client: docker.DockerClient | None = None
        self._sessions: dict[str, SandboxSession] = {}

    @property
    def client(self) -> docker.DockerClient:
        if self._client is None:
            self._client = docker.from_env()
        return self._client

    def create_session(self, session_id: str | None = None) -> SandboxSession:
        """创建一个新的沙箱会话。"""
        sid = session_id or f"coding-{uuid.uuid4().hex[:8]}"
        host_workspace = os.path.join(
            tempfile.gettempdir(), "coding-agent-workspaces", sid
        )
        os.makedirs(host_workspace, exist_ok=True)

        container = self.client.containers.run(
            image=self.settings.docker_image,
            command="sleep infinity",
            detach=True,
            working_dir=self.settings.docker_workspace,
            volumes={
                host_workspace: {
                    "bind": self.settings.docker_workspace,
                    "mode": "rw",
                },
            },
            mem_limit=self.settings.docker_memory_limit,
            cpu_period=self.settings.docker_cpu_period,
            cpu_quota=self.settings.docker_cpu_quota,
            network_mode=self.settings.docker_network,
            name=f"coding-agent-{sid}",
            remove=True,
        )

        session = SandboxSession(
            session_id=sid,
            container=container,
            workspace_host=host_workspace,
            workspace_guest=self.settings.docker_workspace,
        )
        self._sessions[sid] = session
        return session

    async def execute(
        self,
        session: SandboxSession,
        command: str,
        timeout: int | None = None,
    ) -> ExecResult:
        """在沙箱中执行命令。"""
        if not session.active:
            return ExecResult(exit_code=-1, stdout="", stderr="Session is not active")

        timeout = timeout or self.settings.docker_timeout

        try:
            exit_code, output = await asyncio.to_thread(
                self._run_in_container, session.container, command, timeout
            )
            stdout = output.decode("utf-8", errors="replace") if isinstance(output, bytes) else str(output)
            return ExecResult(exit_code=exit_code, stdout=stdout, stderr="")
        except asyncio.TimeoutError:
            return ExecResult(exit_code=-1, stdout="", stderr=f"Command timed out after {timeout}s", timed_out=True)
        except Exception as e:
            return ExecResult(exit_code=-1, stdout="", stderr=str(e))

    def _run_in_container(self, container: Container, command: str, timeout: int) -> tuple[int, bytes]:
        """同步方式在容器内执行命令。"""
        result = container.exec_run(
            cmd=["bash", "-c", command],
            demux=True,
            workdir=self.settings.docker_workspace,
        )
        stdout = result.output[0] or b""
        stderr = result.output[1] or b""
        combined = stdout + (b"\n[stderr]\n" + stderr if stderr else b"")
        return result.exit_code, combined

    async def write_file(
        self,
        session: SandboxSession,
        path: str,
        content: str,
    ) -> None:
        """写入文件到沙箱（通过宿主机挂载）。"""
        full_path = os.path.join(session.workspace_host, path.lstrip("/"))
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        await asyncio.to_thread(
            lambda: Path(full_path).write_text(content, encoding="utf-8")
        )

    async def read_file(
        self,
        session: SandboxSession,
        path: str,
        max_chars: int = 50_000,
    ) -> str:
        """从沙箱读取文件（通过宿主机挂载）。"""
        full_path = os.path.join(session.workspace_host, path.lstrip("/"))
        if not os.path.exists(full_path):
            raise FileNotFoundError(f"File not found: {path}")

        def _read() -> str:
            text = Path(full_path).read_text(encoding="utf-8", errors="replace")
            return text[:max_chars]

        return await asyncio.to_thread(_read)

    async def list_files(
        self,
        session: SandboxSession,
        path: str = ".",
    ) -> list[dict[str, str]]:
        """列出沙箱中的文件。"""
        full_path = os.path.join(session.workspace_host, path.lstrip("/"))
        if not os.path.isdir(full_path):
            return []

        def _list() -> list[dict[str, str]]:
            entries = []
            for entry in sorted(os.scandir(full_path), key=lambda e: (not e.is_dir(), e.name)):
                entries.append({
                    "name": entry.name,
                    "type": "dir" if entry.is_dir() else "file",
                    "size": str(entry.stat().st_size) if entry.is_file() else "",
                })
            return entries

        return await asyncio.to_thread(_list)

    def destroy_session(self, session: SandboxSession) -> None:
        """销毁沙箱会话。"""
        session._active = False
        try:
            session.container.stop(timeout=5)
        except Exception:
            pass
        self._sessions.pop(session.session_id, None)

    def destroy_all(self) -> None:
        """销毁所有会话。"""
        for session in list(self._sessions.values()):
            self.destroy_session(session)

    def __del__(self) -> None:
        self.destroy_all()
