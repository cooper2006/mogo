"""056 — 审批单一内核 ``ApprovalKernel``。

把历史上三套互不相识的审批状态机收敛为一个可复用的内核：

* ``tool``   —— admin-api ``gate_approvals``（工具放行）
* ``portal`` —— 037 ``portal_requests``（申领开通）
* ``sop``    —— 050 ``human_approval`` / ``run_store.claim_pending``（SOP 续跑）

本模块是 **新增内核本体**（spec 056 R-1 ~ R-6），刻意 **不改动任何既有调用方**：
spec「风险与回滚」明确 Kernel 为新增模块、旧路径保留到下一个版本，通过
``APPROVAL_KERNEL_ENABLED=false`` 可切回。调用方迁移（R-7）、统一待办端点
（US1 的 ``/api/v1/admin/approvals/*``）、``resolve_review`` 增加 reassign 选项
（R-4 后半）属于后续阶段，须连真实 Mongo + 三服务回归才能安全落地。

设计要点：
* **revision 乐观并发**（R-2）：所有状态转换的 ``update_one`` filter 都带
  ``{"state": PENDING, "revision": expected}`` 前置条件，``modified_count == 0``
  即抛 :class:`ApprovalConflictError`（对应错误码 ``approval.conflict``），
  由调用方幂等返回或重试——杜绝「取消后又批准」「终态被覆盖」的 TOCTOU 竞态。
* **身份一致性**（R-5）：``decide`` 校验 ``actor_id == approver_id``，不匹配抛
  :class:`ApprovalActorMismatchError`（错误码 ``approval.actor_mismatch``）。
* **统一审计**（R-6/R-7）：每个方法写一条 ``gate_events`` 事件，动作命名
  ``approval.{source_type}.{action}``；``detail`` 含 ``source_id`` / ``run_id`` /
  ``node_id`` / ``previous_state`` / ``new_state`` / ``actor_id``。审计失败
  fail-open（重试 3 次后记 ``approval.audit_write_failed`` 错误日志），不阻断业务。
* **fail-closed 超时**（R-2）：``resolve_timeout`` 把悬而未决且已过 deadline 的
  票据一律置 ``expired``。
* 后端透明（E4）：基于 ``app.core.db.get_db()`` 抽象，Mongo 与 PanWeiDB 均可；
  ``db`` / ``audit_db`` 支持构造注入，单测无需真实数据库。

角色型审批人（R-3）属 spec clarify 项，首期仅实现用户型；传入 role_id 时记
warning 但不阻塞（E1）。
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Literal, Optional

from app.common.shared_constants import utc_now

logger = logging.getLogger(__name__)

#: 内核专属集合——与旧 ``gate_approvals`` / ``portal_requests`` 隔离，存量数据不热迁移（E2）。
TICKETS_COLLECTION = "approval_tickets"
#: 001 gatekeeper 单一审计汇（与 portal/ontology/employees 同 schema）。
GATE_EVENTS_COLLECTION = "gate_events"

AUDIT_MAX_RETRIES = 3


class ApprovalState(str, Enum):
    """票据状态机（056 R-1）。"""

    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    REASSIGNED = "reassigned"  # 改派后的中间态，仍需新审批人决策


#: 可决策/可取消状态：``REASSIGNED`` 是改派后的中间态，仍需新审批人决策
#: （056 R-1 注释）；若只认 PENDING，改派后新审批人将看不到可决策票据，
#: 复刻 spec P1-4 的「改派出口残缺 → 死锁」。
_DECIDABLE_STATES = [ApprovalState.PENDING.value, ApprovalState.REASSIGNED.value]


class ApprovalSource(str, Enum):
    """审批来源（056 R-1 / R-6 前缀）。"""

    TOOL = "tool"
    PORTAL = "portal"
    SOP = "sop"


class ApprovalError(Exception):
    """内核异常基类，携带对外的稳定错误码（见 docs/error-codes.md §3）。"""

    code = "approval.error"

    def __init__(self, message: str = "", **detail: Any) -> None:
        super().__init__(message)
        self.detail = detail


class ApprovalConflictError(ApprovalError):
    """revision 前置条件失配：并发状态转换，先落库者胜（056 R-1/R-2）。"""

    code = "approval.conflict"


class ApprovalActorMismatchError(ApprovalError):
    """决策人不是票据登记的审批人（056 R-5）。"""

    code = "approval.actor_mismatch"


class ApprovalNotFoundError(ApprovalError):
    """票据不存在或不属于该租户。"""

    code = "approval.not_found"


@dataclass
class ApprovalTicket:
    """签发的审批票据（``issue`` 返回值）。"""

    ticket_id: str
    source: ApprovalSource
    source_id: str
    tenant_id: str
    actor_id: str
    approver_id: str
    deadline: datetime
    state: ApprovalState
    revision: int
    token: str  # 一次性明文 token，仅签发时返回；库里只存 token_hash
    run_id: str = ""
    node_id: str = ""
    created_at: datetime = field(default_factory=utc_now)


@dataclass
class ApprovalTodo:
    """统一待办视图元素（``list_todos`` 返回值）。"""

    ticket_id: str
    source_type: str
    source_id: str
    tenant_id: str
    approver_id: str
    deadline: datetime
    state: str
    run_id: str = ""
    node_id: str = ""


@dataclass
class ApprovalOutcome:
    """状态转换结果。"""

    ok: bool
    state: ApprovalState
    ticket_id: str
    revision: int
    code: str = ""  # 成功为空；冲突/身份不匹配时是稳定错误码
    detail: dict[str, Any] = field(default_factory=dict)


def _token_hash(token: str) -> str:
    return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()


def resolve_approver(actor_id: str, tenant_id: str, *, role_id: str = "") -> str:
    """统一审批人解析（056 R-3）。

    首期仅支持**用户型**：``approver_id`` 即 ``actor_id`` 字面值。角色型（查
    ``position_roles`` 选一名 active 成员）属 clarify 项、暂不实现；传入
    ``role_id`` 时记 warning 并 fallback 为用户型，不阻塞（E1）。
    """
    if role_id:
        logger.warning(
            "approval.resolve_approver.role_not_supported tenant=%s role_id=%s "
            "falling_back_to_actor=%s", tenant_id, role_id, actor_id,
        )
    return str(actor_id or "")


class ApprovalKernel:
    """统一审批状态机，MongoDB / PanWeiDB 后端透明（056 R-1）。"""

    def __init__(
        self,
        db: Optional[Any] = None,
        *,
        audit_db: Optional[Any] = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._db = db
        self._audit_db = audit_db
        self._clock = clock

    # ── 惰性后端解析（构造注入优先，便于单测） ────────────────────────
    def _tickets(self) -> Any:
        db = self._db
        if db is None:
            from app.core.db import get_db

            db = get_db()
            self._db = db
        return db[TICKETS_COLLECTION]

    def _events(self) -> Any:
        # 审计库可与业务库分离（US3 / T044 语义）；仓库当前未提供 get_audit_db，
        # 因此惰性尝试导入，缺失时回退业务库，避免编造不存在的 API。
        if self._audit_db is not None:
            return self._audit_db[GATE_EVENTS_COLLECTION]
        try:
            from app.core.db import get_audit_db  # type: ignore[attr-defined]

            self._audit_db = get_audit_db()
        except (ImportError, AttributeError):
            self._audit_db = self._db if self._db is not None else _business_db()
        return self._audit_db[GATE_EVENTS_COLLECTION]

    # ── 审计（fail-open，不阻断业务） ─────────────────────────────────
    async def _audit(
        self,
        *,
        source: ApprovalSource,
        action: str,
        tenant_id: str,
        actor_id: str,
        detail: dict[str, Any],
        decision: str = "allow",
    ) -> None:
        event = {
            "event_id": uuid.uuid4().hex,
            "occurred_at": self._clock(),
            "tenant_id": tenant_id,
            "user_id": actor_id,
            "roles": [],
            "tool": f"approval.{source.value}.{action}",
            "risk_level": "",
            "autonomy_level": "",
            "decision": decision,
            "layer": "approval_kernel",
            "reason": f"approval {source.value} {action}",
            "source_service": "chat-api",
            "detail": detail,
        }
        for attempt in range(AUDIT_MAX_RETRIES):
            try:
                await self._events().insert_one(dict(event))
                return
            except Exception as exc:  # pragma: no cover - 审计不可用不阻断主流程
                logger.warning(
                    "approval.audit_write_retry tenant=%s action=%s attempt=%d: %s",
                    tenant_id, action, attempt + 1, exc,
                )
        logger.error(
            "approval.audit_write_failed tenant=%s action=%s (gave up after %d retries)",
            tenant_id, action, AUDIT_MAX_RETRIES,
        )

    # ── 核心方法 ─────────────────────────────────────────────────────
    async def issue(
        self,
        *,
        source: ApprovalSource,
        source_id: str,
        tenant_id: str,
        actor_id: str,
        approver_id: str,
        deadline: datetime,
        ttl_seconds: int = 300,
        run_id: str = "",
        node_id: str = "",
    ) -> ApprovalTicket:
        """签发待办，返回含一次性 token 的票据（056 R-1）。"""
        token = secrets.token_urlsafe(24)
        ticket_id = uuid.uuid4().hex
        now = self._clock()
        doc = {
            "ticket_id": ticket_id,
            "source": source.value,
            "source_id": str(source_id),
            "tenant_id": str(tenant_id),
            "actor_id": str(actor_id),
            "approver_id": str(approver_id),
            "token_hash": _token_hash(token),
            "deadline": deadline,
            "ttl_seconds": int(ttl_seconds),
            "run_id": str(run_id or ""),
            "node_id": str(node_id or ""),
            "state": ApprovalState.PENDING.value,
            "revision": 0,
            "created_at": now,
            "updated_at": now,
        }
        await self._tickets().insert_one(doc)
        await self._audit(
            source=source, action="issued", tenant_id=str(tenant_id), actor_id=str(actor_id),
            detail={
                "source_id": str(source_id), "run_id": str(run_id or ""),
                "node_id": str(node_id or ""), "previous_state": None,
                "new_state": ApprovalState.PENDING.value, "actor_id": str(actor_id),
            },
        )
        return ApprovalTicket(
            ticket_id=ticket_id, source=source, source_id=str(source_id),
            tenant_id=str(tenant_id), actor_id=str(actor_id), approver_id=str(approver_id),
            deadline=deadline, state=ApprovalState.PENDING, revision=0, token=token,
            run_id=str(run_id or ""), node_id=str(node_id or ""), created_at=now,
        )

    async def decide(
        self,
        *,
        source: ApprovalSource,
        source_id: str,
        tenant_id: str,
        token: str,
        actor_id: str,
        approved: bool,
        reason: str = "",
    ) -> ApprovalOutcome:
        """审批人决策（approve/deny），带身份校验 + revision 原子推进（056 R-1/R-2/R-5）。"""
        collection = self._tickets()
        doc = await collection.find_one(
            {
                "source": source.value,
                "source_id": str(source_id),
                "tenant_id": str(tenant_id),
                "token_hash": _token_hash(token),
                "state": {"$in": _DECIDABLE_STATES},
            }
        )
        if doc is None:
            raise ApprovalNotFoundError("approval ticket not found or not pending", source_id=str(source_id))
        if str(actor_id or "") != str(doc.get("approver_id") or ""):
            raise ApprovalActorMismatchError(
                "decision actor does not match approver_id",
                source_id=str(source_id), actor_id=str(actor_id),
            )
        # fail-closed：已过 deadline 的票据哪怕仍是 pending 也不得批准。
        if doc.get("deadline") and doc["deadline"] < self._clock():
            await self._expire(doc, reason="decide_after_deadline")
            raise ApprovalConflictError("approval ticket expired", source_id=str(source_id))

        new_state = ApprovalState.APPROVED if approved else ApprovalState.DENIED
        expected = int(doc.get("revision") or 0)
        # 原子 CAS：filter 同时约束 state 与 revision，先落库者胜。
        result = await collection.update_one(
            {"_id": doc["_id"], "state": {"$in": _DECIDABLE_STATES}, "revision": expected},
            {
                "$set": {
                    "state": new_state.value,
                    "resolved_at": self._clock(),
                    "updated_at": self._clock(),
                    "decided_by": str(actor_id),
                    "reason": str(reason or ""),
                },
                "$inc": {"revision": 1},
            },
        )
        if result.modified_count != 1:
            raise ApprovalConflictError(
                "concurrent state transition", source_id=str(source_id), expected_revision=expected,
            )
        action = "decided" if approved else "denied"
        await self._audit(
            source=source, action=action, tenant_id=str(tenant_id), actor_id=str(actor_id),
            decision="allow" if approved else "deny",
            detail={
                "source_id": str(source_id), "run_id": doc.get("run_id", ""),
                "node_id": doc.get("node_id", ""),
                "previous_state": str(doc.get("state")), "new_state": new_state.value,
                "actor_id": str(actor_id),
            },
        )
        return ApprovalOutcome(
            ok=True, state=new_state, ticket_id=str(doc["ticket_id"]),
            revision=expected + 1,
            detail={"source_id": str(source_id), "reason": str(reason or "")},
        )

    async def cancel(
        self,
        *,
        source: ApprovalSource,
        source_id: str,
        tenant_id: str,
        actor_id: str,
        reason: str = "",
    ) -> ApprovalOutcome:
        """取消待办，带 revision 前置条件防止 TOCTOU（056 R-2）。"""
        collection = self._tickets()
        doc = await collection.find_one(
            {"source": source.value, "source_id": str(source_id), "tenant_id": str(tenant_id)}
        )
        if doc is None or doc.get("state") not in _DECIDABLE_STATES:
            # 幂等：已是终态（含已被并发决策/取消）→ 返回一致结论，无副作用。
            state = ApprovalState(str(doc["state"])) if doc else ApprovalState.EXPIRED
            return ApprovalOutcome(
                ok=False, state=state, ticket_id=str(doc["ticket_id"]) if doc else "",
                revision=int(doc.get("revision") or 0) if doc else 0,
                code="approval.already_settled",
                detail={"source_id": str(source_id)},
            )
        expected = int(doc.get("revision") or 0)
        result = await collection.update_one(
            {"_id": doc["_id"], "state": {"$in": _DECIDABLE_STATES}, "revision": expected},
            {
                "$set": {
                    "state": ApprovalState.CANCELLED.value,
                    "resolved_at": self._clock(),
                    "updated_at": self._clock(),
                    "cancelled_by": str(actor_id),
                    "reason": str(reason or ""),
                },
                "$inc": {"revision": 1},
            },
        )
        if result.modified_count != 1:
            raise ApprovalConflictError(
                "concurrent state transition during cancel",
                source_id=str(source_id), expected_revision=expected,
            )
        await self._audit(
            source=source, action="cancelled", tenant_id=str(tenant_id), actor_id=str(actor_id),
            detail={
                "source_id": str(source_id), "run_id": doc.get("run_id", ""),
                "node_id": doc.get("node_id", ""),
                "previous_state": str(doc.get("state")),
                "new_state": ApprovalState.CANCELLED.value, "actor_id": str(actor_id),
            },
        )
        return ApprovalOutcome(
            ok=True, state=ApprovalState.CANCELLED, ticket_id=str(doc["ticket_id"]),
            revision=expected + 1,
        )

    async def reassign(
        self,
        *,
        source: ApprovalSource,
        source_id: str,
        tenant_id: str,
        new_approver_id: str,
        actor_id: str,
        reason: str = "",
        new_deadline: Optional[datetime] = None,
    ) -> ApprovalOutcome:
        """改派：更新 approver_id + 重置 deadline + 重签 resume_token（056 R-4）。"""
        collection = self._tickets()
        doc = await collection.find_one(
            {"source": source.value, "source_id": str(source_id), "tenant_id": str(tenant_id)}
        )
        if doc is None or doc.get("state") not in (
            ApprovalState.PENDING.value, ApprovalState.REASSIGNED.value
        ):
            raise ApprovalNotFoundError("approval ticket not reassignable", source_id=str(source_id))
        expected = int(doc.get("revision") or 0)
        token = secrets.token_urlsafe(24)
        deadline = new_deadline or self._clock()
        result = await collection.update_one(
            {
                "_id": doc["_id"],
                "state": {"$in": [ApprovalState.PENDING.value, ApprovalState.REASSIGNED.value]},
                "revision": expected,
            },
            {
                "$set": {
                    "state": ApprovalState.REASSIGNED.value,
                    "approver_id": str(new_approver_id),
                    "deadline": deadline,
                    "token_hash": _token_hash(token),  # 旧 token 立即失效
                    "updated_at": self._clock(),
                    "reassigned_by": str(actor_id),
                    "reason": str(reason or ""),
                },
                "$inc": {"revision": 1},
            },
        )
        if result.modified_count != 1:
            raise ApprovalConflictError(
                "concurrent state transition during reassign",
                source_id=str(source_id), expected_revision=expected,
            )
        await self._audit(
            source=source, action="reassigned", tenant_id=str(tenant_id), actor_id=str(actor_id),
            detail={
                "source_id": str(source_id), "run_id": doc.get("run_id", ""),
                "node_id": doc.get("node_id", ""),
                "previous_state": str(doc.get("state")),
                "new_state": ApprovalState.REASSIGNED.value,
                "actor_id": str(actor_id), "new_approver_id": str(new_approver_id),
            },
        )
        return ApprovalOutcome(
            ok=True, state=ApprovalState.REASSIGNED, ticket_id=str(doc["ticket_id"]),
            revision=expected + 1,
            detail={"new_token": token, "new_approver_id": str(new_approver_id)},
        )

    async def list_todos(
        self,
        *,
        tenant_id: str,
        approver_id: str,
        status: Literal["pending", "all"] = "pending",
    ) -> list[ApprovalTodo]:
        """查询审批人待办列表（统一视图，056 R-1 / US1）。"""
        query: dict[str, Any] = {"tenant_id": str(tenant_id), "approver_id": str(approver_id)}
        if status == "pending":
            query["state"] = {"$in": [ApprovalState.PENDING.value, ApprovalState.REASSIGNED.value]}
        rows = await self._tickets().find(query).to_list(length=500)
        return [
            ApprovalTodo(
                ticket_id=str(r.get("ticket_id") or ""),
                source_type=str(r.get("source") or ""),
                source_id=str(r.get("source_id") or ""),
                tenant_id=str(r.get("tenant_id") or ""),
                approver_id=str(r.get("approver_id") or ""),
                deadline=r.get("deadline"),
                state=str(r.get("state") or ""),
                run_id=str(r.get("run_id") or ""),
                node_id=str(r.get("node_id") or ""),
            )
            for r in rows
        ]

    async def resolve_timeout(self, *, source_id: str, tenant_id: str = "") -> int:
        """超时处置（fail-closed）：悬而未决且已过 deadline 的票据一律 expired。"""
        query: dict[str, Any] = {
            "state": {"$in": [ApprovalState.PENDING.value, ApprovalState.REASSIGNED.value]},
            "deadline": {"$lt": self._clock()},
        }
        if source_id:
            query["source_id"] = str(source_id)
        if tenant_id:
            query["tenant_id"] = str(tenant_id)
        collection = self._tickets()
        rows = await collection.find(query).to_list(length=500)
        expired = 0
        for doc in rows:
            result = await collection.update_one(
                {"_id": doc["_id"], "state": doc["state"], "revision": int(doc.get("revision") or 0)},
                {
                    "$set": {
                        "state": ApprovalState.EXPIRED.value,
                        "resolved_at": self._clock(),
                        "updated_at": self._clock(),
                    },
                    "$inc": {"revision": 1},
                },
            )
            if result.modified_count != 1:
                continue  # 已被并发路径消费，先到者胜
            expired += 1
            src = ApprovalSource(str(doc.get("source") or ApprovalSource.SOP.value))
            await self._audit(
                source=src, action="timeout", tenant_id=str(doc.get("tenant_id") or ""),
                actor_id="system", decision="deny",
                detail={
                    "source_id": str(doc.get("source_id") or ""),
                    "run_id": doc.get("run_id", ""), "node_id": doc.get("node_id", ""),
                    "previous_state": str(doc.get("state")),
                    "new_state": ApprovalState.EXPIRED.value, "actor_id": "system",
                },
            )
        return expired

    # ── R-7 迁移期旁路双写（影子镜像，不参与判权） ─────────────────────
    # 三套旧状态机仍是唯一仲裁源；Kernel 在此只镜像 pending/终态票据 +
    # 统一 gate_events 审计，供统一待办视图与跨能力对账。所有写入都应由
    # approval_mirror 包在 try/except 中调用，失败不阻断业务（fail-open 降级）。
    async def mirror_issue(
        self,
        *,
        source: ApprovalSource,
        source_id: str,
        tenant_id: str,
        actor_id: str,
        approver_id: str,
        deadline: datetime,
        run_id: str = "",
        node_id: str = "",
    ) -> None:
        """镜像一条 pending 影子票据（按 source+source_id 幂等）。"""
        collection = self._tickets()
        key = {"source": source.value, "source_id": str(source_id), "shadow": True}
        if await collection.find_one(key) is not None:
            return
        now = self._clock()
        await collection.insert_one({
            **key,
            "ticket_id": uuid.uuid4().hex,
            "tenant_id": str(tenant_id),
            "actor_id": str(actor_id),
            "approver_id": str(approver_id),
            "token_hash": "",  # 影子票据不可被 Kernel.decide 消费
            "deadline": deadline,
            "run_id": str(run_id or ""),
            "node_id": str(node_id or ""),
            "state": ApprovalState.PENDING.value,
            "revision": 0,
            "created_at": now,
            "updated_at": now,
        })
        await self._audit(
            source=source, action="issued", tenant_id=str(tenant_id), actor_id=str(actor_id),
            detail={
                "source_id": str(source_id), "run_id": str(run_id or ""),
                "node_id": str(node_id or ""), "previous_state": None,
                "new_state": ApprovalState.PENDING.value, "actor_id": str(actor_id),
                "shadow": True,
            },
        )

    async def mirror_decision(
        self,
        *,
        source: ApprovalSource,
        source_id: str,
        tenant_id: str,
        actor_id: str,
        approved: bool,
        reason: str = "",
    ) -> bool:
        """把影子票据推进终态并写审计；返回是否确实镜像到一条票据。

        找不到影子票（例如签发时开关未打开）时静默跳过，绝不抛异常——
        旁路写入不能改变旧状态机的结果与 HTTP 契约。
        """
        collection = self._tickets()
        state = ApprovalState.APPROVED if approved else ApprovalState.DENIED
        # tenant_id 可为空：admin gatekeeper 的 /decide 端点只有 actionId，
        # 拿不到租户；此时按 (source, source_id, shadow) 定位，避免漏镜像。
        # 影子票据不参与判权，跨租户误匹配不会造成放行。
        key: dict[str, Any] = {
            "source": source.value, "source_id": str(source_id),
            "shadow": True, "state": {"$in": _DECIDABLE_STATES},
        }
        if tenant_id:
            key["tenant_id"] = str(tenant_id)
        result = await collection.update_one(
            key,
            {
                "$set": {
                    "state": state.value, "resolved_at": self._clock(),
                    "updated_at": self._clock(), "decided_by": str(actor_id),
                    "reason": str(reason or ""),
                },
                "$inc": {"revision": 1},
            },
        )
        if result.modified_count != 1:
            return False
        await self._audit(
            source=source, action="decided" if approved else "denied",
            tenant_id=str(tenant_id), actor_id=str(actor_id),
            decision="allow" if approved else "deny",
            detail={
                "source_id": str(source_id), "run_id": "", "node_id": "",
                "previous_state": ApprovalState.PENDING.value,
                "new_state": state.value, "actor_id": str(actor_id), "shadow": True,
            },
        )
        return True

    async def _expire(self, doc: dict[str, Any], *, reason: str) -> None:
        """decide 发现票据已过期时的原子过期处置（fail-closed）。"""
        await self._tickets().update_one(
            {
                "_id": doc["_id"], "state": {"$in": _DECIDABLE_STATES},
                "revision": int(doc.get("revision") or 0),
            },
            {
                "$set": {
                    "state": ApprovalState.EXPIRED.value, "updated_at": self._clock(),
                    "expire_reason": reason,
                },
                "$inc": {"revision": 1},
            },
        )


def _business_db() -> Any:
    from app.core.db import get_db

    return get_db()


__all__ = [
    "ApprovalKernel", "ApprovalState", "ApprovalSource", "ApprovalTicket",
    "ApprovalTodo", "ApprovalOutcome", "ApprovalError", "ApprovalConflictError",
    "ApprovalActorMismatchError", "ApprovalNotFoundError", "resolve_approver",
    "TICKETS_COLLECTION", "GATE_EVENTS_COLLECTION",
]
