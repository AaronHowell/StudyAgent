from __future__ import annotations

import os
import unittest
from unittest.mock import patch
from urllib.parse import urlparse

from api import config as api_config
import configs
from configs import Settings
from domain import MemoryType
from integrations.storage.mem0_memory_store import Mem0MemoryStore
from integrations.vectorstore.qdrant_store import QdrantChunkVectorStore, QdrantConnectionConfig
from langchain_core.messages import AIMessage, HumanMessage
from memory.service import MemoryService
from orchestration.request_config import resolve_agent_request_config
from runtime.dependencies import _build_memory_chat_model, _build_primary_chat_model, _build_qdrant_client, _patch_reasoning_content_support
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

    def test_short_term_context_keeps_answer_messages_but_excludes_internal_artifacts(self) -> None:
        service = MemoryService(
            backend=None,
            settings=AgentSettings(short_term_raw_turns=4, short_term_summary_turns=0),
        )
        messages = [
            HumanMessage(content="你好"),
            HumanMessage(
                content="你好",
                additional_kwargs={"metadata": {"artifact_type": "question"}},
            ),
            AIMessage(
                content="Recent raw turns:\n- user: 你好",
                additional_kwargs={"metadata": {"artifact_type": "short_term_context"}},
            ),
            AIMessage(
                content="最终回答",
                additional_kwargs={"metadata": {"artifact_type": "answer"}},
            ),
            HumanMessage(content="继续"),
        ]

        context = service.build_short_term_context(role="supervisor", messages=messages)

        self.assertIn("- user: 你好", context)
        self.assertIn("- user: 继续", context)
        self.assertIn("- assistant: 最终回答", context)
        self.assertNotIn("artifact_type", context)
        self.assertNotIn("- assistant: Recent raw turns:", context)

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

    def test_memory_backend_defaults_to_mem0(self) -> None:
        settings = AgentSettings()

        self.assertEqual(settings.memory_backend, "mem0")
        self.assertEqual(settings.memory_markdown_root, "data/memory")

    def test_memory_backend_can_switch_to_markdown(self) -> None:
        env = {
            "PAPERLAB_MEMORY_BACKEND": "markdown",
            "PAPERLAB_MEMORY_MARKDOWN_ROOT": "custom/memory",
        }
        with patch.dict(os.environ, env, clear=False):
            settings = AgentSettings.from_env()

        self.assertEqual(settings.memory_backend, "markdown")
        self.assertEqual(settings.memory_markdown_root, "custom/memory")

    def test_memory_llm_defaults_to_main_chat_model(self) -> None:
        settings = AgentSettings(
            llm_base_url="http://main.local/v1",
            llm_api_key="main-key",
            llm_model="main-model",
        )

        self.assertEqual(settings.memory_llm_base_url, "http://main.local/v1")
        self.assertEqual(settings.memory_llm_api_key, "main-key")
        self.assertEqual(settings.memory_llm_model, "main-model")

    def test_memory_llm_can_be_configured_independently(self) -> None:
        env = {
            "PAPERLAB_LLM_BASE_URL": "https://big.example/v1",
            "PAPERLAB_LLM_API_KEY": "big-key",
            "PAPERLAB_LLM_MODEL": "big-model",
            "PAPERLAB_MEMORY_LLM_BASE_URL": "http://small.local/v1",
            "PAPERLAB_MEMORY_LLM_API_KEY": "small-key",
            "PAPERLAB_MEMORY_LLM_MODEL": "small-model",
        }
        with patch.dict(os.environ, env, clear=False):
            settings = AgentSettings.from_env()

        self.assertEqual(settings.llm_base_url, "https://big.example/v1")
        self.assertEqual(settings.llm_api_key, "big-key")
        self.assertEqual(settings.llm_model, "big-model")
        self.assertEqual(settings.memory_llm_base_url, "http://small.local/v1")
        self.assertEqual(settings.memory_llm_api_key, "small-key")
        self.assertEqual(settings.memory_llm_model, "small-model")

    def test_memory_chat_model_uses_independent_config(self) -> None:
        settings = AgentSettings(
            llm_base_url="https://big.example/v1",
            llm_api_key="big-key",
            llm_model="big-model",
            memory_llm_base_url="http://small.local/v1",
            memory_llm_api_key="small-key",
            memory_llm_model="small-model",
        )

        with patch("runtime.dependencies.ChatOpenAI") as chat_openai:
            _build_memory_chat_model(settings)

        self.assertEqual(chat_openai.call_args.kwargs["base_url"], "http://small.local/v1")
        self.assertEqual(chat_openai.call_args.kwargs["api_key"], "small-key")
        self.assertEqual(chat_openai.call_args.kwargs["model"], "small-model")
        self.assertEqual(chat_openai.call_args.kwargs["extra_body"], {"thinking": {"type": "disabled"}})

    def test_primary_chat_model_disables_thinking_by_default(self) -> None:
        settings = AgentSettings(
            llm_base_url="https://main.example/v1",
            llm_api_key="main-key",
            llm_model="main-model",
        )

        with patch("runtime.dependencies.ChatOpenAI") as chat_openai:
            _build_primary_chat_model(settings)

        self.assertEqual(chat_openai.call_args.kwargs["base_url"], "https://main.example/v1")
        self.assertEqual(chat_openai.call_args.kwargs["api_key"], "main-key")
        self.assertEqual(chat_openai.call_args.kwargs["model"], "main-model")
        self.assertEqual(chat_openai.call_args.kwargs["extra_body"], {"thinking": {"type": "disabled"}})

    def test_primary_chat_model_can_enable_thinking_via_env(self) -> None:
        with patch.dict(
            os.environ,
            {
                "PAPERLAB_LLM_THINKING_ENABLED": "true",
                "PAPERLAB_MEMORY_LLM_THINKING_ENABLED": "true",
            },
            clear=False,
        ):
            settings = AgentSettings.from_env()

        self.assertTrue(settings.llm_thinking_enabled)
        self.assertTrue(settings.memory_llm_thinking_enabled)

    def test_reasoning_content_patch_round_trips_reasoning_content(self) -> None:
        from langchain_core.messages import AIMessage
        import langchain_openai.chat_models.base as openai_base

        _patch_reasoning_content_support()
        message = AIMessage(
            content="final answer",
            additional_kwargs={"reasoning_content": "hidden chain"},
            response_metadata={"reasoning_content": "hidden chain"},
        )

        serialized = openai_base._convert_message_to_dict(message)

        self.assertEqual(serialized["reasoning_content"], "hidden chain")

    def test_qdrant_client_ignores_system_proxy_by_default(self) -> None:
        settings = AgentSettings()

        self.assertEqual(settings.qdrant_trust_env, False)

    def test_qdrant_client_can_trust_environment_proxy_when_enabled(self) -> None:
        with patch.dict(os.environ, {"PAPERLAB_QDRANT_TRUST_ENV": "true"}, clear=False):
            settings = AgentSettings.from_env()

        self.assertEqual(settings.qdrant_trust_env, True)

    def test_invalid_memory_backend_falls_back_to_mem0(self) -> None:
        with patch.dict(os.environ, {"PAPERLAB_MEMORY_BACKEND": "bad-backend"}, clear=False):
            settings = AgentSettings.from_env()

        self.assertEqual(settings.memory_backend, "mem0")

    def test_vector_store_disables_environment_proxy_by_default(self) -> None:
        config = QdrantConnectionConfig(host="10.201.0.86", port=6333)

        with patch("integrations.vectorstore.qdrant_store.QdrantClient") as qdrant_client:
            QdrantChunkVectorStore(config)

        self.assertEqual(qdrant_client.call_args.kwargs["trust_env"], False)

    def test_memory_qdrant_client_uses_same_proxy_policy(self) -> None:
        settings = AgentSettings(qdrant_url="http://10.201.0.86:6333", qdrant_trust_env=False)

        with patch("runtime.dependencies.QdrantClient") as qdrant_client:
            _build_qdrant_client(settings, urlparse(settings.qdrant_url))

        self.assertEqual(qdrant_client.call_args.kwargs["trust_env"], False)

    def test_remote_qdrant_client_preserves_explicit_http_url_when_api_key_is_present(self) -> None:
        settings = AgentSettings(
            qdrant_url="http://10.201.0.86:6333",
            qdrant_api_key="secret-key",
            qdrant_trust_env=False,
        )

        with patch("runtime.dependencies.QdrantClient") as qdrant_client:
            _build_qdrant_client(settings, urlparse(settings.qdrant_url))

        self.assertEqual(qdrant_client.call_args.kwargs["url"], "http://10.201.0.86:6333")
        self.assertEqual(qdrant_client.call_args.kwargs["api_key"], "secret-key")

    def test_vector_store_preserves_explicit_http_url_when_api_key_is_present(self) -> None:
        config = QdrantConnectionConfig(
            url="http://10.201.0.86:6333",
            host="10.201.0.86",
            port=6333,
            api_key="secret-key",
        )

        with patch("integrations.vectorstore.qdrant_store.QdrantClient") as qdrant_client:
            QdrantChunkVectorStore(config)

        self.assertEqual(qdrant_client.call_args.kwargs["url"], "http://10.201.0.86:6333")
        self.assertEqual(qdrant_client.call_args.kwargs["api_key"], "secret-key")

    def test_api_and_agent_settings_share_base_environment_parsing(self) -> None:
        env = {
            "PAPERLAB_MYSQL_HOST": "shared-mysql",
            "PAPERLAB_QDRANT_URL": "http://shared-qdrant:6333",
            "PAPERLAB_LLM_MODEL": "shared-model",
            "PAPERLAB_MULTIMODAL_EMBEDDING_ENABLED": "true",
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
        self.assertEqual(api.multimodal_embedding_enabled, True)
        self.assertEqual(agent.multimodal_embedding_enabled, True)
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
