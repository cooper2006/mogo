"""017 B1: the RAG adapter must actually reach the memory layer.

Before B1 ``knowledge_search`` called ``context.get("role")`` on a frozen
pydantic ``CapabilityExecutionContext`` that has no ``get`` method.  The
resulting ``AttributeError`` was swallowed by a blanket ``except Exception``,
so every existing knowledge_search test passed while the whole 017 RAG path
was dead.  ``memory_candidates`` were also computed but never consumed.
"""

from __future__ import annotations

import ast
import inspect
import textwrap

import pytest

from app.enterprise_capabilities.runtime.adapters import knowledge_search
from app.enterprise_capabilities.runtime.contracts import CapabilityExecutionContext
from app.memory.scope import Memory
from app.memory.viewer import MemoryViewerContext


def _context() -> CapabilityExecutionContext:
    return CapabilityExecutionContext(
        tenant_id="t1",
        user_id="u1",
        conversation_id="c1",
        kernel_session_id="ks1",
        profile_version="v1",
        action_id="a1",
        turn_context={"knowledge_base_ids": []},
    )


def test_adapter_never_calls_context_get():
    """Pin the AttributeError root cause: BaseModel has no .get()."""
    # AST rather than substring: the explanatory comment mentions the old
    # call, and ``context.turn_context.get(...)`` is valid code.
    src = textwrap.dedent(inspect.getsource(knowledge_search))
    offenders = [
        node
        for node in ast.walk(ast.parse(src))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "context"
    ]
    assert offenders == []
    assert hasattr(CapabilityExecutionContext, "get") is False


@pytest.mark.asyncio
async def test_knowledge_search_surfaces_memory_candidates(monkeypatch):
    captured: dict = {}
    viewer = MemoryViewerContext(
        tenant_id="t1",
        user_id="u1",
        viewer_org_id="org1",
        visible_workspace_ids=frozenset({"p1"}),
    )

    async def _resolve_viewer(**kwargs):
        captured["trusted_ids"] = kwargs
        return viewer

    monkeypatch.setattr(
        "app.memory.viewer.resolve_viewer_from_identity", _resolve_viewer
    )

    class _Store:
        async def list_for_viewer(self, **kwargs):
            captured["list_kwargs"] = kwargs
            return [
                Memory(
                    content="team note",
                    scope="personal",
                    owner_id="u1",
                    tenant_id="t1",
                    memory_id="m1",
                    l0_summary="note",
                )
            ]

    monkeypatch.setattr("app.memory.store.MemoryStore", lambda: _Store())

    async def _kg(**kwargs):
        return []

    monkeypatch.setattr("app.knowledge_graph.rag_candidates.kg_rag_candidates", _kg)

    class _QA:
        async def answer(self, **kwargs):
            return {"ok": True, "usedChunks": [], "retrievedCount": 0}

    monkeypatch.setattr(
        "app.enterprise_capabilities.runtime.adapters.internal_knowledge_qa_service",
        _QA(),
    )

    payload = await knowledge_search({"query": "note"}, _context())

    # The 017 path is no longer hollow.
    assert payload["memory_candidates"], "memory RAG candidates must not be dropped"
    assert payload["memory_candidates"][0]["addr"].startswith("mogo://memory/")
    assert payload["memory_retrieval_trace"]

    # Identity comes from trusted ids + server-side lookups, never from the
    # model or from a client-supplied dict; viewer_org_id is no longer omitted.
    assert captured["trusted_ids"] == {"tenant_id": "t1", "user_id": "u1"}
    assert captured["list_kwargs"]["viewer_id"] == "u1"
    assert captured["list_kwargs"]["viewer_org_id"] == "org1"
    assert captured["list_kwargs"]["is_workspace_member"] is True
