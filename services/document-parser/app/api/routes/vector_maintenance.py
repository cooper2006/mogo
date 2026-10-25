from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from app.core.security import verify_service_token
from app.domain.jobs import DeleteDocumentVectorsRequest
from app.services.vector_store import get_vector_store

router = APIRouter()


@router.post("/vectors/documents/deletion")
async def delete_document_vectors(
    payload: DeleteDocumentVectorsRequest,
    _: None = Depends(verify_service_token),
) -> dict[str, int | str]:
    config = dict(payload.config or {})
    vector_store = get_vector_store(config)
    deleted = vector_store.delete_document_chunks(
        tenant_id=payload.tenantId,
        document_id=payload.documentId,
    )
    return {
        "documentId": payload.documentId,
        "deleted": deleted,
        "vectorStoreType": "weaviate",
        "collectionName": vector_store.collection,
    }


@router.post("/vectors/documents/delete", include_in_schema=False, deprecated=True)
async def delete_document_vectors_legacy(request: Request, _: None = Depends(verify_service_token)):
    """向后兼容别名：旧路径 `POST /vectors/documents/delete`（025 T010）。

    308 永久重定向保留 POST 方法（301 会被客户端改成 GET），
    客户端按 308 重发 POST + body + 服务 token。
    """
    return RedirectResponse(
        request.url_for("delete_document_vectors"),
        status_code=308,
    )
