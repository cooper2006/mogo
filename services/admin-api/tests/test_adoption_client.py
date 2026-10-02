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
    apply_low_quality_ranking,
    fetch_marked_skill_keys,
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
            if r.get("tenant_id") == tenant and r.get("marked_low_quality") is marked
        ]
        return self._FakeResult(out)

    class _FakeResult:
        def __init__(self, rows):
            self._rows = rows

        async def to_list(self, length=0):
            return list(self._rows)


def _fake_db(rows):
    class _Db:
        def __getitem__(self, name):
            assert name == ADOPTION_COLLECTION
            return _FakeCursor(rows)

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
    # The 016 reader and the 011 writer must agree on the exact marker key, or
    # the cross-service "no double-write, one shared bit" contract breaks.
    from app.services.skill_market.scoring import LOW_QUALITY_MARKER

    assert MARKED_LOW_QUALITY == LOW_QUALITY_MARKER == "marked_low_quality"

