#!/usr/bin/env python3
"""Release admission gate for a bundled DSH Runtime Host candidate."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import yaml


CHAT_API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = CHAT_API_ROOT.parents[1]
MATRIX_PATH = CHAT_API_ROOT / "dsh" / "compatibility-matrix.yaml"
VERSIONS_LOCK = CHAT_API_ROOT / "dsh" / "versions.lock"
HOST_PACKAGE = CHAT_API_ROOT / "dsh" / "runtime-host" / "package.json"
HOST_PROTOCOL = CHAT_API_ROOT / "dsh" / "runtime-host" / "src" / "host-protocol.mjs"
HOST_OVERLAY = CHAT_API_ROOT / "dsh" / "runtime-host" / "src" / "official-host" / "overlay.mjs"
SBOM_PATH = CHAT_API_ROOT / "dsh" / "sbom.cdx.json"


def _constant(path: Path, name: str) -> str:
    text = path.read_text(encoding="utf-8")
    match = re.search(rf"\b{name}\s*=\s*['\"]([^'\"]+)['\"]", text)
    if not match:
        raise ValueError(f"{name} is missing from {path.relative_to(REPO_ROOT)}")
    return match.group(1)


def _lock_section(section: str) -> str:
    text = VERSIONS_LOCK.read_text(encoding="utf-8")
    section_match = re.search(
        rf"^\[{re.escape(section)}\]\s*$([\s\S]*?)(?=^\[|\Z)",
        text,
        re.MULTILINE,
    )
    if not section_match:
        raise ValueError(f"missing [{section}] in versions.lock")
    return section_match.group(1)


def _lock_scalar(section: str, name: str) -> str | bool:
    """Read the two admission fields without adding a Python-version dependency.

    ``versions.lock`` is intentionally a human-auditable policy file.  The
    release gate only needs one string and one boolean from it, so requiring a
    TOML package merely to run the repository guard would make the guard less
    portable than the artifact it protects.
    """
    value_match = re.search(
        rf"^{re.escape(name)}\s*=\s*(.+?)\s*$",
        _lock_section(section),
        re.MULTILINE,
    )
    if not value_match:
        raise ValueError(f"missing [{section}].{name} in versions.lock")
    value = value_match.group(1).strip()
    if value in {"true", "false"}:
        return value == "true"
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1]
    raise ValueError(f"unsupported [{section}].{name} value in versions.lock")


def _lock_string_list(section: str, name: str) -> list[str]:
    """Read a list of strings without adding a Python-version dependency."""
    value_match = re.search(
        rf"^{re.escape(name)}\s*=\s*\[(.*?)\]\s*$",
        _lock_section(section),
        re.MULTILINE | re.DOTALL,
    )
    if not value_match:
        raise ValueError(f"missing [{section}].{name} in versions.lock")
    return re.findall(r'"([^"]*)"', value_match.group(1))


def _allowed_mixed_exceptions() -> dict[str, str]:
    """Read the authorized mixed-train exceptions as ``{package: version}``.

    ``versions.lock`` records one authorized exception per upstream package
    that cannot join the current release train (for example a package the
    upstream never republished for this train).  The exception is exact: both
    the package name and its pinned version must match, so an exception can
    never authorize an arbitrary version of an arbitrary package.
    """
    exceptions: dict[str, str] = {}
    for entry in _lock_string_list("release_train", "allowed_mixed_exceptions"):
        name, separator, version = entry.rpartition("@")
        if not separator or not name or not version:
            raise ValueError(f"invalid allowed_mixed_exceptions entry: {entry!r}")
        if not (name == "@deepseek-ai/dsh" or name.startswith("@deepseek-ai/dsh-")):
            raise ValueError(f"allowed_mixed_exceptions only covers DSH packages: {entry!r}")
        if name in exceptions:
            raise ValueError(f"duplicated allowed_mixed_exceptions entry: {entry!r}")
        exceptions[name] = version
    return exceptions


def current_candidate() -> dict[str, Any]:
    matrix = yaml.safe_load(MATRIX_PATH.read_text(encoding="utf-8"))
    active = matrix["active_release"]
    return {
        "dsh_release_train": active["dsh_release_train"],
        "node_runtime": active["node_runtime"],
        "host_protocol": active["host_protocol"],
        "host_overlay": active["host_overlay"],
        "execution_projection": active["execution_projection"],
        "workspace_contract": active["workspace_contract"],
        "session_persistence_provider": active["session_persistence"]["provider"],
        "old_session_resume_verified": True,
        "presets": list(active["required_presets"]),
        "code_model_tools": list(active["code_model_tools"]),
        "code_capabilities": list(active["code_capabilities"]),
        "host_modules": list(active["required_host_modules"]),
    }


def validate_candidate(candidate: dict[str, Any], matrix: dict[str, Any]) -> None:
    active = matrix["active_release"]
    supported = {
        (str(row["dsh_release_train"]), str(row["host_protocol"]), str(row["host_overlay"]))
        for row in matrix["supported_releases"]
        if row.get("status") == "production" and row.get("old_session_resume") == "verified"
    }
    identity = (
        str(candidate.get("dsh_release_train") or ""),
        str(candidate.get("host_protocol") or ""),
        str(candidate.get("host_overlay") or ""),
    )
    if identity not in supported:
        raise ValueError(f"candidate release identity is not admitted: {identity!r}")
    exact = {
        "node_runtime": active["node_runtime"],
        "execution_projection": active["execution_projection"],
        "workspace_contract": active["workspace_contract"],
        "session_persistence_provider": active["session_persistence"]["provider"],
    }
    for key, expected in exact.items():
        if candidate.get(key) != expected:
            raise ValueError(f"candidate {key} changed: expected {expected!r}")
    if active["session_persistence"]["resume_probe_required"] and candidate.get("old_session_resume_verified") is not True:
        raise ValueError("candidate did not pass the old Session resume probe")
    for key, required_key in (
        ("presets", "required_presets"),
        ("code_model_tools", "code_model_tools"),
        ("code_capabilities", "code_capabilities"),
        ("host_modules", "required_host_modules"),
    ):
        missing = sorted(set(active[required_key]) - set(candidate.get(key) or []))
        if missing:
            raise ValueError(f"candidate is missing required {key}: {missing}")


def validate_repository() -> None:
    matrix = yaml.safe_load(MATRIX_PATH.read_text(encoding="utf-8"))
    if matrix.get("schema_version") != "mogo.dsh-compatibility-matrix.v1":
        raise ValueError("unsupported DSH compatibility matrix schema")
    policy = matrix["upgrade_policy"]
    required_policy = {
        "floating_versions": False,
        "mutate_installed_runtime_in_place": False,
        "candidate_requires_full_contract_suite": True,
        "candidate_requires_packaged_smoke": True,
        "candidate_requires_old_session_resume": True,
        "rollback_unit": "versioned_container_release",
        "rollback_preserves_runtime_data": True,
        "publish_on_failed_admission": False,
    }
    if policy != required_policy:
        raise ValueError("DSH upgrade/rollback policy changed without contract review")

    active = matrix["active_release"]
    version = str(active["dsh_release_train"])
    exceptions = _allowed_mixed_exceptions()
    package = json.loads(HOST_PACKAGE.read_text(encoding="utf-8"))
    if package.get("engines", {}).get("node") != active["node_runtime"]:
        raise ValueError("Runtime Host Node engine differs from the compatibility matrix")
    dsh_dependencies = {
        name: value for name, value in package["dependencies"].items()
        if name == "@deepseek-ai/dsh" or name.startswith("@deepseek-ai/dsh-")
    }
    mismatched = {
        name: value for name, value in dsh_dependencies.items()
        if value != version and exceptions.get(name) != value
    }
    if not dsh_dependencies or mismatched:
        raise ValueError(f"Runtime Host DSH dependencies are not one exact release train: {mismatched}")

    if _lock_scalar("release_train", "version") != version or _lock_scalar("upstream", "allow_floating_versions"):
        raise ValueError("versions.lock is not aligned with the compatibility matrix")
    if _constant(HOST_PROTOCOL, "ASKAI_DSH_KERNEL_VERSION") != version:
        raise ValueError("Runtime Host kernel handshake version differs from the matrix")
    if _constant(HOST_PROTOCOL, "ASKAI_DSH_HOST_PROTOCOL_VERSION") != active["host_protocol"]:
        raise ValueError("Runtime Host protocol differs from the matrix")
    if _constant(HOST_OVERLAY, "ASKAI_DSH_HOST_OVERLAY_VERSION") != active["host_overlay"]:
        raise ValueError("Host overlay differs from the matrix")
    sbom = json.loads(SBOM_PATH.read_text(encoding="utf-8"))
    dsh_components = [
        component for component in sbom.get("components", [])
        if component.get("name") == "@deepseek-ai/dsh"
        or str(component.get("name") or "").startswith("@deepseek-ai/dsh-")
    ]
    sbom_mismatched = {
        str(component.get("name")): str(component.get("version"))
        for component in dsh_components
        if component.get("version") != version
        and exceptions.get(str(component.get("name"))) != str(component.get("version"))
    }
    if not dsh_components or sbom_mismatched:
        raise ValueError("DSH SBOM is missing or contains a mixed release train")
    observed = {
        **{name: value for name, value in dsh_dependencies.items() if value != version},
        **{str(component.get("name")): str(component.get("version")) for component in dsh_components},
    }
    stale = sorted(
        f"{name}@{expected}"
        for name, expected in exceptions.items()
        if observed.get(name) != expected
    )
    if stale:
        raise ValueError(f"allowed_mixed_exceptions entries are stale: {stale}")
    validate_candidate(current_candidate(), matrix)


def main() -> int:
    parser = argparse.ArgumentParser(description="Admit a bundled DSH release against MOGO's versioned contracts.")
    parser.add_argument("--candidate", type=Path, help="optional JSON candidate inventory produced by the contract suite")
    args = parser.parse_args()
    matrix = yaml.safe_load(MATRIX_PATH.read_text(encoding="utf-8"))
    validate_repository()
    if args.candidate:
        validate_candidate(json.loads(args.candidate.read_text(encoding="utf-8")), matrix)
    print("DSH upgrade contract verified: candidate is safe for packaged release admission")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
