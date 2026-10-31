"""Stable text locations from the original DOCX package for review tools."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from io import BytesIO
from zipfile import ZipFile

from lxml import etree


W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def qn(local: str) -> str:
    return f"{{{W}}}{local}"


@dataclass(frozen=True)
class ReviewBlock:
    id: str
    text: str
    paragraph: etree._Element


def source_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def read_document_xml(content: bytes) -> etree._Element:
    with ZipFile(BytesIO(content)) as package:
        return etree.fromstring(package.read("word/document.xml"))


def review_blocks(root: etree._Element) -> list[ReviewBlock]:
    body = root.find(qn("body"))
    if body is None:
        raise ValueError("DOCX has no document body")
    blocks: list[ReviewBlock] = []
    # Paragraph order includes paragraphs inside table cells. The IDs are
    # stable for this immutable source, including repeated identical text.
    for index, paragraph in enumerate(body.iter(qn("p")), start=1):
        text = "".join(part.text or "" for part in paragraph.iter(qn("t")))
        if text.strip():
            blocks.append(ReviewBlock(f"p{index:06d}", text, paragraph))
    return blocks


def page_blocks(blocks: list[ReviewBlock], *, offset: int, max_chars: int) -> dict:
    if offset < 0 or offset > len(blocks):
        raise ValueError("offset is outside the document")
    if max_chars < 1000 or max_chars > 20000:
        raise ValueError("max_chars must be between 1000 and 20000")
    selected: list[dict[str, str]] = []
    consumed = 0
    for block in blocks[offset:]:
        if len(block.text) > max_chars:
            raise ValueError(f"review block {block.id} is too large for reliable annotation")
        if selected and consumed + len(block.text) > max_chars:
            break
        selected.append({"id": block.id, "text": block.text})
        consumed += len(block.text)
    next_offset = offset + len(selected)
    return {
        "blocks": selected,
        "total_blocks": len(blocks),
        "has_more": next_offset < len(blocks),
        "next_offset": next_offset if next_offset < len(blocks) else None,
    }
