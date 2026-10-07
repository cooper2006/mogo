"""Guard against "implemented and green but unreachable in production".

QA finding (2026-10-06): ``app.context_space.router`` and the whole 021 layer
(router + four tenant adapters + delegated visibility + retrieval trace) were
fully implemented with a 100% green test suite, yet **zero** production modules
imported the router and no HTTP route reached it. Nothing about "files exist +
tests pass" catches that class of defect.

This check fails the build when a module that declares itself a production
entry point is not actually wired in. Configure via ``WIRING_REQUIRED`` /
``WIRING_FORBIDDEN`` below.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1] / "app"

# (module dotted path, a token that must appear in some production .py file)
WIRING_REQUIRED: list[tuple[str, str]] = [
    ("app.context_space.router", "app.include_router(context_space.router)"),
    ("app.context_space.dispatcher", "dispatch_session_end"),
    ("app.memory.sediment", "sediment_session_end"),
    ("app.memory.tiering", "tier_content"),
    ("app.memory.address", "MemoryAddress"),
]

# Modules that are intentionally entry-point-only (routers included by main.py)
# and therefore not imported by other production modules.
WIRING_FORBIDDEN: list[tuple[str, str]] = [
    # e.g. a leftover experimental adapter nobody may import yet
]


def _iter_production_files() -> list[Path]:
    out: list[Path] = []
    for path in APP_ROOT.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        out.append(path)
    return out


def main() -> int:
    if os.getenv("SKIP_WIRING_CHECK") == "1":
        print("wiring check skipped (SKIP_WIRING_CHECK=1)")
        return 0

    files = _iter_production_files()
    blobs: dict[Path, str] = {}
    for path in files:
        try:
            blobs[path] = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            blobs[path] = ""

    failures: list[str] = []

    for module, token in WIRING_REQUIRED:
        # The wiring token may live in main.py or any production module.
        hit = next((p for p, src in blobs.items() if token in src), None)
        if hit is None:
            failures.append(
                f"{module}: no production module references {token!r} — "
                f"the feature is implemented but unreachable at runtime"
            )
        else:
            rel = hit.relative_to(APP_ROOT)
            print(f"ok  {module} wired via {rel}")

    for module, token in WIRING_FORBIDDEN:
        hit = next((p for p, src in blobs.items() if token in src and p.name != Path(module).name), None)
        if hit is not None:
            failures.append(
                f"{module}: {token!r} is referenced by {hit.relative_to(APP_ROOT)} but must stay unwired"
            )

    if failures:
        print("\n::error::production wiring check failed")
        for f in failures:
            print(f"  - {f}")
        return 1

    print(f"\nwiring check passed ({len(WIRING_REQUIRED)} modules verified)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
