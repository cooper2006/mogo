from __future__ import annotations

import logging

from datetime import datetime, timezone
from typing import Any

from app.core.ids import is_valid_backend_id, to_backend_id
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.api.deps import get_current_admin_user
from app.core.db import get_db
from app.core.quota_policy import (
    DEFAULT_ALERT_THRESHOLD_RATIO,
    ORG_COLLECTION,
    ORG_QUOTA_POLICY_COLLECTION,
    USER_COLLECTION,
    USER_ORG_REL_COLLECTION,
    USER_QUOTA_LOG_COLLECTION,
    USER_QUOTA_POLICY_COLLECTION,
    ensure_default_user_policy,
    ensure_org_quota_policy,
    get_quota_summary,
    normalize_period,
    normalize_timezone,
    period_window,
    sum_usage,
    utc_now,
)
from app.repositories.directory_repository import DEPARTMENT_COLLECTION
from app.services import quota_projects as projects_service

logger = logging.getLogger(__name__)

router = APIRouter()


class OrgQuotaPayload(BaseModel):
    totalTokens: int = Field(default=0, ge=0)
    unlimited: bool = Field(default=False)
    period: str = Field(default="monthly")
    timezone: str = Field(default="Asia/Shanghai")
    status: str = Field(default="active", pattern=r"^(active|disabled)$")
    # 042 R-10：接近阈值比例，默认 20%，区间 (0, 1]。
    alertThresholdRatio: float = Field(default=DEFAULT_ALERT_THRESHOLD_RATIO, gt=0, le=1)


class TeamPolicyPayload(BaseModel):
    quotaTokens: int = Field(default=0, ge=0)
    period: str = Field(default="monthly")
    status: str = Field(default="active", pattern=r"^(active|disabled)$")
    name: str = Field(default="", max_length=64)


class ProjectPayload(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    note: str = Field(default="", max_length=200)
    memberUserIds: list[str] = Field(default_factory=list)
    status: str = Field(default="active", pattern=r"^(active|disabled)$")


class ProjectPolicyPayload(BaseModel):
    quotaTokens: int = Field(default=0, ge=0)
    period: str = Field(default="monthly")
    status: str = Field(default="active", pattern=r"^(active|disabled)$")


class DefaultPolicyPayload(BaseModel):
    quotaTokens: int = Field(default=0, ge=0)
    unlimited: bool = Field(default=False)
    period: str = Field(default="monthly")
    status: str = Field(default="active", pattern=r"^(active|disabled)$")


class UserPolicyPayload(BaseModel):
    userId: str = Field(min_length=1)
    quotaTokens: int = Field(default=0, ge=0)
    unlimited: bool = Field(default=False)
    period: str = Field(default="monthly")
    reason: str = Field(default="", max_length=200)


def _tenant_id(current_user: dict[str, Any]) -> str:
    return str(current_user.get("tenant_id") or "default")


def _fmt(value: Any) -> str:
    if not isinstance(value, datetime):
        return ""
    normalized = value
    if normalized.tzinfo is None:
        normalized = normalized.replace(tzinfo=timezone.utc)
    return normalized.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


async def _department_maps(tenant_id: str) -> tuple[dict[str, str], dict[str, str]]:
    db = get_db()
    deps = await db[DEPARTMENT_COLLECTION].find({"tenant_id": tenant_id}).to_list(length=10000)
    dep_names = {str(item.get("_id")): str(item.get("name") or "") for item in deps}
    rels = await db[USER_ORG_REL_COLLECTION].find({"tenant_id": tenant_id}).to_list(length=50000)
    primary: dict[str, str] = {}
    for rel in rels:
        user_id = str(rel.get("user_id") or "")
        if rel.get("is_primary") and user_id:
            primary[user_id] = str(rel.get("org_id") or "")
    return dep_names, primary


@router.get("/overview")
async def get_traffic_allocation_overview(current_user: dict[str, Any] = Depends(get_current_admin_user)) -> dict[str, Any]:
    tenant_id = _tenant_id(current_user)
    db = get_db()
    org = await db[ORG_COLLECTION].find_one({"tenant_id": tenant_id}) or {}
    org_policy = await ensure_org_quota_policy(tenant_id, org_total_points=int(org.get("total_points") or 0))
    default_policy = await ensure_default_user_policy(tenant_id, period=str(org_policy.get("period") or "monthly"))
    tz_name = normalize_timezone(org_policy.get("timezone"))
    start_at, end_at = period_window(str(org_policy.get("period") or "monthly"), tz_name)
    org_used = await sum_usage(tenant_id, start_at=start_at, end_at=end_at)
    assigned_policies = await db[USER_QUOTA_POLICY_COLLECTION].find(
        {"tenant_id": tenant_id, "scope_type": "user"},
        {"scope_id": 1, "quota_tokens": 1},
    ).to_list(length=50000)
    policy_user_ids = [str(policy.get("scope_id") or "") for policy in assigned_policies]
    valid_user_oids = [to_backend_id(user_id) for user_id in policy_user_ids if is_valid_backend_id(user_id)]
    existing_user_rows = (
        await db[USER_COLLECTION].find({"_id": {"$in": valid_user_oids}, "tenant_id": tenant_id}, {"_id": 1}).to_list(length=len(valid_user_oids))
        if valid_user_oids
        else []
    )
    existing_user_ids = {str(user.get("_id")) for user in existing_user_rows}
    assigned_count = 0
    assigned_tokens = 0
    for policy in assigned_policies:
        if str(policy.get("scope_id") or "") not in existing_user_ids:
            continue
        assigned_count += 1
        assigned_tokens += int(policy.get("quota_tokens") or 0)
    team_policies = await db[USER_QUOTA_POLICY_COLLECTION].find(
        {"tenant_id": tenant_id, "scope_type": "team"}, {"scope_id": 1, "quota_tokens": 1}
    ).to_list(length=5000)
    project_policies = await db[USER_QUOTA_POLICY_COLLECTION].find(
        {"tenant_id": tenant_id, "scope_type": "project"}, {"scope_id": 1, "quota_tokens": 1}
    ).to_list(length=5000)
    total = int(org_policy.get("total_tokens") or 0)
    # T038: ``unlimited`` (decision 12) means the cap is not enforced, so the
    # front end must render "不限额" instead of doing arithmetic on 0 / -1.
    org_unlimited = bool(org_policy.get("unlimited", False))
    return {
        "orgPolicy": {
            "totalTokens": total,
            "unlimited": org_unlimited,
            "period": normalize_period(org_policy.get("period")),
            "timezone": tz_name,
            "status": org_policy.get("status") or "active",
            "usedTokens": org_used,
            "remainingTokens": -1 if org_unlimited else max(0, total - org_used),
            "periodStartAt": _fmt(start_at),
            "resetAt": _fmt(end_at),
        },
        "defaultPolicy": {
            "quotaTokens": int(default_policy.get("quota_tokens") or 0),
            "unlimited": bool(default_policy.get("unlimited", False)),
            "period": normalize_period(default_policy.get("period")),
            "status": default_policy.get("status") or "active",
        },
        "assignedTokens": assigned_tokens,
        "assignedPolicyCount": assigned_count,
        # 042 R-14：向后兼容扩展；assignedTokens/assignedPolicyCount 仍只统计 user 层。
        "teamAssignedTokens": _scoped_assigned(team_policies),
        "teamPolicyCount": len(team_policies),
        "projectAssignedTokens": _scoped_assigned(project_policies),
        "projectPolicyCount": len(project_policies),
        "alertThresholdRatio": float(
            org_policy.get("alert_threshold_ratio") or DEFAULT_ALERT_THRESHOLD_RATIO
        ),
    }


@router.put("/org-policy")
async def update_org_quota_policy(payload: OrgQuotaPayload, current_user: dict[str, Any] = Depends(get_current_admin_user)) -> dict[str, bool]:
    tenant_id = _tenant_id(current_user)
    now = utc_now()
    db = get_db()
    existing = await db[ORG_QUOTA_POLICY_COLLECTION].find_one({"tenant_id": tenant_id})
    before = int((existing or {}).get("total_tokens") or 0)
    await db[ORG_QUOTA_POLICY_COLLECTION].update_one(
        {"tenant_id": tenant_id},
        {
            "$set": {
                "total_tokens": int(payload.totalTokens),
                "unlimited": bool(payload.unlimited),
                "period": normalize_period(payload.period),
                "timezone": normalize_timezone(payload.timezone),
                "status": payload.status,
                "alert_threshold_ratio": float(payload.alertThresholdRatio),
                "updated_by": str(current_user.get("username") or ""),
                "updated_at": now,
            },
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )
    await db[USER_QUOTA_LOG_COLLECTION].insert_one(
        {
            "tenant_id": tenant_id,
            "user_id": "org_policy",
            "action": "set_org",
            "before_quota_tokens": before,
            "after_quota_tokens": int(payload.totalTokens),
            "delta_tokens": int(payload.totalTokens) - before,
            "reason": "修改企业本周期总额度",
            "operator": str(current_user.get("username") or ""),
            "created_at": now,
        }
    )
    return {"success": True}



@router.put("/default-policy")
async def update_default_user_policy(payload: DefaultPolicyPayload, current_user: dict[str, Any] = Depends(get_current_admin_user)) -> dict[str, bool]:
    tenant_id = _tenant_id(current_user)
    now = utc_now()
    db = get_db()
    
    org_policy = await ensure_org_quota_policy(tenant_id)
    org_unlimited = bool(org_policy.get("unlimited", False))
    if not org_unlimited and int(org_policy.get("total_tokens") or 0) == 0 and int(payload.quotaTokens) > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="当前企业本周期总额度为 0，不能为成员分配大于 0 的额度。请先配置企业总额度。"
        )

    existing = await db[USER_QUOTA_POLICY_COLLECTION].find_one({"tenant_id": tenant_id, "scope_type": "all", "scope_id": ""})

    before = int((existing or {}).get("quota_tokens") or 0)
    await db[USER_QUOTA_POLICY_COLLECTION].update_one(
        {"tenant_id": tenant_id, "scope_type": "all", "scope_id": ""},
        {
            "$set": {
                "quota_tokens": int(payload.quotaTokens),
                "unlimited": bool(payload.unlimited),
                "period": normalize_period(payload.period),
                "priority": 10,
                "status": payload.status,
                "updated_by": str(current_user.get("username") or ""),
                "updated_at": now,
            },
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )
    # 级联更新该组织下所有专属用户的重置周期，以确保全局重置周期设置对所有专属用户也生效
    await db[USER_QUOTA_POLICY_COLLECTION].update_many(
        {"tenant_id": tenant_id, "scope_type": "user"},
        {
            "$set": {
                "period": normalize_period(payload.period),
                "updated_at": now,
            }
        }
    )
    await db[USER_QUOTA_LOG_COLLECTION].insert_one(
        {
            "tenant_id": tenant_id,
            "user_id": "default_policy",
            "action": "set_default",
            "before_quota_tokens": before,
            "after_quota_tokens": int(payload.quotaTokens),
            "delta_tokens": int(payload.quotaTokens) - before,
            "reason": "修改成员默认额度",
            "operator": str(current_user.get("username") or ""),
            "created_at": now,
        }
    )
    return {"success": True}




@router.get("/users")
async def list_user_allocations(
    current_user: dict[str, Any] = Depends(get_current_admin_user),
    keyword: str = Query(default=""),
    statusFilter: str = Query(default=""),
) -> list[dict[str, Any]]:
    tenant_id = _tenant_id(current_user)
    db = get_db()
    query: dict[str, Any] = {"tenant_id": tenant_id}
    if statusFilter:
        query["status"] = statusFilter
    if keyword.strip():
        regex = {"$regex": keyword.strip(), "$options": "i"}
        query["$or"] = [{"name": regex}, {"mobile": regex}, {"phone": regex}, {"email": regex}, {"login_name": regex}]
    users = await db[USER_COLLECTION].find(query).sort("updated_at", -1).to_list(length=5000)
    dep_names, primary_map = await _department_maps(tenant_id)
    rows: list[dict[str, Any]] = []
    for user in users:
        summary = await get_quota_summary(tenant_id, user)
        user_id = str(user.get("_id") or "")
        dep_id = primary_map.get(user_id, str(user.get("primary_org_id") or ""))
        rows.append(
            {
                "userId": user_id,
                "name": user.get("name") or user.get("login_name") or "",
                "loginName": user.get("login_name") or "",
                "email": user.get("email") or "",
                "mobile": user.get("mobile") or user.get("phone") or "",
                "status": user.get("status") or "active",
                "departmentName": dep_names.get(dep_id, ""),
                "quotaTokens": int(summary.get("totalPoints") or 0),
                "usedTokens": int(summary.get("usedPoints") or 0),
                "unlimited": bool(summary.get("unlimited")),
                "remainingTokens": int(summary.get("remainingPoints") or 0),
                "period": summary.get("period") or "monthly",
                "resetAt": summary.get("resetAt") or "",
            }
        )
    return rows


@router.put("/users/{user_id}/policy")
async def update_user_policy(
    user_id: str,
    payload: UserPolicyPayload,
    current_user: dict[str, Any] = Depends(get_current_admin_user),
) -> dict[str, bool]:
    tenant_id = _tenant_id(current_user)
    if payload.userId != user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="用户ID不一致")
    db = get_db()
    if not is_valid_backend_id(user_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="用户ID无效")
    user = await db[USER_COLLECTION].find_one({"_id": to_backend_id(user_id), "tenant_id": tenant_id})
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
        
    org_policy = await ensure_org_quota_policy(tenant_id)
    # T035: unlimited orgs can allocate any per-user amount.
    org_unlimited = bool(org_policy.get("unlimited", False))
    if not org_unlimited and int(org_policy.get("total_tokens") or 0) == 0 and int(payload.quotaTokens) > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="当前企业本周期总额度为 0，不能为用户分配大于 0 的额度。请先配置企业总额度。"
        )

    query = {"tenant_id": tenant_id, "scope_type": "user", "scope_id": user_id}
    existing = await db[USER_QUOTA_POLICY_COLLECTION].find_one(query)

    before = int((existing or {}).get("quota_tokens") or 0)
    now = utc_now()
    await db[USER_QUOTA_POLICY_COLLECTION].update_one(
        query,
        {
            "$set": {
                "quota_tokens": int(payload.quotaTokens),
                "unlimited": bool(payload.unlimited),
                "period": normalize_period(payload.period),
                "priority": 100,
                "status": "active",
                "updated_by": str(current_user.get("username") or ""),
                "updated_at": now,
            },
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )
    await db[USER_QUOTA_LOG_COLLECTION].insert_one(
        {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "action": "set",
            "before_quota_tokens": before,
            "after_quota_tokens": int(payload.quotaTokens),
            "delta_tokens": int(payload.quotaTokens) - before,
            "reason": payload.reason.strip(),
            "operator": str(current_user.get("username") or ""),
            "created_at": now,
        }
    )
    return {"success": True}


@router.get("/logs")
async def list_allocation_logs(
    current_user: dict[str, Any] = Depends(get_current_admin_user),
    page: int = Query(default=1, ge=1),
    pageSize: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    tenant_id = _tenant_id(current_user)
    db = get_db()
    query = {"tenant_id": tenant_id}
    skip = (page - 1) * pageSize
    total = await db[USER_QUOTA_LOG_COLLECTION].count_documents(query)
    logs = await db[USER_QUOTA_LOG_COLLECTION].find(query).sort("created_at", -1).skip(skip).limit(pageSize).to_list(length=pageSize)
    user_ids = [to_backend_id(row["user_id"]) for row in logs if is_valid_backend_id(str(row.get("user_id") or ""))]
    users = await db[USER_COLLECTION].find({"_id": {"$in": user_ids}}).to_list(length=pageSize) if user_ids else []
    user_map = {str(user.get("_id")): user for user in users}
    return {
        "page": page,
        "pageSize": pageSize,
        "total": total,
        "items": [
            {
                "id": str(row.get("_id")),
                "userId": str(row.get("user_id") or ""),
                "userName": "新成员默认额度" if row.get("user_id") == "default_policy" else "企业本周期总额度" if row.get("user_id") == "org_policy" else user_map.get(str(row.get("user_id") or ""), {}).get("name") or "",
                "action": row.get("action") or "set",
                "beforeQuotaTokens": int(row.get("before_quota_tokens") or 0),
                "afterQuotaTokens": int(row.get("after_quota_tokens") or 0),
                "deltaTokens": int(row.get("delta_tokens") or 0),
                "reason": row.get("reason") or "",
                "operator": row.get("operator") or "",
                "createdAt": _fmt(row.get("created_at")),
            }
            for row in logs
        ],
    }


# ---------------------------------------------------------------------------
# 042-three-level-quota: 团队（部门节点）与项目（自定义分组）配额
# ---------------------------------------------------------------------------


def _scoped_assigned(policies: list[dict[str, Any]]) -> int:
    return sum(int(policy.get("quota_tokens") or 0) for policy in policies)


async def _write_quota_log(
    db,
    tenant_id: str,
    *,
    scope_key: str,
    action: str,
    before_tokens: int,
    after_tokens: int,
    reason: str,
    operator: str,
) -> None:
    """复用既有 user_token_allocation_logs（FR-009）；写失败不阻断主流程。"""

    try:
        await db[USER_QUOTA_LOG_COLLECTION].insert_one(
            {
                "tenant_id": tenant_id,
                "user_id": scope_key,
                "action": action,
                "before_quota_tokens": before_tokens,
                "after_quota_tokens": after_tokens,
                "delta_tokens": after_tokens - before_tokens,
                "reason": reason,
                "operator": operator,
                "created_at": utc_now(),
            }
        )
    except Exception as exc:  # 审计是旁路
        logger.warning("[traffic_allocations._write_quota_log] suppressed %s: %s", type(exc).__name__, exc)


async def _require_org_unit(tenant_id: str, org_unit_id: str) -> dict[str, Any]:
    db = get_db()
    department = await db[DEPARTMENT_COLLECTION].find_one(
        {"tenant_id": tenant_id, "_id": org_unit_id}
    )
    if not department:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="部门节点不存在")
    return department


async def _require_project(tenant_id: str, project_id: str) -> dict[str, Any]:
    project = await projects_service.get_project(tenant_id, project_id)
    if not project or str(project.get("status") or "") == "deleted":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目分组不存在")
    return project


async def _upsert_scoped_policy(
    db,
    tenant_id: str,
    *,
    scope_type: str,
    scope_id: str,
    payload: TeamPolicyPayload | ProjectPolicyPayload,
    name: str,
    operator: str,
) -> dict[str, Any]:
    now = utc_now()
    existing = await db[USER_QUOTA_POLICY_COLLECTION].find_one(
        {"tenant_id": tenant_id, "scope_type": scope_type, "scope_id": scope_id}
    )
    before = int((existing or {}).get("quota_tokens") or 0)
    await db[USER_QUOTA_POLICY_COLLECTION].update_one(
        {"tenant_id": tenant_id, "scope_type": scope_type, "scope_id": scope_id},
        {
            "$set": {
                "quota_tokens": int(payload.quotaTokens),
                "period": normalize_period(payload.period),
                "priority": 10,
                "status": payload.status,
                "name": name,
                "updated_by": operator,
                "updated_at": now,
            },
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )
    action = ("update_" if existing else "setup_") + (
        "team" if scope_type == "team" else "project"
    )
    await _write_quota_log(
        db,
        tenant_id,
        scope_key=f"{scope_type}:{scope_id}",
        action=action,
        before_tokens=before,
        after_tokens=int(payload.quotaTokens),
        reason=("修改团队本周期额度" if scope_type == "team" else "修改项目本周期额度"),
        operator=operator,
    )
    return {
        "scopeType": scope_type,
        "scopeId": scope_id,
        "name": name,
        "quotaTokens": int(payload.quotaTokens),
        "period": normalize_period(payload.period),
        "status": payload.status,
    }


@router.get("/teams")
async def list_team_policies(current_user: dict[str, Any] = Depends(get_current_admin_user)) -> dict[str, Any]:
    """团队层策略列表（含部门名称，供前端展示与编辑）。"""

    tenant_id = _tenant_id(current_user)
    db = get_db()
    policies = await db[USER_QUOTA_POLICY_COLLECTION].find(
        {"tenant_id": tenant_id, "scope_type": "team"}
    ).to_list(length=5000)
    department_names, _primary = await _department_maps(tenant_id)
    items = [
        {
            "scopeType": "team",
            "scopeId": str(policy.get("scope_id") or ""),
            "name": str(
                policy.get("name")
                or department_names.get(str(policy.get("scope_id") or ""), "")
            ),
            "quotaTokens": int(policy.get("quota_tokens") or 0),
            "period": normalize_period(policy.get("period")),
            "status": str(policy.get("status") or "active"),
        }
        for policy in policies
    ]
    return {"items": items, "total": len(items)}


@router.put("/teams/{org_unit_id}/policy")
async def update_team_quota_policy(
    org_unit_id: str,
    payload: TeamPolicyPayload,
    current_user: dict[str, Any] = Depends(get_current_admin_user),
) -> dict[str, Any]:
    tenant_id = _tenant_id(current_user)
    department = await _require_org_unit(tenant_id, org_unit_id)
    db = get_db()
    name = str(payload.name or department.get("name") or "")
    return await _upsert_scoped_policy(
        db,
        tenant_id,
        scope_type="team",
        scope_id=org_unit_id,
        payload=payload,
        name=name,
        operator=str(current_user.get("username") or ""),
    )


@router.delete("/teams/{org_unit_id}/policy")
async def delete_team_quota_policy(
    org_unit_id: str,
    current_user: dict[str, Any] = Depends(get_current_admin_user),
) -> dict[str, bool]:
    tenant_id = _tenant_id(current_user)
    db = get_db()
    existing = await db[USER_QUOTA_POLICY_COLLECTION].find_one(
        {"tenant_id": tenant_id, "scope_type": "team", "scope_id": org_unit_id}
    )
    if existing:
        await db[USER_QUOTA_POLICY_COLLECTION].delete_one(
            {"tenant_id": tenant_id, "scope_type": "team", "scope_id": org_unit_id}
        )
        await _write_quota_log(
            db,
            tenant_id,
            scope_key=f"team:{org_unit_id}",
            action="delete_team",
            before_tokens=int(existing.get("quota_tokens") or 0),
            after_tokens=0,
            reason="删除团队额度",
            operator=str(current_user.get("username") or ""),
        )
    return {"success": True}


@router.get("/projects")
async def list_quota_projects(current_user: dict[str, Any] = Depends(get_current_admin_user)) -> dict[str, Any]:
    """项目分组列表，附带该项目的周期额度（取自 user_quota_policies 的 project 层）。"""

    tenant_id = _tenant_id(current_user)
    items = await projects_service.list_projects(tenant_id)
    db = get_db()
    policies = await db[USER_QUOTA_POLICY_COLLECTION].find(
        {"tenant_id": tenant_id, "scope_type": "project"}
    ).to_list(length=projects_service.MAX_MEMBERS)
    by_scope = {str(policy.get("scope_id") or ""): policy for policy in policies}
    for item in items:
        policy = by_scope.get(item["id"])
        item["quotaTokens"] = int((policy or {}).get("quota_tokens") or 0)
        item["period"] = normalize_period((policy or {}).get("period"))
        item["policyStatus"] = str((policy or {}).get("status") or "")
    return {"items": items, "total": len(items)}


@router.post("/projects", status_code=status.HTTP_201_CREATED)
async def create_quota_project(
    payload: ProjectPayload,
    current_user: dict[str, Any] = Depends(get_current_admin_user),
) -> dict[str, Any]:
    tenant_id = _tenant_id(current_user)
    try:
        document = await projects_service.create_project(
            tenant_id,
            name=payload.name,
            note=payload.note,
            member_user_ids=payload.memberUserIds,
            actor=str(current_user.get("username") or ""),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    db = get_db()
    await _write_quota_log(
        db,
        tenant_id,
        scope_key=f"project:{document.get('_id')}",
        action="setup_project",
        before_tokens=0,
        after_tokens=0,
        reason="新建项目分组",
        operator=str(current_user.get("username") or ""),
    )
    return projects_service.project_view(document)


@router.put("/projects/{project_id}")
async def update_quota_project(
    project_id: str,
    payload: ProjectPayload,
    current_user: dict[str, Any] = Depends(get_current_admin_user),
) -> dict[str, Any]:
    tenant_id = _tenant_id(current_user)
    await _require_project(tenant_id, project_id)
    try:
        document = await projects_service.update_project(
            tenant_id,
            project_id,
            name=payload.name,
            note=payload.note,
            member_user_ids=payload.memberUserIds,
            status=payload.status,
            actor=str(current_user.get("username") or ""),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目分组不存在")
    db = get_db()
    await _write_quota_log(
        db,
        tenant_id,
        scope_key=f"project:{project_id}",
        action="update_project",
        before_tokens=0,
        after_tokens=0,
        reason="修改项目分组",
        operator=str(current_user.get("username") or ""),
    )
    return projects_service.project_view(document)


@router.delete("/projects/{project_id}")
async def delete_quota_project(
    project_id: str,
    current_user: dict[str, Any] = Depends(get_current_admin_user),
) -> dict[str, bool]:
    tenant_id = _tenant_id(current_user)
    deleted = await projects_service.delete_project(
        tenant_id, project_id, actor=str(current_user.get("username") or "")
    )
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目分组不存在")
    db = get_db()
    await _write_quota_log(
        db,
        tenant_id,
        scope_key=f"project:{project_id}",
        action="delete_project",
        before_tokens=0,
        after_tokens=0,
        reason="删除项目分组",
        operator=str(current_user.get("username") or ""),
    )
    return {"success": True}


@router.put("/projects/{project_id}/policy")
async def update_project_quota_policy(
    project_id: str,
    payload: ProjectPolicyPayload,
    current_user: dict[str, Any] = Depends(get_current_admin_user),
) -> dict[str, Any]:
    tenant_id = _tenant_id(current_user)
    project = await _require_project(tenant_id, project_id)
    db = get_db()
    return await _upsert_scoped_policy(
        db,
        tenant_id,
        scope_type="project",
        scope_id=project_id,
        payload=payload,
        name=str(project.get("name") or ""),
        operator=str(current_user.get("username") or ""),
    )


@router.delete("/projects/{project_id}/policy")
async def delete_project_quota_policy(
    project_id: str,
    current_user: dict[str, Any] = Depends(get_current_admin_user),
) -> dict[str, bool]:
    tenant_id = _tenant_id(current_user)
    db = get_db()
    existing = await db[USER_QUOTA_POLICY_COLLECTION].find_one(
        {"tenant_id": tenant_id, "scope_type": "project", "scope_id": project_id}
    )
    if existing:
        await db[USER_QUOTA_POLICY_COLLECTION].delete_one(
            {"tenant_id": tenant_id, "scope_type": "project", "scope_id": project_id}
        )
        await _write_quota_log(
            db,
            tenant_id,
            scope_key=f"project:{project_id}",
            action="update_project",
            before_tokens=int(existing.get("quota_tokens") or 0),
            after_tokens=0,
            reason="删除项目额度",
            operator=str(current_user.get("username") or ""),
        )
    return {"success": True}
