"""037 门户目录聚合（chat-api 读侧）。

数据源 = ``portal_listings``（上架标记） + ``skills`` / ``capability_assets``
（016/018 治理数据）。**只读投影，不落库** —— ``CatalogItem`` 是一次聚合查询
在应用层 join 出来的视图，字段缺失时对应区域隐藏（FR-004，前端容错）。

关键边界（spec FR-003 / FR-013 / ADR-7）：

* 目录**仅返回已上架且 018 ``active`` 的资产**；
* 严格按 ``end_user`` 会话的租户隔离（``portal_listings.tenant_id``）；
* 036 就绪后 ``L1`` 实验级资产不进公共目录（软裁剪，默认关闭，双向不阻塞）。

集合名与字段契约与 admin-api 侧 ``tests/test_portal_admin.py`` 保持一致。
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from app.core.db import get_db

#: 目录支持的资产类型（首期两类）。
CATALOG_ASSET_TYPES: tuple[str, ...] = ("skill", "capability_asset")

PORTAL_LISTINGS_COLLECTION = "portal_listings"

#: 016 效果分数据集合（跨服务共享；读取失败时字段可缺席）。
QUALITY_METRICS_COLLECTION = "skill_quality_metrics"

#: 036 评级集合（可选；未就绪时读不到，评级字段缺席）。
TRUST_RATINGS_COLLECTION = "trust_ratings"

#: 036 就绪后开启的软裁剪开关（默认关闭，保证 037 不依赖 036）。
PORTAL_L1_FILTER_ENABLED = False

#: 单次目录列表最大页大小。
MAX_PAGE_SIZE = 100

#: 未下架的过滤条件（``unpublished_at`` 为空）。
_ACTIVE_LISTING_FILTER = {"$or": [{"unpublished_at": None}, {"unpublished_at": {"$exists": False}}]}


def _get_db(db: Any = None) -> Any:
    return db if db is not None else get_db()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def is_active_asset(row: dict[str, Any], asset_type: str) -> bool:
    """判定资产是否满足「目录可见」的 active 语义。

    * ``skill``：文档存在；platform 治理的技能要求 ``publication_status == published``
      （016/018 治理后的 active 资产口径），用户自有技能按存在即视为可用；
    * ``capability_asset``：``state == "active"``（018 FR-6）。
    """
    if not row:
        return False
    if asset_type == "capability_asset":
        return str(row.get("state") or "") == "active"
    if asset_type == "skill":
        if str(row.get("authoring_mode") or "") == "platform":
            return str(row.get("publication_status") or "") == "published"
        return True
    return False


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _effect_summary_from_rows(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """把 016 日桶合并成一个摘要（按 ``samples`` 加权；无样本权重的取均值）。"""
    if not rows:
        return None
    total_weight = 0.0
    weighted = 0.0
    plain: list[float] = []
    samples_total = 0
    updated_at: Any = None
    for row in rows:
        score = _as_float(row.get("effect_score"))
        if score is None:
            continue
        weight = _as_float(row.get("samples") if row.get("samples") is not None else row.get("count"))
        if weight is not None and weight > 0:
            total_weight += weight
            weighted += score * weight
            samples_total += int(weight)
        else:
            plain.append(score)
        stamp = row.get("updated_at") or row.get("date") or row.get("bucket")
        if stamp is not None and (updated_at is None or str(stamp) > str(updated_at)):
            updated_at = stamp
    if total_weight > 0:
        score_value = round(weighted / total_weight, 4)
    elif plain:
        score_value = round(sum(plain) / len(plain), 4)
    else:
        return None
    return {"effect_score": score_value, "samples": samples_total or None, "updated_at": updated_at}


async def _effect_summaries(
    db: Any, tenant_id: str, skill_keys: list[str]
) -> dict[str, dict[str, Any]]:
    """批量读取 016 效果分摘要（可选字段，读取失败返回空表）。"""
    if not skill_keys:
        return {}
    try:
        rows = await db[QUALITY_METRICS_COLLECTION].find(
            {"tenant_id": tenant_id, "skill_key": {"$in": skill_keys}}
        ).to_list(length=10_000)
    except Exception:
        return {}
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        key = str(row.get("skill_key") or "")
        if key:
            grouped.setdefault(key, []).append(row)
    summary: dict[str, dict[str, Any]] = {}
    for key, buckets in grouped.items():
        item = _effect_summary_from_rows(buckets)
        if item:
            summary[key] = item
    return summary


def _rating_summary_from_rows(row: dict[str, Any], rating_doc: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """036 评级摘要：优先取 ``trust_ratings`` 集合，回落资产文档上的历史字段。"""
    if rating_doc:
        level = rating_doc.get("level") or rating_doc.get("trust_level")
        if level:
            return {"level": str(level), "score": rating_doc.get("score")}
    rating = row.get("trust_rating") or row.get("rating")
    if rating is None:
        return None
    if isinstance(rating, dict):
        return {"level": rating.get("level") or rating.get("trust_level"), "score": rating.get("score")}
    return {"level": str(rating)}


async def _rating_docs(
    db: Any, tenant_id: str, asset_type: str, asset_keys: list[str]
) -> dict[str, dict[str, Any]]:
    """批量读取 036 评级（可选；未就绪时返回空表）。"""
    if not asset_keys:
        return {}
    try:
        rows = await db[TRUST_RATINGS_COLLECTION].find(
            {"tenant_id": tenant_id, "asset_type": asset_type, "asset_key": {"$in": asset_keys}}
        ).to_list(length=10_000)
    except Exception:
        return {}
    return {str(row.get("asset_key") or ""): row for row in rows}


def _is_l1_asset(row: dict[str, Any], rating: dict[str, Any] | None) -> bool:
    """L1 实验级判定（036 软裁剪用）。"""
    if rating and rating.get("level") == "L1":
        return True
    return str(row.get("trust_level") or "") == "L1" or str(row.get("rating_level") or "") == "L1"


def _project_asset(
    *,
    asset_type: str,
    asset_key: str,
    row: dict[str, Any],
    rating: dict[str, Any] | None,
    effect: dict[str, Any] | None,
) -> dict[str, Any]:
    """资产文档 → 目录卡片视图（纯函数，无 IO）。"""
    owner_role = str(row.get("owner_role") or row.get("owner") or "")
    owner = str(row.get("created_by") or row.get("owner_id") or "") or owner_role
    description = str(row.get("description") or (row.get("summary") or "") or "")
    tags = [str(t) for t in (row.get("tags") or row.get("labels") or []) if t]
    return {
        "asset_type": asset_type,
        "asset_key": asset_key,
        "name": str(row.get("name") or asset_key),
        "description": description,
        "category": str(row.get("category") or ""),
        "owner": owner,
        "owner_role": owner_role,
        "tags": tags,
        "state": str(row.get("state") or "active"),
        "is_low_quality": bool(
            row.get("low_quality")
            or row.get("adoption_status") == "low_quality"
            or row.get("quality_flag")
        ),
        "effect": effect,
        "rating": rating,
        "kind": str(row.get("kind") or ""),
        "endpoint": str(row.get("endpoint") or ""),
    }


async def get_asset_basics(
    tenant_id: str,
    asset_type: str,
    asset_key: str,
    db: Any = None,
) -> dict[str, Any] | None:
    """读取单个资产的基础字段（目录卡片 / 详情共用）。"""
    db = _get_db(db)
    if asset_type == "capability_asset":
        row = await db["capability_assets"].find_one({"asset_id": asset_key})
    else:
        row = await db.skills.find_one({"_id": asset_key, "tenant_id": tenant_id})

    if not row or not is_active_asset(row, asset_type):
        return None

    effects = await _effect_summaries(db, tenant_id, [asset_key] if asset_type == "skill" else [])
    ratings = await _rating_docs(db, tenant_id, asset_type, [asset_key])
    return _project_asset(
        asset_type=asset_type,
        asset_key=asset_key,
        row=row,
        rating=_rating_summary_from_rows(row, ratings.get(asset_key)),
        effect=effects.get(asset_key),
    )


async def find_listing(
    tenant_id: str, asset_type: str, asset_key: str, db: Any = None
) -> dict[str, Any] | None:
    """读取一条**已上架**标记（未上架 / 已下架返回 None）。"""
    db = _get_db(db)
    return await db[PORTAL_LISTINGS_COLLECTION].find_one(
        {
            "tenant_id": tenant_id,
            "asset_type": asset_type,
            "asset_key": asset_key,
            **_ACTIVE_LISTING_FILTER,
        }
    )


async def list_catalog(
    tenant_id: str,
    *,
    category: str = "",
    keyword: str = "",
    page: int = 1,
    page_size: int = 20,
    l1_filter_enabled: bool = PORTAL_L1_FILTER_ENABLED,
    db: Any = None,
) -> dict[str, Any]:
    """目录列表：已上架 + active 资产，支持分类 / 关键词 / 分页。

    返回 ``{"items": [...], "total": int, "page": int, "page_size": int}``。
    """
    db = _get_db(db)
    page = max(int(page or 1), 1)
    page_size = min(max(int(page_size or 20), 1), MAX_PAGE_SIZE)
    keyword = str(keyword or "").strip().lower()

    listings = await db[PORTAL_LISTINGS_COLLECTION].find(
        {"tenant_id": tenant_id, **_ACTIVE_LISTING_FILTER}
    ).to_list(length=10_000)

    # 批量取资产 / 评级 / 效果分，避免 N+1。
    skill_keys = [l["asset_key"] for l in listings if l.get("asset_type") == "skill"]
    cap_keys = [l["asset_key"] for l in listings if l.get("asset_type") == "capability_asset"]
    skills: dict[str, dict[str, Any]] = {}
    caps: dict[str, dict[str, Any]] = {}
    if skill_keys:
        for row in await db.skills.find(
            {"_id": {"$in": skill_keys}, "tenant_id": tenant_id}
        ).to_list(length=10_000):
            skills[str(row.get("_id"))] = row
    if cap_keys:
        for row in await db["capability_assets"].find(
            {"asset_id": {"$in": cap_keys}}
        ).to_list(length=10_000):
            caps[str(row.get("asset_id"))] = row

    effects = await _effect_summaries(db, tenant_id, skill_keys)
    # 评级按 (asset_type, asset_key) 维度区分（同一 key 可能同时是 skill 与能力资产）。
    ratings_by_type: dict[tuple[str, str], dict[str, Any]] = {}
    for asset_type, keys in (("skill", skill_keys), ("capability_asset", cap_keys)):
        ratings_by_type.update(
            {(asset_type, key): doc for key, doc in (await _rating_docs(db, tenant_id, asset_type, keys)).items()}
        )

    items: list[dict[str, Any]] = []
    for listing in listings:
        asset_type = listing.get("asset_type")
        asset_key = listing.get("asset_key")
        row = skills.get(asset_key) if asset_type == "skill" else caps.get(asset_key)
        if not row or not is_active_asset(row, asset_type):
            continue
        basic = _project_asset(
            asset_type=asset_type,
            asset_key=asset_key,
            row=row,
            rating=_rating_summary_from_rows(row, ratings_by_type.get((asset_type, asset_key))),
            effect=effects.get(asset_key) if asset_type == "skill" else None,
        )
        if l1_filter_enabled and _is_l1_asset(row, basic["rating"]):
            continue
        if category and str(listing.get("category") or "") != category:
            continue
        if keyword:
            haystack = " ".join(
                [basic["name"], basic["description"], " ".join(basic["tags"]), basic["owner"]]
            ).lower()
            if keyword not in haystack:
                continue
        items.append(
            {
                "asset_type": asset_type,
                "asset_key": asset_key,
                "name": basic["name"],
                "description": basic["description"],
                "category": str(listing.get("category") or basic["category"] or "uncategorized"),
                "owner": basic["owner"],
                "owner_role": basic["owner_role"],
                "tags": basic["tags"],
                "is_low_quality": basic["is_low_quality"],
                "effect": basic["effect"],
                "rating": basic["rating"],
                "kind": basic["kind"],
            }
        )

    total = len(items)
    start = (page - 1) * page_size
    return {
        "items": items[start : start + page_size],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


async def list_categories(tenant_id: str, db: Any = None) -> list[dict[str, Any]]:
    """目录可用的分类（来自已上架标记，去重）。"""
    db = _get_db(db)
    rows = await db[PORTAL_LISTINGS_COLLECTION].find(
        {"tenant_id": tenant_id, **_ACTIVE_LISTING_FILTER}
    ).to_list(length=10_000)
    seen: dict[str, int] = {}
    for row in rows:
        cat = str(row.get("category") or "uncategorized")
        seen[cat] = seen.get(cat, 0) + 1
    return [{"category": key, "count": count} for key, count in sorted(seen.items())]


def normalize_asset_key(raw: str) -> str:
    """规范化资产标识（去空白，防空注入）。"""
    return re.sub(r"\s+", "", str(raw or "")).strip()
