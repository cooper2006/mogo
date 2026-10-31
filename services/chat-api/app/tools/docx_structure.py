"""Separate optional cover and contents from the complete document body."""

from __future__ import annotations

import re
from typing import Iterable


def split_document_structure(
    lines: list[str], *, cover_title: str | None,
    toc_headings: Iterable[str],
) -> tuple[str, str, list[str], bool]:
    """Never consume source paragraphs merely because a cover is requested.

    A cover title is presentation metadata. The source H1 and every paragraph
    remain in the body, including short documents without any H2 heading.
    Only an explicit table-of-contents block is omitted from the body.
    """
    first_h1 = next((line.strip()[2:].strip() for line in lines if line.strip().startswith("# ")), "")
    resolved_title = (cover_title or "").strip() or first_h1
    titles = {value.casefold() for value in toc_headings}
    body: list[str] = []
    in_toc = False
    has_toc = False
    for line in lines:
        stripped = line.strip()
        heading = re.match(r"^#{1,2}\s+(.+)$", stripped)
        if heading and heading.group(1).strip().casefold() in titles:
            in_toc = True
            has_toc = True
            continue
        if in_toc:
            if stripped == "---":
                in_toc = False
                continue
            if heading:
                in_toc = False
            else:
                continue
        body.append(line)
    return resolved_title, "", body, has_toc
