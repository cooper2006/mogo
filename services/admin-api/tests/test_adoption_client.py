"""016 reads the 011-shared ``marked_low_quality`` bit (T014-3 / T015-2).

These tests pin the 016 side of the shared marker: 011 persists the flag into
the tenant-partitioned ``skill_adoption`` collection; this module reads it back
and down-ranks flagged skills in the market list.

The repo has no asyncio pytest mode configured, so each test drives its coroutine
through ``asyncio.run`` directly (same pattern the other pure-logic suites use).
"""

from __future__ import annotations

import asyncio

from app.services.skill_market.adoption_client import (
    ADOPTION_COLLECTION,
    MARKED_LOW_QUALITY,
    SOURCE_011_ADOPTION,
    SOURCE_016_QUALITY,
    apply_low_quality_ranking,
    apply_quality_assessment,
    fetch_marked_skill_keys,
    restore_quality,
)


class _FakeCursor:
    def __init__(self, rows):
        self._rows = list(rows)

    def find(self, flt, projection=None):
        tenant = flt.get("tenant_id")
        marked = flt.get("marked_low_quality")
        out = [
            r
            for r in self._rows
            if r.get("tenant_id") == tenant
            and (r.get("marked_low_quality") is marked if marked is not None else True)
        ]
        return self._FakeResult(out)

    def find_one(self, flt):
        for r in self._rows:
            if all(r.get(k) == v for k, v in flt.items()):
                return dict(r)
        return None

    async def update_one(self, flt, update, upsert=False):
        # Supports both plain ``$set`` and a single-stage aggregation pipeline
        # (used to derive marked_low_quality from the surviving source bit).
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
        sets = {}
        sets.update(update.get("$setOnInsert", {}))
        sets.update(update.get("$set", {}))
        for k, v in sets.items():
            if isinstance(v, dict) and "$or" in v:
                # Field-reference expressions ({"$or": ["$field", False]}) are not
                # evaluated; treat the referenced field as the live doc value.
                doc[k] = any(
                    (doc.get(o.lstrip("$")) if isinstance(o, str) and o.startswith("$") else bool(o))
                    for o in v["$or"]
                )
            else:
                doc[k] = v
        for k, v in update.get("$inc", {}).items():
            doc[k] = int(doc.get(k) or 0) + int(v)

    class _FakeResult:
        def __init__(self, rows):
            self._rows = rows

        async def to_list(self, length=0):
            return list(self._rows)


def _fake_db(rows):
    # NOTE: the same cursor (and therefore the same backing list) must be reused
    # across find / update_one / find_one, otherwise writes never surface on read.
    shared = list(rows)
    cursor = _FakeCursor(shared)

    class _Db:
        def __getitem__(self, name):
            assert name == ADOPTION_COLLECTION
            return cursor

    return _Db()


def test_fetch_marked_skill_keys_reads_shared_bit():
    db = _fake_db(
        [
            {"tenant_id": "t1", "skill_key": "good", "marked_low_quality": False},
            {"tenant_id": "t1", "skill_key": "bad", "marked_low_quality": True},
            # Different tenant must not leak into t1.
            {"tenant_id": "t2", "skill_key": "other-bad", "marked_low_quality": True},
        ]
    )
    marked = asyncio.run(fetch_marked_skill_keys(db, main_id="t1"))
    assert marked == {"bad"}


def test_ranking_down_ranks_but_keeps_visible():
    skills = [
        {"id": "bad", "name": "low quality"},
        {"id": "good", "name": "ok"},
        {"id": "good2", "name": "ok2"},
    ]
    ranked = apply_low_quality_ranking(skills, marked={"bad"})
    # Flagged skill is annotated and moved to the end.
    assert [s["id"] for s in ranked] == ["good", "good2", "bad"]
    assert ranked[-1]["markedLowQuality"] is True
    assert all(s["markedLowQuality"] is False for s in ranked[:-1])


def test_ranking_no_markers_keeps_order():
    skills = [{"id": "a"}, {"id": "b"}]
    ranked = apply_low_quality_ranking(skills, marked=set())
    assert [s["id"] for s in ranked] == ["a", "b"]
    assert all(s["markedLowQuality"] is False for s in ranked)


def test_shared_marker_key_matches_011():
    # The 016 reader/writer and the 011 writer must agree on the exact marker
    # keys, or the cross-service "no double-write, one shared bit" contract
    # breaks. 011 has its own copy of the same constants (kept in sync by the
    # chat-api-side test test_adoption_source_bit_keys_match_contract); here we
    # only assert the 016 side resolves to the agreed literal strings.
    from app.services.skill_market.scoring import LOW_QUALITY_MARKER

    assert MARKED_LOW_QUALITY == LOW_QUALITY_MARKER == "marked_low_quality"
    assert SOURCE_011_ADOPTION == "flagged_by_011_adoption"
    assert SOURCE_016_QUALITY == "flagged_by_016_quality"


def test_016_quality_assessment_writes_shared_bit():
    # 016-side write loop: a sustained-low-effect-score skill gets the aggregated
    # marker written, and the 016 reader surfaces it.
    db = _fake_db([])
    outcome = asyncio.run(
        apply_quality_assessment(
            db,
            main_id="t1",
            skill_key="weak",
            total_calls=100,
            successful_calls=10,
            adopted_calls=10,
            corrected_calls=80,
            sustained_days=7,
        )
    )
    assert outcome["marked_low_quality"] is True
    marked = asyncio.run(fetch_marked_skill_keys(db, main_id="t1"))
    assert marked == {"weak"}
    # The 016 source bit (not the 011 one) is what was set.
    rows = db[ADOPTION_COLLECTION].find_one({"tenant_id": "t1", "skill_key": "weak"})
    assert rows[SOURCE_016_QUALITY] is True
    assert rows.get(SOURCE_011_ADOPTION, False) is False


def test_016_restore_keeps_011_mark():
    # 016-side restore must clear only the 016 source bit and recompute the
    # aggregated bit, never wiping an 011 low-adoption mark that is still set.
    db = _fake_db(
        [
            {
                "tenant_id": "t1",
                "skill_key": "shared",
                "marked_low_quality": True,
                SOURCE_011_ADOPTION: True,
                SOURCE_016_QUALITY: True,
            }
        ]
    )
    asyncio.run(restore_quality(db, main_id="t1", skill_key="shared", actor="admin"))
    rows = db[ADOPTION_COLLECTION].find_one({"tenant_id": "t1", "skill_key": "shared"})
    # 016 bit cleared, but the aggregated bit stays True because 011 is still set.
    assert rows[SOURCE_016_QUALITY] is False
    assert rows[SOURCE_011_ADOPTION] is True
    assert rows[MARKED_LOW_QUALITY] is True
    marked = asyncio.run(fetch_marked_skill_keys(db, main_id="t1"))
    assert marked == {"shared"}

