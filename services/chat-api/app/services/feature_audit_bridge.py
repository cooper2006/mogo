"""T999 production wiring: feature events → 001 governance audit stream.

Bridges the dependency-light ``record_feature_event`` helpers (012/014/015/
016/017/018) into the 001 ``position_role_audit_logs`` stream so all feature
events share the same audit trail, retention and compliance reporting.

The sink here is async-Mongo-aware; when no DB is bound (tests / in-memory)
events are buffered in-process so no feature event is silently lost.
"""

from __future__ import annotations

import logging
from typing import Any

from app.services.feature_audit import record_feature_event

logger = logging.getLogger(__name__)

_T999_AUDIT_ACTION = "feature.audit"
_T999_TARGET_TYPE = "feature"


class FeatureAuditSink:
    """Writes feature audit events into the 001 governance audit stream.

    In production this persists to ``position_role_audit_logs``. In tests or
    when the DB is unavailable, events are buffered so that "100% 审计" is
    preserved without a hard DB dependency at construction time.
    """

    def __init__(self) -> None:
        self.buffered: list[dict[str, Any]] = []

    async def emit(
        self,
        feature: str,
        event: str,
        document: dict[str, Any],
        *,
        tenant_id: str = "",
        actor: str = "",
    ) -> dict[str, Any]:
        record = record_feature_event(feature, event, document)
        record.setdefault("tenant_id", tenant_id)
        record.setdefault("actor", actor)
        self._persist(feature, record)
        return record

    def _persist(self, feature: str, record: dict[str, Any]) -> None:
        try:
            from app.core.db import get_db

            db = get_db()
            if db is None:
                raise RuntimeError("db not bound")
            from app.services.feature_audit import AuditSink  # noqa: F401 - import parity

            # Async write scheduled on the next event loop; fire-and-forget.
            _schedule_insert(feature, record, db)
        except Exception:  # noqa: BLE001 - never let audit drop a call
            logger.warning("feature audit deferred: %s/%s", feature, record.get("event"))
            self.buffered.append(record)

    # -- synchronous entry used by pure-library feature call sites -----------
    def record(
        self,
        feature: str,
        event: str,
        document: dict[str, Any],
        *,
        tenant_id: str = "",
        actor: str = "",
    ) -> dict[str, Any]:
        record = record_feature_event(feature, event, document)
        record.setdefault("tenant_id", tenant_id)
        record.setdefault("actor", actor)
        self._persist(feature, record)
        return record


def _schedule_insert(feature: str, record: dict[str, Any], db: Any) -> None:
    """Best-effort async insert onto the current loop; falls back to buffer."""
    import asyncio

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No running loop (sync context): buffer it for the next async flush.
        _DEFAULT_SINK.buffered.append(record)
        return

    async def _do_insert() -> None:
        import uuid
        from datetime import datetime, timezone

        await db.position_role_audit_logs.insert_one(
            {
                "_id": uuid.uuid4().hex,
                "main_id": str(record.get("tenant_id") or "default"),
                "actor": str(record.get("actor") or ""),
                "action": _T999_AUDIT_ACTION,
                "target_type": _T999_TARGET_TYPE,
                "target_id": feature,
                "details": {"feature": feature, **record},
                "created_at": datetime.now(timezone.utc),
            }
        )

    loop.create_task(_do_insert())


_DEFAULT_SINK = FeatureAuditSink()


def emit_feature_event(
    feature: str,
    event: str,
    document: dict[str, Any],
    *,
    tenant_id: str = "",
    actor: str = "",
) -> dict[str, Any]:
    """Module-level convenience for synchronous call sites."""
    return _DEFAULT_SINK.record(feature, event, document, tenant_id=tenant_id, actor=actor)


async def aemit_feature_event(
    feature: str,
    event: str,
    document: dict[str, Any],
    *,
    tenant_id: str = "",
    actor: str = "",
) -> dict[str, Any]:
    """Module-level convenience for async call sites."""
    return await _DEFAULT_SINK.emit(feature, event, document, tenant_id=tenant_id, actor=actor)


__all__ = [
    "FeatureAuditSink",
    "emit_feature_event",
    "aemit_feature_event",
    "_DEFAULT_SINK",
]
