from __future__ import annotations

import asyncio
from pathlib import Path


class FakeLockStore:
    def __init__(self) -> None:
        self.held: set[str] = set()
        self.acquired: list[str] = []
        self.released: list[str] = []

    def acquire_lock(self, key: str, ttl_seconds: int) -> bool:
        if key in self.held:
            return False
        self.held.add(key)
        self.acquired.append(key)
        return True

    def release_lock(self, key: str) -> None:
        self.held.discard(key)
        self.released.append(key)


def test_mailbox_uses_optional_lock_for_writes(tmp_path: Path) -> None:
    from workers.reproduce.locks import RedisReproductionLock
    from workers.reproduce.mailbox import FileMailbox

    store = FakeLockStore()
    lock = RedisReproductionLock(store)
    mailbox = FileMailbox(tmp_path, lock=lock)

    mailbox.send(
        run_id="run-1",
        sender="plan_agent",
        recipient="code_worker",
        message_type="task_assignment",
        payload={"task_id": "T5"},
    )
    unread = mailbox.read_unread("run-1", "code_worker")
    mailbox.mark_read("run-1", "code_worker", [unread[0].message_id])

    assert "paperlab:reproduce:run-1:mailbox:code_worker" in store.acquired
    assert store.acquired == store.released


def test_plan_agent_skips_run_when_redis_lock_is_held(tmp_path: Path) -> None:
    from workers.reproduce.locks import RedisReproductionLock
    from workers.reproduce.mailbox import FileMailbox
    from workers.reproduce.plan_agent import PlanAgent
    from workers.reproduce.store import FileReproductionStore
    from workers.reproduce.workers import build_default_workers

    store = FakeLockStore()
    lock = RedisReproductionLock(store)
    file_store = FileReproductionStore(tmp_path)
    mailbox = FileMailbox(tmp_path, lock=lock)
    agent = PlanAgent(
        store=file_store,
        mailbox=mailbox,
        workers=build_default_workers(store=file_store, mailbox=mailbox),
        sandbox_root=tmp_path,
        lock=lock,
    )
    run = asyncio.run(
        agent.create_run(
            project_id="project-1",
            objective="reproduce",
            paper_ids=[],
        )
    )

    assert lock.acquire_run(run.run_id)
    loaded = asyncio.run(agent.run(run.run_id))

    assert loaded.status == "created"
    lock.release_run(run.run_id)
