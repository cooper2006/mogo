"""Tenant identifier constants and guards shared across the admin API.

``__platform__`` is the reserved ``main_id`` that holds the single platform
super-admin (the tenant-lifecycle operator). It must never be treated as a
regular tenant: business routes reject it and tenant enumeration skips it.
``default`` is the legacy fallback identifier and is likewise not a real tenant.
"""

from __future__ import annotations

PLATFORM_MAIN_ID = "__platform__"
DEFAULT_MAIN_ID = "default"

# Identifiers that are not real tenants.
RESERVED_MAIN_IDS: tuple[str, ...] = (PLATFORM_MAIN_ID, DEFAULT_MAIN_ID, "")


def normalize_main_id(value: object) -> str:
    return str(value or "").strip()


def is_platform_main_id(value: object) -> bool:
    return normalize_main_id(value) == PLATFORM_MAIN_ID


def is_reserved_main_id(value: object) -> bool:
    """True for empty / ``default`` / ``__platform__`` — never a real tenant."""
    normalized = normalize_main_id(value)
    return normalized == "" or normalized in RESERVED_MAIN_IDS
