"""016 effect-score collection + periodic assessment (closed write loop).

admin-api owns the *read/score* side: chat-api writes daily buckets into
``skill_quality_metrics``; this module rolls them up, computes the weighted effect
score, and persists the result into the shared ``skill_adoption`` bit (016 FR-3/FR-6).

No asyncio pytest mode is configured, so every coroutine is driven via ``asyncio.run``.
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta

from app.services.skill_market.adoption_client import (
    ADOPTION_COLLECTION,
    MARKED_LOW_QUALITY,
    fetch_marked_skill_keys,
)
from app.services.skill_market.quality_metrics import (
    LOW_QUALITY_SUSTAINED_DAYS,
    QUALITY_METRICS_COLLECTION,
    evaluate_all,
    evaluate_skill_quality,
    record_skill_call,
)


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    async def to_list(self, length=0):
        return list(self._rows)


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def find(self, flt, projection=None):
        out = []
        for r in self._rows:
            ok = True
            for k, v in flt.items():
                if isinstance(v, dict) and "$gte" in v:
                    if str(r.get(k) or "") < str(v["$gte"]):
                        ok = False
                elif isinstance(v, dict) and "$lte" in v:
                    if str(r.get(k) or "") > str(v["$lte"]):
                        ok = False
                elif r.get(k) != v:
                    ok = False
            if ok:
                out.append(r)
        return _FakeResult(out)

    def aggregate(self, pipeline):
        # Only the {"$group": {"_id": {"main_id", "skill_key"}}} shape is used.
        seen = {}
        for r in self._rows:
            key = (str(r.get("main_id") or ""), str(r.get("skill_key") or ""))
            seen[key] = True
        return _FakeResult([{"_id": {"main_id": k[0], "skill_key": k[1]}} for k in seen])

    async def update_one(self, flt, update, upsert=False):
        if isinstance(update, list):
            update = update[0]
        doc = None
        for r in self._rows:
            if all(r.get(k) == v for k, v in flt.items()):
                doc = r
                break
        if doc is None:
            if not upsert:
                return
            doc = dict(flt)
            self._rows.append(doc)
        for op, fields in (update or {}).items():
            if op == "$inc":
                for k, v in fields.items():
                    doc[k] = int(doc.get(k) or 0) + int(v)
            elif op == "$set":
                for k, v in fields.items():
                    if isinstance(v, dict) and "$or" in v:
                        doc[k] = any(
                            (doc.get(o.lstrip("$")) if isinstance(o, str) and o.startswith("$") else bool(o))
                            for o in v["$or"]
                        )
                    else:
                        doc[k] = v
            elif op == "$setOnInsert":
                for k, v in fields.items():
                    doc.setdefault(k, v)


def _fake_db(rows):
    # Two collections are touched: the metric buckets (read/score) and the shared
    # adoption bit (written by apply_quality_assessment, read by the market list).
    shared = list(rows)
    metrics = _FakeCursor(shared)
    adoption = _FakeCursor([])

    class _Db:
        def __getitem__(self, name):
            if name == QUALITY_METRICS_COLLECTION:
                return metrics
            if name == ADOPTION_COLLECTION:
                return adoption
            raise AssertionError(f"unexpected collection {name}")

    return _Db(), metrics, adoption


def _seed_low_days(db_cursor, *, main_id, skill_key, days, success=False):
    """Seed ``days`` consecutive daily buckets, all below the 0.4 effect threshold."""
    for offset in range(days):
        day = (date.today() - timedelta(days=offset)).isoformat()
        db_cursor._rows.append(
            {
                "main_id": main_id,
                "skill_key": skill_key,
                "date": day,
                "total_calls": 100,
                # success 0.1, adoption 0.1, correction 0.8 -> score ~0.12 (low)
                "successful_calls": 10 if success else 10,
                "adopted_calls": 10,
                "corrected_calls": 80,
            }
        )


def test_record_skill_call_accumulates_daily_buckets():
    db, cursor, _adoption = _fake_db([])
    asyncio.run(
        record_skill_call(db, main_id="t1", skill_key="s", success=True, adopted=1, corrected=0)
    )
    asyncio.run(
        record_skill_call(db, main_id="t1", skill_key="s", success=False, adopted=0, corrected=1)
    )
    bucket = [r for r in cursor._rows if r["main_id"] == "t1" and r["skill_key"] == "s"][0]
    assert bucket["total_calls"] == 2
    assert bucket["successful_calls"] == 1
    assert bucket["adopted_calls"] == 1
    assert bucket["corrected_calls"] == 1


def test_sustained_low_quality_marks_shared_bit():
    db, cursor, _adoption = _fake_db([])
    _seed_low_days(cursor, main_id="t1", skill_key="weak", days=LOW_QUALITY_SUSTAINED_DAYS)

    outcome = asyncio.run(evaluate_skill_quality(db, main_id="t1", skill_key="weak"))
    assert outcome["marked_low_quality"] is True
    assert outcome["sustained_low_days"] >= LOW_QUALITY_SUSTAINED_DAYS
    # The 016 write loop surfaces through the shared reader the market list uses.
    marked = asyncio.run(fetch_marked_skill_keys(db, main_id="t1"))
    assert marked == {"weak"}


def test_interrupted_window_resets_sustained_streak():
    db, cursor, _adoption = _fake_db([])
    _seed_low_days(cursor, main_id="t1", skill_key="weak", days=LOW_QUALITY_SUSTAINED_DAYS)
    # Insert one healthy day in the middle of the window -> streak breaks.
    mid = (date.today() - timedelta(days=3)).isoformat()
    cursor._rows.append(
        {
            "main_id": "t1",
            "skill_key": "weak",
            "date": mid,
            "total_calls": 100,
            "successful_calls": 90,
            "adopted_calls": 80,
            "corrected_calls": 5,
        }
    )
    outcome = asyncio.run(evaluate_skill_quality(db, main_id="t1", skill_key="weak"))
    assert outcome["sustained_low_days"] < LOW_QUALITY_SUSTAINED_DAYS
    # Not sustained long enough -> aggregated bit stays clear.
    marked = asyncio.run(fetch_marked_skill_keys(db, main_id="t1"))
    assert marked == set()


def test_healthy_skill_is_not_marked():
    db, cursor, _adoption = _fake_db([])
    for offset in range(LOW_QUALITY_SUSTAINED_DAYS):
        day = (date.today() - timedelta(days=offset)).isoformat()
        cursor._rows.append(
            {
                "main_id": "t1",
                "skill_key": "good",
                "date": day,
                "total_calls": 100,
                "successful_calls": 95,
                "adopted_calls": 80,
                "corrected_calls": 5,
            }
        )
    outcome = asyncio.run(evaluate_skill_quality(db, main_id="t1", skill_key="good"))
    assert outcome["marked_low_quality"] is False
    assert asyncio.run(fetch_marked_skill_keys(db, main_id="t1")) == set()


def test_evaluate_all_scores_every_key():
    db, cursor, _adoption = _fake_db([])
    _seed_low_days(cursor, main_id="t1", skill_key="weak", days=LOW_QUALITY_SUSTAINED_DAYS)
    _seed_low_days(cursor, main_id="t1", skill_key="weaker", days=LOW_QUALITY_SUSTAINED_DAYS)
    # A different tenant must not leak.
    _seed_low_days(cursor, main_id="t2", skill_key="weak2", days=LOW_QUALITY_SUSTAINED_DAYS)

    scored = asyncio.run(evaluate_all(db))
    assert scored == 3
    marked_t1 = asyncio.run(fetch_marked_skill_keys(db, main_id="t1"))
    assert marked_t1 == {"weak", "weaker"}


def test_scanner_starts_and_stops_cleanly():
    # The periodic trigger must start a task and cancel it on stop without
    # leaking (the app lifespan calls exactly this pair).
    from app.services.skill_market.quality_metrics import SkillQualityScanner

    scanner = SkillQualityScanner(db=None, interval_seconds=3600.0)

    async def _cycle():
        await scanner.start()
        assert scanner._task is not None and not scanner._task.done()
        await scanner.stop()
        assert scanner._task is None

    asyncio.run(_cycle())
