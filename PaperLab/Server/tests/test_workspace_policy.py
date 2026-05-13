from __future__ import annotations

from pathlib import Path

import pytest

from orchestration.request_config import resolve_agent_request_config
from workspace import tools


def test_request_config_resolves_workspace_permissions_and_root() -> None:
    resolved = resolve_agent_request_config(
        {
            "configurable": {
                "project_id": "project-a",
                "thread_id": "thread-a",
                "workspace_root": "C:/demo/workspace",
                "allow_web_search": True,
                "allow_file_read": True,
                "allow_file_write": False,
                "allow_mcp": True,
                "allow_shell": False,
            }
        }
    )

    assert resolved.workspace_root == "C:/demo/workspace"
    assert resolved.allow_web_search is True
    assert resolved.allow_file_read is True
    assert resolved.allow_file_write is False
    assert resolved.allow_mcp is True
    assert resolved.allow_shell is False


def test_resolve_workspace_path_rejects_escape(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    with pytest.raises(ValueError, match="escapes workspace root"):
        tools.resolve_workspace_path(workspace_root=workspace, user_path="../outside.txt")


def test_execute_workspace_tool_deletes_file_inside_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "demo.txt"
    target.write_text("hello", encoding="utf-8")

    result = tools.execute_workspace_tool(
        root=workspace,
        tool_name="delete_file",
        args={"path": "demo.txt"},
    )

    assert result["summary"] == "Deleted demo.txt."
    assert result["changed_files"] == ["demo.txt"]
    assert not target.exists()


def test_execute_workspace_tool_rejects_high_privilege_shell_without_permission(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    with pytest.raises(ValueError, match="not enabled"):
        tools.execute_workspace_tool(
            root=workspace,
            tool_name="run_command",
            args={"command": "powershell -Command Get-ChildItem"},
        )

