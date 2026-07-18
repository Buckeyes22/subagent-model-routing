"""Provider adapters for the public transport shims."""

from __future__ import annotations

from .base import ProviderAdapter
from .claude import ClaudeAdapter
from .codex import CodexAdapter
from .grok import GrokAdapter
from .kimi import KimiAdapter
from .opencode import OpenCodeAdapter


_ADAPTERS: dict[str, type[ProviderAdapter]] = {
    "claude": ClaudeAdapter,
    "codex": CodexAdapter,
    "grok": GrokAdapter,
    "kimi": KimiAdapter,
    "opencode": OpenCodeAdapter,
}


def get_adapter(provider_id: str) -> ProviderAdapter:
    try:
        return _ADAPTERS[provider_id]()
    except KeyError as exc:
        raise ValueError(f"unknown provider: {provider_id}") from exc


def adapter_ids() -> set[str]:
    return set(_ADAPTERS)
