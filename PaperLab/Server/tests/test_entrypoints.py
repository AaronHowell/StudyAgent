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


if __name__ == "__main__":
    unittest.main()
