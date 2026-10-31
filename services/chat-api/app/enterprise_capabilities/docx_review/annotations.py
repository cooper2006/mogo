"""Insert verified native Word comments into a copy of a DOCX package."""

from __future__ import annotations

from copy import deepcopy
from io import BytesIO
from zipfile import ZipFile

from lxml import etree

from .comment_content import append_comment, missing_comment_fields
from .source import W, ReviewBlock, qn, read_document_xml, review_blocks


REL = "http://schemas.openxmlformats.org/package/2006/relationships"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"
COMMENTS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments"
COMMENTS_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"


def _direct_runs(paragraph: etree._Element) -> list[tuple[etree._Element, etree._Element]]:
    pairs: list[tuple[etree._Element, etree._Element]] = []
    for child in paragraph:
        if child.tag != qn("r"):
            continue
        texts = child.findall(qn("t"))
        # Word may cache rendered page boundaries inside an ordinary text run.
        # They do not contribute text and are safe to retain on the leading run.
        other = [item for item in child if item.tag not in {qn("rPr"), qn("t"), qn("lastRenderedPageBreak")}]
        if len(texts) == 1 and not other:
            pairs.append((child, texts[0]))
    return pairs


def _set_text(element: etree._Element, value: str) -> None:
    element.text = value
    if value[:1].isspace() or value[-1:].isspace():
        element.set(XML_SPACE, "preserve")
    else:
        element.attrib.pop(XML_SPACE, None)


def _split_at(paragraph: etree._Element, position: int) -> bool:
    consumed = 0
    for run, text in _direct_runs(paragraph):
        value = text.text or ""
        end = consumed + len(value)
        if consumed < position < end:
            clone = deepcopy(run)
            clone_text = clone.find(qn("t"))
            assert clone_text is not None
            for marker in clone.findall(qn("lastRenderedPageBreak")):
                clone.remove(marker)
            _set_text(text, value[: position - consumed])
            _set_text(clone_text, value[position - consumed :])
            run.addnext(clone)
            return True
        consumed = end
    return position in {0, consumed} or any(
        position == sum(len(node.text or "") for _, node in _direct_runs(paragraph)[:index])
        for index in range(1, len(_direct_runs(paragraph)))
    )


def _anchor(paragraph: etree._Element, quote: str, comment_id: int) -> str | None:
    pairs = _direct_runs(paragraph)
    direct_text = "".join(text.text or "" for _, text in pairs)
    full_text = "".join(text.text or "" for text in paragraph.iter(qn("t")))
    if full_text != direct_text:
        return "unsupported_text_structure"
    start = direct_text.find(quote)
    if start < 0:
        return "quote_not_found"
    if direct_text.find(quote, start + 1) >= 0:
        return "ambiguous_quote"
    end = start + len(quote)
    if not _split_at(paragraph, end) or not _split_at(paragraph, start):
        return "unsupported_text_structure"
    pairs = _direct_runs(paragraph)
    cursor = 0
    first = last = None
    for run, text in pairs:
        next_cursor = cursor + len(text.text or "")
        if cursor == start:
            first = run
        if next_cursor == end:
            last = run
            break
        cursor = next_cursor
    if first is None or last is None:
        return "unsupported_text_structure"
    range_start = etree.Element(qn("commentRangeStart"))
    range_start.set(qn("id"), str(comment_id))
    range_end = etree.Element(qn("commentRangeEnd"))
    range_end.set(qn("id"), str(comment_id))
    reference = etree.Element(qn("r"))
    etree.SubElement(reference, qn("commentReference")).set(qn("id"), str(comment_id))
    first.addprevious(range_start)
    last.addnext(range_end)
    range_end.addnext(reference)
    return None


def _serialize(root: etree._Element) -> bytes:
    return etree.tostring(root, encoding="UTF-8", xml_declaration=True, standalone=True)


def annotate_docx(source_bytes: bytes, findings: list[dict], *, language: str = "zh") -> tuple[bytes | None, list[dict], list[dict]]:
    """Only exact, unique quotes in a declared source block become comments."""
    root = read_document_xml(source_bytes)
    blocks = {block.id: block for block in review_blocks(root)}
    with ZipFile(BytesIO(source_bytes)) as source:
        names = set(source.namelist())
        comments = (
            etree.fromstring(source.read("word/comments.xml"))
            if "word/comments.xml" in names else etree.Element(qn("comments"), nsmap={"w": W})
        )
        used_ids = [int(value) for item in comments.findall(qn("comment")) if (value := item.get(qn("id"))) and value.isdigit()]
        used_ids.extend(
            int(value)
            for tag in ("commentRangeStart", "commentRangeEnd", "commentReference")
            for item in root.iter(qn(tag))
            if (value := item.get(qn("id"))) and value.isdigit()
        )
        next_id = max(used_ids, default=-1) + 1
        accepted: list[dict] = []
        rejected: list[dict] = []
        for index, finding in enumerate(findings):
            block_id = str(finding.get("source_block_id") or "").strip()
            quote = str(finding.get("source_quote") or "").strip()
            block: ReviewBlock | None = blocks.get(block_id)
            reason = ""
            if not block:
                reason = "source_block_not_found"
            elif not quote or missing_comment_fields(finding):
                reason = "incomplete_finding"
            elif quote not in block.text:
                reason = "quote_not_found"
            elif block.text.count(quote) != 1:
                reason = "ambiguous_quote"
            else:
                reason = _anchor(block.paragraph, quote, next_id) or ""
            if reason:
                rejected.append({
                    "index": index,
                    "source_block_id": block_id,
                    "source_quote": quote[:500],
                    "criterion_ref": str(finding.get("criterion_ref") or "")[:200],
                    "criterion_text": str(finding.get("criterion_text") or "")[:500],
                    "finding": str(finding.get("finding") or "")[:500],
                    "suggested_revision": str(finding.get("suggested_revision") or "")[:1000],
                    "reason": reason,
                })
                continue
            append_comment(comments, next_id, finding, language=language)
            accepted.append({"index": index, "source_block_id": block_id, "source_quote": quote, "comment_id": next_id})
            next_id += 1
        if not accepted:
            return None, accepted, rejected
        if [(block.id, block.text) for block in review_blocks(root)] != [
            (block.id, block.text) for block in review_blocks(read_document_xml(source_bytes))
        ]:
            raise ValueError("annotation changed source document text")
        replacements = {"word/document.xml": _serialize(root), "word/comments.xml": _serialize(comments)}
        rel_path = "word/_rels/document.xml.rels"
        rels = (
            etree.fromstring(source.read(rel_path))
            if rel_path in names else etree.Element(f"{{{REL}}}Relationships", nsmap={None: REL})
        )
        if not any(item.get("Type") == COMMENTS_REL for item in rels):
            used = {item.get("Id") for item in rels}
            relation_id = next(f"rId{index}" for index in range(1, 10000) if f"rId{index}" not in used)
            relation = etree.SubElement(rels, f"{{{REL}}}Relationship")
            relation.set("Id", relation_id)
            relation.set("Type", COMMENTS_REL)
            relation.set("Target", "comments.xml")
            replacements[rel_path] = _serialize(rels)
        content_types = etree.fromstring(source.read("[Content_Types].xml"))
        if not any(item.get("PartName") == "/word/comments.xml" for item in content_types):
            override = etree.SubElement(content_types, f"{{{CT}}}Override")
            override.set("PartName", "/word/comments.xml")
            override.set("ContentType", COMMENTS_TYPE)
            replacements["[Content_Types].xml"] = _serialize(content_types)
        output = BytesIO()
        with ZipFile(output, "w") as target:
            for member in source.infolist():
                target.writestr(member, replacements.pop(member.filename, source.read(member.filename)))
            for path, content in replacements.items():
                target.writestr(path, content)
    result = output.getvalue()
    with ZipFile(BytesIO(result)) as verified:
        verified_xml = etree.fromstring(verified.read("word/document.xml"))
        verified_comments = etree.fromstring(verified.read("word/comments.xml"))
        for item in accepted:
            identifier = str(item["comment_id"])
            for tag in ("commentRangeStart", "commentRangeEnd", "commentReference"):
                if not any(node.get(qn("id")) == identifier for node in verified_xml.iter(qn(tag))):
                    raise ValueError("annotated DOCX is missing a verified comment anchor")
            if not any(node.get(qn("id")) == identifier for node in verified_comments.findall(qn("comment"))):
                raise ValueError("annotated DOCX is missing a verified comment body")
    return result, accepted, rejected
