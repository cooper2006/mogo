"""Persistent orchestration runs (050 FR-004 / FR-005 / FR-011).

The 010 engine executes in-process with no checkpointing; a ``human_approval``
node must survive restarts, so this module adds the ``orchestration_runs``
collection: one document per run holding the **locked definition snapshot**,
per-node outcomes (checkpoints), the shared context and pending approval todos.

Design points (spec 050 decisions #2/#3, T003/T004):

* the full definition document is embedded at creation — editing the source
  definition while a run is suspended never affects the in-flight run;
* every node outcome is checkpointed with an optimistic ``revision`` counter;
* recovery uses a single-active lease (``lease_owner`` / ``lease_until``),
  mirroring ``scheduled_tasks/repository.py`` — never a distributed scheduler;
* the store is transport-agnostic: the db handle is injected (``get_db()`` at
  the API seam), so tests run against any mongo-shaped fake and both 027
  backends share this exact code path (FR-011).
"""

from __future__ import annotations

import uuid
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any

ORCHESTRATION_RUNS_COLLECTION = "orchestration_runs"

RUN_RUNNING = "running"
RUN_AWAITING = "awaiting_approval"
RUN_COMPLETED = "completed"
RUN_REJECTED = "rejected"
RUN_TIMEOUT = "timeout"
RUN_CANCELLED = "cancelled"
RUN_FAILED = "failed"
RUN_NEEDS_REVIEW = "needs_review"

TERMINAL_STATES = (RUN_COMPLETED, RUN_REJECTED, RUN_TIMEOUT, RUN_CANCELLED, RUN_FAILED)
ACTIVE_STATES = (RUN_RUNNING, RUN_AWAITING, RUN_NEEDS_REVIEW)

LEASE_MINUTES = 2
#: 终态运行快照保留期（OQ-4：对齐审计 ≥180 天口径，可经环境变量调整）。
DEFAULT_RETENTION_DAYS = 180


class RunStoreError(RuntimeError):
    """Raised for illegal state transitions or lost optimistic writes."""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RunStore:
    """Repository over ``orchestration_runs`` (mongo-shaped async db handle)."""

    def __init__(self, db: Any, *, lease_minutes: int = LEASE_MINUTES) -> None:
        if db is None:
            raise RunStoreError("数据后端未初始化，无法持久化编排运行（fail-closed）")
        self._col = db[ORCHESTRATION_RUNS_COLLECTION]
        self._lease = timedelta(minutes=max(1, int(lease_minutes)))

    # ------------------------------------------------------------------ create

    async def create_run(
        self,
        *,
        document: dict[str, Any],
        tenant_id: str,
        user_id: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        header = document.get("orchestration") or {}
        orchestration_id = str(header.get("id") or "").strip()
        if not orchestration_id:
            raise RunStoreError("运行创建需要带 orchestration.id 的定义文档")
        now = utcnow()
        run = {
            "run_id": uuid.uuid4().hex,
            "orchestration_id": orchestration_id,
            "definition_version": header.get("version"),
            "definition_document": deepcopy(document),
            "tenant_id": tenant_id,
            "initiator_id": user_id,
            "status": RUN_RUNNING,
            "context": dict(context or {}),
            "outcomes": {},
            "events": [],
            "pending_approvals": {},
            "decision_history": [],
            "revision": 0,
            "lease_owner": None,
            "lease_until": None,
            "created_at": now,
            "updated_at": now,
        }
        await self._col.insert_one(run)
        return deepcopy(run)

    async def get_run(self, run_id: str, *, tenant_id: str | None = None) -> dict[str, Any] | None:
        query: dict[str, Any] = {"run_id": run_id}
        if tenant_id is not None:
            query["tenant_id"] = tenant_id
        doc = await self._col.find_one(query)
        return deepcopy(doc) if doc else None

    async def list_runs(self, *, tenant_id: str, status: str | None = None) -> list[dict[str, Any]]:
        query: dict[str, Any] = {"tenant_id": tenant_id}
        if status:
            query["status"] = status
        items: list[dict[str, Any]] = []
        async for doc in self._col.find(query).sort("created_at", -1):
            items.append(deepcopy(doc))
        return items

    # -------------------------------------------------------------- checkpoint

    async def checkpoint(
        self,
        run_id: str,
        *,
        node_id: str,
        outcome: dict[str, Any],
        context: dict[str, Any],
        event: dict[str, Any] | None = None,
        expected_revision: int | None = None,
    ) -> int:
        """Persist one node outcome; returns the new revision.

        A failed write raises (fail-closed, spec edge case): the caller must not
        keep an unpersisted "in-memory suspension" that a restart would drop.
        """
        query: dict[str, Any] = {"run_id": run_id}
        if expected_revision is not None:
            query["revision"] = expected_revision
        update: dict[str, Any] = {
            "$set": {
                f"outcomes.{node_id}": deepcopy(outcome),
                "context": deepcopy(context),
                "updated_at": utcnow(),
            },
            "$inc": {"revision": 1},
        }
        if event is not None:
            update["$push"] = {"events": deepcopy(event)}
        result = await self._col.update_one(query, update)
        if result.matched_count == 0:
            raise RunStoreError(f"checkpoint 写入失败（运行不存在或版本冲突）：{run_id}/{node_id}")
        doc = await self._col.find_one({"run_id": run_id})
        return int(doc.get("revision") or 0)

    async def append_event(self, run_id: str, event: dict[str, Any]) -> None:
        await self._col.update_one(
            {"run_id": run_id},
            {"$push": {"events": deepcopy(event)}, "$set": {"updated_at": utcnow()}},
        )

    # --------------------------------------------------------------- suspension

    async def suspend(self, run_id: str, *, node_id: str, todo: dict[str, Any]) -> None:
        """Persist an approval todo and flip the run to ``awaiting_approval``.

        Persist-first: if this write fails the node must fail, never suspend in
        memory only (spec edge case "快照写入失败").
        """
        result = await self._col.update_one(
            {"run_id": run_id, "status": {"$in": [RUN_RUNNING, RUN_AWAITING]}},
            {
                "$set": {
                    f"pending_approvals.{node_id}": deepcopy(todo),
                    f"outcomes.{node_id}": {"node_id": node_id, "state": "awaiting_approval"},
                    "status": RUN_AWAITING,
                    "updated_at": utcnow(),
                },
                "$inc": {"revision": 1},
            },
        )
        if result.matched_count == 0:
            raise RunStoreError(f"挂起快照写入失败（运行不存在或已终态）：{run_id}/{node_id}")

    async def claim_pending(self, run_id: str, node_id: str) -> dict[str, Any]:
        """Atomically remove a pending todo — the one-time consumption guard.

        Survives restarts because the guard lives in the document, not in the
        in-process ``ApprovalRuntime`` dict (T003 two-stage design).

        MUST request the **pre-update** document: the update ``$unset``s the
        todo, so ``return_document=True`` (ReturnDocument.AFTER) yields a doc
        without the field and would raise after the todo has already been
        consumed — leaving the run stuck in ``awaiting_approval`` with no todo
        visible to ``list_todos`` / ``scan_timeouts``. Both motor and the 027
        pg_compat facade treat ``True`` as AFTER.
        """
        doc = await self._col.find_one_and_update(
            {"run_id": run_id, f"pending_approvals.{node_id}": {"$exists": True}},
            {
                "$unset": {f"pending_approvals.{node_id}": ""},
                "$set": {"updated_at": utcnow()},
                "$inc": {"revision": 1},
            },
            return_document=False,
        )
        if doc is None:
            raise RunStoreError(f"待办不存在或已被消费：{run_id}/{node_id}")
        todo = (doc.get("pending_approvals") or {}).get(node_id)
        if todo is None:
            raise RunStoreError(f"待办不存在或已被消费：{run_id}/{node_id}")
        return deepcopy(todo)

    async def record_decision(self, run_id: str, decision: dict[str, Any]) -> None:
        await self._col.update_one(
            {"run_id": run_id},
            {"$push": {"decision_history": deepcopy(decision)}, "$set": {"updated_at": utcnow()}},
        )

    # ------------------------------------------------------------ lease/resume

    async def resume(self, run_id: str, *, worker_id: str, from_status: str = RUN_AWAITING) -> dict[str, Any]:
        """Acquire the single-active lease and flip to ``running`` (FR-005)."""
        now = utcnow()
        found = await self._col.find_one_and_update(
            {
                "run_id": run_id,
                "status": from_status,
                "$or": [
                    {"lease_until": {"$exists": False}},
                    {"lease_until": None},
                    {"lease_until": {"$lt": now}},
                ],
            },
            {
                "$set": {
                    "status": RUN_RUNNING,
                    "lease_owner": worker_id,
                    "lease_until": now + self._lease,
                    "updated_at": now,
                },
                "$inc": {"revision": 1},
            },
            return_document=True,
        )
        if found is None:
            raise RunStoreError(f"运行不可恢复（状态不符或租约被占用）：{run_id}")
        # Do not rely on the BEFORE/AFTER semantics of the returned document:
        # re-read so the lease/status surfaced to the driver is the persisted one.
        # (motor and pg_compat both treat ``return_document=True`` as AFTER.)
        doc = await self._col.find_one({"run_id": run_id})
        if doc is None:
            raise RunStoreError(f"运行不存在：{run_id}")
        return deepcopy(doc)

    async def release_lease(self, run_id: str, *, worker_id: str, status: str) -> None:
        await self._col.update_one(
            {"run_id": run_id, "lease_owner": worker_id},
            {"$set": {"status": status, "lease_owner": None, "lease_until": None, "updated_at": utcnow()}},
        )

    async def set_status(self, run_id: str, status: str, *, reason: str = "", actor_id: str = "") -> None:
        await self._col.update_one(
            {"run_id": run_id},
            {
                "$set": {"status": status, "lease_owner": None, "lease_until": None, "updated_at": utcnow()},
                "$push": {"events": {"event": f"run.{status}", "reason": reason, "actor_id": actor_id, "at": utcnow().isoformat()}},
            },
        )

    # ------------------------------------------------------------------- todos

    async def list_todos(self, *, tenant_id: str, approver: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        async for doc in self._col.find({"tenant_id": tenant_id, "status": RUN_AWAITING}):
            for node_id, todo in (doc.get("pending_approvals") or {}).items():
                if str(todo.get("approver")) == approver:
                    items.append(
                        {
                            "run_id": doc["run_id"],
                            "orchestration_id": doc.get("orchestration_id"),
                            "node_id": node_id,
                            "initiator_id": doc.get("initiator_id"),
                            **deepcopy(todo),
                        }
                    )
        return items

    async def reassign(self, run_id: str, *, node_id: str, new_approver: str, actor_id: str) -> None:
        doc = await self.get_run(run_id)
        if doc is None or node_id not in (doc.get("pending_approvals") or {}):
            raise RunStoreError(f"改派失败：待办不存在 {run_id}/{node_id}")
        if not str(new_approver or "").strip():
            raise RunStoreError("改派失败：新审批人为空")
        await self._col.update_one(
            {"run_id": run_id, f"pending_approvals.{node_id}": {"$exists": True}},
            {
                "$set": {f"pending_approvals.{node_id}.approver": new_approver, "updated_at": utcnow()},
                "$push": {
                    "events": {"event": "approval.reassigned", "node": node_id, "approver": new_approver, "actor_id": actor_id, "at": utcnow().isoformat()},
                    "decision_history": {"node_id": node_id, "action": "reassign", "actor_id": actor_id, "approver": new_approver, "at": utcnow().isoformat()},
                },
            },
        )

    async def cancel(self, run_id: str, *, actor_id: str, reason: str = "") -> None:
        doc = await self.get_run(run_id)
        if doc is None:
            raise RunStoreError(f"运行不存在：{run_id}")
        if doc.get("status") in TERMINAL_STATES:
            raise RunStoreError(f"运行已终态，不可取消：{doc.get('status')}")
        await self._col.update_one(
            {"run_id": run_id},
            {
                "$set": {"pending_approvals": {}, "status": RUN_CANCELLED, "lease_owner": None, "lease_until": None, "updated_at": utcnow()},
                "$push": {
                    "events": {"event": "run.cancelled", "actor_id": actor_id, "reason": reason, "at": utcnow().isoformat()},
                    "decision_history": {"action": "cancel", "actor_id": actor_id, "reason": reason, "at": utcnow().isoformat()},
                },
            },
        )

    # -------------------------------------------------------- recovery sweeps

    async def scan_timeouts(self, *, now: datetime | None = None) -> list[dict[str, Any]]:
        """Expire pending approvals whose deadline passed (FR-006 fail-closed).

        Driven by the recovery sweep, not an in-process timer: a suspended run
        holds no coroutine, so restarts cannot lose the timeout judgement.
        Returns ``[{run_id, node_id, todo}]`` for the caller to block downstream
        and audit. The run flips to ``timeout`` only when no todos remain.
        """
        moment = now or utcnow()
        expired: list[dict[str, Any]] = []
        async for doc in self._col.find({"status": RUN_AWAITING}):
            for node_id, todo in list((doc.get("pending_approvals") or {}).items()):
                deadline = _as_datetime(todo.get("deadline"))
                if deadline is None or deadline > moment:
                    continue
                claimed = await self._col.find_one_and_update(
                    {"run_id": doc["run_id"], f"pending_approvals.{node_id}": {"$exists": True}},
                    {
                        "$unset": {f"pending_approvals.{node_id}": ""},
                        "$set": {
                            f"outcomes.{node_id}": {"node_id": node_id, "state": "failed", "error": "approval timeout"},
                            "updated_at": moment,
                        },
                        "$push": {"events": {"event": "approval.timeout", "node": node_id, "at": moment.isoformat()}},
                        "$inc": {"revision": 1},
                    },
                    return_document=True,
                )
                if claimed is None:
                    continue
                expired.append({"run_id": doc["run_id"], "node_id": node_id, "todo": deepcopy(todo)})
                refreshed = await self._col.find_one({"run_id": doc["run_id"]})
                if refreshed is not None and not (refreshed.get("pending_approvals") or {}):
                    await self.set_status(doc["run_id"], RUN_TIMEOUT, reason=f"approval timeout: {node_id}")
        return expired

    async def scan_interrupted(self, *, now: datetime | None = None) -> list[dict[str, Any]]:
        """Runs that were ``running`` when their worker died (lease expired).

        Without a per-node idempotency declaration the in-flight node's side
        effects are unknown, so the run goes to ``needs_review`` — never a
        silent re-run (US2 acceptance #3).
        """
        moment = now or utcnow()
        flagged: list[dict[str, Any]] = []
        async for doc in self._col.find({"status": RUN_RUNNING, "lease_until": {"$lt": moment}}):
            await self._col.update_one(
                {"run_id": doc["run_id"], "status": RUN_RUNNING},
                {
                    "$set": {"status": RUN_NEEDS_REVIEW, "lease_owner": None, "lease_until": None, "updated_at": moment},
                    "$push": {"events": {"event": "run.needs_review", "reason": "worker lease expired mid-run", "at": moment.isoformat()}},
                },
            )
            flagged.append(deepcopy(doc))
        return flagged

    async def resolve_review(self, run_id: str, *, node_id: str, action: str, actor_id: str) -> dict[str, Any]:
        """Admin disposition for ``needs_review`` runs (OQ-3：首期交付).

        ``skip`` marks the crashed node completed with no output and resumes;
        ``terminate`` fails the node (downstream blocking happens on resume).
        """
        if action not in ("skip", "terminate"):
            raise RunStoreError(f"未知处置动作：{action!r}（允许 skip/terminate）")
        doc = await self.get_run(run_id)
        if doc is None or doc.get("status") != RUN_NEEDS_REVIEW:
            raise RunStoreError(f"运行不存在或不处于 needs_review：{run_id}")
        state = "completed" if action == "skip" else "failed"
        outcome: dict[str, Any] = {"node_id": node_id, "state": state, "reason": f"needs_review resolved: {action}"}
        if action == "terminate":
            outcome["error"] = f"terminated by {actor_id}"
        await self._col.update_one(
            {"run_id": run_id},
            {
                "$set": {f"outcomes.{node_id}": outcome, "status": RUN_AWAITING, "updated_at": utcnow()},
                "$push": {
                    "events": {"event": "run.review_resolved", "node": node_id, "action": action, "actor_id": actor_id, "at": utcnow().isoformat()},
                    "decision_history": {"node_id": node_id, "action": f"review_{action}", "actor_id": actor_id, "at": utcnow().isoformat()},
                },
                "$inc": {"revision": 1},
            },
        )
        result = await self.get_run(run_id)
        if result is None:
            raise RunStoreError(f"运行不存在：{run_id}")
        return result

    async def cleanup_terminal(self, *, retention_days: int = DEFAULT_RETENTION_DAYS, now: datetime | None = None) -> int:
        cutoff = (now or utcnow()) - timedelta(days=max(1, int(retention_days)))
        result = await self._col.delete_many({"status": {"$in": list(TERMINAL_STATES)}, "updated_at": {"$lt": cutoff}})
        return int(result.deleted_count)


def _as_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None