"""Integration tests for 021 adapters + router against a fake MongoDB.

Exercises every root (memory / resource / skill / session) through
``resolve_memory`` with a stubbed ``get_db`` so no real Mongo is required. The
backends' existing stores are mirrored by simple in-memory documents.
"""

from __future__ import annotations

import pytest

from app.context_space.router import ContextVisibilityError, resolve_memory
from app.memory.address import MemoryAddress


# --- fake mongo -------------------------------------------------------------

def _match(doc: dict, query: dict) -> bool:
    for key, cond in query.items():
        if key == "$or":
            if not any(_match(doc, sub) for sub in cond):
                return False
            continue
        if key == "$and":
            if not all(_match(doc, sub) for sub in cond):
                return False
            continue
        doc_val = doc.get(key)
        if isinstance(cond, dict) and any(k.startswith("$") for k in cond):
            for op, val in cond.items():
                if op == "$in":
                    if doc_val not in val:
                        return False
                elif op == "$exists":
                    if bool(val) != (key in doc):
                        return False
                elif op == "$eq":
                    if doc_val != val:
                        return False
                else:
                    if doc_val != val:
                        return False
        elif doc_val != cond:
            # Tolerate ObjectId/str mismatch in the fake store.
            try:
                if str(doc_val) != str(cond):
                    return False
            except Exception:
                return False
    return True


class _Cursor:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def sort(self, *a, **k):  # noqa: D401 - chainable no-op
        return self

    def limit(self, n):  # noqa: D401 - chainable no-op
        return _Cursor(self._rows[:n])

    async def to_list(self, length=None) -> list:
        return list(self._rows)


class _Collection:
    def __init__(self, docs: list) -> None:
        self._docs = docs

    def find(self, query: dict) -> _Cursor:
        return _Cursor([d for d in self._docs if _match(d, query)])

    async def find_one(self, query: dict):
        for d in self._docs:
            if _match(d, query):
                return d
        return None


class _FakeDb(dict):
    def __getitem__(self, name: str) -> _Collection:
        if name not in self:
            self[name] = _Collection([])
        return super().__getitem__(name)


@pytest.fixture
def fake_db(monkeypatch):
    db = _FakeDb()
    # `from app.core.db import get_db` copies the binding into each adapter
    # module, so patch it everywhere it is referenced.
    for target in (
        "app.core.db.get_db",
        "app.context_space.adapters.resource.get_db",
        "app.context_space.adapters.skill.get_db",
        "app.context_space.adapters.session.get_db",
    ):
        monkeypatch.setattr(target, lambda: db)
    for target in (
        "app.core.tenant.add_main_scope",
        "app.context_space.adapters.resource.add_main_scope",
        "app.context_space.adapters.skill.add_main_scope",
        "app.context_space.adapters.session.add_main_scope",
        "app.core.tenant.resolve_main_id",
        "app.context_space.adapters.resource.resolve_main_id",
        "app.context_space.adapters.skill.resolve_main_id",
        "app.context_space.adapters.session.resolve_main_id",
    ):
        if "add_main_scope" in target:
            monkeypatch.setattr(target, lambda q, _m=None: q)
        else:
            monkeypatch.setattr(target, lambda t: t)
    return db


# --- memory (017): reuse the existing in-memory MemoryStore via monkeypatch ----

class _FakeMemoryStore:
    def __init__(self) -> None:
        self._mem = {
            "m-1": _mem_row("personal", "u1", "one-line summary", "overview", "raw body"),
        }

    async def get(self, *, tenant_id: str, memory_id: str):
        row = self._mem.get(memory_id)
        if row is None:
            return None
        from app.memory.scope import Memory

        return Memory(
            memory_id=memory_id,
            content=row["content"],
            scope=row["scope"],
            owner_id=row["owner_id"],
            l0_summary=row["l0"],
            l1_overview=row["l1"],
            source_session_id=row.get("source_session_id", ""),
            source_type=row.get("source_type", ""),
        )


def _mem_row(scope, owner, l0, l1, content, source_session_id="", source_type=""):
    return {
        "scope": scope,
        "owner_id": owner,
        "l0": l0,
        "l1": l1,
        "content": content,
        "source_session_id": source_session_id,
        "source_type": source_type,
    }


@pytest.fixture
def memory_store(monkeypatch):
    store = _FakeMemoryStore()
    monkeypatch.setattr(
        "app.context_space.adapters.memory.MemoryStore", lambda: store
    )
    return store


# --- documents for resource / skill / session -------------------------------

def _seed(db: _FakeDb) -> None:
    db["knowledge_document_chunks"] = _Collection(
        [
            {
                "main_id": "t1",
                "document_id": "doc-1",
                "chunk_id": "c1",
                "text": "the full chunk text body",
                "contextualText": "contextual summary of chunk",
                "titlePath": ["Chapter 1", "Section A"],
                "pageNo": 3,
                "contentType": "text",
            }
        ]
    )
    db["business_entity_index"] = _Collection(
        [
            {
                "entity_id": "rec-7",
                "tenant_id": "t1",
                "entity_type": "customer",
                "title": "Acme Corp",
                "source_ref": "crm:acme",
                "fields": {"region": "EU", "tier": "gold"},
            }
        ]
    )
    db["kg_nodes"] = _Collection(
        [
            {
                "node_id": "n-42",
                "tenant_id": "t1",
                "entity_type": "person",
                "name": "Alice",
                "attributes": {"role": "engineer"},
                "source_ref": "hr:alice",
                "confidence": 1.0,
                "conflicted": False,
            }
        ]
    )
    db["kg_edges"] = _Collection([])
    db["user_skills"] = _Collection(
        [
            {
                "_id": "sk-1",
                "name": "PDF extractor",
                "summary": "extracts tables from PDFs",
                "description": "extracts tables",
                "category": "parsing",
                "contract_json": {
                    "input_profile": {"file": "pdf"},
                    "output_profile": {"tables": "csv"},
                    "applicable_scenarios": "when user uploads a PDF",
                },
                "skill_markdown": "# PDF extractor\nfull doc",
                "published_version": "v1",
            }
        ]
    )
    db["skill_releases"] = _Collection([])
    db["capability_assets"] = _Collection(
        [
            {
                "key": "asset-9",
                "display_name": "Search Tool",
                "asset_type": "tool",
                "owner": "team-a",
                "version": "1",
                "contract": {"input": "query", "output": "results"},
                "status": "active",
                "a2a_exposed": True,
            }
        ]
    )
    db["chat_sessions"] = _Collection(
        [
            {
                "_id": "507f1f77bcf86cd799439011",
                # 002 ownership: sessions are read with a ``user_id`` filter
                # everywhere else in the app; the 021 adapter must match.
                "user_id": "u1",
                "title": "Planning",
                "summary": "roadmap",
                "message_count": 2,
                "active_document": "doc-x",
                "multi_user": False,
            }
        ]
    )
    db["chat_messages"] = _Collection(
        [
            {"session_id": "507f1f77bcf86cd799439011", "role": "user", "content": "hello"},
            {"session_id": "507f1f77bcf86cd799439011", "role": "assistant", "content": "hi there"},
        ]
    )


# --- tests ------------------------------------------------------------------

async def test_resolve_memory_root(fake_db, memory_store) -> None:
    _seed(fake_db)
    out = await resolve_memory(
        "mogo://memory/personal/u1/m-1/L0",
        tenant_id="t1",
        viewer_id="u1",
    )
    assert out["resolved"]["content"] == "one-line summary"
    assert out["trace"]["candidates"][0]["uri"].startswith("mogo://memory/")


async def test_resolve_resource_doc(fake_db, memory_store) -> None:
    _seed(fake_db)
    out = await resolve_memory(
        "mogo://resource/doc/t1/doc-1/c1/L0", tenant_id="t1", viewer_id="u1"
    )
    assert "Chapter 1" in out["resolved"]["content"]
    assert out["resolved"]["meta"]["subtype"] == "doc"


async def test_resolve_resource_doc_l2(fake_db, memory_store) -> None:
    _seed(fake_db)
    out = await resolve_memory(
        "mogo://resource/doc/t1/doc-1/c1/L2", tenant_id="t1", viewer_id="u1"
    )
    assert out["resolved"]["content"] == "the full chunk text body"


async def test_resolve_resource_biz(fake_db, memory_store) -> None:
    _seed(fake_db)
    out = await resolve_memory(
        "mogo://resource/biz/t1/crm/customer/rec-7", tenant_id="t1", viewer_id="u1"
    )
    assert out["resolved"]["content"].startswith("Acme Corp")
    assert out["resolved"]["meta"]["entity_type"] == "customer"


async def test_resolve_resource_kg(fake_db, memory_store) -> None:
    _seed(fake_db)
    out = await resolve_memory(
        "mogo://resource/kg/t1/n-42", tenant_id="t1", viewer_id="u1"
    )
    assert out["resolved"]["content"] == "Alice"
    assert out["resolved"]["meta"]["neighbour_count"] == 0


async def test_resolve_resource_kg_l1_lists_neighbours(fake_db, memory_store) -> None:
    """L1 surfaces neighbour ids resolved by the single-node direct read."""
    _seed(fake_db)
    fake_db["kg_edges"] = _Collection(
        [
            {"tenant_id": "t1", "source": "n-42", "target": "n-7", "relation": "works_with"},
            {"tenant_id": "t1", "source": "n-42", "target": "n-9", "relation": "knows"},
        ]
    )
    out = await resolve_memory(
        "mogo://resource/kg/t1/n-42/L1", tenant_id="t1", viewer_id="u1"
    )
    content = out["resolved"]["content"]
    assert "type=person" in content
    assert "n-7" in content and "n-9" in content
    assert out["resolved"]["meta"]["neighbour_count"] == 2


async def test_resolve_resource_kg_does_not_load_whole_graph(fake_db, memory_store) -> None:
    """P1-3: the adapter must not pull the tenant's entire graph into memory.

    ``TenantKgStore._ensure_loaded`` fetches up to 2000 nodes / 5000 edges. The
    adapter now uses ``get_node_direct``, so the bulk loader must never run — we
    assert that by spying on it and by checking the node map stays empty.
    """
    from app.knowledge_graph import persisted_store as kg_mod

    bulk_loads: list[str] = []
    original = kg_mod.TenantKgStore._ensure_loaded

    async def _tracking(self):
        bulk_loads.append(self._tenant_id)
        await original(self)

    kg_mod.TenantKgStore._ensure_loaded = _tracking
    try:
        _seed(fake_db)
        out = await resolve_memory(
            "mogo://resource/kg/t1/n-42", tenant_id="t1", viewer_id="u1"
        )
    finally:
        kg_mod.TenantKgStore._ensure_loaded = original

    assert out["resolved"]["content"] == "Alice"
    assert bulk_loads == [], "adapter must not trigger the whole-graph bulk load"


async def test_resolve_skill_defaults_to_l0(fake_db, memory_store) -> None:
    """No tier segment → L0 (one-line capability description, no contract)."""
    _seed(fake_db)
    out = await resolve_memory(
        "mogo://skill/t1/sk-1", tenant_id="t1", viewer_id="u1"
    )
    resolved = out["resolved"]
    assert resolved["tier_used"] == "L0"
    assert resolved["content"] == "PDF extractor — extracts tables from PDFs"
    assert "when:" not in resolved["content"]
    assert resolved["meta"]["skill_id"] == "sk-1"


async def test_resolve_skill_l1_contract(fake_db, memory_store) -> None:
    """L1 carries the contract summary (in/out/when); meta stays structured."""
    _seed(fake_db)
    out = await resolve_memory(
        "mogo://skill/t1/sk-1/L1", tenant_id="t1", viewer_id="u1"
    )
    resolved = out["resolved"]
    assert resolved["tier_used"] == "L1"
    content = resolved["content"]
    assert "when: when user uploads a PDF" in content
    assert "in: {'file': 'pdf'}" in content
    assert "out: {'tables': 'csv'}" in content
    # meta is tier-independent and must stay structured.
    assert resolved["meta"] == {
        "subtype": "skill",
        "skill_id": "sk-1",
        "name": "PDF extractor",
        "version": "v1",
        "category": "parsing",
        "a2a_exposed": False,
    }


async def test_resolve_skill_asset(fake_db, memory_store) -> None:
    _seed(fake_db)
    out = await resolve_memory(
        "mogo://skill/asset/asset-9", tenant_id="t1", viewer_id="u1"
    )
    assert out["resolved"]["content"] == "Search Tool"
    assert out["resolved"]["meta"]["a2a_exposed"] is True


async def test_skill_no_tenant_agnostic_fallback(fake_db, memory_store, monkeypatch) -> None:
    """C3 (2026-10-06 R2 遗留建议): skill resolution must not fall back to a
    tenant-agnostic ``_id`` lookup. A skill stored under another org's ``main_id``
    must resolve to 404, not leak across tenants.

    The shared ``fake_db`` fixture patches ``add_main_scope`` to a no-op so most
    adapter tests can ignore scoping.  This test restores the real
    ``add_main_scope`` / ``resolve_main_id`` so the scoping filter is applied.
    We inline the real implementations because the fixture has already patched
    the originals on the ``app.core.tenant`` module.
    """
    from app.context_space.visibility import ContextNotFoundError

    def _real_resolve_main_id(value=None) -> str:
        main_id = str(value or "").strip()
        return main_id or "default"

    def _real_add_main_scope(query, main_id=None):
        resolved = _real_resolve_main_id(main_id)
        base = dict(query or {})
        if resolved == "default":
            scope = {"$or": [
                {"main_id": resolved},
                {"main_id": {"$exists": False}},
                {"main_id": ""},
                {"main_id": None},
            ]}
            if not base:
                return scope
            return {"$and": [base, scope]}
        base.update({"main_id": resolved})
        return base

    # Seed a skill stored under main_id="org-A", but the request comes for
    # tenant "org-B" — the visibility guard passes (URI says org-B, tenant is
    # org-B), but the real scoping query looks for main_id="org-B" and finds
    # nothing.  The removed fallback would have found it by _id alone.
    fake_db["user_skills"] = _Collection(
        [
            {
                "_id": "sk-cross-org",
                "name": "Cross-org Skill",
                "summary": "belongs to org-A",
                "main_id": "org-A",
                "contract_json": {},
                "skill_markdown": "# cross-org skill",
            }
        ]
    )
    fake_db["skill_releases"] = _Collection([])

    # Restore the real tenant scoping helpers (undo the fixture's no-op patches).
    import importlib
    skill_mod = importlib.import_module("app.context_space.adapters.skill")
    monkeypatch.setattr(skill_mod, "add_main_scope", _real_add_main_scope)
    monkeypatch.setattr(skill_mod, "resolve_main_id", _real_resolve_main_id)

    with pytest.raises(ContextNotFoundError, match="skill not found"):
        await resolve_memory(
            "mogo://skill/org-B/sk-cross-org",
            tenant_id="org-B",
            viewer_id="u1",
        )


async def test_resolve_session_l0(fake_db, memory_store) -> None:
    _seed(fake_db)
    out = await resolve_memory(
        "mogo://session/t1/507f1f77bcf86cd799439011/L0", tenant_id="t1", viewer_id="u1"
    )
    assert "Planning" in out["resolved"]["content"]


async def test_resolve_session_l2_transcript(fake_db, memory_store) -> None:
    _seed(fake_db)
    out = await resolve_memory(
        "mogo://session/t1/507f1f77bcf86cd799439011/L2", tenant_id="t1", viewer_id="u1"
    )
    assert "hello" in out["resolved"]["content"]
    assert "hi there" in out["resolved"]["content"]


async def test_resolve_resource_visibility_denied(fake_db, memory_store) -> None:
    _seed(fake_db)
    with pytest.raises(Exception):
        await resolve_memory(
            "mogo://resource/doc/t1/doc-1/c1", tenant_id="OTHER", viewer_id="u1"
        )


async def test_resolve_unknown_root(fake_db, memory_store) -> None:
    with pytest.raises(ValueError):
        await resolve_memory(
            "mogo://nope/x", tenant_id="t1", viewer_id="u1"
        )


# --- R3 regressions: the address layer must not be an authorization bypass ----
# Wiring 021 into production (R1) made these paths reachable over HTTP. The URI
# is caller-supplied, so it can never be the basis of an access decision.

async def test_resolve_memory_forged_owner_is_denied(fake_db, memory_store) -> None:
    """R3 P0: ``m-1`` belongs to ``u1`` (personal). ``u2`` forges an address
    claiming the record as their own — must be denied, not leaked."""
    _seed(fake_db)
    with pytest.raises(ContextVisibilityError):
        await resolve_memory(
            "mogo://memory/personal/u2/m-1/L2", tenant_id="t1", viewer_id="u2"
        )


async def test_resolve_memory_forged_org_scope_is_denied(fake_db, memory_store) -> None:
    """R3 P0: re-labelling a personal record as ``org`` must not widen it."""
    _seed(fake_db)
    with pytest.raises(ContextVisibilityError):
        await resolve_memory(
            "mogo://memory/org/u1/m-1/L2", tenant_id="t1", viewer_id="u2"
        )


async def test_resolve_memory_owner_still_reads_own(fake_db, memory_store) -> None:
    """The fix must not break the legitimate owner path."""
    _seed(fake_db)
    out = await resolve_memory(
        "mogo://memory/personal/u1/m-1/L2", tenant_id="t1", viewer_id="u1"
    )
    assert out["resolved"]["content"] == "raw body"


async def test_resolve_session_other_user_is_denied(fake_db, memory_store) -> None:
    """R3 P0: sessions are owner-scoped; ``u2`` must not read ``u1``'s
    transcript even though both are in tenant ``t1``."""
    _seed(fake_db)
    with pytest.raises(Exception):
        await resolve_memory(
            "mogo://session/t1/507f1f77bcf86cd799439011/L2",
            tenant_id="t1",
            viewer_id="u2",
        )


async def test_resolve_session_owner_still_reads_own(fake_db, memory_store) -> None:
    _seed(fake_db)
    out = await resolve_memory(
        "mogo://session/t1/507f1f77bcf86cd799439011/L2",
        tenant_id="t1",
        viewer_id="u1",
    )
    assert "hello" in out["resolved"]["content"]
