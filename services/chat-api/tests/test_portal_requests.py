"""037 T024 / T025 / T028：门户目录聚合与申领单状态机（chat-api 侧）。

覆盖范围（对应 ``specs/037-unified-portal/tasks.md``）：

* T024 —— 申领单状态机：申请幂等、审批人解析（owner 动态 / 回落管理员 / fail-closed）、
  防自审、条件更新幂等（并发双审批）、批准即开通、拒绝不开通、资产下线自动拒绝、
  回收、惰性过期、我的申领单过滤与分页；
* T025 —— 目录聚合：只列已上架且 active、租户隔离、L1 软裁剪开关、分类 / 关键词、
  016 效果分与 036 评级可选字段；
* T028 —— 端到端链路（服务层）：浏览 → 申领 → 审批 → 开通 → 我的申领 → 回收。

测试用内存假 DB（与 ``tests/api/test_auth_portal_sso.py`` 同一风格），
不连真实 Mongo / panwei，聚焦状态机与字段契约本身。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.endpoints import portal as portal_api
from app.api.principal import ApiPrincipal, require_end_user_principal
from app.services.portal import (
    CATALOG_ASSET_TYPES,
    PORTAL_LISTINGS_COLLECTION,
    PORTAL_REQUESTS_COLLECTION,
    STATUS_TERMINAL,
    build_asset_use_code,
    expire_stale_grants,
    get_asset_basics,
    issue_request,
    list_catalog,
    list_categories,
    list_my_requests,
    resolve_approver,
    revoke_grant,
    decide_request,
)
from app.services.portal import requests as portal_requests

TENANT = "tenant-a"
OTHER_TENANT = "tenant-b"
REQUESTER = "user-1"
OWNER = "user-owner"
ADMIN = "admin-with-approve"


# ---------------------------------------------------------------------------
# 内存假 Mongo（仅实现本特性用到的操作）
# ---------------------------------------------------------------------------
_MISSING = object()


class _MatchError(Exception):
    pass


def _matches(doc: dict, filt: dict) -> bool:
    for key, cond in filt.items():
        if key == "$or":
            if not any(_matches(doc, sub) for sub in cond):
                return False
            continue
        value = doc.get(key, _MISSING)
        if isinstance(cond, dict):
            for op, arg in cond.items():
                if op == "$in":
                    if value is _MISSING or value not in arg:
                        return False
                elif op == "$exists":
                    if bool(arg) != (value is not _MISSING):
                        return False
                elif op == "$ne":
                    if value is not _MISSING and value == arg:
                        return False
                elif op == "$lte":
                    if value is _MISSING or value is None or not value <= arg:
                        return False
                else:  # pragma: no cover - 未实现的查询算子显式报错，避免静默放宽
                    raise _MatchError(op)
        elif value is _MISSING or value != cond:
            return False
    return True


class FakeCollection:
    def __init__(self) -> None:
        self.docs: list[dict] = []

    async def insert_one(self, doc: dict) -> SimpleNamespace:
        self.docs.append(dict(doc))
        return SimpleNamespace(inserted_id=doc.get("request_id") or doc.get("asset_key"))

    async def find_one(self, filt: dict) -> dict | None:
        for doc in self.docs:
            if _matches(doc, filt):
                return dict(doc)
        return None

    def find(self, filt: dict) -> "_FakeCursor":
        return _FakeCursor([dict(d) for d in self.docs if _matches(d, filt)])

    async def update_one(self, filt: dict, update: dict, upsert: bool = False) -> SimpleNamespace:
        set_doc = dict(update.get("$set") or {})
        unset = dict(update.get("$unset") or {})
        for doc in self.docs:
            if _matches(doc, filt):
                doc.update(set_doc)
                for key in unset:
                    doc.pop(key, None)
                return SimpleNamespace(modified_count=1, matched_count=1)
        if upsert:
            new_doc = dict(set_doc)
            new_doc.update({k: v for k, v in filt.items() if not isinstance(v, dict) and k != "$or"})
            self.docs.append(new_doc)
            return SimpleNamespace(modified_count=0, matched_count=0, upserted_id=new_doc.get("code"))
        return SimpleNamespace(modified_count=0, matched_count=0)

    async def delete_one(self, filt: dict) -> SimpleNamespace:
        for index, doc in enumerate(self.docs):
            if _matches(doc, filt):
                self.docs.pop(index)
                return SimpleNamespace(deleted_count=1)
        return SimpleNamespace(deleted_count=0)


class _FakeCursor:
    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs

    async def to_list(self, length: int | None = None) -> list[dict]:
        return self._docs[:length] if length else list(self._docs)


class FakeDB:
    def __init__(self) -> None:
        self._collections: dict[str, FakeCollection] = {}

    def __getitem__(self, name: str) -> FakeCollection:
        return self._collections.setdefault(name, FakeCollection())

    def __getattr__(self, name: str) -> FakeCollection:
        # ``db.skills`` 语法糖
        return self.__getitem__(name)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _seed(db: FakeDB, *, owner: str = OWNER, asset_type: str = "skill", asset_key: str = "skill-1") -> None:
    """上架一条 active 资产（默认：skill-1 的 owner 是 OWNER）。"""
    if asset_type == "skill":
        db["skills"].docs.append(
            {
                "_id": asset_key,
                "tenant_id": TENANT,
                "name": "周报生成",
                "description": "自动汇总周报",
                "tags": ["写作", "效率"],
                "created_by": owner,
                "owner_role": "产品",
                "category": "效率",
            }
        )
    else:
        db["capability_assets"].docs.append(
            {
                "asset_id": asset_key,
                "tenant_id": TENANT,
                "name": "检索能力",
                "state": "active",
                "created_by": owner,
                "kind": "retrieval",
                "endpoint": "http://internal",
            }
        )
    db[PORTAL_LISTINGS_COLLECTION].docs.append(
        {
            "tenant_id": TENANT,
            "asset_type": asset_type,
            "asset_key": asset_key,
            "category": "效率",
            "published_by": "admin",
            "published_at": _now(),
        }
    )


# ---------------------------------------------------------------------------
# T024 申领（幂等 / 审批人解析 / fail-closed）
# ---------------------------------------------------------------------------


async def test_issue_request_creates_applied_and_audits():
    db = FakeDB()
    _seed(db)
    result = await issue_request(
        db, tenant_id=TENANT, requester_id=REQUESTER, asset_type="skill", asset_key="skill-1", reason="需要"
    )
    assert result["status"] == "applied"
    assert result["created"] is True
    row = result["request"]
    assert row["approver_id"] == OWNER  # owner 优先，且 owner != requester
    assert row["status"] == "applied"
    assert row["applied_at"] is not None
    # 审计：申请事件落 gate_events
    events = db["gate_events"].docs
    assert [e["tool"] for e in events] == ["portal.request.applied"]
    assert events[0]["tenant_id"] == TENANT


async def test_issue_request_idempotent_pending():
    db = FakeDB()
    _seed(db)
    first = await issue_request(db, tenant_id=TENANT, requester_id=REQUESTER, asset_type="skill", asset_key="skill-1")
    second = await issue_request(db, tenant_id=TENANT, requester_id=REQUESTER, asset_type="skill", asset_key="skill-1")
    assert second["status"] == "pending"
    assert second["created"] is False
    assert second["request"]["request_id"] == first["request"]["request_id"]
    assert len(db[PORTAL_REQUESTS_COLLECTION].docs) == 1


async def test_issue_request_already_granted_is_idempotent():
    db = FakeDB()
    _seed(db)
    db[PORTAL_REQUESTS_COLLECTION].docs.append(
        {
            "tenant_id": TENANT,
            "request_id": "req-granted",
            "requester_id": REQUESTER,
            "asset_type": "skill",
            "asset_key": "skill-1",
            "status": "granted",
            "applied_at": _now() - timedelta(days=1),
        }
    )
    result = await issue_request(db, tenant_id=TENANT, requester_id=REQUESTER, asset_type="skill", asset_key="skill-1")
    assert result["status"] == "already_granted"
    assert result["created"] is False
    assert len(db[PORTAL_REQUESTS_COLLECTION].docs) == 1


async def test_issue_request_rejects_unpublished_asset():
    db = FakeDB()
    db["skills"].docs.append({"_id": "skill-2", "tenant_id": TENANT, "name": "未上架", "created_by": OWNER})
    with pytest.raises(portal_requests.PortalRequestError) as excinfo:
        await issue_request(db, tenant_id=TENANT, requester_id=REQUESTER, asset_type="skill", asset_key="skill-2")
    assert excinfo.value.reason == "asset_not_published"


async def test_issue_request_fail_closed_without_approver():
    """owner 就是申请人且租户内没有持 portal:approve 的管理员 → 不落单。"""
    db = FakeDB()
    _seed(db, owner=REQUESTER)
    with pytest.raises(portal_requests.PortalRequestError) as excinfo:
        await issue_request(db, tenant_id=TENANT, requester_id=REQUESTER, asset_type="skill", asset_key="skill-1")
    assert excinfo.value.reason == "approver_unresolved"
    assert db[PORTAL_REQUESTS_COLLECTION].docs == []


async def test_resolve_approver_falls_back_to_admin():
    db = FakeDB()
    _seed(db, owner=REQUESTER)  # 申请人 = owner → 必须回落到管理员
    db["admin_accounts"].docs.append(
        {"tenant_id": TENANT, "username": ADMIN, "status": "active", "role_name": "组织管理员", "permission_codes": ["portal:approve"]}
    )
    approver = await resolve_approver(
        db, tenant_id=TENANT, requester_id=REQUESTER, asset_type="skill", asset_key="skill-1"
    )
    assert approver == ADMIN


async def test_resolve_approver_is_dynamic_on_owner_transfer():
    db = FakeDB()
    _seed(db, owner="old-owner")
    before = await resolve_approver(
        db, tenant_id=TENANT, requester_id=REQUESTER, asset_type="skill", asset_key="skill-1"
    )
    db["skills"].docs[0]["created_by"] = "new-owner"  # 转移 owner，不做缓存
    after = await resolve_approver(
        db, tenant_id=TENANT, requester_id=REQUESTER, asset_type="skill", asset_key="skill-1"
    )
    assert (before, after) == ("old-owner", "new-owner")


# ---------------------------------------------------------------------------
# T024 审批（防自审 / 条件更新 / 开通 / 拒绝 / 下线）
# ---------------------------------------------------------------------------


async def _applied(db: FakeDB) -> str:
    result = await issue_request(
        db, tenant_id=TENANT, requester_id=REQUESTER, asset_type="skill", asset_key="skill-1", reason="试用"
    )
    return result["request"]["request_id"]


async def test_decide_approve_grants_user_level_permission():
    db = FakeDB()
    _seed(db)
    request_id = await _applied(db)
    result = await decide_request(
        db, tenant_id=TENANT, request_id=request_id, approver_id=OWNER, approved=True, reason="ok"
    )
    assert result["status"] == "granted"
    assert result["changed"] is True

    rows = db["permission_grants"].docs
    assert len(rows) == 1
    grant = rows[0]
    # 001 字段契约（跨服务一致，admin-api 运行时直接按此判权）
    assert set(grant) == {"tenant_id", "level", "org_id", "user_id", "code", "granted_by", "granted_at"}
    assert grant["tenant_id"] == TENANT
    assert grant["level"] == "user"
    assert grant["org_id"] == ""
    assert grant["user_id"] == REQUESTER
    assert grant["code"] == "asset:use:skill-1"
    assert grant["granted_by"] == OWNER

    row = db[PORTAL_REQUESTS_COLLECTION].docs[0]
    assert row["status"] == "granted"
    assert row["granted_at"] is not None
    assert [e["tool"] for e in db["gate_events"].docs] == [
        "portal.request.applied",
        "portal.request.approved",
        "portal.grant.granted",
    ]


async def test_decide_reject_does_not_grant():
    db = FakeDB()
    _seed(db)
    request_id = await _applied(db)
    result = await decide_request(
        db, tenant_id=TENANT, request_id=request_id, approver_id=OWNER, approved=False, reason="不批"
    )
    assert result["status"] == "rejected"
    assert db["permission_grants"].docs == []
    row = db[PORTAL_REQUESTS_COLLECTION].docs[0]
    assert row["status"] == "rejected"
    assert row["decided_reason"] == "不批"
    assert STATUS_TERMINAL >= {"rejected"}


async def test_decide_forbids_self_approval():
    db = FakeDB()
    _seed(db)
    request_id = await _applied(db)
    with pytest.raises(portal_requests.PortalRequestError) as excinfo:
        await decide_request(db, tenant_id=TENANT, request_id=request_id, approver_id=REQUESTER, approved=True)
    assert excinfo.value.reason == "self_approval_forbidden"
    assert db["permission_grants"].docs == []


async def test_decide_is_idempotent_under_concurrent_approval():
    """条件更新：第二次审批不重复开通。"""
    db = FakeDB()
    _seed(db)
    request_id = await _applied(db)
    first = await decide_request(db, tenant_id=TENANT, request_id=request_id, approver_id=OWNER, approved=True)
    second = await decide_request(db, tenant_id=TENANT, request_id=request_id, approver_id=ADMIN, approved=True)
    assert first["changed"] is True
    assert second["changed"] is False
    assert second["status"] == "granted"
    granted_events = [e for e in db["gate_events"].docs if e["tool"] == "portal.grant.granted"]
    assert len(granted_events) == 1


async def test_decide_auto_rejects_when_asset_offline():
    db = FakeDB()
    _seed(db, asset_type="capability_asset", asset_key="cap-1")
    request_id = await _applied_cap(db)
    db["capability_assets"].docs[0]["state"] = "offline"  # 审批窗口内下线
    result = await decide_request(db, tenant_id=TENANT, request_id=request_id, approver_id=OWNER, approved=True)
    assert result["status"] == "rejected"
    assert result["reason"] == "asset_offline"
    assert db["permission_grants"].docs == []


async def _applied_cap(db: FakeDB) -> str:
    result = await issue_request(
        db, tenant_id=TENANT, requester_id=REQUESTER, asset_type="capability_asset", asset_key="cap-1"
    )
    return result["request"]["request_id"]


# ---------------------------------------------------------------------------
# T018 / T024 回收与惰性过期
# ---------------------------------------------------------------------------


async def test_revoke_grant_removes_permission_and_marks_request():
    db = FakeDB()
    _seed(db)
    request_id = await _applied(db)
    await decide_request(db, tenant_id=TENANT, request_id=request_id, approver_id=OWNER, approved=True)

    result = await revoke_grant(
        db,
        tenant_id=TENANT,
        user_id=REQUESTER,
        asset_type="skill",
        asset_key="skill-1",
        revoked_by=OWNER,
        reason="离职",
    )
    assert result["revoked"] is True
    assert db["permission_grants"].docs == []
    row = db[PORTAL_REQUESTS_COLLECTION].docs[0]
    assert row["status"] == "revoked"
    assert row["revoked_by"] == OWNER
    assert [e["tool"] for e in db["gate_events"].docs][-1] == "portal.grant.revoked"


async def test_expire_stale_grants_is_lazy_and_annotates_list():
    db = FakeDB()
    _seed(db)
    request_id = await _applied(db)
    await decide_request(db, tenant_id=TENANT, request_id=request_id, approver_id=OWNER, approved=True)
    # 手工把一个合法的授权写成已到期（模拟租户 TTL 到期）
    row = db[PORTAL_REQUESTS_COLLECTION].docs[0]
    row["expires_at"] = _now() - timedelta(minutes=1)

    expired = await expire_stale_grants(db, tenant_id=TENANT)
    assert [e["request_id"] for e in expired] == [request_id]
    assert db["permission_grants"].docs == []
    assert db[PORTAL_REQUESTS_COLLECTION].docs[0]["status"] == "expired"
    assert db["gate_events"].docs[-1]["tool"] == "portal.grant.expired"

    mine = await list_my_requests(db, tenant_id=TENANT, requester_id=REQUESTER)
    assert mine["items"][0]["status"] == "expired"
    assert mine["items"][0]["is_expired"] is True
    assert mine["items"][0]["is_terminal"] is True


async def test_list_my_requests_filters_and_paginates():
    db = FakeDB()
    _seed(db, asset_type="skill", asset_key="skill-1")
    _seed(db, asset_type="skill", asset_key="skill-2")
    _seed(db, asset_type="skill", asset_key="skill-3")
    for key in ("skill-1", "skill-2", "skill-3"):
        await issue_request(db, tenant_id=TENANT, requester_id=REQUESTER, asset_type="skill", asset_key=key)

    page1 = await list_my_requests(db, tenant_id=TENANT, requester_id=REQUESTER, page=1, page_size=2)
    page2 = await list_my_requests(db, tenant_id=TENANT, requester_id=REQUESTER, page=2, page_size=2)
    assert page1["total"] == 3
    assert len(page1["items"]) == 2
    assert len(page2["items"]) == 1

    granted = await list_my_requests(db, tenant_id=TENANT, requester_id=REQUESTER, status="granted")
    assert granted["items"] == []

    with pytest.raises(portal_requests.PortalRequestError):
        await list_my_requests(db, tenant_id=TENANT, requester_id=REQUESTER, status="bogus")


async def test_list_my_requests_is_tenant_isolated():
    db = FakeDB()
    _seed(db)
    await issue_request(db, tenant_id=TENANT, requester_id=REQUESTER, asset_type="skill", asset_key="skill-1")
    other = await list_my_requests(db, tenant_id=OTHER_TENANT, requester_id=REQUESTER)
    assert other["items"] == []


# ---------------------------------------------------------------------------
# T025 目录聚合
# ---------------------------------------------------------------------------


async def test_catalog_only_lists_published_and_active():
    db = FakeDB()
    _seed(db, asset_type="skill", asset_key="skill-1")
    # skill-2 已上架但资产不 active（平台技能要求 published）
    db["skills"].docs.append(
        {"_id": "skill-2", "tenant_id": TENANT, "name": "草稿技能", "authoring_mode": "platform", "publication_status": "draft"}
    )
    db[PORTAL_LISTINGS_COLLECTION].docs.append(
        {"tenant_id": TENANT, "asset_type": "skill", "asset_key": "skill-2", "category": "效率", "published_at": _now()}
    )
    # skill-3 已下架
    _seed(db, asset_type="skill", asset_key="skill-3")
    db[PORTAL_LISTINGS_COLLECTION].docs[-1]["unpublished_at"] = _now()

    catalog = await list_catalog(TENANT, db=db)
    assert [item["asset_key"] for item in catalog["items"]] == ["skill-1"]
    assert catalog["total"] == 1


async def test_catalog_is_tenant_isolated():
    db = FakeDB()
    _seed(db)
    db[PORTAL_LISTINGS_COLLECTION].docs.append(
        {"tenant_id": OTHER_TENANT, "asset_type": "skill", "asset_key": "skill-1", "category": "效率"}
    )
    catalog = await list_catalog(OTHER_TENANT, db=db)
    # 其他租户读不到 tenant-a 的 skills 文档（skills 按 tenant_id 过滤）→ 目录为空
    assert catalog["items"] == []


async def test_catalog_l1_filter_soft_switch():
    db = FakeDB()
    _seed(db, asset_type="skill", asset_key="skill-l1")
    db["trust_ratings"].docs.append(
        {"tenant_id": TENANT, "asset_type": "skill", "asset_key": "skill-l1", "level": "L1", "owner_id": OWNER}
    )
    default = await list_catalog(TENANT, db=db)
    assert [i["asset_key"] for i in default["items"]] == ["skill-l1"]
    assert default["items"][0]["rating"] == {"level": "L1", "score": None}

    filtered = await list_catalog(TENANT, db=db, l1_filter_enabled=True)
    assert filtered["items"] == []


async def test_catalog_category_and_keyword_filters_with_categories():
    db = FakeDB()
    _seed(db, asset_type="skill", asset_key="skill-1")
    db["skills"].docs.append(
        {"_id": "skill-9", "tenant_id": TENANT, "name": "财务报表", "description": "季度财报", "created_by": OWNER}
    )
    db[PORTAL_LISTINGS_COLLECTION].docs.append(
        {"tenant_id": TENANT, "asset_type": "skill", "asset_key": "skill-9", "category": "财务"}
    )

    by_category = await list_catalog(TENANT, category="财务", db=db)
    assert [i["asset_key"] for i in by_category["items"]] == ["skill-9"]

    by_keyword = await list_catalog(TENANT, keyword="周报", db=db)
    assert [i["asset_key"] for i in by_keyword["items"]] == ["skill-1"]

    categories = await list_categories(TENANT, db=db)
    assert {c["category"] for c in categories} == {"效率", "财务"}


async def test_catalog_effect_and_rating_are_optional_fields():
    db = FakeDB()
    _seed(db, asset_type="skill", asset_key="skill-1")
    db["skill_quality_metrics"].docs.extend(
        [
            {"tenant_id": TENANT, "skill_key": "skill-1", "date": "2026-10-01", "effect_score": 0.8, "samples": 10},
            {"tenant_id": TENANT, "skill_key": "skill-1", "date": "2026-10-02", "effect_score": 0.4, "samples": 30},
        ]
    )
    db["trust_ratings"].docs.append(
        {"tenant_id": TENANT, "asset_type": "skill", "asset_key": "skill-1", "level": "L3"}
    )
    basic = await get_asset_basics(TENANT, "skill", "skill-1", db=db)
    assert basic["effect"]["effect_score"] == 0.5  # (0.8*10 + 0.4*30) / 40
    assert basic["effect"]["samples"] == 40
    assert basic["rating"]["level"] == "L3"

    # 无指标时字段缺席（前端隐藏），不报错
    db2 = FakeDB()
    _seed(db2, asset_type="skill", asset_key="skill-1")
    basic2 = await get_asset_basics(TENANT, "skill", "skill-1", db=db2)
    assert basic2["effect"] is None and basic2["rating"] is None


async def test_catalog_supports_capability_assets():
    db = FakeDB()
    _seed(db, asset_type="capability_asset", asset_key="cap-1")
    catalog = await list_catalog(TENANT, db=db)
    assert [i["asset_key"] for i in catalog["items"]] == ["cap-1"]
    assert catalog["items"][0]["kind"] == "retrieval"
    assert "capability_asset" in CATALOG_ASSET_TYPES


# ---------------------------------------------------------------------------
# T013 / T015 端点契约（鉴权 + 租户隔离 + 错误映射）
# ---------------------------------------------------------------------------


@pytest.fixture()
def api(monkeypatch):
    """把 chat-api 门户端点挂到裸 FastAPI 上，假 DB + 放行 end_user 身份。"""
    db = FakeDB()
    monkeypatch.setattr(portal_api, "get_db", lambda: db)
    app = FastAPI()
    app.include_router(portal_api.router)

    def _principal() -> ApiPrincipal:
        return ApiPrincipal(kind="end_user", tenant_id=TENANT, user_id=REQUESTER)

    app.dependency_overrides[require_end_user_principal] = _principal
    return TestClient(app), db


def test_api_catalog_and_detail(api):
    client, db = api
    _seed(db, asset_type="skill", asset_key="skill-1")

    listing = client.get("/api/portal/catalog")
    assert listing.status_code == 200
    assert [i["asset_key"] for i in listing.json()["items"]] == ["skill-1"]

    detail = client.get("/api/portal/catalog/skill/skill-1")
    assert detail.status_code == 200
    body = detail.json()
    assert body["item"]["name"] == "周报生成"
    assert body["granted"] is False
    assert body["my_request"] is None

    missing = client.get("/api/portal/catalog/skill/nope")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "asset_not_found"


def test_api_create_request_then_mine(api):
    client, db = api
    _seed(db)
    created = client.post(
        "/api/portal/requests",
        json={"asset_type": "skill", "asset_key": "skill-1", "reason": "需要生成周报"},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["status"] == "applied"
    assert body["request"]["approver_id"] == OWNER

    again = client.post("/api/portal/requests", json={"asset_type": "skill", "asset_key": "skill-1"})
    assert again.status_code == 201
    assert again.json()["status"] == "pending"

    mine = client.get("/api/portal/requests/mine")
    assert mine.status_code == 200
    assert mine.json()["total"] == 1
    assert mine.json()["items"][0]["status"] == "applied"


def test_api_create_request_approver_unresolved_returns_409(api):
    client, db = api
    _seed(db, owner=REQUESTER)  # 无 owner 之外的审批人
    response = client.post("/api/portal/requests", json={"asset_type": "skill", "asset_key": "skill-1"})
    assert response.status_code == 409
    assert response.json()["detail"] == "approver_unresolved"


def test_api_revoke_requires_requester_or_owner(api, monkeypatch):
    client, db = api
    _seed(db)
    created = client.post("/api/portal/requests", json={"asset_type": "skill", "asset_key": "skill-1"})
    request_id = created.json()["request"]["request_id"]
    # 单还没开通 → 回收无授权，但请求存在；申请人本人允许
    ok = client.post(f"/api/portal/requests/{request_id}/revoke", json={"reason": "不需要了"})
    assert ok.status_code == 200

    # 换成无关用户 → 403
    outsider = ApiPrincipal(kind="end_user", tenant_id=TENANT, user_id="someone-else")
    client.app.dependency_overrides[require_end_user_principal] = lambda: outsider
    forbidden = client.post(f"/api/portal/requests/{request_id}/revoke", json={})
    assert forbidden.status_code == 403


# ---------------------------------------------------------------------------
# T028 端到端（服务层全链路）
# ---------------------------------------------------------------------------


async def test_full_chain_browse_apply_approve_grant_revoke():
    db = FakeDB()
    _seed(db, asset_type="skill", asset_key="skill-1")

    catalog = await list_catalog(TENANT, db=db)
    assert catalog["total"] == 1

    applied = await issue_request(
        db, tenant_id=TENANT, requester_id=REQUESTER, asset_type="skill", asset_key="skill-1", reason="试点"
    )
    request_id = applied["request"]["request_id"]

    decided = await decide_request(
        db, tenant_id=TENANT, request_id=request_id, approver_id=OWNER, approved=True, reason="批准试点"
    )
    assert decided["status"] == "granted"

    grants = db["permission_grants"].docs
    assert [g["code"] for g in grants] == [build_asset_use_code("skill-1")]

    mine = await list_my_requests(db, tenant_id=TENANT, requester_id=REQUESTER)
    assert mine["items"][0]["status"] == "granted"

    revoked = await revoke_grant(
        db, tenant_id=TENANT, user_id=REQUESTER, asset_type="skill", asset_key="skill-1", revoked_by=OWNER
    )
    assert revoked["revoked"] is True
    assert db["permission_grants"].docs == []
    mine_after = await list_my_requests(db, tenant_id=TENANT, requester_id=REQUESTER)
    assert mine_after["items"][0]["status"] == "revoked"
