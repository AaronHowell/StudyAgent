from __future__ import annotations

import unittest

from study_agent_agents.graph import (
    AgentRequestConfig,
    build_assistant_metadata,
    resolve_agent_request_config,
)
from study_agent_domain import Citation


class LangGraphAdapterTest(unittest.TestCase):
    def test_resolve_agent_request_config_reads_configurable_values(self) -> None:
        config = resolve_agent_request_config(
            {
                "configurable": {
                    "project_id": "project-42",
                    "document_limit": 7,
                    "chunk_limit": 11,
                    "asset_limit": 3,
                }
            }
        )

        self.assertEqual(
            config,
            AgentRequestConfig(
                project_id="project-42",
                document_limit=7,
                chunk_limit=11,
                asset_limit=3,
            ),
        )

    def test_resolve_agent_request_config_uses_defaults_when_values_missing(self) -> None:
        config = resolve_agent_request_config({})

        self.assertEqual(
            config,
            AgentRequestConfig(
                project_id="default-project",
                document_limit=5,
                chunk_limit=8,
                asset_limit=6,
            ),
        )

    def test_build_assistant_metadata_serializes_citations(self) -> None:
        metadata = build_assistant_metadata(
            [
                Citation(
                    document_id="doc-1",
                    document_title="Paper A",
                    chunk_id="chunk-1",
                    page=4,
                    locator="p.4",
                )
            ]
        )

        self.assertEqual(metadata["citations"][0]["document_id"], "doc-1")
        self.assertEqual(metadata["citations"][0]["locator"], "p.4")


if __name__ == "__main__":
    unittest.main()
