"""033-canary-rollout: Skill call-entry shadow point (影子分流点).

影子发布语义（spec 决策表 #5、FR-006/FR-007/FR-008）：
* 影子流量 = 未命中 ``traffic_ratio`` 的用户对候选版本的双跑；
* 用户响应 100% 来自稳定版，影子结果**只记录不返回**；
* 影子执行不计入 ``Rollout.call_count`` / ``error_count``，因此影子失败
  **不会**触发回滚；
* 影子执行异常/超时一律吞并并记录，绝不影响用户请求路径（fail-soft）。

本模块是 chat-api 侧**唯一**的影子分流点（plan T002 结论：挂载在
``profile/skills`` 调用入口，避免多入口重复实现）；调用方负责在拿到
稳定版结果后决定是否触发 :func:`run_shadow`，本模块只负责判定、隔离执行
与落库。分流判定与 admin-api 侧 :func:`resolve_assignment` 口径一致
（``(tenant_id, user_id)`` SHA-256 确定性哈希取模，粘滞、纯函数、无存储）。
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger(__name__)

#: 与 admin-api ``canary.TRAFFIC_BUCKETS`` 保持一致，保证两侧分流判定一致。
TRAFFIC_BUCKETS = 10000

#: 影子执行记录集合（与 admin-api ``canary.SHADOW_RUNS_COLLECTION`` 同名，
#: 两服务共用同一 MongoDB 库）。
SHADOW_RUNS_COLLECTION = "skill_shadow_runs"

#: 影子双跑超时：超时一律吞并（决策表 #9）。
DEFAULT_SHADOW_TIMEOUT_SECONDS = 30.0

#: 影子读取 admin-api 灰度配置的超时：读取失败按"无影子"处理（fail-soft）。
PLAN_FETCH_TIMEOUT_SECONDS = 3.0


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def traffic_bucket(tenant_id: str, user_id: str) -> int:
    """Deterministic hash of ``(tenant_id, user_id)`` → bucket in [0, TRAFFIC_BUCKETS)."""
    digest = hashlib.sha256(f"{tenant_id}:{user_id}".encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") % TRAFFIC_BUCKETS


def resolve_candidate(plan: dict[str, Any], *, tenant_id: str, user_id: str) -> bool:
    """Whether *this* user should be routed to the candidate (canary) version.

    ``plan`` is the admin-api rollout row (``target_tenants`` + ``traffic_ratio``
    叠加口径，spec 决策表 #2/#3）。
    """
    ratio = float(plan.get("traffic_ratio") or 1.0)
    if not 0.0 < ratio <= 1.0:
        return False
    tenants = plan.get("target_tenants") or []
    if tenants and str(tenant_id) not in {str(t) for t in tenants}:
        return False
    return traffic_bucket(str(tenant_id), str(user_id)) < max(1, round(ratio * TRAFFIC_BUCKETS))


def should_shadow(plan: dict[str, Any], *, tenant_id: str, user_id: str) -> bool:
    """Whether this user's request should trigger a shadow dual-run.

    命中 ratio 的用户已真实走候选版（直接返回，无需再影子双跑——US2 场景 4）；
    未命中且影子开启时才双跑。
    """
    if not plan.get("shadow_enabled"):
        return False
    return not resolve_candidate(plan, tenant_id=tenant_id, user_id=user_id)


async def fetch_rollout_plan(skill_id: str) -> Optional[dict[str, Any]]:
    """Read the rollout plan for ``skill_id`` from admin-api (fail-soft).

    任何异常（网络/鉴权/非 200/解析失败）都返回 ``None``，由调用方按
    "无灰度、无影子"处理——影子读取失败绝不阻断用户请求。
    """
    import httpx

    from app.core.config import get_settings

    settings = get_settings()
    base_url = str(settings.ADMIN_API_BASE_URL or "http://127.0.0.1:8100").rstrip("/")
    token = str(settings.ADMIN_BACKEND_SERVICE_TOKEN or "")
    try:
        async with httpx.AsyncClient(timeout=PLAN_FETCH_TIMEOUT_SECONDS) as client:
            response = await client.get(
                f"{base_url}/api/skills/canary/{skill_id}",
                headers={"X-Service-Token": token} if token else {},
            )
        if response.status_code != 200:
            return None
        body = response.json()
        data = (body or {}).get("data") or {}
        if not data.get("skill_id"):
            return None
        return data
    except Exception:  # noqa: BLE001 - 影子读取必须 fail-soft
        logger.warning("canary plan fetch failed (shadow disabled)", extra={"skill_id": skill_id})
        return None


async def record_shadow_run(
    db,
    *,
    skill_id: str,
    version: int,
    tenant_id: str,
    user_id: str,
    duration_ms: int,
    ok: bool,
    error: str = "",
) -> dict[str, Any]:
    """Persist one shadow observation into ``skill_shadow_runs`` (FR-008).

    只写；该记录绝不返回给用户，也绝不流入回滚判定。
    """
    doc: dict[str, Any] = {
        "skill_id": str(skill_id),
        "version": int(version),
        "tenant_id": str(tenant_id),
        "user_id": str(user_id),
        "duration_ms": int(duration_ms),
        "ok": bool(ok),
        "error": str(error or ""),
        "created_at": _utcnow_iso(),
    }
    await db[SHADOW_RUNS_COLLECTION].insert_one(doc)
    return doc


async def run_shadow(
    db,
    *,
    plan: dict[str, Any],
    tenant_id: str,
    user_id: str,
    executor: Callable[[], Awaitable[Any]],
    timeout: float = DEFAULT_SHADOW_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Execute a shadow dual-run of the candidate version, fully isolated (FR-007).

    * ``executor`` is the candidate-version runner; any exception / timeout is
      swallowed and recorded;
    * the user's own response is produced by the caller from the **stable**
      version — this function never returns a result to the user path
      (``ok=False`` on any failure);
    * the observation is persisted via :func:`record_shadow_run` and does not
      touch the rollout counters, so it can never trigger a rollback (FR-009).
    """
    started = _utcnow_iso()
    t0 = __import__("time").monotonic()
    ok = True
    error = ""
    try:
        await asyncio.wait_for(executor(), timeout=timeout)
    except asyncio.TimeoutError:
        ok, error = False, f"shadow_timeout>{timeout}s"
    except Exception as exc:  # noqa: BLE001 - 影子执行异常一律吞并
        ok, error = False, f"{type(exc).__name__}: {exc}"
    duration_ms = int((__import__("time").monotonic() - t0) * 1000)

    record = await record_shadow_run(
        db,
        skill_id=str(plan.get("skill_id") or ""),
        version=int(plan.get("version") or 0),
        tenant_id=tenant_id,
        user_id=user_id,
        duration_ms=duration_ms,
        ok=ok,
        error=error,
    )
    if not ok:
        logger.warning("shadow run failed (swallowed)", extra={"skill_id": plan.get("skill_id"), "error": error})
    return {
        "ok": ok,
        "error": error,
        "duration_ms": duration_ms,
        "started_at": started,
        "recorded": bool(record),
    }


__all__ = [
    "DEFAULT_SHADOW_TIMEOUT_SECONDS",
    "SHADOW_RUNS_COLLECTION",
    "TRAFFIC_BUCKETS",
    "fetch_rollout_plan",
    "record_shadow_run",
    "resolve_candidate",
    "run_shadow",
    "should_shadow",
    "traffic_bucket",
]