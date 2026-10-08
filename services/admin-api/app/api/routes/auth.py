import hashlib
import hmac
import secrets
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Header, HTTPException, Request, UploadFile, status
from pydantic import BaseModel, Field

from app.api.deps import get_authenticated_admin
from app.api.time_utils import utc_iso
from app.core.config import settings
from app.core.db import get_db
from app.core.security import (
    ABSOLUTE_TIMEOUT_SECONDS,
    IDLE_TIMEOUT_SECONDS,
    create_access_token,
    create_refresh_token,
    create_recovery_token,
    decode_access_token,
    decode_refresh_token,
    hash_recovery_token,
    mask_identifier,
    verify_password,
)
from app.core.tenant_identity import PLATFORM_MAIN_ID, is_reserved_main_id
from app.core.totp import compute_totp, generate_secret, totp_uri, verify_totp
from app.core.encryption import decrypt_secret, encrypt_secret, verify_and_decrypt
from app.core.rate_limiter import get_default_limiter
from app.repositories.org_user_repository import (
    find_account_by_username,
    list_accounts_by_username,
    set_account_password,
    touch_account_last_login,
    update_account_avatar,
    update_account_profile,
)
from app.repositories.admin_session_repository import create_session, revoke_session


class LoginRequest(BaseModel):
    username: str
    password: str
    tenantId: str = Field(default="", max_length=64)


class SelectTenantRequest(BaseModel):
    challengeToken: str = Field(min_length=12, max_length=160)
    tenantId: str = Field(min_length=1, max_length=64)


class ProfileUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    email: str = Field(default="", max_length=128)
    phone: str = Field(default="", max_length=32)


class PasswordChangeRequest(BaseModel):
    currentPassword: str = Field(min_length=1, max_length=128)
    newPassword: str = Field(min_length=10, max_length=128)

    @staticmethod
    def validate_strength(password: str) -> str | None:
        """Return a human-readable reason if the password is too weak, else None."""
        if len(password) < 10:
            return "密码长度至少 10 位"
        if not re.search(r"[A-Z]", password):
            return "密码必须包含大写字母"
        if not re.search(r"[a-z]", password):
            return "密码必须包含小写字母"
        if not re.search(r"\d", password):
            return "密码必须包含数字"
        if not re.search(r"[^A-Za-z0-9]", password):
            return "密码必须包含特殊字符"
        return None


router = APIRouter()
LOGIN_CHALLENGE_COLLECTION = "admin_login_challenges"
AVATAR_CONTENT_TYPES = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}

# QF-356: Redis-backed login rate limiter (per IP).
# Supports multi-instance deployment; falls back to in-memory if Redis is unreachable.
_LOGIN_FAIL_WINDOW_SECONDS = 300  # 5-minute sliding window
_LOGIN_MAX_FAILURES = 5  # max failures before lock


def _login_rate_limit_key(request: Request) -> str:
    """Build a rate-limit key from client IP.

    QF-358: only trust ``X-Forwarded-For`` if the request comes from a
    known proxy (127.0.0.1 / ::1).  Otherwise use the direct connection IP
    to prevent header-spoofing bypass.
    """
    direct_ip = request.client.host if request.client else "unknown"
    # Only trust X-Forwarded-For from loopback proxies.
    if direct_ip in ("127.0.0.1", "::1"):
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            # Take the first (leftmost) IP in the chain — the original client.
            real_ip = forwarded.split(",")[0].strip()
            if real_ip:
                return f"login:{real_ip}"
    return f"login:{direct_ip}"


def _check_login_rate_limit(key: str) -> None:
    """Raise 429 if the key has too many recent failures."""
    limiter = get_default_limiter()
    if not limiter.check(key):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="登录尝试过于频繁，请 5 分钟后重试",
        )


def _record_login_failure(key: str) -> None:
    """Record a failed login attempt."""
    limiter = get_default_limiter()
    limiter.record_failure(key)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _digits_only(value: Any) -> str:
    return re.sub(r"\D", "", str(value or ""))


def _is_mobile_like(value: Any) -> bool:
    return bool(re.fullmatch(r"1[3-9]\d{9}", _digits_only(value)))


def _safe_display_name(user: dict[str, Any]) -> str:
    display_name = str(user.get("display_name") or "").strip()
    if not display_name:
        return ""
    display_digits = _digits_only(display_name)
    if _is_mobile_like(display_name) and display_digits in {
        _digits_only(user.get("username")),
        _digits_only(user.get("phone")),
    }:
        return ""
    return display_name


def _safe_path_part(value: Any, fallback: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_.-]+", "-", str(value or "").strip()).strip(".-")
    return normalized[:80] or fallback


def _avatar_extension(content_type: str, filename: str) -> str:
    suffix = Path(filename or "").suffix.lower().lstrip(".")
    ext = AVATAR_CONTENT_TYPES.get(content_type.lower())
    if ext and suffix in {"", "jpg", "jpeg", "png", "webp"}:
        return ext
    if suffix == "jpeg":
        suffix = "jpg"
    if suffix in {"jpg", "png", "webp"} and content_type.lower() in AVATAR_CONTENT_TYPES:
        return suffix
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="头像仅支持 JPG、PNG、WebP")


def _validate_avatar_signature(data: bytes, ext: str) -> None:
    if ext == "jpg" and data.startswith(b"\xff\xd8\xff"):
        return
    if ext == "png" and data.startswith(b"\x89PNG\r\n\x1a\n"):
        return
    if ext == "webp" and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="头像文件内容无效")


def _avatar_public_url(relative_path: str) -> str:
    return f"/static/{relative_path.strip('/')}"


def _profile_from_user(user: dict[str, Any], tenant_id: str) -> dict[str, object]:
    return {
        "name": _safe_display_name(user),
        "roleName": user.get("role_name") or "组织管理员",
        "orgName": user.get("org_name") or user.get("group_code") or "组织账户",
        "username": user.get("username") or "",
        "email": user.get("email") or "",
        "phone": user.get("phone") or "",
        "avatarUrl": user.get("avatar_url") or "",
        "avatarUpdatedAt": utc_iso(user.get("avatar_updated_at")),
        "lastLoginAt": utc_iso(user.get("last_login_at")),
        "mainId": tenant_id,
    }


def _candidate_from_user(user: dict[str, Any]) -> dict[str, object]:
    tenant_id = str(user.get("tenant_id") or "")
    return {
        "mainId": tenant_id,
        "orgName": user.get("org_name") or user.get("group_code") or "组织账户",
        "roleName": user.get("role_name") or "组织管理员",
        "displayName": user.get("display_name") or user.get("username") or "",
        "username": user.get("username") or "",
    }


async def _create_login_challenge(username: str, candidates: list[dict[str, object]]) -> dict[str, object]:
    db = get_db()
    now = _now()
    token = secrets.token_urlsafe(32)
    expires_at = now + timedelta(minutes=5)
    await db[LOGIN_CHALLENGE_COLLECTION].insert_one(
        {
            "challenge_token": token,
            "username": username,
            "candidates": candidates,
            "status": "active",
            "created_at": now,
            "updated_at": now,
            "expires_at": expires_at,
        }
    )
    return {
        "requiresTenantSelection": True,
        "challengeToken": token,
        "candidates": candidates,
        "expiresAt": expires_at.isoformat(),
    }


async def _issue_login_response(user: dict[str, Any], tenant_id: str, request: Request) -> dict[str, object]:
    await touch_account_last_login(user["username"], tenant_id)
    profile = _profile_from_user(user, tenant_id)

    # QF-342~347: if MFA is enabled, issue a short-lived mfaToken instead of a full token.
    mfa_enabled = bool(user.get("mfa_enabled"))
    mfa_secret_hash = str(user.get("mfa_secret_hash") or "")
    if mfa_enabled and mfa_secret_hash:
        # The raw TOTP secret was consumed during setup; the mfaToken carries
        # the session info so /mfa/verify can check the code against the hash.
        # We cannot verify TOTP from the hash alone, so we store the raw secret
        # in a temporary field during the MFA setup flow.  For now, if we have
        # only the hash, we issue a "mfa_pending" token that the frontend must
        # complete via /mfa/verify.
        mfa_token, expires_at, session_id = create_access_token(
            {
                "username": user["username"],
                "tenant_id": tenant_id,
                "mfa_pending": True,
            },
            expires_in_seconds=300,  # 5-minute window for MFA completion
        )
        return {
            "mfaRequired": True,
            "mfaToken": mfa_token,
            "profile": profile,
        }

    token, expires_at, session_id = create_access_token(
        {
            "username": user["username"],
            "role_name": profile["roleName"],
            "org_name": profile["orgName"],
            "tenant_id": tenant_id,
        }
    )
    await create_session(
        session_id=session_id,
        username=user["username"],
        token_expires_at=expires_at,
        user_agent=request.headers.get("user-agent"),
        ip=request.client.host if request.client else None,
    )
    return {
        "token": token,
        "profile": profile,
    }


def _password_matches(user: dict[str, Any], password: str) -> bool:
    password_hash = user.get("password_hash") or ""
    password_salt = user.get("password_salt") or ""
    return bool(password_hash and password_salt and verify_password(password, password_hash, password_salt))


async def _assert_tenant_login_allowed(tenant_id: str) -> None:
    """T040: archived (or otherwise non-active) tenants cannot log in (decision 13).

    The reserved platform identifier is never in the tenant registry and is
    handled by the platform bootstrap instead, so only non-reserved
    identifiers are checked.
    """
    if is_reserved_main_id(tenant_id) or tenant_id == PLATFORM_MAIN_ID:
        return
    db = get_db()
    tenant = await db["tenants"].find_one({"tenant_id": tenant_id}, {"status": 1})
    if tenant is None:
        # Unknown identifier: keep the legacy 401/403 semantics; a brand-new
        # tenant is always registered by provision_tenant before it is usable.
        return
    if str(tenant.get("status") or "") != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant is not active",
        )


@router.post("/login")
async def login(payload: LoginRequest, request: Request) -> dict[str, object]:
    requested_main_id = payload.tenantId.strip()
    username = payload.username.strip()

    # QF-356: check rate limit before any database work.
    rate_limit_key = _login_rate_limit_key(request)
    _check_login_rate_limit(rate_limit_key)

    if requested_main_id:
        tenant_id = requested_main_id
        user = await find_account_by_username(username, tenant_id)
        if user is None:
            _record_login_failure(rate_limit_key)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")
        if user.get("status") != "active":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin user is disabled")
        await _assert_tenant_login_allowed(tenant_id)
        if not _password_matches(user, payload.password):
            _record_login_failure(rate_limit_key)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")
        # QF-358: clear rate limit on successful login.
        get_default_limiter().record_success(rate_limit_key)
        return await _issue_login_response(user, tenant_id, request)

    accounts = await list_accounts_by_username(username)
    matched_users = [
        account
        for account in accounts
        if account.get("status") == "active" and _password_matches(account, payload.password)
    ]

    if len(matched_users) > 1:
        candidates = [
            _candidate_from_user(user)
            for user in matched_users
            if not await _tenant_blocked_for_login(str(user.get("tenant_id") or ""))
        ]
        if not candidates:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant is not active")
        if len(candidates) > 1:
            return await _create_login_challenge(username, candidates)
        user = next(a for a in matched_users if str(a.get("tenant_id") or "") == str(candidates[0].get("tenantId")))
    else:
        user = matched_users[0] if matched_users else None

    if user is None:
        _record_login_failure(rate_limit_key)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")
    if user.get("status") != "active":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin user is disabled")
    tenant_id = str(user.get("tenant_id") or "").strip()
    if not tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin user has no tenant")
    await _assert_tenant_login_allowed(tenant_id)
    # QF-358: clear rate limit on successful login.
    get_default_limiter().record_success(rate_limit_key)
    return await _issue_login_response(user, tenant_id, request)


async def _tenant_blocked_for_login(tenant_id: str) -> bool:
    """True when the tenant row exists and is not active (archived / purged)."""
    if is_reserved_main_id(tenant_id) or tenant_id == PLATFORM_MAIN_ID:
        return False
    db = get_db()
    tenant = await db["tenants"].find_one({"tenant_id": tenant_id}, {"status": 1})
    return tenant is not None and str(tenant.get("status") or "") != "active"


@router.post("/login/select-tenant")
async def select_tenant(payload: SelectTenantRequest, request: Request) -> dict[str, object]:
    db = get_db()
    now = _now()
    challenge = await db[LOGIN_CHALLENGE_COLLECTION].find_one(
        {"challenge_token": payload.challengeToken, "status": "active"}
    )
    if not challenge:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Login challenge not found")
    expires_at = _as_utc(challenge.get("expires_at"))
    if expires_at and expires_at < now:
        await db[LOGIN_CHALLENGE_COLLECTION].update_one(
            {"_id": challenge["_id"]},
            {"$set": {"status": "expired", "updated_at": now}},
        )
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Login challenge expired")

    candidates = list(challenge.get("candidates") or [])
    selected = next((item for item in candidates if str(item.get("tenantId") or "") == payload.tenantId), None)
    if not selected:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Selected organization is not available")

    user = await find_account_by_username(str(challenge.get("username") or ""), payload.tenantId)
    if user is None or user.get("status") != "active":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Admin user is unavailable")
    await _assert_tenant_login_allowed(str(payload.tenantId))

    await db[LOGIN_CHALLENGE_COLLECTION].update_one(
        {"_id": challenge["_id"]},
        {"$set": {"status": "used", "updated_at": now, "used_main_id": payload.tenantId}},
    )
    return await _issue_login_response(user, payload.tenantId, request)


@router.get("/me")
async def me(current_user: dict = Depends(get_authenticated_admin)) -> dict[str, object]:
    return _profile_from_user(current_user, str(current_user["tenant_id"]))


@router.patch("/me")
async def update_me(
    payload: ProfileUpdateRequest,
    current_user: dict = Depends(get_authenticated_admin),
) -> dict[str, object]:
    tenant_id = str(current_user["tenant_id"])
    display_name = payload.name.strip()
    if not display_name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="姓名不能为空")
    updated = await update_account_profile(
        str(current_user["username"]),
        tenant_id,
        {
            "display_name": display_name,
            "email": payload.email.strip(),
            "phone": payload.phone.strip(),
        },
    )
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Admin user is unavailable")
    return _profile_from_user(updated, tenant_id)


@router.post("/me/password")
async def change_my_password(
    payload: PasswordChangeRequest,
    authorization: str | None = Header(default=None),
    current_user: dict = Depends(get_authenticated_admin),
) -> dict[str, bool]:
    if not _password_matches(current_user, payload.currentPassword):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前密码不正确")
    if payload.currentPassword == payload.newPassword:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="新密码不能与当前密码相同")

    # QF-338: enforce password strength policy server-side.
    strength_error = PasswordChangeRequest.validate_strength(payload.newPassword)
    if strength_error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=strength_error)

    tenant_id = str(current_user["tenant_id"])
    await set_account_password(str(current_user["username"]), payload.newPassword, tenant_id)

    if authorization and authorization.startswith("Bearer "):
        token = authorization.replace("Bearer ", "", 1).strip()
        decoded = decode_access_token(token)
        subject = decoded.get("sub") or {}
        session_id = subject.get("session_id")
        if session_id:
            await revoke_session(str(session_id))
    return {"success": True}


@router.post("/me/avatar")
async def upload_my_avatar(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_authenticated_admin),
) -> dict[str, object]:
    content_type = str(file.content_type or "").lower()
    ext = _avatar_extension(content_type, file.filename or "")
    max_bytes = int(settings.avatar_max_upload_mb or 2) * 1024 * 1024
    chunks: list[bytes] = []
    size = 0
    while True:
        chunk = await file.read(256 * 1024)
        if not chunk:
            break
        size += len(chunk)
        if size > max_bytes:
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="头像文件不能超过 2MB")
        chunks.append(chunk)
    data = b"".join(chunks)
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="头像文件不能为空")
    _validate_avatar_signature(data, ext)

    tenant_id = str(current_user["tenant_id"])
    username = str(current_user["username"])
    relative_dir = f"admin-avatars/{_safe_path_part(main_id, 'default')}"
    filename = f"{_safe_path_part(username, 'user')}-{uuid.uuid4().hex}.{ext}"
    relative_path = f"{relative_dir}/{filename}"
    static_root = Path(settings.admin_static_dir).expanduser().resolve()
    target = (static_root / relative_path).resolve()
    if static_root not in target.parents:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="头像路径无效")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)

    avatar_url = _avatar_public_url(relative_path)
    updated = await update_account_avatar(username, tenant_id, avatar_url)
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Admin user is unavailable")
    return _profile_from_user(updated, tenant_id)


@router.post("/logout")
async def logout(
    authorization: str | None = Header(default=None),
    current_user: dict = Depends(get_authenticated_admin),
) -> dict[str, bool]:
    del current_user
    if authorization and authorization.startswith("Bearer "):
        token = authorization.replace("Bearer ", "", 1).strip()
        payload = decode_access_token(token)
        subject = payload.get("sub") or {}
        session_id = subject.get("session_id")
        if session_id:
            await revoke_session(str(session_id))
    return {"success": True}


# ── MFA / TOTP endpoints (QF-342~347) ──────────────────────────────────


class MfaEnableRequest(BaseModel):
    secret: str = Field(min_length=16, max_length=64)
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class MfaDisableRequest(BaseModel):
    currentPassword: str = Field(min_length=1, max_length=128)


class MfaVerifyRequest(BaseModel):
    token: str = Field(min_length=20, max_length=256)
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


@router.post("/mfa/setup")
async def mfa_setup(current_user: dict = Depends(get_authenticated_admin)) -> dict[str, object]:
    """Generate a TOTP secret for MFA provisioning.

    Returns the base32 secret and an ``otpauth://`` URI that the frontend
    renders as a QR code.  The secret is NOT persisted until ``/mfa/enable``
    succeeds.
    """
    secret = generate_secret()
    uri = totp_uri(str(current_user.get("username") or ""), secret)
    return {"secret": secret, "otpauthUri": uri}


@router.post("/mfa/enable")
async def mfa_enable(
    payload: MfaEnableRequest,
    authorization: str | None = Header(default=None),
    current_user: dict = Depends(get_authenticated_admin),
) -> dict[str, bool]:
    """Verify a TOTP code and persist the encrypted secret to enable MFA.

    Flow:
    1. Verify the TOTP code against the raw secret (from /mfa/setup).
    2. Encrypt the raw secret with AES-256-GCM using the JWT secret.
    3. Store ``mfa_secret_encrypted`` (for future verification) and
       ``mfa_secret_hash`` (for integrity check).
    4. Revoke the current session — user must re-login with MFA.
    """
    if not verify_totp(payload.secret, payload.code):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="TOTP code is invalid")

    tenant_id = str(current_user["tenant_id"])
    username = str(current_user["username"])
    master_key = str(settings.jwt_secret)
    secret_hash = hashlib.sha256(payload.secret.encode("utf-8")).hexdigest()
    secret_encrypted = encrypt_secret(payload.secret, master_key)
    await _store_mfa_secret(username, tenant_id, secret_hash, secret_encrypted)

    # Revoke the current session — the user must re-login with MFA.
    if authorization and authorization.startswith("Bearer "):
        token = authorization.replace("Bearer ", "", 1).strip()
        decoded = decode_access_token(token)
        subject = decoded.get("sub") or {}
        session_id = subject.get("session_id")
        if session_id:
            await revoke_session(str(session_id))
    return {"success": True}


@router.post("/mfa/disable")
async def mfa_disable(
    payload: MfaDisableRequest,
    authorization: str | None = Header(default=None),
    current_user: dict = Depends(get_authenticated_admin),
) -> dict[str, bool]:
    """Disable MFA after verifying the current password."""
    if not _password_matches(current_user, payload.currentPassword):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前密码不正确")

    tenant_id = str(current_user["tenant_id"])
    username = str(current_user["username"])
    await _clear_mfa_secret(username, tenant_id)

    if authorization and authorization.startswith("Bearer "):
        token = authorization.replace("Bearer ", "", 1).strip()
        decoded = decode_access_token(token)
        subject = decoded.get("sub") or {}
        session_id = subject.get("session_id")
        if session_id:
            await revoke_session(str(session_id))
    return {"success": True}


@router.post("/mfa/verify")
async def mfa_verify(payload: MfaVerifyRequest) -> dict[str, object]:
    """Two-step login: verify TOTP code after password succeeds.

    The first step (``POST /login``) returns ``{"mfaRequired": true, "mfaToken": "..."}``.
    The client calls this endpoint with the mfaToken + TOTP code.  On success
    a real access token is issued.
    """
    from app.core.db import get_db as _get_db

    try:
        decoded = decode_access_token(payload.token)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="mfaToken expired or invalid")

    subject = decoded.get("sub") or {}
    username = str(subject.get("username") or "")
    tenant_id = str(subject.get("tenant_id") or "")
    session_id = str(subject.get("session_id") or "")
    if not username or not tenant_id or not session_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid mfaToken")

    db = _get_db()
    user_doc = await db["admin_accounts"].find_one({"username": username, "tenant_id": tenant_id})
    if not user_doc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

    secret_hash = str(user_doc.get("mfa_secret_hash") or "")
    if not secret_hash:
        # MFA was disabled after the login started; fall through.
        token_out, expires_at, sid = await _issue_mfa_login_response(
            db, user_doc, tenant_id, session_id
        )
        return {
            "success": True,
            "accessToken": token_out,
            "expiresAt": expires_at,
            "sessionId": sid,
        }

    # Decrypt the stored secret and verify the TOTP code.
    secret_encrypted = str(user_doc.get("mfa_secret_encrypted") or "")
    if not secret_encrypted:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="MFA secret not found")

    master_key = str(settings.jwt_secret)
    raw_secret = verify_and_decrypt(secret_encrypted, master_key)
    if not raw_secret:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="MFA secret integrity check failed")

    # Integrity check: verify the decrypted secret matches the stored hash.
    computed_hash = hashlib.sha256(raw_secret.encode("utf-8")).hexdigest()
    if not hmac.compare_digest(computed_hash, secret_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="MFA secret integrity check failed")

    if not verify_totp(raw_secret, payload.code):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="TOTP code is invalid")

    token_out, expires_at, sid = await _issue_mfa_login_response(
        db, user_doc, tenant_id, session_id
    )
    return {
        "success": True,
        "accessToken": token_out,
        "expiresAt": expires_at,
        "sessionId": sid,
    }


async def _store_mfa_secret(username: str, tenant_id: str, secret_hash: str, secret_encrypted: str) -> None:
    """Persist the hashed and encrypted TOTP secret to the user's account document."""
    from app.core.db import get_db as _get_db

    db = _get_db()
    await db["admin_accounts"].update_one(
        {"username": username, "tenant_id": tenant_id},
        {
            "$set": {
                "mfa_enabled": True,
                "mfa_secret_hash": secret_hash,
                "mfa_secret_encrypted": secret_encrypted,
                "updated_at": _now(),
            }
        },
    )


async def _clear_mfa_secret(username: str, tenant_id: str) -> None:
    """Remove MFA secret from the user's account document."""
    from app.core.db import get_db as _get_db

    db = _get_db()
    await db["admin_accounts"].update_one(
        {"username": username, "tenant_id": tenant_id},
        {
            "$set": {"mfa_enabled": False, "updated_at": _now()},
            "$unset": {"mfa_secret_hash": "", "mfa_secret_encrypted": ""},
        },
    )


async def _issue_mfa_login_response(
    db, user_doc: dict, tenant_id: str, session_id: str
) -> tuple[str, int, str]:
    """Issue a full access token after MFA verification succeeds."""
    username = str(user_doc.get("username") or "")
    display_name = str(user_doc.get("display_name") or username)
    token, expires_at, sid = create_access_token(
        {
            "username": username,
            "tenant_id": tenant_id,
            "display_name": display_name,
            "role_name": str(user_doc.get("role_name") or ""),
            "org_name": str(user_doc.get("org_name") or user_doc.get("group_code") or ""),
            "mfa_verified": True,
        },
        expires_in_seconds=3600,
    )
    # Reuse the original session_id if available, otherwise create a new one.
    await create_session(sid, username, tenant_id, expires_at)
    return token, expires_at, sid


# ── QF-350: Refresh token rotation with replay detection ─────────────────

REFRESH_TOKEN_COLLECTION = "admin_refresh_tokens"
RECOVERY_TOKEN_COLLECTION = "admin_recovery_tokens"


class RefreshTokenRequest(BaseModel):
    refreshToken: str = Field(min_length=50, max_length=500)


class SessionRevokeRequest(BaseModel):
    sessionId: str = Field(min_length=10, max_length=64)


class RecoveryRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    tenantId: str = Field(default="", max_length=64)


class RecoveryResetRequest(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    newPassword: str = Field(min_length=10, max_length=128)


@router.post("/refresh")
async def refresh_token(payload: RefreshTokenRequest) -> dict[str, object]:
    """QF-350: Rotate refresh token and detect replay.

    Flow:
    1. Decode the refresh token.
    2. Check if the token ID has been used before (replay detection).
    3. If used, revoke the entire family and return 401.
    4. If not used, mark it as used and issue a new token.
    5. Also check session timeout (QF-352).
    """
    from app.repositories.admin_session_repository import create_session, revoke_session
    from app.repositories.org_user_repository import find_account_by_username

    try:
        decoded = decode_refresh_token(payload.refreshToken)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    subject = decoded.get("sub") or {}
    username = str(subject.get("username") or "")
    tenant_id = str(subject.get("tenant_id") or "")
    family_id = str(decoded.get("fid") or "")
    token_id = str(decoded.get("jti") or "")

    if not username or not tenant_id or not family_id or not token_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    db = get_db()

    # QF-350: Check if this token ID has been used before (replay detection).
    used_token = await db[REFRESH_TOKEN_COLLECTION].find_one({"token_id": token_id})
    if used_token:
        # Replay detected! Revoke the entire family.
        await db[REFRESH_TOKEN_COLLECTION].delete_many({"family_id": family_id})
        await db["admin_sessions"].delete_many({"tenant_id": tenant_id, "username": username})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token reuse detected. All sessions revoked.",
        )

    # QF-352: Check absolute session timeout.
    created_at = int(used_token.get("created_at") or 0) if used_token else 0
    # If no record yet, this is the first use — check the session.
    session_doc = None
    if family_id:
        session_doc = await db["admin_sessions"].find_one({"session_id": family_id, "tenant_id": tenant_id})
        if session_doc:
            session_created = int(session_doc.get("created_at") or 0)
            if session_created and (int(time.time()) - session_created) > ABSOLUTE_TIMEOUT_SECONDS:
                # Absolute timeout exceeded — revoke family.
                await db[REFRESH_TOKEN_COLLECTION].delete_many({"family_id": family_id})
                await db["admin_sessions"].delete_many({"session_id": family_id, "tenant_id": tenant_id})
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Session expired. Please log in again.",
                )
            # Update last activity for idle timeout tracking.
            await db["admin_sessions"].update_one(
                {"session_id": family_id, "tenant_id": tenant_id},
                {"$set": {"last_activity_at": int(time.time())}},
            )

    # Mark the current token as used.
    await db[REFRESH_TOKEN_COLLECTION].insert_one({
        "token_id": token_id,
        "family_id": family_id,
        "username": username,
        "tenant_id": tenant_id,
        "created_at": int(time.time()),
    })

    # Issue a new refresh token with the same family ID.
    user = await find_account_by_username(username, tenant_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    new_refresh, new_refresh_exp, new_token_id, new_family = create_refresh_token(
        {"username": username, "tenant_id": tenant_id},
        family_id=family_id,
    )
    await db[REFRESH_TOKEN_COLLECTION].insert_one({
        "token_id": new_token_id,
        "family_id": new_family,
        "username": username,
        "tenant_id": tenant_id,
        "created_at": int(time.time()),
        "is_current": True,
    })
    # Mark old token as not current.
    await db[REFRESH_TOKEN_COLLECTION].update_one(
        {"token_id": token_id, "family_id": family_id},
        {"$set": {"is_current": False}},
    )

    # Issue a new access token.
    token, expires_at, sid = create_access_token(
        {
            "username": username,
            "tenant_id": tenant_id,
            "display_name": str(user.get("display_name") or username),
            "role_name": str(user.get("role_name") or ""),
            "org_name": str(user.get("org_name") or user.get("group_code") or ""),
        },
        expires_in_seconds=3600,
    )

    return {
        "accessToken": token,
        "refreshToken": new_refresh,
        "expiresAt": expires_at,
        "refreshExpiresAt": new_refresh_exp,
        "sessionId": sid,
    }


# ── QF-354: Active session enumeration and remote revocation ──────────────


@router.get("/sessions")
async def list_sessions(
    authorization: str | None = Header(default=None),
    current_user: dict = Depends(get_authenticated_admin),
) -> dict[str, object]:
    """QF-354: List active sessions for the current user."""
    from app.repositories.admin_session_repository import list_sessions_for_user

    tenant_id = str(current_user["tenant_id"])
    username = str(current_user["username"])
    sessions = await list_sessions_for_user(username, tenant_id)

    current_session_id = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.replace("Bearer ", "", 1).strip()
        try:
            decoded = decode_access_token(token)
            subject = decoded.get("sub") or {}
            current_session_id = subject.get("session_id")
        except ValueError:
            pass

    return {
        "sessions": [
            {
                "sessionId": s.get("session_id"),
                "createdAt": s.get("created_at"),
                "lastActivityAt": s.get("last_activity_at"),
                "expiresAt": s.get("token_expires_at"),
                "userAgent": s.get("user_agent"),
                "ip": s.get("ip"),
                "isCurrent": s.get("session_id") == current_session_id,
            }
            for s in sessions
        ],
    }


@router.post("/sessions/revoke")
async def revoke_session_endpoint(
    payload: SessionRevokeRequest,
    authorization: str | None = Header(default=None),
    current_user: dict = Depends(get_authenticated_admin),
) -> dict[str, bool]:
    """QF-354: Revoke a specific session."""
    from app.repositories.admin_session_repository import revoke_session

    tenant_id = str(current_user["tenant_id"])
    username = str(current_user["username"])

    # Verify the session belongs to the current user.
    db = get_db()
    session = await db["admin_sessions"].find_one(
        {"session_id": payload.sessionId, "tenant_id": tenant_id, "username": username}
    )
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    await revoke_session(payload.sessionId)
    # Also revoke all refresh tokens in this family.
    await db[REFRESH_TOKEN_COLLECTION].delete_many({"family_id": payload.sessionId, "tenant_id": tenant_id})
    return {"success": True}


# ── QF-357/363: Password recovery without leaking account existence ───────


@router.post("/recover/request")
async def request_recovery(payload: RecoveryRequest) -> dict[str, object]:
    """QF-357/363: Request password recovery.

    Always returns the same response regardless of whether the account exists,
    to prevent account enumeration. The recovery token is sent via email/SMS
    (mocked here — in production, wire up an email service).
    """
    username = payload.username.strip()
    tenant_id = payload.tenantId.strip() or "default"

    # Always respond with the same message (QF-357: no account existence leak).
    response_message = "若该账号存在，恢复令牌已发送至您的注册邮箱"

    # Try to find the account. If found, generate a recovery token.
    from app.repositories.org_user_repository import find_account_by_username

    user = await find_account_by_username(username, tenant_id)
    if user and user.get("status") == "active":
        token, expires_at, token_hash = create_recovery_token(username, tenant_id, "password_reset")
        db = get_db()
        await db[RECOVERY_TOKEN_COLLECTION].insert_one({
            "token_hash": token_hash,
            "username": username,
            "tenant_id": tenant_id,
            "purpose": "password_reset",
            "expires_at": expires_at,
            "used": False,
            "created_at": int(time.time()),
        })
        # In production, send the token via email/SMS.
        # For now, return it for development/testing.
        import logging
        logger = logging.getLogger(__name__)
        logger.info("Recovery token generated for %s (dev mode: token returned in response)", mask_identifier(username))

    return {
        "success": True,
        "message": response_message,
    }


@router.post("/recover/reset")
async def reset_with_recovery(payload: RecoveryResetRequest) -> dict[str, bool]:
    """QF-360/361: Reset password using a recovery token.

    - Token must be high-entropy, one-time, and short-lived.
    - After successful reset, the token is immediately invalidated.
    - All sessions for the account are revoked.
    """
    token = payload.token.strip()
    if not token or len(token) < 20:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid token")

    token_hash = hash_recovery_token(token)
    db = get_db()

    # Find the recovery token (QF-360: bound to account and purpose).
    doc = await db[RECOVERY_TOKEN_COLLECTION].find_one({
        "token_hash": token_hash,
        "used": False,
    })

    if doc is None:
        # QF-361: token expired or already used.
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="令牌已过期或已被使用")

    # QF-361: Check expiration.
    expires_at = int(doc.get("expires_at") or 0)
    if expires_at and int(time.time()) > expires_at:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="令牌已过期")

    username = str(doc.get("username") or "")
    tenant_id = str(doc.get("tenant_id") or "")
    purpose = str(doc.get("purpose") or "")

    if not username or purpose != "password_reset":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid token")

    # Validate new password strength.
    from app.api.routes.auth import PasswordChangeRequest
    strength_error = PasswordChangeRequest.validate_strength(payload.newPassword)
    if strength_error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=strength_error)

    # Update password.
    from app.repositories.org_user_repository import set_account_password
    await set_account_password(username, payload.newPassword, tenant_id)

    # QF-361: Immediately invalidate the token (one-time use).
    await db[RECOVERY_TOKEN_COLLECTION].update_one(
        {"_id": doc["_id"]},
        {"$set": {"used": True, "used_at": int(time.time())}},
    )

    # Revoke all sessions for this account.
    await db["admin_sessions"].delete_many({"tenant_id": tenant_id, "username": username})
    await db[REFRESH_TOKEN_COLLECTION].delete_many({"tenant_id": tenant_id, "username": username})

    return {"success": True}
