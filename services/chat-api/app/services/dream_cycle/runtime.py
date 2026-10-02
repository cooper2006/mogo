"""T999 production wiring for 011 (dream cycle).

011 was delivered as a library: two dependency-light packages
(``app.self_evolution`` for the pure core, ``app.services.dream_cycle`` for the
integration layer) that nothing in ``app/`` imported, nothing scheduled, and
whose five ``audit_*`` wrappers were never called. This module closes that gap
without touching the DSH turn hot path:

* friction is *derived* from rows the event pipeline already persists
  (``kernel_event_projections``): a tool that failed and later succeeded inside
  one message is FR-1's ``failed_then_succeeded``. No new code runs inside
  ``DshTurnRunner``, so no latency is added to a live turn.
* ``run_once()`` is one scan pass — collect → detect → cluster → draft →
  audit — taking an injected db handle, fragment store and audit sink, which
  keeps it unit-testable without a live MongoDB.
* ``DreamCycleScanner`` owns the periodic trigger (an ``asyncio.Task`` looping
  on ``EvolutionConfig.scan_interval_hours``) and is started/stopped from the
  application lifespan beside ``scheduled_task_scheduler``.

``scheduled_tasks`` itself is *not* reused: its jobs model user-facing chat
runs (each needs a prompt and a session), which is the wrong shape for a
background scan. The loop below follows the ``_receipt_gc_loop`` pattern in
``app/main.py`` instead.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from typing import Any, Callable, Iterable, Optional

from app.core.db import get_db
from app.self_evolution.draft_gen import generate_draft
from app.self_evolution.fragment import ExperienceFragment, FragmentStore
from app.self_evolution.friction import FrictionSignal, detect_friction
from app.self_evolution.scanner import (
    ScanConfig,
    ScanResult,
    scan_fragments,
    scan_summary,
    should_generate_draft,
)
from app.services.dream_cycle import deprecation as _deprecation
from app.services.dream_cycle import evolution_audit as _audit
from app.services.dream_cycle.evolution_audit import EvolutionConfig

logger = logging.getLogger(__name__)

#: The 011 feature code registered in ``feature_audit.FEATURE_AUDIT_EVENTS``.
AUDIT_FEATURE = "011"

#: Projected tool rows live here (written by the DSH event side band).
PROJECTIONS_COLLECTION = "kernel_event_projections"

_TOOL_FAILED = "item.failed"
_TOOL_COMPLETED = "item.completed"

#: Default cap on rows pulled per pass, so one pass cannot read a whole tenant's
#: history into memory.
DEFAULT_ROW_LIMIT = 2000


def _default_audit_sink(
    *,
    event_type: str,
    actor: str,
    ts: Any,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Adapt the 011 sink protocol onto the 001 audit bridge (T999).

    ``record_evolution_event`` calls sinks *synchronously* with keyword
    arguments, and ``emit_feature_event`` is synchronous too (it schedules its
    Mongo write on the running loop), so the two fit together directly. The
    import is deferred to keep this module free of an import cycle.
    """
    from app.services.feature_audit_bridge import emit_feature_event

    document = {"actor": actor, "ts": ts, **dict(payload or {})}
    tenant_id = str(document.get("tenant_id") or "default")
    return emit_feature_event(
        AUDIT_FEATURE,
        event_type,
        document,
        tenant_id=tenant_id,
        actor=actor,
    )


def _failed_then_succeeded(sequence: list[str]) -> bool:
    """True when a failure is followed by a success in the same tool's run."""
    try:
        first_failure = sequence.index(_TOOL_FAILED)
    except ValueError:
        return False
    return _TOOL_COMPLETED in sequence[first_failure + 1 :]


def _attempts_until_first_success(sequence: list[str]) -> int:
    """Calls made before the tool first succeeded (the retry count + 1)."""
    try:
        first_failure = sequence.index(_TOOL_FAILED)
        first_success = sequence.index(_TOOL_COMPLETED, first_failure + 1)
    except ValueError:
        return len(sequence)
    return first_success + 1


def signals_from_rows(rows: Iterable[dict[str, Any]]) -> list[FrictionSignal]:
    """Derive friction signals from projected tool rows.

    Rows are grouped per ``(tenant_id, message_id)`` and then per tool name, so
    unrelated concurrent messages never share a "retry". A tool whose outcome
    sequence contains a failure followed by a success is a retry (FR-1).
    """
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        key = (
            str(row.get("tenant_id") or "default"),
            str(row.get("message_id") or ""),
        )
        groups.setdefault(key, []).append(row)

    signals: list[FrictionSignal] = []
    for (tenant_id, message_id), group in groups.items():
        group.sort(key=lambda item: int(item.get("stream_seq") or 0))
        sequences: dict[str, list[str]] = {}
        for row in group:
            payload = row.get("payload") or {}
            name = str(payload.get("name") or "tool")
            sequences.setdefault(name, []).append(str(row.get("type") or ""))
        for name, sequence in sequences.items():
            if not _failed_then_succeeded(sequence):
                continue
            signal = detect_friction(
                attempts=_attempts_until_first_success(sequence),
                succeeded=True,
                scene=[name],
                actions=list(sequence),
                result=f"{name} failed then succeeded",
                source_session=message_id,
                tenant_id=tenant_id,
            )
            if signal is not None:
                signals.append(signal)
    return signals


def fragments_from_signals(
    signals: Iterable[FrictionSignal],
) -> list[ExperienceFragment]:
    """Turn friction signals into storable experience fragments."""
    return [
        ExperienceFragment(
            scene=list(signal.scene),
            actions=list(signal.actions),
            result=signal.result,
            friction_kind=signal.kind,
            source_session=signal.source_session,
            feedback=signal.feedback,
            tenant_id=signal.tenant_id,
        )
        for signal in signals
    ]


async def collect_tool_rows(
    db: Any,
    *,
    after_stream_seq: int = 0,
    limit: int = DEFAULT_ROW_LIMIT,
) -> list[dict[str, Any]]:
    """Read the projected tool outcomes the scan consumes."""
    if db is None:
        return []
    cursor = (
        db[PROJECTIONS_COLLECTION]
        .find(
            {
                "item_kind": "tool",
                "type": {"$in": [_TOOL_FAILED, _TOOL_COMPLETED]},
                "stream_seq": {"$gt": int(after_stream_seq)},
            },
            {
                "_id": 0,
                "message_id": 1,
                "tenant_id": 1,
                "stream_seq": 1,
                "type": 1,
                "payload": 1,
            },
        )
        .sort("stream_seq", 1)
        .limit(int(limit))
    )
    return [dict(row) async for row in cursor]


async def ensure_indexes(db: Any = None) -> None:
    """Index the scan's projection filter + the tenant-partitioned adoption store (011)."""
    resolved = db if db is not None else get_db()
    if resolved is None:
        return
    await resolved[PROJECTIONS_COLLECTION].create_index(
        [("item_kind", 1), ("type", 1), ("stream_seq", 1)],
        name="dream_cycle_tool_outcomes",
    )
    # T002-1 / ET005 / SEC001: tenant-partitioned unique index on the adoption
    # collection so one tenant's low-quality flags cannot bleed into another's.
    await resolved[_deprecation.AdoptionStore.COLLECTION].create_index(
        [("tenant_id", 1), ("skill_key", 1)],
        unique=True,
        name="skill_adoption_tenant_skill",
    )


def _audit_capture_many(
    fragments: Iterable[ExperienceFragment], *, sink: Callable[..., Any], actor: str
) -> int:
    recorded = 0
    for fragment in fragments:
        _audit.audit_capture(fragment.as_document(), sink=sink, actor=actor)
        recorded += 1
    return recorded


async def run_once(
    *,
    db: Any = None,
    sink: Optional[Callable[..., Any]] = None,
    store: Optional[FragmentStore] = None,
    config: Optional[EvolutionConfig] = None,
    scan_config: Optional[ScanConfig] = None,
    after_stream_seq: int = 0,
    actor: str = "dream-cycle",
    deprecations: Optional[Iterable[dict[str, Any]]] = None,
    restorations: Optional[Iterable[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Run one dream-cycle pass and return a small report.

    ``deprecations`` / ``restorations`` are supplied by whoever owns skill
    adoption telemetry (016). When a DB is bound, 011 persists the shared
    ``marked_low_quality`` bit into the tenant-partitioned ``skill_adoption``
    collection (via ``AdoptionStore``) so the 016 market side can read it back
    and down-rank the skill (T014-3 / T015-2). Without a DB the store degrades
    to an in-process dict, and passing no deprecations/restorations makes both
    paths a no-op rather than a fake event.
    """
    resolved_config = config or EvolutionConfig()
    resolved_scan = scan_config or ScanConfig(
        jaccard_threshold=resolved_config.jaccard_threshold,
        min_samples=resolved_config.min_samples,
        action_similarity_threshold=resolved_config.action_similarity_threshold,
        draft_backlog_limit=resolved_config.draft_backlog_limit,
    )
    audit_sink = sink if sink is not None else _default_audit_sink
    fragment_store = store if store is not None else FragmentStore()

    resolved_db = db if db is not None else get_db()
    adoption_store = _deprecation.AdoptionStore(db=resolved_db)
    rows = await collect_tool_rows(resolved_db, after_stream_seq=after_stream_seq)
    signals = signals_from_rows(rows)
    fragments = fragments_from_signals(signals)
    fragment_store.extend(fragments)

    captured = _audit_capture_many(fragments, sink=audit_sink, actor=actor)
    generated = 0
    mrs = 0
    draft_ids: list[str] = []
    # T009-3 / T018-4: the draft backlog cap is per-tenant, not global. Each
    # tenant's generated count is tracked separately so one chatty tenant
    # cannot exhaust another's quota.
    per_tenant_drafts: dict[str, int] = {}

    for tenant_id in sorted({item.tenant_id for item in fragment_store.all()}):
        result = scan_fragments(fragment_store.all(tenant_id), config=resolved_scan)
        for cluster in result.clusters:
            if not should_generate_draft(
                cluster,
                config=resolved_scan,
                existing_drafts=per_tenant_drafts.get(tenant_id, 0),
            ):
                continue
            draft = generate_draft(cluster, min_samples=resolved_scan.min_samples)
            if draft is None:
                continue
            generated += 1
            draft_ids.append(draft.skill_id)
            per_tenant_drafts[tenant_id] = per_tenant_drafts.get(tenant_id, 0) + 1
            _audit.audit_generate(1, sink=audit_sink, actor=actor)
            if cluster.is_mr_eligible(
                threshold=resolved_scan.jaccard_threshold,
                min_samples=resolved_scan.min_samples,
            ):
                _audit.audit_mr(draft.as_dict(), sink=audit_sink, actor=actor)
                mrs += 1

    deprecated = 0
    for record in deprecations or ():
        # Persist the shared ``marked_low_quality`` bit (read by 016) and audit.
        skill_key = str(record.get("skill_key") or "")
        tenant_id = str(record.get("tenant_id") or "default")
        if skill_key:
            adoption_store.mark_deprecated(skill_key, tenant_id, dict(record))
        _audit.audit_deprecate(dict(record), sink=audit_sink, actor=actor)
        deprecated += 1

    restored = 0
    for record in restorations or ():
        skill_key = str(record.get("skill_key") or "")
        tenant_id = str(record.get("tenant_id") or "default")
        if skill_key:
            adoption_store.restore(skill_key, tenant_id)
        _audit.audit_restore(dict(record), sink=audit_sink, actor=actor)
        restored += 1

    # T007-4: the scan pass itself must produce an audit event so the full
    # self-evolution chain (T017) is actually complete, not just "capture /
    # generate / mr / deprecate / restore". ``scan_id`` makes each pass
    # addressable; ``draftCount`` is falsifiable against ``generated``.
    scan_id = uuid.uuid4().hex
    summary = scan_summary(
        ScanResult(clusters=[]),
        config=resolved_scan,
        scan_id=scan_id,
        draft_count=generated,
    )
    _audit.audit_scan(summary, sink=audit_sink, actor=actor, scan_id=scan_id)

    return {
        "scanId": scan_id,
        "rows": len(rows),
        "signals": len(signals),
        "fragments": len(fragments),
        "captured": captured,
        "generated": generated,
        "mr": mrs,
        "deprecated": deprecated,
        "restored": restored,
        "draftIds": draft_ids,
    }


class DreamCycleScanner:
    """Periodic trigger for ``run_once`` (started from the app lifespan)."""

    def __init__(
        self,
        *,
        config: Optional[EvolutionConfig] = None,
        interval_seconds: Optional[float] = None,
        sink: Optional[Callable[..., Any]] = None,
    ) -> None:
        self._config = config or EvolutionConfig()
        self._interval_seconds = interval_seconds
        self._sink = sink
        self._task: Optional[asyncio.Task] = None
        self._stopping = asyncio.Event()

    @property
    def interval_seconds(self) -> float:
        if self._interval_seconds is not None:
            return float(self._interval_seconds)
        return float(self._config.scan_interval_hours) * 3600.0

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stopping.clear()
        self._task = asyncio.create_task(self._loop(), name="dream-cycle-scanner")

    async def stop(self) -> None:
        self._stopping.set()
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def _loop(self) -> None:
        while not self._stopping.is_set():
            try:
                await run_once(config=self._config, sink=self._sink)
            except Exception:  # pragma: no cover - defensive, mirrors _receipt_gc_loop
                logger.exception("dream cycle scan failed")
            try:
                await asyncio.wait_for(
                    self._stopping.wait(), timeout=self.interval_seconds
                )
            except asyncio.TimeoutError:
                pass


#: Process-wide scanner, started/stopped from ``app.main``'s lifespan.
dream_cycle_scanner = DreamCycleScanner()


__all__ = [
    "AUDIT_FEATURE",
    "DEFAULT_ROW_LIMIT",
    "DreamCycleScanner",
    "PROJECTIONS_COLLECTION",
    "collect_tool_rows",
    "dream_cycle_scanner",
    "ensure_indexes",
    "fragments_from_signals",
    "run_once",
    "signals_from_rows",
]
