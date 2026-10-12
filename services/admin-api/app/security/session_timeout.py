"""会话超时判定（022 FR-11 / T017 / T018）。

纯逻辑层：不触库、不依赖 FastAPI，双服务（admin-api / chat-api）共用同一套
判定语义 —— 空闲 30min / 绝对 24h。

接入点各服务自行实现：

- admin-api：:mod:`app.middleware.timeout`（薄封装）→
  :func:`app.api.deps._load_authenticated_account`；
- chat-api：:func:`app.services.end_user_session.resolve_session_user`。

会话文档字段差异（admin 用 epoch 秒的 ``last_activity_at``，chat 用 datetime
的 ``last_seen_at``）通过 :func:`epoch_seconds` 统一归一化，判定逻辑只关心
「绝对窗口起点」与「最近活动时间」。
"""

from __future__ import annotations

import datetime as _dt
import logging
import time as _time
from dataclasses import dataclass
from typing import Any, Mapping

logger = logging.getLogger(__name__)

#: 空闲窗口（30min）与绝对窗口（24h）。
IDLE_TIMEOUT_SECONDS = 30 * 60
ABSOLUTE_TIMEOUT_SECONDS = 24 * 3600

#: 判定原因码（前端 / 审计可直接使用）。
REASON_IDLE = "idle_timeout"
REASON_ABSOLUTE = "absolute_timeout"
REASON_OK = "ok"

#: 判定失败时返回给前端的文案。
MESSAGE_IDLE = "会话已因长时间无操作而失效，请重新登录。"
MESSAGE_ABSOLUTE = "会话已达到最长有效期，请重新登录。"


@dataclass(frozen=True)
class SessionTimeoutVerdict:
    """会话超时判定结果。"""

    ok: bool
    reason: str
    message: str
    idle_seconds: int
    absolute_seconds: int
    idle_limit_seconds: int
    absolute_limit_seconds: int

    @property
    def expired(self) -> bool:
        return not self.ok


def epoch_seconds(value: Any) -> int:
    """把 ``datetime`` / epoch int / epoch float 统一成 Unix 秒。"""
    if value is None:
        return 0
    if isinstance(value, _dt.datetime):
        return int(value.timestamp())
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def evaluate_session_timeout(
    session_doc: Mapping[str, Any] | None,
    *,
    now: float | int | None = None,
    idle_limit_seconds: int = IDLE_TIMEOUT_SECONDS,
    absolute_limit_seconds: int = ABSOLUTE_TIMEOUT_SECONDS,
    last_activity_field: str = "last_activity_at",
) -> SessionTimeoutVerdict:
    """判定一个会话是否已超时（纯函数，不抛异常）。

    语义（fail-closed 但向后兼容）：

    - ``session_doc is None`` / 空字典：无法判定窗口 → 返回 ok（放行），
      由调用方继续做 ``status`` / 令牌 ``exp`` 等既有校验；
    - 绝对窗口起点缺失：仅判空闲；
    - 最近活动时间缺失：回退用绝对窗口起点作为基准；
    - 两个窗口都能算时才比较，任一超限即判定超时（空闲优先报告）。

    Args:
        last_activity_field: 最近活动时间字段名（admin-api 用
            ``last_activity_at``，chat-api 用 ``last_seen_at``）。
    """
    now_ts = int(float(now)) if now is not None else int(_time.time())

    if not session_doc:
        return SessionTimeoutVerdict(
            ok=True, reason=REASON_OK, message="",
            idle_seconds=0, absolute_seconds=0,
            idle_limit_seconds=idle_limit_seconds,
            absolute_limit_seconds=absolute_limit_seconds,
        )

    created_at = epoch_seconds(session_doc.get("created_at"))
    last_activity = epoch_seconds(session_doc.get(last_activity_field)) or created_at

    idle_seconds = max(0, now_ts - last_activity) if last_activity else 0
    absolute_seconds = max(0, now_ts - created_at) if created_at else 0

    if idle_seconds > idle_limit_seconds:
        return SessionTimeoutVerdict(
            ok=False, reason=REASON_IDLE, message=MESSAGE_IDLE,
            idle_seconds=idle_seconds, absolute_seconds=absolute_seconds,
            idle_limit_seconds=idle_limit_seconds,
            absolute_limit_seconds=absolute_limit_seconds,
        )
    if absolute_seconds > absolute_limit_seconds:
        return SessionTimeoutVerdict(
            ok=False, reason=REASON_ABSOLUTE, message=MESSAGE_ABSOLUTE,
            idle_seconds=idle_seconds, absolute_seconds=absolute_seconds,
            idle_limit_seconds=idle_limit_seconds,
            absolute_limit_seconds=absolute_limit_seconds,
        )
    return SessionTimeoutVerdict(
        ok=True, reason=REASON_OK, message="",
        idle_seconds=idle_seconds, absolute_seconds=absolute_seconds,
        idle_limit_seconds=idle_limit_seconds,
        absolute_limit_seconds=absolute_limit_seconds,
    )


def rejection_detail(verdict: SessionTimeoutVerdict) -> dict[str, Any]:
    """把超时判定转成统一的 401 响应体。"""
    return {
        "code": "SESSION_TIMEOUT",
        "reason": verdict.reason,
        "message": verdict.message,
        "idleSeconds": verdict.idle_seconds,
        "absoluteSeconds": verdict.absolute_seconds,
        "idleLimitSeconds": verdict.idle_limit_seconds,
        "absoluteLimitSeconds": verdict.absolute_limit_seconds,
    }


async def enforce_session_timeout(
    session_doc: Mapping[str, Any] | None,
    *,
    now: float | int | None = None,
    last_activity_field: str = "last_activity_at",
    idle_limit_seconds: int = IDLE_TIMEOUT_SECONDS,
    absolute_limit_seconds: int = ABSOLUTE_TIMEOUT_SECONDS,
) -> SessionTimeoutVerdict:
    """超时判定 + 审计日志。调用方在 ``verdict.ok is False`` 时应抛 401。"""
    verdict = evaluate_session_timeout(
        session_doc,
        now=now,
        last_activity_field=last_activity_field,
        idle_limit_seconds=idle_limit_seconds,
        absolute_limit_seconds=absolute_limit_seconds,
    )
    if not verdict.ok:
        logger.warning(
            "session timeout enforced: reason=%s idle=%ss absolute=%ss",
            verdict.reason, verdict.idle_seconds, verdict.absolute_seconds,
        )
    return verdict


__all__ = [
    "ABSOLUTE_TIMEOUT_SECONDS",
    "IDLE_TIMEOUT_SECONDS",
    "MESSAGE_ABSOLUTE",
    "MESSAGE_IDLE",
    "REASON_ABSOLUTE",
    "REASON_IDLE",
    "REASON_OK",
    "SessionTimeoutVerdict",
    "epoch_seconds",
    "evaluate_session_timeout",
    "enforce_session_timeout",
    "rejection_detail",
]
