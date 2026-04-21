"""OpenAI-compatible LLM provider implementations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import httpx


@dataclass(slots=True)
class OpenAICompatibleLLMConfig:
    """Connection settings for an OpenAI-compatible chat-completions endpoint."""

    base_url: str
    api_key: str
    model: str
    timeout_seconds: float = 120.0


class OpenAICompatibleLLMProvider:
    """LLM provider backed by an OpenAI-compatible `/chat/completions` API."""

    def __init__(self, config: OpenAICompatibleLLMConfig) -> None:
        self.config = config
        self._endpoint = f"{config.base_url.rstrip('/')}/chat/completions"

    def generate(self, prompt: str) -> str:
        payload = self._build_payload(prompt, stream=False)
        response = self._post_chat(payload)
        choices = response.get("choices", [])
        if not choices:
            return ""
        return str(choices[0].get("message", {}).get("content", ""))

    def stream_generate(self, prompt: str) -> Iterable[str]:
        payload = self._build_payload(prompt, stream=True)
        headers = self._build_headers()
        with httpx.Client(timeout=self.config.timeout_seconds) as client:
            with client.stream("POST", self._endpoint, json=payload, headers=headers) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line:
                        continue
                    if not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data.strip() == "[DONE]":
                        break
                    chunk = self._extract_stream_delta(data)
                    if chunk:
                        yield chunk

    def _post_chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        with httpx.Client(timeout=self.config.timeout_seconds) as client:
            response = client.post(self._endpoint, json=payload, headers=self._build_headers())
            response.raise_for_status()
            return response.json()

    def _build_payload(self, prompt: str, *, stream: bool) -> dict[str, Any]:
        return {
            "model": self.config.model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": stream,
        }

    def _build_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return headers

    @staticmethod
    def _extract_stream_delta(data: str) -> str:
        import json

        payload = json.loads(data)
        choices = payload.get("choices", [])
        if not choices:
            return ""
        delta = choices[0].get("delta", {})
        return str(delta.get("content", ""))
