"""Internal audit entry access for the authenticated admin service."""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from fastapi.responses import StreamingResponse
from urllib.parse import quote
from pathlib import PurePosixPath

from app.api.principal import ApiPrincipal, require_api_principal
from app.execution_isolation.audit_reader import call_file_metadata, open_call_file, read_call_text


router = APIRouter(prefix="/internal/sandbox-audits", tags=["internal-sandbox-audits"])


@router.get("/{message_id}/calls/{call_id}/{kind}", response_class=PlainTextResponse)
async def get_call_text(
    message_id: str, call_id: str, kind: str,
    principal: ApiPrincipal = Depends(require_api_principal),
) -> str:
    if principal.kind != "admin_service":
        raise HTTPException(status_code=403, detail="admin_service_required")
    return await read_call_text(principal.tenant_id, message_id, call_id, kind)


@router.get("/{message_id}/calls/{call_id}/files/{file_index}")
async def download_call_file(
    message_id: str, call_id: str, file_index: int,
    principal: ApiPrincipal = Depends(require_api_principal),
) -> StreamingResponse:
    if principal.kind != "admin_service":
        raise HTTPException(status_code=403, detail="admin_service_required")
    object_path, item = await call_file_metadata(
        principal.tenant_id, message_id, call_id, file_index,
    )
    path = str(item.get("path") or "")
    digest = str(item.get("sha256") or "")
    if not path or not digest:
        raise HTTPException(status_code=404, detail="audit_file_not_found")
    filename = PurePosixPath(path).name
    def content():
        with open_call_file(object_path, call_id, path, digest) as (chunks, _size):
            yield from chunks
    return StreamingResponse(
        content(), media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )
