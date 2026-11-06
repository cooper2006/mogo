"""017 three-scope memory — admin 治理端点（design §9.1）。

契约基准：``apps/admin-web/src/api/memories.ts``（B4 前端已写好）。前端用
``dataOf`` 解包 ``payload.data ?? payload``，因此这里沿用 049
``traffic_allocations.py`` 的裸 dict 响应即可（统一 envelope 亦兼容）。
分页 ``page / page_size / total``（admin），user 侧走 chat-api、本文件不碰。

治理路径的几条纪律（design §7.2 / §7.4 / D4）：

* 范围轴封闭：只认 ``personal / project / department``，``workspace / org``
  等旧拼写一律 ``400 scope_invalid``，无别名 / 兼容层。
* 租户边界：以 ``get_current_admin_user`` 的 token tenant 为准，客户端自报的
  ``tenant_id`` 只做「同租户筛选」，跨租户查询直接空结果（不可见不泄露）。
* 不可见一律 404：治理接口是**独立的、有审计的**读取路径，不复用 chat-api
  的普通读取路径（``visible_to`` / ``list_for_viewer``），也不跨服务 import
  chat-api。这里按 ``scope.py:visible_to`` 中 full-access-admin 分支的结构
  完整性 / N2 / 租户判据做等价过滤；与普通读取路径的差异是治理路径**允许
  读取 archived 记录**（否则 status 筛选与 restore 无法成立），该差异在
  ``_governance_visible`` 中显式注释。
* ``project_id == "default"`` 不得作为项目记忆放行（N2）。
* ``project_owner_id`` 是只读回显，客户端传值一律忽略（本文件的写 payload
  不含该字段；Pydantic 默认 extra=ignore）。
* 项目名消歧按 ``{tenant_id, _id: project_id, user_id: project_owner_id}``
  查 ``projects``，查不到回显「已归档 / 已删除」；不假定 ``project_members``
  集合或 ``sharing_enabled`` 字段。
* 治理动作落 001 审计（``position_role_audit_logs``），事件名取 017 白名单；
  admin-api 没有 chat-api 的 ``feature_audit_bridge``（``scoring.py`` 里是
  ImportError 静默跳过的 dead import），故用 admin-api 既有的审计直写通道
  （与 ``capability_assets/registry.py::audit`` 同款），字段对齐 001
  ``feature.audit`` 契约，使 ``system_audit/query.py`` 可汇总。审计失败只留
  日志不阻断。
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.api.deps import get_current_admin_user
from app.core.db import get_db
from app.governance.rbac_model import has_permission
from app.position_roles.constants import AUDIT_COLLECTION
from app.system_audit.constants import SYSTEM_AUDIT_COLLECTION

logger = logging.getLogger(__name__)

router = APIRouter()

# ── 集合名与常量 ────────────────────────────────────────────────────────
# chat-api store.py: COLLECTION = "memories"；文档主键是 memory_id（非 _id）。
MEMORIES_COLLECTION = "memories"
# 049 quota_projects.py: PROJECT_COLLECTION = "projects"（_id = workspace_id / str）。
PROJECTS_COLLECTION = "projects"
# 策略 / 配额配置：按 tenant_id 一份文档，GET 未配置时回前端默认契约。
POLICIES_COLLECTION = "memory_policies"

DEFAULT_PROJECT_ID = "default"
ARCHIVED_PROJECT_LABEL = "已归档 / 已删除"

# D4 目标态：范围轴只有这三值。旧值明确列出来，命中即 400 scope_invalid。
VALID_SCOPES = frozenset({"personal", "project", "department"})
LEGACY_SCOPES = frozenset({"workspace", "org"})
VALID_STATUSES = frozenset({"active", "archived"})

# design §7.2 建议的权限码（参考 portal_admin.py 的 RBAC 口径）。
MEMORY_READ = "memory:read"
MEMORY_MANAGE = "memory:manage"
MEMORY_APPROVE = "memory:approve"

# 与 portal_admin.py:75 同款：平台级 / 006 full_access_admin 角色 → 全量权限码。
_ALL_CODES_ROLES = frozenset({"平台管理员", "平台超级管理员", "超级管理员", "full_access_admin"})
# 所有已认证管理员的只读基线，避免治理页对普通管理员整体不可用。
_BASELINE_CODES = frozenset({MEMORY_READ})

FEATURE_CODE = "017"
FEATURE_AUDIT_ACTION = "feature.audit"  # 对齐 chat-api feature_audit_bridge
RECENT_WINDOW_DAYS = 7


# ── RBAC（fail-closed，与 portal_admin.py 同款）────────────────────────────
def _admin_codes(user: dict[str, Any]) -> set[str]:
    if str(user.get("role_name") or "") in _ALL_CODES_ROLES:
        return {"*"}
    codes = set(_BASELINE_CODES)
    for code in user.get("permission_codes") or ():
        code = str(code or "")
        if code:
            codes.add(code)
    return codes


def _require(user: dict[str, Any], code: str) -> None:
    if not has_permission(_admin_codes(user), code):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"missing permission: {code}")


def _require_full_access_admin(user: dict[str, Any]) -> None:
    """G-1 / §7.2：删除、提升到 department 需 full_access_admin。"""
    if "*" not in _admin_codes(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="full_access_admin required")


def _tenant_id(user: dict[str, Any]) -> str:
    # 049 traffic_allocations.py 口径：tenant 只来自 token，不读客户端自报值。
    return str(user.get("tenant_id") or "default")


def _actor(user: dict[str, Any]) -> str:
    return str(user.get("username") or user.get("display_name") or "")


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── 治理可见性（独立的、有审计的路径；不复用普通读取路径）─────────────────
def _governance_visible(doc: dict[str, Any], tenant_id: str) -> bool:
    """治理接口对一条记忆是否「可见」，可见才返回，否则一律 404。

    对齐 ``chat-api/app/memory/scope.py::visible_to`` 中 full-access-admin 分支
    的**前置结构完整性检查**与租户 / N2 判据：

    * 跨租户 fail-closed（B-7）；
    * scope 必须在封闭枚举内（D4，旧值 workspace/org 不可见）；
    * personal 需 owner_id，project 需 project_id + project_owner_id 且
      project_id != "default"（N1 / N2），department 需 department_id。

    与 ``visible_to`` 的差异（治理路径专属）：这里**不**因 ``archived`` 而
    返回 False。治理页要按 status=archived 筛选并能 restore 归档记录，
    scope.py 注释亦明确 malformed / archived 记录「the governance surface
    reads it through a separate, audited path」（§157-161）。
    """
    if str(doc.get("tenant_id") or "") != tenant_id:
        return False
    scope = str(doc.get("scope") or "")
    if scope not in VALID_SCOPES:
        return False
    if scope == "personal":
        return bool(str(doc.get("owner_id") or ""))
    if scope == "project":
        project_id = str(doc.get("project_id") or "")
        project_owner_id = str(doc.get("project_owner_id") or "")
        if not project_id or not project_owner_id:
            return False
        if project_id == DEFAULT_PROJECT_ID:  # N2
            return False
        return True
    if scope == "department":
        return bool(str(doc.get("department_id") or ""))
    return False


def _status_of(doc: dict[str, Any]) -> str:
    return "archived" if bool(doc.get("archived")) else "active"


def _as_epoch(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, datetime):
        normalized = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return normalized.timestamp()
    return 0.0


def _fmt_time(value: Any) -> str:
    if isinstance(value, datetime):
        normalized = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return normalized.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, (int, float)) and value:
        return datetime.fromtimestamp(float(value), timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, str):
        return value
    return ""


def _resolved_from(doc: dict[str, Any]) -> str:
    """B-9 / 契约 §响应回显：现算 ``resolved_from``。

    与 chat-api ``app/api/endpoints/memory.py::_resolved_from`` **同款规则**，
    枚举 ``explicit | default | default_fallback | sediment``（无 ``legacy_alias``）。
    ``store.py`` 不落库 ``resolved_from`` / ``actual_scope``（由 chat-api 端点现算），
    因此这里绝不读 DB 里那些不存在的字段，仅由已持久化的可信字段
    （``source_type`` / ``project_id`` / ``scope`` / ``department_id``）现场推导。
    """
    if str(doc.get("source_type") or "") == "session":
        return "sediment"
    if str(doc.get("project_id") or "") == DEFAULT_PROJECT_ID:
        # N2 / E-4：049 "default" 行回落到 personal。
        return "default_fallback"
    if (
        str(doc.get("scope") or "") == "personal"
        and not doc.get("project_id")
        and not doc.get("department_id")
    ):
        return "default"
    return "explicit"


def _serialize(doc: dict[str, Any], project_name: str | None = None) -> dict[str, Any]:
    """DB 行 → 前端 MemoryItem（apps/admin-web/src/api/memories.ts）。

    只回显 ``store.py`` 真实持久化的字段 + 前端契约里声明的可选字段；
    ``provenance`` / ``retrieval_trace`` / ``audit`` 等若文档未存则透传
    可选值或由真实 ``source_*`` 字段组装，不凭空编造内容。

    ``actual_scope`` / ``resolved_from`` 按 chat-api 端点同款规则**现算**
    （store.py 不落库这两个字段），与契约 §响应回显逐条一致，不依赖 DB 字段。
    """
    scope = str(doc.get("scope") or "")
    item: dict[str, Any] = {
        "memory_id": str(doc.get("memory_id") or doc.get("_id") or ""),
        "scope": scope,
        "actual_scope": scope,
        "resolved_from": _resolved_from(doc),
        "project_id": str(doc.get("project_id") or ""),
        # 只读回显；客户端写入一律忽略。
        "project_owner_id": str(doc.get("project_owner_id") or ""),
        "department_id": str(doc.get("department_id") or ""),
        "owner_id": str(doc.get("owner_id") or ""),
        "tenant_id": str(doc.get("tenant_id") or ""),
        "content": str(doc.get("content") or ""),
        "l0_summary": str(doc.get("l0_summary") or ""),
        "l1_overview": str(doc.get("l1_overview") or ""),
        "l2_raw": str(doc.get("l2_raw") or ""),
        "tierable": bool(doc.get("tierable", True)),
        "source_session_id": str(doc.get("source_session_id") or ""),
        "source_type": str(doc.get("source_type") or ""),
        "status": _status_of(doc),
        "archived": bool(doc.get("archived")),
        "created_at": _fmt_time(doc.get("created_at")),
        "updated_at": _fmt_time(doc.get("updated_at")),
        "last_accessed_at": _fmt_time(doc.get("last_accessed_at")),
        "provenance": doc.get("provenance") or {
            "source_session_id": str(doc.get("source_session_id") or ""),
            "source_type": str(doc.get("source_type") or ""),
        },
    }
    # 稀疏可选字段：仅在文档里存在时透传（resolved_from 已在上方现算，
    # 不再从 DB 稀疏透传，避免恒缺字段）。
    for key in ("addr", "retrieval_trace", "audit"):
        if doc.get(key) is not None:
            item[key] = doc.get(key)
    if project_name is not None:
        # project_id + project_owner_id 消歧回显；查不到 → 「已归档 / 已删除」。
        item["project_name"] = project_name
    return item


async def _project_names(db: Any, tenant_id: str) -> dict[tuple[str, str], str]:
    """一次查询构建 ``(project_id, project_owner_id) -> title`` 映射。"""
    rows = await db[PROJECTS_COLLECTION].find({"tenant_id": tenant_id}).to_list(length=None)
    mapping: dict[tuple[str, str], str] = {}
    for row in rows:
        key = (str(row.get("_id") or ""), str(row.get("user_id") or ""))
        mapping[key] = str(row.get("title") or row.get("name") or "")
    return mapping


async def _resolve_project_name(db: Any, tenant_id: str, doc: dict[str, Any]) -> str:
    """按 §9.1 口径 ``{tenant_id, _id: project_id, user_id: project_owner_id}`` 查。"""
    project_id = str(doc.get("project_id") or "")
    project_owner_id = str(doc.get("project_owner_id") or "")
    if not project_id:
        return ""
    row = await db[PROJECTS_COLLECTION].find_one(
        {"tenant_id": tenant_id, "_id": project_id, "user_id": project_owner_id}
    )
    return str((row or {}).get("title") or (row or {}).get("name") or "") or ARCHIVED_PROJECT_LABEL


# ── 审计（admin-api 既有通道，失败只留日志不阻断）─────────────────────────
async def _emit_001_audit(
    db: Any,
    *,
    tenant_id: str,
    actor: str,
    event: str,
    document: dict[str, Any],
) -> None:
    """写 001 审计 ``position_role_audit_logs``，字段对齐 chat-api ``feature_audit_bridge``。

    事件名取 017 白名单（``feature_audit.py`` 已扩充）：memory.archived /
    memory.restored / memory.deleted / memory.promoted / memory.policy.updated。
    """
    try:
        await db[AUDIT_COLLECTION].insert_one(
            {
                "_id": uuid.uuid4().hex,
                "tenant_id": tenant_id,
                "actor": actor,
                "action": FEATURE_AUDIT_ACTION,
                "target_type": "feature",
                "target_id": FEATURE_CODE,
                "details": {"feature": FEATURE_CODE, "event": event, **document},
                "created_at": _now(),
            }
        )
    except Exception as exc:  # 审计是旁路
        logger.warning("[memories._emit_001_audit] suppressed %s: %s", type(exc).__name__, exc)


async def _record_governance_view(
    db: Any,
    *,
    tenant_id: str,
    actor: str,
    memory_id: str,
) -> None:
    """治理接口「跨范围查看」落管理审计（system_audit_logs，admin-api 既有通道）。

    全局 ``SystemAuditMiddleware`` 只覆盖 MUTATING 方法，GET 详情这类特权查看
    在此显式留痕；用注入的 db（不另起 get_db），失败不阻断。
    """
    try:
        await db[SYSTEM_AUDIT_COLLECTION].insert_one(
            {
                "_id": uuid.uuid4().hex,
                "tenant_id": tenant_id,
                "actor": actor,
                "category": "management",
                "module": "memories",
                "module_label": "记忆管理",
                "action": "view",
                "method": "GET",
                "route": "/api/v1/memories/admin/{id}",
                "target": memory_id,
                "result": "success",
                "status_code": 200,
                "occurred_at": _now(),
            }
        )
    except Exception as exc:  # 审计是旁路
        logger.warning("[memories._record_governance_view] suppressed %s: %s", type(exc).__name__, exc)


# ── 错误（沿用仓库既有 HTTPException + detail 形状；025 handler 只接管 422/500）──
def _scope_invalid() -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="scope_invalid")


def _not_found() -> HTTPException:
    # 不泄露存在性：detail 不含任何记忆内容。
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


def _validate_scope(scope: str) -> None:
    """D4：空值表示不筛选；目标态三值放行；旧拼写 / 其它值一律 400。"""
    if scope and (scope in LEGACY_SCOPES or scope not in VALID_SCOPES):
        raise _scope_invalid()


async def _load_visible(
    db: Any,
    tenant_id: str,
    memory_id: str,
) -> dict[str, Any]:
    """按治理路径取单条；不存在 / 不可见 → 404（不泄露内容）。"""
    doc = await db[MEMORIES_COLLECTION].find_one(
        {"memory_id": memory_id, "tenant_id": tenant_id}
    )
    if not doc or not _governance_visible(doc, tenant_id):
        raise _not_found()
    return doc


# ── 请求体 ──────────────────────────────────────────────────────────────
class ReasonPayload(BaseModel):
    reason: str = Field(default="", max_length=500)


class MemoryApprovalPayload(BaseModel):
    memory_id: str = Field(min_length=1)
    target_scope: str = "department"
    department_id: str = Field(min_length=1)
    reason: str = Field(default="", max_length=500)


class VisibilityRule(BaseModel):
    department_ids: list[str] = Field(default_factory=list)
    position_role_ids: list[str] = Field(default_factory=list)
    employee_user_ids: list[str] = Field(default_factory=list)
    include_descendants: bool = True


class MemoryQuota(BaseModel):
    per_user: int = 0
    per_project: int = 0
    per_department: int = 0


class MemoryPoliciesPayload(BaseModel):
    decay_days: int = 30
    cleanup_policy: str = "archive"
    summary_refresh_days: int = 30
    l2_hard_max_bytes: int = 0
    archived_project_retrievable: bool = False
    visibility: VisibilityRule = Field(default_factory=VisibilityRule)
    quota: MemoryQuota = Field(default_factory=MemoryQuota)


def _default_policies() -> dict[str, Any]:
    """与前端 ``defaultMemoryPolicies()`` 完全一致。"""
    return {
        "decay_days": 30,
        "cleanup_policy": "archive",
        "summary_refresh_days": 30,
        "l2_hard_max_bytes": 0,
        "archived_project_retrievable": False,
        "visibility": {
            "department_ids": [],
            "position_role_ids": [],
            "employee_user_ids": [],
            "include_descendants": True,
        },
        "quota": {"per_user": 0, "per_project": 0, "per_department": 0},
    }


# ===========================================================================
# 静态路由先注册，避免被 /{id} 抢占匹配。
# ===========================================================================
@router.get("/list")
async def list_admin_memories(
    current_user: dict[str, Any] = Depends(get_current_admin_user),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    scope: str = Query(default=""),
    tenant_id: str = Query(default=""),
    status_filter: str = Query(default="", alias="status"),
    keyword: str = Query(default=""),
) -> dict[str, Any]:
    """跨范围列表：分页 + scope / 状态 / 关键词 / 租户筛选（§9.1）。"""
    _require(current_user, MEMORY_READ)
    _validate_scope(scope)
    tenant = _tenant_id(current_user)
    db = get_db()

    # 客户端自报 tenant_id 只用于「同租户筛选」；跨租户查询返回空，不泄露其它
    # 租户是否存在（不可见一律不回显）。
    if tenant_id and tenant_id != tenant:
        return {"items": [], "total": 0, "page": page, "page_size": page_size}

    rows = await db[MEMORIES_COLLECTION].find({"tenant_id": tenant}).to_list(length=None)
    wanted_status = status_filter if status_filter in VALID_STATUSES else ""
    needle = keyword.strip().lower()

    visible: list[dict[str, Any]] = []
    for row in rows:
        if not _governance_visible(row, tenant):
            continue
        if scope and str(row.get("scope") or "") != scope:
            continue
        if wanted_status and _status_of(row) != wanted_status:
            continue
        if needle:
            haystack = " ".join(
                str(row.get(field) or "")
                for field in ("content", "l0_summary", "l1_overview", "l2_raw")
            ).lower()
            if needle not in haystack:
                continue
        visible.append(row)

    visible.sort(key=lambda r: _as_epoch(r.get("created_at")), reverse=True)
    total = len(visible)
    skip = (page - 1) * page_size
    page_rows = visible[skip : skip + page_size]

    proj_map = await _project_names(db, tenant)
    items: list[dict[str, Any]] = []
    for row in page_rows:
        project_name = None
        if str(row.get("scope") or "") == "project" and str(row.get("project_id") or ""):
            key = (str(row.get("project_id") or ""), str(row.get("project_owner_id") or ""))
            project_name = proj_map.get(key) or ARCHIVED_PROJECT_LABEL
        items.append(_serialize(row, project_name=project_name))

    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/stats")
async def get_admin_memory_stats(
    current_user: dict[str, Any] = Depends(get_current_admin_user),
) -> dict[str, Any]:
    """指标卡：总数 / 按 scope 分布 / 近日新增 / 待审批（§7.2 / MemoryStats）。"""
    _require(current_user, MEMORY_READ)
    tenant = _tenant_id(current_user)
    db = get_db()
    rows = await db[MEMORIES_COLLECTION].find({"tenant_id": tenant}).to_list(length=None)
    visible = [row for row in rows if _governance_visible(row, tenant)]

    by_scope = {key: 0 for key in VALID_SCOPES}
    for row in visible:
        key = str(row.get("scope") or "")
        if key in by_scope:
            by_scope[key] += 1

    cutoff = time.time() - RECENT_WINDOW_DAYS * 86400
    recent_added = sum(1 for row in visible if _as_epoch(row.get("created_at")) >= cutoff)

    # admin 审批端点是「直接提升」（submitMemoryApproval 返回 MemoryItem），
    # 没有独立的待审批队列，故恒为 0；若后续落 portal_requests 状态机再接。
    pending_approval = 0
    # 覆盖部门数：department 记忆涉及的独立 department_id 数量。
    department_coverage = len(
        {
            str(row.get("department_id") or "")
            for row in visible
            if str(row.get("scope") or "") == "department" and str(row.get("department_id") or "")
        }
    )
    # 待衰减归档：未归档且久未访问（超过 decay_days）的记录数。
    policies = await _load_policies(db, tenant)
    decay_cutoff = time.time() - int(policies.get("decay_days") or 30) * 86400
    pending_decay_archive = sum(
        1
        for row in visible
        if not bool(row.get("archived"))
        and 0 < _as_epoch(row.get("last_accessed_at")) < decay_cutoff
    )

    return {
        "total": len(visible),
        "by_scope": by_scope,
        "recent_added": recent_added,
        "pending_approval": pending_approval,
        "department_coverage": department_coverage,
        "pending_decay_archive": pending_decay_archive,
    }


async def _load_policies(db: Any, tenant_id: str) -> dict[str, Any]:
    doc = await db[POLICIES_COLLECTION].find_one({"tenant_id": tenant_id})
    if not doc:
        return _default_policies()
    defaults = _default_policies()
    result = dict(defaults)
    for key in defaults:
        if key in doc:
            result[key] = doc[key]
    result.pop("_id", None)
    result.pop("tenant_id", None)
    return result


@router.get("/policies")
async def get_memory_policies(
    current_user: dict[str, Any] = Depends(get_current_admin_user),
) -> dict[str, Any]:
    _require(current_user, MEMORY_READ)
    db = get_db()
    return await _load_policies(db, _tenant_id(current_user))


@router.put("/policies")
async def update_memory_policies(
    payload: MemoryPoliciesPayload,
    current_user: dict[str, Any] = Depends(get_current_admin_user),
) -> dict[str, Any]:
    _require(current_user, MEMORY_MANAGE)
    if payload.cleanup_policy not in {"archive", "delete"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="cleanup_policy_invalid")
    tenant = _tenant_id(current_user)
    db = get_db()
    document = payload.model_dump()
    document["tenant_id"] = tenant
    document["updated_by"] = _actor(current_user)
    document["updated_at"] = _now()
    await db[POLICIES_COLLECTION].update_one(
        {"tenant_id": tenant}, {"$set": document}, upsert=True
    )
    await _emit_001_audit(
        db,
        tenant_id=tenant,
        actor=_actor(current_user),
        event="memory.policy.updated",
        document={"decay_days": payload.decay_days, "cleanup_policy": payload.cleanup_policy},
    )
    return await _load_policies(db, tenant)


@router.post("/approvals")
async def submit_memory_approval(
    payload: MemoryApprovalPayload,
    current_user: dict[str, Any] = Depends(get_current_admin_user),
) -> dict[str, Any]:
    """提升审批（§9.1）：target_scope=department + department_id，需 full_access_admin。"""
    _require(current_user, MEMORY_APPROVE)
    _require_full_access_admin(current_user)
    if payload.target_scope != "department":
        raise _scope_invalid()
    tenant = _tenant_id(current_user)
    db = get_db()

    # G-1：目标部门须在当前租户内可见（fail-closed，不注入无关部门）。
    dept = await db["org_units"].find_one(
        {"tenant_id": tenant, "_id": payload.department_id}
    )
    if not dept:
        raise _not_found()

    doc = await _load_visible(db, tenant, payload.memory_id)
    # G-2 / G4：只改落点字段，保留 L0/L1/L2、provenance、project_owner_id。
    await db[MEMORIES_COLLECTION].update_one(
        {"memory_id": payload.memory_id, "tenant_id": tenant},
        {
            "$set": {
                "scope": "department",
                "department_id": payload.department_id,
                "updated_at": _now(),
            }
        },
    )
    await _emit_001_audit(
        db,
        tenant_id=tenant,
        actor=_actor(current_user),
        event="memory.promoted",
        document={
            "memory_id": payload.memory_id,
            "target_scope": "department",
            "department_id": payload.department_id,
            "from_scope": str(doc.get("scope") or ""),
            "reason": payload.reason,
        },
    )
    doc.update({"scope": "department", "department_id": payload.department_id})
    return _serialize(doc)


# ===========================================================================
# 动态 /{id} 路由（放在所有静态路由之后）
# ===========================================================================
@router.get("/{memory_id}")
async def get_admin_memory(
    memory_id: str,
    current_user: dict[str, Any] = Depends(get_current_admin_user),
) -> dict[str, Any]:
    """详情：L0/L1/L2、provenance、项目名消歧回显；不可见一律 404。"""
    _require(current_user, MEMORY_READ)
    tenant = _tenant_id(current_user)
    db = get_db()
    doc = await _load_visible(db, tenant, memory_id)
    project_name = None
    if str(doc.get("scope") or "") == "project" and str(doc.get("project_id") or ""):
        project_name = await _resolve_project_name(db, tenant, doc)
    # 治理接口跨范围查看落管理审计（不复用普通读取路径）。
    await _record_governance_view(
        db, tenant_id=tenant, actor=_actor(current_user), memory_id=memory_id
    )
    return _serialize(doc, project_name=project_name)


async def _governance_action(
    memory_id: str,
    payload: ReasonPayload,
    current_user: dict[str, Any],
    *,
    action: str,
    event: str,
) -> dict[str, bool]:
    """archive / restore / delete 共用：可见性校验 → 写 → 001 审计。"""
    if action == "delete":
        _require_full_access_admin(current_user)  # §7.2 删除需 full_access_admin
    else:
        _require(current_user, MEMORY_MANAGE)
    tenant = _tenant_id(current_user)
    db = get_db()
    doc = await _load_visible(db, tenant, memory_id)
    query = {"memory_id": memory_id, "tenant_id": tenant}

    if action == "archive":
        await db[MEMORIES_COLLECTION].update_one(
            query, {"$set": {"archived": True, "updated_at": _now()}}
        )
    elif action == "restore":
        await db[MEMORIES_COLLECTION].update_one(
            query, {"$set": {"archived": False, "updated_at": _now()}}
        )
    else:  # delete
        await db[MEMORIES_COLLECTION].delete_one(query)

    await _emit_001_audit(
        db,
        tenant_id=tenant,
        actor=_actor(current_user),
        event=event,
        document={
            "memory_id": memory_id,
            "scope": str(doc.get("scope") or ""),
            "action": action,
            "reason": payload.reason,
        },
    )
    return {"success": True}


@router.post("/{memory_id}/archive")
async def archive_admin_memory(
    memory_id: str,
    payload: ReasonPayload,
    current_user: dict[str, Any] = Depends(get_current_admin_user),
) -> dict[str, bool]:
    return await _governance_action(
        memory_id, payload, current_user, action="archive", event="memory.archived"
    )


@router.post("/{memory_id}/restore")
async def restore_admin_memory(
    memory_id: str,
    payload: ReasonPayload,
    current_user: dict[str, Any] = Depends(get_current_admin_user),
) -> dict[str, bool]:
    return await _governance_action(
        memory_id, payload, current_user, action="restore", event="memory.restored"
    )


@router.post("/{memory_id}/delete")
async def delete_admin_memory(
    memory_id: str,
    payload: ReasonPayload,
    current_user: dict[str, Any] = Depends(get_current_admin_user),
) -> dict[str, bool]:
    return await _governance_action(
        memory_id, payload, current_user, action="delete", event="memory.deleted"
    )
