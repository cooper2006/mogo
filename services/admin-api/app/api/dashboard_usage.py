"""Usage-dimension dashboard aggregations (008 T014 / T015).

These helpers add the *usage* dimension on top of the shared 008 base
(``dashboard_metrics``): call-count time series, deduplicated active users
(per day/week/month), and skill / retrieval frequency ranking.

All helpers are pure over an injected fake DB / pre-fetched rows so they are
unit-testable without a live MongoDB.

* T014: call volume time series + active-user dedup (key = user_id, day/week/month)
* T015: skill / retrieval frequency (ranked by skill name / retrieval type)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

from .dashboard_metrics import tenant_match, window_start

# Active-user dedup grains (T014).
GRAINS: tuple[str, ...] = ("day", "week", "month")


def bucket_rows_by_grain(
    rows: Iterable[dict[str, Any]], *, grain: str = "day"
) -> dict[str, dict[str, Any]]:
    """Group pre-fetched ``token_usage_logs`` rows into UTC time buckets.

    Returns ``{bucket_key: {"calls", "tokens", "cost", "user_ids"}}`` where
    ``bucket_key`` is ``YYYY-MM-DD`` / ``YYYY-Www`` / ``YYYY-MM`` depending on
    the grain (T014 time-series data for the 008 usage tab / T022).
    """
    grain = grain if grain in GRAINS else "day"
    buckets: dict[str, dict[str, Any]] = {}
    for row in rows:
        created = row.get("created_at")
        if isinstance(created, datetime):
            dt = created if created.tzinfo else created.replace(tzinfo=timezone.utc)
        else:
            continue
        dt = dt.astimezone(timezone.utc)
        if grain == "day":
            key = dt.strftime("%Y-%m-%d")
        elif grain == "week":
            iso_year, iso_week, _ = dt.isocalendar()
            key = f"{iso_year}-W{iso_week:02d}"
        else:  # month
            key = dt.strftime("%Y-%m")
        bucket = buckets.setdefault(
            key, {"calls": 0, "tokens": 0, "cost": 0.0, "user_ids": set()}
        )
        bucket["calls"] += 1
        bucket["tokens"] += int(row.get("total_tokens") or 0)
        bucket["cost"] += float(row.get("cost_estimate_usd") or row.get("cost") or 0.0)
        user_id = str(row.get("user_id") or "").strip()
        if user_id:
            bucket["user_ids"].add(user_id)
    for bucket in buckets.values():
        bucket["active_users"] = len(bucket.pop("user_ids"))
        bucket["cost"] = round(bucket["cost"], 6)
    return buckets


def usage_time_series(rows: Iterable[dict[str, Any]], *, grain: str = "day") -> list[dict[str, Any]]:
    """T014 / T022: the call-volume time series (bucket key + metrics, sorted)."""
    series: list[dict[str, Any]] = []
    for key in sorted(bucket_rows_by_grain(rows, grain=grain)):
        bucket = bucket_rows_by_grain(rows, grain=grain)[key]
        series.append({"bucket": key, **bucket})
    return series


def active_user_counts(rows: Iterable[dict[str, Any]], *, grains: Iterable[str] = ("day", "week", "month")) -> dict[str, int]:
    """T014: deduplicated active users per grain (dedup key = user_id).

    A user active in any bucket of a grain counts once for that grain.
    """
    result: dict[str, int] = {}
    for grain in grains:
        if grain not in GRAINS:
            continue
        users: set[str] = set()
        for row in rows:
            user_id = str(row.get("user_id") or "").strip()
            if user_id:
                users.add(user_id)
        result[grain] = len(users)
    return result


def rank_frequency(rows: Iterable[dict[str, Any]], *, key: str, top_n: int = 10) -> list[dict[str, Any]]:
    """T015: rank rows by a frequency key (skill name / retrieval type).

    ``key`` names the row field to aggregate on (e.g. ``skill_name`` or
    ``retrieval_type``); rows missing the value fall into ``未命名``.
    """
    buckets: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key) or "").strip() or "未命名"
        buckets[value] = buckets.get(value, 0) + 1
    ranked = [
        {"key": name, "count": count}
        for name, count in sorted(buckets.items(), key=lambda item: item[1], reverse=True)
    ]
    return ranked[: max(1, int(top_n))]


def empty_usage_section() -> dict[str, Any]:
    """T025: the empty-tenant / empty-data fallback for the usage dimension (FR-9)."""
    return {
        "calls": 0,
        "activeUsers": {},
        "skillRanking": [],
        "retrievalRanking": [],
        "timeSeries": [],
    }
