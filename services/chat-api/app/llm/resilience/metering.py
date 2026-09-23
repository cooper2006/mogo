"""Dimension aggregation of LLM usage + cost for the 008 dashboard (007 T020).

Aggregates ``token_usage_logs`` by provider / model / tenant / agent dimension
(FR-6). The aggregation is *pure*: given a list of already-fetched rows it
returns pre-bucketed totals, so it is unit-testable with in-memory data and
reusable by either 008 (cost tab) or an export endpoint.

Provider dimension: ``model_router`` / provider metadata are not stored per row
in ``token_usage_logs`` (the record keeps ``model_name`` / ``model_id``), so the
provider is derived from the model name prefix mapping when a row has no
explicit ``provider`` field. The agent dimension reads the ``agent_id`` field
(FR-6: agent dimension takes the call's ``agent_id``).
"""

from __future__ import annotations

from typing import Any, Iterable

# Known model-name prefix -> provider mapping (mirrors llm/providers names).
_PROVIDER_PREFIXES: dict[str, str] = {
    "deepseek": "deepseek",
    "gpt": "openai",
    "qwen": "qwen",
    "azure": "azure",
}


def _provider_for(model_name: str, row: dict[str, Any]) -> str:
    explicit = str(row.get("provider") or "").strip()
    if explicit:
        return explicit
    lower = str(model_name or "").lower()
    for prefix, provider in _PROVIDER_PREFIXES.items():
        if lower.startswith(prefix):
            return provider
    return "unknown"


def aggregate_usage(rows: Iterable[dict[str, Any]], *, dimension: str) -> list[dict[str, Any]]:
    """Bucket rows by ``dimension`` (provider | model | tenant | agent).

    Returns one row per bucket with summed tokens / calls / cost, sorted by cost
    descending (the 008 cost tab wants the most expensive buckets first).
    """
    dimension = str(dimension or "model").strip().lower()
    if dimension not in ("provider", "model", "tenant", "agent"):
        dimension = "model"

    buckets: dict[str, dict[str, Any]] = {}
    for row in rows:
        if dimension == "provider":
            key = _provider_for(str(row.get("model_name") or ""), row)
        elif dimension == "model":
            key = str(row.get("model_name") or row.get("model_id") or "").strip() or "unknown"
        elif dimension == "tenant":
            key = str(row.get("main_id") or "").strip() or "unknown"
        else:  # agent
            key = str(row.get("agent_id") or row.get("node_id") or "").strip() or "unknown"

        bucket = buckets.setdefault(
            key,
            {
                "dimension": dimension,
                "key": key,
                "calls": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "cost": 0.0,
            },
        )
        bucket["calls"] += 1
        bucket["prompt_tokens"] += int(row.get("prompt_tokens") or 0)
        bucket["completion_tokens"] += int(row.get("completion_tokens") or 0)
        bucket["total_tokens"] += int(row.get("total_tokens") or 0)
        # Cost: prefer the per-row estimate when present (007 T019), else 0.
        bucket["cost"] += float(row.get("cost_estimate_usd") or row.get("cost") or 0.0)

    items = sorted(buckets.values(), key=lambda item: item["cost"], reverse=True)
    for item in items:
        item["cost"] = round(item["cost"], 6)
    return items


__all__ = ["aggregate_usage"]
