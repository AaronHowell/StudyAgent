from __future__ import annotations

import importlib
import unittest
from unittest.mock import patch

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

    def test_project_folder_picker_endpoint(self) -> None:
        module = importlib.import_module("api.main")
        client = TestClient(module.app)

        with patch.object(module, "_select_directory_path", return_value="C:/Research/Papers"):
            response = client.post(
                "/desktop/project-folder/select",
                json={"current_path": "C:/Users/Aaron_Howell/Desktop"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["path"], "C:/Research/Papers")

    def test_startup_config_summary_lists_targets_without_secrets(self) -> None:
        module = importlib.import_module("api.main")
        api_settings = module.Settings(
            mysql_host="mysql.local",
            mysql_port=3307,
            mysql_database="paperlab_test",
            mysql_user="paperlab_user",
            mysql_password="secret-password",
            qdrant_url="http://qdrant.local:6333",
            qdrant_api_key="secret-qdrant-key",
            llm_provider="openai-compatible",
            llm_base_url="http://llm.local/v1",
            llm_api_key="secret-llm-key",
            llm_model="paper-model",
            embedding_base_url="http://embed.local/v1",
            embedding_api_key="secret-embedding-key",
            embedding_model="embedding-model",
            redis_host="redis.local",
            redis_port=6380,
            redis_password="secret-redis-password",
        )
        agent_settings = module.AgentSettings(
            redis_enabled=True,
            redis_host="redis.local",
            redis_port=6380,
            redis_db=3,
            checkpoint_redis_enabled=True,
            checkpoint_redis_url="redis://:secret-redis-password@redis.local:6380/4",
        )

        summary = "\n".join(
            module._startup_config_summary(
                api_settings=api_settings,
                agent_settings=agent_settings,
            )
        )

        self.assertIn("MySQL: mysql.local:3307/paperlab_test user=paperlab_user", summary)
        self.assertIn("Qdrant: http://qdrant.local:6333", summary)
        self.assertIn("LLM: provider=openai-compatible base_url=http://llm.local/v1 model=paper-model", summary)
        self.assertIn("Embedding: base_url=http://embed.local/v1 model=embedding-model", summary)
        self.assertIn("API Redis: redis.local:6380", summary)
        self.assertIn("Agent Redis: enabled redis.local:6380 db=3", summary)
        self.assertIn("Checkpoint Redis: enabled redis.local:6380 db=4", summary)
        self.assertNotIn("secret", summary)


if __name__ == "__main__":
    unittest.main()
