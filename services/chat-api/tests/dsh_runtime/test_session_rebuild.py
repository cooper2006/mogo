"""§12.4 option A: cross-replica session rebuild from a sealed seed.

When the owning replica loses a session (restart, ring reshuffle) a plain
resume fails with "session is not live". These tests pin the coordinator's
fallback: pull the sealed seed off the replica that still holds it, rehydrate
a fresh session on the target, and rotate the binding to the new kernel
session id.
"""

from __future__ import annotations

import pytest

from app.dsh_runtime.errors import DshRuntimeError, DshTransportError
from app.dsh_runtime.runtime_coordinator import RuntimeCoordinator


class _StubGateway:
    """Gateway stub that scripts create/resume/discover outcomes."""

    def __init__(self) -> None:
        self.discovered = None
        self.resume_error: Exception | None = None
        self.export_result: dict | None = None
        self.created: list[dict] = []

    async def discover_runtime(self, **kwargs):
        return self.discovered

    def attach_session(self, **kwargs) -> None:
        pass

    async def resume_session(self, session_id: str):
        if self.resume_error is not None:
            raise self.resume_error
        return {}

    async def export_session_seed(self, *, runtime_id: str, session_id: str):
        if self.export_result is None:
            raise AttributeError("export_session_seed unavailable")
        return self.export_result

    async def create_session(self, request, *, sealed_seed: dict | None = None):
        class _Handle:
            session_id = "dsh-new"
            status = "active"
        handle = _Handle()
        self.created.append({"request": request, "sealed_seed": sealed_seed})
        return handle

    async def create_runtime(self, request):
        raise NotImplementedError

    async def dispose_session(self, session_id: str) -> None:
        pass


class _StubBindings:
    def __init__(self) -> None:
        self.created: list[dict] = []

    async def create(self, **fields):
        fields = {**fields, "binding_id": "binding-new"}
        self.created.append(fields)
        return fields

    async def update_runtime(self, binding_id: str, *, runtime_id: str) -> None:
        pass


class _Runtime:
    def __init__(self) -> None:
        self.runtime_id = "runtime-target"
        self.kernel_version = "k1"
        self.profile_version = "v1"
        self.model_instance_id = "m1"
        self.isolation_key = "tenant:t1:profile:v1"


def _coordinator() -> tuple[RuntimeCoordinator, _StubGateway, _StubBindings]:
    gateway = _StubGateway()
    bindings = _StubBindings()
    coordinator = RuntimeCoordinator(gateway, bindings)
    return coordinator, gateway, bindings


def _binding() -> dict:
    return {
        "binding_id": "binding-old",
        "tenant_id": "t1",
        "user_id": "u1",
        "conversation_id": "conv-1",
        "kernel_session_id": "sess-old",
        "profile_version": "v1",
        "model_instance_id": "m1",
        "runtime_id": "runtime-target",
        "preset_id": "askai-enterprise",
        "execution_location": "server",
        "dsh_workspace_id": None,
        "device_id": None,
        "source_workspace_id": None,
        "git_branch": None,
        "source_ref": None,
        "base_commit": None,
        "detached_head": False,
        "execution_mode": None,
        "worktree": False,
    }


@pytest.mark.asyncio
async def test_restore_rebuilds_from_sealed_seed_when_resume_fails():
    coordinator, gateway, bindings = _coordinator()
    gateway.discovered = _Runtime()
    gateway.resume_error = DshRuntimeError("session is not live: sess-old")
    gateway.export_result = {
        "found": True,
        "seed": [{"type": "message", "data": {}}],
        "seedSignature": "sig",
        "seedSourceInstanceId": "instance-a",
        "seedSourceSessionId": "sess-old",
    }

    new_binding = await coordinator.restore(_binding())

    assert new_binding["binding_id"] == "binding-new"
    assert new_binding["kernel_session_id"] == "dsh-new"
    # The rebuild must ship the sealed seed to the target, not the stale
    # runtime/session local reference.
    (created,) = gateway.created
    assert created["sealed_seed"]["seedSourceInstanceId"] == "instance-a"
    assert created["sealed_seed"]["seedSignature"] == "sig"
    spec = created["request"].session_spec
    assert spec.seed_runtime_id is None and spec.seed_session_id is None
    assert new_binding["replaces_binding_id"] == "binding-old"


@pytest.mark.asyncio
async def test_restore_falls_back_to_unseeded_successor_when_no_seed_exists():
    coordinator, gateway, bindings = _coordinator()
    gateway.discovered = _Runtime()
    gateway.resume_error = DshRuntimeError("session is not live: sess-old")
    gateway.export_result = {
        "found": False,
        "seed": None,
        "seedSignature": None,
        "seedSourceInstanceId": None,
        "seedSourceSessionId": None,
    }

    new_binding = await coordinator.restore(_binding())

    assert new_binding["kernel_session_id"] == "dsh-new"
    (created,) = gateway.created
    assert created["sealed_seed"] is None
    # No live seed anywhere: the successor at least references the old
    # session so the lineage is recorded where the kernel can use it.
    spec = created["request"].session_spec
    assert spec.seed_session_id == "sess-old"


@pytest.mark.asyncio
async def test_restore_success_path_never_touches_the_seed_fallback():
    coordinator, gateway, bindings = _coordinator()
    gateway.discovered = _Runtime()
    gateway.resume_error = None
    gateway.export_result = {"found": False, "seed": None}

    result = await coordinator.restore(_binding())

    assert result["binding_id"] == "binding-old"
    assert gateway.created == []
    assert bindings.created == []


@pytest.mark.asyncio
async def test_restore_does_not_fork_a_successor_on_a_transport_failure():
    """A host that is merely unreachable still holds the session: rebuilding
    would duplicate it, so a DshTransportError must propagate, not fall back
    to a seed rebuild."""
    coordinator, gateway, bindings = _coordinator()
    gateway.discovered = _Runtime()
    gateway.resume_error = DshTransportError("host unreachable")
    gateway.export_result = {
        "found": True,
        "seed": [{"type": "message", "data": {}}],
        "seedSignature": "sig",
    }

    with pytest.raises(DshTransportError):
        await coordinator.restore(_binding())

    assert gateway.created == []
    assert bindings.created == []

