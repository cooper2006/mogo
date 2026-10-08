from __future__ import annotations

from fastapi import Header, HTTPException, status

from app.core.security import decode_access_token
from app.core.tenant_identity import is_platform_main_id, is_reserved_main_id
from app.repositories.org_user_repository import find_account_by_username
from app.repositories.admin_session_repository import find_session


async def _load_authenticated_account(authorization: str | None) -> dict:
    """Decode the bearer token, verify the session and load the admin account.

    The tenant identifier comes **only** from the token subject — there is no
    ``bootstrap_main_id`` fallback any more (removing it is what closes the
    cross-tenant leak). An empty identifier is a hard 401.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")

    token = authorization.replace("Bearer ", "", 1).strip()
    try:
        payload = decode_access_token(token)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    subject = payload.get("sub") or {}
    username = subject.get("username")
    session_id = subject.get("session_id")
    tenant_id = str(subject.get("tenant_id") or "").strip()
    if not username or not session_id or not tenant_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token subject")

    session = await find_session(str(session_id))
    if session is None or session.get("status") != "active":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session is not active")

    user = await find_account_by_username(str(username), tenant_id)
    if user is None or user.get("status") != "active":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin user is not available")

    role_name = user.get("role_name") or "组织管理员"
    org_name = user.get("org_name") or user.get("group_code") or "组织账户"
    return {
        **user,
        "tenant_id": tenant_id,
        "role_name": role_name,
        "org_name": org_name,
        "display_name": user.get("display_name") or user.get("username") or "",
    }


async def get_authenticated_admin(authorization: str | None = Header(default=None)) -> dict:
    """Any authenticated admin account, including the platform super-admin.

    Used by account-self endpoints (``/auth/me`` and friends) so the platform
    admin can manage its own profile.
    """
    return await _load_authenticated_account(authorization)


async def get_current_admin_user(authorization: str | None = Header(default=None)) -> dict:
    """Tenant-scoped admin dependency for business routes.

    Rejects missing / ``default`` / ``__platform__`` identifiers, so every
    business route is automatically guarded against the platform tenant
    (reverse guard, T022).
    """
    user = await _load_authenticated_account(authorization)
    if is_reserved_main_id(user["tenant_id"]):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant context is required")
    return user


async def get_current_platform_admin(authorization: str | None = Header(default=None)) -> dict:
    """Platform super-admin dependency: requires the reserved ``__platform__``."""
    user = await _load_authenticated_account(authorization)
    if not is_platform_main_id(user["tenant_id"]):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Platform administrator privileges are required",
        )
    return user
