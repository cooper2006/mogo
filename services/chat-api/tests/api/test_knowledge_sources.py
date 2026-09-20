import asyncio

from app.api.endpoints import knowledge_sources


def test_personal_knowledge_metadata_keeps_scope_for_product_extensions(monkeypatch) -> None:
    async def current_scope(_authorization):
        return "user", "tenant"

    async def find_document(_document_id, _main_id, _user_id):
        return {
            "_id": "doc",
            "scope": "personal",
            "name": "Personal document",
            "original_filename": "personal.docx",
        }

    monkeypatch.setattr(knowledge_sources, "_current_scope", current_scope)
    monkeypatch.setattr(knowledge_sources, "_find_document_or_404", find_document)

    payload = asyncio.run(knowledge_sources.get_knowledge_source_document("doc", "Bearer token"))

    assert payload["scope"] == "personal"
    assert payload["canDownload"] is True
