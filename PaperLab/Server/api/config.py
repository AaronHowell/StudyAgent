"""Backward-compatible API settings import path."""

from configs.settings.api_settings import Settings, _load_env_files

__all__ = [
    "Settings",
    "_load_env_files",
]



