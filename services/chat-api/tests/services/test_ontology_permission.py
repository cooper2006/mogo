"""运行时本体数据权限解析的单元测试（设计四 §5.6.1）。

全部使用注入的假 provider/store，不依赖真实 DB。
"""

from __future__ import annotations

import pytest

from app.services import ontology_permission as op


class _FakeSubjectProvider:
    def __init__(self, subjects: op.SubjectSet | None = None) -> None:
        self.subjects = subjects
        self.calls = 0

    async def load(self, tenant_id: str, user_id: str) -> op.SubjectSet:
        self.calls += 1
        return self.subjects or op.SubjectSet(tenant_id=tenant_id, user_id=user_id)


class _FakeGrantStore:
    def __init__(self, rows: list[dict], *, boom: bool = False) -> None:
        self.rows = rows
        self.boom = boom
        self.calls = 0

    async def fetch_grants(self, subjects: op.SubjectSet) -> list[dict]:
        self.calls += 1
        if self.boom:
            raise RuntimeError("db down")
        return self.rows


class _RecordingAuditSink:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def emit(self, event) -> None:
        self.events.append(dict(event))


@pytest.fixture(autouse=True)
def _reset_module_state():
    op.clear_cache()
    op.set_cache_ttl(op.DEFAULT_CACHE_TTL_SECONDS)
    yield
    op.clear_cache()


def _subjects(*, orgs=(), roles=()) -> op.SubjectSet:
    return op.SubjectSet(
        tenant_id="t1",
        user_id="u1",
        org_ids=frozenset(orgs),
        role_ids=frozenset(roles),
    )


# --- 纯解析 ---------------------------------------------------------------


def test_resolve_priority_highest_wins():
    subjects = _subjects(orgs=["o1"])
    rows = [
        {"subject_type": "tenant", "subject_id": "t1", "ontology_uri": "material", "access_mode": "none", "priority": 10},
        {"subject_type": "org", "subject_id": "o1", "ontology_uri": "material", "access_mode": "read", "priority": 100},
    ]
    assert op.resolve_visible_ontologies(subjects, rows) == frozenset({"material"})


def test_resolve_none_hides_when_priority_higher():
    subjects = _subjects(orgs=["o1"])
    rows = [
        {"subject_type": "org", "subject_id": "o1", "ontology_uri": "material", "access_mode": "read", "priority": 10},
        {"subject_type": "user", "subject_id": "u1", "ontology_uri": "material", "access_mode": "none", "priority": 200},
    ]
    assert op.resolve_visible_ontologies(subjects, rows) == frozenset()


def test_resolve_ignores_non_matching_subject():
    subjects = _subjects()
    rows = [
        {"subject_type": "org", "subject_id": "other", "ontology_uri": "material", "access_mode": "read", "priority": 100},
    ]
    assert op.resolve_visible_ontologies(subjects, rows) == frozenset()


def test_resolve_ignores_disabled_and_blank_uri():
    subjects = _subjects()
    rows = [
        {"subject_type": "user", "subject_id": "u1", "ontology_uri": "a", "access_mode": "read", "priority": 100, "enabled": False},
        {"subject_type": "user", "subject_id": "u1", "ontology_uri": "", "access_mode": "read", "priority": 100},
    ]
    assert op.resolve_visible_ontologies(subjects, rows) == frozenset()


def test_resolve_tie_prefers_more_restrictive():
    subjects = _subjects()
    rows = [
        {"subject_type": "user", "subject_id": "u1", "ontology_uri": "m", "access_mode": "read", "priority": 100},
        {"subject_type": "tenant", "subject_id": "t1", "ontology_uri": "m", "access_mode": "none", "priority": 100},
    ]
    # 同优先级：更严格者胜（none 压 read），fail-closed 偏置。
    assert op.resolve_visible_ontologies(subjects, rows) == frozenset()


def test_resolve_missing_priority_defaults_to_100():
    subjects = _subjects()
    rows = [
        {"subject_type": "user", "subject_id": "u1", "ontology_uri": "m", "access_mode": "write"},
        {"subject_type": "user", "subject_id": "u1", "ontology_uri": "m", "access_mode": "none", "priority": 50},
    ]
    assert op.resolve_visible_ontologies(subjects, rows) == frozenset({"m"})


# --- visible_ontology_ids -------------------------------------------------


async def test_empty_user_id_returns_empty_without_querying():
    store = _FakeGrantStore([{"subject_type": "user", "subject_id": "u1", "ontology_uri": "m", "access_mode": "read"}])
    op.configure(subject_provider=_FakeSubjectProvider(), grant_store=store, audit_sink=_RecordingAuditSink())
    assert await op.visible_ontology_ids("t1", "") == frozenset()
    assert await op.visible_ontology_ids("", "u1") == frozenset()
    assert store.calls == 0


async def test_success_resolves_and_caches():
    provider = _FakeSubjectProvider(_subjects())
    store = _FakeGrantStore([{"subject_type": "user", "subject_id": "u1", "ontology_uri": "material", "access_mode": "read"}])
    audit = _RecordingAuditSink()
    op.configure(subject_provider=provider, grant_store=store, audit_sink=audit)

    first = await op.visible_ontology_ids("t1", "u1")
    second = await op.visible_ontology_ids("t1", "u1")

    assert first == frozenset({"material"})
    assert second == frozenset({"material"})
    # 第二次命中缓存，不再查库。
    assert store.calls == 1
    assert provider.calls == 1
    assert len(audit.events) == 1


async def test_store_failure_is_fail_closed_and_not_cached():
    provider = _FakeSubjectProvider(_subjects())
    store = _FakeGrantStore([], boom=True)
    audit = _RecordingAuditSink()
    op.configure(subject_provider=provider, grant_store=store, audit_sink=audit)

    assert await op.visible_ontology_ids("t1", "u1") == frozenset()
    assert await op.visible_ontology_ids("t1", "u1") == frozenset()
    # 异常不写缓存 → 每次都重试查库。
    assert store.calls == 2
    assert all(event["decision"] == "deny" for event in audit.events)


async def test_invalidate_clears_cache():
    store = _FakeGrantStore([{"subject_type": "user", "subject_id": "u1", "ontology_uri": "material", "access_mode": "read"}])
    op.configure(subject_provider=_FakeSubjectProvider(_subjects()), grant_store=store, audit_sink=_RecordingAuditSink())

    await op.visible_ontology_ids("t1", "u1")
    op.invalidate("t1", "u1")
    await op.visible_ontology_ids("t1", "u1")
    assert store.calls == 2


async def test_snapshot_shape():
    store = _FakeGrantStore([
        {"subject_type": "user", "subject_id": "u1", "ontology_uri": "b", "access_mode": "write"},
        {"subject_type": "user", "subject_id": "u1", "ontology_uri": "a", "access_mode": "read"},
    ])
    op.configure(subject_provider=_FakeSubjectProvider(_subjects()), grant_store=store, audit_sink=_RecordingAuditSink())

    snapshot = await op.ontology_scope_snapshot("t1", "u1")
    assert snapshot["tenantId"] == "t1"
    assert snapshot["userId"] == "u1"
    assert snapshot["ontologies"] == ["a", "b"]
    assert snapshot["count"] == 2
    assert "generatedAt" in snapshot
