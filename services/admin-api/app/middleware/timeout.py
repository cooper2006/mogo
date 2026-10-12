"""会话超时判定接入层（022 FR-11 / T017）。

纯逻辑在 :mod:`app.security.session_timeout`（双服务共用）。本模块只做两件事：

1. 以 admin-api 的字段名与默认参数**薄封装**共用逻辑，保持既有调用方与
   测试的公共 API 不变；
2. 提供 :func:`touch_session_activity` —— 判定通过时刷新
   ``last_activity_at``，作为下一次空闲判定的基准。

真正的接入点是 :func:`app.api.deps._load_authenticated_account`（唯一加载
会话的地方），因此判定覆盖全部需认证路由。
"""

from __future__ import annotations

import logging
from typing import Any, Mapping

from app.security import session_timeout as _st

logger = logging.getLogger(__name__)

# 保持既有公共 API 名称不变（测试与调用方按这些名字导入）。
IDLE_TIMEOUT_SECONDS = _st.IDLE_TIMEOUT_SECONDS
ABSOLUTE_TIMEOUT_SECONDS = _st.ABSOLUTE_TIMEOUT_SECONDS
REASON_IDLE = _st.REASON_IDLE
REASON_ABSOLUTE = _st.REASON_ABSOLUTE
REASON_OK = _st.REASON_OK
MESSAGE_IDLE = _st.MESSAGE_IDLE
MESSAGE_ABSOLUTE = _st.MESSAGE_ABSOLUTE
SessionTimeoutVerdict = _st.SessionTimeoutVerdict
epoch_seconds = _st.epoch_seconds
rejection_detail = _st.rejection_detail

#: admin-api 会话文档使用的时间字段。
LAST_ACTIVITY_FIELD = "last_activity_at"
SESSION_COLLECTION = "admin_sessions"


def evaluate_session_timeout(
    session_doc: Mapping[str, Any] | None,
    *,
    now: float | int | None = None,
    idle_limit_seconds: int = IDLE_TIMEOUT_SECONDS,
    absolute_limit_seconds: int = ABSOLUTE_TIMEOUT_SECONDS,
) -> SessionTimeoutVerdict:
    """admin-api 口径的会话超时判定（字段名 ``last_activity_at``）。"""
    return _st.evaluate_session_timeout(
        session_doc,
        now=now,
        idle_limit_seconds=idle_limit_seconds,
        absolute_limit_seconds=absolute_limit_seconds,
        last_activity_field=LAST_ACTIVITY_FIELD,
    )


async def enforce_session_timeout(
    session_doc: Mapping[str, Any] | None,
    *,
    now: float | int | None = None,
) -> SessionTimeoutVerdict:
    """超时判定 + 审计日志（fail-closed：超时即返回不可用判定）。"""
    return await _st.enforce_session_timeout(
        session_doc, now=now, last_activity_field=LAST_ACTIVITY_FIELD
    )


async def touch_session_activity(session_id: str, *, now: float | int | None = None) -> None:
    """刷新 ``last_activity_at``（空闲窗口基准）。

    写入失败不影响主流程 —— 空闲判定最多延后一个窗口，不能因为存储抖动
    把用户登出。
    """
    if not session_id:
        return
    try:
        from app.core.db import get_db

        now_ts = int(float(now)) if now is not None else _now_epoch()
        db = get_db()
        await db[SESSION_COLLECTION].update_one(
            {"session_id": session_id},
            {"$set": {"last_activity_at": now_ts, "updated_at": now_ts}},
        )
    except Exception as exc:  # noqa: BLE001 - 活动记录失败降级
        logger.warning("failed to touch session activity for %s: %s", session_id, exc)


def _now_epoch() -> int:
    import time

    return int(time.time())


__all__ = [
    "ABSOLUTE_TIMEOUT_SECONDS",
    "IDLE_TIMEOUT_SECONDS",
    "LAST_ACTIVITY_FIELD",
    "MESSAGE_ABSOLUTE",
    "MESSAGE_IDLE",
    "REASON_ABSOLUTE",
    "REASON_IDLE",
    "REASON_OK",
    "SESSION_COLLECTION",
    "SessionTimeoutVerdict",
    "epoch_seconds",
    "evaluate_session_timeout",
    "enforce_session_timeout",
    "rejection_detail",
    "touch_session_activity",
]
