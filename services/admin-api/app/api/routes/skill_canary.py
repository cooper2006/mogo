"""Canary rollout + rollback endpoints (feature 016, extended by 033).

Production wiring with MongoDB persistence (FR-10): rollouts are stored in
the ``skill_rollouts`` collection so they survive process restarts.

033-canary-rollout 增量：创建/查询扩展 ``traffic_ratio`` / ``ladder`` /
``shadow`` 维度（FR-012）；查询返回当前档位、推进历史与影子统计；新增
``POST /{skill_id}/advance``（手动推进）与 ``POST /{skill_id}/shadow``（影子开关）；
手动一键回滚路由与语义原样保留（FR-010）。
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from app.security.service_token import ServiceTokenHeader

from app.core.db import get_db
from app.services.skill_market.canary import (
    DEFAULT_CANARY_ROLLBACK_THRESHOLD,
    DEFAULT_MIN_CANARY_SAMPLES,
    DEFAULT_SHADOW_RATIO,
    LadderStep,
    Rollout,
    advance_ladder,
    apply_rollback,
    default_ladder,
    evaluate_canary,
    fetch_shadow_stats,
    _rollout_to_row,
    _row_to_rollout,
)

COLLECTION = "skill_rollouts"


def _token_ok(token: str) -> bool:
    from app.core.config import settings
    expected = str(settings.backend_service_token or "")
    return bool(token and expected and __import__("hmac").compare_digest(token, expected))


async def _authorize(
    service_token: ServiceTokenHeader = "",
    authorization: Optional[str] = Header(default=None),
) -> None:
    """Require a valid intra-service token (016 契约) **or** a live admin session.

    033 增量（FR-013）：admin-web 灰度配置页以登录管理员身份调用本路由，因此除
    intra-service token 外也接受有效的 admin 会话令牌；chat-api → admin-api 的
    服务调用路径不受影响（服务 token 校验优先，未提供时才回退到 admin 会话）。
    """
    if _token_ok(service_token):
        return
    if authorization and authorization.startswith("Bearer "):
        # 复用既有 admin 会话校验（租户作用域），仅用于 UI 调用路径。
        from app.api.deps import _load_authenticated_account
        try:
            await _load_authenticated_account(authorization)
            return
        except HTTPException:
            pass
    raise HTTPException(status_code=401, detail="invalid_service_token")


# 025 T035：prefix 曾误写 "/api/skills/canary"，叠加 api_router 的 "/api" 前缀后
# 实际路由为 "/api/api/skills/canary/*"，与前端调用不符。改为 "/skills/canary"。
router = APIRouter(
    prefix="/skills/canary",
    tags=["skill-canary"],
    dependencies=[Depends(_authorize)],
)


def _parse_ladder(raw: Any, default_ratio: float) -> list[LadderStep]:
    """Parse an optional ``ladder`` payload into :class:`LadderStep` list.

    Empty payload → the default ladder; otherwise each rung must expose a
    ``ratio`` in (0, 1]. A single ``traffic_ratio`` with no ladder still uses
    the default ladder (the ladder governs auto-advance only).
    """
    if not raw:
        return default_ladder()
    steps: list[LadderStep] = []
    for item in raw:
        if not isinstance(item, dict) or "ratio" not in item:
            raise HTTPException(status_code=400, detail="invalid_ladder_step")
        ratio = float(item["ratio"])
        if not 0.0 < ratio <= 1.0:
            raise HTTPException(status_code=400, detail="invalid_traffic_ratio")
        steps.append(
            LadderStep(
                ratio=ratio,
                min_samples=int(item["min_samples"]) if item.get("min_samples") else None,
            )
        )
    if not steps:
        return default_ladder()
    if steps[-1].ratio < 1.0:
        steps.append(LadderStep(ratio=1.0))
    for prev, curr in zip(steps, steps[1:]):
        if curr.ratio < prev.ratio:
            raise HTTPException(status_code=400, detail="ladder_ratio_not_ascending")
    return steps


def _parse_ratio(raw: Any) -> float:
    """Validate and return a ``traffic_ratio`` in (0, 1] (edge case: ratio 非法值)."""
    try:
        ratio = float(raw)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="invalid_traffic_ratio")
    if not 0.0 < ratio <= 1.0:
        raise HTTPException(status_code=400, detail="invalid_traffic_ratio")
    return round(ratio, 4)


@router.post("")
async def create_rollout(
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Start a canary rollout for a Skill version (FR-4, FR-10 persistence).

    033 增量（FR-001/FR-012）：payload 额外接受 ``traffic_ratio``（默认 1.0，
    0 < ratio ≤ 1）、``ladder``（阶梯档位，默认 1%→10%→50%→100%）、
    ``shadow_enabled``（影子模式开关，默认 False）；既有 ``target_tenants``
    语义不变（决策表第 2 条：tenants 与 ratio 叠加）。
    """

    skill_id = str(payload.get("skill_id") or "").strip()
    version = int(payload.get("version") or 0)
    stable_version = int(payload.get("stable_version") or 0)
    target_tenants = [str(t) for t in payload.get("target_tenants") or []]

    if not skill_id or version <= 0:
        raise HTTPException(status_code=400, detail="skill_id and version required")

    traffic_ratio = _parse_ratio(payload.get("traffic_ratio", 1.0))
    ladder = _parse_ladder(payload.get("ladder"), traffic_ratio)
    shadow_enabled = bool(payload.get("shadow_enabled") or False)
    current_step = max(
        0,
        min(int(payload.get("current_step") or 0), len(ladder) - 1),
    )

    rollout = Rollout(
        skill_id=skill_id,
        version=version,
        stable_version=stable_version,
        target_tenants=target_tenants,
        traffic_ratio=traffic_ratio,
        ladder=ladder,
        current_step=current_step,
        shadow_enabled=shadow_enabled,
    )
    db = get_db()
    await db[COLLECTION].replace_one(
        {"skill_id": skill_id},
        _rollout_to_row(rollout),
        upsert=True,
    )
    return {
        "code": 0,
        "message": "rollout_started",
        "data": {
            "skill_id": skill_id,
            "version": version,
            "stable_version": stable_version,
            "target_tenants": target_tenants,
            "state": rollout.state,
            "traffic_ratio": rollout.traffic_ratio,
            "ladder": [step.to_dict() for step in rollout.ladder],
            "current_step": rollout.current_step,
            "shadow_enabled": rollout.shadow_enabled,
        },
    }


@router.post("/{skill_id}/record")
async def record_rollout_calls(
    skill_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Record call/error counts for a canary rollout (FR-4 / FR-5)."""

    db = get_db()
    row = await db[COLLECTION].find_one({"skill_id": skill_id})
    if row is None:
        raise HTTPException(status_code=404, detail="rollout_not_found")

    rollout = _row_to_rollout(row)
    calls = int(payload.get("calls") or 0)
    errors = int(payload.get("errors") or 0)
    rollout.record_calls(calls=calls, errors=errors)
    await db[COLLECTION].replace_one(
        {"skill_id": skill_id},
        _rollout_to_row(rollout),
    )
    return {
        "code": 0,
        "message": "recorded",
        "data": {
            "skill_id": skill_id,
            "call_count": rollout.call_count,
            "error_count": rollout.error_count,
            "error_rate": round(rollout.error_rate(), 4),
            "state": rollout.state,
        },
    }


@router.get("/{skill_id}")
async def evaluate_rollout(
    skill_id: str,
    threshold: Optional[float] = None,
    min_samples: Optional[int] = None,
) -> dict[str, Any]:
    """Evaluate canary health and decide rollback (FR-5).

    033 增量（FR-012）：查询同时返回当前档位、推进历史与影子统计，
    供 admin-web 灰度配置页展示（US4）。
    """

    db = get_db()
    row = await db[COLLECTION].find_one({"skill_id": skill_id})
    if row is None:
        raise HTTPException(status_code=404, detail="rollout_not_found")

    rollout = _row_to_rollout(row)
    decision = evaluate_canary(
        rollout,
        threshold=float(threshold or DEFAULT_CANARY_ROLLBACK_THRESHOLD),
        min_samples=int(min_samples or DEFAULT_MIN_CANARY_SAMPLES),
    )
    shadow_stats = await fetch_shadow_stats(db, skill_id=skill_id, version=rollout.version)
    return {
        "code": 0,
        "message": "evaluated",
        "data": {
            "skill_id": skill_id,
            "state": decision.state,
            "error_rate": round(decision.error_rate, 4),
            "should_rollback": decision.should_rollback,
            "reason": decision.reason,
            "sample_sufficient": decision.sample_sufficient,
            "traffic_ratio": rollout.traffic_ratio,
            "current_step": rollout.current_step,
            "ladder": [step.to_dict() for step in rollout.ladder],
            "ladder_history": rollout.ladder_history,
            "shadow_enabled": rollout.shadow_enabled,
            "shadow_stats": shadow_stats,
        },
    }


@router.post("/{skill_id}/advance")
async def advance_rollout(
    skill_id: str,
    min_samples: Optional[int] = None,
) -> dict[str, Any]:
    """Manually evaluate and advance the traffic ladder (033 FR-004 / decision #4).

    保留手动推进：与 5 分钟扫描循环同一套推进条件（样本 ≥ min_samples 且
    异常率 ≤ threshold），但由运营者显式触发。
    """

    db = get_db()
    row = await db[COLLECTION].find_one({"skill_id": skill_id})
    if row is None:
        raise HTTPException(status_code=404, detail="rollout_not_found")

    rollout = _row_to_rollout(row)
    decision = advance_ladder(
        rollout,
        min_samples=int(min_samples or DEFAULT_MIN_CANARY_SAMPLES),
        threshold=DEFAULT_CANARY_ROLLBACK_THRESHOLD,
    )
    if decision.advanced:
        await db[COLLECTION].replace_one(
            {"skill_id": skill_id},
            _rollout_to_row(rollout),
        )
    return {
        "code": 0,
        "message": "promote" if decision.promoted else ("advanced" if decision.advanced else "held"),
        "data": {
            "skill_id": skill_id,
            "advanced": decision.advanced,
            "promoted": decision.promoted,
            "current_step": decision.current_step,
            "traffic_ratio": decision.traffic_ratio,
            "state": rollout.state,
            "reason": decision.reason,
            "min_samples_required": decision.min_samples_required,
        },
    }


@router.post("/{skill_id}/shadow")
async def toggle_shadow(
    skill_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Enable / disable shadow mode for a rollout (033 FR-006, US4 影子开关).

    影子开启后，未命中 ``traffic_ratio`` 的用户在获得稳定版响应的同时，
    chat-api 会对其请求双跑候选版本并只记录到 ``skill_shadow_runs``。
    """

    db = get_db()
    row = await db[COLLECTION].find_one({"skill_id": skill_id})
    if row is None:
        raise HTTPException(status_code=404, detail="rollout_not_found")

    rollout = _row_to_rollout(row)
    requested = payload.get("enabled", True)
    if isinstance(requested, str):
        requested = requested.strip().lower() in {"1", "true", "yes", "on"}
    rollout.shadow_enabled = bool(requested)
    await db[COLLECTION].replace_one(
        {"skill_id": skill_id},
        _rollout_to_row(rollout),
    )
    return {
        "code": 0,
        "message": "shadow_updated",
        "data": {
            "skill_id": skill_id,
            "shadow_enabled": rollout.shadow_enabled,
            "default_shadow_ratio": DEFAULT_SHADOW_RATIO,
        },
    }


@router.post("/{skill_id}/rollback")
async def do_rollback(
    skill_id: str,
) -> dict[str, Any]:
    """Manually trigger rollback for a canary rollout (FR-11)."""

    db = get_db()
    row = await db[COLLECTION].find_one({"skill_id": skill_id})
    if row is None:
        raise HTTPException(status_code=404, detail="rollout_not_found")

    rollout = _row_to_rollout(row)
    decision = evaluate_canary(rollout)
    result = apply_rollback(rollout, decision)
    # Persist the updated state.
    await db[COLLECTION].replace_one(
        {"skill_id": skill_id},
        _rollout_to_row(rollout),
    )
    if not result:
        return {"code": 0, "message": "no_rollback_needed", "data": {
            "skill_id": skill_id,
            "state": rollout.state,
            "error_rate": round(rollout.error_rate(), 4),
        }}
    return {
        "code": 0,
        "message": "rollback_applied",
        "data": result,
    }


__all__ = ["router"]
