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
                elif op == "$in" and actual not in operand:
                    return False
                elif op not in ("$ne", "$lt", "$in"):
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
        if upsert:
            # Insert a new document seeded from the filter + $set payload.
            new_doc = {k: v for k, v in flt.items() if not isinstance(v, dict)}
            new_doc.update(update.get("$setOnInsert", {}))
            new_doc.update(update.get("$set", {}))
            self.docs.append(new_doc)
            return _Result(1)
        return _Result(0)

    async def delete_many(self, flt):
        before = len(self.docs)
        self.docs = [doc for doc in self.docs if not _matches(doc, flt)]
        return _Result(before - len(self.docs))

    async def distinct(self, key, flt=None):
        seen = []
        for doc in self.docs:
            if _matches(doc, flt) and doc.get(key) is not None:
                if doc[key] not in seen:
                    seen.append(doc[key])
        return seen

    def find(self, flt, projection=None):
        rows = [dict(doc) for doc in self.docs if _matches(doc, flt)]

        class _Cursor:
            def __init__(self, initial_rows):
                self._rows = list(initial_rows)
                self._it = iter(self._rows)

            def sort(self, key, direction=1):
                self._rows = sorted(
                    self._rows,
                    key=lambda d: str(d.get(key) or ""),
                    reverse=(direction == -1),
                )
                self._it = iter(self._rows)
                return self

            def to_list(self, length=None):
                data = self._rows
                if length is not None:
                    data = data[:length]
                return data

            def __aiter__(self):
                self._it = iter(self._rows)
                return self

            async def __anext__(self):
                try:
                    return next(self._it)
                except StopIteration:  # pragma: no cover - defensive
                    raise StopAsyncIteration

        return _Cursor(rows)


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
    mem["tenants"].docs.append({"_id": "t1", "tenant_id": MAIN_ID, "name": "Acme", "status": status})
    mem["organizations"].docs.append({"tenant_id": MAIN_ID, "name": "Acme"})
    mem["chat_messages"].docs.append({"tenant_id": MAIN_ID, "content": "hi"})


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


def test_collection_list_covers_tenant_id_partitioned_collections() -> None:
    """Regression: 5 governance collections were missing from the purge lists.

    These are all partitioned by ``tenant_id`` (not ``tenant_id``), so they were
    invisible to the pass that scanned for ``tenant_id`` writes.
    """
    governance = set(tenant_purge.TENANT_GOVERNANCE_COLLECTIONS)
    for name in (
        "agent_kernel_bindings",
        "enterprise_authoritative_deliveries",
        "presentation_generation_jobs",
        "runtime_profile_versions",
        "runtime_profile_audit",
        # Found by scanning collection-name literals instead of constants:
        # ``business_semantic_index.py`` uses ``db["business_entity_index"]``
        # directly, so no ``*_COLLECTION`` constant ever named it.
        "business_entity_index",
    ):
        assert name in governance, f"{name} is tenant_id-partitioned and must be purged"


def test_collection_list_covers_tenant_id_partitioned_preferences() -> None:
    """``user_shortcut_preferences`` and ``session_snapshots`` carry ``tenant_id``."""
    scoped = set(tenant_purge.TENANT_SCOPED_COLLECTIONS)
    for name in ("user_shortcut_preferences", "session_snapshots"):
        assert name in scoped, f"{name} carries tenant_id and must be purged"


def test_session_shares_is_resolved_not_matched() -> None:
    """``session_shares`` has no tenant key, so a plain sweep cannot find it.

    Putting it in either keyed list would look correct and silently delete
    nothing (there is no ``tenant_id``/``tenant_id`` field to match). It belongs
    to ``TENANT_ORPHANED_COLLECTIONS``, which is cascaded from ``chat_sessions``.
    """
    assert "session_shares" in tenant_purge.TENANT_ORPHANED_COLLECTIONS
    assert "session_shares" not in tenant_purge.TENANT_SCOPED_COLLECTIONS
    assert "session_shares" not in tenant_purge.TENANT_GOVERNANCE_COLLECTIONS


def test_every_tenant_id_keyed_collection_in_the_tree_is_covered() -> None:
    """T045's own wording, turned into a guard: scan the tree, not memory.

    T045 said ``TENANT_SCOPED_COLLECTIONS`` should be "scanned from the
    collections that actually carry ``tenant_id``". The delivered artefact was a
    hand-written list, which is exactly why it drifted. This test does the
    scan for real, so drift fails CI instead of failing an audit.

    It greps every ``*_COLLECTION = "..."`` constant in both services, finds
    the ones whose write sites include a ``tenant_id``/``tenant_id`` key, and
    asserts they are covered (or explicitly exempted).
    """
    import re
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[3]
    services_root = repo_root / "services"

    # 1. Collect every collection-name constant declared in the tree.
    declared: dict[str, list[str]] = {}
    for path in services_root.rglob("*.py"):
        if ".venv" in path.parts or "venv" in path.parts:
            continue
        try:
            text = path.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        for match in re.finditer(r'[A-Za-z_]*COLLECTION\s*[:=]+\s*["\']([a-z0-9_]+)["\']', text):
            declared.setdefault(match.group(1), []).append(
                f"{path.relative_to(repo_root)}:{text[: match.start()].count(chr(10)) + 1}"
            )

    covered = (
        set(tenant_purge.TENANT_SCOPED_COLLECTIONS)
        | set(tenant_purge.TENANT_GOVERNANCE_COLLECTIONS)
        | set(tenant_purge.TENANT_ORPHANED_COLLECTIONS)
    )

    # 2. Exemptions, each with a reason. Anything not here must be covered.
    exempt = {
        # Global / platform singletons — never tenant-partitioned.
        "system_bootstrap",      # _id: "singleton"
        "capability_assets",     # find({}) global catalogue
        "admin_model_providers", # global provider seeds
        "admin_sessions",        # session-id keyed
        # 016 collector high-water mark: one global doc (_id="skill_activity"),
        # carries no tenant key at all — nothing tenant-specific to purge.
        "skill_quality_collector_state",
        # Orchestration DAG registry (005/012): keyed by orchestration_id only,
        # a platform-wide development source of truth, not tenant-partitioned.
        "dag_definitions",
        # Purge survives these on purpose (see the sibling test).
        "system_audit_logs",
        "tenants",
        # Transient, no business value, TTL or presence-only.
        "end_user_login_challenges",
        "presence_heartbeats",
        "session_presence_state",
    }

    missing = sorted(name for name in declared if name not in covered and name not in exempt)
    assert not missing, (
        "collections declared in the tree are missing from the purge lists — "
        + ", ".join(f"{n} ({declared[n][0]})" for n in missing[:12])
    )

    # 3. The reverse direction: everything the lists claim to purge must be a
    #    collection that actually exists in the tree, or a known literal-name
    #    one (chat-api writes some collections via ``db["name"]`` literals with
    #    no constant at all — ``business_entity_index`` was missed for exactly
    #    this reason). A typo'd name here deletes nothing, silently.
    literal_only = {
        "business_entity_index",
        "chat_messages",
        "chat_sessions",
        "desktop_projects",
        "execution_logs",
        "project_memories",
        "site_profiles",
        "skill_packages",
        "user_skills",
    }
    unknown = sorted(name for name in covered if name not in declared and name not in literal_only)
    assert not unknown, f"purge lists reference collections that do not exist: {unknown}"
    # The literal-only escape hatch must not become a dumping ground.
    assert len(literal_only - set(declared)) == len(literal_only), (
        "a name in ``literal_only`` is now declared as a constant — drop it "
        "from the escape hatch so the scan covers it properly"
    )


def test_transient_collections_are_exempt_not_forgotten() -> None:
    """Presence/heartbeat rows have no tenant key and no business value.

    They are session-scoped and TTL'd, so there is nothing to "leak" once the
    session itself is gone. Pinned as an explicit decision (see quickstart §7)
    rather than an omission.
    """
    covered = (
        set(tenant_purge.TENANT_SCOPED_COLLECTIONS)
        | set(tenant_purge.TENANT_GOVERNANCE_COLLECTIONS)
        | set(tenant_purge.TENANT_ORPHANED_COLLECTIONS)
    )
    for name in ("presence_heartbeats", "session_presence_state", "capability_assets"):
        assert name not in covered, f"{name} holds no tenant data; exempt by decision"


def test_platform_side_collections_are_deliberately_exempt() -> None:
    """Two collections hold *platform* records and must NOT be swept.

    - ``system_audit_logs`` *is* keyed by ``tenant_id``, but the rows record what
      the platform administrator did **to** a tenant. Deleting them on purge
      would erase the very trail SC-007 exists to keep. This is the §1.3
      decision, now written down as an executable answer rather than a comment.
    - ``tenants`` is the registry itself; it is turned into a tombstone by
      ``run_purge`` instead of being deleted.
    """
    for name in ("system_audit_logs", "tenants"):
        assert name not in tenant_purge.TENANT_SCOPED_COLLECTIONS, f"{name} must survive the sweep"
        assert name not in tenant_purge.TENANT_GOVERNANCE_COLLECTIONS


def test_collection_lists_have_no_duplicates() -> None:
    scoped = tenant_purge.TENANT_SCOPED_COLLECTIONS
    assert len(scoped) == len(set(scoped))


# ---------------------------------------------------------------------------
# Audit P2 (accepted): the in-memory task store must be bounded
# ---------------------------------------------------------------------------


def test_task_store_is_bounded() -> None:
    """A long-lived process must not accumulate a task entry per purge forever.

    The store is in-memory (audit P2), so the least we can do is cap it. This
    pins the cap: without it, a deployment purging thousands of tenants would
    leak one dict entry each, in a process meant to run for months.
    """
    store = tenant_purge._PurgeTaskStore()
    cap = tenant_purge._PurgeTaskStore._MAX_TASKS
    assert cap > 0

    for i in range(cap + 50):
        store.create(f"tenant-{i}", f"task-{i}")

    assert len(store._tasks) <= cap, "task map grew past its bound"
    assert len(store._tenant_id_to_task) <= cap, "index grew past its bound"


def test_task_store_eviction_clears_the_index() -> None:
    """Evicting a task must not leave the tenant_id index pointing at nothing.

    ``get_for_tenant_id`` resolves through ``_tenant_id_to_task``; a stale entry
    there would make it return ``None`` for a tenant whose purge we dropped,
    which reads as "never purged" rather than "forgotten". Both are wrong, but
    the stale-index version is the one that looks like a bug in the caller.
    """
    store = tenant_purge._PurgeTaskStore()
    cap = tenant_purge._PurgeTaskStore._MAX_TASKS

    store.create("tenant-0", "task-0")
    for i in range(1, cap + 10):
        store.create(f"tenant-{i}", f"task-{i}")

    # "tenant-0" was evicted, so its index entry must have gone with it.
    assert store.get_for_tenant_id("tenant-0") is None
    # The newest tenant is still resolvable.
    assert store.get_for_tenant_id(f"tenant-{cap + 9}") is not None
    # Every surviving index entry points at a task that actually exists.
    for tenant_id, key in store._tenant_id_to_task.items():
        assert store.get(key) is not None, f"stale index entry for {tenant_id}"


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
# Collections with no tenant key — purged by cascading from the parent
# ---------------------------------------------------------------------------


def test_shares_are_purged_by_cascading_from_sessions(monkeypatch) -> None:
    """``session_shares`` carries no tenant key, so it is resolved via sessions.

    A share row is only ``share_id`` / ``session_id`` / ``snapshot_id`` —
    ``ShareStore`` never persists the tenant. Without the cascade, a purged
    tenant's share tokens live forever with no way to attribute them.
    """
    mem = _Mem()
    _seed(mem)
    mem["chat_sessions"].docs.append({"_id": "s1", "tenant_id": MAIN_ID})
    mem["chat_sessions"].docs.append({"_id": "s2", "tenant_id": MAIN_ID})
    # A session belonging to someone else must be left alone.
    mem["chat_sessions"].docs.append({"_id": "s9", "tenant_id": "other-tenant"})
    mem["session_shares"].docs.append({"share_id": "sh1", "session_id": "s1"})
    mem["session_shares"].docs.append({"share_id": "sh2", "session_id": "s2"})
    mem["session_shares"].docs.append({"share_id": "sh9", "session_id": "s9"})
    monkeypatch.setattr(tenant_purge, "get_db", lambda: mem)

    asyncio.run(tenant_purge._phase_mongo(MAIN_ID))

    left = [doc["share_id"] for doc in mem["session_shares"].docs]
    assert "sh1" not in left, "shares of the purged tenant must go"
    assert "sh2" not in left
    assert left == ["sh9"], f"another tenant's share must survive, got {left}"


def test_cascade_needs_sessions_so_ordering_matters(monkeypatch) -> None:
    """The cascade resolves shares through sessions, so ordering is load-bearing.

    If someone moved ``session_shares`` into ``TENANT_SCOPED_COLLECTIONS`` it
    would match on ``tenant_id`` and delete nothing (that field is not stored
    there). This pins that the real thing works — and the sibling test above
    proves it works through the full phase, i.e. while sessions still exist.
    """
    mem = _Mem()
    monkeypatch.setattr(tenant_purge, "get_db", lambda: mem)

    # A tenant with no sessions at all must not blow up or delete anything.
    mem["session_shares"].docs.append({"share_id": "other", "session_id": "nope"})
    asyncio.run(tenant_purge._purge_key_only_collections(mem, MAIN_ID))
    assert len(mem["session_shares"].docs) == 1, "no sessions → no cascade, nothing deleted"

    # With a session of our own, its share goes.
    mem["chat_sessions"].docs.append({"_id": "s1", "tenant_id": MAIN_ID})
    mem["session_shares"].docs.append({"share_id": "mine", "session_id": "s1"})
    asyncio.run(tenant_purge._purge_key_only_collections(mem, MAIN_ID))
    left = [doc["share_id"] for doc in mem["session_shares"].docs]
    assert left == ["other"], f"only our share should go, got {left}"


# ---------------------------------------------------------------------------
# Vector phase: failures must propagate (previously silent)
# ---------------------------------------------------------------------------


def test_vector_phase_raises_when_token_missing(monkeypatch) -> None:
    mem = _Mem()
    mem["knowledge_documents"].docs.append({"tenant_id": MAIN_ID, "document_id": "doc-1"})
    monkeypatch.setattr(tenant_purge, "get_db", lambda: mem)
    monkeypatch.setattr(tenant_purge.settings, "document_processing_service_token", "", raising=False)

    with pytest.raises(RuntimeError, match="not configured"):
        asyncio.run(tenant_purge._phase_vectors(MAIN_ID))


def test_vector_phase_raises_when_delete_fails(monkeypatch) -> None:
    mem = _Mem()
    mem["knowledge_documents"].docs.append({"tenant_id": MAIN_ID, "document_id": "doc-1"})
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


# ---------------------------------------------------------------------------
# FR-032: purge progress persisted cross-replica (020 residual, 续五十八)
# ---------------------------------------------------------------------------


def test_purge_progress_persists_to_mongo(monkeypatch) -> None:
    """A completed purge leaves a document in tenant_purge_progress that a
    *different* process (fresh in-memory store) can still read."""
    mem = _Mem()
    _seed(mem)
    _patch(monkeypatch, mem)
    _no_phases(monkeypatch)

    # Simulate run_purge with a fresh store (replica A).
    store_a = tenant_purge._PurgeTaskStore()
    asyncio.run(_run_with_store(store_a, mem))

    # Replica B: brand-new in-memory store, same Mongo.
    store_b = tenant_purge._PurgeTaskStore()
    result = asyncio.run(store_b.get_persisted(MAIN_ID, "task-1"))
    assert result is not None, "progress must survive across processes via Mongo"
    assert result["status"] == "done"
    assert result["progress"] == {"mongo": "done", "vectors": "done", "files": "done"}


async def _run_with_store(store, mem) -> None:
    """Run the real pipeline against a given store + Mongo (no monkeypatch of
    the module-level _task_store, so the Mongo side effects are observable)."""
    tenant_id = MAIN_ID
    task_id = "task-1"
    store.create(tenant_id, task_id)

    db = mem
    tenant = await db["tenants"].find_one({"tenant_id": tenant_id}, {"status": 1})
    assert tenant and tenant["status"] == "archived"

    await store.mark_persisted(tenant_id, task_id, "mongo", "running")
    await tenant_purge._phase_mongo(tenant_id)
    await store.mark_persisted(tenant_id, task_id, "mongo", "done")
    await store.mark_persisted(tenant_id, task_id, "vectors", "done")
    await store.mark_persisted(tenant_id, task_id, "files", "done")
    await store.finish_persisted(tenant_id, task_id, True, "")


def test_get_purge_status_falls_back_to_mongo(monkeypatch) -> None:
    """get_purge_status: no in-memory task, but Mongo has one → Mongo wins
    over the 'unknown' default."""
    mem = _Mem()
    _seed(mem)
    _patch(monkeypatch, mem)

    # Seed a persisted progress doc directly (as if replica A ran the purge).
    mem["tenant_purge_progress"].docs.append({
        "tenant_id": MAIN_ID,
        "task_id": "task-9",
        "status": "done",
        "progress": {"mongo": "done", "vectors": "done", "files": "done"},
        "error": "",
        "started_at": None,
        "updated_at": None,
    })

    # Fresh empty store → no in-memory hit.
    monkeypatch.setattr(tenant_purge, "_task_store", tenant_purge._PurgeTaskStore())

    result = asyncio.run(tenant_purge.get_purge_status(MAIN_ID, "task-9"))
    assert result["status"] == "done"
    assert result["progress"]["mongo"] == "done"


def test_get_purge_status_unknown_when_nothing_anywhere(monkeypatch) -> None:
    """No in-memory task, no Mongo doc, tenant not purged → unknown + empty
    progress (honest, not fabricated)."""
    mem = _Mem()
    _seed(mem)  # tenant row is 'archived', not 'purged'
    _patch(monkeypatch, mem)
    monkeypatch.setattr(tenant_purge, "_task_store", tenant_purge._PurgeTaskStore())

    result = asyncio.run(tenant_purge.get_purge_status(MAIN_ID))
    assert result["status"] == "unknown"
    assert result["progress"] == {}


def test_mark_persisted_degrades_when_mongo_unavailable(monkeypatch) -> None:
    """Mongo failure: mark_persisted still updates in-memory state and does not
    raise (offline degradation, no fabricated success)."""
    mem = _Mem()
    _seed(mem)
    _patch(monkeypatch, mem)
    _no_phases(monkeypatch)

    store = tenant_purge._PurgeTaskStore()
    monkeypatch.setattr(tenant_purge, "_task_store", store)

    # Break Mongo: make update_one raise.
    def _boom(self, flt, update, upsert=False):
        raise RuntimeError("mongo down")
    monkeypatch.setattr(_MemCol, "update_one", _boom)

    store.create(MAIN_ID, "task-x")
    # Must not raise even though Mongo is down.
    asyncio.run(store.mark_persisted(MAIN_ID, "task-x", "mongo", "running"))
    task = store.get(f"{MAIN_ID}:task-x")
    assert task["progress"]["mongo"] == "running", "in-memory state must still advance"

    # get_persisted returns None when Mongo is unavailable.
    assert asyncio.run(store.get_persisted(MAIN_ID, "task-x")) is None
