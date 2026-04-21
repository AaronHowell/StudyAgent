"""Embedding provider implementations for PaperLab."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import math
import re
from typing import Any

import httpx


@dataclass(slots=True)
class OpenAICompatibleEmbeddingConfig:
    """Connection settings for an OpenAI-compatible embedding endpoint.

    作用:
        统一承载嵌入模型服务地址、鉴权和模型名，供集成层适配器复用。
    """

    base_url: str
    api_key: str
    model: str
    timeout_seconds: float = 60.0
    max_input_tokens: int = 480


class OpenAICompatibleEmbeddingProvider:
    """Embedding provider backed by an OpenAI-compatible `/embeddings` API.

    作用:
        为当前项目提供最小可用的真实嵌入能力，支持文档、chunk 和视觉资产摘要写入 Qdrant。
    """

    def __init__(self, config: OpenAICompatibleEmbeddingConfig) -> None:
        """Create one embedding provider instance.

        Args:
            config: 嵌入服务配置。
        """

        self.config = config
        self._endpoint = f"{config.base_url.rstrip('/')}/embeddings"

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of text inputs through the configured API.

        Args:
            texts: 待嵌入的文本列表。

        Returns:
            list[list[float]]: 与输入一一对应的向量列表。

        Raises:
            ValueError: 当输入为空或响应形状非法时抛出。
            httpx.HTTPError: 当远端请求失败时抛出。
        """

        if not texts:
            return []

        prepared_texts = [self._prepare_text_for_embedding(text) for text in texts]

        payload = {
            "model": self.config.model,
            "input": prepared_texts,
        }
        response = self._post_embeddings(payload)
        data = response.get("data")
        if not isinstance(data, list):
            raise ValueError("Embedding API response missing 'data' list.")

        try:
            sorted_items = sorted(data, key=lambda item: int(item["index"]))
            return [list(item["embedding"]) for item in sorted_items]
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Embedding API returned an unexpected payload shape.") from exc

    def embed_images(self, image_paths: list[str]) -> list[list[float]]:
        """Embed image paths by converting them to textual surrogates for now.

        作用:
            当前项目的图片索引主要依赖 caption/summary 文本，因此这里保留接口但不直接走图像二进制。

        Args:
            image_paths: 图片路径列表。

        Returns:
            list[list[float]]: 占位文本嵌入结果。
        """

        surrogate_texts = [f"image:{Path(path).name}" for path in image_paths]
        return self.embed_texts(surrogate_texts)

    def _post_embeddings(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Send one embedding request and return the decoded JSON payload.

        Args:
            payload: 请求体。

        Returns:
            dict[str, Any]: 服务端 JSON 响应。
        """

        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"

        with httpx.Client(timeout=self.config.timeout_seconds) as client:
            response = client.post(self._endpoint, json=payload, headers=headers)
            response.raise_for_status()
            return response.json()

    def _prepare_text_for_embedding(self, text: str) -> str:
        """Normalize and truncate text before sending it to the embedding model.

        Args:
            text: 原始文本。

        Returns:
            str: 归一化并裁剪后的文本，尽量不超过配置的 token 预算。
        """

        normalized = " ".join(text.split())
        if not normalized:
            return ""
        return self._truncate_to_token_budget(normalized, self.config.max_input_tokens)

    @staticmethod
    def _truncate_to_token_budget(text: str, max_tokens: int) -> str:
        """Truncate text using a conservative approximate token counter.

        作用:
            当前后端 embedding 模型最大上下文较小，不能把整段长文本直接送进去。
            这里用保守估算控制输入长度：
            - CJK 单字符按 1 token 估算
            - 英文/数字连续片段按 `ceil(len / 4)` 估算
            - 其它符号按 1 token 估算

        Args:
            text: 待裁剪文本。
            max_tokens: 允许的近似 token 上限。

        Returns:
            str: 裁剪后的文本。
        """

        if max_tokens <= 0 or not text:
            return ""

        parts = re.findall(r"[\u4e00-\u9fff]|[A-Za-z0-9_]+|[^\s]", text)
        budget = 0
        kept_parts: list[str] = []

        for part in parts:
            if re.fullmatch(r"[\u4e00-\u9fff]", part):
                token_cost = 1
            elif re.fullmatch(r"[A-Za-z0-9_]+", part):
                token_cost = max(1, math.ceil(len(part) / 4))
            else:
                token_cost = 1

            if budget + token_cost > max_tokens:
                break

            kept_parts.append(part)
            budget += token_cost

        clipped = " ".join(kept_parts).strip()
        if clipped == text:
            return clipped
        return f"{clipped} ..."

