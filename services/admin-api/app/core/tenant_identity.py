"""Tenant identifier constants and guards shared across the admin API.

``__platform__`` is the reserved ``tenant_id`` that holds the single platform
super-admin (the tenant-lifecycle operator). It must never be treated as a
regular tenant: business routes reject it and tenant enumeration skips it.
``default`` is the legacy fallback identifier and is likewise not a real tenant.
"""

from __future__ import annotations

PLATFORM_TENANT_ID = "__platform__"
DEFAULT_TENANT_ID = "default"

# Identifiers that are not real tenants.
RESERVED_TENANT_IDS: tuple[str, ...] = (PLATFORM_TENANT_ID, DEFAULT_TENANT_ID, "")


def normalize_tenant_id(value: object) -> str:
    return str(value or "").strip()


def is_platform_tenant_id(value: object) -> bool:
    return normalize_tenant_id(value) == PLATFORM_TENANT_ID


def is_reserved_tenant_id(value: object) -> bool:
    """True for empty / ``default`` / ``__platform__`` — never a real tenant."""
    normalized = normalize_tenant_id(value)
    return normalized == "" or normalized in RESERVED_TENANT_IDS


__all__ = [
    "DEFAULT_TENANT_ID",
    "PLATFORM_TENANT_ID",
    "RESERVED_TENANT_IDS",
    "is_platform_tenant_id",
    "is_reserved_tenant_id",
    "normalize_tenant_id",
]
