"""Tests for tenant identifier constants/guards (Phase 3 / T012)."""

from __future__ import annotations

from app.core import tenant_identity as ti


def test_platform_main_id_constant() -> None:
    assert ti.PLATFORM_TENANT_ID == "__platform__"
    assert ti.DEFAULT_TENANT_ID == "default"


def test_is_platform_tenant_id() -> None:
    assert ti.is_platform_tenant_id("__platform__") is True
    assert ti.is_platform_tenant_id("  __platform__  ") is True
    assert ti.is_platform_tenant_id("tenant-a") is False
    assert ti.is_platform_tenant_id(None) is False
    assert ti.is_platform_tenant_id("") is False


def test_is_reserved_tenant_id() -> None:
    for value in ("__platform__", "default", "", None, "   "):
        assert ti.is_reserved_tenant_id(value) is True, value
    assert ti.is_reserved_tenant_id("tenant-a") is False
