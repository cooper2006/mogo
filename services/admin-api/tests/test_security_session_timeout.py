"""T017 单测：会话超时判定（FR-11 空闲 30min / 绝对 24h）。

覆盖 :mod:`app.middleware.timeout` 的纯函数判定逻辑，以及接入
:func:`app.api.deps._load_authenticated_account` 后的 401 语义。
不启动 MongoDB；会话文档全部为内存构造。
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest
from fastapi import HTTPException

from app.api import deps as deps_module
from app.core.security import decode_access_token, create_access_token
from app.middleware.timeout import (
    MESSAGE_ABSOLUTE,
    MESSAGE_IDLE,
    REASON_ABSOLUTE,
    REASON_IDLE,
    REASON_OK,
    SessionTimeoutVerdict,
    epoch_seconds,
    evaluate_session_timeout,
    enforce_session_timeout,
    rejection_detail,
    touch_session_activity,
)
from app.repositories import admin_session_repository

NOW = 1_700_000_000
TENANT = "tenant-0001"
ADMIN = "admin@corp.example"


def _session(**overrides: Any) -> dict:
    doc = {
        "session_id": "sess-1",
        "username": ADMIN,
        "tenant_id": TENANT,
        "status": "active",
        "created_at": NOW - 3600,
        "last_activity_at": NOW - 60,
    }
    doc.update(overrides)
    return doc


# ---------------------------------------------------------------------------
# epoch_seconds：两种时间表示都必须吃得下
# ---------------------------------------------------------------------------


def test_epoch_seconds_handles_int_float_and_datetime() -> None:
    assert epoch_seconds(NOW) == NOW
    assert epoch_seconds(float(NOW)) == NOW
    assert epoch_seconds(dt.datetime.fromtimestamp(NOW, tz=dt.timezone.utc)) == NOW
    assert epoch_seconds(0) == 0
    assert epoch_seconds("") == 0


def test_epoch_seconds_naive_datetime_is_converted() -> None:
    """历史写入可能是 naive datetime；.timestamp() 按本机时区解释，结果可用。"""
    naive = dt.datetime(2026, 10, 12, 0, 0, 0)
    assert isinstance(epoch_seconds(naive), int)


def test_epoch_seconds_none_and_garbage_are_zero() -> None:
    assert epoch_seconds(None) is 0
    assert epoch_seconds("not-a-number") == 0
    assert epoch_seconds(object()) == 0


# ---------------------------------------------------------------------------
# 纯判定：空闲 / 绝对 / 通过
# ---------------------------------------------------------------------------


def test_session_within_both_windows_passes() -> None:
    verdict = evaluate_session_timeout(_session(), now=NOW)
    assert verdict.ok is True
    assert verdict.reason == REASON_OK
    assert verdict.message == ""
    assert verdict.idle_seconds == 60
    assert verdict.absolute_seconds == 3600


def test_session_idle_over_30min_is_rejected() -> None:
    verdict = evaluate_session_timeout(
        _session(last_activity_at=NOW - 30 * 60 - 1), now=NOW
    )
    assert verdict.ok is False
    assert verdict.expired is True
    assert verdict.reason == REASON_IDLE
    assert verdict.message == MESSAGE_IDLE


def test_session_idle_exactly_30min_is_still_valid() -> None:
    """边界：恰好 30min 未超时，第 31 秒才超时。"""
    assert evaluate_session_timeout(
        _session(last_activity_at=NOW - 30 * 60), now=NOW
    ).ok is True
    assert evaluate_session_timeout(
        _session(last_activity_at=NOW - 30 * 60 - 1), now=NOW
    ).ok is False


def test_session_absolute_over_24h_is_rejected() -> None:
    verdict = evaluate_session_timeout(
        _session(created_at=NOW - 24 * 3600 - 60, last_activity_at=NOW - 60),
        now=NOW,
    )
    assert verdict.ok is False
    assert verdict.reason == REASON_ABSOLUTE
    assert verdict.message == MESSAGE_ABSOLUTE


def test_session_absolute_exactly_24h_is_still_valid() -> None:
    assert evaluate_session_timeout(
        _session(created_at=NOW - 24 * 3600, last_activity_at=NOW), now=NOW
    ).ok is True


def test_idle_reason_wins_over_absolute_when_both_exceeded() -> None:
    """两个窗口同时超限时优先报告空闲（对前端更可操作）。"""
    verdict = evaluate_session_timeout(
        _session(created_at=NOW - 25 * 3600, last_activity_at=NOW - 2 * 3600), now=NOW
    )
    assert verdict.reason == REASON_IDLE
    assert verdict.absolute_seconds == 25 * 3600


def test_missing_last_activity_falls_back_to_created_at() -> None:
    verdict = evaluate_session_timeout(
        {"session_id": "s", "created_at": NOW - 35 * 60},
        now=NOW,
    )
    assert verdict.ok is False
    assert verdict.reason == REASON_IDLE
    assert verdict.idle_seconds == 35 * 60


def test_missing_last_activity_within_idle_window_passes() -> None:
    """20min 无活动仍在 30min 窗口内，判定通过。"""
    verdict = evaluate_session_timeout(
        {"session_id": "s", "created_at": NOW - 20 * 60},
        now=NOW,
    )
    assert verdict.ok is True
    assert verdict.idle_seconds == 20 * 60


def test_missing_created_at_only_checks_idle() -> None:
    verdict = evaluate_session_timeout(
        {"session_id": "s", "last_activity_at": NOW - 60}, now=NOW
    )
    assert verdict.ok is True
    assert verdict.absolute_seconds == 0
    assert verdict.idle_seconds == 60


def test_missing_session_doc_is_permissive() -> None:
    """历史数据没有会话文档时不阻断（由令牌 exp 继续兜底）。"""
    verdict = evaluate_session_timeout(None, now=NOW)
    assert verdict.ok is True
    assert verdict.reason == REASON_OK
    assert verdict.idle_seconds == 0 and verdict.absolute_seconds == 0


def test_empty_session_doc_is_permissive() -> None:
    assert evaluate_session_timeout({}, now=NOW).ok is True


def test_custom_limits_are_honored() -> None:
    verdict = evaluate_session_timeout(
        _session(last_activity_at=NOW - 120), now=NOW, idle_limit_seconds=60
    )
    assert verdict.ok is False
    assert verdict.idle_limit_seconds == 60


def test_now_defaults_to_real_clock() -> None:
    """不传 now 时使用系统时钟，结果仍是可判定的。"""
    verdict = evaluate_session_timeout(_session(last_activity_at=1), now=None)
    assert isinstance(verdict, SessionTimeoutVerdict)
    assert verdict.ok is False  # last_activity_at=1 早就超时


def test_verdict_is_frozen() -> None:
    verdict = evaluate_session_timeout(_session(), now=NOW)
    with pytest.raises(Exception):
        verdict.ok = False  # type: ignore[misc]


def test_default_limits_match_spec() -> None:
    verdict = evaluate_session_timeout(_session(), now=NOW)
    assert verdict.idle_limit_seconds == 30 * 60
    assert verdict.absolute_limit_seconds == 24 * 3600


# ---------------------------------------------------------------------------
# rejection_detail：统一 401 响应体
# ---------------------------------------------------------------------------


def test_rejection_detail_carries_all_fields() -> None:
    verdict = evaluate_session_timeout(
        _session(last_activity_at=NOW - 3600), now=NOW
    )
    detail = rejection_detail(verdict)
    assert detail["code"] == "SESSION_TIMEOUT"
    assert detail["reason"] == REASON_IDLE
    assert detail["message"] == MESSAGE_IDLE
    assert detail["idleLimitSeconds"] == 30 * 60
    assert detail["absoluteLimitSeconds"] == 24 * 3600
    assert detail["idleSeconds"] == 3600
    assert isinstance(detail["idleSeconds"], int)
    assert isinstance(detail["absoluteSeconds"], int)


def test_rejection_detail_ok_verdict_has_no_message() -> None:
    verdict = evaluate_session_timeout(_session(), now=NOW)
    detail = rejection_detail(verdict)
    assert detail["reason"] == REASON_OK
    assert detail["message"] == ""


# ---------------------------------------------------------------------------
# enforce / touch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enforce_session_timeout_returns_verdict() -> None:
    verdict = await enforce_session_timeout(_session(last_activity_at=NOW - 3600), now=NOW)
    assert verdict.ok is False
    assert verdict.reason == REASON_IDLE


@pytest.mark.asyncio
async def test_enforce_session_timeout_passes_fresh_session() -> None:
    verdict = await enforce_session_timeout(_session(), now=NOW)
    assert verdict.ok is True


@pytest.mark.asyncio
async def test_touch_session_activity_writes_last_activity(fake_db) -> None:
    await touch_session_activity("sess-1", now=NOW)
    assert fake_db.store["admin_sessions"] == []  # 无匹配文档时静默成功


@pytest.mark.asyncio
async def test_touch_session_activity_updates_existing_row(fake_db) -> None:
    fake_db.store["admin_sessions"].append(
        {"session_id": "sess-1", "last_activity_at": NOW - 3600}
    )
    await touch_session_activity("sess-1", now=NOW)
    assert fake_db.store["admin_sessions"][0]["last_activity_at"] == NOW


@pytest.mark.asyncio
async def test_touch_session_activity_empty_id_is_noop() -> None:
    # 不应触库
    await touch_session_activity("", now=NOW)
    await touch_session_activity(None, now=NOW)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 接入点：deps._load_authenticated_account
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


@pytest.fixture
def fake_db(monkeypatch) -> Any:
    """同时覆盖 app.core.db 与各 repository 的 get_db。"""
    store: dict[str, list[dict]] = {
        "admin_sessions": [],
        "admin_accounts": [],
    }

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

    class _DB:
        def __getitem__(self, name: str) -> Any:
            return FakeCollection(store.setdefault(name, []))

    instance = _DB()
    monkeypatch.setattr(admin_session_repository, "get_db", lambda: instance)
    import app.core.db as core_db
    monkeypatch.setattr(core_db, "get_db", lambda: instance)
    import app.repositories.org_user_repository as org_repo
    monkeypatch.setattr(org_repo, "get_db", lambda: instance)
    instance.store = store  # type: ignore[attr-defined]
    return instance


class _FrozenClock:
    """冻结的 time 模块替身。"""

    def time(self) -> float:  # noqa: D102
        return float(NOW)


@pytest.fixture
def fixed_clock(monkeypatch) -> None:
    """冻结共用逻辑层的时钟，使 epoch 常量 NOW 与"当前"一致。"""
    import app.security.session_timeout as st_module

    monkeypatch.setattr(st_module, "_time", _FrozenClock())
    import app.middleware.timeout as mw_module

    monkeypatch.setattr(mw_module, "_now_epoch", lambda: NOW)


def _login_token() -> str:
    token, _exp, _sid = create_access_token(
        {"username": ADMIN, "tenant_id": TENANT, "role_name": "组织管理员"}
    )
    return token


def _subject(token: str) -> dict:
    payload = decode_access_token(token)
    return payload["sub"]


@pytest.mark.asyncio
async def test_deps_rejects_session_past_idle_timeout(fake_db, fixed_clock) -> None:
    token = _login_token()
    sub = _subject(token)
    fake_db.store["admin_sessions"].append({  # type: ignore[attr-defined]
        "session_id": sub["session_id"],
        "username": ADMIN,
        "tenant_id": TENANT,
        "status": "active",
        "created_at": NOW - 3600,
        "last_activity_at": NOW - 3600,
    })
    fake_db.store["admin_accounts"].append({  # type: ignore[attr-defined]
        "username": ADMIN, "tenant_id": TENANT, "status": "active", "role_name": "组织管理员",
    })

    with pytest.raises(HTTPException) as exc_info:
        await deps_module._load_authenticated_account(f"Bearer {token}")

    assert exc_info.value.status_code == 401
    detail = exc_info.value.detail
    assert detail["code"] == "SESSION_TIMEOUT"
    assert detail["reason"] == REASON_IDLE


@pytest.mark.asyncio
async def test_deps_accepts_fresh_session_and_touches_activity(fake_db, fixed_clock) -> None:
    token = _login_token()
    sub = _subject(token)
    fake_db.store["admin_sessions"].append({  # type: ignore[attr-defined]
        "session_id": sub["session_id"],
        "username": ADMIN,
        "tenant_id": TENANT,
        "status": "active",
        "created_at": NOW - 3600,
        "last_activity_at": NOW - 3600,
    })
    fake_db.store["admin_accounts"].append({  # type: ignore[attr-defined]
        "username": ADMIN, "tenant_id": TENANT, "status": "active", "role_name": "组织管理员",
    })

    # 最近活跃且在绝对窗口内
    fake_db.store["admin_sessions"][0]["last_activity_at"] = NOW - 60  # type: ignore[attr-defined]

    user = await deps_module._load_authenticated_account(f"Bearer {token}")
    assert user["username"] == ADMIN
    assert user["tenant_id"] == TENANT


@pytest.mark.asyncio
async def test_deps_rejects_session_past_absolute_timeout(fake_db, fixed_clock) -> None:
    token = _login_token()
    sub = _subject(token)
    fake_db.store["admin_sessions"].append({  # type: ignore[attr-defined]
        "session_id": sub["session_id"],
        "username": ADMIN,
        "tenant_id": TENANT,
        "status": "active",
        "created_at": NOW - 25 * 3600,
        "last_activity_at": NOW - 60,
    })
    fake_db.store["admin_accounts"].append({  # type: ignore[attr-defined]
        "username": ADMIN, "tenant_id": TENANT, "status": "active", "role_name": "组织管理员",
    })

    with pytest.raises(HTTPException) as exc_info:
        await deps_module._load_authenticated_account(f"Bearer {token}")

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail["reason"] == REASON_ABSOLUTE
