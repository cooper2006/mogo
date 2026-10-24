from __future__ import annotations

import logging

from datetime import datetime, timezone, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.core.db import get_db

ORG_COLLECTION = "organizations"
USER_COLLECTION = "end_users"
USER_ORG_REL_COLLECTION = "end_user_org_relations"
TOKEN_USAGE_COLLECTION = "token_usage_logs"
ORG_QUOTA_POLICY_COLLECTION = "org_quota_policies"
USER_QUOTA_POLICY_COLLECTION = "user_quota_policies"
USER_QUOTA_OVERRIDE_COLLECTION = "user_quota_overrides"
USER_QUOTA_LOG_COLLECTION = "user_token_allocation_logs"
# 042-three-level-quota: 团队/项目层策略仍存 user_quota_policies（scope_type 区分），
# 项目分组是新建的轻量实体（与桌面 Code 的 projects 端点语义无关）。
QUOTA_PROJECT_COLLECTION = "quota_projects"
QUOTA_ALERT_COLLECTION = "quota_alert_events"
QUOTA_ALERT_KINDS = ("exceeded", "approaching", "layer_unreadable")
DEFAULT_ALERT_THRESHOLD_RATIO = 0.2
MAX_LAYER_MEMBERS = 5000
TEAM_SCOPE = "team"
PROJECT_SCOPE = "project"
# 并列最小值时的归因顺序：更具体的层优先（R-6）。
SCOPE_ORDER = ("team", "project", "org", "user")

VALID_PERIODS = {"monthly", "daily", "hourly"}
DEFAULT_TIMEZONE = "Asia/Shanghai"


class QuotaExceededError(ValueError):
    """配额超限。042 起携带超限层信息供调用方结构化取用（R-8）。"""

    def __init__(
        self,
        message: str = "",
        *,
        layer: str = "",
        scope_id: str = "",
        kind: str = "exceeded",
    ) -> None:
        super().__init__(message)
        self.layer = layer
        self.scope_id = scope_id
        self.kind = kind


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_period(value: Any) -> str:
    period = str(value or "monthly").strip().lower()
    return period if period in VALID_PERIODS else "monthly"


def normalize_timezone(value: Any) -> str:
    name = str(value or DEFAULT_TIMEZONE).strip() or DEFAULT_TIMEZONE
    try:
        ZoneInfo(name)
        return name
    except Exception:
        return DEFAULT_TIMEZONE


def period_window(period: str, tz_name: str = DEFAULT_TIMEZONE, now: datetime | None = None) -> tuple[datetime, datetime]:
    zone = ZoneInfo(normalize_timezone(tz_name))
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    local_now = current.astimezone(zone)
    normalized_period = normalize_period(period)
    if normalized_period == "hourly":
        start_local = local_now.replace(minute=0, second=0, microsecond=0)
        end_local = start_local + timedelta(hours=1)
    elif normalized_period == "daily":
        start_local = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_local = start_local + _one_day()
    else:
        start_local = local_now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if start_local.month == 12:
            end_local = start_local.replace(year=start_local.year + 1, month=1)
        else:
            end_local = start_local.replace(month=start_local.month + 1)
    return (
        start_local.astimezone(timezone.utc),
        end_local.astimezone(timezone.utc),
    )


def _one_day():
    from datetime import timedelta

    return timedelta(days=1)


async def ensure_org_quota_policy(tenant_id: str, *, org_total_points: int = 0) -> dict[str, Any]:
    db = get_db()
    policy = await db[ORG_QUOTA_POLICY_COLLECTION].find_one({"tenant_id": tenant_id})
    if policy:
        return policy
    now = utc_now()
    total = max(int(org_total_points or 0), 0)
    # T033/T034: default to unlimited (decision 12: 配额默认不限额).
    # ``unlimited=True`` means the quota checks short-circuit to "available".
    policy = {
        # Phase 1 dual-write: canonical tenant_id + legacy tenant_id.
        "tenant_id": tenant_id,
        "total_tokens": total,
        "unlimited": True,
        "period": "monthly",
        "timezone": DEFAULT_TIMEZONE,
        "status": "active",
        "created_at": now,
        "updated_at": now,
    }
    await db[ORG_QUOTA_POLICY_COLLECTION].update_one({"tenant_id": tenant_id}, {"$setOnInsert": policy}, upsert=True)
    return await db[ORG_QUOTA_POLICY_COLLECTION].find_one({"tenant_id": tenant_id}) or policy


async def ensure_default_user_policy(tenant_id: str, *, period: str = "monthly") -> dict[str, Any]:
    db = get_db()
    query = {"tenant_id": tenant_id, "scope_type": "all", "scope_id": ""}
    policy = await db[USER_QUOTA_POLICY_COLLECTION].find_one(query)
    if policy:
        return policy
    now = utc_now()
    policy = {
        **query,
        # Phase 1 dual-write: canonical tenant_id (tenant_id already in query).
        "tenant_id": tenant_id,
        "quota_tokens": 0,
        "period": normalize_period(period),
        "priority": 10,
        "status": "active",
        "created_at": now,
        "updated_at": now,
    }
    await db[USER_QUOTA_POLICY_COLLECTION].update_one(query, {"$setOnInsert": policy}, upsert=True)
    return await db[USER_QUOTA_POLICY_COLLECTION].find_one(query) or policy


async def sum_usage(
    tenant_id: str,
    *,
    user_id: str = "",
    user_ids: list[str] | None = None,
    start_at: datetime,
    end_at: datetime,
) -> int:
    db = get_db()
    match: dict[str, Any] = {
        "tenant_id": tenant_id,
        "created_at": {"$gte": start_at, "$lt": end_at},
        "status": {"$ne": "failed"},
    }
    if user_ids is not None:
        match["user_id"] = {"$in": [str(item) for item in user_ids]}
    elif user_id:
        match["user_id"] = user_id
    rows = await db[TOKEN_USAGE_COLLECTION].aggregate(
        [{"$match": match}, {"$group": {"_id": None, "tokens": {"$sum": {"$ifNull": ["$total_tokens", 0]}}}}],
    ).to_list(length=1)
    return int(rows[0].get("tokens") or 0) if rows else 0


async def resolve_user_policy(tenant_id: str, user_id: str) -> dict[str, Any]:
    db = get_db()
    user_policy = await db[USER_QUOTA_POLICY_COLLECTION].find_one(
        {"tenant_id": tenant_id, "scope_type": "user", "scope_id": user_id},
        sort=[("priority", -1), ("updated_at", -1)],
    )
    if user_policy:
        return user_policy
    org_policy = await db[ORG_QUOTA_POLICY_COLLECTION].find_one({"tenant_id": tenant_id})
    org_period = org_policy.get("period") if org_policy else "monthly"
    default_policy = await ensure_default_user_policy(tenant_id, period=org_period)
    return default_policy


async def sum_active_overrides(tenant_id: str, user_id: str, now: datetime | None = None) -> int:
    db = get_db()
    current = now or utc_now()
    rows = await db[USER_QUOTA_OVERRIDE_COLLECTION].aggregate(
        [
            {
                "$match": {
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "status": "active",
                    "$or": [{"expires_at": {"$exists": False}}, {"expires_at": None}, {"expires_at": {"$gt": current}}],
                }
            },
            {"$group": {"_id": None, "tokens": {"$sum": {"$ifNull": ["extra_tokens", 0]}}}},
        ],
    ).to_list(length=1)
    return int(rows[0].get("tokens") or 0) if rows else 0


async def _team_scope_ids(db, tenant_id: str, user_id: str) -> list[str]:
    """用户直接所属的部门节点（不做子树聚合，R-3）。"""

    rows = await db[USER_ORG_REL_COLLECTION].find(
        {"tenant_id": tenant_id, "user_id": user_id}
    ).to_list(length=200)
    return [str(row.get("org_id") or "") for row in rows if row.get("org_id")]


async def _project_scope_ids(db, tenant_id: str, user_id: str) -> list[str]:
    rows = await db[QUOTA_PROJECT_COLLECTION].find(
        {"tenant_id": tenant_id, "status": "active", "member_user_ids": user_id}
    ).to_list(length=200)
    return [str(row.get("_id") or "") for row in rows if row.get("_id")]


async def _scope_members(db, tenant_id: str, scope_type: str, scope_id: str) -> list[str]:
    if scope_type == TEAM_SCOPE:
        rows = await db[USER_ORG_REL_COLLECTION].find(
            {"tenant_id": tenant_id, "org_id": scope_id}
        ).to_list(length=MAX_LAYER_MEMBERS)
        return [str(row.get("user_id") or "") for row in rows if row.get("user_id")]
    doc = await db[QUOTA_PROJECT_COLLECTION].find_one({"tenant_id": tenant_id, "_id": scope_id})
    if not doc or str(doc.get("status") or "active") != "active":
        return []
    return [str(item) for item in (doc.get("member_user_ids") or [])][:MAX_LAYER_MEMBERS]


async def _layer_state(db, tenant_id: str, *, scope_type: str, scope_id: str, tz_name: str) -> dict[str, Any] | None:
    """单个团队/项目层的当前状态；策略缺失或非 active 视为无该层（R-7）。"""

    policy = await db[USER_QUOTA_POLICY_COLLECTION].find_one(
        {"tenant_id": tenant_id, "scope_type": scope_type, "scope_id": scope_id, "status": "active"},
        sort=[("priority", -1), ("updated_at", -1)],
    )
    if not policy:
        return None
    members = await _scope_members(db, tenant_id, scope_type, scope_id)
    period = normalize_period(policy.get("period") or "monthly")
    start, end = period_window(period, tz_name)
    used = await sum_usage(tenant_id, user_ids=members, start_at=start, end_at=end) if members else 0
    total = int(policy.get("quota_tokens") or policy.get("total_tokens") or 0)
    return {
        "scope_type": scope_type,
        "scope_id": scope_id,
        "name": str(policy.get("name") or ""),
        "total": total,
        "used": used,
        "remaining": max(0, total - used),
        "period": period,
        "period_start": start,
        "period_end": end,
    }


async def _scoped_layers(db, tenant_id: str, user_id: str, tz_name: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """团队/项目层：用户命中的每条策略各算一次，层内取最严（R-2/R-7）。"""

    details: dict[str, Any] = {}
    layers: list[dict[str, Any]] = []
    for scope_type in (TEAM_SCOPE, PROJECT_SCOPE):
        if scope_type == TEAM_SCOPE:
            scope_ids = await _team_scope_ids(db, tenant_id, user_id)
        else:
            scope_ids = await _project_scope_ids(db, tenant_id, user_id)
        states = []
        for scope_id in scope_ids:
            state = await _layer_state(db, tenant_id, scope_type=scope_type, scope_id=scope_id, tz_name=tz_name)
            if state:
                states.append(state)
        if not states:
            continue
        strictest = min(states, key=lambda item: item["remaining"])
        layers.append(strictest)
        prefix = "team" if scope_type == TEAM_SCOPE else "project"
        details[f"{prefix}RemainingPoints"] = strictest["remaining"]
        details[f"{prefix}TotalPoints"] = strictest["total"]
        details[f"{prefix}UsedPoints"] = strictest["used"]
        details[f"{prefix}ResetAt"] = _iso(strictest["period_end"])
        details[f"{prefix}ScopeId"] = strictest["scope_id"]
        details[f"{prefix}Name"] = strictest["name"]
    return details, layers


def _iso(value: datetime) -> str:
    return value.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


async def _record_quota_alert(
    db,
    tenant_id: str,
    layer: dict[str, Any],
    *,
    kind: str,
    ratio: float,
) -> None:
    """写 quota 告警事件；同一 (租户, 层, scope, kind, 周期) 只落一次（R-11）。"""

    period_start = layer.get("period_start")
    alert_key = f"{tenant_id}:{layer['scope_type']}:{layer.get('scope_id') or ''}:{kind}:{period_start.isoformat()}"
    document = {
        "tenant_id": tenant_id,
        "scope_type": layer["scope_type"],
        "scope_id": str(layer.get("scope_id") or ""),
        "kind": kind,
        "ratio": round(float(ratio), 6),
        "layer_name": str(layer.get("name") or ""),
        "period_start": period_start,
        "at": utc_now(),
        "alert_key": alert_key,
    }
    try:
        await db[QUOTA_ALERT_COLLECTION].update_one(
            {"alert_key": alert_key}, {"$setOnInsert": document}, upsert=True
        )
    except Exception as exc:  # 告警是旁路，写失败不阻断主链路
        logging.getLogger(__name__).warning(
            "[core.quota_policy._record_quota_alert] suppressed %s: %s", type(exc).__name__, exc
        )


async def _emit_layer_alerts(db, tenant_id: str, layers: list[dict[str, Any]], threshold_ratio: float) -> None:
    for layer in layers:
        total = int(layer.get("total") or 0)
        if total <= 0:
            continue
        remaining = int(layer.get("remaining") or 0)
        ratio = remaining / total
        if remaining <= 0:
            await _record_quota_alert(db, tenant_id, layer, kind="exceeded", ratio=ratio)
        elif ratio < threshold_ratio:
            await _record_quota_alert(db, tenant_id, layer, kind="approaching", ratio=ratio)


async def get_quota_summary(tenant_id: str, user: dict[str, Any]) -> dict[str, Any]:
    db = get_db()
    user_id = str(user.get("_id") or "")
    space_type = str(user.get("space_type") or "").strip().lower()
    if space_type not in {"personal", "enterprise"}:
        space_type = "personal" if str(user.get("org_name") or "").strip() == "个人空间" else "enterprise"
    org = await db[ORG_COLLECTION].find_one({"tenant_id": tenant_id}) or {}

    if space_type != "enterprise":
        total = int(org.get("total_points") or 0)
        used = int(org.get("used_points") or 0)
        # T033/T034: personal/community spaces default to unlimited
        # (organizations.points_unlimited, decision 12).
        points_unlimited = bool(org.get("points_unlimited", True))
        return {
            "tenantId": tenant_id,
            "orgName": org.get("org_name") or user.get("org_name") or "个人空间",
            "spaceType": "personal",
            "quotaSource": "registration_gift",
            "period": "lifetime",
            "totalPoints": total,
            "usedPoints": used,
            "unlimited": points_unlimited,
            "remainingPoints": -1 if points_unlimited else max(0, total - used),
            "resetAt": "",
            "status": "active",
        }

    org_policy = await ensure_org_quota_policy(tenant_id, org_total_points=int(org.get("total_points") or 0))
    user_policy = await resolve_user_policy(tenant_id, user_id)
    tz_name = normalize_timezone(org_policy.get("timezone"))
    org_start, org_end = period_window(str(org_policy.get("period") or "monthly"), tz_name)
    user_start, user_end = period_window(str(user_policy.get("period") or org_policy.get("period") or "monthly"), tz_name)

    # T033/T034: unlimited short-circuit (decision 12).
    # org_quota_policies.unlimited defaults to True for new tenants; legacy
    # rows without the field are treated as limited (backward-compatible).
    org_unlimited = bool(org_policy.get("unlimited", False))
    if org_unlimited:
        # Usage is still recorded for reporting; the limit itself is lifted.
        org_used = await sum_usage(tenant_id, start_at=org_start, end_at=org_end)
        user_used = await sum_usage(tenant_id, user_id=user_id, start_at=user_start, end_at=user_end)
        return {
            "tenantId": tenant_id,
            "orgName": org.get("org_name") or user.get("org_name") or "组织空间",
            "spaceType": "enterprise",
            "quotaSource": "enterprise_allocation",
            "period": normalize_period(user_policy.get("period") or org_policy.get("period")),
            "totalPoints": -1,
            "usedPoints": user_used,
            "unlimited": True,
            "remainingPoints": -1,
            "resetAt": user_end.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z"),
            "status": "active" if org_policy.get("status") == "active" else "disabled",
            "orgTotalPoints": -1,
            "orgUsedPoints": org_used,
            "orgRemainingPoints": -1,
        }

    org_used = await sum_usage(tenant_id, start_at=org_start, end_at=org_end)
    user_used = await sum_usage(tenant_id, user_id=user_id, start_at=user_start, end_at=user_end)
    org_total = int(org_policy.get("total_tokens") or 0)
    base_user_total = int(user_policy.get("quota_tokens") or 0)
    extra = await sum_active_overrides(tenant_id, user_id)
    user_total = max(0, base_user_total + extra)
    remaining = max(0, min(user_total - user_used, org_total - org_used))
    limiting_scope = "user" if (user_total - user_used) <= (org_total - org_used) else "org"
    threshold_ratio = float(org_policy.get("alert_threshold_ratio") or DEFAULT_ALERT_THRESHOLD_RATIO)
    scoped_details, scoped_layers = await _scoped_layers(db, tenant_id, user_id, tz_name)
    org_layer = {
        "scope_type": "org",
        "scope_id": tenant_id,
        "name": "",
        "total": org_total,
        "used": org_used,
        "remaining": max(0, org_total - org_used),
        "period_start": org_start,
        "period_end": org_end,
    }
    user_layer = {
        "scope_type": "user",
        "scope_id": user_id,
        "name": "",
        "total": user_total,
        "used": user_used,
        "remaining": max(0, user_total - user_used),
        "period_start": user_start,
        "period_end": user_end,
    }
    alert_layers = [*scoped_layers, org_layer, user_layer]
    if scoped_layers:
        # R-6: 三层取小；unlimited 层（total<=0）不参与，并列时按 SCOPE_ORDER 归因。
        candidates = [layer for layer in alert_layers if int(layer.get("total") or 0) > 0]
        if candidates:
            strictest = min(
                candidates,
                key=lambda item: (int(item["remaining"]), SCOPE_ORDER.index(item["scope_type"])),
            )
            remaining = max(0, int(strictest["remaining"]))
            limiting_scope = strictest["scope_type"]
    await _emit_layer_alerts(db, tenant_id, alert_layers, threshold_ratio)
    extra_fields: dict[str, Any] = dict(scoped_details)
    if scoped_layers:
        extra_fields["limitingScope"] = limiting_scope
        extra_fields["limitingResetAt"] = _iso(
            next(
                (layer["period_end"] for layer in alert_layers if layer["scope_type"] == limiting_scope),
                user_end,
            )
        )
    result: dict[str, Any] = {
        "tenantId": tenant_id,
        "orgName": org.get("org_name") or user.get("org_name") or "组织空间",
        "spaceType": "enterprise",
        "quotaSource": "enterprise_allocation",
        "period": normalize_period(user_policy.get("period") or org_policy.get("period")),
        "totalPoints": user_total,
        "usedPoints": user_used,
        "unlimited": False,
        "remainingPoints": remaining,
        "resetAt": user_end.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "active" if org_policy.get("status") == "active" else "disabled",
        "orgTotalPoints": org_total,
        "orgUsedPoints": org_used,
        "orgRemainingPoints": max(0, org_total - org_used),
    }
    result.update(extra_fields)
    return result


def _layer_denial_message(scope_type: str, summary: dict[str, Any]) -> str:
    """R-8：按超限层给出文案；org/user 沿用既有两句原文。"""

    if scope_type == TEAM_SCOPE:
        name = str(summary.get("teamName") or "").strip()
        suffix = f"（{name}）" if name else ""
        return f"团队额度已用尽{suffix}，请联系企业管理员调整额度。"
    if scope_type == PROJECT_SCOPE:
        name = str(summary.get("projectName") or "").strip()
        suffix = f"（{name}）" if name else ""
        return f"项目额度已用尽{suffix}，请联系企业管理员调整额度。"
    if summary.get("spaceType") == "enterprise":
        return "当前企业分派额度已用尽，请联系企业管理员调整额度。"
    return "个人赠送额度已用尽，请升级或切换到有可用额度的空间。"


async def assert_quota_available(tenant_id: str, user: dict[str, Any]) -> dict[str, Any]:
    summary = await get_quota_summary(tenant_id, user)
    if summary.get("status") != "active":
        raise QuotaExceededError(
            "当前空间额度策略未启用，请联系管理员。", layer=str(summary.get("limitingScope") or "")
        )
    # T035: unlimited short-circuit — remainingPoints == -1 means no limit.
    if int(summary.get("remainingPoints") or 0) <= 0 and not summary.get("unlimited"):
        # 042 R-8：叠加层已由 get_quota_summary 归因到 limitingScope。
        layer = str(summary.get("limitingScope") or "").strip()
        scope_id = str(summary.get(f"{layer}ScopeId") or "") if layer in (TEAM_SCOPE, PROJECT_SCOPE) else ""
        raise QuotaExceededError(
            _layer_denial_message(layer, summary),
            layer=layer,
            scope_id=scope_id,
            kind="exceeded",
        )
    return summary
