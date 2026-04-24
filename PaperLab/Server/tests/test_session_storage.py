from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from session_storage.models import SessionCheckpoint
from session_storage.service import SessionStorageService


class SessionStorageServiceTest(unittest.TestCase):
    def test_append_transcript_and_checkpoint_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = SessionStorageService(root_dir=Path(temp_dir) / "sessions")

            service.append_message(
                project_id="project-a",
                session_id="session-1",
                role="human",
                message_id="message-1",
                content="你好，系统",
                additional_kwargs={},
                response_metadata={},
            )
            service.write_checkpoint(
                project_id="project-a",
                session_id="session-1",
                checkpoint=SessionCheckpoint(
                    session_id="session-1",
                    project_id="project-a",
                    thread_id="session-1",
                    updated_at="2026-04-22T08:00:00Z",
                    interrupt=None,
                    next_nodes=[],
                    resume_capable=False,
                ),
            )

            summaries = service.list_sessions(project_id="project-a")
            restored = service.load_session(project_id="project-a", session_id="session-1")

            self.assertEqual(len(summaries), 1)
            self.assertEqual(summaries[0].session_id, "session-1")
            self.assertEqual(restored.messages[0].content, "你好，系统")
            self.assertIsNotNone(restored.checkpoint)
            self.assertEqual(restored.checkpoint.thread_id, "session-1")

    def test_worker_logs_are_isolated_from_main_session(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = SessionStorageService(root_dir=Path(temp_dir) / "sessions")

            service.append_worker_event(
                project_id="project-a",
                session_id="session-1",
                agent_id="worker-1",
                worker_type="tool",
                kind="worker_result",
                payload={"status": "ok"},
            )

            restored = service.load_session(project_id="project-a", session_id="session-1")
            worker_events = service.load_worker_events(
                project_id="project-a",
                session_id="session-1",
                agent_id="worker-1",
            )

            self.assertEqual(restored.messages, [])
            self.assertEqual(len(worker_events), 1)
            self.assertEqual(worker_events[0].worker_type, "tool")


if __name__ == "__main__":
    unittest.main()
