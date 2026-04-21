from __future__ import annotations

from functools import lru_cache

from runtime import AgentRuntime
from runtime import create_runtime


@lru_cache(maxsize=1)
def get_runtime() -> AgentRuntime:
    return create_runtime()


def _runtime() -> AgentRuntime:
    return get_runtime()
