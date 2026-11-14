"""T030/T031 单测：SSO 令牌 POST 换票（022 FR-14 / QF-634）。

覆盖 admin-api `POST /auth/sso/exchange`：

- `_verify_sso_token`：签名 / 格式 / 过期 fail-closed；
- 一次性幂等：同一 SSO 票据只能换票一次，重放直接 401；
- 成功后签发新的管理端 access token 并注册会话。

全部用内存 fake motor，不启动 MongoDB。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

import base64
import pytest

from app.api.routes import auth as auth_routes
from app.api.routes.auth import SSOExchangeRequest, _verify_sso_token
from fastapi import HTTPException


FIXED_NOW = 1_700_000_000.0
TENANT = "tenant-001"
USERNAME = "alice"
SECRET = "s" * 48  # 与 settings.jwt_secret 对齐（测试内 monkeypatch）


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(raw: str) -> bytes:
    return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))


def _sign_sso_token(
    *,
    username: str = USERNAME,
    tenant_id: str = TENANT,
    session_id: str = "sso-sess-1",
    role_name: str = "租户管理员",
    org_name: str = "测试组织",
    expires_at: int = int(FIXED_NOW) + 60,
    secret: str = SECRET,
) -> str:
    """按 chat-api `_create_admin_token` 的格式签一枚 SSO 票据。"""
    payload = {
        "sub": {
            "username": username,
            "role_name": role_name,
            "org_name": org_name,
            "tenant_id": tenant_id,
            "session_id": session_id,
        },
        "exp": expires_at,
    }
    encoded_payload = _b64encode(
        json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    )
    signature = _b64encode(
        hmac.new(secret.encode("utf-8"), encoded_payload.encode("utf-8"), hashlib.sha256).digest()
    )
    return f"{encoded_payload}.{signature}"


# ---------------------------------------------------------------------------
# 内存 fake motor（复用 test_token_lifecycle 的模式）
# ---------------------------------------------------------------------------


def _matches(doc: dict, query: dict) -> bool:
    for key, expected in (query or {}).items():
        actual = doc.get(key)
        if isinstance(expected, dict):
            for op, operand in expected.items():
                if op == "$ne" and actual == operand:
                    return False
        elif actual != expected:
            return False
    return True


class FakeCollection:
    def __init__(self, name: str) -> None:
        self.name = name
        self.docs: list[dict] = []

    async def find_one(self, query: dict, projection=None) -> dict | None:
        for doc in self.docs:
            if _matches(doc, query or {}):
                return dict(doc)
        return None

    async def insert_one(self, doc: dict) -> None:
        self.docs.append(dict(doc))

    async def update_one(self, query: dict, update: dict, upsert: bool = False) -> None:
        for doc in self.docs:
            if _matches(doc, query or {}):
                doc.update(update.get("$set", {}))
                return
        if upsert:
            merged = dict(query)
            merged.update(update.get("$set", {}))
            self.docs.append(merged)

    async def update_many(self, query: dict, update: dict, upsert: bool = False) -> None:
        for doc in self.docs:
            if _matches(doc, query or {}):
                doc.update(update.get("$set", {}))

    async def delete_many(self, query: dict) -> None:
        self.docs = [d for d in self.docs if not _matches(d, query or {})]


class FakeDB:
    def __init__(self) -> None:
        self.collections: dict[str, FakeCollection] = {}

    def __getitem__(self, name: str) -> FakeCollection:
        return self.collections.setdefault(name, FakeCollection(name))


@pytest.fixture
def fake_db(monkeypatch) -> FakeDB:
    db = FakeDB()
    monkeypatch.setattr(auth_routes, "get_db", lambda: db)
    # create_session 在独立模块里取自己的 get_db，也要一并指向内存库。
    from app.repositories import admin_session_repository

    monkeypatch.setattr(admin_session_repository, "get_db", lambda: db)
    return db


@pytest.fixture
def aligned_secret(monkeypatch) -> str:
    """让 settings.jwt_secret 与测试签名的 SECRET 一致。"""
    monkeypatch.setattr(auth_routes.settings, "jwt_secret", SECRET)
    return SECRET


@pytest.fixture
def fixed_clock(monkeypatch) -> None:
    """冻结 time.time()，让过期判定可预测。"""
    monkeypatch.setattr(time, "time", lambda: float(FIXED_NOW))


def _seed_active_account(db: FakeDB) -> None:
    """在 admin_accounts 里放一个 active 账号。"""
    db["admin_accounts"].docs.append(
        {
            "_id": "acct-1",
            "username": USERNAME,
            "tenant_id": TENANT,
            "status": "active",
            "role_name": "租户管理员",
            "org_name": "测试组织",
        }
    )


# ---------------------------------------------------------------------------
# _verify_sso_token
# ---------------------------------------------------------------------------


def test_verify_accepts_valid_token(aligned_secret, fixed_clock) -> None:
    subject = _verify_sso_token(_sign_sso_token())
    assert subject["username"] == USERNAME
    assert subject["tenant_id"] == TENANT
    assert subject["session_id"] == "sso-sess-1"


def test_verify_rejects_tampered_payload(aligned_secret) -> None:
    """攻击者改 payload 里的 tenant_id 必须因签名失效被拒。"""
    token = _sign_sso_token()
    parts = token.split(".")
    payload = json.loads(_b64decode(parts[0]))
    payload["sub"]["tenant_id"] = "tenant-EVIL"
    forged = (
        f"{_b64encode(json.dumps(payload, separators=(',', ':')).encode())}|{parts[1]}"
    )
    with pytest.raises(HTTPException) as excinfo:
        _verify_sso_token(forged)
    assert excinfo.value.status_code == 401


def test_verify_rejects_wrong_secret() -> None:
    """用另一把密钥签的令牌必须被拒（fail-closed，不降级）。"""
    token = _sign_sso_token(secret="w" * 48)
    with pytest.raises(HTTPException) as excinfo:
        _verify_sso_token(token)
    assert excinfo.value.status_code == 401


def test_verify_rejects_expired_token(aligned_secret, fixed_clock) -> None:
    token = _sign_sso_token(expires_at=int(FIXED_NOW) - 10)
    with pytest.raises(HTTPException) as excinfo:
        _verify_sso_token(token)
    assert excinfo.value.status_code == 401
    assert "过期" in str(excinfo.value.detail)


@pytest.mark.parametrize(
    "token",
    ["", "   ", "not-a-token", "only-payload", "a.b.c.d", "."],
)
def test_verify_rejects_malformed_token(aligned_secret, token: str) -> None:
    with pytest.raises(HTTPException) as excinfo:
        _verify_sso_token(token)
    assert excinfo.value.status_code == 401


def test_verify_rejects_missing_session_id(aligned_secret) -> None:
    """票据里没有 session_id 时无法做一次性幂等，必须拒绝。"""
    payload = {"sub": {"username": USERNAME, "tenant_id": TENANT}, "exp": int(FIXED_NOW) + 60}
    encoded = _b64encode(json.dumps(payload, separators=(",", ":")).encode())
    sig = _b64encode(
        hmac.new(SECRET.encode(), encoded.encode(), hashlib.sha256).digest()
    )
    with pytest.raises(HTTPException):
        _verify_sso_token(f"{encoded}.{sig}")


# ---------------------------------------------------------------------------
# POST /auth/sso/exchange
# ---------------------------------------------------------------------------


def test_exchange_issues_admin_token_and_registers_session(
    fake_db, aligned_secret, fixed_clock
) -> None:
    _seed_active_account(fake_db)
    from starlette.testclient import TestClient
    from app.main import create_app

    app = create_app()
    client = TestClient(app)

    response = client.post("/api/auth/sso/exchange", json={"sso_token": _sign_sso_token()})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["code"] == 0
    assert body["data"]["accessToken"]
    assert body["data"]["sessionId"]

    docs = fake_db["admin_sessions"].docs
    # 新增的管理端会话
    new_session = next(d for d in docs if d.get("session_id") == body["data"]["sessionId"])
    assert new_session["username"] == USERNAME
    assert new_session["tenant_id"] == TENANT
    # 一次性消费标记（SSO 票据的 session_id 被打上 exchanged=True）
    consumed = next(d for d in docs if d.get("session_id") == "sso-sess-1")
    assert consumed.get("exchanged") is True


def test_exchange_rejects_replay(fake_db, aligned_secret, fixed_clock) -> None:
    _seed_active_account(fake_db)
    """同一 SSO 票据第二次换票必须 401（accept-once 幂等）。"""
    from starlette.testclient import TestClient
    from app.main import create_app

    app = create_app()
    client = TestClient(app)

    token = _sign_sso_token()
    first = client.post("/api/auth/sso/exchange", json={"sso_token": token})
    assert first.status_code == 200, first.text

    second = client.post("/api/auth/sso/exchange", json={"sso_token": token})
    assert second.status_code == 401
    assert "已使用" in second.json().get("detail", "")


def test_exchange_rejects_inactive_account(fake_db, aligned_secret, fixed_clock) -> None:
    """账号已停用时拒绝换票（403）。"""
    fake_db["admin_accounts"].docs.append(
        {"_id": "acct-2", "username": USERNAME, "tenant_id": TENANT, "status": "disabled"}
    )

    from starlette.testclient import TestClient
    from app.main import create_app

    app = create_app()
    client = TestClient(app)

    response = client.post("/api/auth/sso/exchange", json={"sso_token": _sign_sso_token()})
    assert response.status_code == 403


def test_exchange_request_model_rejects_empty_token() -> None:
    with pytest.raises(ValueError):
        SSOExchangeRequest(sso_token="")
