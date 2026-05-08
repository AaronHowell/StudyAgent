from __future__ import annotations

from workspace.tools import build_tool_approval_request
from workspace.tools import detect_platform


def test_detect_platform_returns_supported_shape() -> None:
    info = detect_platform()

    assert info.system in {"windows", "linux", "darwin"}
    assert info.shell in {"powershell", "sh"}
    assert isinstance(info.has_rg, bool)


def test_build_tool_approval_request_marks_write_and_execute_tools() -> None:
    write_request = build_tool_approval_request(
        tool_call_id="call-1",
        tool_name="write",
        args={"relative_path": "demo.py"},
    )
    run_request = build_tool_approval_request(
        tool_call_id="call-2",
        tool_name="run",
        args={"command": "pytest"},
    )
    read_request = build_tool_approval_request(
        tool_call_id="call-3",
        tool_name="read",
        args={"path": "demo.py"},
    )

    assert write_request is not None
    assert write_request.risk == "write"
    assert "demo.py" in write_request.preview
    assert run_request is not None
    assert run_request.risk == "execute"
    assert "pytest" in run_request.preview
    assert read_request is None
