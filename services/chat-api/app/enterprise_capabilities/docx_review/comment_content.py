"""User-facing review comment content, separate from DOCX source anchoring."""

from __future__ import annotations

from datetime import datetime, timezone

from lxml import etree

from .source import qn


REQUIRED_COMMENT_FIELDS = ("finding", "suggested_revision", "criterion_text")
COMMENT_LABELS = {
    "zh": ("问题", "修改建议", "审核依据", "规则编号"),
    "en": ("Issue", "Suggested revision", "Review criterion", "Rule reference"),
}


def review_language(value: str) -> str:
    return "en" if value.strip().lower().startswith("en") else "zh"


def missing_comment_fields(finding: dict) -> list[str]:
    return [key for key in REQUIRED_COMMENT_FIELDS if not str(finding.get(key) or "").strip()]


def comment_lines(finding: dict, *, language: str = "zh") -> list[str]:
    """Put the actionable issue first; a rule ID is never the explanation."""
    normalized = review_language(language)
    issue, revision, criterion, reference_label = COMMENT_LABELS[normalized]
    separator = ": " if normalized == "en" else "："
    lines = [
        f"{issue}{separator}{str(finding['finding']).strip()}",
        f"{revision}{separator}{str(finding['suggested_revision']).strip()}",
        f"{criterion}{separator}{str(finding['criterion_text']).strip()}",
    ]
    reference = str(finding.get("criterion_ref") or "").strip()
    if reference:
        lines.append(f"{reference_label}{separator}{reference}")
    return lines


def append_comment(comments: etree._Element, comment_id: int, finding: dict, *, language: str = "zh") -> None:
    comment = etree.SubElement(comments, qn("comment"))
    comment.set(qn("id"), str(comment_id))
    comment.set(qn("author"), "MOGO AI")
    comment.set(qn("date"), datetime.now(timezone.utc).isoformat(timespec="seconds"))
    paragraph = etree.SubElement(comment, qn("p"))
    for index, line in enumerate(comment_lines(finding, language=language)):
        if index:
            etree.SubElement(etree.SubElement(paragraph, qn("r")), qn("br"))
        run = etree.SubElement(paragraph, qn("r"))
        etree.SubElement(run, qn("t")).text = line[:2000]
