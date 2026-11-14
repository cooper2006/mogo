"""017 C-7 / T038：项目成员变更审计回归用例（跨特性，钩子在 049 ``patch_project``）。

参照 ``tests/memory/test_memory_endpoints.py`` 的**真实** auth 契约
``{session, user, tenant_id, org_id}``（不伪造 ``user_id`` / ``role`` /
``is_workspace_member`` 顶层字段），用 monkeypatch 打桩审计桥与数据库，直接
调用端点函数（不走 TestClient）。

覆盖 017 design §9.4 事件契约 / SC-14，并回归 049 既有语义：

- 成员 diff 新增 → ``project.member.granted``；移除 → ``project.member.revoked``；
  一次 PATCH 同时增删最多两条。
- 空 diff / 只改 ``title`` / ``status`` 不发事件。
- **审计桥抛异常时 PATCH 仍成功、响应码 / 响应结构不变**，仅留观测日志。
- 049 既有语义不退化：非创建者 403、``default`` 400、去重去空、500 上限、
  ``member_user_ids`` 响应结构、``update_one`` 未命中（404）不发事件。
- 白名单（T033）：``"049"`` 分组存在、``"017"`` 含 §9.4 事件且保留既有 3 个、
  未知 feature / event 仍抛 ``ValueError``。
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from app.api.endpoints import projects
from app.services.feature_audit import FEATURE_AUDIT_EVENTS, record_feature_event


TENANT = "t1"
CREATOR = "u1"
PROJECT_ID = "p1"


# ── auth：照抄 test_memory_endpoints.py 的真实契约 ──────────────────────


def _auth_payload(
    *, user_id: str = CREATOR, tenant_id: str = TENANT, org_id: str = TENANT
) -> dict:
    """``resolve_session_user`` 的真实返回形态（test_memory_endpoints.py:35-47）。"""
    return {
        "session": {"_id": "s1", "user_id": user_id, "tenant_id": tenant_id},
        "user": {
            "_id": user_id,
            "tenant_id": tenant_id,
            "status": "active",
            "primary_org_id": org_id,
        },
        "tenant_id": tenant_id,
        "org_id": org_id,
    }


def _patch_auth(monkeypatch, *, user_id: str = CREATOR) -> None:
    async def _fake_resolve(authorization):
        return _auth_payload(user_id=user_id)

    # projects.py 用 ``from app.api.endpoints.auth import _resolve_session_user``
    # 把名字绑进本模块，故必须 patch projects 模块内的名字（而非 auth 源模块）。
    monkeypatch.setattr("app.api.endpoints.projects._resolve_session_user", _fake_resolve)


# ── fake DB ───────────────────────────────────────────────────────────


class _UpdateResult:
    def __init__(self, matched_count: int) -> None:
        self.matched_count = matched_count
        self.modified_count = matched_count


class _FakeProjects:
    """单文档内存集合：``find_one`` 返回快照副本，``update_one`` 原地改存储。"""

    def __init__(self, doc: dict | None) -> None:
        self._doc = dict(doc) if doc else None
        self.update_calls: list[tuple[dict, dict]] = []
        self.force_matched_zero = False

    def _snapshot(self) -> dict | None:
        if self._doc is None:
            return None
        snap = dict(self._doc)
        if isinstance(snap.get("member_user_ids"), list):
            snap["member_user_ids"] = list(snap["member_user_ids"])
        return snap

    async def find_one(self, scope: dict, projection=None) -> dict | None:
        if self._doc is None:
            return None
        if (
            self._doc.get("_id") == scope.get("_id")
            and self._doc.get("tenant_id") == scope.get("tenant_id")
        ):
            return self._snapshot()
        return None

    async def update_one(self, scope: dict, update: dict) -> _UpdateResult:
        self.update_calls.append((scope, update))
        if self.force_matched_zero or self._doc is None:
            return _UpdateResult(0)
        if self._doc.get("_id") == scope.get("_id"):
            self._doc.update(update.get("$set", {}))
            return _UpdateResult(1)
        return _UpdateResult(0)


class _FakeDB:
    def __init__(self, doc: dict | None) -> None:
        self.projects = _FakeProjects(doc)


def _seed_project(
    *,
    owner: str = CREATOR,
    members: list[str] | None = None,
    project_id: str = PROJECT_ID,
) -> dict:
    return {
        "_id": project_id,
        "tenant_id": TENANT,
        "user_id": owner,
        "workspace_id": project_id,
        "title": "a project",
        "status": "active",
        "member_user_ids": list(members or []),
    }


# ── harness ───────────────────────────────────────────────────────────


class _Harness:
    def __init__(
        self,
        monkeypatch,
        *,
        caller: str = CREATOR,
        owner: str = CREATOR,
        before_members: list[str] | None = None,
        project_id: str = PROJECT_ID,
        matched_zero: bool = False,
        audit_raises: bool = False,
    ) -> None:
        self.events: list[dict[str, Any]] = []
        self.audit_raises = audit_raises

        def _fake_emit(feature, event, document, *, tenant_id="", actor=""):
            if self.audit_raises:
                raise RuntimeError("audit bridge down")
            self.events.append(
                {
                    "feature": feature,
                    "event": event,
                    "document": document,
                    "tenant_id": tenant_id,
                    "actor": actor,
                }
            )
            return {}

        # 审计桥的 hook 用「延迟导入」写在 patch_project 内，等价于 patch 源模块属性。
        monkeypatch.setattr(
            "app.services.feature_audit_bridge.emit_feature_event", _fake_emit
        )
        self.db = _FakeDB(
            _seed_project(owner=owner, members=before_members, project_id=project_id)
        )
        self.db.projects.force_matched_zero = matched_zero
        monkeypatch.setattr("app.api.endpoints.projects.get_db", lambda: self.db)
        _patch_auth(monkeypatch, user_id=caller)

    async def patch(self, payload: dict, project_id: str = PROJECT_ID):
        return await projects.patch_project(
            project_id,
            projects.ProjectPatch(**payload),
            authorization="Bearer test",
        )


def _make(monkeypatch, **kwargs) -> _Harness:
    return _Harness(monkeypatch, **kwargs)


# ── diff → 事件 ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_added_members_emit_granted(monkeypatch):
    """新增成员 → project.member.granted；payload 字段与 049 语义均不退化。"""
    h = _make(monkeypatch, before_members=[])
    resp = await h.patch({"member_user_ids": ["bob", "carol"]})

    # 响应码 / 响应结构不变（049 既有语义）
    assert resp.code == 0
    assert resp.message is None
    assert resp.data["_id"] == PROJECT_ID
    # 去空 / 去重 / 排除创建者的 049 语义不退化
    assert resp.data["member_user_ids"] == ["bob", "carol"]

    assert len(h.events) == 1
    e = h.events[0]
    assert e["feature"] == "049"
    assert e["event"] == "project.member.granted"
    assert e["tenant_id"] == TENANT
    assert e["actor"] == CREATOR
    doc = e["document"]
    assert doc["project_id"] == PROJECT_ID
    assert doc["project_owner_id"] == CREATOR
    assert doc["added"] == ["bob", "carol"]
    assert doc["removed"] == []
    assert doc["previous_member_count"] == 0
    assert doc["resulting_member_count"] == 2
    assert isinstance(doc["occurred_at"], str) and doc["occurred_at"]


@pytest.mark.asyncio
async def test_removed_members_emit_revoked(monkeypatch):
    """移除成员 → project.member.revoked。"""
    h = _make(monkeypatch, before_members=["bob", "carol", "dave"])
    resp = await h.patch({"member_user_ids": ["bob"]})

    assert resp.code == 0
    assert resp.data["member_user_ids"] == ["bob"]
    assert len(h.events) == 1
    e = h.events[0]
    assert e["feature"] == "049"
    assert e["event"] == "project.member.revoked"
    assert e["document"]["added"] == []
    assert e["document"]["removed"] == ["carol", "dave"]
    assert e["document"]["previous_member_count"] == 3
    assert e["document"]["resulting_member_count"] == 1


@pytest.mark.asyncio
async def test_add_and_remove_emits_two_events(monkeypatch):
    """一次 PATCH 同时增删 → 最多两条事件，共享完整 diff 上下文。"""
    h = _make(monkeypatch, before_members=["bob", "carol"])
    resp = await h.patch({"member_user_ids": ["carol", "dave"]})

    assert resp.code == 0
    assert {e["event"] for e in h.events} == {
        "project.member.granted",
        "project.member.revoked",
    }
    assert len(h.events) == 2
    for e in h.events:
        assert e["feature"] == "049"
        assert e["document"]["added"] == ["dave"]
        assert e["document"]["removed"] == ["bob"]


# ── 不发事件的分支 ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_empty_diff_emits_nothing(monkeypatch):
    """member_user_ids 同集合（仅顺序不同）→ diff 为空，不发事件。"""
    h = _make(monkeypatch, before_members=["bob", "carol"])
    resp = await h.patch({"member_user_ids": ["carol", "bob"]})
    assert resp.code == 0
    assert h.events == []


@pytest.mark.asyncio
async def test_title_only_change_emits_nothing(monkeypatch):
    h = _make(monkeypatch, before_members=["bob"])
    resp = await h.patch({"title": "renamed"})
    assert resp.code == 0
    assert resp.data["title"] == "renamed"
    assert h.events == []


@pytest.mark.asyncio
async def test_status_only_change_emits_nothing(monkeypatch):
    h = _make(monkeypatch, before_members=["bob"])
    resp = await h.patch({"status": "archived"})
    assert resp.code == 0
    assert resp.data["status"] == "archived"
    assert h.events == []


@pytest.mark.asyncio
async def test_no_audit_when_update_matches_nothing(monkeypatch):
    """仅 update_one 成功之后才发事件；matched_count=0（404）不发。"""
    h = _make(monkeypatch, before_members=[], matched_zero=True)
    resp = await h.patch({"member_user_ids": ["bob"]})
    assert resp.code == 404
    assert h.events == []


# ── 失败纪律 / 049 既有语义 ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_audit_bridge_exception_does_not_block_patch(monkeypatch, caplog):
    """审计桥抛异常 → PATCH 仍成功、响应码 / 响应结构不变，仅留观测日志。"""
    h = _make(monkeypatch, before_members=[], audit_raises=True)
    with caplog.at_level(logging.WARNING):
        resp = await h.patch({"member_user_ids": ["bob"]})

    assert resp.code == 0
    assert resp.message is None
    assert resp.data["_id"] == PROJECT_ID
    assert resp.data["member_user_ids"] == ["bob"]
    assert any(
        "audit emit failed" in rec.getMessage() for rec in caplog.records
    )


@pytest.mark.asyncio
async def test_non_creator_returns_403_and_no_event(monkeypatch):
    """049 既有语义：非创建者写成员 → 403，且走到不了审计钩子。"""
    h = _make(monkeypatch, caller="intruder", owner=CREATOR, before_members=[])
    resp = await h.patch({"member_user_ids": ["bob"]})
    assert resp.code == 403
    assert h.events == []


@pytest.mark.asyncio
async def test_default_project_returns_400_and_no_event(monkeypatch):
    """049 既有语义：默认项目 → 400，且走到不了审计钩子。"""
    h = _make(monkeypatch, before_members=[])
    resp = await h.patch({"member_user_ids": ["bob"]}, project_id="default")
    assert resp.code == 400
    assert h.events == []


@pytest.mark.asyncio
async def test_member_cap_500_unchanged(monkeypatch):
    """049 既有语义：500 上限仍生效，被拒的请求不发事件。"""
    h = _make(monkeypatch, before_members=[])
    # 用不与创建者 id（"u1"）冲突的前缀，确保 501 个成员全部通过归一化后命中上限。
    resp = await h.patch({"member_user_ids": [f"member-{i}" for i in range(501)]})
    assert resp.code == 400
    assert h.events == []


# ── T033 白名单 ───────────────────────────────────────────────────────


def test_t033_whitelist_049_and_017():
    """白名单与钩子同批：049 分组存在、017 含 §9.4 事件、未知项仍抛 ValueError。"""
    assert "049" in FEATURE_AUDIT_EVENTS
    assert "project.member.granted" in FEATURE_AUDIT_EVENTS["049"]
    assert "project.member.revoked" in FEATURE_AUDIT_EVENTS["049"]

    rec = record_feature_event("049", "project.member.granted", {"project_id": "p1"})
    assert rec["feature"] == "049"
    assert rec["event"] == "project.member.granted"
    assert rec["project_id"] == "p1"

    for event in (
        "memory.promoted",
        "memory.department_write",
        "memory.scope_demoted",
        "memory.archived",
        "memory.deleted",
        "memory.policy.updated",
        "memory.decayed",     # 既有，保留
        "memory.restored",    # 既有，保留
    ):
        assert event in FEATURE_AUDIT_EVENTS["017"]

    with pytest.raises(ValueError):
        record_feature_event("049", "project.member.unknown", {})
    with pytest.raises(ValueError):
        record_feature_event("999", "nope", {})


def test_real_bridge_accepts_c7_events(monkeypatch):
    """真实 emit_feature_event + 真实白名单不抛 ValueError（T032/T033 同批的证明）。

    actor / tenant_id 由 bridge 的 ``record.setdefault`` 并入最终审计记录，
    与设计 §9.4 的 ``emit_feature_event(..., tenant_id=, actor=)`` 调用一致。
    """
    from app.services import feature_audit_bridge as bridge

    # 隔离 DB：只验证「校验 + 归一化」，不真正落库。
    monkeypatch.setattr(
        bridge.FeatureAuditSink, "_persist", lambda self, feature, record: None
    )
    rec = bridge.emit_feature_event(
        "049",
        "project.member.revoked",
        {"project_id": "p1", "added": [], "removed": ["bob"]},
        tenant_id="t1",
        actor="u1",
    )
    assert rec["feature"] == "049"
    assert rec["event"] == "project.member.revoked"
    assert rec["tenant_id"] == "t1"
    assert rec["actor"] == "u1"
    assert rec["removed"] == ["bob"]
