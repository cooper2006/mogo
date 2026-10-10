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
    DELIVERIES_COLLECTION,
    EDIT_EVENTS_COLLECTION,
    LOW_QUALITY_SUSTAINED_DAYS,
    MIN_EFFECT_SAMPLES,
    PROJECTIONS_COLLECTION,
    QUALITY_METRICS_COLLECTION,
    RECEIPTS_COLLECTION,
    collect_edit_events,
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
        if isinstance(v, dict) and "$in" in v:
            if actual not in v["$in"]:
                return False
        elif isinstance(v, dict) and "$gt" in v:
            if not (actual is not None and actual > v["$gt"]):
                return False
        elif isinstance(v, dict) and "$gte" in v:
            if actual is None:
                return False
            if isinstance(actual, str) != isinstance(v["$gte"], str):
                return False
            if actual < v["$gte"]:
                return False
        elif isinstance(v, dict) and "$lte" in v:
            if actual is None:
                return False
            if isinstance(actual, str) != isinstance(v["$lte"], str):
                return False
            if actual > v["$lte"]:
                return False
        elif actual != v:
            return False
    return True


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def find(self, flt, projection=None):
        return _FakeResult([r for r in self._rows if _matches_row(r, flt)])

    async def find_one(self, flt, projection=None, sort=None):
        rows = [r for r in self._rows if _matches_row(r, flt)]
        if sort:
            key, direction = sort[0]
            rows = sorted(rows, key=lambda r: r.get(key) or 0, reverse=int(direction) < 0)
        return dict(rows[0]) if rows else None

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
    # Collections touched: metric buckets (read/score), the shared adoption bit,
    # chat-api's kernel projections + deliveries + receipts (collected), the
    # product-edit events, and the collector watermark.
    shared = list(rows)
    metrics = _FakeCursor(shared)
    adoption = _FakeCursor([])
    projections = _FakeCursor([])
    deliveries = _FakeCursor([])
    receipts = _FakeCursor([])
    edits = _FakeCursor([])
    state = _FakeCursor([])

    class _Db:
        def __getitem__(self, name):
            if name == QUALITY_METRICS_COLLECTION:
                return metrics
            if name == ADOPTION_COLLECTION:
                return adoption
            if name == PROJECTIONS_COLLECTION:
                return projections
            if name == DELIVERIES_COLLECTION:
                return deliveries
            if name == RECEIPTS_COLLECTION:
                return receipts
            if name == EDIT_EVENTS_COLLECTION:
                return edits
            if name == COLLECTOR_STATE_COLLECTION:
                return state
            raise AssertionError(f"unexpected collection {name}")

    return _Db(), metrics, adoption, projections, state, deliveries, receipts, edits


def _seed_low_days(db_cursor, *, tenant_id, skill_key, days, success=False):
    """Seed ``days`` consecutive daily buckets, all below the 0.4 effect threshold."""
    for offset in range(days):
        day = (date.today() - timedelta(days=offset)).isoformat()
        db_cursor._rows.append(
            {
                "tenant_id": tenant_id,
                "skill_key": skill_key,
                "date": day,
                "total_calls": 100,
                # success 0.1, adoption 0.1, correction 0.8 -> score ~0.12 (low)
                "successful_calls": 10 if success else 10,
                "adopted_calls": 10,
                "corrected_calls": 80,
                # A real success verdict is present, so the scoring gate passes.
                "success_tracked": True,
            }
        )


def test_record_skill_call_accumulates_daily_buckets():
    db, cursor, _adoption, _proj, _state, _deliv, _recv, _edits = _fake_db([])
    asyncio.run(
        record_skill_call(db, tenant_id="t1", skill_key="s", success=True, adopted=1, corrected=0)
    )
    asyncio.run(
        record_skill_call(db, tenant_id="t1", skill_key="s", success=False, adopted=0, corrected=1)
    )
    bucket = [r for r in cursor._rows if r["tenant_id"] == "t1" and r["skill_key"] == "s"][0]
    assert bucket["total_calls"] == 2
    assert bucket["successful_calls"] == 1
    assert bucket["adopted_calls"] == 1
    assert bucket["corrected_calls"] == 1


def test_sustained_low_quality_marks_shared_bit():
    db, cursor, _adoption, _proj, _state, _deliv, _recv, _edits = _fake_db([])
    _seed_low_days(cursor, tenant_id="t1", skill_key="weak", days=LOW_QUALITY_SUSTAINED_DAYS)

    outcome = asyncio.run(evaluate_skill_quality(db, tenant_id="t1", skill_key="weak"))
    assert outcome["marked_low_quality"] is True
    assert outcome["sustained_low_days"] >= LOW_QUALITY_SUSTAINED_DAYS
    # The 016 write loop surfaces through the shared reader the market list uses.
    marked = asyncio.run(fetch_marked_skill_keys(db, tenant_id="t1"))
    assert marked == {"weak"}


def test_interrupted_window_resets_sustained_streak():
    db, cursor, _adoption, _proj, _state, _deliv, _recv, _edits = _fake_db([])
    _seed_low_days(cursor, tenant_id="t1", skill_key="weak", days=LOW_QUALITY_SUSTAINED_DAYS)
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
            "success_tracked": True,
        }
    )
    outcome = asyncio.run(evaluate_skill_quality(db, tenant_id="t1", skill_key="weak"))
    assert outcome["sustained_low_days"] < LOW_QUALITY_SUSTAINED_DAYS
    # Not sustained long enough -> aggregated bit stays clear.
    marked = asyncio.run(fetch_marked_skill_keys(db, tenant_id="t1"))
    assert marked == set()


def test_healthy_skill_is_not_marked():
    db, cursor, _adoption, _proj, _state, _deliv, _recv, _edits = _fake_db([])
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
                "success_tracked": True,
            }
        )
    outcome = asyncio.run(evaluate_skill_quality(db, tenant_id="t1", skill_key="good"))
    assert outcome["marked_low_quality"] is False
    assert asyncio.run(fetch_marked_skill_keys(db, tenant_id="t1")) == set()


def test_evaluate_all_scores_every_key():
    db, cursor, _adoption, _proj, _state, _deliv, _recv, _edits = _fake_db([])
    _seed_low_days(cursor, tenant_id="t1", skill_key="weak", days=LOW_QUALITY_SUSTAINED_DAYS)
    _seed_low_days(cursor, tenant_id="t1", skill_key="weaker", days=LOW_QUALITY_SUSTAINED_DAYS)
    # A different tenant must not leak.
    _seed_low_days(cursor, tenant_id="t2", skill_key="weak2", days=LOW_QUALITY_SUSTAINED_DAYS)

    scored = asyncio.run(evaluate_all(db))
    assert scored == 3
    marked_t1 = asyncio.run(fetch_marked_skill_keys(db, tenant_id="t1"))
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

    db, cursor, _adoption, proj, state, _deliv, _recv, _edits = _fake_db([])
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
    buckets = {(r["tenant_id"], r["skill_key"]): r["total_calls"] for r in cursor._rows}
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
    db, cursor, _adoption, _proj, _state, _deliv, _recv, _edits = _fake_db([])
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
    outcome = asyncio.run(evaluate_skill_quality(db, tenant_id="t1", skill_key="totalonly"))
    assert outcome["evaluated"] is False
    assert outcome["reason"] == "insufficient_signal"
    # Nothing was written to the shared bit -> the market keeps it ranked normally.
    assert asyncio.run(fetch_marked_skill_keys(db, tenant_id="t1")) == set()


def test_below_min_samples_is_not_scored():
    db, cursor, _adoption, _proj, _state, _deliv, _recv, _edits = _fake_db([])
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
    outcome = asyncio.run(evaluate_skill_quality(db, tenant_id="t1", skill_key="rare"))
    assert outcome["evaluated"] is False
    assert MIN_EFFECT_SAMPLES > 2


# --- OQ-6 richer dimensions ---------------------------------------------------


def _activity_with_message(
    tenant_id, source_id, seq, message_id, session_id, when, selection_mode="automatic"
):
    return {
        "tenant_id": tenant_id,
        "user_id": "u1",
        "item_kind": "activity",
        "type": "item.completed",
        "event_id": f"dsh-v3:{seq}",
        "item_id": f"{message_id}:selected-skill:{source_id}",
        "message_id": message_id,
        "kernel_session_id": session_id,
        "stream_seq": seq,
        "payload": {
            "category": "skill",
            "skill_name": f"name-{source_id}",
            "selection_mode": selection_mode,
        },
        "created_at": when,
    }


def test_adoption_is_attributed_from_accepted_delivery():
    from datetime import datetime, timezone

    db, cursor, _adoption, proj, _state, deliv, _recv, _edits = _fake_db([])
    when = datetime.now(timezone.utc)
    proj._rows.append(_activity_with_message("t1", "skill-a", 10, "m1", "sess-1", when))
    # The turn produced an accepted authoritative delivery -> adopted.
    deliv._rows.append({"tenant_id": "t1", "message_id": "m1", "accepted": True})

    asyncio.run(collect_skill_activity_metrics(db))
    bucket = cursor._rows[0]
    assert bucket["total_calls"] == 1
    assert bucket["adopted_calls"] == 1
    assert bucket["success_tracked"] is True


def test_adoption_absent_without_accepted_delivery():
    from datetime import datetime, timezone

    db, cursor, _adoption, proj, _state, deliv, _recv, _edits = _fake_db([])
    when = datetime.now(timezone.utc)
    proj._rows.append(_activity_with_message("t1", "skill-a", 10, "m1", "sess-1", when))
    # Only a rejected / unrelated delivery exists -> not adopted.
    deliv._rows.append({"tenant_id": "t1", "message_id": "m2", "accepted": True})

    asyncio.run(collect_skill_activity_metrics(db))
    assert cursor._rows[0]["adopted_calls"] == 0


def test_success_is_attributed_from_failed_receipt_in_window():
    from datetime import datetime, timedelta, timezone

    db, cursor, _adoption, proj, _state, _deliv, recv, _edits = _fake_db([])
    when = datetime.now(timezone.utc)
    proj._rows.append(_activity_with_message("t1", "skill-a", 10, "m1", "sess-1", when))
    # A failed tool receipt in the same kernel session, close in time.
    recv._rows.append(
        {
            "kernel_session_id": "sess-1",
            "status": "failed",
            "created_at": when - timedelta(seconds=30),
        }
    )

    asyncio.run(collect_skill_activity_metrics(db))
    bucket = cursor._rows[0]
    assert bucket["total_calls"] == 1
    assert bucket["successful_calls"] == 0  # not successful


def test_success_ignores_receipts_outside_window_or_other_session():
    from datetime import datetime, timedelta, timezone

    db, cursor, _adoption, proj, _state, _deliv, recv, _edits = _fake_db([])
    when = datetime.now(timezone.utc)
    proj._rows.append(_activity_with_message("t1", "skill-a", 10, "m1", "sess-1", when))
    recv._rows.extend(
        [
            # Too far away in time.
            {"kernel_session_id": "sess-1", "status": "failed", "created_at": when - timedelta(hours=5)},
            # Different session.
            {"kernel_session_id": "sess-2", "status": "failed", "created_at": when},
        ]
    )
    asyncio.run(collect_skill_activity_metrics(db))
    assert cursor._rows[0]["successful_calls"] == 1


def test_edit_event_is_attributed_to_the_turn_skill():
    from datetime import datetime, timezone

    db, cursor, _adoption, proj, _state, _deliv, _recv, edits = _fake_db([])
    when = datetime.now(timezone.utc)
    proj._rows.append(_activity_with_message("t1", "skill-a", 10, "m1", "sess-1", when))
    edits._rows.append(
        {
            "_id": 1,
            "tenant_id": "t1",
            "user_id": "u1",
            "object_path": "p/deck.json",
            "message_id": "m1",
            "created_at": when,
        }
    )
    result = asyncio.run(collect_edit_events(db))
    assert result["collected"] == 1
    bucket = cursor._rows[0]
    assert bucket["corrected_calls"] == 1
    # Idempotent: the same event is not counted twice.
    again = asyncio.run(collect_edit_events(db))
    assert again["collected"] == 0
    assert cursor._rows[0]["corrected_calls"] == 1


def test_edit_event_without_a_skill_on_the_turn_is_skipped():
    from datetime import datetime, timezone

    db, cursor, _adoption, _proj, _state, _deliv, _recv, edits = _fake_db([])
    edits._rows.append(
        {
            "_id": 1,
            "tenant_id": "t1",
            "user_id": "u1",
            "object_path": "p/deck.json",
            "message_id": "m-without-skill",
            "created_at": datetime.now(timezone.utc),
        }
    )
    result = asyncio.run(collect_edit_events(db))
    assert result["collected"] == 0
    assert cursor._rows == []


def test_three_dimensions_can_actually_mark_a_low_quality_skill():
    # End-to-end: collected real dimensions -> score -> shared marker set. This is
    # the "falsifiable" half that was previously blocked by the completeness gate.
    from datetime import datetime, timedelta, timezone

    db, cursor, _adoption, proj, _state, deliv, recv, _edits = _fake_db([])
    base = datetime.now(timezone.utc)
    # The sustained window needs LOW_QUALITY_SUSTAINED_DAYS consecutive low days, so
    # spread the calls across that many days (>= MIN_EFFECT_SAMPLES in total).
    seq = 100
    per_day = max(1, -(-MIN_EFFECT_SAMPLES // LOW_QUALITY_SUSTAINED_DAYS))
    for day_offset in range(LOW_QUALITY_SUSTAINED_DAYS):
        day = base - timedelta(days=day_offset)
        for i in range(per_day):
            seq += 1
            # Every call failed -> success rate 0; no adoption; a correction each time.
            when = day - timedelta(minutes=i)
            proj._rows.append(
                _activity_with_message("t1", "weak", seq, f"m{seq}", f"s{seq}", when)
            )
            recv._rows.append(
                {"kernel_session_id": f"s{seq}", "status": "failed", "created_at": when}
            )
    asyncio.run(collect_skill_activity_metrics(db))
    outcome = asyncio.run(evaluate_skill_quality(db, tenant_id="t1", skill_key="weak"))
    assert outcome["evaluated"] is True
    assert outcome["marked_low_quality"] is True
    assert asyncio.run(fetch_marked_skill_keys(db, tenant_id="t1")) == {"weak"}


def test_edit_is_attributed_to_the_manual_skill_when_a_turn_loads_several():
    # A turn auto-loads skills (automatic) but the user explicitly picked one
    # (manual). The edit must be credited to the user's pick, not the earliest row.
    from datetime import datetime, timezone

    db, cursor, _adoption, proj, _state, _deliv, _recv, edits = _fake_db([])
    when = datetime.now(timezone.utc)
    proj._rows.append(
        _activity_with_message("t1", "auto-early", 10, "m1", "sess-1", when, "automatic")
    )
    proj._rows.append(
        _activity_with_message("t1", "user-pick", 11, "m1", "sess-1", when, "manual")
    )
    edits._rows.append(
        {"_id": 1, "tenant_id": "t1", "user_id": "u1", "object_path": "p/d.json",
         "message_id": "m1", "created_at": when}
    )

    asyncio.run(collect_edit_events(db))
    by_key = {r["skill_key"]: r["corrected_calls"] for r in cursor._rows}
    assert by_key == {"user-pick": 1}


def test_edit_falls_back_to_the_first_automatic_skill():
    # No manual pick on the turn -> keep the previous behaviour (first activity).
    from datetime import datetime, timezone

    db, cursor, _adoption, proj, _state, _deliv, _recv, edits = _fake_db([])
    when = datetime.now(timezone.utc)
    proj._rows.append(
        _activity_with_message("t1", "auto-first", 10, "m1", "sess-1", when, "automatic")
    )
    proj._rows.append(
        _activity_with_message("t1", "auto-second", 11, "m1", "sess-1", when, "automatic")
    )
    edits._rows.append(
        {"_id": 1, "tenant_id": "t1", "user_id": "u1", "object_path": "p/d.json",
         "message_id": "m1", "created_at": when}
    )

    asyncio.run(collect_edit_events(db))
    by_key = {r["skill_key"]: r["corrected_calls"] for r in cursor._rows}
    assert by_key == {"auto-first": 1}


def test_one_edit_credits_exactly_one_skill():
    # Guards against inflating the correction rate by crediting every skill on the turn.
    from datetime import datetime, timezone

    db, cursor, _adoption, proj, _state, _deliv, _recv, edits = _fake_db([])
    when = datetime.now(timezone.utc)
    for i, mode in enumerate(["automatic", "automatic", "manual", "automatic"]):
        proj._rows.append(
            _activity_with_message("t1", f"s{i}", 10 + i, "m1", "sess-1", when, mode)
        )
    edits._rows.append(
        {"_id": 1, "tenant_id": "t1", "user_id": "u1", "object_path": "p/d.json",
         "message_id": "m1", "created_at": when}
    )

    asyncio.run(collect_edit_events(db))
    assert sum(int(r["corrected_calls"]) for r in cursor._rows) == 1
