from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.enterprise_capabilities.artifacts import service
from app.enterprise_capabilities.runtime import CapabilityExecutionContext


def _context() -> CapabilityExecutionContext:
    return CapabilityExecutionContext(
        tenant_id="tenant-regression",
        user_id="user-regression",
        conversation_id="conversation-regression",
        kernel_session_id="session-regression",
        profile_version="profile-regression",
        action_id="action-regression",
        turn_context={},
    )


def test_word_export_routes_markdown_to_governed_document_service(monkeypatch) -> None:
    captured = {}

    async def render(markdown, **kwargs):
        captured.update({"markdown": markdown, **kwargs})
        return {"object_path": "user-regression/dsh-regression.docx", "filename": "dsh-regression.docx"}

    monkeypatch.setattr(service.document_service, "render", render)
    result = asyncio.run(service.artifact_export({
        "format": "docx",
        "markdown": "# DSH Regression",
        "filename": "dsh-regression.docx",
    }, _context()))

    assert captured == {
        "markdown": "# DSH Regression",
        "user_id": "user-regression",
        "format": "docx",
        "filename": "dsh-regression.docx",
        "title": None,
        "skip_cover": False,
        "skip_toc": False,
    }
    assert result["success"] is True
    assert result["artifact"]["object_path"] == "user-regression/dsh-regression.docx"


def test_docx_translation_uses_in_place_translator_and_governed_upload(monkeypatch) -> None:
    captured = {}

    def source(_arguments, _context):
        return {}, b"source-docx", "source.docx"

    async def translate(**kwargs):
        captured["translate"] = kwargs
        return SimpleNamespace(file_bytes=b"translated-docx", stats={"translated": 1}, glossary={})

    def upload(content, **kwargs):
        captured["upload"] = {"content": content, **kwargs}
        return {"object_path": "user-regression/translated.docx", "filename": "translated.docx"}

    monkeypatch.setattr(service, "_source", source)
    monkeypatch.setattr(service, "translate_docx_inplace", translate)
    monkeypatch.setattr(service, "_upload", upload)
    result = asyncio.run(service.document_transform({
        "artifact": {"object_path": "regression/source.docx"},
        "source_language": "zh-CN",
        "target_language": "en-US",
        "filename": "translated.docx",
    }, _context()))

    assert captured["translate"] == {
        "source_bytes": b"source-docx",
        "source_language": "zh-CN",
        "target_language": "en-US",
    }
    assert captured["upload"]["content"] == b"translated-docx"
    assert captured["upload"]["filename"] == "translated.docx"
    assert result["success"] is True
    assert result["stats"] == {"translated": 1}
