"""Tests for the 021 production entry point (`/api/v1/context/*`).

QA finding: ``app.context_space.router`` had **zero** production imports — the
whole 021 layer (router + four tenant adapters + delegated visibility + trace)
existed and was green in tests but nothing in the running service could reach
it. These tests pin the HTTP surface that closes that gap.

D4: the endpoint resolves one server-built ``MemoryViewerContext`` and threads
it through as ``viewer=``; retired address segments must not leak content.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.endpoints import context_space
from app.memory.viewer import MemoryViewerContext


def _auth_payload(*, user_id="u1", tenant_id="t1", org_id=""):
    """Real ``resolve_session_user`` shape (B1 / DEP-1, no invented keys)."""
    return {
        "session": {"_id": "s1", "user_id": user_id, "tenant_id": tenant_id},
        "user": {
            "_id": user_id,
            "tenant_id": tenant_id,
            "status": "active",
            "primary_org_id": org_id,
        },
        "tenant_id": tenant_id,
        "org_id": org_id,
    }


@pytest.fixture
def client(monkeypatch):
    """A minimal app with only the 021 router, plus a stubbed auth resolver."""
    app = FastAPI()
    app.include_router(context_space.router)

    async def _fake_resolve(authorization: str):
        return _auth_payload()

    monkeypatch.setattr("app.api.endpoints.auth._resolve_session_user", _fake_resolve)

    # Identity lookups are pinned on the D4 load_* seam so these HTTP tests
    # never need a live Mongo. No fabricated auth keys are injected.
    async def _no_roles(db, tenant_id, user_id):
        return frozenset()

    async def _no_projects(db, tenant_id, user_id):
        return frozenset()

    async def _no_departments(db, tenant_id, user_id, *, fallback_primary_org_id=""):
        return frozenset(), fallback_primary_org_id

    monkeypatch.setattr("app.memory.viewer.load_role_keys", _no_roles)
    monkeypatch.setattr("app.memory.viewer.load_visible_project_keys", _no_projects)
    monkeypatch.setattr("app.memory.viewer.load_visible_department_ids", _no_departments)
    return TestClient(app)


def test_resolve_rejects_empty_request(client):
    r = client.post("/api/v1/context/resolve", json={})
    assert r.status_code == 400
    assert "uri" in r.json()["detail"]


def test_resolve_rejects_oversized_batch(client):
    r = client.post("/api/v1/context/resolve", json={"uris": [f"mogo://memory/x/{i}" for i in range(60)]})
    assert r.status_code == 400
    assert "50" in r.json()["detail"]


def test_resolve_unknown_root_is_client_error(client):
    """An unknown root is a malformed address → 400, not a 500."""
    r = client.post("/api/v1/context/resolve", json={"uri": "mogo://nope/x"})
    assert r.status_code == 400
    assert "unknown context root" in r.json()["detail"]


def test_resolve_non_mogo_uri_is_client_error(client):
    r = client.post("/api/v1/context/resolve", json={"uri": "http://example.com"})
    assert r.status_code == 400


def test_resolve_missing_address_reports_per_item(client):
    """A missing address must fail only that item, not the whole batch."""
    r = client.post(
        "/api/v1/context/resolve",
        json={"uris": ["mogo://memory/personal/u1/does-not-exist/L0"]},
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["resolved_count"] == 0
    assert data["failed_count"] == 1
    item = data["items"][0]
    assert item["ok"] is False
    # reason 可能为 "visibility_denied"、"unresolved:<ExceptionName>"（router 层）
    # 或 "<ExceptionName>"（endpoint 层对未知异常的兜底格式）。
    r = item["reason"]
    assert r == "visibility_denied" or r.startswith("unresolved:") or not r.startswith("internal_error"), (
        f"unexpected reason: {r!r}"
    )


@pytest.mark.parametrize("legacy_scope", ["workspace", "org"])
def test_resolve_legacy_scope_address_does_not_leak_content(client, legacy_scope):
    """D4: retired segments are rejected (400) or reported as a failed item;
    under no circumstance may stored memory content be returned."""
    r = client.post(
        "/api/v1/context/resolve",
        json={"uri": f"mogo://memory/{legacy_scope}/u1/m-1/L0"},
    )
    body = r.text
    assert "raw body" not in body
    assert "one-line summary" not in body
    if r.status_code == 200:
        item = r.json()["data"]["items"][0]
        assert item["ok"] is False
        assert item["resolved"] is None
    else:
        # D4: a retired memory address is not found (404) / rejected (400),
        # never resolved and never leaked.
        assert r.status_code in (400, 404)


def test_resolve_tenant_mismatch_reports_visibility_denied(client):
    """Cross-tenant address → per-item visibility_denied (no data leak)."""
    r = client.post(
        "/api/v1/context/resolve",
        json={"uri": "mogo://resource/doc/OTHER-TENANT/doc-1/c1/L0"},
    )
    assert r.status_code == 200
    item = r.json()["data"]["items"][0]
    assert item["ok"] is False
    assert item["reason"] == "visibility_denied"
    assert item["resolved"] is None


def test_trace_readback_roundtrip(client, monkeypatch):
    """A recorded trace must be retrievable by id (FR-17 replay)."""
    context_space._TRACE_RING.clear()

    async def _fake_resolve_memory(uri, **kwargs):
        return {
            "resolved": {"uri": uri, "tier_used": "L0", "content": "x", "meta": {}},
            "trace": {
                "trace_id": "trace-abc",
                "session_id": "s1",
                "turn_id": "t1",
                "candidates": [],
                "skipped": [],
            },
        }

    monkeypatch.setattr("app.api.endpoints.context_space.resolve_memory", _fake_resolve_memory)

    r = client.post("/api/v1/context/resolve", json={"uri": "mogo://memory/personal/u1/m-1/L0"})
    assert r.status_code == 200
    assert r.json()["data"]["resolved_count"] == 1

    r2 = client.get("/api/v1/context/trace/trace-abc")
    assert r2.status_code == 200
    assert r2.json()["data"]["trace"]["trace_id"] == "trace-abc"

    context_space._TRACE_RING.clear()


def test_trace_missing_returns_404(client):
    context_space._TRACE_RING.clear()
    r = client.get("/api/v1/context/trace/does-not-exist")
    assert r.status_code == 404


def test_trace_ring_is_bounded(client):
    """The trace ring must evict rather than grow without limit."""
    context_space._TRACE_RING.clear()
    for i in range(context_space._TRACE_RING_SIZE + 20):
        context_space._remember_trace({"trace_id": f"t{i}", "candidates": []})
    assert len(context_space._TRACE_RING) == context_space._TRACE_RING_SIZE
    context_space._TRACE_RING.clear()


def test_trace_readback_is_tenant_scoped(client, monkeypatch):
    """R3: a trace recorded under one tenant must not be readable by another.

    The ring is process-wide, so without the tenant guard any authenticated user
    could replay another tenant's retrieval trace by id.
    """
    context_space._TRACE_RING.clear()
    context_space._remember_trace({"trace_id": "trace-t1", "candidates": []}, "t1")

    # The default client authenticates as tenant t1 → allowed.
    assert client.get("/api/v1/context/trace/trace-t1").status_code == 200

    async def _other_tenant(authorization: str):
        return _auth_payload(user_id="u9", tenant_id="t2")

    monkeypatch.setattr("app.api.endpoints.auth._resolve_session_user", _other_tenant)
    # 404 (not 403) so the trace's existence is not disclosed.
    assert client.get("/api/v1/context/trace/trace-t1").status_code == 404
    context_space._TRACE_RING.clear()


def test_resolve_passes_server_resolved_viewer(client, monkeypatch):
    """B1 / DEP-1 / D4: the 021 endpoint must pass one real viewer context,
    never an empty viewer_id or a fabricated identity dict."""
    captured: dict = {}

    async def _fake_resolve_memory(uri, **kwargs):
        captured.update(kwargs)
        return {
            "resolved": {"uri": uri, "tier_used": "L0", "content": "x", "meta": {}},
            "trace": {},
        }

    monkeypatch.setattr("app.api.endpoints.context_space.resolve_memory", _fake_resolve_memory)
    r = client.post("/api/v1/context/resolve", json={"uri": "mogo://memory/personal/u1/m-1/L0"})
    assert r.status_code == 200

    viewer = captured["viewer"]
    assert isinstance(viewer, MemoryViewerContext)
    assert viewer.user_id == "u1"          # was "" before B1
    assert viewer.tenant_id == "t1"
    # D4: the scattered B1 kwargs are gone.
    for retired in ("viewer_id", "viewer_role", "is_workspace_member", "viewer_org_id"):
        assert retired not in captured


def test_router_is_registered_in_main():
    """Regression: the router must be wired into the running app."""
    import app.main as main_mod

    src = open(main_mod.__file__, encoding="utf-8").read()
    assert "app.include_router(context_space.router)" in src, (
        "021 router is not registered in main.py — the address space is unreachable in production"
    )
