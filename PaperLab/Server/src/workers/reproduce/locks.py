"""Optional Redis-backed locks for reproduction runs and mailboxes."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Protocol


class LockStore(Protocol):
    def acquire_lock(self, key: str, ttl_seconds: int) -> bool:
        """Acquire one lock key if it is not currently held."""

    def release_lock(self, key: str) -> None:
        """Release one lock key."""


class NullReproductionLock:
    """No-op lock used when Redis is not configured."""

    def acquire_run(self, run_id: str) -> bool:
        return True

    def release_run(self, run_id: str) -> None:
        return None

    @contextmanager
    def mailbox_lock(self, run_id: str, agent_name: str):
        yield


class RedisReproductionLock:
    """Small reproduction-specific wrapper over RedisCacheStore locks."""

    def __init__(
        self,
        store: LockStore,
        *,
        run_ttl_seconds: int = 300,
        mailbox_ttl_seconds: int = 30,
    ) -> None:
        self.store = store
        self.run_ttl_seconds = run_ttl_seconds
        self.mailbox_ttl_seconds = mailbox_ttl_seconds

    def acquire_run(self, run_id: str) -> bool:
        return self.store.acquire_lock(self.run_lock_key(run_id), self.run_ttl_seconds)

    def release_run(self, run_id: str) -> None:
        self.store.release_lock(self.run_lock_key(run_id))

    @contextmanager
    def mailbox_lock(self, run_id: str, agent_name: str):
        key = self.mailbox_lock_key(run_id, agent_name)
        if not self.store.acquire_lock(key, self.mailbox_ttl_seconds):
            raise RuntimeError(f"Mailbox is locked: {agent_name}")
        try:
            yield
        finally:
            self.store.release_lock(key)

    @staticmethod
    def run_lock_key(run_id: str) -> str:
        return f"paperlab:reproduce:{run_id}:run"

    @staticmethod
    def mailbox_lock_key(run_id: str, agent_name: str) -> str:
        return f"paperlab:reproduce:{run_id}:mailbox:{agent_name}"
