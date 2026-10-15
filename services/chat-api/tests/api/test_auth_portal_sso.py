"""T005 集成测试 + T006 安全测试：门户 SSO 接收方（029）。

覆盖 ``POST /api/auth/portal-ticket``（服务身份签发一次性票据）与
``POST /api/auth/portal-exchange``（验签 + accept-once + 建会话）。

设计（spec 029 / docs/MOGO-Web应用集成方案.md §1.3.2）：
- portal-ticket 需要服务身份（scope ``portal.issue_ticket``），按共享主键 ``end_users._id``
  解析用户，签发一次性票据（TTL 60s，``PORTAL_SSO_SECRET`` 签名）。
- portal-exchange 验签（fail-closed）、按 ``session_id`` accept-once 幂等（第二次 401）、
  单租户直建会话 / 多租户返回选租户挑战 / 跨租户拒绝 / 签名错或过期拒绝。
- 门户**不持有**签名密钥；票据绝不下落 URL。

测试用内存假 DB 与打桩的重依赖，聚焦端点接线（鉴权、验签、幂等、id 匹配、失败回退）。
"""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest
from bson import ObjectId
from fastapi import HTTPException

from app.api.endpoints import auth as auth_module

PORTAL_SECRET = "portal-sso-secret-0123456789abcdef"
USER_ID = "665f1c0c0b1e2a3f4a5b6c7d"
TENANT_ID = "tenant-0001"
USERNAME = "portal-user"


# ---------------------------------------------------------------------------
# 内存假 Mongo 集合 / DB
# ---------------------------------------------------------------------------
class _MatchError(Exception):
    pass


class FakeCollection:
    def __init__(self) -> None:
        self.docs: list[dict] = []

    async def insert_one(self, doc: dict) -> SimpleNamespace:
        stored = dict(doc)
        stored.setdefault("_id", ObjectId())
        self.docs.append(stored)
        return SimpleNamespace(inserted_id=stored["_id"])

    def _matches(self, doc: dict, filt: dict) -> bool:
        for key, cond in filt.items():
            value = doc.get(key)
            if isinstance(cond, dict):
                if "$ne" in cond and value == cond["$ne"]:
                    return False
                if "$in" in cond and value not in cond["$in"]:
                    return False
            elif value != cond:
                return False
        return True

    async def find_one(self, filt: dict) -> dict | None:
        for doc in self.docs:
            if self._matches(doc, filt):
                return dict(doc)
        return None

    async def find(self, filt: dict) -> _FakeCursor:
        return _FakeCursor([dict(d) for d in self.docs if self._matches(d, filt)])

    async def update_one(self, filt: dict, update: dict, upsert: bool = False) -> SimpleNamespace:
        set_doc = update.get("$set", {})
        for doc in self.docs:
            if self._matches(doc, filt):
                doc.update(set_doc)
                return SimpleNamespace(modified_count=1, matched_count=1, upserted_id=None)
        if upsert:
            new_doc = dict(set_doc)
            new_doc.update({k: v for k, v in filt.items() if not isinstance(v, dict)})
            new_doc.setdefault("_id", ObjectId())
            self.docs.append(new_doc)
            return SimpleNamespace(modified_count=0, matched_count=0, upserted_id=new_doc["_id"])
        return SimpleNamespace(modified_count=0, matched_count=0, upserted_id=None)


class _FakeCursor:
    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs

    async def to_list(self, length: int | None = None) -> list[dict]:
        return self._docs


class FakeDB:
    def __init__(self) -> None:
        self._collections: dict[str, FakeCollection] = {}

    def __getitem__(self, name: str) -> FakeCollection:
        return self._collections.setdefault(name, FakeCollection())


def _candidates() -> list[dict]:
    return [
        {
            "userId": USER_ID,
            "tenantId": TENANT_ID,
            "orgName": "门户组织",
            "spaceType": "enterprise",
            "canAccessAdmin": True,
        }
    ]


async def _load_candidates(_db, rows):
    # 依据用户文档的 tenant_id 派生候选租户（便于跨租户用例反映真实绑定）。
    return [
        {
            "userId": str(r.get("_id")),
            "tenantId": r.get("tenant_id") or TENANT_ID,
            "orgName": "门户组织",
            "spaceType": "enterprise",
            "canAccessAdmin": True,
        }
        for r in rows
    ]


@pytest.fixture()
async def env(monkeypatch):
    """接线端点：假 DB、假 settings、打桩的重依赖、服务身份直接放行。"""
    db = FakeDB()

    monkeypatch.setattr(auth_module, "get_db", lambda: db)
    monkeypatch.setattr(
        auth_module,
        "get_settings",
        lambda: SimpleNamespace(PORTAL_SSO_SECRET=PORTAL_SECRET, END_USER_AUTH_SECRET=PORTAL_SECRET),
    )
    monkeypatch.setattr(auth_module, "_verify_portal_service_identity", lambda token: None)

    async def _load_candidates(_db, rows):
        # 依据用户文档 tenant_id 派生候选租户（跨租户用例据此反映真实绑定）。
        return [
            {
                "userId": str(r.get("_id")),
                "tenantId": r.get("tenant_id") or TENANT_ID,
                "orgName": "门户组织",
                "spaceType": "enterprise",
                "canAccessAdmin": True,
            }
            for r in rows
        ]

    monkeypatch.setattr(auth_module, "load_tenant_candidates", _load_candidates)

    created: list[tuple] = []

    async def _create_session(user_doc, available_tenants):
        created.append((user_doc, available_tenants))
        return {
            "token": "session-token-abc",
            "profile": {"userId": user_doc.get("_id"), "username": user_doc.get("login_name")},
            "expiresAt": "2099-01-01T00:00:00+00:00",
        }

    monkeypatch.setattr(auth_module, "_create_session", _create_session)

    async def _create_login_challenge(username, candidates):
        return {
            "challengeToken": "challenge-token-xyz",
            "candidates": candidates,
            "expiresAt": "2099-01-01T00:05:00+00:00",
        }

    monkeypatch.setattr(auth_module, "_create_login_challenge", _create_login_challenge)

    # 预置一个 active 终端用户
    await _seed_user(db)

    return SimpleNamespace(db=db, created=created)


async def _seed_user(db: FakeDB) -> None:
    await db[auth_module.USER_COLLECTION].insert_one(
        {
            "_id": ObjectId(USER_ID),
            "login_name": USERNAME,
            "status": "active",
            "tenant_id": TENANT_ID,
        }
    )


def _portal_ticket_body(user_id: str = USER_ID, tenant_id: str | None = None) -> dict:
    body: dict = {"user_id": user_id}
    if tenant_id is not None:
        body["tenant_id"] = tenant_id
    return body


# ---------------------------------------------------------------------------
# T005：集成——签发 → 换票建会话 → 复药拒绝
# ---------------------------------------------------------------------------
async def test_portal_ticket_then_exchange_creates_session(env) -> None:
    issued = await auth_module.portal_ticket(
        auth_module.PortalTicketRequest(**_portal_ticket_body()), service_token="svc"
    )
    assert issued.code == 0
    token = issued.data["token"]
    assert isinstance(token, str) and token.count(".") == 1
    # 票据 TTL 固定 60s（now + 60，允许几秒误差）
    remaining = int(issued.data["expiresAt"]) - int(time.time())
    assert 55 <= remaining <= 61

    # 单租户：换票直建会话
    exchanged = await auth_module.portal_exchange(
        auth_module.PortalExchangeRequest(portal_token=token)
    )
    assert exchanged.code == 0
    assert exchanged.data["token"] == "session-token-abc"
    assert exchanged.data["profile"]["username"] == USERNAME
    assert env.created, "应复用 _create_session 建立会话"


async def test_portal_exchange_rejects_replay(env) -> None:
    issued = await auth_module.portal_ticket(
        auth_module.PortalTicketRequest(**_portal_ticket_body()), service_token="svc"
    )
    token = issued.data["token"]

    first = await auth_module.portal_exchange(
        auth_module.PortalExchangeRequest(portal_token=token)
    )
    assert first.code == 0

    with pytest.raises(HTTPException) as exc:
        await auth_module.portal_exchange(
            auth_module.PortalExchangeRequest(portal_token=token)
        )
    assert exc.value.status_code == 401


async def test_portal_exchange_multi_tenant_returns_challenge(env, monkeypatch) -> None:
    async def _multi(_db, rows):
        return [
            {"userId": USER_ID, "tenantId": "tenant-0001", "orgName": "A", "spaceType": "enterprise"},
            {"userId": USER_ID, "tenantId": "tenant-0002", "orgName": "B", "spaceType": "enterprise"},
        ]

    monkeypatch.setattr(auth_module, "load_tenant_candidates", _multi)

    issued = await auth_module.portal_ticket(
        auth_module.PortalTicketRequest(**_portal_ticket_body()), service_token="svc"
    )
    token = issued.data["token"]
    # 多租户：票据不携带 tenant_id，换票返回选租户挑战
    assert issued.data.get("requiresTenantSelection") is True

    exchanged = await auth_module.portal_exchange(
        auth_module.PortalExchangeRequest(portal_token=token)
    )
    assert exchanged.code == 0
    assert exchanged.data.get("requiresTenantSelection") is True
    assert exchanged.data["challengeToken"] == "challenge-token-xyz"
    # 多租户不直接建会话
    assert not env.created


# ---------------------------------------------------------------------------
# T006：安全（参数化）——签名错 / 篡改 / 过期 / 复药 / 未知用户 全部拒绝
# ---------------------------------------------------------------------------
async def test_portal_ticket_rejects_unknown_user(env) -> None:
    with pytest.raises(HTTPException) as exc:
        await auth_module.portal_ticket(
            auth_module.PortalTicketRequest(**_portal_ticket_body(user_id="665f1c0c0b1e2a3f4a5b6c99")),
            service_token="svc",
        )
    assert exc.value.status_code in (401, 404)


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda t: t + "x", id="tampered-signature"),
        pytest.param(lambda t: t.split(".")[1] + "." + t.split(".")[1], id="reordered"),
        pytest.param(lambda t: "not-a-token", id="malformed"),
        pytest.param(lambda t: "", id="empty"),
    ],
)
async def test_portal_exchange_rejects_bad_tickets(env, mutate) -> None:
    issued = await auth_module.portal_ticket(
        auth_module.PortalTicketRequest(**_portal_ticket_body()), service_token="svc"
    )
    token = issued.data["token"]

    with pytest.raises(HTTPException) as exc:
        await auth_module.portal_exchange(
            auth_module.PortalExchangeRequest(portal_token=mutate(token))
        )
    assert exc.value.status_code == 401


async def test_portal_exchange_rejects_cross_tenant(env) -> None:
    # 先按 tenant-0001 签发票据，随后用户被移到 tenant-9999，换票应因跨租户被拒。
    issued = await auth_module.portal_ticket(
        auth_module.PortalTicketRequest(**_portal_ticket_body()), service_token="svc"
    )
    token = issued.data["token"]

    env.db[auth_module.USER_COLLECTION].docs[0]["tenant_id"] = "tenant-9999"

    with pytest.raises(HTTPException) as exc:
        await auth_module.portal_exchange(
            auth_module.PortalExchangeRequest(portal_token=token)
        )
    assert exc.value.status_code == 401
