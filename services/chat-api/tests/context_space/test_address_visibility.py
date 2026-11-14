"""Tests for 021 unified address parsing + delegated visibility dispatch.

D4: ``project`` / ``department`` are the legal non-personal memory segments;
``workspace`` / ``org`` are rejected. Visibility is delegated with a single
server-built ``MemoryViewerContext`` passed as ``viewer=``.
"""

from __future__ import annotations

import pytest

from app.context_space.address import (
    ResourceAddress,
    SessionAddress,
    SkillAddress,
    parse_context_uri,
)
from app.context_space.visibility import (
    ContextVisibilityError,
    ViewerContext,
    check_visibility,
)
from app.memory.address import MemoryAddress
from app.memory.viewer import MemoryViewerContext, build_viewer_context


def _auth_payload(*, user_id="u1", tenant_id="t1", org_id=""):
    """Real ``resolve_session_user`` shape — no invented identity keys."""
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


def _viewer(*, user_id="u1", tenant_id="t1"):
    return build_viewer_context(_auth_payload(user_id=user_id, tenant_id=tenant_id))


def _ctx(*, user_id="u1", tenant_id="t1") -> ViewerContext:
    """021 ``ViewerContext`` carries the server-built 017 memory viewer; the
    address layer never re-implements authorization itself."""
    return ViewerContext(
        viewer_id=user_id,
        tenant_id=tenant_id,
        memory_viewer=_viewer(user_id=user_id, tenant_id=tenant_id),
    )


def test_viewer_context_carries_server_built_memory_viewer() -> None:
    ctx = _ctx()
    assert isinstance(ctx.memory_viewer, MemoryViewerContext)
    assert ctx.memory_viewer.user_id == "u1"
    assert ctx.memory_viewer.tenant_id == "t1"
    assert ctx.viewer_id == "u1"


def test_parse_memory_reuses_existing() -> None:
    addr = parse_context_uri("mogo://memory/project/u1/m-9/L1")
    assert isinstance(addr, MemoryAddress)
    assert addr.scope == "project" and addr.owner_id == "u1"
    assert addr.memory_id == "m-9" and addr.tier == "L1"


@pytest.mark.parametrize("legacy_scope", ["workspace", "org"])
def test_parse_context_uri_rejects_legacy_memory_scopes(legacy_scope: str) -> None:
    with pytest.raises(ValueError):
        parse_context_uri(f"mogo://memory/{legacy_scope}/u1/m-9/L1")


def test_parse_resource_doc() -> None:
    addr = parse_context_uri("mogo://resource/doc/t1/doc-1/chunk-2")
    assert isinstance(addr, ResourceAddress)
    assert addr.subtype == "doc"
    assert addr.identifiers == ("t1", "doc-1", "chunk-2")
    assert addr.tier == "L0"
    assert addr.uri() == "mogo://resource/doc/t1/doc-1/chunk-2/L0"


def test_parse_resource_doc_with_tier() -> None:
    addr = parse_context_uri("mogo://resource/doc/t1/d1/c1/L2")
    assert addr.tier == "L2"


def test_parse_resource_biz() -> None:
    addr = parse_context_uri("mogo://resource/biz/t1/crm/customer/rec-7")
    assert isinstance(addr, ResourceAddress)
    assert addr.subtype == "biz"
    assert addr.identifiers == ("t1", "crm", "customer", "rec-7")
    assert addr.tenant_id == "t1"


def test_parse_resource_kg() -> None:
    addr = parse_context_uri("mogo://resource/kg/t1/n-42")
    assert isinstance(addr, ResourceAddress)
    assert addr.subtype == "kg" and addr.identifiers == ("t1", "n-42")
    assert addr.tenant_id == "t1"


def test_parse_skill_no_version() -> None:
    addr = parse_context_uri("mogo://skill/t1/sk-1")
    assert isinstance(addr, SkillAddress)
    assert addr.subtype == "skill"
    assert addr.identifiers == ("t1", "sk-1")


def test_parse_skill_with_version() -> None:
    addr = parse_context_uri("mogo://skill/t1/sk-1/v2")
    assert addr.identifiers == ("t1", "sk-1", "v2")


def test_parse_skill_asset() -> None:
    addr = parse_context_uri("mogo://skill/asset/asset-key-9")
    assert isinstance(addr, SkillAddress)
    assert addr.subtype == "asset"
    assert addr.identifiers == ("asset-key-9",)


def test_parse_session() -> None:
    addr = parse_context_uri("mogo://session/t1/sess-5/L1")
    assert isinstance(addr, SessionAddress)
    assert addr.tenant_id == "t1" and addr.session_id == "sess-5" and addr.tier == "L1"


def test_parse_rejects_unknown_root() -> None:
    with pytest.raises(ValueError):
        parse_context_uri("mogo://bogus/x")


def test_parse_rejects_non_mogo() -> None:
    with pytest.raises(ValueError):
        parse_context_uri("http://x")


def test_parse_rejects_bad_resource_shape() -> None:
    with pytest.raises(ValueError):
        parse_context_uri("mogo://resource/doc/only-one")


# --- visibility dispatch ----------------------------------------------------

def test_check_memory_visibility_uses_stored_record_not_uri() -> None:
    """The URI is a **locator, not a credential** (R3 audit, 2026-10-06).

    A forged ``personal/<self>`` or ``department/<victim>`` address must not
    grant access to a record that is actually owned by someone else.
    """
    from app.memory.scope import Memory

    stored = Memory(scope="personal", owner_id="u1", tenant_id="t1", memory_id="m")
    # The owner reads their own record — allowed.
    assert check_visibility(
        addr=MemoryAddress(scope="personal", owner_id="u1", memory_id="m", tier="L0"),
        ctx=_ctx(user_id="u1"),
        memory=stored,
    ) is True
    # Forged URI claims the viewer owns it; the record says otherwise → denied.
    assert check_visibility(
        addr=MemoryAddress(scope="personal", owner_id="u2", memory_id="m", tier="L0"),
        ctx=_ctx(user_id="u2"),
        memory=stored,
    ) is False
    # Forged ``department`` scope must not widen a personal record → denied.
    assert check_visibility(
        addr=MemoryAddress(scope="department", owner_id="u1", memory_id="m", tier="L2"),
        ctx=_ctx(user_id="u2"),
        memory=stored,
    ) is False


def test_check_visibility_accepts_viewer_kwarg_directly() -> None:
    """D4: a server-built MemoryViewerContext can be threaded straight through
    as ``viewer=``; the address layer builds the matching ViewerContext and
    delegates memory authorization to 017 ``visible_to``."""
    from app.memory.scope import Memory

    stored = Memory(scope="personal", owner_id="u1", tenant_id="t1", memory_id="m")
    addr = MemoryAddress(scope="personal", owner_id="u1", memory_id="m", tier="L0")
    assert check_visibility(addr=addr, viewer=_viewer(user_id="u1"), memory=stored) is True
    assert check_visibility(addr=addr, viewer=_viewer(user_id="u2"), memory=stored) is False
    # No stored record → fail closed even with a valid viewer.
    assert check_visibility(addr=addr, viewer=_viewer()) is False
    # The coarse tenant guard also works off viewer.tenant_id.
    resource = ResourceAddress("doc", ("t1", "d1", "c1"))
    assert check_visibility(addr=resource, viewer=_viewer(tenant_id="t1")) is True
    assert check_visibility(addr=resource, viewer=_viewer(tenant_id="t2")) is False


def test_check_memory_visibility_fails_closed_without_record() -> None:
    """No stored record → deny: URI identity alone cannot prove ownership."""
    addr = MemoryAddress(scope="personal", owner_id="u1", memory_id="m", tier="L0")
    assert check_visibility(addr=addr, ctx=_ctx()) is False


def test_check_visibility_resource_tenant_scoped() -> None:
    addr = ResourceAddress("doc", ("t1", "d1", "c1"))
    assert check_visibility(addr=addr, ctx=_ctx(tenant_id="t1")) is True
    assert check_visibility(addr=addr, ctx=_ctx(tenant_id="t2")) is False


def test_check_visibility_skill_org_scoped() -> None:
    addr = SkillAddress("skill", ("t1", "sk-1"))
    assert check_visibility(addr=addr, ctx=_ctx(tenant_id="t1")) is True
    assert check_visibility(addr=addr, ctx=_ctx(tenant_id="t9")) is False


def test_check_visibility_session_tenant_scoped() -> None:
    addr = SessionAddress("t1", "sess-1")
    assert check_visibility(addr=addr, ctx=_ctx(tenant_id="t1")) is True
    assert check_visibility(addr=addr, ctx=_ctx(tenant_id="t2")) is False


def test_visibility_raises_on_unknown_type() -> None:
    class Weird:
        pass

    with pytest.raises(NotImplementedError):
        check_visibility(addr=Weird(), ctx=_ctx())


def test_context_visibility_error_is_a_permission_error() -> None:
    assert issubclass(ContextVisibilityError, PermissionError)
