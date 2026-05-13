"""Cross-platform workspace tool helpers for the coding agent."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import os
import platform
import shutil
import subprocess
from typing import Literal
import shlex


ToolRisk = Literal["read", "write", "execute"]

DEFAULT_ALLOWED_COMMANDS = {
    "python",
    "pip",
    "pytest",
    "git",
    "rg",
}

HIGH_PRIVILEGE_SHELLS = {"powershell", "cmd", "bash", "sh"}


@dataclass(slots=True)
class PlatformInfo:
    system: str
    shell: str
    path_separator: str
    has_rg: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "system": self.system,
            "shell": self.shell,
            "path_separator": self.path_separator,
            "has_rg": self.has_rg,
        }


@dataclass(slots=True)
class ToolApprovalRequest:
    tool_call_id: str
    tool_name: str
    args: dict[str, object]
    risk: ToolRisk
    platform: PlatformInfo
    preview: str

    def to_dict(self) -> dict[str, object]:
        return {
            "tool_call_id": self.tool_call_id,
            "tool_name": self.tool_name,
            "args": dict(self.args),
            "risk": self.risk,
            "platform": self.platform.to_dict(),
            "preview": self.preview,
        }


@dataclass(slots=True)
class WorkspaceToolPolicy:
    workspace_root: Path
    allow_file_read: bool = False
    allow_file_write: bool = False
    allow_shell: bool = False
    allowed_commands: set[str] | None = None

    def normalized_allowed_commands(self) -> set[str]:
        configured = self.allowed_commands or DEFAULT_ALLOWED_COMMANDS
        return {str(item).strip().lower() for item in configured if str(item).strip()}


def detect_platform() -> PlatformInfo:
    system = platform.system().lower() or os.name
    if system.startswith("windows"):
        normalized = "windows"
        shell = "powershell"
    elif system == "darwin":
        normalized = "darwin"
        shell = "sh"
    else:
        normalized = "linux"
        shell = "sh"
    return PlatformInfo(
        system=normalized,
        shell=shell,
        path_separator=os.sep,
        has_rg=shutil.which("rg") is not None,
    )


def build_tool_approval_request(
    *,
    tool_call_id: str,
    tool_name: str,
    args: dict[str, object],
) -> ToolApprovalRequest | None:
    risk = _risk_for_tool(tool_name)
    if risk == "read":
        return None
    return ToolApprovalRequest(
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        args=args,
        risk=risk,
        platform=detect_platform(),
        preview=_preview_tool_call(tool_name, args),
    )


def find_files(*, root: Path, pattern: str = "", limit: int = 100) -> list[str]:
    resolved_root = root.resolve()
    if detect_platform().has_rg:
        command = ["rg", "--files"]
        if pattern:
            command.extend(["-g", pattern])
        completed = subprocess.run(command, cwd=resolved_root, capture_output=True, text=True, check=False)
        if completed.returncode in {0, 1}:
            return [line for line in completed.stdout.splitlines() if line][:limit]
    matches: list[str] = []
    needle = pattern.replace("*", "").lower()
    for path in resolved_root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(resolved_root).as_posix()
        if needle and needle not in relative.lower():
            continue
        matches.append(relative)
        if len(matches) >= limit:
            break
    return matches


def build_workspace_policy(
    *,
    root: Path,
    allow_file_read: bool = False,
    allow_file_write: bool = False,
    allow_shell: bool = False,
    allowed_commands: set[str] | None = None,
) -> WorkspaceToolPolicy:
    return WorkspaceToolPolicy(
        workspace_root=root.expanduser().resolve(strict=False),
        allow_file_read=allow_file_read,
        allow_file_write=allow_file_write,
        allow_shell=allow_shell,
        allowed_commands=set(allowed_commands) if allowed_commands is not None else None,
    )


def resolve_workspace_path(*, workspace_root: Path, user_path: str) -> Path:
    normalized_root = workspace_root.expanduser().resolve(strict=False)
    raw_path = Path(user_path).expanduser()
    candidate = raw_path if raw_path.is_absolute() else normalized_root / raw_path
    normalized_candidate = candidate.resolve(strict=False)
    try:
        if os.path.commonpath(
            [
                os.path.normcase(str(normalized_root)),
                os.path.normcase(str(normalized_candidate)),
            ]
        ) != os.path.normcase(str(normalized_root)):
            raise ValueError(f"Path '{user_path}' escapes workspace root.")
    except ValueError as exc:
        raise ValueError(f"Path '{user_path}' escapes workspace root.") from exc
    return normalized_candidate


def validate_workspace_command(
    *,
    command: str,
    policy: WorkspaceToolPolicy,
) -> list[str]:
    tokens = _tokenize_command(command)
    executable = str(tokens[0] or "").strip().lower()
    if executable in HIGH_PRIVILEGE_SHELLS and not policy.allow_shell:
        raise ValueError(f"Command '{tokens[0]}' is not enabled.")
    if executable not in policy.normalized_allowed_commands() and executable not in HIGH_PRIVILEGE_SHELLS:
        raise ValueError(f"Command '{tokens[0]}' is not allowed in the workspace policy.")
    return tokens


def execute_workspace_tool(
    *,
    root: Path,
    tool_name: str,
    args: dict[str, object],
    policy: WorkspaceToolPolicy | None = None,
) -> dict[str, object]:
    resolved_root = root.expanduser().resolve(strict=False)
    resolved_policy = policy or build_workspace_policy(
        root=resolved_root,
        allow_file_read=True,
        allow_file_write=True,
        allow_shell=False,
    )
    normalized = tool_name.strip().lower()
    if normalized == "get_current_time":
        now = datetime.now(timezone.utc)
        local_now = datetime.now()
        content = (
            f"当前本地时间: {local_now.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"当前UTC时间: {now.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"星期: {['一','二','三','四','五','六','日'][local_now.weekday()]}\n"
            f"时区: {local_now.astimezone().tzinfo}"
        )
        return {"summary": "获取当前时间成功。", "content": content}
    if normalized == "detect_platform":
        return {"summary": "Detected current platform.", "content": detect_platform().to_dict()}
    if normalized == "list_files":
        _ensure_read_allowed(resolved_policy, tool_name)
        target = _resolve_path(resolved_policy, str(args.get("path") or "."))
        if target.is_file():
            entries = [target.relative_to(resolved_root).as_posix()]
        else:
            entries = [child.relative_to(resolved_root).as_posix() for child in sorted(target.iterdir())]
        return {"summary": f"Listed {len(entries)} path(s).", "content": "\n".join(entries)}
    if normalized == "find_files":
        _ensure_read_allowed(resolved_policy, tool_name)
        matches = find_files(root=resolved_root, pattern=str(args.get("pattern") or ""), limit=int(args.get("limit") or 100))
        return {"summary": f"Found {len(matches)} file(s).", "content": "\n".join(matches)}
    if normalized == "search_text":
        _ensure_read_allowed(resolved_policy, tool_name)
        pattern = str(args.get("pattern") or "").strip()
        target = _resolve_path(resolved_policy, str(args.get("path") or "."))
        matches = _search_text(root=resolved_root, target=target, pattern=pattern, limit=int(args.get("limit") or 100))
        return {"summary": f"Found {len(matches)} text match(es).", "content": "\n".join(matches)}
    if normalized == "read_file":
        _ensure_read_allowed(resolved_policy, tool_name)
        target = _resolve_path(resolved_policy, str(args.get("path") or ""))
        max_chars = int(args.get("max_chars") or 12000)
        return {"summary": f"Read {target.relative_to(resolved_root).as_posix()}.", "content": target.read_text(encoding="utf-8")[:max_chars]}
    if normalized in {"mkdir", "make_directory"}:
        _ensure_write_allowed(resolved_policy, tool_name)
        target = _resolve_path(resolved_policy, str(args.get("path") or args.get("relative_path") or ""))
        target.mkdir(parents=True, exist_ok=True)
        return {"summary": f"Created directory {target.relative_to(resolved_root).as_posix()}.", "content": ""}
    if normalized in {"write_file", "write"}:
        _ensure_write_allowed(resolved_policy, tool_name)
        target = _resolve_path(resolved_policy, str(args.get("path") or args.get("relative_path") or ""))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(args.get("content") or ""), encoding="utf-8")
        return {"summary": f"Wrote {target.relative_to(resolved_root).as_posix()}.", "content": "", "changed_files": [target.relative_to(resolved_root).as_posix()]}
    if normalized in {"delete_file", "delete"}:
        _ensure_write_allowed(resolved_policy, tool_name)
        target = _resolve_path(resolved_policy, str(args.get("path") or args.get("relative_path") or ""))
        if not target.exists():
            raise FileNotFoundError(target)
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        return {"summary": f"Deleted {target.relative_to(resolved_root).as_posix()}.", "content": "", "changed_files": [target.relative_to(resolved_root).as_posix()]}
    if normalized in {"run_command", "run"}:
        _ensure_write_allowed(resolved_policy, tool_name)
        command = str(args.get("command") or "").strip()
        tokens = validate_workspace_command(command=command, policy=resolved_policy)
        completed = subprocess.run(tokens, cwd=resolved_root, capture_output=True, text=True, timeout=int(args.get("timeout_seconds") or 120), check=False)
        return {
            "summary": f"Ran command with exit code {completed.returncode}.",
            "content": f"stdout:\n{completed.stdout}\n\nstderr:\n{completed.stderr}",
            "exit_code": completed.returncode,
        }
    raise ValueError(f"Unsupported workspace tool: {tool_name}")


def _resolve_path(policy: WorkspaceToolPolicy, relative_path: str) -> Path:
    if not relative_path:
        raise ValueError("Path is required.")
    return resolve_workspace_path(workspace_root=policy.workspace_root, user_path=relative_path)


def _search_text(*, root: Path, target: Path, pattern: str, limit: int) -> list[str]:
    if not pattern:
        raise ValueError("Search pattern is required.")
    files = [target] if target.is_file() else [path for path in target.rglob("*") if path.is_file()]
    matches: list[str] = []
    for path in files:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for index, line in enumerate(lines, start=1):
            if pattern in line:
                matches.append(f"{path.relative_to(root).as_posix()}:{index}: {line}")
                if len(matches) >= limit:
                    return matches
    return matches


def _tokenize_command(command: str) -> list[str]:
    if not command:
        raise ValueError("Command is required.")
    if any(fragment in command for fragment in ["&&", "||", ";", "|", ">", "<"]):
        raise ValueError("Shell chaining and redirection are not allowed.")
    return shlex.split(command, posix=detect_platform().system != "windows")


def _risk_for_tool(tool_name: str) -> ToolRisk:
    normalized = tool_name.strip().lower()
    if normalized in {"write", "write_task_file", "write_file", "mkdir", "make_directory", "delete", "delete_file"}:
        return "write"
    if normalized in {"run", "run_task_command", "run_command"}:
        return "execute"
    return "read"


def _preview_tool_call(tool_name: str, args: dict[str, object]) -> str:
    normalized = tool_name.strip().lower()
    if normalized in {"write", "write_task_file", "write_file"}:
        return f"Write file: {args.get('relative_path') or args.get('path') or ''}"
    if normalized in {"mkdir", "make_directory"}:
        return f"Create directory: {args.get('relative_path') or args.get('path') or ''}"
    if normalized in {"delete", "delete_file"}:
        return f"Delete path: {args.get('relative_path') or args.get('path') or ''}"
    if normalized in {"run", "run_task_command", "run_command"}:
        return f"Run command: {args.get('command') or ''}"
    return f"Run tool: {tool_name}"


def _ensure_read_allowed(policy: WorkspaceToolPolicy, tool_name: str) -> None:
    if not policy.allow_file_read:
        raise ValueError(f"Tool '{tool_name}' is not enabled.")


def _ensure_write_allowed(policy: WorkspaceToolPolicy, tool_name: str) -> None:
    if not policy.allow_file_write:
        raise ValueError(f"Tool '{tool_name}' is not enabled.")
