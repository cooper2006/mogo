"""Per-module coverage floor for the newer subsystems (CI gate).

The repo-wide ``fail_under = 55`` is a coarse gate over a large legacy app. The
subsystems below are small, actively changed, and cheap to test thoroughly, so
they get their own much higher floor. Raising the global number would either
fail on untouched legacy code or be meaningless.

Run after the normal coverage run (it reads ``coverage.json`` / ``.coverage``)::

    pytest --cov=app --cov-report=json
    python scripts/check_module_coverage.py

``MIN_MODULE_COVERAGE`` is per-directory; a module with no executed statements
is ignored so a freshly added file cannot fail the build before its tests land.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1] / "app"

# directory prefix -> minimum coverage %, measured over the whole directory.
MIN_MODULE_COVERAGE: dict[str, int] = {
    "context_space": 85,   # 021 — router + adapters + address + visibility
    "memory": 80,           # 017 — scope/tiering/address/store/sediment
    "dsh_runtime/hooks": 75,  # 009 — dispatcher/engine/guard/store/integration
}

# Individual modules that must clear a higher bar than their directory.
MIN_FILE_COVERAGE: dict[str, int] = {
    "context_space/router.py": 95,
    "context_space/trace.py": 95,
    "memory/address.py": 90,
    "memory/tiering.py": 90,
    "dsh_runtime/hooks/dispatcher.py": 80,
}


def _load_coverage() -> dict:
    candidates = [
        Path(os.getenv("COVERAGE_JSON", "coverage.json")),
        Path("coverage.json"),
    ]
    for path in candidates:
        if path.is_file():
            with path.open(encoding="utf-8") as fh:
                return json.load(fh)
    raise SystemExit(
        "coverage.json not found — run pytest with --cov-report=json first"
    )


def _pct(summary: dict) -> float:
    total = summary.get("num_statements", 0)
    if not total:
        return 100.0
    return 100.0 * summary.get("covered_lines", 0) / total


def _iter_files(data: dict):
    for filename, payload in (data.get("files") or {}).items():
        rel = filename
        marker = "/app/"
        if marker in rel:
            rel = rel.split(marker, 1)[1]
        elif rel.startswith("app/"):
            rel = rel[4:]
        else:
            continue
        yield rel, payload.get("summary", {})


def main() -> int:
    data = _load_coverage()
    files = list(_iter_files(data))

    failures: list[str] = []

    for directory, floor in MIN_MODULE_COVERAGE.items():
        scoped = [(rel, s) for rel, s in files if rel.startswith(directory)]
        if not scoped:
            print(f"--  {directory}: no measured files, skipped")
            continue
        total_stmts = sum(s.get("num_statements", 0) for _, s in scoped)
        covered = sum(s.get("covered_lines", 0) for _, s in scoped)
        pct = 100.0 * covered / total_stmts if total_stmts else 100.0
        status = "ok " if pct >= floor else "FAIL"
        print(f"{status} {directory}: {pct:.1f}% (floor {floor}%)")
        if pct < floor:
            failures.append(f"{directory} at {pct:.1f}% < required {floor}%")

    for rel, floor in MIN_FILE_COVERAGE.items():
        match = next(((r, s) for r, s in files if r == rel), None)
        if match is None:
            print(f"--  {rel}: not measured, skipped")
            continue
        pct = _pct(match[1])
        status = "ok " if pct >= floor else "FAIL"
        print(f"{status} {rel}: {pct:.1f}% (floor {floor}%)")
        if pct < floor:
            failures.append(f"{rel} at {pct:.1f}% < required {floor}%")

    if failures:
        print("\n::error::module coverage check failed")
        for f in failures:
            print(f"  - {f}")
        return 1

    print(f"\nmodule coverage check passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
