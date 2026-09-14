from __future__ import annotations

import io
import json
import posixpath
import zipfile
from typing import Any

from .validator import SkillPackageError


def restore_expert_distribution(
    archive: zipfile.ZipFile,
    *,
    file_names: list[str],
    manifest: dict[str, Any],
    slug: str,
    child_slugs: list[str],
) -> bytes:
    """Rebuild the distributable expert shape from MOVO's persisted canonical archive."""
    if "skillset.md" not in file_names:
        raise SkillPackageError("missing_expert_descriptor", "Canonical expert package has no skillset.md", file="skillset.md")
    child_files = [name for name in file_names if name.startswith("children/")]
    allowed_prefixes = tuple(f"children/{child_slug}/" for child_slug in child_slugs)
    unexpected = [name for name in child_files if not name.startswith(allowed_prefixes)]
    if unexpected:
        raise SkillPackageError("expert_children_mismatch", "Canonical expert package contains an undeclared child", file=unexpected[0])

    outer_files: dict[str, bytes] = {
        "manifest.json": json.dumps(
            manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8"),
        f"skillsets/{slug}.md": archive.read("skillset.md"),
    }
    for child_slug in child_slugs:
        prefix = f"children/{child_slug}/"
        paths = [name for name in child_files if name.startswith(prefix)]
        if f"{prefix}SKILL.md" not in paths:
            raise SkillPackageError(
                "missing_expert_child", "Canonical expert package is missing a child Skill", file=f"{prefix}SKILL.md",
            )
        child_archive = {
            name[len(prefix):]: archive.read(name)
            for name in paths
            if name[len(prefix):]
        }
        outer_files[f"skills/{child_slug}.zip"] = deterministic_zip(child_archive)
    return deterministic_zip(outer_files)


def deterministic_zip(files: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path, content in sorted(files.items()):
            normalized = posixpath.normpath(path)
            if normalized.startswith("../") or normalized in {"", ".", ".."}:
                raise SkillPackageError("unsafe_archive_path", "Canonical expert package contains an unsafe path", file=path)
            info = zipfile.ZipInfo(normalized, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            bundle.writestr(info, content)
    return output.getvalue()
