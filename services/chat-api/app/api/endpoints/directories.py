"""Server-side directory browsing for the pure-web client.

The web client has no access to the employee's own filesystem, so the DSH
desktop's native OS directory chooser cannot serve it. DSH models this case
with its ``directoryPicker`` seam's ``browse`` capability, which is documented
as the interaction that "works for remote clients — nothing renders on the
host display". This endpoint exposes that capability over HTTP so the web
client can drive a directory browser the way the DSH client drives its native
chooser.

The listing shape and the failure codes mirror the DSH seam exactly, so the
client discriminates on the code (``directory-unreadable`` /
``directory-exists`` / ``directory-create-failed``) rather than on message
text.

Access is gated on the same ``code_generation`` capability the Code surfaces
require: browsing a workspace directory is part of starting a Code task, so
an employee without that capability must not enumerate the host's workspace
tree.
"""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from app.api.endpoints.auth import _resolve_session_user
from app.core.tenant import resolve_tenant_id
from app.dsh_runtime.application import dsh_runtime_application
from app.dsh_runtime.directory_browser import DirectoryBrowseError
from app.governance.position_policy import MongoEmployeePolicyResolver


router = APIRouter(tags=["directories"])


class ApiResponse(BaseModel):
    code: int = 0
    message: str | None = None
    data: object | None = None


class DirectoryCreate(BaseModel):
    """One child directory to create under an existing parent."""

    path: str = Field(min_length=1, max_length=1024)
    name: str = Field(min_length=1, max_length=255)


async def _require_code_capability(tenant_id: str, user_id: str) -> None:
    """Refuse directory browsing without the Code capability."""
    policy = await MongoEmployeePolicyResolver().resolve(tenant_id, user_id)
    if not policy.allows_capability("code_generation"):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "position_role_denied",
                "message": "当前岗位未开通代码生成能力，无法浏览工作区目录",
            },
        )


async def _identity(authorization: str | None) -> tuple[str, str]:
    resolved = await _resolve_session_user(authorization if isinstance(authorization, str) else None)
    return resolve_tenant_id(resolved["tenant_id"]), str(resolved["user"].get("_id") or "")


def _fail(error: DirectoryBrowseError) -> HTTPException:
    """Map a directory failure onto its HTTP status and closed code."""
    status = 409 if error.code == "directory-exists" else 400
    return HTTPException(
        status_code=status,
        detail={"code": error.code, "message": str(error), "path": error.path},
    )


@router.get("/directories", response_model=ApiResponse)
async def list_directory(
    path: str | None = None,
    authorization: str | None = Header(default=None),
):
    """List one directory level of the browsable workspace root."""
    tenant_id, user_id = await _identity(authorization)
    await _require_code_capability(tenant_id, user_id)
    browser = dsh_runtime_application.require_directory_browser()
    try:
        listing = await browser.list(path)
    except DirectoryBrowseError as error:
        raise _fail(error) from error
    return ApiResponse(data=listing)


@router.post("/directories", response_model=ApiResponse)
async def create_directory(
    payload: DirectoryCreate,
    authorization: str | None = Header(default=None),
):
    """Create one child directory under an existing parent directory."""
    tenant_id, user_id = await _identity(authorization)
    await _require_code_capability(tenant_id, user_id)
    browser = dsh_runtime_application.require_directory_browser()
    try:
        created = await browser.create_directory(payload.path, payload.name)
    except DirectoryBrowseError as error:
        raise _fail(error) from error
    return ApiResponse(data={"path": created})
