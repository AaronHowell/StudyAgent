from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from api import config as api_config
import configs
from configs import Settings
from domain import MemoryType
from integrations.storage.mem0_memory_store import Mem0MemoryStore
from memory.service import MemoryService
from orchestration.request_config import resolve_agent_request_config
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


class _LegacyMem0Client:
    def __init__(self) -> None:
        self.search_calls: list[dict[str, object]] = []
        self.get_all_calls: list[dict[str, object]] = []

    def search(self, query: str, *, limit: int, filters: dict[str, object]) -> dict[str, object]:
        self.search_calls.append(
            {"query": query, "limit": limit, "filters": filters}
        )
        return {"results": [{"id": "m1", "memory": "cached fact", "metadata": {"memory_type": "research_episode"}}]}

    def get_all(self, *, filters: dict[str, object], limit: int) -> dict[str, object]:
        self.get_all_calls.append({"filters": filters, "limit": limit})
        return {"results": [{"id": "m2", "memory": "another fact", "metadata": {"memory_type": "research_episode"}}]}


class _LegacyScopedMem0Client:
    def __init__(self) -> None:
        self.search_calls: list[dict[str, object]] = []
        self.get_all_calls: list[dict[str, object]] = []

    def search(self, query: str, *, limit: int, user_id: str) -> dict[str, object]:
        self.search_calls.append({"query": query, "limit": limit, "user_id": user_id})
        return {"results": [{"id": "m1", "memory": "cached fact", "metadata": {"memory_type": "research_episode"}}]}

    def get_all(self, *, limit: int, user_id: str) -> dict[str, object]:
        self.get_all_calls.append({"limit": limit, "user_id": user_id})
        return {"results": [{"id": "m2", "memory": "another fact", "metadata": {"memory_type": "research_episode"}}]}


class _Mem0V1ScopedMem0Client:
    def __init__(self) -> None:
        self.search_calls: list[dict[str, object]] = []
        self.get_all_calls: list[dict[str, object]] = []

    def search(
        self,
        query: str,
        *,
        user_id: str | None = None,
        filters: dict[str, object] | None = None,
        limit: int = 100,
    ) -> dict[str, object]:
        if not user_id:
            raise ValueError("At least one of 'user_id', 'agent_id', or 'run_id' must be provided.")
        self.search_calls.append({"query": query, "limit": limit, "user_id": user_id, "filters": filters})
        return {"results": [{"id": "m1", "memory": "cached fact", "metadata": {"memory_type": "research_episode"}}]}

    def get_all(
        self,
        *,
        user_id: str | None = None,
        filters: dict[str, object] | None = None,
        limit: int = 100,
    ) -> dict[str, object]:
        if not user_id:
            raise ValueError("At least one of 'user_id', 'agent_id', or 'run_id' must be provided.")
        self.get_all_calls.append({"limit": limit, "user_id": user_id, "filters": filters})
        return {"results": [{"id": "m2", "memory": "another fact", "metadata": {"memory_type": "research_episode"}}]}


class _FailingMemoryBackend:
    def add(self, item: object) -> None:
        raise AssertionError("not used")

    def remember_messages(self, **_kwargs: object) -> list[object]:
        raise ValueError("At least one of 'user_id', 'agent_id', or 'run_id' must be provided.")

    def search(self, *_args: object, **_kwargs: object) -> list[object]:
        raise ValueError("At least one of 'user_id', 'agent_id', or 'run_id' must be provided.")

    def summarize_for_project(self, _project_id: str) -> str:
        raise ValueError("At least one of 'user_id', 'agent_id', or 'run_id' must be provided.")


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

    def test_mem0_adapter_supports_legacy_limit_api(self) -> None:
        client = _LegacyMem0Client()
        store = Mem0MemoryStore(client=client)

        items = store.search("what happened", "frontend-project", limit=3)
        summary = store.summarize_for_project("frontend-project")

        self.assertEqual(len(items), 1)
        self.assertEqual(client.search_calls[0]["filters"], {"user_id": "frontend-project"})
        self.assertEqual(client.search_calls[0]["limit"], 3)
        self.assertEqual(client.get_all_calls[0]["filters"], {"user_id": "frontend-project"})
        self.assertEqual(client.get_all_calls[0]["limit"], 10)
        self.assertIn("Relevant memory:", summary)

    def test_memory_service_fails_open_when_backend_memory_errors(self) -> None:
        service = MemoryService(
            backend=_FailingMemoryBackend(),
            settings=AgentSettings(memory_enabled=True),
        )

        recall = service.recall(
            role="supervisor",
            query="hello",
            project_id="default-project",
            limit=5,
        )
        stored = service.store_turn(
            role="supervisor",
            project_id="default-project",
            thread_id="thread-1",
            user_text="hello",
            assistant_text="hi",
            metadata={},
            memory_type=MemoryType.RESEARCH_EPISODE,
        )

        self.assertEqual(recall.summary, "")
        self.assertEqual(recall.hits, [])
        self.assertFalse(stored)

    def test_mem0_adapter_supports_legacy_top_level_user_id_scope(self) -> None:
        client = _LegacyScopedMem0Client()
        store = Mem0MemoryStore(client=client)

        items = store.search("what happened", "frontend-project", limit=3)
        summary = store.summarize_for_project("frontend-project")

        self.assertEqual(len(items), 1)
        self.assertEqual(client.search_calls[0]["user_id"], "frontend-project")
        self.assertEqual(client.search_calls[0]["limit"], 3)
        self.assertEqual(client.get_all_calls[0]["user_id"], "frontend-project")
        self.assertEqual(client.get_all_calls[0]["limit"], 10)
        self.assertIn("Relevant memory:", summary)

    def test_mem0_adapter_prefers_top_level_user_id_for_mem0_v1_scope(self) -> None:
        client = _Mem0V1ScopedMem0Client()
        store = Mem0MemoryStore(client=client)

        items = store.search("what happened", "frontend-project", limit=3)
        summary = store.summarize_for_project("frontend-project")

        self.assertEqual(len(items), 1)
        self.assertEqual(client.search_calls[0]["user_id"], "frontend-project")
        self.assertIsNone(client.search_calls[0]["filters"])
        self.assertEqual(client.get_all_calls[0]["user_id"], "frontend-project")
        self.assertIsNone(client.get_all_calls[0]["filters"])
        self.assertIn("Relevant memory:", summary)

    def test_mem0_adapter_falls_back_to_single_default_project_scope(self) -> None:
        client = _Mem0V1ScopedMem0Client()
        store = Mem0MemoryStore(client=client)

        items = store.search("what happened", "", limit=3)
        summary = store.summarize_for_project("   ")

        self.assertEqual(len(items), 1)
        self.assertEqual(client.search_calls[0]["user_id"], "default-project")
        self.assertEqual(client.get_all_calls[0]["user_id"], "default-project")
        self.assertIn("Relevant memory:", summary)

    def test_request_config_falls_back_to_single_project_and_thread(self) -> None:
        resolved = resolve_agent_request_config(
            {"configurable": {"project_id": "", "thread_id": "   "}}
        )

        self.assertEqual(resolved.project_id, "default-project")
        self.assertEqual(resolved.thread_id, "default-thread")

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

    def test_api_and_agent_settings_share_base_environment_parsing(self) -> None:
        env = {
            "PAPERLAB_MYSQL_HOST": "shared-mysql",
            "PAPERLAB_QDRANT_URL": "http://shared-qdrant:6333",
            "PAPERLAB_LLM_MODEL": "shared-model",
            "PAPERLAB_API_PORT": "8123",
            "PAPERLAB_AGENT_LOOP_MAX_STEPS": "9",
        }
        with patch.dict(os.environ, env, clear=False):
            api = Settings.from_env()
            agent = AgentSettings.from_env()

        self.assertEqual(api.mysql_host, "shared-mysql")
        self.assertEqual(agent.mysql_host, "shared-mysql")
        self.assertEqual(api.qdrant_url, "http://shared-qdrant:6333")
        self.assertEqual(agent.qdrant_url, "http://shared-qdrant:6333")
        self.assertEqual(api.llm_model, "shared-model")
        self.assertEqual(agent.llm_model, "shared-model")
        self.assertEqual(api.port, 8123)
        self.assertEqual(agent.agent_loop_max_steps, 9)

    def test_single_configs_module_contains_agent_and_policy_config(self) -> None:
        self.assertEqual(configs.AGENT_CONFIGS["tool_worker"]["role"], "tool")
        self.assertEqual(configs.AGENT_CONFIGS["tool_worker"]["capabilities"], ["mcp", "skills"])
        self.assertEqual(configs.POLICIES["sandbox"]["enabled"], True)
        self.assertEqual(configs.POLICIES["retrieval"]["chunk_limit"], 8)

    def test_api_config_loads_only_server_env_file(self) -> None:
        with patch("configs.Path.exists", return_value=True), patch("configs.load_dotenv") as load_dotenv:
            configs._load_env_files()

        self.assertEqual(load_dotenv.call_count, 1)
        self.assertTrue(str(load_dotenv.call_args.args[0]).endswith("PaperLab\\Server\\.env"))
        self.assertEqual(load_dotenv.call_args.kwargs, {"override": True})

    def test_runtime_settings_loads_only_server_env_file(self) -> None:
        with patch("configs.Path.exists", return_value=True), patch("configs.load_dotenv") as load_dotenv:
            configs._load_env_files()

        self.assertEqual(load_dotenv.call_count, 1)
        self.assertTrue(str(load_dotenv.call_args.args[0]).endswith("PaperLab\\Server\\.env"))
        self.assertEqual(load_dotenv.call_args.kwargs, {"override": True})


if __name__ == "__main__":
    unittest.main()
