"""Standalone Redis cache/lock store for PaperLab runtime state."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha1
import json
from typing import Any

try:
    import redis
except ImportError:  # pragma: no cover
    redis = None  # type: ignore[assignment]


@dataclass(slots=True)
class RedisCacheConfig:
    host: str
    port: int
    password: str = ""
    db: int = 0
    decode_responses: bool = True


class RedisCacheStore:
    """Small JSON cache and lock wrapper over a single Redis instance."""

    def __init__(
        self,
        config: RedisCacheConfig | None = None,
        *,
        client: Any | None = None,
    ) -> None:
        self.config = config
        if client is not None:
            self.client = client
        else:
            if redis is None:
                raise RuntimeError("redis is not installed. Install redis-py to enable Redis cache.")
            if config is None:
                raise ValueError("RedisCacheConfig is required when no client is provided.")
            self.client = redis.Redis(
                host=config.host,
                port=config.port,
                password=config.password or None,
                db=config.db,
                decode_responses=config.decode_responses,
            )

    def get_json(self, key: str) -> dict[str, Any] | None:
        raw = self.client.get(key)
        if not raw:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return json.loads(raw)

    def set_json(self, key: str, payload: dict[str, Any], ttl_seconds: int) -> None:
        self.client.set(key, json.dumps(payload, ensure_ascii=False), ex=ttl_seconds)

    def delete(self, key: str) -> None:
        self.client.delete(key)

    def acquire_lock(self, key: str, ttl_seconds: int) -> bool:
        return bool(self.client.set(key, "1", ex=ttl_seconds, nx=True))

    def release_lock(self, key: str) -> None:
        self.client.delete(key)

    def thread_lock_key(self, thread_id: str) -> str:
        return f"studyagent:lock:thread:{thread_id}"

    def save_thread_context(self, thread_id: str, payload: dict[str, Any], ttl_seconds: int = 21600) -> None:
        self.set_json(f"studyagent:thread:{thread_id}:context", payload, ttl_seconds)

    def load_thread_context(self, thread_id: str) -> dict[str, Any] | None:
        return self.get_json(f"studyagent:thread:{thread_id}:context")

    def save_cached_retrieval(self, project_id: str, query: str, payload: dict[str, Any], ttl_seconds: int = 3600) -> None:
        self.set_json(self._retrieval_key(project_id, query), payload, ttl_seconds)

    def load_cached_retrieval(self, project_id: str, query: str) -> dict[str, Any] | None:
        return self.get_json(self._retrieval_key(project_id, query))

    def save_cached_web_search(self, query: str, payload: dict[str, Any], ttl_seconds: int = 1800) -> None:
        self.set_json(self._web_search_key(query), payload, ttl_seconds)

    def load_cached_web_search(self, query: str) -> dict[str, Any] | None:
        return self.get_json(self._web_search_key(query))

    def save_cached_url_fetch(self, url: str, payload: dict[str, Any], ttl_seconds: int = 3600) -> None:
        self.set_json(self._url_fetch_key(url), payload, ttl_seconds)

    def load_cached_url_fetch(self, url: str) -> dict[str, Any] | None:
        return self.get_json(self._url_fetch_key(url))

    @staticmethod
    def _retrieval_key(project_id: str, query: str) -> str:
        return f"studyagent:cache:retrieval:{project_id}:{_digest(query)}"

    @staticmethod
    def _web_search_key(query: str) -> str:
        return f"studyagent:cache:web_search:{_digest(query)}"

    @staticmethod
    def _url_fetch_key(url: str) -> str:
        return f"studyagent:cache:url_fetch:{_digest(url)}"


def _digest(value: str) -> str:
    return sha1(value.encode("utf-8")).hexdigest()[:16]

