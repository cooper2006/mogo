"""Gate-layer set resolution for thick/thin modes (019 FR-1 / FR-5 / FR-8).

The six layers mirror the 001 gate chain. Thin mode may drop **approval** and
**quota** only; identity / RBAC / redaction / audit are required, and the R4 red
line is enforced inside the remaining layers regardless of mode.
"""

from __future__ import annotations

CANONICAL_LAYERS: tuple[str, ...] = (
    "identity",
    "rbac",
    "redaction",
    "approval",
    "quota",
    "audit",
)

# Layers that thin mode may drop (clarify OQ-2).
DROPPABLE_LAYERS: frozenset[str] = frozenset({"approval", "quota"})

# Layers that must always be enabled (the governance floor).
REQUIRED_LAYERS: frozenset[str] = frozenset({"identity", "rbac", "redaction", "audit"})

THICK_MODE = "thick"
THIN_MODE = "thin"


def resolve_layers(mode: str = THICK_MODE, *, enabled: list[str] | None = None) -> list[str]:
    """Resolve the enabled gate layers for ``mode`` in canonical order.

    * ``thick`` -> all six layers;
    * ``thin``  -> all layers except approval + quota;
    * an explicit ``enabled`` list overrides the mode (still ordered canonically
      and still subject to the floor check).
    """
    if enabled is not None:
        selected = set(enabled)
    elif str(mode).lower() == THIN_MODE:
        selected = {name for name in CANONICAL_LAYERS if name not in DROPPABLE_LAYERS}
    else:
        selected = set(CANONICAL_LAYERS)
    return [name for name in CANONICAL_LAYERS if name in selected]


def is_thin(mode: str) -> bool:
    return str(mode).lower() == THIN_MODE
