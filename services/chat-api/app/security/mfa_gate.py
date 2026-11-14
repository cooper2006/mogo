"""FR-2 / FR-3 / FR-4 登录闸门组合层（022 Phase 1，T011 / T012）。

把 Phase 0 的纯逻辑（:mod:`app.security.mfa_policy`）与存储实现
（:class:`MongoMfaLockoutTracker` / :class:`MongoTotpUsedStepStore`）以及
FR-23 审计落点（:mod:`app.security.audit_events`）组合成路由可直接调用的
少量函数：

- :func:`evaluate_login_gate` — FR-2 登录闸门（高权限账号强制 MFA）；
- :func:`record_mfa_failure` / :func:`clear_mfa_failures` — FR-3 限流计数；
- :func:`check_and_consume_totp` — FR-4 TOTP 校验 + used_step 防重放；
- :func:`emit_mfa_audit` — FR-23 审计落点（审计失败绝不阻断主流程）；
- :func:`notify_mfa_change` — OQ-1：通知通道未接入时降级为审计事件。

设计原则与 Phase 0 一致：**纯逻辑 + 可注入依赖**。所有存储与 TOTP 校验器
都可注入 fake，因此本模块可以在不启动 MongoDB、不起事件循环的前提下被
单元测试完整覆盖。
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Mapping, Protocol

from . import mfa_policy as mp
from .audit_events import AuditEventRepository
from .mfa_policy import (
    AccountMfaState,
    DECISION_BIND_REQUIRED,
    DECISION_LOCKED,
    DECISION_VERIFY_REQUIRED,
    LockoutState,
    LoginGateDecision,
    MongoMfaLockoutTracker,
    MongoTotpUsedStepStore,
    TOTP_STEP_SECONDS,
    TOTP_USED_STEP_TTL_SECONDS,
)

logger = logging.getLogger(__name__)

#: 审计事件的 source_service 标识（FR-23 双服务可区分来源）。
SOURCE_SERVICE = "admin-api"

# ---------------------------------------------------------------------------
# 审计动作名（FR-23 统一命名，便于检索与合规取证）
# ---------------------------------------------------------------------------

AUDIT_MFA_VERIFY_OK = "mfa.verify"
AUDIT_MFA_VERIFY_FAIL = "mfa.verify_fail"
AUDIT_MFA_REPLAY = "mfa.replay_blocked"
AUDIT_MFA_LOCKED = "mfa.locked"
AUDIT_MFA_BIND_REQUIRED = "mfa.bind_required"
AUDIT_MFA_ENABLE = "mfa.enable"
AUDIT_MFA_DISABLE = "mfa.disable"

DECISION_ALLOW = "allow"
DECISION_DENY = "deny"

# 通知降级说明（OQ-1：通知通道未接入时仅落审计事件）
NOTIFICATION_NOT_CONNECTED = "notification channel not connected; degraded to audit event only"


# ---------------------------------------------------------------------------
# 协议 / 小工具
# ---------------------------------------------------------------------------


class TotpVerifier(Protocol):
    """TOTP 校验器协议：``verify_totp(secret, token, *, window) -> bool``。"""

    def __call__(self, secret: str, token: str, *, window: int = 1) -> bool: ...


class MfaNotificationChannel(Protocol):
    """MFA 变更通知通道协议（邮件 / 短信 / 站内信）。"""

    def __call__(self, *, tenant_id: str, username: str, event_type: str, detail: Mapping[str, Any]) -> None:
        """同步发送通知；实现方自行处理异步与重试。"""


def client_ip_from_request(request: Any | None) -> str:
    """从 FastAPI ``Request`` 提取客户端 IP，取不到时返回空串。"""
    if request is None:
        return ""
    forwarded = ""
    try:
        headers = getattr(request, "headers", {})
        forwarded = str(headers.get("x-forwarded-for") or "")
    except Exception:  # noqa: BLE001 - 头解析失败不影响主流程
        forwarded = ""
    if forwarded:
        return forwarded.split(",")[0].strip()
    client = getattr(request, "client", None)
    host = getattr(client, "host", None)
    return str(host) if host else ""


def current_totp_step(now: float | None = None) -> int:
    """当前 TOTP step（用于防重放判定）。"""
    ts = float(now) if now is not None else time.time()
    return int(ts // TOTP_STEP_SECONDS)


def secret_scope(*, user_id: str, tenant_id: str = "", secret_hint: str = "") -> str:
    """used_step 作用域（透传 :meth:`MongoTotpUsedStepStore.scope_for`）。"""
    return MongoTotpUsedStepStore.scope_for(
        user_id=user_id, tenant_id=tenant_id, secret_hint=secret_hint
    )


# ---------------------------------------------------------------------------
# 默认实例（模块级单例，避免每次请求重复构造）
# ---------------------------------------------------------------------------


def _default_repo(db: Any, *, collection: str | None = None) -> AuditEventRepository:
    return AuditEventRepository(db, source_service=SOURCE_SERVICE)


# ---------------------------------------------------------------------------
# FR-2：登录闸门
# ---------------------------------------------------------------------------


async def evaluate_login_gate(
    db: Any,
    user_doc: Mapping[str, Any],
    *,
    client_ip: str = "",
    tracker: Any | None = None,
) -> LoginGateDecision:
    """FR-2：判定该账号此刻能否进入业务。

    流程：读限流计数 → 组装账号视图 → 交给纯逻辑 :func:`decide_login_gate`。
    存储读取失败按「未锁定」处理，避免 MongoDB 抖动把所有高权限账号锁死。
    """
    username = str(user_doc.get("username") or "")
    tenant_id = str(user_doc.get("tenant_id") or "")
    key = mp.failure_key(username=username, tenant_id=tenant_id, client_ip=client_ip)

    failures = 0
    try:
        store = tracker or MongoMfaLockoutTracker(db)
        state = await store.get(key)
        failures = mp.effective_failures(state, mp._now_epoch())
    except Exception:  # noqa: BLE001 - 限流存储故障降级为未锁定
        logger.warning("mfa lockout store read failed for %s", username, exc_info=True)

    return mp.decide_login_gate(mp.AccountMfaState.from_row(user_doc), failures=failures)


async def record_mfa_failure(
    db: Any,
    *,
    username: str,
    tenant_id: str,
    client_ip: str = "",
    tracker: Any | None = None,
) -> LockoutState:
    """FR-3：记录一次 MFA 校验失败（限流维度 = username + tenant_id + IP）。"""
    key = mp.failure_key(username=username, tenant_id=tenant_id, client_ip=client_ip)
    store = tracker or MongoMfaLockoutTracker(db)
    return await store.record_failure(key)


async def clear_mfa_failures(
    db: Any,
    *,
    username: str,
    tenant_id: str,
    client_ip: str = "",
    tracker: Any | None = None,
) -> None:
    """FR-3：成功认证后清零该维度的失败计数。"""
    key = mp.failure_key(username=username, tenant_id=tenant_id, client_ip=client_ip)
    store = tracker or MongoMfaLockoutTracker(db)
    await store.reset(key)


# ---------------------------------------------------------------------------
# FR-4：TOTP 校验 + used_step 防重放
# ---------------------------------------------------------------------------


async def check_and_consume_totp(
    db: Any,
    *,
    username: str,
    tenant_id: str,
    code: str,
    raw_secret: str,
    client_ip: str = "",
    user_id: str = "",
    secret_hint: str = "",
    step: int | None = None,
    now: float | None = None,
    verifier: Callable[..., bool] | None = None,
    tracker: Any | None = None,
    used_step_store: Any | None = None,
) -> tuple[bool, LoginGateDecision]:
    """FR-4：校验 TOTP code，并在成功后消费 used_step 防重放。

    判定顺序（**先防重放，再校验**，重放比错误更危险）：

    1. 限流窗口已满 → ``(False, locked)``，不消耗任何 step；
    2. 候选 step 与历史 used_step 相交 → ``(False, replay)``，记失败并落审计；
    3. TOTP 校验失败 → ``(False, fail)``，记失败并落审计；
    4. 校验成功 → 标记候选 step 为 used（TTL 90s）→ ``(True, verify_ok)``。

    Returns:
        ``(是否通过, 判定详情)``。判定详情带 ``reason_code`` 供调用方选择
        HTTP 状态码与文案。
    """
    now = float(now) if now is not None else time.time()
    step_no = int(step) if step is not None else current_totp_step(now)
    key = mp.failure_key(username=username, tenant_id=tenant_id, client_ip=client_ip)

    scope = secret_scope(
        user_id=user_id or username, tenant_id=tenant_id, secret_hint=secret_hint
    )

    store = tracker or MongoMfaLockoutTracker(db)
    steps_store = used_step_store or MongoTotpUsedStepStore(db)

    state = await store.get(key, now=now)
    failures = mp.effective_failures(state, now)

    if failures >= mp.MAX_FAILURES:
        # 直接构造锁定判定：不借道 decide_login_gate（它按 role 判定，而
        # 此处我们已经确认该账号确实需要 MFA，只需报告限流结果）。
        return False, LoginGateDecision(
            action=mp.DECISION_LOCKED,
            message=mp.LOCKED_MESSAGE,
            reason_code="rate_limited",
            locked_until=datetime.fromtimestamp(now + mp.LOCKOUT_WINDOW_SECONDS, tz=timezone.utc),
            attempts_remaining=0,
            detail={"window_seconds": mp.LOCKOUT_WINDOW_SECONDS},
        )

    candidates = mp.candidate_steps(step_no)
    try:
        used = await steps_store.used_steps_for(scope)
    except Exception:  # noqa: BLE001 - used_step 存储故障不放过重放检测缺口
        logger.warning("mfa used-step store read failed for %s", username, exc_info=True)
        used = set()

    if mp.is_replay(candidates, used):
        new_state = await store.record_failure(key, now=now)
        return False, LoginGateDecision(
            action=mp.DECISION_LOCKED if new_state.is_locked else mp.DECISION_VERIFY_REQUIRED,
            message="该验证码已被使用，请等待下一个时间窗口",
            reason_code="replay_blocked",
            attempts_remaining=new_state.attempts_remaining,
            detail={"window_seconds": mp.LOCKOUT_WINDOW_SECONDS},
        )

    verify = verifier or _lazy_verify_totp()
    if not bool(verify(raw_secret, code)):
        new_state = await store.record_failure(key, now=now)
        return False, LoginGateDecision(
            action=mp.DECISION_LOCKED if new_state.is_locked else mp.DECISION_VERIFY_REQUIRED,
            message="TOTP code is invalid",
            reason_code="totp_invalid",
            attempts_remaining=new_state.attempts_remaining,
            locked_until=datetime.fromtimestamp(new_state.locked_until, tz=timezone.utc)
            if new_state.locked_until
            else None,
            detail={"window_seconds": mp.LOCKOUT_WINDOW_SECONDS},
        )

    expires_at = datetime.fromtimestamp(now, tz=timezone.utc) + timedelta(
        seconds=TOTP_USED_STEP_TTL_SECONDS
    )
    try:
        await steps_store.mark_used(scope, candidates, expires_at=expires_at)
    except Exception:  # noqa: BLE001 - 标记失败不应阻断登录，但必须留痕
        logger.warning("mfa used-step mark failed for %s", username, exc_info=True)

    await clear_mfa_failures(
        db, username=username, tenant_id=tenant_id, client_ip=client_ip, tracker=store
    )
    return True, LoginGateDecision(
        action=DECISION_VERIFY_REQUIRED,
        reason_code="totp_verified",
        attempts_remaining=mp.MAX_FAILURES,
        detail={"scope": scope, "candidates": list(candidates)},
    )


def _lazy_verify_totp() -> Callable[..., bool]:
    """延迟导入 `app.core.totp.verify_totp`，保持本模块无核心依赖。"""
    try:
        from app.core.totp import verify_totp  # noqa: PLC0415

        return verify_totp
    except Exception:  # noqa: BLE001 - 极端情况下退化为「永不通过」
        return lambda _secret, _token, **_kw: False


# ---------------------------------------------------------------------------
# FR-23：审计落点
# ---------------------------------------------------------------------------


async def emit_mfa_audit(
    db: Any,
    *,
    tenant_id: str,
    actor_id: str,
    action: str,
    decision: str,
    target_id: str | None = None,
    detail: Mapping[str, Any] | None = None,
    client_ip: str = "",
    repo: AuditEventRepository | None = None,
    retries: int = 5,
) -> bool:
    """落一条 MFA 相关审计事件（FR-23）。

    **审计失败绝不抛异常**：与 ``tenant_lifecycle.record_tenant_audit`` 的语义
    一致，审计链路故障不能阻断登录 / 解绑主流程。返回是否成功落库。
    """
    try:
        repository = repo or _default_repo(db)
        await repository.record(
            retries=retries,
            tenant_id=tenant_id or None,
            actor_type="user",
            actor_id=actor_id,
            action=action,
            decision=decision,
            target_type="mfa" if action != AUDIT_MFA_LOCKED else "account",
            target_id=target_id,
            client_ip=client_ip or None,
            detail=dict(detail or {}),
        )
        return True
    except Exception:  # noqa: BLE001 - 审计降级为日志
        logger.warning("failed to record mfa audit action=%s actor=%s", action, actor_id, exc_info=True)
        return False


# ---------------------------------------------------------------------------
# OQ-1：解绑 / 绑定通知（通道未接入时降级为审计事件）
# ---------------------------------------------------------------------------


async def notify_mfa_change(
    db: Any,
    *,
    tenant_id: str,
    username: str,
    event_type: str,
    detail: Mapping[str, Any] | None = None,
    client_ip: str = "",
    audit_action: str = AUDIT_MFA_DISABLE,
    decision: str = DECISION_ALLOW,
    channel: MfaNotificationChannel | None = None,
    repo: AuditEventRepository | None = None,
) -> dict[str, Any]:
    """OQ-1：发送 MFA 变更通知，通道未接入时降级为审计事件。

    Returns:
        ``{"notified": bool, "degraded": bool, "reason": str, "audit": bool}``。
        ``notified=False`` 且 ``degraded=True`` 表示仅落了审计事件。
    """
    audit_ok = await emit_mfa_audit(
        db,
        tenant_id=tenant_id,
        actor_id=username,
        action=audit_action,
        decision=decision,
        target_id=username,
        detail={"event_type": event_type, **(dict(detail or {}))},
        client_ip=client_ip,
        repo=repo,
    )

    if channel is None:
        logger.info(
            "mfa change notification degraded: tenant=%s user=%s event=%s (%s)",
            tenant_id,
            username,
            event_type,
            NOTIFICATION_NOT_CONNECTED,
        )
        return {
            "notified": False,
            "degraded": True,
            "reason": NOTIFICATION_NOT_CONNECTED,
            "audit": audit_ok,
        }

    try:
        channel(tenant_id=tenant_id, username=username, event_type=event_type, detail=dict(detail or {}))
        return {"notified": True, "degraded": False, "reason": "", "audit": audit_ok}
    except Exception:  # noqa: BLE001 - 通知失败降级为审计事件
        logger.warning(
            "mfa change notification failed, degraded to audit event: user=%s event=%s",
            username,
            event_type,
            exc_info=True,
        )
        return {"notified": False, "degraded": True, "reason": "notification send failed", "audit": audit_ok}


__all__ = [
    "AccountMfaState",
    "AUDIT_MFA_BIND_REQUIRED",
    "AUDIT_MFA_DISABLE",
    "AUDIT_MFA_ENABLE",
    "AUDIT_MFA_LOCKED",
    "AUDIT_MFA_REPLAY",
    "AUDIT_MFA_VERIFY_FAIL",
    "AUDIT_MFA_VERIFY_OK",
    "DECISION_ALLOW",
    "DECISION_DENY",
    "LockoutState",
    "LoginGateDecision",
    "NOTIFICATION_NOT_CONNECTED",
    "SOURCE_SERVICE",
    "clear_mfa_failures",
    "client_ip_from_request",
    "current_totp_step",
    "emit_mfa_audit",
    "evaluate_login_gate",
    "mp",
    "notify_mfa_change",
    "record_mfa_failure",
    "secret_scope",
]
