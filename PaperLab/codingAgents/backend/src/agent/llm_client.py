"""LLM 客户端 — 封装 OpenAI 兼容 API 调用。"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from configs.settings import Settings

logger = logging.getLogger(__name__)


class LLMClient:
    """OpenAI 兼容的 LLM 客户端。"""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.settings.llm_base_url,
                headers={
                    "Authorization": f"Bearer {self.settings.llm_api_key}",
                    "Content-Type": "application/json",
                },
                timeout=httpx.Timeout(self.settings.llm_timeout, connect=10),
            )
        return self._client

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> dict[str, Any]:
        """调用 LLM chat completion。"""
        body: dict[str, Any] = {
            "model": self.settings.llm_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"

        try:
            resp = await self.client.post("/chat/completions", json=body)
            resp.raise_for_status()
            data = resp.json()
            choice = data["choices"][0]
            message = choice["message"]
            return {
                "content": message.get("content") or "",
                "tool_calls": message.get("tool_calls") or [],
                "finish_reason": choice.get("finish_reason", ""),
            }
        except httpx.HTTPStatusError as e:
            logger.error("LLM API error: %s %s", e.response.status_code, e.response.text[:500])
            raise
        except Exception as e:
            logger.error("LLM call failed: %s", e)
            raise

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
