"""036 trust rating (L1-L4) — pure logic + persistence.

An *asset* (``skill`` / ``agent`` / ``workflow``) carries a single asset-level
trust rating (spec 已定决策 #5). Ratings are stored in ``trust_ratings`` keyed by
``(tenant_id, asset_type, asset_key)`` (软键关联, spec 已定决策 #6) and are the
input to two downstream policies:

* FR-8   —— the gate approval layer caps the effective autonomy level by the
  rating (``effective_level = min(autonomy_level, cap(trust_level))``);
* FR-9   —— L4 assets doing a write at risk >= R2 require *two* distinct human
  approvers (see :mod:`app.governance.layers.approval`).

Ratings move only through :func:`record_change`, which atomically writes the new
level and appends a ``before/after`` audit record to the 022 chain (FR-6).

Quality signal (FR-17) is consumed, never written, from two upstream features:

* 032 ``skill_eval_runs`` (preferred, per the agreed contract);
* 016 ``skill_quality_metrics`` (fallback while 032 has < ``MIN_EVAL_RUNS``).

This module owns no scanner; see :mod:`downgrade_scanner` for the periodic driver.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from app.services.eval_gate import RUNS_COLLECTION  # 032 contract (read-only)
from app.services.skill_market.quality_metrics import (
    MIN_EFFECT_SAMPLES,
    QUALITY_METRICS_COLLECTION,
)
from app.services.skill_market.scoring import LOW_QUALITY_THRESHOLD, compute_effect_score
from app.system_audit.repository import SystemAuditRepository

# --- levels / policy -------------------------------------------------------

#: Asset trust levels, low -> high.
TRUST_LEVELS: tuple[str, ...] = ("L1", "L2", "L3", "L4")

#: An asset with no rating yet starts here (已定决策 #1).
DEFAULT_TRUST_LEVEL = "L1"

#: Asset kinds a rating can be attached to (已定决策 #5).
ASSET_TYPES: tuple[str, ...] = ("skill", "agent", "workflow")

#: Autonomy levels the gate recognizes (001) — needed for ``min``.
_AUTONOMY_ORDER: tuple[str, ...] = ("L1", "L2", "L3", "L4", "L5")
_RISK_ORDER: tuple[str, ...] = ("R0", "R1", "R2", "R3", "R4")

#: Canonical rating -> max autonomy level (已定决策 #7). Tenant-level overrides
#: live in ``trust_autonomy_caps`` (see :func:`trust_caps_for_tenant`).
TRUST_TO_AUTONOMY_CAP: dict[str, str] = {"L1": "L1", "L2": "L2", "L3": "L3", "L4": "L5"}

#: Risk >= R2 at which an L4 write needs a second approver (FR-9).
L4_TWO_APPROVER_MIN_RISK = "R2"

# --- collections -----------------------------------------------------------

RATINGS_COLLECTION = "trust_ratings"
CAPS_COLLECTION = "trust_autonomy_caps"
SETTINGS_COLLECTION = "trust_rating_settings"
SCAN_STATE_COLLECTION = "trust_rating_scan_state"

#: The single scan-state document id (mirrors 016 ``_COLLECTOR_STATE_ID``).
SCAN_STATE_ID = "downgrade"

# --- downgrade policy (FR-10 / FR-11) --------------------------------------

#: Consecutive non-passing days before an automatic downgrade.
DEFAULT_DOWNGRADE_WINDOW_DAYS = 21

#: Tenant-level switch, on by default (spec 已定决策 #3).
DEFAULT_DOWNGRADE_ENABLED = True

#: Scanner cadence (mirrors 016 ``DEFAULT_INTERVAL_SECONDS``).
DEFAULT_SCAN_INTERVAL_SECONDS = 6 * 3600.0

#: Minimum 032 runs inside the window before a verdict is trusted (spec edge case).
MIN_EVAL_RUNS = 20

#: Minimum share of passing 032 runs that counts as "passing".
EVAL_PASS_RATE_THRESHOLD = 0.8

#: Minimum 016 calls inside the window (mirrors 016 ``MIN_EFFECT_SAMPLES``).
MIN_QUALITY_SAMPLES = MIN_EFFECT_SAMPLES

#: 016 fallback window in days.
QUALITY_FALLBACK_WINDOW_DAYS = 7

#: Permission codes (FR-4, fail-closed).
TRUST_READ = "trust:read"
TRUST_MANAGE = "trust:manage"

#: Reasons accepted by :func:`record_change`.
CHANGE_REASONS: tuple[str, ...] = (
    "manual_promote",
    "manual_demote",
    "auto_downgrade",
    "reset_streak",
    "deprecate_requested",
)


# --- pure helpers ----------------------------------------------------------

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _utc_today() -> date:
    return _utcnow().date()


def _as_dt(value: Any) -> Optional[datetime]:
    """Normalise an ISO string or datetime to a tz-aware datetime (UTC)."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str) and value:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _level_index(level: str) -> int:
    try:
        return TRUST_LEVELS.index(str(level or ""))
    except ValueError:
        raise ValueError(f"invalid trust level: {level!r} (expected one of {TRUST_LEVELS})") from None


def _autonomy_index(level: str) -> int:
    level = str(level or "")
    return _AUTONOMY_ORDER.index(level) if level in _AUTONOMY_ORDER else _AUTONOMY_ORDER.index("L1")


def _min_autonomy(a: str, b: str) -> str:
    return _AUTONOMY_ORDER[min(_autonomy_index(a), _autonomy_index(b))]


def autonomy_cap_for(trust_level: Optional[str]) -> str:
    """Max autonomy level allowed for a trust level (fail-closed).

    An unknown or missing rating maps to ``L1`` — a caller must never be able to
    opt out of the cap by omitting the rating.
    """
    level = str(trust_level or "")
    return TRUST_TO_AUTONOMY_CAP.get(level, TRUST_TO_AUTONOMY_CAP[DEFAULT_TRUST_LEVEL])


def apply_trust_cap(
    autonomy_level: str,
    trust_level: Optional[str],
    caps: Optional[dict[str, str]] = None,
) -> str:
    """``effective = min(autonomy_level, cap(trust_level))`` (FR-8).

    ``caps`` may carry a tenant override; a value missing from ``caps`` falls back
    to the canonical :data:`TRUST_TO_AUTONOMY_CAP`. R4 red lines are unaffected —
    this only lowers the *autonomy* cell the gate consults.
    """
    effective_caps: dict[str, str] = {**TRUST_TO_AUTONOMY_CAP, **(caps or {})}
    level = str(trust_level or "")
    if level not in TRUST_LEVELS:
        return _min_autonomy(str(autonomy_level or DEFAULT_TRUST_LEVEL), TRUST_TO_AUTONOMY_CAP[DEFAULT_TRUST_LEVEL])
    cap = effective_caps.get(level, TRUST_TO_AUTONOMY_CAP[DEFAULT_TRUST_LEVEL])
    return _min_autonomy(str(autonomy_level or DEFAULT_TRUST_LEVEL), cap)


def required_approvals_for(effective_autonomy_level: str, risk_level: str) -> int:
    """Number of distinct human approvers a ticket needs (FR-9).

    An L4 write at risk >= R2 needs two; everything else keeps the historical
    single-approver path, so 001 behaviour is unchanged for non-L4 traffic.
    """
    if str(effective_autonomy_level or "") != "L4":
        return 1
    risk = str(risk_level or "")
    if risk in _RISK_ORDER and _RISK_ORDER.index(risk) >= _RISK_ORDER.index(L4_TWO_APPROVER_MIN_RISK):
        return 2
    return 1


def next_higher_level(level: str) -> Optional[str]:
    index = _level_index(level)
    return TRUST_LEVELS[index + 1] if index + 1 < len(TRUST_LEVELS) else None


def next_lower_level(level: str) -> Optional[str]:
    index = _level_index(level)
    return TRUST_LEVELS[index - 1] if index > 0 else None


def validate_asset(asset_type: str, asset_key: str) -> tuple[str, str]:
    """Validate and normalise an asset identity (spec edge case: 载体异构)."""
    asset_type = str(asset_type or "").strip().lower()
    if asset_type not in ASSET_TYPES:
        raise ValueError(f"unsupported asset_type: {asset_type!r} (expected one of {ASSET_TYPES})")
    asset_key = str(asset_key or "").strip()
    if not asset_key:
        raise ValueError("asset_key must not be empty")
    return asset_type, asset_key


def rating_key(tenant_id: str, asset_type: str, asset_key: str) -> dict[str, str]:
    return {
        "tenant_id": str(tenant_id or ""),
        "asset_type": str(asset_type),
        "asset_key": str(asset_key),
    }


def compute_streak(below_since: Optional[str], now: Optional[date] = None) -> int:
    """Consecutive non-passing calendar days ending today (0 when no streak)."""
    if not below_since:
        return 0
    start = _as_dt(below_since)
    if start is None:
        return 0
    today = now or _utc_today()
    return (today - start.date()).days + 1


def next_downgrade_action(
    *,
    level: str,
    passing: bool,
    below_since: Optional[str],
    now: Optional[date] = None,
    window_days: int = DEFAULT_DOWNGRADE_WINDOW_DAYS,
) -> dict[str, Any]:
    """Decide what a scan should do with a rating (FR-10 / FR-11, pure).

    Returns ``action`` in ``{reset_streak, none, downgrade, deprecate}``. The
    streak is measured in *calendar* days so a 6-hourly scan can never
    double-count a single day.
    """
    today = now or _utc_today()
    window = int(window_days)
    if passing:
        return {"action": "reset_streak", "below_since": None, "below_streak_days": 0}
    streak = compute_streak(below_since, today)
    if streak < window:
        return {"action": "none", "below_since": below_since, "below_streak_days": streak}
    lower = next_lower_level(str(level))
    if lower is None:
        # Already L1 and still failing -> deprecation intent (FR-11).
        return {"action": "deprecate", "below_since": below_since, "below_streak_days": streak}
    return {
        "action": "downgrade",
        "target_level": lower,
        "below_since": None,
        "below_streak_days": 0,
    }


# --- quality signal (FR-17: 032 preferred, 016 fallback) -------------------

async def _eval_032_signal(
    db: Any,
    *,
    tenant_id: str,
    skill_id: str,
    window_days: int,
    today: date,
) -> dict[str, Any]:
    rows = (
        await db[RUNS_COLLECTION]
        .find({"tenant_id": tenant_id, "skill_id": skill_id})
        .to_list(length=500)
    )
    cutoff = today - timedelta(days=int(window_days) - 1)
    in_window: list[dict[str, Any]] = []
    for row in rows:
        dt = _as_dt(row.get("created_at"))
        if dt is None:
            continue
        day = dt.date()
        if cutoff <= day <= today:
            in_window.append(row)
    if len(in_window) < MIN_EVAL_RUNS:
        return {"source": "032", "available": False, "runs": len(in_window), "reason": "insufficient_runs"}
    passing = sum(1 for row in in_window if bool(row.get("passed")))
    pass_rate = passing / len(in_window)
    return {
        "source": "032",
        "available": True,
        "runs": len(in_window),
        "passing_runs": passing,
        "pass_rate": round(pass_rate, 4),
        "passing": pass_rate >= EVAL_PASS_RATE_THRESHOLD,
    }


async def _eval_016_signal(
    db: Any,
    *,
    tenant_id: str,
    skill_id: str,
    days: int,
    today: date,
) -> dict[str, Any]:
    start = (today - timedelta(days=int(days) - 1)).isoformat()
    rows = (
        await db[QUALITY_METRICS_COLLECTION]
        .find({"tenant_id": tenant_id, "skill_key": skill_id, "date": {"$gte": start, "$lte": today.isoformat()}})
        .to_list(length=days + 1)
    )
    totals = {"total_calls": 0, "successful_calls": 0, "adopted_calls": 0, "corrected_calls": 0}
    success_tracked = False
    for row in rows:
        for key in totals:
            totals[key] += int(row.get(key) or 0)
        success_tracked = success_tracked or bool(row.get("success_tracked"))
    if totals["total_calls"] < MIN_QUALITY_SAMPLES or not success_tracked:
        return {
            "source": "016",
            "available": False,
            "total_calls": totals["total_calls"],
            "reason": "insufficient_signal",
        }
    score = compute_effect_score(
        total_calls=totals["total_calls"],
        successful_calls=totals["successful_calls"],
        adopted_calls=totals["adopted_calls"],
        corrected_calls=totals["corrected_calls"],
    ).score
    return {
        "source": "016",
        "available": True,
        "total_calls": totals["total_calls"],
        "effect_score": round(score, 4),
        "passing": score >= LOW_QUALITY_THRESHOLD,
    }


async def resolve_quality_signal(
    db: Any,
    *,
    tenant_id: str,
    skill_id: str,
    window_days: int = DEFAULT_DOWNGRADE_WINDOW_DAYS,
    as_of: Optional[date] = None,
) -> dict[str, Any]:
    """Best available quality verdict for a skill (032 -> 016 -> insufficient)."""
    today = as_of or _utc_today()
    if db is None:
        return {"source": "none", "available": False, "reason": "no_db"}
    signal = await _eval_032_signal(db, tenant_id=tenant_id, skill_id=skill_id, window_days=window_days, today=today)
    if signal.get("available"):
        return signal
    signal = await _eval_016_signal(
        db,
        tenant_id=tenant_id,
        skill_id=skill_id,
        days=QUALITY_FALLBACK_WINDOW_DAYS,
        today=today,
    )
    if signal.get("available"):
        return signal
    return {"source": "none", "available": False, "reason": "insufficient_signal", "032": signal, "016": signal}


# --- settings / caps -------------------------------------------------------

async def get_downgrade_settings(db: Any, tenant_id: str) -> dict[str, Any]:
    doc = await db[SETTINGS_COLLECTION].find_one({"_id": str(tenant_id or "default")})
    if not doc:
        return {
            "enabled": DEFAULT_DOWNGRADE_ENABLED,
            "window_days": DEFAULT_DOWNGRADE_WINDOW_DAYS,
            "interval_seconds": DEFAULT_SCAN_INTERVAL_SECONDS,
        }
    return {
        "enabled": bool(doc.get("enabled", DEFAULT_DOWNGRADE_ENABLED)),
        "window_days": int(doc.get("window_days") or DEFAULT_DOWNGRADE_WINDOW_DAYS),
        "interval_seconds": float(doc.get("interval_seconds") or DEFAULT_SCAN_INTERVAL_SECONDS),
    }


async def update_downgrade_settings(
    db: Any,
    tenant_id: str,
    *,
    enabled: Optional[bool] = None,
    window_days: Optional[int] = None,
    actor: str = "",
) -> dict[str, Any]:
    """Persist a tenant's downgrade switch (FR-10). Closing the switch keeps any
    existing ``below_since`` intact, so accumulated days survive re-enabling."""
    current = await get_downgrade_settings(db, tenant_id)
    if window_days is not None:
        if int(window_days) < 1:
            raise ValueError("window_days must be >= 1")
        current["window_days"] = int(window_days)
    if enabled is not None:
        current["enabled"] = bool(enabled)
    doc = {
        "_id": str(tenant_id or "default"),
        "enabled": current["enabled"],
        "window_days": current["window_days"],
        "interval_seconds": current["interval_seconds"],
        "updated_by": str(actor or ""),
        "updated_at": _utcnow(),
    }
    await db[SETTINGS_COLLECTION].update_one({"_id": doc["_id"]}, {"$set": doc}, upsert=True)
    await _audit(
        db,
        {
            "tenant_id": str(tenant_id or ""),
            "action": "trust.settings.updated",
            "actor": str(actor or ""),
            "result": "success",
            "detail": {"enabled": current["enabled"], "window_days": current["window_days"]},
        },
    )
    return current


async def trust_caps_for_tenant(db: Any, tenant_id: str) -> dict[str, str]:
    """Canonical rating->cap map merged with the tenant override (已定决策 #7).

    An override value outside the autonomy ladder is dropped (fail-closed), never
    silently applied.
    """
    caps: dict[str, str] = dict(TRUST_TO_AUTONOMY_CAP)
    if db is None:
        return caps
    doc = await db[CAPS_COLLECTION].find_one({"_id": str(tenant_id or "default")})
    overrides = doc.get("caps") if doc else None
    if isinstance(overrides, dict):
        for key, value in overrides.items():
            if str(key) in TRUST_LEVELS and str(value) in _AUTONOMY_ORDER:
                caps[str(key)] = str(value)
    return caps


# --- ratings persistence ---------------------------------------------------

def _default_evidence(reason: str) -> dict[str, Any]:
    return {"source": "manual", "reason": reason}


async def _audit(db: Any, record: dict[str, Any]) -> None:
    """Best-effort append to the 022 audit chain (FR-6). A failure is logged, never raised."""
    if db is None:
        return
    try:
        await SystemAuditRepository(db=db).record_management_operation(record)
    except Exception:  # pragma: no cover - best-effort audit
        import logging

        logging.getLogger(__name__).warning("trust_rating audit write failed", exc_info=True)


async def ensure_rating(
    db: Any,
    *,
    tenant_id: str,
    asset_type: str,
    asset_key: str,
    owner_id: str = "",
    created_by: str = "",
) -> dict[str, Any]:
    """Return the existing rating, or create a default L1 (FR: 新资产默认 L1)."""
    asset_type, asset_key = validate_asset(asset_type, asset_key)
    key = rating_key(tenant_id, asset_type, asset_key)
    existing = await db[RATINGS_COLLECTION].find_one(key)
    if existing is not None:
        return existing
    document = {
        **key,
        "level": DEFAULT_TRUST_LEVEL,
        "previous_level": None,
        "below_since": None,
        "below_streak_days": 0,
        "reason": "initial",
        "last_evidence": _default_evidence("initial"),
        "owner_id": str(owner_id or ""),
        "created_by": str(created_by or ""),
        "updated_by": str(created_by or ""),
        "deprecate_pending": False,
        "created_at": _utcnow(),
        "updated_at": _utcnow(),
    }
    await db[RATINGS_COLLECTION].insert_one(document)
    await _audit(
        db,
        {
            "tenant_id": str(tenant_id),
            "module": "trust_rating",
            "action": "trust.create",
            "actor": str(created_by or ""),
            "before": None,
            "after": {"level": DEFAULT_TRUST_LEVEL},
            "reason": "initial",
            "evidence": _default_evidence("initial"),
            "result": "success",
        },
    )
    return document


async def get_rating(db: Any, *, tenant_id: str, asset_type: str, asset_key: str) -> Optional[dict[str, Any]]:
    asset_type, asset_key = validate_asset(asset_type, asset_key)
    return await db[RATINGS_COLLECTION].find_one(rating_key(tenant_id, asset_type, asset_key))


async def list_ratings(
    db: Any,
    *,
    tenant_id: str,
    asset_type: Optional[str] = None,
    visible_to: str = "",
) -> list[dict[str, Any]]:
    """List a tenant's ratings.

    FR-14: an L1 rating is visible only to its creator/owner, so catalogue/market
    listings never leak unvetted L1 assets to unrelated callers.
    """
    tenant_id = str(tenant_id or "")
    if asset_type:
        asset_type = str(asset_type).strip().lower()
        if asset_type not in ASSET_TYPES:
            raise ValueError(f"unsupported asset_type: {asset_type!r} (expected one of {ASSET_TYPES})")
    flt: dict[str, Any] = {"tenant_id": tenant_id}
    if asset_type:
        flt["asset_type"] = asset_type
    rows = await db[RATINGS_COLLECTION].find(flt).to_list(length=10000)
    viewer = str(visible_to or "")
    if not viewer:
        return rows
    visible: list[dict[str, Any]] = []
    for row in rows:
        if row.get("level") != DEFAULT_TRUST_LEVEL:
            visible.append(row)
            continue
        if viewer in {str(row.get("owner_id") or ""), str(row.get("created_by") or "")}:
            visible.append(row)
    return visible


async def record_change(
    db: Any,
    *,
    tenant_id: str,
    asset_type: str,
    asset_key: str,
    target_level: str,
    reason: str,
    evidence: Optional[dict[str, Any]] = None,
    actor: str = "",
) -> dict[str, Any]:
    """Move a rating to ``target_level`` and audit it (FR-6).

    Transitions are single-step: ``target_level`` must be the current level, its
    successor, or its predecessor. Promoting into L3/L4 requires quality evidence
    (FR / 已定决策 #2) — without ``evidence.quality_passed`` the call is refused.
    """
    if reason not in CHANGE_REASONS:
        raise ValueError(f"unsupported change reason: {reason!r} (expected one of {CHANGE_REASONS})")
    asset_type, asset_key = validate_asset(asset_type, asset_key)
    target_level = str(target_level or "")
    _level_index(target_level)  # validates
    document = await db[RATINGS_COLLECTION].find_one(rating_key(tenant_id, asset_type, asset_key))
    if document is None:
        document = await ensure_rating(db, tenant_id=tenant_id, asset_type=asset_type, asset_key=asset_key, created_by=actor)

    current = str(document.get("level") or DEFAULT_TRUST_LEVEL)
    allowed = {current, next_higher_level(current), next_lower_level(current)}
    if target_level not in allowed:
        raise ValueError(
            f"invalid transition {current} -> {target_level}; only single-step changes are allowed"
        )

    promoting = _level_index(target_level) > _level_index(current)
    if promoting and _level_index(target_level) >= _level_index("L3"):
        passed = bool((evidence or {}).get("quality_passed"))
        if not passed:
            raise ValueError(f"promoting to {target_level} requires quality evidence (evidence.quality_passed)")

    below_since = document.get("below_since")
    below_streak_days = int(document.get("below_streak_days") or 0)
    if promoting:
        below_since = None
        below_streak_days = 0

    previous = current
    key = rating_key(tenant_id, asset_type, asset_key)
    patch = {
        "level": target_level,
        "previous_level": previous,
        "below_since": below_since,
        "below_streak_days": below_streak_days,
        "reason": reason,
        "last_evidence": dict(evidence) if evidence else _default_evidence(reason),
        "updated_by": str(actor or ""),
        "updated_at": _utcnow(),
    }
    await db[RATINGS_COLLECTION].update_one(key, {"$set": patch})
    updated = {**document, **patch}
    await _audit(
        db,
        {
            "tenant_id": str(tenant_id),
            "module": "trust_rating",
            "action": "trust.change",
            "actor": str(actor or ""),
            "before": {"level": previous},
            "after": {"level": target_level},
            "reason": reason,
            "evidence": patch["last_evidence"],
            "result": "success",
        },
    )
    return updated


async def recompute_rating(
    db: Any,
    *,
    tenant_id: str,
    asset_type: str,
    asset_key: str,
    actor: str = "",
    as_of: Optional[date] = None,
) -> dict[str, Any]:
    """Manual/periodic re-evaluation of a single rating (FR-10 / FR-11).

    Reads the quality signal, applies :func:`next_downgrade_action` and persists
    the outcome (downgrade, deprecation intent, streak reset, or a mere streak
    bump). Never raises for a missing asset — the rating is simply ensured first.
    """
    document = await get_rating(db, tenant_id=tenant_id, asset_type=asset_type, asset_key=asset_key)
    if document is None:
        document = await ensure_rating(db, tenant_id=tenant_id, asset_type=asset_type, asset_key=asset_key, created_by=actor)

    settings = await get_downgrade_settings(db, tenant_id)
    if not bool(settings["enabled"]):
        # FR-10: 租户开关关闭时自动降级不触发（现有 below_since 保留）。
        return {"rating": document, "signal": {"source": "disabled"}, "action": "skipped_disabled", "decision": {}}
    signal = await resolve_quality_signal(
        db,
        tenant_id=tenant_id,
        skill_id=str(document.get("asset_key")),
        window_days=int(settings["window_days"]),
        as_of=as_of,
    )
    passing = bool(signal.get("passing")) if signal.get("available") else True
    decision = next_downgrade_action(
        level=str(document.get("level") or DEFAULT_TRUST_LEVEL),
        passing=passing,
        below_since=document.get("below_since"),
        now=as_of,
        window_days=int(settings["window_days"]),
    )
    action = decision["action"]
    if action == "downgrade":
        updated = await record_change(
            db,
            tenant_id=tenant_id,
            asset_type=asset_type,
            asset_key=asset_key,
            target_level=decision["target_level"],
            reason="auto_downgrade",
            evidence={**signal, "quality_passed": False},
            actor=actor,
        )
    elif action == "deprecate":
        await db[RATINGS_COLLECTION].update_one(
            rating_key(tenant_id, asset_type, asset_key), {"$set": {"deprecate_pending": True, "updated_at": _utcnow()}}
        )
        await _audit(
            db,
            {
                "tenant_id": str(tenant_id),
                "module": "trust_rating",
                "action": "trust.deprecate_requested",
                "actor": str(actor or ""),
                "before": {"level": str(document.get("level"))},
                "after": {"deprecate_pending": True},
                "reason": "deprecate_requested",
                "evidence": signal,
                "result": "success",
            },
        )
        updated = await get_rating(db, tenant_id=tenant_id, asset_type=asset_type, asset_key=asset_key)
        if updated is None:
            updated = {**document, "deprecate_pending": True}
    elif action == "reset_streak":
        await db[RATINGS_COLLECTION].update_one(
            rating_key(tenant_id, asset_type, asset_key),
            {"$set": {"below_since": None, "below_streak_days": 0, "updated_at": _utcnow()}},
        )
        updated = await get_rating(db, tenant_id=tenant_id, asset_type=asset_type, asset_key=asset_key) or document
    else:
        if decision["below_since"]:
            await db[RATINGS_COLLECTION].update_one(
                rating_key(tenant_id, asset_type, asset_key),
                {"$set": {"below_streak_days": decision["below_streak_days"], "updated_at": _utcnow()}},
            )
        updated = await get_rating(db, tenant_id=tenant_id, asset_type=asset_type, asset_key=asset_key) or document
    return {"rating": updated, "signal": signal, "action": action, "decision": decision}


async def rating_distribution(db: Any, *, tenant_id: str) -> dict[str, int]:
    """FR-16: rating counts for the 008 dashboard."""
    counts = {level: 0 for level in TRUST_LEVELS}
    rows = await db[RATINGS_COLLECTION].find({"tenant_id": str(tenant_id or "")}).to_list(length=100000)
    for row in rows:
        level = str(row.get("level") or "")
        counts[level] = counts.get(level, 0) + 1
    return counts


async def ensure_indexes(db: Any) -> None:
    await db[RATINGS_COLLECTION].create_index(
        [("tenant_id", 1), ("asset_type", 1), ("asset_key", 1)],
        unique=True,
        name="trust_ratings_unique",
    )
    await db[RATINGS_COLLECTION].create_index(
        [("tenant_id", 1), ("asset_type", 1), ("level", 1)], name="trust_ratings_tenant_asset_level"
    )


__all__ = [
    "TRUST_LEVELS",
    "DEFAULT_TRUST_LEVEL",
    "ASSET_TYPES",
    "TRUST_TO_AUTONOMY_CAP",
    "RATINGS_COLLECTION",
    "CAPS_COLLECTION",
    "SETTINGS_COLLECTION",
    "SCAN_STATE_COLLECTION",
    "DEFAULT_DOWNGRADE_WINDOW_DAYS",
    "DEFAULT_DOWNGRADE_ENABLED",
    "DEFAULT_SCAN_INTERVAL_SECONDS",
    "MIN_EVAL_RUNS",
    "EVAL_PASS_RATE_THRESHOLD",
    "TRUST_READ",
    "TRUST_MANAGE",
    "CHANGE_REASONS",
    "autonomy_cap_for",
    "apply_trust_cap",
    "required_approvals_for",
    "next_higher_level",
    "next_lower_level",
    "validate_asset",
    "rating_key",
    "compute_streak",
    "next_downgrade_action",
    "resolve_quality_signal",
    "get_downgrade_settings",
    "update_downgrade_settings",
    "trust_caps_for_tenant",
    "ensure_rating",
    "get_rating",
    "list_ratings",
    "record_change",
    "recompute_rating",
    "rating_distribution",
    "ensure_indexes",
]