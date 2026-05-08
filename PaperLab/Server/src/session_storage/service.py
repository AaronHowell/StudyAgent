"""追加写 session transcript，并维护最近 checkpoint。"""

from __future__ import annotations

from datetime import UTC
from datetime import datetime
import json
from pathlib import Path
import shutil
from typing import Any
from uuid import uuid4

from session_storage.models import RestoredSession
from session_storage.models import SessionCheckpoint
from session_storage.models import SessionMessageRecord
from session_storage.models import SessionSummary
from session_storage.models import WorkerEventRecord


class SessionStorageService:
    """文件系统版会话持久化服务。"""

    def __init__(self, *, root_dir: Path) -> None:
        self._root_dir = root_dir

    def append_message(
        self,
        *,
        project_id: str,
        session_id: str,
        role: str | None,
        message_id: str | None,
        content: Any,
        additional_kwargs: dict[str, object],
        response_metadata: dict[str, object],
        message_type: str | None = None,
    ) -> None:
        created_at = self._now()
        self._append_jsonl(
            self._session_log_path(project_id, session_id),
            {
                "event_id": self._new_id("evt"),
                "kind": "message",
                "session_id": session_id,
                "project_id": project_id,
                "created_at": created_at,
                "payload": {
                    "id": message_id,
                    "type": message_type or role,
                    "role": role,
                    "content": content,
                    "additional_kwargs": additional_kwargs,
                    "response_metadata": response_metadata,
                    "created_at": created_at,
                },
            },
        )

    def write_checkpoint(
        self,
        *,
        project_id: str,
        session_id: str,
        checkpoint: SessionCheckpoint,
    ) -> None:
        path = self._checkpoint_path(project_id, session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(checkpoint.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def append_worker_event(
        self,
        *,
        project_id: str,
        session_id: str,
        agent_id: str,
        worker_type: str,
        kind: str,
        payload: dict[str, object],
    ) -> None:
        self._append_jsonl(
            self._worker_log_path(project_id, session_id, agent_id),
            {
                "event_id": self._new_id("worker"),
                "session_id": session_id,
                "project_id": project_id,
                "agent_id": agent_id,
                "worker_type": worker_type,
                "kind": kind,
                "payload": payload,
                "created_at": self._now(),
            },
        )

    def list_sessions(self, *, project_id: str) -> list[SessionSummary]:
        project_root = self._project_root(project_id)
        if not project_root.exists():
            return []

        summaries: list[SessionSummary] = []
        for session_dir in project_root.iterdir():
            if not session_dir.is_dir():
                continue
            restored = self.load_session(project_id=project_id, session_id=session_dir.name)
            latest_time = (
                restored.checkpoint.updated_at
                if restored.checkpoint is not None
                else (restored.messages[-1].created_at if restored.messages else "")
            )
            first_human = next(
                (
                    message.content
                    for message in restored.messages
                    if (message.role or message.type) in {"human", "user"}
                ),
                "",
            )
            title = str(first_human or restored.session_id)
            summaries.append(
                SessionSummary(
                    session_id=restored.session_id,
                    project_id=project_id,
                    title=title[:24] + ("..." if len(title) > 24 else ""),
                    updated_at=latest_time,
                    message_count=len(restored.messages),
                    resume_capable=bool(restored.checkpoint and restored.checkpoint.resume_capable),
                )
            )

        summaries.sort(key=lambda item: item.updated_at, reverse=True)
        return summaries

    def load_session(self, *, project_id: str, session_id: str) -> RestoredSession:
        messages: list[SessionMessageRecord] = []
        log_path = self._session_log_path(project_id, session_id)
        if log_path.exists():
            for line in log_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                record = json.loads(line)
                if record.get("kind") != "message":
                    continue
                messages.append(SessionMessageRecord.from_dict(dict(record.get("payload", {}) or {})))

        checkpoint = self._load_checkpoint(project_id=project_id, session_id=session_id)
        thread_id = checkpoint.thread_id if checkpoint is not None else session_id
        return RestoredSession(
            session_id=session_id,
            project_id=project_id,
            thread_id=thread_id,
            messages=messages,
            checkpoint=checkpoint,
        )

    def delete_session(self, *, project_id: str, session_id: str) -> bool:
        session_dir = self._session_root(project_id, session_id)
        if not session_dir.exists():
            return False
        shutil.rmtree(session_dir)
        return True

    def load_worker_events(
        self,
        *,
        project_id: str,
        session_id: str,
        agent_id: str,
    ) -> list[WorkerEventRecord]:
        path = self._worker_log_path(project_id, session_id, agent_id)
        if not path.exists():
            return []
        events: list[WorkerEventRecord] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            events.append(WorkerEventRecord.from_dict(json.loads(line)))
        return events

    def _load_checkpoint(
        self,
        *,
        project_id: str,
        session_id: str,
    ) -> SessionCheckpoint | None:
        path = self._checkpoint_path(project_id, session_id)
        if not path.exists():
            return None
        return SessionCheckpoint.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def _append_jsonl(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def _project_root(self, project_id: str) -> Path:
        return self._root_dir / project_id

    def _session_root(self, project_id: str, session_id: str) -> Path:
        return self._project_root(project_id) / session_id

    def _session_log_path(self, project_id: str, session_id: str) -> Path:
        return self._session_root(project_id, session_id) / "session.jsonl"

    def _checkpoint_path(self, project_id: str, session_id: str) -> Path:
        return self._session_root(project_id, session_id) / "checkpoint.json"

    def _worker_log_path(self, project_id: str, session_id: str, agent_id: str) -> Path:
        return self._session_root(project_id, session_id) / "workers" / f"{agent_id}.jsonl"

    @staticmethod
    def _new_id(prefix: str) -> str:
        return f"{prefix}_{uuid4().hex[:8]}"

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")
