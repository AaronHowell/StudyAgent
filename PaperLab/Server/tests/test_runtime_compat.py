from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from api import config as api_config
from integrations.storage.mem0_memory_store import Mem0MemoryStore
from runtime import settings as runtime_settings
from runtime.settings import AgentSettings


class _FakeMem0Client:
    def __init__(self) -> None:
        self.search_calls: list[dict[str, object]] = []
        self.get_all_calls: list[dict[str, object]] = []

    def search(self, query: str, *, top_k: int, filters: dict[str, object]) -> dict[str, object]:
        self.search_calls.append(
            {"query": query, "top_k": top_k, "filters": filters}
        )
        return {"results": [{"id": "m1", "memory": "cached fact", "metadata": {"memory_type": "research_episode"}}]}

    def get_all(self, *, filters: dict[str, object], top_k: int) -> dict[str, object]:
        self.get_all_calls.append({"filters": filters, "top_k": top_k})
        return {"results": [{"id": "m2", "memory": "another fact", "metadata": {"memory_type": "research_episode"}}]}


class RuntimeCompatTest(unittest.TestCase):
    def test_mem0_adapter_uses_filters_api(self) -> None:
        client = _FakeMem0Client()
        store = Mem0MemoryStore(client=client)

        items = store.search("what happened", "frontend-project", limit=3)
        summary = store.summarize_for_project("frontend-project")

        self.assertEqual(len(items), 1)
        self.assertEqual(client.search_calls[0]["filters"], {"user_id": "frontend-project"})
        self.assertEqual(client.search_calls[0]["top_k"], 3)
        self.assertEqual(client.get_all_calls[0]["filters"], {"user_id": "frontend-project"})
        self.assertEqual(client.get_all_calls[0]["top_k"], 10)
        self.assertIn("Relevant memory:", summary)

    def test_settings_accept_legacy_environment_prefix(self) -> None:
        env = {
            "PAPERLAB_MYSQL_HOST": "",
            "PAPERLAB_QDRANT_URL": "",
            "PAPERLAB_QDRANT_CHUNK_COLLECTION_NAME": "",
            "PAPERLAB_QDRANT_ASSET_COLLECTION_NAME": "",
            "PAPERLAB_QDRANT_DOCUMENT_COLLECTION_NAME": "",
            "PAPERLAB_LLM_MODEL": "",
            "STUDY_AGENT_MYSQL_HOST": "mysql-host",
            "STUDY_AGENT_QDRANT_URL": "http://qdrant:6333",
            "STUDY_AGENT_QDRANT_CHUNK_COLLECTION_NAME": "legacy_chunks",
            "STUDY_AGENT_QDRANT_ASSET_COLLECTION_NAME": "legacy_assets",
            "STUDY_AGENT_QDRANT_DOCUMENT_COLLECTION_NAME": "legacy_documents",
            "STUDY_AGENT_LLM_MODEL": "demo-model",
        }
        with patch.dict(os.environ, env, clear=False):
            settings = AgentSettings.from_env()

        self.assertEqual(settings.mysql_host, "mysql-host")
        self.assertEqual(settings.qdrant_url, "http://qdrant:6333")
        self.assertEqual(settings.qdrant_chunk_collection_name, "legacy_chunks")
        self.assertEqual(settings.qdrant_asset_collection_name, "legacy_assets")
        self.assertEqual(settings.qdrant_document_collection_name, "legacy_documents")
        self.assertEqual(settings.llm_model, "demo-model")

    def test_api_config_loads_only_server_env_file(self) -> None:
        with patch("api.config.Path.exists", return_value=True), patch("api.config.load_dotenv") as load_dotenv:
            api_config._load_env_files()

        self.assertEqual(load_dotenv.call_count, 1)
        self.assertTrue(str(load_dotenv.call_args.args[0]).endswith("PaperLab\\Server\\.env"))
        self.assertEqual(load_dotenv.call_args.kwargs, {"override": True})

    def test_runtime_settings_loads_only_server_env_file(self) -> None:
        with patch("runtime.settings.Path.exists", return_value=True), patch("runtime.settings.load_dotenv") as load_dotenv:
            runtime_settings._load_env_files()

        self.assertEqual(load_dotenv.call_count, 1)
        self.assertTrue(str(load_dotenv.call_args.args[0]).endswith("PaperLab\\Server\\.env"))
        self.assertEqual(load_dotenv.call_args.kwargs, {"override": True})


if __name__ == "__main__":
    unittest.main()
