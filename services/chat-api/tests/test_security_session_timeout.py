"""T018 集成测试：chat-api 会话空闲 30min / 绝对 24h 超时（FR-11）。

覆盖：

- :mod:`app.security.session_timeout` 纯逻辑在 chat-api 字段名
  （``last_seen_at``，datetime 存储）下的行为；
- :func:`app.services.end_user_session.resolve_session_user` 接入点：
  空闲 / 绝对超时返回 401 并把会话标记为 ``expired``，窗口内刷新
  ``last_seen_at``。

与 admin-api 的 :mod:`app.middleware.timeout` 共用同一份判定逻辑，
因此两边口径必然一致。
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest
from fastapi import HTTPException

from app.core.end_user_auth import build_session_token
from app.security import session_timeout as st
from app.security.session_timeout import (
    ABSOLUTE_TIMEOUT_SECONDS,
    IDLE_TIMEOUT_SECONDS,
    MESSAGE_ABSOLUTE,
    MESSAGE_IDLE,
    REASON_ABSOLUTE,
    REASON_IDLE,
    REASON_OK,
    evaluate_session_timeout,
    rejection_detail,
)
from bson import ObjectId

from app.services import end_user_session

SECRET = "test-end-user-secret"
TENANT = "tenant-0001"
USER_ID = "665f1c0c0b1e2a3f4a5b6c7d"
def _now_dt() -> dt.datetime:
    """测试内统一取一次"当前时间"，所有文档相对它构造。"""
    return dt.datetime.now(dt.timezone.utc)


NOW_DT = _now_dt()
NOW_TS = int(NOW_DT.timestamp())


# ---------------------------------------------------------------------------
# 纯判定：chat-api 字段名
# ---------------------------------------------------------------------------


def _session(**overrides: Any) -> dict:
    doc = {
        "token_id": "tok-1",
        "user_id": USER_ID,
        "tenant_id": TENANT,
        "status": "active",
        "created_at": NOW_DT - dt.timedelta(hours=1),
        "last_seen_at": NOW_DT - dt.timedelta(minutes=1),
    }
    doc.update(overrides)
    return doc


def test_chat_api_field_name_is_honored() -> None:
    verdict = evaluate_session_timeout(
        _session(), now=NOW_TS, last_activity_field="last_seen_at"
    )
    assert verdict.ok is True
    assert verdict.reason == REASON_OK
    assert verdict.idle_seconds == 60
    assert verdict.absolute_seconds == 3600


def test_idle_timeout_uses_last_seen_at() -> None:
    verdict = evaluate_session_timeout(
        _session(last_seen_at=NOW_DT - dt.timedelta(minutes=31)),
        now=NOW_TS,
        last_activity_field="last_seen_at",
    )
    assert verdict.ok is False
    assert verdict.reason == REASON_IDLE
    assert verdict.message == MESSAGE_IDLE


def test_absolute_timeout_uses_created_at() -> None:
    verdict = evaluate_session_timeout(
        _session(
            created_at=NOW_DT - dt.timedelta(hours=25),
            last_seen_at=NOW_DT - dt.timedelta(minutes=1),
        ),
        now=NOW_TS,
        last_activity_field="last_seen_at",
    )
    assert verdict.ok is False
    assert verdict.reason == REASON_ABSOLUTE
    assert verdict.message == MESSAGE_ABSOLUTE


def test_wrong_field_name_falls_back_to_created_at() -> None:
    """字段名配错时不会崩，回退到 created_at 作为基准（fail-safe）。"""
    verdict = evaluate_session_timeout(
        _session(
            created_at=NOW_DT - dt.timedelta(minutes=10),
            last_seen_at=NOW_DT - dt.timedelta(minutes=40),
        ),
        now=NOW_TS,
        last_activity_field="last_activity_at",  # 不存在
    )
    # 无 last_activity_at → 回退 created_at（10min 前），仍在空闲窗口内
    assert verdict.ok is True
    assert verdict.idle_seconds == 10 * 60


def test_defaults_match_admin_api() -> None:
    """双服务超时窗口必须一致（FR-11 统一口径）。"""
    assert IDLE_TIMEOUT_SECONDS == 30 * 60
    assert ABSOLUTE_TIMEOUT_SECONDS == 24 * 3600


def test_rejection_detail_shape() -> None:
    verdict = evaluate_session_timeout(
        _session(last_seen_at=NOW_DT - dt.timedelta(minutes=40)),
        now=NOW_TS,
        last_activity_field="last_seen_at",
    )
    detail = rejection_detail(verdict)
    assert detail["code"] == "SESSION_TIMEOUT"
    assert detail["reason"] == REASON_IDLE
    assert detail["idleSeconds"] == 40 * 60
    assert detail["absoluteLimitSeconds"] == 24 * 3600


def test_epoch_seconds_handles_chat_api_datetimes() -> None:
    assert st.epoch_seconds(NOW_DT) == NOW_TS
    naive = dt.datetime(2026, 10, 12, 10, 0, 0)
    assert isinstance(st.epoch_seconds(naive), int)
    assert st.epoch_seconds(None) == 0


# ---------------------------------------------------------------------------
# 接入点：resolve_session_user
# ---------------------------------------------------------------------------


class FakeCollection:
    def __init__(self, docs: list[dict]) -> None:
        self.docs = docs

    async def find_one(self, query: dict, projection=None) -> dict | None:
        for doc in self.docs:
            if all(doc.get(k) == v for k, v in (query or {}).items()):
                return dict(doc)
        return None

    async def update_one(self, query: dict, update: dict, upsert: bool = False) -> None:
        for doc in self.docs:
            if all(doc.get(k) == v for k, v in (query or {}).items()):
                doc.update(update.get("$set", {}))
                return


class FakeDB:
    def __init__(self) -> None:
        self.collections: dict[str, list[dict]] = {}

    def __getitem__(self, name: str) -> Any:
        return FakeCollection(self.collections.setdefault(name, []))


@pytest.fixture
def fake_db(monkeypatch) -> Any:
    db = FakeDB()
    monkeypatch.setattr(end_user_session, "get_db", lambda: db)

    # 让 resolve_session_user 使用的密钥与 build_session_token 一致
    settings = type(
        "Settings",
        (),
        {"END_USER_AUTH_SECRET": SECRET, "END_USER_AUTH_TOKEN_TTL_SECONDS": 3600},
    )()
    monkeypatch.setattr(end_user_session, "get_settings", lambda: settings)
    return db


def _token(token_id: str = "tok-1") -> str:
    return build_session_token(SECRET, token_id)


def _session_doc(**overrides: Any) -> dict:
    doc = {
        "_id": 1,
        "token_id": "tok-1",
        "user_id": USER_ID,
        "tenant_id": TENANT,
        "status": "active",
        "created_at": NOW_DT - dt.timedelta(hours=1),
        "last_seen_at": NOW_DT - dt.timedelta(minutes=1),
    }
    doc.update(overrides)
    return doc


def _user_doc() -> dict:
    return {
        "_id": ObjectId(USER_ID),
        "tenant_id": TENANT,
        "status": "active",
        "primary_org_id": "",
    }


@pytest.mark.asyncio
async def test_resolve_session_user_rejects_idle_session(fake_db) -> None:
    fake_db["end_user_sessions"].docs.append(
        _session_doc(last_seen_at=NOW_DT - dt.timedelta(minutes=31))
    )
    fake_db["end_users"].docs.append(_user_doc())

    with pytest.raises(HTTPException) as exc_info:
        await end_user_session.resolve_session_user(f"Bearer {_token()}")

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail["code"] == "SESSION_TIMEOUT"
    assert exc_info.value.detail["reason"] == REASON_IDLE
    # 会话被标记为 expired
    assert fake_db["end_user_sessions"].docs[0]["status"] == "expired"


@pytest.mark.asyncio
async def test_resolve_session_user_rejects_absolute_timeout(fake_db) -> None:
    fake_db["end_user_sessions"].docs.append(
        _session_doc(
            created_at=NOW_DT - dt.timedelta(hours=25),
            last_seen_at=NOW_DT - dt.timedelta(minutes=1),
        )
    )
    fake_db["end_users"].docs.append(_user_doc())

    with pytest.raises(HTTPException) as exc_info:
        await end_user_session.resolve_session_user(f"Bearer {_token()}")

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail["reason"] == REASON_ABSOLUTE
    assert fake_db["end_user_sessions"].docs[0]["status"] == "expired"


@pytest.mark.asyncio
async def test_resolve_session_user_refreshes_last_seen_within_windows(fake_db) -> None:
    original_seen = NOW_DT - dt.timedelta(minutes=5)
    session_doc = _session_doc(last_seen_at=original_seen)
    fake_db["end_user_sessions"].docs.append(session_doc)
    fake_db["end_users"].docs.append(_user_doc())

    result = await end_user_session.resolve_session_user(f"Bearer {_token()}")
    assert result["session"]["token_id"] == "tok-1"
    assert result["tenant_id"] == TENANT
    assert result["org_id"] == ""
    # last_seen_at 被刷新到调用时刻（全量套件下允许较大漂移）
    stored = fake_db["end_user_sessions"].docs[0]
    assert stored["last_seen_at"] > original_seen


@pytest.mark.asyncio
async def test_resolve_session_user_still_rejects_expired_token(fake_db) -> None:
    """既有的 expires_at 判定不受新逻辑影响。"""
    fake_db["end_user_sessions"].docs.append(
        _session_doc(expires_at=NOW_DT - dt.timedelta(minutes=1))
    )
    fake_db["end_users"].docs.append(_user_doc())

    with pytest.raises(HTTPException) as exc_info:
        await end_user_session.resolve_session_user(f"Bearer {_token()}")
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "session_expired"


@pytest.mark.asyncio
async def test_resolve_session_user_invalid_token_still_rejected(fake_db) -> None:
    with pytest.raises(HTTPException) as exc_info:
        await end_user_session.resolve_session_user("Bearer garbage")
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "invalid_token"


@pytest.mark.asyncio
async def test_resolve_session_user_missing_session_rejected(fake_db) -> None:
    with pytest.raises(HTTPException) as exc_info:
        await end_user_session.resolve_session_user(f"Bearer {_token()}")
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "session_not_found"


def test_chat_api_constants_are_exported() -> None:
    assert end_user_session.SESSION_IDLE_TIMEOUT_SECONDS == 30 * 60
    assert end_user_session.SESSION_ABSOLUTE_TIMEOUT_SECONDS == 24 * 3600
    assert end_user_session.LAST_SEEN_FIELD == "last_seen_at"
