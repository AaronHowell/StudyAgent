from __future__ import annotations

import os
from pathlib import Path
import shlex
import subprocess
from typing import Sequence

from integrations.sandbox.models import CommandResult
from integrations.sandbox.task_manager import SandboxManager


ALLOWED_COMMANDS = {
    "python",
    "pip",
    "pytest",
    "git",
    "rg",
    "ls",
    "dir",
    "cat",
    "type",
}


class SandboxRunner:
    """Run whitelisted commands inside one task workspace."""

    def __init__(
        self,
        *,
        manager: SandboxManager,
        default_timeout_seconds: int = 120,
        max_output_chars: int = 4_000,
    ) -> None:
        self.manager = manager
        self.default_timeout_seconds = default_timeout_seconds
        self.max_output_chars = max_output_chars

    def run_task_command(
        self,
        task_id: str,
        *,
        command: str,
        timeout_seconds: int | None = None,
    ) -> CommandResult:
        tokens = self._tokenize_command(command)
        executable = tokens[0].lower()
        if executable not in ALLOWED_COMMANDS:
            raise ValueError(f"Command '{tokens[0]}' is not allowed in the sandbox.")

        paths = self.manager.resolve_task_paths(task_id)
        timeout_value = timeout_seconds or self.default_timeout_seconds

        if executable in {"ls", "dir"}:
            stdout, stderr, exit_code, timed_out = self._run_list_directory(paths.workspace, tokens)
        elif executable in {"cat", "type"}:
            stdout, stderr, exit_code, timed_out = self._run_show_file(paths.workspace, tokens)
        else:
            stdout, stderr, exit_code, timed_out = self._run_subprocess(
                tokens=tokens,
                working_directory=paths.workspace,
                timeout_seconds=timeout_value,
            )

        metadata = self.manager.mark_running(task_id, command=command, exit_code=exit_code)
        log_path = paths.logs / f"command_{metadata.command_count:03d}.log"
        log_path.write_text(
            self._build_log(
                command=command,
                working_directory=paths.workspace,
                exit_code=exit_code,
                timed_out=timed_out,
                stdout=stdout,
                stderr=stderr,
            ),
            encoding="utf-8",
        )
        status = "timed_out" if timed_out else ("completed" if exit_code == 0 else "failed")
        return CommandResult(
            task_id=task_id,
            command=command,
            exit_code=exit_code,
            status=status,
            stdout=self._truncate(stdout),
            stderr=self._truncate(stderr),
            timed_out=timed_out,
            log_path=str(log_path),
            working_directory=str(paths.workspace),
        )

    def _run_subprocess(
        self,
        *,
        tokens: Sequence[str],
        working_directory: Path,
        timeout_seconds: int,
    ) -> tuple[str, str, int, bool]:
        try:
            completed = subprocess.run(
                list(tokens),
                cwd=str(working_directory),
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
                env=self._build_clean_env(),
            )
        except subprocess.TimeoutExpired as exc:
            return exc.stdout or "", exc.stderr or "Command timed out.", -1, True
        return completed.stdout, completed.stderr, completed.returncode, False

    def _run_list_directory(
        self,
        workspace: Path,
        tokens: Sequence[str],
    ) -> tuple[str, str, int, bool]:
        target = self._resolve_builtin_path(workspace, tokens[1] if len(tokens) > 1 else ".")
        if not target.exists():
            return "", f"Path '{target.name}' does not exist.", 1, False
        if target.is_file():
            return str(target.relative_to(workspace)).replace("\\", "/"), "", 0, False
        entries = [str(child.relative_to(workspace)).replace("\\", "/") for child in sorted(target.iterdir())]
        return "\n".join(entries), "", 0, False

    def _run_show_file(
        self,
        workspace: Path,
        tokens: Sequence[str],
    ) -> tuple[str, str, int, bool]:
        if len(tokens) < 2:
            return "", "cat/type requires a relative path.", 1, False
        target = self._resolve_builtin_path(workspace, tokens[1])
        if not target.exists():
            return "", f"File '{tokens[1]}' does not exist.", 1, False
        if target.is_dir():
            return "", f"'{tokens[1]}' is a directory.", 1, False
        return target.read_text(encoding="utf-8"), "", 0, False

    def _resolve_builtin_path(self, workspace: Path, relative_path: str) -> Path:
        candidate = (workspace / (relative_path or ".")).resolve()
        try:
            candidate.relative_to(workspace)
        except ValueError as exc:
            raise ValueError(f"Path '{relative_path}' escapes the task workspace.") from exc
        return candidate

    def _tokenize_command(self, command: str) -> list[str]:
        command_text = command.strip()
        if not command_text:
            raise ValueError("Sandbox command cannot be empty.")
        forbidden_fragments = ["&&", "||", ";", "|", ">", "<"]
        if any(fragment in command_text for fragment in forbidden_fragments):
            raise ValueError("Shell chaining and redirection are not allowed in sandbox commands.")
        return shlex.split(command_text, posix=True)

    def _build_clean_env(self) -> dict[str, str]:
        allowed_env = [
            "PATH",
            "SYSTEMROOT",
            "COMSPEC",
            "PATHEXT",
            "TEMP",
            "TMP",
            "USERPROFILE",
            "HOMEDRIVE",
            "HOMEPATH",
            "VIRTUAL_ENV",
        ]
        env = {name: value for name, value in os.environ.items() if name in allowed_env}
        env["PYTHONIOENCODING"] = "utf-8"
        env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
        return env

    def _truncate(self, output: str) -> str:
        if len(output) <= self.max_output_chars:
            return output
        return output[: self.max_output_chars] + "\n...[truncated]"

    def _build_log(
        self,
        *,
        command: str,
        working_directory: Path,
        exit_code: int,
        timed_out: bool,
        stdout: str,
        stderr: str,
    ) -> str:
        return (
            f"command: {command}\n"
            f"cwd: {working_directory}\n"
            f"exit_code: {exit_code}\n"
            f"timed_out: {timed_out}\n\n"
            f"[stdout]\n{stdout}\n\n"
            f"[stderr]\n{stderr}\n"
        )
