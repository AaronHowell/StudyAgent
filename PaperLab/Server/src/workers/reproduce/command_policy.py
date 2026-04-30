"""Deterministic command policy for reproduction workspaces."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shlex


@dataclass(slots=True)
class CommandPolicyResult:
    decision: str
    reason: str


class CommandPolicy:
    allow_exact = {
        "python reproduce.py",
        "pytest",
        "pip install -r requirements.txt",
        "python --version",
        "pip --version",
        "pwd",
        "ls",
        "dir",
    }
    deny_tokens = {"sudo", "su", "chown"}
    deny_fragments = ["rm -rf /", "rm -rf ~", "chmod -R 777", "curl", "| sh", "| bash", "git push", "git reset --hard"]

    def decide(self, command: str, *, cwd: Path | str, workspace_path: Path | str) -> CommandPolicyResult:
        workspace = Path(workspace_path).resolve()
        current = Path(cwd).resolve()
        try:
            current.relative_to(workspace)
        except ValueError:
            return CommandPolicyResult("deny", "cwd is outside the reproduction workspace")

        normalized = " ".join(command.strip().split())
        lowered = normalized.lower()
        if any(fragment in lowered for fragment in self.deny_fragments):
            return CommandPolicyResult("deny", "command matches a deterministic deny rule")

        try:
            tokens = shlex.split(normalized, posix=True)
        except ValueError:
            return CommandPolicyResult("deny", "command cannot be parsed")
        if not tokens:
            return CommandPolicyResult("deny", "command is empty")
        if tokens[0].lower() in self.deny_tokens:
            return CommandPolicyResult("deny", "command starts with a denied executable")
        if lowered in self.allow_exact:
            return CommandPolicyResult("allow", "command is explicitly allowed")
        if tokens[0].lower() in {"cat", "type", "grep", "rg", "find"}:
            return CommandPolicyResult("allow", "read-only command is allowed inside workspace")
        return CommandPolicyResult("require_user", "command requires user approval")
