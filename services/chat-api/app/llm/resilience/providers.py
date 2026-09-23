"""Provider list construction from declarative config (007 T005 / FR-8).

Provider order (primary -> backups) is declared in
``app/config/resilience.yaml``; when the file is missing or malformed the
resilience layer degrades to a *single* provider built from the existing
``get_llm_client`` factory — i.e. exactly today's behavior (FR-9, no behavior
change for single-provider deployments).

Example ``resilience.yaml``::

    providers:
      - name: primary
        kind: default            # default | azure | qwen
        model: gpt-5.2
      - name: backup
        kind: azure
        model: gpt-5.2
    retry:
      base_seconds: 1.5
      max_seconds: 30.0
      max_attempts: 3
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import yaml

from ...llm.base import BaseLLMClient
from .failover import ProviderEntry
from .retry import RetryPolicy

_CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
DEFAULT_CONFIG_PATH = _CONFIG_DIR / "resilience.yaml"

_DEFAULT_RETRY = RetryPolicy()


def _default_client() -> BaseLLMClient:
    # Imported lazily so config parsing stays importable without pulling the
    # whole LLM factory (and its driver deps) just to read a YAML file.
    from ...llm.factory import get_llm_client

    return get_llm_client(streaming=True)


def _client_factory(model: Optional[str]) -> Callable[[], BaseLLMClient]:
    def _build() -> BaseLLMClient:
        from ...llm.factory import get_llm_client

        return get_llm_client(streaming=True, model_name=model)

    return _build


def load_retry_policy(document: Dict[str, Any]) -> RetryPolicy:
    retry = document.get("retry") if isinstance(document.get("retry"), dict) else {}
    return RetryPolicy(
        base_seconds=float(retry.get("base_seconds", _DEFAULT_RETRY.base_seconds)),
        max_seconds=float(retry.get("max_seconds", _DEFAULT_RETRY.max_seconds)),
        max_attempts=int(retry.get("max_attempts", _DEFAULT_RETRY.max_attempts)),
        jitter_seconds=float(retry.get("jitter_seconds", _DEFAULT_RETRY.jitter_seconds)),
    )


def build_provider_entries(
    document: Dict[str, Any],
    *,
    default: Callable[[], BaseLLMClient] | None = None,
) -> List[ProviderEntry]:
    """Turn a parsed config document into an ordered provider list.

    Falls back to a single provider (the current factory default) when the
    document declares no providers — single-provider deployments keep today's
    behavior (FR-9).
    """
    policy = load_retry_policy(document)
    providers = document.get("providers")
    entries: List[ProviderEntry] = []
    if isinstance(providers, list):
        for item in providers:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            model = item.get("model")
            model = str(model) if model else None
            entries.append(ProviderEntry(name, _client_factory(model), policy))
    if not entries:
        factory = default or _default_client
        entries.append(ProviderEntry("default", factory, policy))
    return entries


def load_resilience_config(path: str | Path | None = None) -> Dict[str, Any]:
    """Load the resilience config; return an empty dict when absent/unreadable."""
    target = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    try:
        if not target.exists():
            return {}
        with target.open("r", encoding="utf-8") as handle:
            document = yaml.safe_load(handle)
    except Exception:
        return {}
    return document if isinstance(document, dict) else {}


def get_resilient_llm_client(
    *,
    path: str | Path | None = None,
    on_event: Callable[[Dict[str, Any]], None] | None = None,
) -> "ResilientLLMClient":
    """Build a ``ResilientLLMClient`` from config (single provider if unset)."""
    from .failover import ResilientLLMClient

    document = load_resilience_config(path)
    entries = build_provider_entries(document)
    return ResilientLLMClient(entries, on_event=on_event)
