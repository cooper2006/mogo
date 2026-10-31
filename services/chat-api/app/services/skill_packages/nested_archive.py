"""Create a canonical Skill-only ZIP from a repository archive."""

from __future__ import annotations

import io
import zipfile


def skill_subtree_zip(
    archive: zipfile.ZipFile,
    entries: list[tuple[zipfile.ZipInfo, str]],
    root_prefix: str,
) -> bytes:
    """Keep the unique Skill tree and discard repository files outside it."""
    root_name = root_prefix.rstrip("/").rsplit("/", 1)[-1]
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as normalized:
        for info, path in entries:
            if not path.startswith(root_prefix):
                continue
            relative = path[len(root_prefix):]
            if relative:
                entry = zipfile.ZipInfo(f"{root_name}/{relative}", date_time=info.date_time)
                entry.compress_type = zipfile.ZIP_DEFLATED
                entry.external_attr = info.external_attr
                entry.create_system = info.create_system
                normalized.writestr(entry, archive.read(info))
    return output.getvalue()
