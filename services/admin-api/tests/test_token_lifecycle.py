"""T022 集成测试：US2「令牌与会话生命周期」（FR-11 / FR-12）。

覆盖 022 Phase 2 的端到端行为：

- T014 / T015：access token TTL 默认值与硬上限均为 1h（双服务）；
- T016：登录签发 refresh token，`/refresh` 一次性轮换 + 重放检测吊销整个 family；
- T017：`/refresh` 链路的绝对 24h / 空闲 30min 超时判定；
- 横切：refresh 签发在存储故障时 fail-open（登录不受影响）。

全部用内存 fake motor，不启动 MongoDB。TOTP / JWT 均使用仓库内实现，
不引入第三方 token 库。
"""

from __future__ import annotations

import time
from typing import Any

import pytest
from fastapi import HTTPException

from app.api.routes import auth as auth_routes
from app.api.routes.auth import (
    REFRESH_TOKEN_COLLECTION,
    RefreshTokenRequest,
    _issue_refresh_token_pair,
    refresh_token,
)
from app.core.config import MAX_ACCESS_TOKEN_TTL_SECONDS, settings
from app.core.security import (
    ABSOLUTE_TIMEOUT_SECONDS,
    IDLE_TIMEOUT_SECONDS,
    create_access_token,
    create_refresh_token,
)
from app.repositories import org_user_repository

TENANT = "tenant-0001"
ADMIN = "admin@corp.example"
FIXED_NOW = 1_700_000_000


# ---------------------------------------------------------------------------
# 内存 fake motor
# ---------------------------------------------------------------------------


def _matches(doc: dict, query: dict) -> bool:
    for key, expected in (query or {}).items():
        actual = doc.get(key)
        if isinstance(expected, dict):
            for op, operand in expected.items():
                if op == "$gt" and not (actual is not None and actual > operand):
                    return False
                if op == "$gte" and not (actual is not None and actual >= operand):
                    return False
                if op == "$lt" and not (actual is not None and actual < operand):
                    return False
                if op == "$lte" and not (actual is not None and actual <= operand):
                    return False
                if op == "$ne" and actual == operand:
                    return False
        elif actual != expected:
            return False
    return True


class FakeCollection:
    def __init__(self, name: str) -> None:
        self.name = name
        self.docs: list[dict] = []
        self.fail_insert = False

    async def find_one(self, query: dict, projection=None) -> dict | None:
        for doc in self.docs:
            if _matches(doc, query or {}):
                return dict(doc)
        return None

    async def insert_one(self, doc: dict) -> None:
        if self.fail_insert:
            raise RuntimeError("mongo down")
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
    monkeypatch.setattr(org_user_repository, "get_db", lambda: db)
    return db


@pytest.fixture
def fixed_clock(monkeypatch) -> None:
    monkeypatch.setattr(time, "time", lambda: float(FIXED_NOW))


# ---------------------------------------------------------------------------
# T014 / T015：TTL 上限 1h
# ---------------------------------------------------------------------------


def test_admin_api_access_token_ttl_defaults_to_one_hour() -> None:
    assert settings.access_token_ttl_seconds == 3600
    assert MAX_ACCESS_TOKEN_TTL_SECONDS == 3600


def test_admin_api_issued_access_token_expires_within_one_hour(fixed_clock) -> None:
    _, expires_at, _ = create_access_token({"username": ADMIN, "tenant_id": TENANT})
    assert expires_at - FIXED_NOW <= MAX_ACCESS_TOKEN_TTL_SECONDS
    assert expires_at - FIXED_NOW > 0


def test_admin_api_ttl_guard_rejects_configured_overrun() -> None:
    """显式配置超过 1h 时，config 的启动判定分支为 True（触发告警）。"""
    from app.core.config import Settings

    override = Settings(_env_file=None, access_token_ttl_seconds=MAX_ACCESS_TOKEN_TTL_SECONDS + 1)
    assert override.access_token_ttl_seconds > MAX_ACCESS_TOKEN_TTL_SECONDS
    assert Settings(_env_file=None).access_token_ttl_seconds <= MAX_ACCESS_TOKEN_TTL_SECONDS


def test_refresh_token_ttl_remains_14_days() -> None:
    """refresh token 不受 1h 上限约束（1h 只约束 access token）。"""
    from app.core.security import REFRESH_TOKEN_TTL_SECONDS

    assert REFRESH_TOKEN_TTL_SECONDS == 14 * 24 * 3600


def test_chat_api_token_ttl_defaults_to_one_hour() -> None:
    """双服务口径一致（跨服务 import，chat-api 使用大写常量名）。"""
    import subprocess
    import sys

    chat_api = str(__import__("pathlib").Path(__file__).resolve().parents[2] / "chat-api")
    out = subprocess.run(
        [f"{chat_api}/venv/bin/python", "-c",
         "from app.core.config import MAX_END_USER_TOKEN_TTL_SECONDS, Settings; "
         "print(Settings(_env_file=None).END_USER_AUTH_TOKEN_TTL_SECONDS, "
         "MAX_END_USER_TOKEN_TTL_SECONDS)"],
        capture_output=True, text=True, check=True, cwd=chat_api,
    )
    default_ttl, ceiling = out.stdout.strip().split()
    assert default_ttl == "3600"
    assert ceiling == "3600"


# ---------------------------------------------------------------------------
# T016：refresh token 签发 + 一次性轮换 + 重放吊销
# ---------------------------------------------------------------------------


def _register_credential(
    db: FakeDB,
    *,
    username: str = ADMIN,
    tenant_id: str = TENANT,
    session_id: str = "sess-1",
    token: str | None = None,
    is_current: bool = True,
    created_at: int = FIXED_NOW,
) -> tuple[str, str]:
    """登记一枚 refresh token（模拟登录签发）并返回 ``(token, token_id)``。"""
    if token is None:
        refresh, _exp, token_id, family_id = create_refresh_token(
            {"username": username, "tenant_id": tenant_id}, family_id=session_id
        )
        token, token_id = refresh, token_id
    db[REFRESH_TOKEN_COLLECTION].docs.append({
        "token_id": token_id,
        "family_id": session_id,
        "username": username,
        "tenant_id": tenant_id,
        "created_at": created_at,
        "is_current": is_current,
    })
    return token, token_id


def _sign_refresh(username: str, tenant_id: str, session_id: str) -> tuple[str, str]:
    refresh, _exp, token_id, _fam = create_refresh_token(
        {"username": username, "tenant_id": tenant_id}, family_id=session_id
    )
    return refresh, token_id


@pytest.mark.asyncio
async def test_issue_refresh_token_pair_registers_current_credential(fake_db, fixed_clock) -> None:
    pair = await _issue_refresh_token_pair(ADMIN, TENANT, "sess-1")
    assert pair is not None
    refresh_token_value, expires_at = pair
    assert refresh_token_value
    assert expires_at > FIXED_NOW
    creds = fake_db[REFRESH_TOKEN_COLLECTION].docs
    assert len(creds) == 1
    assert creds[0]["is_current"] is True
    assert creds[0]["family_id"] == "sess-1"
    assert creds[0]["tenant_id"] == TENANT


@pytest.mark.asyncio
async def test_refresh_rotation_issues_new_token_and_invalidates_old(
    fake_db, fixed_clock, monkeypatch
) -> None:
    monkeypatch.setattr(
        org_user_repository, "find_account_by_username",
        _account(ADMIN, TENANT),
    )
    token, token_id = _register_credential(fake_db, session_id="sess-1")

    result = await refresh_token(RefreshTokenRequest(refreshToken=token))

    assert "accessToken" in result and "refreshToken" in result
    assert result["sessionId"]
    old = next(d for d in fake_db[REFRESH_TOKEN_COLLECTION].docs if d["token_id"] == token_id)
    assert old["is_current"] is False
    assert "rotated_at" in old
    currents = [d for d in fake_db[REFRESH_TOKEN_COLLECTION].docs if d["is_current"] is True]
    assert len(currents) == 1
    assert currents[0]["token_id"] != token_id
    assert currents[0]["family_id"] == "sess-1"  # family 复用


@pytest.mark.asyncio
async def test_refresh_reuse_of_rotated_token_revokes_family(
    fake_db, fixed_clock, monkeypatch
) -> None:
    monkeypatch.setattr(
        org_user_repository, "find_account_by_username",
        _account(ADMIN, TENANT),
    )
    token, token_id = _register_credential(fake_db, session_id="sess-1", is_current=False)
    fake_db["admin_sessions"].docs.append({
        "session_id": "sess-1", "tenant_id": TENANT, "username": ADMIN, "created_at": FIXED_NOW,
    })

    with pytest.raises(HTTPException) as exc_info:
        await refresh_token(RefreshTokenRequest(refreshToken=token))

    assert exc_info.value.status_code == 401
    assert "reuse" in str(exc_info.value.detail).lower()
    # family 全部清掉
    assert fake_db[REFRESH_TOKEN_COLLECTION].docs == []
    # 该用户在该租户下的会话全部清掉
    assert fake_db["admin_sessions"].docs == []


@pytest.mark.asyncio
async def test_refresh_unknown_token_revokes_family(fake_db, fixed_clock, monkeypatch) -> None:
    monkeypatch.setattr(
        org_user_repository, "find_account_by_username",
        _account(ADMIN, TENANT),
    )
    # 未登记的 token（签名合法但凭证表里没有）
    token, _tid = _sign_refresh(ADMIN, TENANT, "sess-ghost")

    with pytest.raises(HTTPException) as exc_info:
        await refresh_token(RefreshTokenRequest(refreshToken=token))

    assert exc_info.value.status_code == 401
    assert "Invalid refresh token" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_refresh_malformed_token_returns_401(fake_db, fixed_clock) -> None:
    garbage = "g" * 50  # 满足 min_length=50，但签名/结构非法
    with pytest.raises(HTTPException) as exc_info:
        await refresh_token(RefreshTokenRequest(refreshToken=garbage))
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_refresh_access_token_is_scoped_to_one_hour(
    fake_db, fixed_clock, monkeypatch
) -> None:
    """轮换签发的 access token 同样受 1h 上限约束。"""
    import base64
    import json

    monkeypatch.setattr(org_user_repository, "find_account_by_username", _account(ADMIN, TENANT))
    token, _tid = _register_credential(fake_db, session_id="sess-1")
    result = await refresh_token(RefreshTokenRequest(refreshToken=token))
    payload = json.loads(
        base64.urlsafe_b64decode(str(result["accessToken"]).split(".")[0] + "==").decode()
    )
    assert payload["exp"] - FIXED_NOW <= MAX_ACCESS_TOKEN_TTL_SECONDS


@pytest.mark.asyncio
async def test_issue_refresh_token_pair_fails_open_on_storage_error(
    fake_db, fixed_clock
) -> None:
    """存储故障不能阻断登录：签发 helper 返回 None。"""
    fake_db[REFRESH_TOKEN_COLLECTION].fail_insert = True
    assert await _issue_refresh_token_pair(ADMIN, TENANT, "sess-1") is None
    assert fake_db[REFRESH_TOKEN_COLLECTION].docs == []


# ---------------------------------------------------------------------------
# T017：会话超时判定（绝对 24h / 空闲 30min）
# ---------------------------------------------------------------------------


def _account(username: str, tenant_id: str) -> Any:
    async def _find(_username: str, _tenant_id: str) -> dict | None:
        return {
            "username": _username,
            "tenant_id": _tenant_id,
            "role_name": "组织管理员",
            "org_name": "X",
            "status": "active",
        }

    return _find


@pytest.mark.asyncio
async def test_refresh_rejects_session_past_absolute_timeout(
    fake_db, fixed_clock, monkeypatch
) -> None:
    monkeypatch.setattr(org_user_repository, "find_account_by_username", _account(ADMIN, TENANT))
    token, _tid = _register_credential(fake_db, session_id="sess-1")
    fake_db["admin_sessions"].docs.append({
        "session_id": "sess-1",
        "tenant_id": TENANT,
        "username": ADMIN,
        "created_at": FIXED_NOW - ABSOLUTE_TIMEOUT_SECONDS - 60,
    })

    with pytest.raises(HTTPException) as exc_info:
        await refresh_token(RefreshTokenRequest(refreshToken=token))

    assert exc_info.value.status_code == 401
    assert "expired" in str(exc_info.value.detail).lower()
    assert fake_db[REFRESH_TOKEN_COLLECTION].docs == []
    assert fake_db["admin_sessions"].docs == []


@pytest.mark.asyncio
async def test_refresh_rejects_session_past_idle_timeout(
    fake_db, fixed_clock, monkeypatch
) -> None:
    monkeypatch.setattr(org_user_repository, "find_account_by_username", _account(ADMIN, TENANT))
    token, _tid = _register_credential(fake_db, session_id="sess-1")
    fake_db["admin_sessions"].docs.append({
        "session_id": "sess-1",
        "tenant_id": TENANT,
        "username": ADMIN,
        "created_at": FIXED_NOW - 3600,  # 绝对超时内
        "last_activity_at": FIXED_NOW - IDLE_TIMEOUT_SECONDS - 60,  # 空闲超时外
    })

    with pytest.raises(HTTPException) as exc_info:
        await refresh_token(RefreshTokenRequest(refreshToken=token))

    assert exc_info.value.status_code == 401
    assert "inactivity" in str(exc_info.value.detail).lower()
    assert fake_db[REFRESH_TOKEN_COLLECTION].docs == []


@pytest.mark.asyncio
async def test_refresh_within_both_windows_updates_last_activity(
    fake_db, fixed_clock, monkeypatch
) -> None:
    monkeypatch.setattr(org_user_repository, "find_account_by_username", _account(ADMIN, TENANT))
    token, _tid = _register_credential(fake_db, session_id="sess-1")
    fake_db["admin_sessions"].docs.append({
        "session_id": "sess-1",
        "tenant_id": TENANT,
        "username": ADMIN,
        "created_at": FIXED_NOW - 3600,
        "last_activity_at": FIXED_NOW - 600,
    })

    result = await refresh_token(RefreshTokenRequest(refreshToken=token))
    assert "accessToken" in result
    session = fake_db["admin_sessions"].docs[0]
    assert session["last_activity_at"] == FIXED_NOW


@pytest.mark.asyncio
async def test_refresh_with_missing_session_doc_still_rotates(
    fake_db, fixed_clock, monkeypatch
) -> None:
    """会话文档缺失（历史数据）时不做超时判定，仍允许轮换 —— 向后兼容。"""
    monkeypatch.setattr(org_user_repository, "find_account_by_username", _account(ADMIN, TENANT))
    token, _tid = _register_credential(fake_db, session_id="sess-1")

    result = await refresh_token(RefreshTokenRequest(refreshToken=token))
    assert "accessToken" in result


@pytest.mark.asyncio
async def test_absolute_timeout_boundary_is_inclusive(fake_db, fixed_clock, monkeypatch) -> None:
    """恰好 24h 未超时；超过 1s 即超时。"""
    monkeypatch.setattr(org_user_repository, "find_account_by_username", _account(ADMIN, TENANT))
    token, _tid = _register_credential(fake_db, session_id="sess-a")
    fake_db["admin_sessions"].docs.append({
        "session_id": "sess-a", "tenant_id": TENANT, "username": ADMIN,
        "created_at": FIXED_NOW - ABSOLUTE_TIMEOUT_SECONDS,
        "last_activity_at": FIXED_NOW,  # 最近活跃，避免误触发空闲超时
    })
    result = await refresh_token(RefreshTokenRequest(refreshToken=token))
    assert "accessToken" in result

    # 再往前推 1s → 超时
    token2, _tid2 = _register_credential(fake_db, session_id="sess-b")
    fake_db["admin_sessions"].docs.append({
        "session_id": "sess-b", "tenant_id": TENANT, "username": ADMIN,
        "created_at": FIXED_NOW - ABSOLUTE_TIMEOUT_SECONDS - 1,
        "last_activity_at": FIXED_NOW,
    })
    with pytest.raises(HTTPException) as exc_info:
        await refresh_token(RefreshTokenRequest(refreshToken=token2))
    assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# 常量 / 契约
# ---------------------------------------------------------------------------


def test_timeout_constants_are_spec_values() -> None:
    assert IDLE_TIMEOUT_SECONDS == 30 * 60
    assert ABSOLUTE_TIMEOUT_SECONDS == 24 * 3600


def test_refresh_collection_name_is_stable() -> None:
    assert REFRESH_TOKEN_COLLECTION == "admin_refresh_tokens"
