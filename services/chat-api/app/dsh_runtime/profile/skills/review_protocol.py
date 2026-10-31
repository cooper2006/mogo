"""Render review-check guidance without introducing a fixed workflow executor."""

from __future__ import annotations

from typing import Any


def review_check_guidance(config: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    subject = str(config.get("reviewSubject") or "").strip()
    criteria = str(config.get("reviewCriteria") or "").strip()
    if subject:
        lines.append(f"Review subject: {subject}")
    if criteria:
        lines.append(f"Review criteria: {criteria}")
    lines.append("First identify the applicable parties, transaction roles, and scope of the review subject and reference materials. If a rule covers only one role and the current material does not match, explain the mismatch first; do not mechanically apply that role's rule or produce a definitive annotation.")
    lines.append("Review each item and provide a conclusion with brief supporting grounds. If a judgment cannot be made, state that it cannot be confirmed; do not treat it as passed.")
    lines.append("Use the language of the current user request for review conclusions, issue descriptions, and revision suggestions. Preserve the source language when quoting original text and rules; do not translate quotations without authorization.")
    output_mode = str(config.get("outputMode") or "report")
    if output_mode in {"annotated_docx", "both"}:
        lines.extend([
            "When output includes annotations on the original: annotate only a readable original DOCX. For other formats, create a separate review report and clearly state that no annotations were made.",
            "For DOCX, first call document_review_source to read all original text blocks, continuing with next_offset until has_more=false. Review conclusions must include the source block ID and a short verbatim quote; do not invent quotes or locations.",
            "After review, call document_annotate with the same user-uploaded file, source_sha256 returned by the reading tool, and each issue. Every issue must include the source block ID, a short verbatim quote, the specific problem, an actionable revision suggestion, and the actual requirement of the applicable rule in criterion_text. A rule number or title may serve only as a supporting criterion_ref, not a substitute for the rule text. Do not fabricate rule text.",
            "Deliver the annotated copy artifact returned by document_annotate. Do not regenerate a Word file from parsed Markdown and present it as an annotated original.",
            "The annotation tool writes only quotes verified against and uniquely located in the original file. Report unlocated comments separately; do not claim they were annotated. If no comment can be located, provide a review report instead.",
        ])
    if output_mode == "annotated_docx":
        lines.append("When an annotated copy already exists, later content generation or export steps must not create another review report unless the user asks for one.")
    if output_mode == "both":
        lines.append("In addition to the annotated original copy, deliver a complete standalone review report. Both outputs must use the same review conclusions.")
    return lines
