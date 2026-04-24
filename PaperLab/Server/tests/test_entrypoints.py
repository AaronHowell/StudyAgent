from __future__ import annotations

import importlib
import unittest

from fastapi.testclient import TestClient


class EntrypointTest(unittest.TestCase):
    def test_imports_work(self) -> None:
        importlib.import_module("orchestration.supervisor")
        importlib.import_module("api.main")

    def test_health_endpoint(self) -> None:
        module = importlib.import_module("api.main")
        client = TestClient(module.app)
        response = client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_chat_state_endpoint(self) -> None:
        module = importlib.import_module("api.main")
        client = TestClient(module.app)
        response = client.get(
            "/chat/state",
            params={"thread_id": "test-thread", "project_id": "test-project"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["thread_id"], "test-thread")
        self.assertEqual(payload["project_id"], "test-project")
        self.assertIn("messages", payload)


if __name__ == "__main__":
    unittest.main()
