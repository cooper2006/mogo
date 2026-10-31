"""Authorized source reading and verified annotated-copy delivery."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.enterprise_capabilities.artifacts.references import require_owned_artifact
from app.enterprise_capabilities.artifacts.storage import read_owned_artifact, upload_derived_artifact
from app.enterprise_capabilities.runtime.contracts import CapabilityExecutionContext

from .annotations import annotate_docx
from .comment_content import review_language
from .source import page_blocks, read_document_xml, review_blocks, source_hash


DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _source(arguments: dict[str, Any], context: CapabilityExecutionContext) -> tuple[dict[str, Any], bytes, str]:
    artifact = require_owned_artifact(dict(arguments.get("artifact") or {}), user_id=context.user_id)
    uploaded_paths = {
        str(item.get("object_path") or "")
        for item in list(context.turn_context.get("documents") or [])
        if isinstance(item, dict)
    }
    if artifact["object_path"] not in uploaded_paths:
        raise PermissionError("review source must be a document uploaded in the current turn")
    artifact, content, filename = read_owned_artifact(artifact, context=context)
    if Path(filename).suffix.lower() != ".docx":
        raise ValueError("original annotations currently support DOCX only; use a review report for this format")
    if len(content) > 25 * 1024 * 1024:
        raise ValueError("DOCX exceeds the 25 MB review limit")
    return artifact, content, filename


async def document_review_source(arguments: dict[str, Any], context: CapabilityExecutionContext) -> dict[str, Any]:
    artifact, content, filename = _source(arguments, context)
    blocks = review_blocks(read_document_xml(content))
    page = page_blocks(
        blocks,
        offset=int(arguments.get("offset") or 0),
        max_chars=int(arguments.get("max_chars") or 12000),
    )
    return {
        "success": True,
        "filename": filename,
        "source_artifact": {"object_path": artifact["object_path"], "filename": filename},
        "source_sha256": source_hash(content),
        **page,
    }


async def document_annotate(arguments: dict[str, Any], context: CapabilityExecutionContext) -> dict[str, Any]:
    _, content, filename = _source(arguments, context)
    expected_hash = str(arguments.get("source_sha256") or "").strip()
    if expected_hash != source_hash(content):
        raise ValueError("review source changed; read the original document again")
    findings = list(arguments.get("findings") or [])
    if not findings or len(findings) > 100 or any(not isinstance(item, dict) for item in findings):
        raise ValueError("findings must contain 1 to 100 review items")
    language = review_language(str(context.turn_context.get("language") or "zh"))
    annotated, accepted, rejected = annotate_docx(content, findings, language=language)
    if annotated is None:
        return {
            "success": False,
            "error": "no_verified_annotations",
            "accepted": [],
            "unlocated": rejected,
            "message": "No finding could be anchored to the original DOCX. Produce a review report instead.",
        }
    requested_name = Path(str(arguments.get("filename") or "").strip()).name
    suffix = "AI_reviewed" if language == "en" else "AI审阅"
    output_name = requested_name if requested_name.lower().endswith(".docx") else f"{Path(filename).stem}_{suffix}.docx"
    artifact = upload_derived_artifact(
        annotated, context=context, filename=output_name, content_type=DOCX_CONTENT_TYPE,
    )
    return {
        "success": True,
        "artifact": artifact,
        "source_unchanged": True,
        "accepted": accepted,
        "unlocated": rejected,
        "accepted_count": len(accepted),
        "unlocated_count": len(rejected),
    }
