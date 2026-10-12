"""FR-2 / FR-3 / FR-4 (QF-525/526/527) MFA 强制策略.

三层能力：
1. **强制判定**（FR-2）：高权限账号（平台管理员/租户管理员）未绑定 MFA 时
   不得进入业务——登录后必须完成绑定。
2. **第二因子限流**（FR-3）：按 ``username + tenant_id + client_ip`` 维度计数，
   300 秒窗口内 5 次失败即锁定。
3. **TOTP 防重放**（FR-4）：把已验证过的 TOTP step 持久化，``±1`` 步窗口内的
   同一 step 不可重复使用。

本模块刻意**不依赖数据库**：判定全部是纯函数，计数与 used_step 通过可注入的
store 协议访问。这样：
- 单元测试无需 MongoDB；
- 生产实现可以是内存（测试/降级）或 MongoDB（:class:`MongoTotpUsedStepStore`、
  :class:`MongoMfaLockoutTracker`）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable, Mapping, Protocol, Sequence


# ---------------------------------------------------------------------------
# 常量（FR-1/2/3 的策略数值）
# ---------------------------------------------------------------------------

MAX_FAILURES = 5
LOCKOUT_WINDOW_SECONDS = 300
TOTP_STEP_SECONDS = 30
TOTP_WINDOW = 1  # ±1 步，与现有 totp 校验窗口一致
TOTP_USED_STEP_TTL_SECONDS = 90  # 与 90 秒防重放窗口对齐

PLATFORM_ADMIN_ROLE = "platform_admin"
TENANT_ADMIN_ROLE = "tenant_admin"
HIGH_PRIVILEGE_ROLES: frozenset[str] = frozenset({PLATFORM_ADMIN_ROLE, TENANT_ADMIN_ROLE})

DECISION_NOT_REQUIRED = "not_required"
DECISION_BIND_REQUIRED = "bind_required"
DECISION_VERIFY_REQUIRED = "verify_required"
DECISION_LOCKED = "locked"

# 服务端唯一文案（避免向客户端泄露策略细节）
BIND_REQUIRED_MESSAGE = "该账号需完成 MFA 绑定后才能进入业务。"
LOCKED_MESSAGE = "MFA 校验失败次数过多，请稍后再试。"


# ---------------------------------------------------------------------------
# 判定结果
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AccountMfaState:
    """登录判定所需的账号视图（避免把整行用户记录传进来）。"""

    user_id: str
    username: str
    tenant_id: str = ""
    role: str = ""
    mfa_enabled: bool = False
    has_mfa_secret: bool = False

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "AccountMfaState":
        """从用户文档构建视图；缺字段按安全侧默认（未启用 MFA）。"""
        return cls(
            user_id=str(row.get("id") or row.get("user_id") or row.get("_id") or ""),
            username=str(row.get("username") or ""),
            tenant_id=str(row.get("tenant_id") or ""),
            role=str(row.get("role") or ""),
            mfa_enabled=bool(row.get("mfa_enabled", False)),
            has_mfa_secret=bool(row.get("mfa_secret") or row.get("mfa_secret_hash")),
        )


@dataclass(frozen=True)
class LoginGateDecision:
    """登录闸门判定结果。"""

    action: str
    message: str = ""
    reason_code: str = ""
    locked_until: datetime | None = None
    attempts_remaining: int | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def blocks_business_access(self) -> bool:
        """True 表示该账号此刻不能进入业务（必须绑定或校验 MFA）。"""
        return self.action in {DECISION_BIND_REQUIRED, DECISION_VERIFY_REQUIRED}


@dataclass(frozen=True)
class LockoutState:
    """限流计数状态。"""

    failures: int
    window_start: float
    locked_until: float | None

    @property
    def is_locked(self) -> bool:
        return self.locked_until is not None

    @property
    def attempts_remaining(self) -> int:
        return max(0, MAX_FAILURES - self.failures)


# ---------------------------------------------------------------------------
# 纯函数判定
# ---------------------------------------------------------------------------


def is_high_privilege_role(role: str | None) -> bool:
    """FR-2：平台管理员/租户管理员视为高权限，必须绑定 MFA。"""
    if not isinstance(role, str) or not role.strip():
        return False
    return role.strip().lower() in HIGH_PRIVILEGE_ROLES


def failure_key(*, username: str, tenant_id: str, client_ip: str) -> str:
    """FR-3：限流维度 = username + tenant_id + IP。"""
    return f"{(tenant_id or '-').strip() or '-'}|{(username or '-').strip().lower() or '-'}|{(client_ip or '-').strip() or '-'}"


def tenant_id_from_failure_key(key: str) -> str:
    """从 :func:`failure_key` 的结果反解 tenant_id（用于给文档补 tenant_id 字段，供租户清理）。"""
    return str(key or "").split("|", 1)[0] or "-"


def tenant_id_from_scope(scope: str) -> str:
    """从 :meth:`MongoTotpUsedStepStore.scope_for` 的作用域反解 tenant_id。"""
    return str(scope or "").split("|", 1)[0] or "-"


def candidate_steps(step: int, window: int = TOTP_WINDOW) -> tuple[int, ...]:
    """返回校验窗口内的候选 step（FR-4），含 step 自身。"""
    step = int(step)
    if window <= 0:
        return (step,)
    return (
        tuple(step - i for i in range(window, 0, -1))
        + (step,)
        + tuple(step + i for i in range(1, window + 1))
    )


def is_replay(candidate_steps_: Iterable[int], used_steps: Iterable[int]) -> bool:
    """FR-4：候选 step 是否已在 used_steps 中出现。"""
    used = set(int(s) for s in used_steps)
    return any(int(s) in used for s in candidate_steps_)


def lockout_until_locked(failures: int, now: float) -> float | None:
    """返回锁定截止时间（未锁定时为 None）。"""
    if failures >= MAX_FAILURES:
        return now + LOCKOUT_WINDOW_SECONDS
    return None


def effective_failures(state: LockoutState, now: float) -> int:
    """窗口外的计数归零（滑动窗口语义）。"""
    if state.failures <= 0:
        return 0
    if state.window_start + LOCKOUT_WINDOW_SECONDS < now:
        return 0
    return state.failures


def normalize_lockout_state(state: LockoutState, now: float) -> LockoutState:
    """把过期的锁定状态归零（锁定到期 或 计数窗口已结束）。"""
    if state.is_locked and state.locked_until is not None and state.locked_until < now:
        return reset_failures()
    if state.failures > 0 and effective_failures(state, now) == 0:
        return reset_failures()
    return state


def decide_login_gate(
    state: AccountMfaState,
    *,
    failures: int = 0,
    now: float | None = None,
    max_failures: int = MAX_FAILURES,
) -> LoginGateDecision:
    """FR-2：登录闸门判定。

    判定顺序（先判定"能不能进业务"，再判定"是否被限流"）：
    1. 非高权限账号 → ``not_required``；
    2. 高权限账号已达失败上限 → ``locked``；
    3. 高权限账号已绑定 MFA → ``verify_required``（走第二因子校验）；
    4. 高权限账号未绑定 MFA → ``bind_required``（先完成绑定）。

    Args:
        state: 账号视图。
        failures: 当前限流窗口内的失败次数（由调用方从 store 读取）。
        now: 当前 Unix 秒（可注入便于测试）。
        max_failures: 覆盖默认失败上限（仅测试用）。
    """
    if not is_high_privilege_role(state.role):
        return LoginGateDecision(action=DECISION_NOT_REQUIRED, reason_code="not_high_privilege")

    now = float(now) if now is not None else _now_epoch()
    remaining = max(0, int(max_failures) - int(max(0, failures)))

    if int(failures) >= int(max_failures):
        return LoginGateDecision(
            action=DECISION_LOCKED,
            message=LOCKED_MESSAGE,
            reason_code="rate_limited",
            locked_until=datetime.fromtimestamp(now + LOCKOUT_WINDOW_SECONDS, tz=timezone.utc),
            attempts_remaining=0,
        )

    if not (state.mfa_enabled and state.has_mfa_secret):
        return LoginGateDecision(
            action=DECISION_BIND_REQUIRED,
            message=BIND_REQUIRED_MESSAGE,
            reason_code="mfa_not_bound",
            attempts_remaining=remaining,
        )

    return LoginGateDecision(
        action=DECISION_VERIFY_REQUIRED,
        reason_code="mfa_enabled",
        attempts_remaining=remaining,
        detail={"window_seconds": LOCKOUT_WINDOW_SECONDS},
    )


def record_failure(state: LockoutState, now: float) -> LockoutState:
    """记录一次 MFA 失败并返回新状态（滑动窗口 + 达上限锁定）。"""
    failures = effective_failures(state, now)
    if state.is_locked and state.locked_until and state.locked_until > now:
        # 锁定期内不累加计数，避免锁定被无限延长
        return state
    failures += 1
    locked = lockout_until_locked(failures, now)
    return LockoutState(
        failures=failures,
        window_start=now if state.failures == 0 or state.window_start + LOCKOUT_WINDOW_SECONDS < now else state.window_start,
        locked_until=locked,
    )


def reset_failures() -> LockoutState:
    return LockoutState(failures=0, window_start=0.0, locked_until=None)


def _now_epoch() -> float:
    return datetime.now(timezone.utc).timestamp()


# ---------------------------------------------------------------------------
# Store 协议与内存实现（MongoDB 实现见下方）
# ---------------------------------------------------------------------------


class FailureTracker(Protocol):
    """MFA 失败计数存储（FR-3）。"""

    async def get(self, key: str, *, now: float | None = None) -> LockoutState: ...

    async def record_failure(self, key: str, *, now: float | None = None) -> LockoutState: ...

    async def reset(self, key: str) -> None: ...


class InMemoryFailureTracker:
    """内存实现：单元测试、单机降级、以及多实例前的默认实现。

    注意：多实例部署下必须替换为 MongoDB/Redis 实现，否则各实例计数不一致。
    """

    def __init__(self) -> None:
        self._states: dict[str, LockoutState] = {}

    async def get(self, key: str, *, now: float | None = None) -> LockoutState:
        now = float(now) if now is not None else _now_epoch()
        state = self._states.get(key)
        if state is None:
            return reset_failures()
        refreshed = normalize_lockout_state(state, now)
        if refreshed != state:
            self._states[key] = refreshed
        return refreshed

    async def record_failure(self, key: str, *, now: float | None = None) -> LockoutState:
        now = float(now) if now is not None else _now_epoch()
        state = await self.get(key, now=now)
        new_state = record_failure(state, now)
        self._states[key] = new_state
        return new_state

    async def reset(self, key: str) -> None:
        self._states.pop(key, None)

    def snapshot(self) -> dict[str, LockoutState]:
        return dict(self._states)


class UsedStepStore(Protocol):
    """TOTP used_step 存储（FR-4）。"""

    async def used_steps_for(self, scope: str) -> set[int]: ...

    async def mark_used(self, scope: str, steps: Iterable[int], *, expires_at: datetime) -> None: ...


class InMemoryUsedStepStore:
    """内存实现：单元测试用。"""

    def __init__(self) -> None:
        self._entries: dict[str, list[tuple[int, datetime]]] = {}

    async def used_steps_for(self, scope: str) -> set[int]:
        entries = self._entries.get(scope)
        if not entries:
            return set()
        now = datetime.now(timezone.utc)
        return {step for step, expires in entries if expires > now}

    async def mark_used(self, scope: str, steps: Iterable[int], *, expires_at: datetime) -> None:
        bucket = self._entries.setdefault(scope, [])
        for step in steps:
            bucket.append((int(step), expires_at))


class MongoMfaLockoutTracker:
    """MongoDB 实现：``mfa_lockouts`` 集合（FR-3）。

    文档结构：
    ``{"_id": key, "tenant_id": str, "failures": int, "window_start": float,
       "locked_until": float|null, "updated_at": dt}``

    ``tenant_id`` 由 key 反解得到，使该集合可被租户清理（TENANT_SCOPED_COLLECTIONS）
    按 ``tenant_id`` 直接 sweep。
    """

    COLLECTION = "mfa_lockouts"

    def __init__(self, db: Any, *, collection: str | None = None) -> None:
        self._db = db
        self._collection = collection or self.COLLECTION

    def _coll(self) -> Any:
        return self._db[self._collection]

    async def get(self, key: str, *, now: float | None = None) -> LockoutState:
        now = float(now) if now is not None else _now_epoch()
        doc = await self._coll().find_one({"_id": key})
        if not doc:
            return reset_failures()
        state = LockoutState(
            failures=int(doc.get("failures") or 0),
            window_start=float(doc.get("window_start") or 0.0),
            locked_until=None if doc.get("locked_until") in (None, "") else float(doc["locked_until"]),
        )
        refreshed = normalize_lockout_state(state, now)
        if refreshed != state:
            await self.reset(key)
            return reset_failures()
        return state

    async def record_failure(self, key: str, *, now: float | None = None) -> LockoutState:
        now = float(now) if now is not None else _now_epoch()
        state = await self.get(key, now=now)
        new_state = record_failure(state, now)
        await self._coll().update_one(
            {"_id": key},
            {
                "$set": {
                    "failures": new_state.failures,
                    "window_start": new_state.window_start,
                    "locked_until": new_state.locked_until,
                    "tenant_id": tenant_id_from_failure_key(key),
                    "updated_at": datetime.now(timezone.utc),
                }
            },
            upsert=True,
        )
        return new_state

    async def reset(self, key: str) -> None:
        await self._coll().delete_one({"_id": key})


class MongoTotpUsedStepStore:
    """MongoDB 实现：``mfa_used_steps`` 集合（FR-4）。

    文档结构：
    ``{"_id": f"{scope}:{step}", "scope": scope, "tenant_id": str, "step": int,
       "expires_at": dt, "created_at": dt}``
    ``expires_at`` 上建 TTL 索引，由 MongoDB 自动清理过期记录；
    ``tenant_id`` 由 scope 反解得到，供租户清理按 tenant_id sweep。
    """

    COLLECTION = "mfa_used_steps"

    def __init__(self, db: Any, *, collection: str | None = None) -> None:
        self._db = db
        self._collection = collection or self.COLLECTION

    def _coll(self) -> Any:
        return self._db[self._collection]

    async def ensure_indexes(self) -> None:
        coll = self._coll()
        await coll.create_index([("expires_at", 1)], expireAfterSeconds=0, name="mfa_used_steps_ttl")
        await coll.create_index([("scope", 1), ("step", 1)], name="mfa_used_steps_scope_step")

    async def used_steps_for(self, scope: str) -> set[int]:
        now = datetime.now(timezone.utc)
        cursor = self._coll().find({"scope": scope, "expires_at": {"$gt": now}})
        return {int(doc["step"]) async for doc in cursor}

    async def mark_used(self, scope: str, steps: Iterable[int], *, expires_at: datetime) -> None:
        now = datetime.now(timezone.utc)
        docs = [
            {
                "_id": f"{scope}:{int(step)}",
                "scope": scope,
                "tenant_id": tenant_id_from_scope(scope),
                "step": int(step),
                "expires_at": expires_at,
                "created_at": now,
            }
            for step in steps
        ]
        if docs:
            await self._coll().insert_many(docs, ordered=False, continue_on_error=True)

    @staticmethod
    def scope_for(*, user_id: str, tenant_id: str = "", secret_hint: str = "") -> str:
        """used_step 的作用域：同一用户+租户+同一枚 secret 共享防重放窗口。"""
        return f"{tenant_id or '-'}|{user_id}|{secret_hint or '-'}"


__all__ = [
    "AccountMfaState",
    "BIND_REQUIRED_MESSAGE",
    "DECISION_BIND_REQUIRED",
    "DECISION_LOCKED",
    "DECISION_NOT_REQUIRED",
    "DECISION_VERIFY_REQUIRED",
    "FailureTracker",
    "HIGH_PRIVILEGE_ROLES",
    "InMemoryFailureTracker",
    "InMemoryUsedStepStore",
    "LOCKOUT_WINDOW_SECONDS",
    "LOCKED_MESSAGE",
    "LockoutState",
    "LoginGateDecision",
    "MAX_FAILURES",
    "MongoMfaLockoutTracker",
    "MongoTotpUsedStepStore",
    "PLATFORM_ADMIN_ROLE",
    "TENANT_ADMIN_ROLE",
    "TOTP_STEP_SECONDS",
    "TOTP_USED_STEP_TTL_SECONDS",
    "TOTP_WINDOW",
    "UsedStepStore",
    "candidate_steps",
    "decide_login_gate",
    "effective_failures",
    "failure_key",
    "is_high_privilege_role",
    "is_replay",
    "lockout_until_locked",
    "normalize_lockout_state",
    "tenant_id_from_failure_key",
    "tenant_id_from_scope",
    "record_failure",
    "reset_failures",
]
