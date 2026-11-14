"""chat-api side of the 016 skill-quality metric collection (FR-3 data source).

Pins the shared collection name + the additive bucket write so chat-api and
admin-api cannot drift on the contract. The production call site that feeds real
``success`` / ``adopted`` / ``corrected`` signals is a platform-level collection
gap (same as 011's own ``AdoptionStore.record_adoption``); this suite covers the
entry point itself.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from app.services.skill_quality_report import (
    QUALITY_METRICS_COLLECTION,
    report_skill_call,
)


def _utc_today() -> date:
    """The day ``report_skill_call`` buckets into.

    The service defaults ``day`` to ``datetime.now(timezone.utc).date()``
    (``_today()``), so assertions must use the same anchor. ``date.today()``
    made these tests fail for the eight hours after local midnight in any zone
    east of UTC: the local date had rolled over while the UTC date had not.
    """
    return datetime.now(timezone.utc).date()


class _FakeCollection:
    def __init__(self):
        self.rows: list[dict] = []

    def update_one(self, flt, update, upsert=False):
        doc = None
        for row in self.rows:
            if all(row.get(k) == v for k, v in flt.items()):
                doc = row
                break
        if doc is None:
            if not upsert:
                return
            doc = dict(flt)
            self.rows.append(doc)
        for k, v in (update or {}).get("$inc", {}).items():
            doc[k] = int(doc.get(k) or 0) + int(v)


class _FakeDb:
    def __init__(self):
        self.collections: dict[str, _FakeCollection] = {}

    def __getitem__(self, name):
        return self.collections.setdefault(name, _FakeCollection())


def test_collection_name_matches_the_016_contract():
    # Must equal admin-api ``skill_market.quality_metrics.QUALITY_METRICS_COLLECTION``.
    assert QUALITY_METRICS_COLLECTION == "skill_quality_metrics"


def test_report_skill_call_accumulates_additively():
    db = _FakeDb()
    report_skill_call(db, tenant_id="t1", skill_key="s", success=True, adopted=1)
    report_skill_call(db, tenant_id="t1", skill_key="s", success=False, corrected=1)
    rows = db[QUALITY_METRICS_COLLECTION].rows
    assert len(rows) == 1
    assert rows[0]["total_calls"] == 2
    assert rows[0]["successful_calls"] == 1
    assert rows[0]["adopted_calls"] == 1
    assert rows[0]["corrected_calls"] == 1
    assert rows[0]["tenant_id"] == "t1"
    assert rows[0]["date"] == _utc_today().isoformat()


def test_report_skill_call_is_tenant_and_day_partitioned():
    db = _FakeDb()
    report_skill_call(db, tenant_id="t1", skill_key="s", success=True)
    report_skill_call(db, tenant_id="t2", skill_key="s", success=True)
    report_skill_call(db, tenant_id="t1", skill_key="s", success=True, day=date(2020, 1, 1))
    keys = {(r["tenant_id"], r["date"]) for r in db[QUALITY_METRICS_COLLECTION].rows}
    assert len(keys) == 3
    assert ("t1", _utc_today().isoformat()) in keys
    assert ("t2", _utc_today().isoformat()) in keys
    assert ("t1", "2020-01-01") in keys


def test_report_skill_call_without_db_is_a_noop():
    report_skill_call(None, tenant_id="t1", skill_key="s", success=True)


def test_record_product_edit_writes_an_edit_event():
    from app.services.skill_quality_report import (
        EDIT_EVENTS_COLLECTION,
        record_product_edit,
    )

    db = _FakeDb()

    class _EditCollection:
        def __init__(self):
            self.docs = []

        async def insert_one(self, doc):
            self.docs.append(doc)

    class _EditDb:
        def __init__(self):
            self.collections = {}

        def __getitem__(self, name):
            return self.collections.setdefault(name, _EditCollection())

    edb = _EditDb()
    import asyncio

    asyncio.run(
        record_product_edit(
            edb,
            tenant_id="t1",
            user_id="u1",
            object_path="p/deck.json",
            message_id="m1",
        )
    )
    docs = edb[EDIT_EVENTS_COLLECTION].docs
    assert len(docs) == 1
    assert docs[0]["tenant_id"] == "t1"
    assert docs[0]["user_id"] == "u1"
    assert docs[0]["object_path"] == "p/deck.json"
    assert docs[0]["message_id"] == "m1"
    assert docs[0]["created_at"] is not None


def test_edit_events_collection_name_matches_the_016_contract():
    from app.services.skill_quality_report import EDIT_EVENTS_COLLECTION

    assert EDIT_EVENTS_COLLECTION == "skill_product_edit_events"
