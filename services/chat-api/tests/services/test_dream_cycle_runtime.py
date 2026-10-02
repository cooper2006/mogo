"""T999 production wiring for 011: projected events → friction → scan → audit.

These tests pin the *wiring*, not the 011 core (already covered by
``tests/self_evolution/`` and ``tests/services/test_dream_*``). Before this
module existed nothing in ``app/`` imported either 011 package.
"""

from __future__ import annotations

import asyncio

from app.self_evolution.scanner import ScanConfig
from app.services.dream_cycle import runtime


def _collecting_sink():
    entries: list[dict] = []

    def sink(**kwargs):
        entries.append(dict(kwargs))
        return dict(kwargs)

    return sink, entries


class _FakeCursor:
    def __init__(self, rows):
        self._rows = list(rows)

    def sort(self, key, direction):
        self._rows.sort(key=lambda row: row.get(key) or 0, reverse=direction < 0)
        return self

    def limit(self, count):
        self._rows = self._rows[: int(count)]
        return self

    def __aiter__(self):
        async def _gen():
            for row in self._rows:
                yield row

        return _gen()


def _matches(row, flt):
    for key, expected in flt.items():
        actual = row.get(key)
        if isinstance(expected, dict):
            if "$in" in expected and actual not in expected["$in"]:
                return False
            if "$gt" in expected and not (actual is not None and actual > expected["$gt"]):
                return False
        elif actual != expected:
            return False
    return True


class _FakeCollection:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.indexes: list = []

    def find(self, flt, projection=None):
        return _FakeCursor([row for row in self.rows if _matches(row, flt)])

    async def create_index(self, keys, name=None):
        self.indexes.append((keys, name))
        return name


class _FakeDb:
    def __init__(self, collections=None):
        self._collections = dict(collections or {})

    def __getitem__(self, name):
        return self._collections.setdefault(name, _FakeCollection())


def _tool_row(message_id, seq, outcome, *, name="grep", tenant_id="t1"):
    return {
        "item_kind": "tool",
        "message_id": message_id,
        "stream_seq": seq,
        "type": outcome,
        "tenant_id": tenant_id,
        "payload": {"name": name},
    }


def _db_with(rows):
    return _FakeDb({runtime.PROJECTIONS_COLLECTION: _FakeCollection(rows)})


# --- deriving friction from projected events ---------------------------------


def test_failed_then_succeeded_row_becomes_a_signal():
    rows = [_tool_row("m1", 1, "item.failed"), _tool_row("m1", 2, "item.completed")]
    signals = runtime.signals_from_rows(rows)
    assert len(signals) == 1
    assert signals[0].kind == "failed_then_succeeded"
    assert signals[0].retries == 1
    assert signals[0].scene == ["grep"]


def test_success_without_failure_is_not_friction():
    rows = [_tool_row("m1", 1, "item.completed"), _tool_row("m1", 2, "item.completed")]
    assert runtime.signals_from_rows(rows) == []


def test_failure_without_a_later_success_is_not_friction():
    rows = [_tool_row("m1", 1, "item.failed"), _tool_row("m1", 2, "item.failed")]
    assert runtime.signals_from_rows(rows) == []


def test_retries_count_until_the_first_success():
    rows = [
        _tool_row("m1", 1, "item.failed"),
        _tool_row("m1", 2, "item.failed"),
        _tool_row("m1", 3, "item.completed"),
    ]
    signals = runtime.signals_from_rows(rows)
    assert signals[0].retries == 2


def test_the_same_tool_across_messages_does_not_share_retries():
    rows = [_tool_row("m1", 1, "item.failed"), _tool_row("m2", 2, "item.completed")]
    assert runtime.signals_from_rows(rows) == []


def test_a_different_tool_does_not_supply_the_success():
    rows = [
        _tool_row("m1", 1, "item.failed", name="grep"),
        _tool_row("m1", 2, "item.completed", name="read_file"),
    ]
    assert runtime.signals_from_rows(rows) == []


# --- one full pass -----------------------------------------------------------


def test_run_once_walks_capture_and_reports():
    sink, entries = _collecting_sink()
    db = _db_with([_tool_row("m1", 1, "item.failed"), _tool_row("m1", 2, "item.completed")])

    report = asyncio.run(runtime.run_once(db=db, sink=sink))

    assert [entry["event_type"] for entry in entries] == ["capture"]
    assert entries[0]["payload"]["friction_kind"] == "failed_then_succeeded"
    assert report["signals"] == 1
    assert report["fragments"] == 1
    assert report["captured"] == 1
    # One sample is below the default ``min_samples`` (5), so no draft yet.
    assert report["generated"] == 0


def test_run_once_generates_and_audits_a_draft_and_mr():
    sink, entries = _collecting_sink()
    db = _db_with([_tool_row("m1", 1, "item.failed"), _tool_row("m1", 2, "item.completed")])

    report = asyncio.run(
        runtime.run_once(
            db=db,
            sink=sink,
            scan_config=ScanConfig(min_samples=1, jaccard_threshold=0.0),
        )
    )

    types = [entry["event_type"] for entry in entries]
    assert types == ["capture", "generate", "mr"]
    assert report["generated"] == 1
    assert report["mr"] == 1
    assert report["draftIds"] == ["skill-frag-000001"]


def test_run_once_scans_each_tenant_separately():
    sink, _entries = _collecting_sink()
    db = _db_with(
        [
            _tool_row("m1", 1, "item.failed", tenant_id="t1"),
            _tool_row("m1", 2, "item.completed", tenant_id="t1"),
            _tool_row("m2", 3, "item.failed", tenant_id="t2"),
            _tool_row("m2", 4, "item.completed", tenant_id="t2"),
        ]
    )

    report = asyncio.run(
        runtime.run_once(
            db=db,
            sink=sink,
            scan_config=ScanConfig(min_samples=1, jaccard_threshold=0.0),
        )
    )

    assert report["generated"] == 2, "each tenant is scanned on its own fragments"


def test_run_once_audits_deprecations_and_restorations():
    sink, entries = _collecting_sink()

    report = asyncio.run(
        runtime.run_once(
            db=_FakeDb(),
            sink=sink,
            deprecations=[{"skill_key": "s1"}],
            restorations=[{"skill_key": "s2"}],
        )
    )

    assert [entry["event_type"] for entry in entries] == ["deprecate", "restore"]
    assert report["deprecated"] == 1
    assert report["restored"] == 1


def test_run_once_without_deprecation_input_emits_no_deprecation_event():
    sink, entries = _collecting_sink()
    asyncio.run(runtime.run_once(db=_FakeDb(), sink=sink))
    assert entries == []


# --- the sink reaches the 001 audit stream ----------------------------------


def test_default_sink_reaches_the_001_bridge(monkeypatch):
    from app.services import feature_audit_bridge

    captured: list[tuple] = []

    def fake_emit(feature, event, document, **kwargs):
        captured.append((feature, event, document, kwargs))
        return {"feature": feature, "event": event}

    monkeypatch.setattr(feature_audit_bridge, "emit_feature_event", fake_emit)

    asyncio.run(
        runtime.run_once(
            db=_db_with(
                [_tool_row("m1", 1, "item.failed"), _tool_row("m1", 2, "item.completed")]
            )
        )
    )

    assert captured, "the default sink must reach the 001 audit bridge"
    feature, event, document, kwargs = captured[0]
    assert feature == "011"
    assert event == "capture"
    assert kwargs["tenant_id"] == "t1"
    assert document["actor"] == "dream-cycle"


def test_011_is_registered_in_the_feature_audit_table():
    from app.services.feature_audit import FEATURE_AUDIT_EVENTS, record_feature_event

    assert FEATURE_AUDIT_EVENTS["011"] == (
        "capture",
        "generate",
        "mr",
        "deprecate",
        "restore",
    )
    record = record_feature_event("011", "capture", {"key": "k"})
    assert record["feature"] == "011"


# --- index + periodic trigger ------------------------------------------------


def test_ensure_indexes_covers_the_scan_filter():
    db = _FakeDb()
    asyncio.run(runtime.ensure_indexes(db))
    assert db[runtime.PROJECTIONS_COLLECTION].indexes == [
        ([("item_kind", 1), ("type", 1), ("stream_seq", 1)], "dream_cycle_tool_outcomes")
    ]


def test_scanner_runs_a_pass_then_stops(monkeypatch):
    calls: list[dict] = []

    async def fake_run_once(**kwargs):
        calls.append(kwargs)
        return {}

    monkeypatch.setattr(runtime, "run_once", fake_run_once)

    async def scenario():
        scanner = runtime.DreamCycleScanner(interval_seconds=0.01)
        await scanner.start()
        await scanner.start()  # idempotent
        await asyncio.sleep(0.05)
        await scanner.stop()
        await scanner.stop()  # idempotent

    asyncio.run(scenario())
    assert calls, "the loop must run at least one pass"


def test_scanner_interval_defaults_to_the_config_hours():
    scanner = runtime.DreamCycleScanner()
    assert scanner.interval_seconds == 24 * 3600.0


def test_application_lifespan_starts_and_stops_the_scanner():
    """The wiring only counts if the process actually starts the loop."""
    from pathlib import Path

    main_py = Path(__file__).resolve().parents[2] / "app" / "main.py"
    text = main_py.read_text(encoding="utf-8")
    assert "dream_cycle_runtime.dream_cycle_scanner.start()" in text
    assert "dream_cycle_runtime.dream_cycle_scanner.stop()" in text
    assert "dream_cycle_runtime.ensure_indexes(db)" in text
