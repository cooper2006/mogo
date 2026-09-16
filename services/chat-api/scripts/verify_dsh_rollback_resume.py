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
    matrix_path = chat_api_root / "dsh" / "compatibility-matrix.yaml"
    matrix = yaml.safe_load(matrix_path.read_text(encoding="utf-8"))
    releases = [
        (str(row["dsh_release_train"]), str(row.get("source_ref") or ""))
        for row in matrix.get("supported_releases", [])
        if row.get("status") == "rollback"
    ]
    if len(releases) != 1:
        raise ValueError("compatibility matrix must declare exactly one rollback release")
    if not releases[0][1]:
        raise ValueError("rollback release must declare its immutable source_ref")
    return releases[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("baseline", nargs="?", help="exact DSH version used by the rollback release")
    parser.add_argument("--source-ref", help="immutable MOVO ref containing the released Runtime Host")
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
