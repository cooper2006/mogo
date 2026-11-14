"""User approval policy for MOGO-owned script execution."""

from __future__ import annotations

from .script_backend import container_backend_enabled


SCRIPT_CAPABILITY_REF = "data.run_script@v1"


def script_requires_approval() -> bool:
    """Legacy in-process execution keeps approval; sandbox execution does not."""
    return not container_backend_enabled()


def is_unapproved_sandbox_script(*, source_type: str, capability_ref: str) -> bool:
    """Also covers profiles published before the sandbox policy changed."""
    return (
        source_type == "internal"
        and capability_ref == SCRIPT_CAPABILITY_REF
        and container_backend_enabled()
    )
