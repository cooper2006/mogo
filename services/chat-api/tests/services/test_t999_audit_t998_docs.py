"""T999 audit/observability + T998 quickstart/contract existence checks (013-019)."""

from __future__ import annotations

import pytest

from app.im_gateway.audit import IM_AUDIT_EVENTS, im_audit_document, record_im_event
from app.services.feature_audit import FEATURE_AUDIT_EVENTS, audit_document, record_feature_event
def test_im_audit_events():
    assert set(IM_AUDIT_EVENTS) == {"im.enter", "im.leave", "im.deliver", "im.fail"}
    captured: list[dict] = []

    def fake_sink(**kwargs):
        captured.append(kwargs)

    doc = record_im_event(
        "im.deliver",
        channel="wecom",
        conversation_id="c-1",
        tenant_id="t1",
        actor="u1",
        sink=fake_sink,
    )
    assert doc["event"] == "im.deliver"
    assert doc["channel"] == "wecom"
    # The 001 sink captured the audit event.
    assert captured[0]["action"] == "im.deliver"
    assert captured[0]["details"]["conversation_id"] == "c-1"


def test_im_unknown_event_rejected():
    with pytest.raises(ValueError):
        record_im_event("im.unknown", channel="wecom", conversation_id="c-1")


def test_feature_audit_events_per_feature():
    # 012/014/015/016/017/018 each expose a known event set.
    assert "a2a.outbound" in FEATURE_AUDIT_EVENTS["012"]
    assert "entity.indexed" in FEATURE_AUDIT_EVENTS["014"]
    assert "kg.mutated" in FEATURE_AUDIT_EVENTS["015"]
    assert "skill.quality.marked" in FEATURE_AUDIT_EVENTS["016"]
    assert "memory.promoted" in FEATURE_AUDIT_EVENTS["017"]
    assert "asset.registered" in FEATURE_AUDIT_EVENTS["018"]

    captured: list[tuple[str, dict]] = []

    def fake_sink(event, record):
        captured.append((event, record))

    record_feature_event("014", "entity.indexed", {"entity_id": "c1"}, sink=fake_sink)
    assert captured[0][0] == "entity.indexed"
    assert captured[0][1]["feature"] == "014"


def test_a2a_audit_event_records_outbound():
    captured: list[tuple[str, dict]] = []

    def fake_sink(event, record):
        captured.append((event, record))

    record_feature_event("012", "a2a.outbound", {"agent": "primary", "task_id": "t-1"}, sink=fake_sink)
    assert captured[0][0] == "a2a.outbound"
    assert captured[0][1]["feature"] == "012"
    assert captured[0][1]["task_id"] == "t-1"


def test_feature_audit_unknown_feature_rejected():
    with pytest.raises(ValueError):
        record_feature_event("099", "nope", {})


def test_feature_audit_unknown_event_rejected():
    with pytest.raises(ValueError):
        record_feature_event("014", "entity.bogus", {})


def test_audit_document_is_pure():
    doc = audit_document("entity.indexed", "014", entity_id="c1")
    assert doc["event"] == "entity.indexed"
    assert doc["feature"] == "014"
    assert doc["entity_id"] == "c1"


def test_all_quickstart_and_contracts_exist():
    from pathlib import Path

    here = Path(__file__).resolve().parents[3]
    repo_root = here.parent  # services/ -> repo root
    required = [
        ("specs/012-a2a-agent-gateway/quickstart.md", "contracts/a2a-gateway.md"),
        ("specs/013-multi-im-entry/quickstart.md", None),
        ("specs/014-business-semantic-index/quickstart.md", None),
        ("specs/015-knowledge-graph-layer/quickstart.md", None),
        ("specs/016-skill-market-hardening/quickstart.md", None),
        ("specs/017-three-scope-memory/quickstart.md", None),
        ("specs/018-capability-asset-registration/quickstart.md", None),
        ("specs/019-harness-elastic-config/quickstart.md", "contracts/harness-config.md"),
        ("contracts/orchestration.md", None),
        ("contracts/self-evolution.md", None),
        ("contracts/session-versioning-contract.md", None),
    ]
    for rel, extra in required:
        path = repo_root / rel
        assert path.exists(), f"missing {path}"
        if extra:
            extra_path = repo_root / extra
            assert extra_path.exists(), f"missing {extra_path}"


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-q"]))
