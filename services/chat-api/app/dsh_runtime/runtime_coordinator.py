"""Recoverable Runtime/Session coordination above the DSH gateway."""

from __future__ import annotations

import logging
from typing import Any

from app.dsh_runtime.bindings import KernelBindingRepository
from app.dsh_runtime.contracts import CreateRuntimeRequest, CreateSessionRequest, SessionSpec
from app.dsh_runtime.errors import DshRuntimeError, DshTransportError
from app.dsh_runtime.gateway import DshAgentKernelGateway
from app.dsh_runtime.runtime_lock import RuntimeLock
from app.dsh_runtime.session_affinity import SessionAffinityCache

logger = logging.getLogger(__name__)


class RuntimeCoordinator:
    def __init__(
        self,
        gateway: DshAgentKernelGateway,
        bindings: KernelBindingRepository,
        affinity: SessionAffinityCache | None = None,
        runtime_lock: RuntimeLock | None = None,
    ) -> None:
        self._gateway = gateway
        self._bindings = bindings
        self._affinity = affinity
        self._runtime_lock = runtime_lock

    @staticmethod
    def isolation_key(tenant_id: str, profile_version: str) -> str:
        return f"tenant:{tenant_id}:profile:{profile_version}"

    async def create_binding(
        self,
        *,
        tenant_id: str,
        user_id: str,
        conversation_id: str,
        profile_version: str,
        model_instance_id: str,
        preset_id: str = "askai-enterprise",
        execution_location: str = "server",
        workspace_id: str | None = None,
        device_id: str | None = None,
        source_workspace_id: str | None = None,
        git_branch: str | None = None,
        source_ref: str | None = None,
        base_commit: str | None = None,
        detached_head: bool = False,
        execution_mode: str | None = None,
        worktree: bool = False,
        replaces_binding_id: str | None = None,
        seed_runtime_id: str | None = None,
        seed_session_id: str | None = None,
        sealed_seed: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        runtime = await self._runtime(tenant_id=tenant_id, profile_version=profile_version)
        session = await self._gateway.create_session(
            CreateSessionRequest(
                runtime_id=runtime.runtime_id,
                session_spec=SessionSpec(
                    conversation_id=conversation_id,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    profile_version=profile_version,
                    preset_id=preset_id,
                    execution_location=execution_location,
                    workspace_id=workspace_id,
                    seed_runtime_id=seed_runtime_id,
                    seed_session_id=seed_session_id,
                ),
            ),
            # Cross-replica rebuild (§12.4 option A): when the session's owning
            # replica has lost it (restart, ring reshuffle) and no replica can
            # answer a local seed reference, the caller ships the event log the
            # source exported, MAC-sealed, and the target rehydrates from it.
            sealed_seed=sealed_seed,
        )
        try:
            return await self._bindings.create(
                tenant_id=tenant_id,
                user_id=user_id,
                conversation_id=conversation_id,
                kernel_session_id=session.session_id,
                runtime_id=runtime.runtime_id,
                profile_version=profile_version,
                model_instance_id=model_instance_id,
                kernel_version=runtime.kernel_version,
                isolation_key=runtime.isolation_key,
                preset_id=preset_id,
                execution_location=execution_location,
                dsh_workspace_id=workspace_id,
                device_id=device_id,
                source_workspace_id=source_workspace_id,
                git_branch=git_branch,
                source_ref=source_ref,
                base_commit=base_commit,
                detached_head=detached_head,
                execution_mode=execution_mode,
                worktree=worktree,
                replaces_binding_id=replaces_binding_id,
            )
        except Exception:
            await self._gateway.dispose_session(session.session_id)
            raise

    async def rotate_binding(
        self,
        binding: dict[str, Any],
        *,
        profile_version: str,
        model_instance_id: str,
    ) -> dict[str, Any]:
        """Create a successor Session seeded from the completed predecessor."""
        return await self.create_binding(
            tenant_id=str(binding["tenant_id"]),
            user_id=str(binding["user_id"]),
            conversation_id=str(binding["conversation_id"]),
            profile_version=profile_version,
            model_instance_id=model_instance_id,
            preset_id=str(binding.get("preset_id") or "askai-enterprise"),
            execution_location=str(binding.get("execution_location") or "server"),
            workspace_id=str(binding.get("dsh_workspace_id") or "") or None,
            device_id=str(binding.get("device_id") or "") or None,
            source_workspace_id=str(binding.get("source_workspace_id") or "") or None,
            git_branch=str(binding.get("git_branch") or "") or None,
            source_ref=str(binding.get("source_ref") or "") or None,
            base_commit=str(binding.get("base_commit") or "") or None,
            detached_head=bool(binding.get("detached_head")),
            execution_mode=str(binding.get("execution_mode") or "") or None,
            worktree=bool(binding.get("worktree")),
            replaces_binding_id=str(binding["binding_id"]),
            seed_runtime_id=str(binding["runtime_id"]),
            seed_session_id=str(binding["kernel_session_id"]),
        )

    async def dispose_restored_session(self, binding: dict[str, Any]) -> bool:
        """Best-effort cleanup after a successor has durably copied the seed."""
        try:
            await self._gateway.dispose_session(str(binding["kernel_session_id"]))
        except DshRuntimeError:
            return False
        return True

    async def _locate_session_owner(
        self,
        *,
        runtime_id: str,
        session_id: str,
    ) -> dict[str, Any] | None:
        """Find the replica holding ``session_id`` (§12.4 option B).

        Consults the affinity cache first and only probes the pool on a miss,
        then records the answer. Returns the probe result, or ``None`` when no
        replica claims the session (the caller must fall back rather than resume
        blind).
        """
        if self._affinity is None:
            return None

        cached = self._affinity.get(session_id)
        if cached:
            # Still verify: a replica that restarted keeps its instance id but
            # loses in-memory sessions, so a cached id can be stale.
            probe = await self._gateway.probe_session_owner(
                runtime_id=runtime_id, session_id=session_id
            )
            if probe.get("found"):
                return probe
            logger.info(
                "cached session affinity is stale; probing the pool",
                extra={
                    "event": "dsh.session_affinity.stale",
                    "session_id": session_id,
                    "cached_instance": cached,
                },
            )
            self._affinity.forget(session_id)

        probe = await self._gateway.probe_session_owner(
            runtime_id=runtime_id, session_id=session_id
        )
        if probe.get("found"):
            instance_id = str(probe.get("instance_id") or "")
            if instance_id:
                self._affinity.set(session_id, instance_id)
            return probe
        return None

    async def restore(self, binding: dict[str, Any]) -> dict[str, Any]:
        tenant_id = str(binding["tenant_id"])
        profile_version = str(binding["profile_version"])
        runtime = await self._runtime(tenant_id=tenant_id, profile_version=profile_version)
        session_id = str(binding["kernel_session_id"])

        # §12.4 option B: learn which replica owns the session before resuming.
        # The sticky LB can route a session to a replica that does not hold it
        # (hash ring reshuffle on scale up/down, or a replica restart dropping
        # in-memory state), and a blind resume then fails with "session is not
        # live" and nothing recovers it.
        owner = await self._locate_session_owner(
            runtime_id=runtime.runtime_id, session_id=session_id
        )
        if owner is None:
            logger.warning(
                "no replica reports owning the session; resume may fail",
                extra={
                    "event": "dsh.session_affinity.not_found",
                    "session_id": session_id,
                    "runtime_id": runtime.runtime_id,
                },
            )
        else:
            logger.info(
                "session owner located",
                extra={
                    "event": "dsh.session_affinity.located",
                    "session_id": session_id,
                    "instance_id": owner.get("instance_id"),
                },
            )

        self._gateway.attach_session(
            runtime_id=runtime.runtime_id,
            session_id=session_id,
            conversation_id=str(binding["conversation_id"]),
            profile_version=profile_version,
            model_instance_id=str(binding["model_instance_id"]),
            preset_id=str(binding.get("preset_id") or "askai-enterprise"),
            workspace_id=str(binding.get("dsh_workspace_id") or "") or None,
        )
        try:
            await self._gateway.resume_session(session_id)
        except DshTransportError:
            # The host itself was unreachable (restart, network blip). The
            # session is not lost -- it is still there once the replica comes
            # back -- so rebuild would fork a duplicate and we must not do it.
            raise
        except DshRuntimeError:
            # §12.4 option A: the replica is reachable but no longer holds this
            # session ("session is not live"), or the routing pinned us to the
            # wrong replica (DshAffinityError). Pull the completed event log
            # off whichever replica still has it, rehydrate a fresh session on
            # the target, and durably rotate the binding to the new kernel
            # session id. If no replica has it, fall back to an unseeded
            # successor so the conversation is not orphaned.
            return await self._rebuild_binding_from_seed(binding, runtime, owner)

        if str(binding.get("runtime_id")) != runtime.runtime_id:
            await self._bindings.update_runtime(str(binding["binding_id"]), runtime_id=runtime.runtime_id)
            binding = {**binding, "runtime_id": runtime.runtime_id}
        return binding

    async def _rebuild_binding_from_seed(
        self,
        binding: dict[str, Any],
        runtime,
        owner: dict[str, Any] | None,
    ) -> dict[str, Any]:
        session_id = str(binding["kernel_session_id"])
        old_binding_id = str(binding["binding_id"])

        seeded = False
        sealed_seed: dict[str, Any] | None = None
        export = await self._gateway.export_session_seed(
            runtime_id=runtime.runtime_id, session_id=session_id
        )
        if export.get("found") and export.get("seed") is not None:
            sealed_seed = {
                "seed": export["seed"],
                "seedSignature": export.get("seedSignature"),
                "seedSourceInstanceId": export.get("seedSourceInstanceId"),
                "seedSourceSessionId": export.get("seedSourceSessionId"),
            }
            seeded = True
        logger.info(
            "session resume failed; rebuilding binding from seed",
            extra={
                "event": "dsh.session_rebuild.started",
                "session_id": session_id,
                "seeded": seeded,
                "runtime_id": runtime.runtime_id,
            },
        )
        if self._affinity is not None:
            self._affinity.forget(session_id)

        new_binding = await self.create_binding(
            tenant_id=str(binding["tenant_id"]),
            user_id=str(binding["user_id"]),
            conversation_id=str(binding["conversation_id"]),
            profile_version=str(binding["profile_version"]),
            model_instance_id=str(binding["model_instance_id"]),
            preset_id=str(binding.get("preset_id") or "askai-enterprise"),
            execution_location=str(binding.get("execution_location") or "server"),
            workspace_id=str(binding.get("dsh_workspace_id") or "") or None,
            device_id=str(binding.get("device_id") or "") or None,
            source_workspace_id=str(binding.get("source_workspace_id") or "") or None,
            git_branch=str(binding.get("git_branch") or "") or None,
            source_ref=str(binding.get("source_ref") or "") or None,
            base_commit=str(binding.get("base_commit") or "") or None,
            detached_head=bool(binding.get("detached_head")),
            execution_mode=str(binding.get("execution_mode") or "") or None,
            worktree=bool(binding.get("worktree")),
            replaces_binding_id=old_binding_id,
            # The new session may live on a different replica than the old one,
            # so prefer the sealed seed (works cross-replica) over the local
            # runtime/session reference (works only on the owning replica).
            seed_runtime_id=None if seeded else runtime.runtime_id,
            seed_session_id=None if seeded else session_id,
            sealed_seed=sealed_seed,
        )
        if seeded:
            logger.info(
                "binding rebuilt from sealed cross-replica seed",
                extra={
                    "event": "dsh.session_rebuild.completed",
                    "old_session_id": session_id,
                    "new_session_id": new_binding["kernel_session_id"],
                    "seed_source": export.get("seedSourceInstanceId"),
                },
            )
        else:
            logger.warning(
                "no replica still holds the session; rebuilt an unseeded successor",
                extra={
                    "event": "dsh.session_rebuild.unseeded",
                    "old_session_id": session_id,
                    "new_session_id": new_binding["kernel_session_id"],
                },
            )
        return new_binding

    async def _runtime(self, *, tenant_id: str, profile_version: str):
        isolation_key = self.isolation_key(tenant_id, profile_version)
        runtime = await self._gateway.discover_runtime(
            tenant_id=tenant_id,
            profile_version=profile_version,
            isolation_key=isolation_key,
        )
        if runtime is not None:
            return runtime
        # § M2: serialise creation of a runtime for this isolation key across
        # all chat-api instances and pool replicas. Without the lock, each
        # replica happily creates its own runtime and tenant kernel state
        # silently forks. The lock only coordinates *creation*; a holder that
        # cannot create (because a concurrent holder already did) falls
        # through to the discover below.
        token = self._runtime_lock.acquire(isolation_key) if self._runtime_lock else None
        try:
            return await self._gateway.create_runtime(
                CreateRuntimeRequest(
                    tenant_id=tenant_id,
                    profile_version=profile_version,
                    isolation_key=isolation_key,
                )
            )
        except DshRuntimeError:
            concurrent = await self._gateway.discover_runtime(
                tenant_id=tenant_id,
                profile_version=profile_version,
                isolation_key=isolation_key,
            )
            if concurrent is not None:
                logger.info(
                    "concurrent runtime creation won; discovered the winner",
                    extra={
                        "event": "dsh.runtime_lock.concurrent_won",
                        "isolation_key": isolation_key,
                        "acquired": token is not None,
                    },
                )
                return concurrent
            raise
        finally:
            if self._runtime_lock is not None and token is not None:
                self._runtime_lock.release(isolation_key, token)
