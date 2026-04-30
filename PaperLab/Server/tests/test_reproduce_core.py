from __future__ import annotations

import asyncio
from pathlib import Path


def test_reproduction_run_round_trips() -> None:
    from workers.reproduce.models import ReproductionRun

    run = ReproductionRun.create(
        project_id="project-1",
        objective="reproduce paper",
        paper_ids=["paper-1"],
        workspace_path="workspace",
    )

    restored = ReproductionRun.from_dict(run.to_dict())

    assert restored.run_id == run.run_id
    assert restored.tasks["T1"].blocked_by == []
    assert restored.tasks["T8"].blocked_by == ["T7"]


def test_file_store_saves_and_loads_run(tmp_path: Path) -> None:
    from workers.reproduce.models import ReproductionRun
    from workers.reproduce.store import FileReproductionStore

    store = FileReproductionStore(tmp_path)
    run = ReproductionRun.create(
        project_id="project-1",
        objective="reproduce paper",
        paper_ids=["paper-1"],
        workspace_path=str(tmp_path / "workspace"),
    )

    store.create(run)
    loaded = store.load(run.run_id)

    assert loaded is not None
    assert loaded.run_id == run.run_id
    assert (tmp_path / run.run_id / "run.json").exists()


def test_mailbox_send_read_and_mark_read(tmp_path: Path) -> None:
    from workers.reproduce.mailbox import FileMailbox

    mailbox = FileMailbox(tmp_path)
    mailbox.ensure_mailboxes("run-1", ["plan_agent", "code_worker"])

    message = mailbox.send(
        run_id="run-1",
        sender="plan_agent",
        recipient="code_worker",
        message_type="task_assignment",
        payload={"task_id": "T5"},
    )

    unread = mailbox.read_unread("run-1", "code_worker")
    assert [item.message_id for item in unread] == [message.message_id]

    mailbox.mark_read("run-1", "code_worker", [message.message_id])
    assert mailbox.read_unread("run-1", "code_worker") == []


def test_command_policy_is_conservative(tmp_path: Path) -> None:
    from workers.reproduce.command_policy import CommandPolicy

    policy = CommandPolicy()
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    assert policy.decide("python reproduce.py", cwd=workspace, workspace_path=workspace).decision == "allow"
    assert policy.decide("rm -rf ~", cwd=workspace, workspace_path=workspace).decision == "deny"
    assert policy.decide("sudo apt install git", cwd=workspace, workspace_path=workspace).decision == "deny"
    assert policy.decide("python reproduce.py", cwd=tmp_path, workspace_path=workspace).decision == "deny"
    assert policy.decide("unknown-tool", cwd=workspace, workspace_path=workspace).decision == "require_user"


def test_plan_agent_smoke_run_completes(tmp_path: Path) -> None:
    from workers.reproduce.mailbox import FileMailbox
    from workers.reproduce.plan_agent import PlanAgent
    from workers.reproduce.store import FileReproductionStore
    from workers.reproduce.workers import build_default_workers

    store = FileReproductionStore(tmp_path)
    mailbox = FileMailbox(tmp_path)
    agent = PlanAgent(
        store=store,
        mailbox=mailbox,
        workers=build_default_workers(store=store, mailbox=mailbox),
        sandbox_root=tmp_path,
    )

    run = asyncio.run(
        agent.create_run(
            project_id="project-1",
            objective="make a minimal reproduction",
            paper_ids=["paper-1"],
        )
    )
    finished = asyncio.run(agent.run(run.run_id))

    assert finished.status == "completed"
    assert (Path(finished.workspace_path) / "README.md").exists()
    assert (Path(finished.workspace_path) / "reproduce.py").exists()
    assert (Path(finished.workspace_path) / "outputs" / "logs" / "run_experiment.log").exists()
    assert Path(finished.report_path).exists()
