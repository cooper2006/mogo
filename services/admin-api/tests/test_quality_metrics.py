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
    COLLECTOR_STATE_COLLECTION,
    LOW_QUALITY_SUSTAINED_DAYS,
    MIN_EFFECT_SAMPLES,
    PROJECTIONS_COLLECTION,
    QUALITY_METRICS_COLLECTION,
    collect_skill_activity_metrics,
    evaluate_all,
    evaluate_skill_quality,
    record_skill_call,
)


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def sort(self, key, direction=1):
        reverse = int(direction) < 0
        self._rows = sorted(self._rows, key=lambda r: r.get(key) or 0, reverse=reverse)
        return self

    def limit(self, count):
        self._rows = list(self._rows)[: int(count)]
        return self

    async def to_list(self, length=0):
        return list(self._rows)


def _dig(doc, dotted):
    cur = doc
    for part in str(dotted).split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _matches_row(row, flt):
    for k, v in flt.items():
        actual = _dig(row, k)
        if isinstance(v, dict) and "$gt" in v:
            if not (actual is not None and actual > v["$gt"]):
                return False
        elif isinstance(v, dict) and "$gte" in v:
            if str(actual or "") < str(v["$gte"]):
                return False
        elif isinstance(v, dict) and "$lte" in v:
            if str(actual or "") > str(v["$lte"]):
                return False
        elif actual != v:
            return False
    return True


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def find(self, flt, projection=None):
        return _FakeResult([r for r in self._rows if _matches_row(r, flt)])

    async def find_one(self, flt, projection=None):
        for r in self._rows:
            if _matches_row(r, flt):
                return dict(r)
        return None

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
    # Four collections are touched: metric buckets (read/score), the shared adoption
    # bit, chat-api's kernel projections (collected), and the collector watermark.
    shared = list(rows)
    metrics = _FakeCursor(shared)
    adoption = _FakeCursor([])
    projections = _FakeCursor([])
    state = _FakeCursor([])

    class _Db:
        def __getitem__(self, name):
            if name == QUALITY_METRICS_COLLECTION:
                return metrics
            if name == ADOPTION_COLLECTION:
                return adoption
            if name == PROJECTIONS_COLLECTION:
                return projections
            if name == COLLECTOR_STATE_COLLECTION:
                return state
            raise AssertionError(f"unexpected collection {name}")

    return _Db(), metrics, adoption, projections, state


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
    db, cursor, _adoption, _proj, _state = _fake_db([])
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
    db, cursor, _adoption, _proj, _state = _fake_db([])
    _seed_low_days(cursor, main_id="t1", skill_key="weak", days=LOW_QUALITY_SUSTAINED_DAYS)

    outcome = asyncio.run(evaluate_skill_quality(db, main_id="t1", skill_key="weak"))
    assert outcome["marked_low_quality"] is True
    assert outcome["sustained_low_days"] >= LOW_QUALITY_SUSTAINED_DAYS
    # The 016 write loop surfaces through the shared reader the market list uses.
    marked = asyncio.run(fetch_marked_skill_keys(db, main_id="t1"))
    assert marked == {"weak"}


def test_interrupted_window_resets_sustained_streak():
    db, cursor, _adoption, _proj, _state = _fake_db([])
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
    db, cursor, _adoption, _proj, _state = _fake_db([])
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
    db, cursor, _adoption, _proj, _state = _fake_db([])
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


def _activity_row(tenant_id, source_id, seq, day=None):
    return {
        "tenant_id": tenant_id,
        "item_kind": "activity",
        "type": "item.completed",
        "event_id": f"dsh-v3:{seq}",
        "item_id": f"m{seq}:selected-skill:{source_id}",
        "stream_seq": seq,
        "payload": {"category": "skill", "skill_name": f"name-{source_id}"},
        "created_at": day,
    }


def test_collect_skill_activity_writes_total_and_advances_watermark():
    from datetime import datetime, timezone

    db, cursor, _adoption, proj, state = _fake_db([])
    today = datetime.now(timezone.utc)
    proj._rows.extend(
        [
            _activity_row("t1", "skill-a", 10, today),
            _activity_row("t1", "skill-a", 11, today),
            _activity_row("t2", "skill-b", 12, today),
        ]
    )

    result = asyncio.run(collect_skill_activity_metrics(db))
    assert result["collected"] == 3
    assert result["last_stream_seq"] == 12
    buckets = {(r["main_id"], r["skill_key"]): r["total_calls"] for r in cursor._rows}
    assert buckets[("t1", "skill-a")] == 2
    assert buckets[("t2", "skill-b")] == 1
    # Watermark persisted -> a second pass re-reads nothing (idempotent).
    again = asyncio.run(collect_skill_activity_metrics(db))
    assert again["collected"] == 0
    assert again["last_stream_seq"] == 12
    assert state._rows[0]["last_stream_seq"] == 12


def test_total_only_metrics_are_not_scored_mass_marked():
    # Regression guard: with only total_calls (no success/adoption/correction
    # verdict yet) the score would be 0.2 < 0.4 and would mass-mark every skill.
    # The completeness gate must skip instead.
    db, cursor, _adoption, _proj, _state = _fake_db([])
    for offset in range(LOW_QUALITY_SUSTAINED_DAYS):
        day = (date.today() - timedelta(days=offset)).isoformat()
        cursor._rows.append(
            {
                "main_id": "t1",
                "skill_key": "totalonly",
                "date": day,
                "total_calls": 100,
                "successful_calls": 0,
                "adopted_calls": 0,
                "corrected_calls": 0,
            }
        )
    outcome = asyncio.run(evaluate_skill_quality(db, main_id="t1", skill_key="totalonly"))
    assert outcome["evaluated"] is False
    assert outcome["reason"] == "insufficient_signal"
    # Nothing was written to the shared bit -> the market keeps it ranked normally.
    assert asyncio.run(fetch_marked_skill_keys(db, main_id="t1")) == set()


def test_below_min_samples_is_not_scored():
    db, cursor, _adoption, _proj, _state = _fake_db([])
    for offset in range(LOW_QUALITY_SUSTAINED_DAYS):
        day = (date.today() - timedelta(days=offset)).isoformat()
        cursor._rows.append(
            {
                "main_id": "t1",
                "skill_key": "rare",
                "date": day,
                "total_calls": 2,  # below MIN_EFFECT_SAMPLES
                "successful_calls": 0,
                "adopted_calls": 1,
                "corrected_calls": 1,
            }
        )
    outcome = asyncio.run(evaluate_skill_quality(db, main_id="t1", skill_key="rare"))
    assert outcome["evaluated"] is False
    assert MIN_EFFECT_SAMPLES > 2
