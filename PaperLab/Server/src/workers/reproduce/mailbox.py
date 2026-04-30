"""JSONL per-agent mailbox for reproduction workers."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from workers.reproduce.locks import NullReproductionLock
from workers.reproduce.models import MailboxMessage


class FileMailbox:
    def __init__(self, root: Path | str, *, lock: object | None = None) -> None:
        self.root = Path(root)
        self.lock = lock or NullReproductionLock()

    def ensure_mailboxes(self, run_id: str, agent_names: list[str]) -> None:
        directory = self._mailbox_dir(run_id)
        directory.mkdir(parents=True, exist_ok=True)
        for name in agent_names:
            self._mailbox_path(run_id, name).touch(exist_ok=True)

    def send(
        self,
        *,
        run_id: str,
        sender: str,
        recipient: str,
        message_type: str,
        payload: dict[str, object],
    ) -> MailboxMessage:
        message = MailboxMessage(
            message_id=f"msg-{uuid4().hex}",
            sender=sender,
            recipient=recipient,
            message_type=message_type,
            payload=payload,
        )
        path = self._mailbox_path(run_id, recipient)
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock.mailbox_lock(run_id, recipient):
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(message.to_dict(), ensure_ascii=False) + "\n")
        return message

    def read_unread(self, run_id: str, agent_name: str) -> list[MailboxMessage]:
        return [message for message in self._read_all(run_id, agent_name) if not message.read]

    def mark_read(self, run_id: str, agent_name: str, message_ids: list[str]) -> None:
        selected = set(message_ids)
        messages = self._read_all(run_id, agent_name)
        for message in messages:
            if message.message_id in selected:
                message.read = True
        path = self._mailbox_path(run_id, agent_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock.mailbox_lock(run_id, agent_name):
            path.write_text(
                "".join(json.dumps(message.to_dict(), ensure_ascii=False) + "\n" for message in messages),
                encoding="utf-8",
            )

    def _read_all(self, run_id: str, agent_name: str) -> list[MailboxMessage]:
        path = self._mailbox_path(run_id, agent_name)
        if not path.exists():
            return []
        messages = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                messages.append(MailboxMessage.from_dict(json.loads(line)))
        return messages

    def _mailbox_dir(self, run_id: str) -> Path:
        return self.root / run_id / "mailboxes"

    def _mailbox_path(self, run_id: str, agent_name: str) -> Path:
        return self._mailbox_dir(run_id) / f"{agent_name}.jsonl"
