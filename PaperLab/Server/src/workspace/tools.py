"""Cross-platform workspace tool helpers for the coding agent."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import platform
import shutil
import subprocess
from typing import Literal
import shlex


ToolRisk = Literal["read", "write", "execute"]


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


def execute_workspace_tool(*, root: Path, tool_name: str, args: dict[str, object]) -> dict[str, object]:
    resolved_root = root.resolve()
    normalized = tool_name.strip().lower()
    if normalized == "detect_platform":
        return {"summary": "Detected current platform.", "content": detect_platform().to_dict()}
    if normalized == "list_files":
        target = _resolve_path(resolved_root, str(args.get("path") or "."))
        if target.is_file():
            entries = [target.relative_to(resolved_root).as_posix()]
        else:
            entries = [child.relative_to(resolved_root).as_posix() for child in sorted(target.iterdir())]
        return {"summary": f"Listed {len(entries)} path(s).", "content": "\n".join(entries)}
    if normalized == "find_files":
        matches = find_files(root=resolved_root, pattern=str(args.get("pattern") or ""), limit=int(args.get("limit") or 100))
        return {"summary": f"Found {len(matches)} file(s).", "content": "\n".join(matches)}
    if normalized == "search_text":
        pattern = str(args.get("pattern") or "").strip()
        target = _resolve_path(resolved_root, str(args.get("path") or "."))
        matches = _search_text(root=resolved_root, target=target, pattern=pattern, limit=int(args.get("limit") or 100))
        return {"summary": f"Found {len(matches)} text match(es).", "content": "\n".join(matches)}
    if normalized == "read_file":
        target = _resolve_path(resolved_root, str(args.get("path") or ""))
        max_chars = int(args.get("max_chars") or 12000)
        return {"summary": f"Read {target.relative_to(resolved_root).as_posix()}.", "content": target.read_text(encoding="utf-8")[:max_chars]}
    if normalized in {"mkdir", "make_directory"}:
        target = _resolve_path(resolved_root, str(args.get("path") or args.get("relative_path") or ""))
        target.mkdir(parents=True, exist_ok=True)
        return {"summary": f"Created directory {target.relative_to(resolved_root).as_posix()}.", "content": ""}
    if normalized in {"write_file", "write"}:
        target = _resolve_path(resolved_root, str(args.get("path") or args.get("relative_path") or ""))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(args.get("content") or ""), encoding="utf-8")
        return {"summary": f"Wrote {target.relative_to(resolved_root).as_posix()}.", "content": "", "changed_files": [target.relative_to(resolved_root).as_posix()]}
    if normalized in {"run_command", "run"}:
        command = str(args.get("command") or "").strip()
        tokens = _tokenize_command(command)
        completed = subprocess.run(tokens, cwd=resolved_root, capture_output=True, text=True, timeout=int(args.get("timeout_seconds") or 120), check=False)
        return {
            "summary": f"Ran command with exit code {completed.returncode}.",
            "content": f"stdout:\n{completed.stdout}\n\nstderr:\n{completed.stderr}",
            "exit_code": completed.returncode,
        }
    raise ValueError(f"Unsupported workspace tool: {tool_name}")


def _resolve_path(root: Path, relative_path: str) -> Path:
    if not relative_path:
        raise ValueError("Path is required.")
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Path '{relative_path}' escapes workspace root.") from exc
    return candidate


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
    if normalized in {"write", "write_task_file", "mkdir", "make_directory"}:
        return "write"
    if normalized in {"run", "run_task_command"}:
        return "execute"
    return "read"


def _preview_tool_call(tool_name: str, args: dict[str, object]) -> str:
    normalized = tool_name.strip().lower()
    if normalized in {"write", "write_task_file", "write_file"}:
        return f"Write file: {args.get('relative_path') or args.get('path') or ''}"
    if normalized in {"mkdir", "make_directory"}:
        return f"Create directory: {args.get('relative_path') or args.get('path') or ''}"
    if normalized in {"run", "run_task_command", "run_command"}:
        return f"Run command: {args.get('command') or ''}"
    return f"Run tool: {tool_name}"
