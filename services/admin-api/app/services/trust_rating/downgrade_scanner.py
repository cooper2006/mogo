"""036 trust-rating periodic downgrade scanner (FR-10 / FR-11).

A background loop (mirroring 016 :class:`SkillQualityScanner`) periodically walks
every tenant's existing ratings, resolves the quality signal (032 -> 016 fallback)
and applies :func:`next_downgrade_action`:

* ``downgrade``  — atomically drop one level, reset the streak, audit (FR-11);
* ``deprecate``  — L1 that still fails: record the deprecation intent + audit;
* ``reset_streak`` / ``none`` — record the running streak only.

The scan is O(ratings that exist) and every failure path is best-effort: a DB or
loop error must never break the scan or the app. A single-document scan state
mirrors 016 ``COLLECTOR_STATE_COLLECTION`` (FR-10).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from app.services.trust_rating.ratings import (
    RATINGS_COLLECTION,
    SCAN_STATE_COLLECTION,
    SCAN_STATE_ID,
    get_downgrade_settings,
    recompute_rating,
    validate_asset,
)

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def run_downgrade_scan(db: Any, *, tenant_id: str = "") -> int:
    """One scan pass; returns the number of ratings evaluated.

    ``tenant_id`` narrows the pass to one tenant. A tenant whose switch is closed
    is skipped untouched, so accumulated ``below_since`` survives a temporary
    disable (spec edge case).
    """
    if db is None:
        return 0
    flt: dict[str, Any] = {"tenant_id": tenant_id} if tenant_id else {}
    rows = await db[RATINGS_COLLECTION].find(flt).to_list(length=10000)
    evaluated = 0
    for row in rows:
        try:
            asset_type, asset_key = validate_asset(str(row.get("asset_type")), str(row.get("asset_key")))
        except ValueError:
            # 孤儿/非法评级容忍：不阻断整轮扫描。
            logger.warning(
                "trust rating scan skipped invalid asset: %s",
                {k: row.get(k) for k in ("tenant_id", "asset_type", "asset_key")},
            )
            continue
        tenant = str(row.get("tenant_id") or "default")
        settings = await get_downgrade_settings(db, tenant)
        if not bool(settings["enabled"]):
            continue
        await recompute_rating(
            db,
            tenant_id=tenant,
            asset_type=asset_type,
            asset_key=asset_key,
            actor="system:downgrade-scanner",
        )
        evaluated += 1
    await db[SCAN_STATE_COLLECTION].update_one(
        {"_id": SCAN_STATE_ID},
        {
            "$set": {
                "last_run_at": _utcnow(),
                "last_tenant": str(tenant_id or ""),
                "evaluated": evaluated,
            }
        },
        upsert=True,
    )
    return evaluated


class TrustRatingDowngradeScanner:
    """Periodic trigger for :func:`run_downgrade_scan` (started from the lifespan)."""

    def __init__(
        self,
        *,
        db: Any = None,
        interval_seconds: Optional[float] = None,
    ) -> None:
        self._db = db
        self._interval_seconds = interval_seconds
        self._task: Optional[asyncio.Task] = None
        self._stopping = asyncio.Event()

    @property
    def interval_seconds(self) -> float:
        from app.services.trust_rating.ratings import DEFAULT_SCAN_INTERVAL_SECONDS

        if self._interval_seconds is not None:
            return float(self._interval_seconds)
        return DEFAULT_SCAN_INTERVAL_SECONDS

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stopping.clear()
        self._task = asyncio.create_task(self._loop(), name="trust-rating-downgrade-scanner")

    async def stop(self) -> None:
        self._stopping.set()
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def _loop(self) -> None:
        from app.core.db import get_db

        while not self._stopping.is_set():
            try:
                db = self._db if self._db is not None else get_db()
                await run_downgrade_scan(db)
            except Exception:  # pragma: no cover - defensive
                logger.exception("trust rating downgrade scan failed")
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=self.interval_seconds)
            except asyncio.TimeoutError:
                pass


__all__ = ["TrustRatingDowngradeScanner", "run_downgrade_scan"]