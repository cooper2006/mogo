"""Tests for the tenant purge pipeline (T045–T053) — FR-028 / FR-031 / FR-033.

Purge had no test coverage at all before this file, which is how the FR-033
inversion (a failed purge still writing the tombstone) and the incomplete
collection list slipped through. The fake below implements only the operations
``tenant_purge`` performs, plus ``$ne`` filters, and lets individual phases be
replaced so failures can be injected deterministically.
"""

from __future__ import annotations

import asyncio

import pytest

from app.services import tenant_purge

MAIN_ID = "acme-1a2b3c4d5e6f7a8b9c0d1e2f"


# ---------------------------------------------------------------------------
# Minimal in-memory database
# ---------------------------------------------------------------------------


def _matches(doc: dict, flt: dict | None) -> bool:
    if not flt:
        return True
    for key, value in flt.items():
        actual = doc.get(key)
        if isinstance(value, dict):
            for op, operand in value.items():
                if op == "$ne" and actual == operand:
                    return False
                elif op == "$lt" and not (actual is not None and actual < operand):
                    return False
                elif op not in ("$ne", "$lt"):
                    raise AssertionError(f"unsupported operator in test fake: {op}")
        elif actual != value:
            return False
    return True


class _Result:
    def __init__(self, count: int = 0) -> None:
        self.deleted_count = count
        self.matched_count = count


class _MemCol:
    def __init__(self) -> None:
        self.docs: list[dict] = []

    async def find_one(self, flt, *args, **kwargs):
        for doc in self.docs:
            if _matches(doc, flt):
                return dict(doc)
        return None

    async def update_one(self, flt, update, upsert=False):
        for doc in self.docs:
            if _matches(doc, flt):
                doc.update(update.get("$set", {}))
                for key in update.get("$unset") or {}:
                    doc.pop(key, None)
                return _Result(1)
        return _Result(0)

    async def delete_many(self, flt):
        before = len(self.docs)
        self.docs = [doc for doc in self.docs if not _matches(doc, flt)]
        return _Result(before - len(self.docs))

    def find(self, flt, projection=None):
        rows = [dict(doc) for doc in self.docs if _matches(doc, flt)]

        class _Cursor:
            def __aiter__(self):
                self._it = iter(rows)
                return self

            async def __anext__(self):
                try:
                    return next(self._it)
                except StopIteration:  # pragma: no cover - defensive
                    raise StopAsyncIteration

        return _Cursor()


class _Mem:
    def __init__(self) -> None:
        self.collections: dict[str, _MemCol] = {}

    def __getitem__(self, name: str) -> _MemCol:
        return self.collections.setdefault(name, _MemCol())


def _patch(monkeypatch, mem: _Mem) -> None:
    monkeypatch.setattr(tenant_purge, "get_db", lambda: mem)
    # Fresh task store per test so state cannot leak between cases.
    monkeypatch.setattr(tenant_purge, "_task_store", tenant_purge._PurgeTaskStore())


def _seed(mem: _Mem, status: str = "archived") -> None:
    mem["tenants"].docs.append({"_id": "t1", "main_id": MAIN_ID, "name": "Acme", "status": status})
    mem["organizations"].docs.append({"main_id": MAIN_ID, "name": "Acme"})
    mem["chat_messages"].docs.append({"main_id": MAIN_ID, "content": "hi"})


def _no_phases(monkeypatch) -> None:
    async def ok(*args, **kwargs):
        return None

    monkeypatch.setattr(tenant_purge, "_phase_mongo", ok)
    monkeypatch.setattr(tenant_purge, "_phase_vectors", ok)
    monkeypatch.setattr(tenant_purge, "_phase_files", ok)


def _pp(monkeypatch) -> None:
    """Make the document-parser config look usable (force a real HTTP attempt)."""
    monkeypatch.setattr(tenant_purge.settings, "document_processing_service_token", "tok", raising=False)
    monkeypatch.setattr(tenant_purge.settings, "document_processing_base_url", "http://127.0.0.1:9", raising=False)


# ---------------------------------------------------------------------------
# FR-033: failure must keep the tenant archived
# ---------------------------------------------------------------------------


def test_failed_purge_does_not_write_tombstone(monkeypatch) -> None:
    """A failing phase leaves ``archived`` + a recorded reason, never ``purged``."""
    mem = _Mem()
    _seed(mem)
    _patch(monkeypatch, mem)
    _no_phases(monkeypatch)

    async def boom(*args, **kwargs):
        raise RuntimeError("weaviate down")

    monkeypatch.setattr(tenant_purge, "_phase_vectors", boom)

    asyncio.run(tenant_purge.run_purge(MAIN_ID, "task-1", actor="platform"))

    tenant = mem["tenants"].docs[0]
    assert tenant["status"] == "archived", "FR-033: tenant must stay archived after a failed purge"
    assert "weaviate down" in tenant["archive_reason"]
    assert "purged_at" not in tenant

    task = tenant_purge._task_store.get(f"{MAIN_ID}:task-1")
    assert task["status"] == "failed"
    assert "weaviate down" in task["error"]


def test_successful_purge_writes_tombstone(monkeypatch) -> None:
    mem = _Mem()
    _seed(mem)
    _patch(monkeypatch, mem)
    _no_phases(monkeypatch)

    asyncio.run(tenant_purge.run_purge(MAIN_ID, "task-2", actor="platform"))

    tenant = mem["tenants"].docs[0]
    assert tenant["status"] == "purged"
    assert tenant["purged_at"] is not None
    assert tenant_purge._task_store.get(f"{MAIN_ID}:task-2")["status"] == "done"


# ---------------------------------------------------------------------------
# FR-028: re-check status at execution time
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["active", "disabled", "purged"])
def test_purge_refuses_non_archived_tenant(monkeypatch, status: str) -> None:
    """A restore racing the background task must not destroy live data."""
    mem = _Mem()
    _seed(mem, status=status)
    _patch(monkeypatch, mem)
    _no_phases(monkeypatch)

    called = False

    async def spy(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(tenant_purge, "_phase_mongo", spy)

    asyncio.run(tenant_purge.run_purge(MAIN_ID, "task-3", actor="platform"))

    assert called is False, "no phase may run for a non-archived tenant"
    assert mem["organizations"].docs, "tenant data must be untouched"
    assert tenant_purge._task_store.get(f"{MAIN_ID}:task-3")["status"] == "failed"


def test_purge_aborts_when_tenant_row_missing(monkeypatch) -> None:
    mem = _Mem()
    _patch(monkeypatch, mem)
    _no_phases(monkeypatch)

    asyncio.run(tenant_purge.run_purge(MAIN_ID, "task-4", actor="platform"))

    assert tenant_purge._task_store.get(f"{MAIN_ID}:task-4")["status"] == "failed"


# ---------------------------------------------------------------------------
# FR-031 / SC-005: the collection list must actually cover tenant data
# ---------------------------------------------------------------------------


def test_collection_list_covers_chat_api_collections() -> None:
    """Regression for the §1 finding: 22 chat-api collections were unpurged."""
    covered = set(tenant_purge.TENANT_SCOPED_COLLECTIONS)
    for name in (
        "chat_messages",
        "chat_sessions",
        "user_skills",
        "skill_shares",
        "knowledge_resources",
        "resource_grants",
        "site_profiles",
        "desktop_projects",
        "end_user_sessions",
    ):
        assert name in covered, f"{name} must be purged"


def test_collection_list_uses_real_names() -> None:
    """``departments`` is a dead name; the real collection is ``org_units``."""
    assert "org_units" in tenant_purge.TENANT_SCOPED_COLLECTIONS
    assert "departments" not in tenant_purge.TENANT_SCOPED_COLLECTIONS
    for name in ("admin_presentation_settings", "page_collection_settings",
                 "user_quota_overrides", "organization_shortcut_schemes"):
        assert name in tenant_purge.TENANT_SCOPED_COLLECTIONS, f"{name} must be purged"


def test_governance_list_includes_hook_rules() -> None:
    assert "hook_rules" in tenant_purge.TENANT_GOVERNANCE_COLLECTIONS


def test_collection_lists_have_no_duplicates() -> None:
    scoped = tenant_purge.TENANT_SCOPED_COLLECTIONS
    assert len(scoped) == len(set(scoped))


def test_mongo_phase_deletes_tenant_rows(monkeypatch) -> None:
    """The mongo phase removes rows from both lists and leaves no tombstone."""
    mem = _Mem()
    _seed(mem)
    monkeypatch.setattr(tenant_purge, "get_db", lambda: mem)

    asyncio.run(tenant_purge._phase_mongo(MAIN_ID))

    assert mem["organizations"].docs == []
    assert mem["chat_messages"].docs == []
    # The tenant row survives so the caller can decide archived vs purged.
    assert mem["tenants"].docs[0]["status"] == "archived"


# ---------------------------------------------------------------------------
# Vector phase: failures must propagate (previously silent)
# ---------------------------------------------------------------------------


def test_vector_phase_raises_when_token_missing(monkeypatch) -> None:
    mem = _Mem()
    mem["knowledge_documents"].docs.append({"main_id": MAIN_ID, "document_id": "doc-1"})
    monkeypatch.setattr(tenant_purge, "get_db", lambda: mem)
    monkeypatch.setattr(tenant_purge.settings, "document_processing_service_token", "", raising=False)

    with pytest.raises(RuntimeError, match="not configured"):
        asyncio.run(tenant_purge._phase_vectors(MAIN_ID))


def test_vector_phase_raises_when_delete_fails(monkeypatch) -> None:
    mem = _Mem()
    mem["knowledge_documents"].docs.append({"main_id": MAIN_ID, "document_id": "doc-1"})
    monkeypatch.setattr(tenant_purge, "get_db", lambda: mem)
    _pp(monkeypatch)

    with pytest.raises(RuntimeError, match="vector delete failed"):
        asyncio.run(tenant_purge._phase_vectors(MAIN_ID))


def test_vector_phase_noop_without_documents(monkeypatch) -> None:
    mem = _Mem()
    monkeypatch.setattr(tenant_purge, "get_db", lambda: mem)
    monkeypatch.setattr(tenant_purge.settings, "document_processing_service_token", "", raising=False)
    asyncio.run(tenant_purge._phase_vectors(MAIN_ID))  # must not raise


# ---------------------------------------------------------------------------
# File phase: avatar directory name must match the writer
# ---------------------------------------------------------------------------


def test_file_phase_removes_avatar_dir_named_like_the_writer(monkeypatch, tmp_path) -> None:
    from app.api.routes.auth import _safe_path_part

    static_dir = tmp_path / "admin-static"
    knowledge_dir = tmp_path / "knowledge"
    avatar_dir = static_dir / "admin-avatars" / _safe_path_part(MAIN_ID, "default")
    avatar_dir.mkdir(parents=True)
    (avatar_dir / "a.png").write_bytes(b"x")
    other_tenant = static_dir / "admin-avatars" / "other-000000000000000000000000"
    other_tenant.mkdir(parents=True)
    (knowledge_dir / MAIN_ID).mkdir(parents=True)

    monkeypatch.setattr(tenant_purge.settings, "admin_static_dir", str(static_dir), raising=False)
    monkeypatch.setattr(tenant_purge.settings, "knowledge_local_storage_dir", str(knowledge_dir), raising=False)

    asyncio.run(tenant_purge._phase_files(MAIN_ID))

    assert not avatar_dir.exists(), "the tenant's own avatar directory must be removed"
    assert not (knowledge_dir / MAIN_ID).exists()
    assert other_tenant.exists(), "another tenant's avatar directory must be untouched"


def test_tombstone_reaper_uses_retention_window() -> None:
    assert tenant_purge.TOMBSTONE_RETENTION.days == 30
