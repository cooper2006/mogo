#!/usr/bin/env python3
"""Verify that a session created by the rollback train resumes on the active DSH."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import yaml

from dsh_upgrade.checks import cross_version_session, verify_declared_release_train
from dsh_upgrade.process import run_command
from dsh_upgrade.workspace import ReleasedWorkspace


def executable(value: str) -> str:
    resolved = shutil.which(value)
    if resolved is None:
        raise ValueError(f"executable not found: {value}")
    return resolved


def configured_rollback_release(chat_api_root: Path) -> tuple[str, str]:
    """Resolve the immediate rollback target declared by the active release.

    The matrix deliberately keeps a multi-level rollback chain, so several rows
    carry ``status: rollback``. The resume probe must use the one the active
    production release points at via ``rollback``, not an arbitrary row (and it
    must not require the chain to contain exactly one rollback release).
    """
    matrix_path = chat_api_root / "dsh" / "compatibility-matrix.yaml"
    matrix = yaml.safe_load(matrix_path.read_text(encoding="utf-8"))
    rows = {
        str(row["dsh_release_train"]): row
        for row in matrix.get("supported_releases", [])
    }
    active_train = str(matrix["active_release"]["dsh_release_train"])
    active_row = rows.get(active_train)
    if active_row is None or active_row.get("status") != "production":
        raise ValueError("active release must be declared as a production supported release")
    target = str(active_row.get("rollback") or "")
    rollback_row = rows.get(target)
    if rollback_row is None or rollback_row.get("status") != "rollback":
        raise ValueError(f"active release must point at a declared rollback release: {target!r}")
    source_ref = str(rollback_row.get("source_ref") or "")
    if not source_ref:
        raise ValueError("rollback release must declare its immutable source_ref")
    return target, source_ref


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("baseline", nargs="?", help="exact DSH version used by the rollback release")
    parser.add_argument("--source-ref", help="immutable MOGO ref containing the released Runtime Host")
    parser.add_argument("--node", default="node")
    parser.add_argument("--pnpm", default="pnpm")
    args = parser.parse_args()
    chat_api_root = Path(__file__).resolve().parents[1]
    active_host = chat_api_root / "dsh" / "runtime-host"
    configured_baseline, configured_source_ref = configured_rollback_release(chat_api_root)
    baseline = args.baseline or configured_baseline
    source_ref = args.source_ref or configured_source_ref
    repository_root = chat_api_root.parents[1]
    host_relative_path = Path("services/chat-api/dsh/runtime-host")

    with ReleasedWorkspace(repository_root, source_ref, host_relative_path) as rollback_host:
        shutil.copy2(
            active_host / "scripts" / "session-compatibility-probe.mjs",
            rollback_host / "scripts" / "session-compatibility-probe.mjs",
        )
        install = run_command(
            "rollback_install",
            [executable(args.pnpm), "install", "--frozen-lockfile", "--ignore-scripts", "--registry=https://registry.npmjs.org"],
            cwd=rollback_host,
            timeout=300,
        )
        train, installed = verify_declared_release_train(rollback_host, baseline)
        result = cross_version_session(rollback_host, active_host, executable(args.node)) if install.passed and train.passed else {
            "checks": [], "created": False, "resumed": False,
        }
        payload = {
            "baseline": baseline,
            "source_ref": source_ref,
            "install": install.to_dict(),
            "release_train": train.to_dict(),
            "installed": installed,
            "resume": {
                "created": result["created"],
                "resumed": result["resumed"],
                "checks": [check.to_dict() for check in result["checks"]],
                "baseline_session": result.get("baseline_session"),
                "active_session": result.get("candidate_session"),
            },
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if install.passed and train.passed and result["created"] and result["resumed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
