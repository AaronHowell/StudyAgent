"""Remote reranker provider implementations for PaperLab."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(slots=True)
class OpenAICompatibleRerankerConfig:
    """Connection settings for a remote reranker endpoint."""

    base_url: str
    api_key: str
    model: str
    timeout_seconds: float = 60.0


class OpenAICompatibleRerankerProvider:
    """Reranker provider backed by an OpenAI-compatible `/rerank` API."""

    def __init__(self, config: OpenAICompatibleRerankerConfig) -> None:
        self.config = config
        self._endpoint = f"{config.base_url.rstrip('/')}/rerank"

    def rerank(self, query: str, candidates: list[str], top_k: int) -> list[float]:
        """Score candidates for one query using a remote reranker service."""

        if not candidates:
            return []

        payload = {
            "model": self.config.model,
            "query": query,
            "documents": candidates,
            "top_n": min(max(top_k, 1), len(candidates)),
        }
        response = self._post_rerank(payload)
        return self._parse_scores(response, len(candidates))

    def _post_rerank(self, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"

        with httpx.Client(timeout=self.config.timeout_seconds) as client:
            response = client.post(self._endpoint, json=payload, headers=headers)
            response.raise_for_status()
            return response.json()

    @staticmethod
    def _parse_scores(payload: dict[str, Any], candidate_count: int) -> list[float]:
        """Parse one reranker response into a dense score list."""

        results = payload.get("results")
        if not isinstance(results, list):
            results = payload.get("data")
        if not isinstance(results, list):
            raise ValueError("Reranker API response missing 'results' or 'data' list.")

        scores = [-1.0 for _ in range(candidate_count)]
        for item in results:
            if not isinstance(item, dict):
                continue
            try:
                index = int(item["index"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("Reranker API returned an invalid candidate index.") from exc

            raw_score = item.get("relevance_score", item.get("score", item.get("relevance", -1.0)))
            try:
                score = float(raw_score)
            except (TypeError, ValueError) as exc:
                raise ValueError("Reranker API returned an invalid score.") from exc

            if 0 <= index < candidate_count:
                scores[index] = score

        return scores

