"""037 门户申领单状态机与授权开通（chat-api 写侧）。

申领单落地在 ``portal_requests`` 集合，字段契约见
``specs/037-unified-portal/spec.md``（PortalRequest 实体）。状态机（已定决策 #7）：

::

    applied ──approve──> approved ──grant──> granted ──revoke──> revoked
        └────reject────> rejected                        └──expire──> expired

红线：

* **条件更新幂等**：所有状态迁移都带 ``status=<前置状态>`` 过滤并判
  ``modified_count == 1``（并发双审批只有一条生效，第 001 条审计教训的同一纪律）；
* **防自审**：``requester_id == approver_id`` 一律拒绝；审批人解析时若资产 owner
  就是申请人，回落到持 ``portal:approve`` 的管理员；
* **fail-closed**：解析不到审批人、资产已下线 / 已下架时不产生待审单；
* **审计**：申请 / 决策 / 开通 / 回收 / 过期都写 ``gate_events``（与 001 同一审计汇）。

开通 = 直写 ``permission_grants`` 的**用户级**记录（``level=user``，
``code=asset:use:<asset_key>``），字段与 admin-api ``governance/permission_grants.py``
的 ``grant_code`` 完全一致，因此 chat-api 运行时的判权热路径无需任何改动即生效；
回收 = 删除该记录（不存在即未授权，fail-closed）。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from app.core.db import get_db

from .listings import CATALOG_ASSET_TYPES, find_listing, get_asset_basics, normalize_asset_key

#: 申领单集合（跨服务共享，chat-api 写 / admin-api 审批写）。
PORTAL_REQUESTS_COLLECTION = "portal_requests"

#: 001 授权表：开通即写用户级 ``asset:use:<asset_key>``。
PERMISSION_GRANTS_COLLECTION = "permission_grants"

#: 001 单一审计汇。
GATE_EVENTS_COLLECTION = "gate_events"

#: 管理员账户表（审批人回落时读取）。
ADMIN_ACCOUNTS_COLLECTION = "admin_accounts"

#: 租户级门户设置（``grant_ttl_days``；缺省 0 = 不过期）。
PORTAL_SETTINGS_COLLECTION = "portal_settings"

STATUS_APPLIED = "applied"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_GRANTED = "granted"
STATUS_REVOKED = "revoked"
STATUS_EXPIRED = "expired"

#: 全部合法状态。
PORTAL_STATUSES: tuple[str, ...] = (
    STATUS_APPLIED,
    STATUS_APPROVED,
    STATUS_REJECTED,
    STATUS_GRANTED,
    STATUS_REVOKED,
    STATUS_EXPIRED,
)

#: 终态：不再发生迁移。
STATUS_TERMINAL = frozenset({STATUS_REJECTED, STATUS_REVOKED, STATUS_EXPIRED})

#: 状态迁移表（fail-closed：不在表内的一律拒绝）。
STATUS_TRANSITIONS: dict[str, tuple[str, ...]] = {
    STATUS_APPLIED: (STATUS_APPROVED, STATUS_REJECTED),
    STATUS_APPROVED: (STATUS_GRANTED,),
    STATUS_GRANTED: (STATUS_REVOKED, STATUS_EXPIRED),
}

#: 审批权限码（回落审批人筛选条件）。
PORTAL_APPROVE_CODE = "portal:approve"

#: 平台级角色 → 展开为全量权限码（与 001 ``full_access_admin`` 同口径）。
ALL_CODES_ROLES = frozenset({"平台管理员", "超级管理员", "full_access_admin"})

#: 租户默认授权有效期（天）；0 = 不过期。
DEFAULT_GRANT_TTL_DAYS = 0

#: 我的申领单列表单页上限。
MAX_PAGE_SIZE = 100


class PortalRequestError(RuntimeError):
    """申领单领域错误；``reason`` 是稳定的机器可读标识（端点映射 HTTP 状态码）。"""

    def __init__(self, reason: str, message: str = "") -> None:
        self.reason = reason
        self.message = message or reason
        super().__init__(self.message)


# --- 基础工具 ---------------------------------------------------------------


def _now(now: datetime | None = None) -> datetime:
    return now if now is not None else datetime.now(timezone.utc)


def _get_db(db: Any = None) -> Any:
    return db if db is not None else get_db()


def build_asset_use_code(asset_key: str) -> str:
    """授权码：``asset:use:<asset_key>``（001 ``<resource>:<action>[:<target>]``）。"""
    key = normalize_asset_key(asset_key)
    if not key:
        raise PortalRequestError("asset_key_required")
    return f"asset:use:{key}"


def _require_asset_type(asset_type: str) -> str:
    value = str(asset_type or "").strip()
    if value not in CATALOG_ASSET_TYPES:
        raise PortalRequestError("unsupported_asset_type", f"unsupported asset_type: {asset_type!r}")
    return value


def code_satisfies(granted_codes: Iterable[str], required: str) -> bool:
    """最小权限码匹配（与 001 ``has_permission`` 同口径：``*`` / ``portal:*`` / 精确）。"""
    required = str(required or "")
    for raw in granted_codes or ():
        code = str(raw or "")
        if not code:
            continue
        if code == "*" or code == required:
            return True
        if code.endswith(":*") and required.startswith(code[:-1]):
            return True
    return False


async def _audit(
    db: Any,
    *,
    tenant_id: str,
    actor: str,
    action: str,
    decision: str = "allow",
    detail: dict[str, Any] | None = None,
) -> None:
    """写 gate_events 审计；审计失败不阻断业务（与 001 同口径）。"""
    try:
        await db[GATE_EVENTS_COLLECTION].insert_one(
            {
                "event_id": uuid.uuid4().hex,
                "occurred_at": _now(),
                "tenant_id": tenant_id,
                "user_id": actor,
                "roles": [],
                "tool": f"portal.{action}",
                "risk_level": "",
                "autonomy_level": "",
                "decision": decision,
                "layer": "portal",
                "reason": f"portal {action}",
                "detail": detail or {},
            }
        )
    except Exception:  # pragma: no cover - 审计不可用时不阻断主流程
        pass


# --- 审批人解析（动态，不缓存）-----------------------------------------------


async def _asset_owner(db: Any, tenant_id: str, asset_type: str, asset_key: str) -> str:
    """资产 owner 的**用户标识**（解析不到用户返回空串，回落管理员）。"""
    if asset_type == "capability_asset":
        row = await db["capability_assets"].find_one({"asset_id": asset_key})
    else:
        row = await db.skills.find_one({"_id": asset_key, "tenant_id": tenant_id})
    if not row:
        return ""
    for field in ("created_by", "owner_id", "owner"):
        value = str(row.get(field) or "").strip()
        if value:
            return value
    # ``owner_role`` 是角色不是用户，不能作为审批人。
    return ""


async def _appointable_admins(db: Any, tenant_id: str) -> list[dict[str, Any]]:
    """租户内持 ``portal:approve`` 的启用管理员（按 username 稳定排序）。"""
    try:
        rows = await db[ADMIN_ACCOUNTS_COLLECTION].find({"tenant_id": tenant_id}).to_list(length=1000)
    except Exception:
        return []
    eligible: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get("status") or "active") != "active":
            continue
        role = str(row.get("role_name") or "")
        codes = set(row.get("permission_codes") or ())
        if role in ALL_CODES_ROLES or code_satisfies(codes, PORTAL_APPROVE_CODE):
            eligible.append(row)
    eligible.sort(key=lambda r: str(r.get("username") or ""))
    return eligible


async def resolve_approver(
    db: Any = None,
    *,
    tenant_id: str,
    requester_id: str,
    asset_type: str,
    asset_key: str,
) -> str:
    """解析审批人：资产 owner（动态读，不缓存）→ 回落持 ``portal:approve`` 的管理员。

    防自审：owner 就是申请人时直接跳过 owner。解析不到返回 ``""``，由
    :func:`issue_request` fail-closed 拒单。
    """
    db = _get_db(db)
    owner = await _asset_owner(db, tenant_id, asset_type, asset_key)
    if owner and owner != requester_id:
        return owner
    for row in await _appointable_admins(db, tenant_id):
        username = str(row.get("username") or "")
        if username and username != requester_id:
            return username
    return ""


# --- 授权开通 / 回收 ---------------------------------------------------------


async def grant_asset_use(
    db: Any = None,
    *,
    tenant_id: str,
    user_id: str,
    asset_key: str,
    granted_by: str = "",
) -> dict[str, Any]:
    """写用户级 ``asset:use:<asset_key>`` 授权（幂等 upsert，字段同 001 契约）。"""
    db = _get_db(db)
    code = build_asset_use_code(asset_key)
    document = {
        "tenant_id": tenant_id,
        "level": "user",
        "org_id": "",
        "user_id": user_id,
        "code": code,
        "granted_by": granted_by,
        "granted_at": _now(),
    }
    await db[PERMISSION_GRANTS_COLLECTION].update_one(
        {
            "tenant_id": tenant_id,
            "level": "user",
            "org_id": "",
            "user_id": user_id,
            "code": code,
        },
        {"$set": document},
        upsert=True,
    )
    return document


async def revoke_asset_use(db: Any = None, *, tenant_id: str, user_id: str, asset_key: str) -> bool:
    """删用户级授权记录（不存在即未授权，fail-closed）。"""
    db = _get_db(db)
    code = build_asset_use_code(asset_key)
    result = await db[PERMISSION_GRANTS_COLLECTION].delete_one(
        {
            "tenant_id": tenant_id,
            "level": "user",
            "org_id": "",
            "user_id": user_id,
            "code": code,
        }
    )
    return bool(getattr(result, "deleted_count", 0))


# --- 租户设置 ---------------------------------------------------------------


async def grant_ttl_days(db: Any = None, tenant_id: str = "") -> int:
    """租户授权有效期（天）；缺省 0 = 不过期。"""
    db = _get_db(db)
    try:
        row = await db[PORTAL_SETTINGS_COLLECTION].find_one({"tenant_id": tenant_id})
    except Exception:
        return DEFAULT_GRANT_TTL_DAYS
    if not row:
        return DEFAULT_GRANT_TTL_DAYS
    try:
        return max(int(row.get("grant_ttl_days") or 0), 0)
    except (TypeError, ValueError):
        return DEFAULT_GRANT_TTL_DAYS


def _expires_at(now: datetime, ttl_days: int) -> datetime | None:
    if ttl_days <= 0:
        return None
    return now + timedelta(days=ttl_days)


def _is_expired(row: dict[str, Any], now: datetime) -> bool:
    expires_at = row.get("expires_at")
    if not isinstance(expires_at, datetime):
        return False
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at <= now


# --- 申请（幂等）-------------------------------------------------------------


async def _latest_request(
    db: Any,
    *,
    tenant_id: str,
    requester_id: str,
    asset_type: str,
    asset_key: str,
) -> dict[str, Any] | None:
    rows = await db[PORTAL_REQUESTS_COLLECTION].find(
        {
            "tenant_id": tenant_id,
            "requester_id": requester_id,
            "asset_type": asset_type,
            "asset_key": asset_key,
        }
    ).to_list(length=100)
    if not rows:
        return None
    rows.sort(key=lambda r: str(r.get("applied_at") or ""), reverse=True)
    return rows[0]


async def issue_request(
    db: Any = None,
    *,
    tenant_id: str,
    requester_id: str,
    asset_type: str,
    asset_key: str,
    reason: str = "",
    now: datetime | None = None,
) -> dict[str, Any]:
    """创建申领单（幂等）。

    幂等口径（spec 边界）：

    * 已有**有效** granted 单 → 返回 ``already_granted``（不重复建单、不重复开通）；
    * 已有 applied / approved 单 → 返回该单（``pending``），不重复建单；
    * 其余（无单、已回收、已过期、已拒绝）→ 新建 applied 单。
    """
    db = _get_db(db)
    asset_type = _require_asset_type(asset_type)
    asset_key = normalize_asset_key(asset_key)
    requester_id = str(requester_id or "").strip()
    if not requester_id:
        raise PortalRequestError("requester_required")

    # fail-closed：未上架 / 资产不 active 不产生申领单。
    listing = await find_listing(tenant_id, asset_type, asset_key, db=db)
    if not listing:
        raise PortalRequestError("asset_not_published")
    basic = await get_asset_basics(tenant_id, asset_type, asset_key, db=db)
    if not basic:
        raise PortalRequestError("asset_not_available", "asset is not active in the catalog")

    latest = await _latest_request(
        db,
        tenant_id=tenant_id,
        requester_id=requester_id,
        asset_type=asset_type,
        asset_key=asset_key,
    )
    if latest:
        status = str(latest.get("status") or "")
        if status == STATUS_GRANTED and not _is_expired(latest, _now(now)):
            return {"status": "already_granted", "request": latest, "created": False}
        if status in (STATUS_APPLIED, STATUS_APPROVED):
            return {"status": "pending", "request": latest, "created": False}

    approver_id = await resolve_approver(
        db,
        tenant_id=tenant_id,
        requester_id=requester_id,
        asset_type=asset_type,
        asset_key=asset_key,
    )
    if not approver_id:
        # fail-closed：没有可审批人时不落单，避免出现永远无法推进的申请。
        raise PortalRequestError("approver_unresolved", "no eligible approver for this asset")

    applied_at = _now(now)
    document = {
        "tenant_id": tenant_id,
        "request_id": uuid.uuid4().hex,
        "requester_id": requester_id,
        "asset_type": asset_type,
        "asset_key": asset_key,
        "reason": str(reason or "")[:500],
        "status": STATUS_APPLIED,
        "approver_id": approver_id,
        "applied_at": applied_at,
    }
    await db[PORTAL_REQUESTS_COLLECTION].insert_one(document)
    await _audit(
        db,
        tenant_id=tenant_id,
        actor=requester_id,
        action="request.applied",
        detail={
            "request_id": document["request_id"],
            "asset_type": asset_type,
            "asset_key": asset_key,
            "approver_id": approver_id,
        },
    )
    return {"status": STATUS_APPLIED, "request": document, "created": True}


# --- 审批（条件更新 + 防自审）------------------------------------------------


async def _transition(
    db: Any,
    *,
    tenant_id: str,
    request_id: str,
    from_status: str,
    to_status: str,
    updates: dict[str, Any] | None = None,
) -> int:
    """条件更新一次状态迁移；返回 ``modified_count``（1 = 本次生效）。"""
    payload: dict[str, Any] = {"status": to_status}
    payload.update(updates or {})
    result = await db[PORTAL_REQUESTS_COLLECTION].update_one(
        {"tenant_id": tenant_id, "request_id": request_id, "status": from_status},
        {"$set": payload},
    )
    return int(getattr(result, "modified_count", 0) or 0)


async def decide_request(
    db: Any = None,
    *,
    tenant_id: str,
    request_id: str,
    approver_id: str,
    approved: bool,
    reason: str = "",
    now: datetime | None = None,
) -> dict[str, Any]:
    """批准 / 拒绝一张申领单；批准即开通（写用户级授权）。

    并发双审批：第二次条件更新 ``modified_count == 0`` → 返回当前状态、
    ``changed=False``，不重复开通。
    """
    db = _get_db(db)
    approver_id = str(approver_id or "").strip()
    row = await db[PORTAL_REQUESTS_COLLECTION].find_one(
        {"tenant_id": tenant_id, "request_id": str(request_id or "").strip()}
    )
    if not row:
        raise PortalRequestError("request_not_found")
    if not approver_id:
        raise PortalRequestError("approver_required")
    if approver_id == str(row.get("requester_id") or ""):
        # 防自审：申请人不能审批自己的单（001 审计教训）。
        raise PortalRequestError("self_approval_forbidden")

    current = str(row.get("status") or "")
    if current != STATUS_APPLIED:
        return {"status": current, "request": row, "changed": False}

    decided_at = _now(now)
    target = STATUS_APPROVED if approved else STATUS_REJECTED

    if approved:
        # 资产在审批窗口内下线 → 自动拒绝（spec 边界：资产 offline → rejected）。
        basic = await get_asset_basics(tenant_id, row["asset_type"], row["asset_key"], db=db)
        if not basic:
            modified = await _transition(
                db,
                tenant_id=tenant_id,
                request_id=row["request_id"],
                from_status=STATUS_APPLIED,
                to_status=STATUS_REJECTED,
                updates={
                    "approver_id": approver_id,
                    "decided_at": decided_at,
                    "decided_reason": "asset_offline",
                },
            )
            if not modified:
                latest = await db[PORTAL_REQUESTS_COLLECTION].find_one(
                    {"tenant_id": tenant_id, "request_id": row["request_id"]}
                )
                return {"status": str((latest or {}).get("status") or ""), "request": latest or row, "changed": False}
            await _audit(
                db,
                tenant_id=tenant_id,
                actor=approver_id,
                action="request.rejected",
                decision="deny",
                detail={"request_id": row["request_id"], "reason": "asset_offline"},
            )
            return {
                "status": STATUS_REJECTED,
                "request": {**row, "status": STATUS_REJECTED, "decided_reason": "asset_offline"},
                "changed": True,
                "reason": "asset_offline",
            }

    modified = await _transition(
        db,
        tenant_id=tenant_id,
        request_id=row["request_id"],
        from_status=STATUS_APPLIED,
        to_status=target,
        updates={
            "approver_id": approver_id,
            "decided_at": decided_at,
            "decided_reason": str(reason or "")[:500],
        },
    )
    if not modified:
        latest = await db[PORTAL_REQUESTS_COLLECTION].find_one(
            {"tenant_id": tenant_id, "request_id": row["request_id"]}
        )
        return {"status": str((latest or {}).get("status") or ""), "request": latest or row, "changed": False}

    if not approved:
        await _audit(
            db,
            tenant_id=tenant_id,
            actor=approver_id,
            action="request.rejected",
            decision="deny",
            detail={"request_id": row["request_id"], "reason": str(reason or "")},
        )
        return {
            "status": STATUS_REJECTED,
            "request": {**row, "status": STATUS_REJECTED, "approver_id": approver_id, "decided_at": decided_at},
            "changed": True,
        }

    await _audit(
        db,
        tenant_id=tenant_id,
        actor=approver_id,
        action="request.approved",
        detail={"request_id": row["request_id"], "requester_id": row["requester_id"]},
    )

    # 开通：写用户级授权 → 再迁移 approved → granted（条件更新，幂等）。
    grant = await grant_asset_use(
        db,
        tenant_id=tenant_id,
        user_id=str(row["requester_id"]),
        asset_key=row["asset_key"],
        granted_by=approver_id,
    )
    ttl_days = await grant_ttl_days(db, tenant_id=tenant_id)
    granted_at = _now(now)
    expires_at = _expires_at(granted_at, ttl_days)
    grant_updates: dict[str, Any] = {"granted_at": granted_at}
    if expires_at is not None:
        grant_updates["expires_at"] = expires_at
    await _transition(
        db,
        tenant_id=tenant_id,
        request_id=row["request_id"],
        from_status=STATUS_APPROVED,
        to_status=STATUS_GRANTED,
        updates=grant_updates,
    )
    await _audit(
        db,
        tenant_id=tenant_id,
        actor=approver_id,
        action="grant.granted",
        detail={
            "request_id": row["request_id"],
            "requester_id": row["requester_id"],
            "code": grant["code"],
            "expires_at": expires_at.isoformat() if expires_at else None,
        },
    )
    granted = {
        **row,
        "status": STATUS_GRANTED,
        "approver_id": approver_id,
        "decided_at": decided_at,
        "granted_at": granted_at,
    }
    if expires_at is not None:
        granted["expires_at"] = expires_at
    return {"status": STATUS_GRANTED, "request": granted, "grant": grant["code"], "changed": True}


# --- 回收 / 过期 -------------------------------------------------------------


async def revoke_grant(
    db: Any = None,
    *,
    tenant_id: str,
    user_id: str,
    asset_type: str,
    asset_key: str,
    revoked_by: str = "",
    reason: str = "",
    now: datetime | None = None,
) -> dict[str, Any]:
    """回收某用户对某资产的已开通授权（删授权记录 + 申领单转 revoked）。"""
    db = _get_db(db)
    asset_type = _require_asset_type(asset_type)
    asset_key = normalize_asset_key(asset_key)
    deleted = await revoke_asset_use(db, tenant_id=tenant_id, user_id=user_id, asset_key=asset_key)
    revoked_at = _now(now)

    rows = await db[PORTAL_REQUESTS_COLLECTION].find(
        {
            "tenant_id": tenant_id,
            "requester_id": user_id,
            "asset_type": asset_type,
            "asset_key": asset_key,
            "status": STATUS_GRANTED,
        }
    ).to_list(length=100)
    revoked_ids: list[str] = []
    for row in rows:
        modified = await _transition(
            db,
            tenant_id=tenant_id,
            request_id=str(row.get("request_id") or ""),
            from_status=STATUS_GRANTED,
            to_status=STATUS_REVOKED,
            updates={"revoked_at": revoked_at, "revoked_by": str(revoked_by or ""), "revoke_reason": str(reason or "")[:500]},
        )
        if modified:
            revoked_ids.append(str(row.get("request_id") or ""))

    await _audit(
        db,
        tenant_id=tenant_id,
        actor=str(revoked_by or user_id),
        action="grant.revoked",
        decision="deny",
        detail={
            "user_id": user_id,
            "asset_type": asset_type,
            "asset_key": asset_key,
            "code": build_asset_use_code(asset_key),
            "removed": deleted,
            "request_ids": revoked_ids,
            "reason": str(reason or ""),
        },
    )
    return {"revoked": bool(deleted or revoked_ids), "grant_removed": deleted, "request_ids": revoked_ids}


async def expire_stale_grants(
    db: Any = None,
    *,
    tenant_id: str = "",
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """惰性过期：把 ``expires_at`` 已到的 granted 单转 expired 并删授权记录。

    由列表 / 详情读取路径调用（无后台调度器，避免引入新依赖）。
    """
    db = _get_db(db)
    moment = _now(now)
    query: dict[str, Any] = {"status": STATUS_GRANTED}
    if tenant_id:
        query["tenant_id"] = tenant_id
    rows = await db[PORTAL_REQUESTS_COLLECTION].find(query).to_list(length=10_000)

    expired: list[dict[str, Any]] = []
    for row in rows:
        if not _is_expired(row, moment):
            continue
        modified = await _transition(
            db,
            tenant_id=str(row.get("tenant_id") or ""),
            request_id=str(row.get("request_id") or ""),
            from_status=STATUS_GRANTED,
            to_status=STATUS_EXPIRED,
            updates={"expired_at": moment},
        )
        if not modified:
            continue
        await revoke_asset_use(
            db,
            tenant_id=str(row.get("tenant_id") or ""),
            user_id=str(row.get("requester_id") or ""),
            asset_key=str(row.get("asset_key") or ""),
        )
        await _audit(
            db,
            tenant_id=str(row.get("tenant_id") or ""),
            actor="system",
            action="grant.expired",
            decision="deny",
            detail={
                "request_id": row.get("request_id"),
                "user_id": row.get("requester_id"),
                "asset_type": row.get("asset_type"),
                "asset_key": row.get("asset_key"),
            },
        )
        expired.append(
            {
                "request_id": row.get("request_id"),
                "requester_id": row.get("requester_id"),
                "asset_type": row.get("asset_type"),
                "asset_key": row.get("asset_key"),
            }
        )
    return expired


# --- 我的申领单 --------------------------------------------------------------


async def list_my_requests(
    db: Any = None,
    *,
    tenant_id: str,
    requester_id: str,
    status: str = "",
    page: int = 1,
    page_size: int = 20,
    now: datetime | None = None,
) -> dict[str, Any]:
    """我的申领单列表（先惰性过期，再按状态过滤 + 分页）。"""
    db = _get_db(db)
    moment = _now(now)
    await expire_stale_grants(db, tenant_id=tenant_id, now=moment)

    page = max(int(page or 1), 1)
    page_size = min(max(int(page_size or 20), 1), MAX_PAGE_SIZE)
    query: dict[str, Any] = {"tenant_id": tenant_id, "requester_id": requester_id}
    status = str(status or "").strip()
    if status:
        if status not in PORTAL_STATUSES:
            raise PortalRequestError("invalid_status", f"unknown status: {status!r}")
        query["status"] = status

    rows = await db[PORTAL_REQUESTS_COLLECTION].find(query).to_list(length=10_000)
    rows.sort(key=lambda r: str(r.get("applied_at") or ""), reverse=True)

    items: list[dict[str, Any]] = []
    for row in rows:
        item = {
            "request_id": row.get("request_id"),
            "asset_type": row.get("asset_type"),
            "asset_key": row.get("asset_key"),
            "reason": row.get("reason") or "",
            "status": row.get("status"),
            "approver_id": row.get("approver_id") or "",
            "applied_at": row.get("applied_at"),
            "decided_at": row.get("decided_at"),
            "decided_reason": row.get("decided_reason") or "",
            "granted_at": row.get("granted_at"),
            "expires_at": row.get("expires_at"),
            "revoked_at": row.get("revoked_at"),
            # 终态标注（前端直接按它渲染徽标，不再自己推算）。
            "is_terminal": str(row.get("status") or "") in STATUS_TERMINAL,
            "is_expired": str(row.get("status") or "") == STATUS_EXPIRED or _is_expired(row, moment),
        }
        items.append(item)

    total = len(items)
    start = (page - 1) * page_size
    return {
        "items": items[start : start + page_size],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


async def get_my_request_state(
    db: Any = None,
    *,
    tenant_id: str,
    requester_id: str,
    asset_type: str,
    asset_key: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """目录详情用：当前用户对该资产的有效授权 / 最近一张单（无则 None）。"""
    db = _get_db(db)
    asset_key = normalize_asset_key(asset_key)
    await expire_stale_grants(db, tenant_id=tenant_id, now=_now(now))
    latest = await _latest_request(
        db,
        tenant_id=tenant_id,
        requester_id=requester_id,
        asset_type=str(asset_type or ""),
        asset_key=asset_key,
    )
    if not latest:
        return {"status": "", "request": None, "granted": False}
    status = str(latest.get("status") or "")
    granted = status == STATUS_GRANTED and not _is_expired(latest, _now(now))
    return {"status": status, "request": latest, "granted": granted}


# --- 索引（admin-api 启动时创建；此处导出契约常量便于测试）-------------------

REQUESTS_INDEX_SPECS: tuple[tuple[list[tuple[str, int]], str, bool], ...] = (
    ([("tenant_id", 1), ("request_id", 1)], "portal_request_key", True),
    ([("tenant_id", 1), ("status", 1), ("applied_at", -1)], "portal_request_queue", False),
    ([("tenant_id", 1), ("requester_id", 1), ("applied_at", -1)], "portal_request_mine", False),
)
