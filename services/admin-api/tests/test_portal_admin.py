"""037 T026 / T027：门户管理侧（上架 / 下架 / 审批 / 回收）契约测试。

覆盖范围（``specs/037-unified-portal/tasks.md``）：

* T026 —— 管理侧 API 契约：上架 / 下架 / 审批队列 / 批准 / 拒绝 / 回收的
  鉴权、租户隔离、错误码，以及**跨服务字段契约**（``portal_listings``、
  ``portal_requests``、``permission_grants`` 的字段集合与取值）；
* T027 —— 上架 / 下架即时生效（写 ``unpublished_at`` 后 chat-api 目录立即读不到，
  且**不撤销**存量授权）、操作留 ``gate_events`` 审计。

chat-api 侧同契约由 ``services/chat-api/tests/test_portal_requests.py`` 覆盖；
两个服务的文档字段靠这些测试锁住，防止漂移。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_current_admin_user
from app.api.routes import portal_admin

TENANT = "tenant-a"
OTHER_TENANT = "tenant-b"
OWNER = "owner-1"
OTHER_ADMIN = "admin-2"
APPROVER = "owner-1"
REQUESTER = "user-1"

_MISSING = object()


# ---------------------------------------------------------------------------
# 内存假 Mongo
# ---------------------------------------------------------------------------
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
                else:  # pragma: no cover
                    raise _MatchError(op)
        elif value is _MISSING or value != cond:
            return False
    return True


class FakeCollection:
    def __init__(self, name: str = "") -> None:
        self.name = name
        self.docs: list[dict] = []
        self.indexes: list[dict] = []

    async def create_index(self, keys, name: str = "", unique: bool = False):
        self.indexes.append({"keys": list(keys), "name": name, "unique": unique})
        return name

    async def insert_one(self, doc: dict) -> SimpleNamespace:
        self.docs.append(dict(doc))
        return SimpleNamespace(inserted_id=doc.get("event_id"))

    async def find_one(self, filt: dict) -> dict | None:
        for doc in self.docs:
            if _matches(doc, filt):
                return dict(doc)
        return None

    def find(self, filt: dict) -> "_FakeCursor":
        return _FakeCursor([dict(d) for d in self.docs if _matches(doc=d, filt=filt)])

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
        return self._collections.setdefault(name, FakeCollection(name))

    def __getattr__(self, name: str) -> FakeCollection:
        return self.__getitem__(name)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _user(username: str, *, role: str = "组织管理员", codes=None, tenant: str = TENANT) -> dict:
    return {
        "username": username,
        "tenant_id": tenant,
        "role_name": role,
        "permission_codes": list(codes or []),
        "display_name": username,
    }


def _seed_skill(db: FakeDB, *, key: str = "skill-1", owner: str = OWNER) -> None:
    db["skills"].docs.append(
        {"_id": key, "tenant_id": TENANT, "name": "周报生成", "created_by": owner, "authoring_mode": "platform", "publication_status": "published"}
    )


@pytest.fixture()
def api(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(portal_admin, "get_db", lambda: db)
    app = FastAPI()
    app.include_router(portal_admin.router, prefix="/api")  # 025 T035：独立挂 router 需补 "/api" 前缀，使路由落在 /api/portal/*
    holder = {"user": _user(OWNER, role="平台管理员")}
    app.dependency_overrides[get_current_admin_user] = lambda: holder["user"]
    client = TestClient(app)
    client.holder = holder  # type: ignore[attr-defined]
    return client, db


# ---------------------------------------------------------------------------
# T027 上架
# ---------------------------------------------------------------------------


def test_publish_by_owner_creates_listing_and_audit(api):
    client, db = api
    _seed_skill(db)
    client.holder["user"] = _user(OWNER)  # 普通管理员，靠资产 owner 上架

    response = client.post("/api/portal/listings", json={"asset_type": "skill", "asset_key": "skill-1", "category": "效率"})
    assert response.status_code == 201
    body = response.json()
    assert body["published"] is True
    assert body["listing"]["category"] == "效率"

    rows = db["portal_listings"].docs
    assert len(rows) == 1
    assert set(rows[0]) >= {"tenant_id", "asset_type", "asset_key", "category", "published_by", "published_at"}
    assert rows[0]["tenant_id"] == TENANT
    assert rows[0]["published_by"] == OWNER
    assert "unpublished_at" not in rows[0]

    events = db["gate_events"].docs
    assert [e["tool"] for e in events] == ["portal.listing.publish"]
    assert events[0]["tenant_id"] == TENANT
    assert events[0]["detail"] == {"asset_type": "skill", "asset_key": "skill-1", "category": "效率"}


def test_publish_requires_ownership_or_manage_permission(api):
    client, db = api
    _seed_skill(db, owner=OWNER)
    client.holder["user"] = _user(OTHER_ADMIN)  # 非 owner、无 portal:manage
    response = client.post("/api/portal/listings", json={"asset_type": "skill", "asset_key": "skill-1"})
    assert response.status_code == 403
    assert db["portal_listings"].docs == []


def test_publish_platform_admin_can_publish_any_asset(api):
    client, db = api
    _seed_skill(db, owner=OWNER)
    client.holder["user"] = _user("platform", role="平台管理员")
    assert client.post("/api/portal/listings", json={"asset_type": "skill", "asset_key": "skill-1"}).status_code == 201
    assert len(db["portal_listings"].docs) == 1


def test_publish_unknown_asset_404_and_inactive_409(api):
    client, db = api
    client.holder["user"] = _user("platform", role="平台管理员")
    assert client.post("/api/portal/listings", json={"asset_type": "skill", "asset_key": "nope"}).status_code == 404

    _seed_skill(db, key="skill-draft")
    db["skills"].docs[-1]["publication_status"] = "draft"  # platform 技能未发布 → 不可上架
    response = client.post("/api/portal/listings", json={"asset_type": "skill", "asset_key": "skill-draft"})
    assert response.status_code == 409
    assert response.json()["detail"] == "asset_not_active"


def test_publish_is_idempotent_and_keeps_first_published_at(api):
    client, db = api
    _seed_skill(db)
    client.holder["user"] = _user("platform", role="平台管理员")
    first = client.post("/api/portal/listings", json={"asset_type": "skill", "asset_key": "skill-1", "category": "效率"})
    published_at = first.json()["listing"]["published_at"]
    second = client.post("/api/portal/listings", json={"asset_type": "skill", "asset_key": "skill-1", "category": "协作"})
    assert second.status_code == 201
    assert second.json()["listing"]["published_at"] == published_at
    assert second.json()["listing"]["category"] == "协作"
    assert len(db["portal_listings"].docs) == 1


def test_publish_unsupported_asset_type_400(api):
    client, db = api
    client.holder["user"] = _user("platform", role="平台管理员")
    assert client.post("/api/portal/listings", json={"asset_type": "tool", "asset_key": "x"}).status_code == 400


def test_publish_capability_asset_requires_active_state(api):
    client, db = api
    client.holder["user"] = _user("platform", role="平台管理员")
    db["capability_assets"].docs.append({"asset_id": "cap-1", "tenant_id": TENANT, "name": "检索", "state": "offline"})
    assert client.post("/api/portal/listings", json={"asset_type": "capability_asset", "asset_key": "cap-1"}).status_code == 409
    db["capability_assets"].docs[0]["state"] = "active"
    assert client.post("/api/portal/listings", json={"asset_type": "capability_asset", "asset_key": "cap-1"}).status_code == 201


# ---------------------------------------------------------------------------
# T027 下架（即时生效 + 不撤销存量授权）
# ---------------------------------------------------------------------------


def test_unpublish_takes_effect_immediately_and_keeps_grants(api):
    client, db = api
    _seed_skill(db)
    client.holder["user"] = _user("platform", role="平台管理员")
    client.post("/api/portal/listings", json={"asset_type": "skill", "asset_key": "skill-1"})
    # 已有存量授权
    db["permission_grants"].docs.append(
        {"tenant_id": TENANT, "level": "user", "org_id": "", "user_id": REQUESTER, "code": "asset:use:skill-1"}
    )

    response = client.delete("/api/portal/listings/skill/skill-1")
    assert response.status_code == 200
    assert response.json()["unpublished"] is True

    row = db["portal_listings"].docs[0]
    assert row["unpublished_at"] is not None
    # chat-api 目录的下架过滤条件（见 services/chat-api/app/services/portal/listings.py）
    assert _matches(row, {"$or": [{"unpublished_at": None}, {"unpublished_at": {"$exists": False}}]}) is False
    # 存量授权不受影响（spec 明确边界）
    assert len(db["permission_grants"].docs) == 1
    assert db["gate_events"].docs[-1]["tool"] == "portal.listing.unpublish"
    assert db["gate_events"].docs[-1]["decision"] == "deny"


def test_unpublish_unknown_listing_404(api):
    client, db = api
    client.holder["user"] = _user("platform", role="平台管理员")
    assert client.delete("/api/portal/listings/skill/ghost").status_code == 404


def test_unpublish_requires_ownership(api):
    client, db = api
    _seed_skill(db, owner=OWNER)
    client.holder["user"] = _user("platform", role="平台管理员")
    client.post("/api/portal/listings", json={"asset_type": "skill", "asset_key": "skill-1"})
    client.holder["user"] = _user(OTHER_ADMIN)
    assert client.delete("/api/portal/listings/skill/skill-1").status_code == 403
    assert db["portal_listings"].docs[0].get("unpublished_at") is None


def test_list_listings_joins_asset_name_and_visibility(api):
    client, db = api
    _seed_skill(db)
    client.holder["user"] = _user("platform", role="平台管理员")
    client.post("/api/portal/listings", json={"asset_type": "skill", "asset_key": "skill-1"})

    published = client.get("/api/portal/listings")
    assert published.status_code == 200
    items = published.json()["items"]
    assert [i["asset_key"] for i in items] == ["skill-1"]
    assert items[0]["name"] == "周报生成"
    assert items[0]["published"] is True
    assert items[0]["is_active_asset"] is True

    client.delete("/api/portal/listings/skill/skill-1")
    assert client.get("/api/portal/listings").json()["items"] == []
    history = client.get("/api/portal/listings", params={"published_only": False}).json()["items"]
    assert history[0]["published"] is False


# ---------------------------------------------------------------------------
# T026 审批队列 / 批准 / 拒绝 / 回收
# ---------------------------------------------------------------------------


def _seed_request(db: FakeDB, *, request_id="req-1", status="applied", requester=REQUESTER, tenant=TENANT, key="skill-1", **extra):
    doc = {
        "tenant_id": tenant,
        "request_id": request_id,
        "requester_id": requester,
        "asset_type": "skill",
        "asset_key": key,
        "reason": "试点",
        "status": status,
        "approver_id": OWNER,
        "applied_at": _now(),
    }
    doc.update(extra)
    db["portal_requests"].docs.append(doc)
    return doc


def test_approval_queue_defaults_to_applied_and_is_tenant_scoped(api):
    client, db = api
    _seed_skill(db)
    _seed_request(db, request_id="req-1")
    _seed_request(db, request_id="req-2", status="granted")
    _seed_request(db, request_id="req-3", tenant=OTHER_TENANT)

    client.holder["user"] = _user(APPROVER, role="平台管理员")
    queue = client.get("/api/portal/approvals").json()
    assert [i["request_id"] for i in queue["items"]] == ["req-1"]
    assert queue["items"][0]["asset_name"] == "周报生成"
    assert queue["items"][0]["can_decide"] is True

    all_rows = client.get("/api/portal/approvals", params={"status": "all"}).json()
    assert {i["request_id"] for i in all_rows["items"]} == {"req-1", "req-2"}
    assert client.get("/api/portal/approvals", params={"status": "bogus"}).status_code == 400


def test_queue_marks_self_request_as_not_decidable(api):
    client, db = api
    _seed_skill(db)
    _seed_request(db, request_id="req-self", requester=OWNER)
    client.holder["user"] = _user(OWNER, role="平台管理员")
    items = client.get("/api/portal/approvals").json()["items"]
    assert items[0]["can_decide"] is False


def test_decide_requires_approve_permission(api):
    client, db = api
    _seed_skill(db)
    _seed_request(db)
    client.holder["user"] = _user(OTHER_ADMIN)  # 无 portal:approve
    response = client.post("/api/portal/approvals/req-1/decide", json={"approved": True})
    assert response.status_code == 403
    assert response.json()["detail"] == "missing permission: portal:approve"


def test_decide_approve_writes_grant_with_exact_contract(api):
    client, db = api
    _seed_skill(db)
    _seed_request(db)
    client.holder["user"] = _user(APPROVER, role="平台管理员")

    response = client.post("/api/portal/approvals/req-1/decide", json={"approved": True, "reason": "批准"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "granted"
    assert body["changed"] is True
    assert body["grant"] == "asset:use:skill-1"

    grant = db["permission_grants"].docs[0]
    # 001 permission_grants 字段契约（字段集合必须精确，chat-api 侧写同样 7 个字段）
    assert set(grant) == {"tenant_id", "level", "org_id", "user_id", "code", "granted_by", "granted_at"}
    assert (grant["tenant_id"], grant["level"], grant["org_id"], grant["user_id"]) == (TENANT, "user", "", REQUESTER)
    assert grant["code"] == "asset:use:skill-1"
    assert grant["granted_by"] == APPROVER

    row = db["portal_requests"].docs[0]
    assert row["status"] == "granted"
    assert row["approver_id"] == APPROVER
    assert row["decided_at"] is not None
    assert row["granted_at"] is not None
    assert row["decided_reason"] == "批准"
    assert [e["tool"] for e in db["gate_events"].docs] == ["portal.grant.granted"]


def test_decide_forbids_self_approval(api):
    client, db = api
    _seed_skill(db)
    _seed_request(db, requester=OWNER)
    client.holder["user"] = _user(OWNER, role="平台管理员")
    response = client.post("/api/portal/approvals/req-1/decide", json={"approved": True})
    assert response.status_code == 403
    assert response.json()["detail"] == "self_approval_forbidden"
    assert db["permission_grants"].docs == []


def test_decide_is_idempotent_for_already_decided_request(api):
    client, db = api
    _seed_skill(db)
    _seed_request(db)
    client.holder["user"] = _user(APPROVER, role="平台管理员")
    first = client.post("/api/portal/approvals/req-1/decide", json={"approved": True}).json()
    second = client.post("/api/portal/approvals/req-1/decide", json={"approved": True}).json()
    assert first["changed"] is True
    assert second["changed"] is False
    assert second["status"] == "granted"
    assert len(db["permission_grants"].docs) == 1
    assert [e["tool"] for e in db["gate_events"].docs] == ["portal.grant.granted"]


def test_decide_reject_sets_reason_and_no_grant(api):
    client, db = api
    _seed_skill(db)
    _seed_request(db)
    client.holder["user"] = _user(APPROVER, role="平台管理员")
    response = client.post("/api/portal/approvals/req-1/decide", json={"approved": False, "reason": "不合规"})
    assert response.json()["status"] == "rejected"
    assert db["permission_grants"].docs == []
    assert db["portal_requests"].docs[0]["decided_reason"] == "不合规"
    assert db["gate_events"].docs[-1]["tool"] == "portal.request.rejected"


def test_decide_auto_rejects_when_asset_went_offline(api):
    client, db = api
    _seed_skill(db)
    _seed_request(db)
    db["skills"].docs[0]["publication_status"] = "archived"  # 审批窗口内下线
    client.holder["user"] = _user(APPROVER, role="平台管理员")
    body = client.post("/api/portal/approvals/req-1/decide", json={"approved": True}).json()
    assert body["status"] == "rejected"
    assert body["reason"] == "asset_offline"
    assert db["permission_grants"].docs == []


def test_decide_unknown_request_404(api):
    client, db = api
    client.holder["user"] = _user(APPROVER, role="平台管理员")
    assert client.post("/api/portal/approvals/ghost/decide", json={"approved": True}).status_code == 404


def test_grant_ttl_sets_expires_at(api):
    client, db = api
    _seed_skill(db)
    _seed_request(db)
    db["portal_settings"].docs.append({"tenant_id": TENANT, "grant_ttl_days": 7})
    client.holder["user"] = _user(APPROVER, role="平台管理员")
    body = client.post("/api/portal/approvals/req-1/decide", json={"approved": True}).json()
    expires_at = body["request"]["expires_at"]
    assert expires_at is not None
    assert db["portal_requests"].docs[0]["expires_at"] is not None


def test_revoke_removes_grant_and_marks_request(api):
    client, db = api
    _seed_skill(db)
    _seed_request(db, status="granted", granted_at=_now())
    db["permission_grants"].docs.append(
        {"tenant_id": TENANT, "level": "user", "org_id": "", "user_id": REQUESTER, "code": "asset:use:skill-1", "granted_by": OWNER, "granted_at": _now()}
    )
    client.holder["user"] = _user("platform", role="平台管理员")
    response = client.post("/api/portal/requests/req-1/revoke", json={"reason": "违规"})
    assert response.status_code == 200
    assert response.json()["revoked"] is True
    assert response.json()["grant_removed"] is True
    assert db["permission_grants"].docs == []
    row = db["portal_requests"].docs[0]
    assert row["status"] == "revoked"
    assert row["revoke_reason"] == "违规"
    assert db["gate_events"].docs[-1]["tool"] == "portal.grant.revoked"


def test_revoke_requires_ownership(api):
    client, db = api
    _seed_skill(db, owner=OWNER)
    _seed_request(db, status="granted")
    client.holder["user"] = _user(OTHER_ADMIN)
    assert client.post("/api/portal/requests/req-1/revoke", json={}).status_code == 403


# ---------------------------------------------------------------------------
# 跨服务契约 / 索引
# ---------------------------------------------------------------------------


def test_collection_and_status_constants_match_chat_api():
    """两个服务共享同一 Mongo 集合名与状态机取值（chat-api 侧同名常量）。"""
    assert portal_admin.PORTAL_LISTINGS_COLLECTION == "portal_listings"
    assert portal_admin.PORTAL_REQUESTS_COLLECTION == "portal_requests"
    assert portal_admin.PERMISSION_GRANTS_COLLECTION == "permission_grants"
    assert portal_admin.GATE_EVENTS_COLLECTION == "gate_events"
    assert portal_admin.CATALOG_ASSET_TYPES == ("skill", "capability_asset")
    assert portal_admin.PORTAL_STATUSES == (
        "applied",
        "approved",
        "rejected",
        "granted",
        "revoked",
        "expired",
    )
    assert portal_admin.build_asset_use_code("skill-1") == "asset:use:skill-1"


def test_ensure_indexes_creates_portal_indexes():
    db = FakeDB()
    asyncio.run(portal_admin.ensure_indexes(db))
    listing_indexes = db["portal_listings"].indexes
    assert {"keys": [("tenant_id", 1), ("asset_type", 1), ("asset_key", 1)], "name": "portal_listing_key", "unique": True} in listing_indexes
    request_indexes = {i["name"]: i for i in db["portal_requests"].indexes}
    assert request_indexes["portal_request_key"]["unique"] is True
    assert {"keys": [("tenant_id", 1), ("status", 1), ("applied_at", -1)], "name": "portal_request_queue", "unique": False} in db["portal_requests"].indexes
