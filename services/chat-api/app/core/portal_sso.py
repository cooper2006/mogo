"""029：门户 SSO 接收方——一次性登录票据的签发、验签与幂等消费。

门户（外部门户 / 集成站点）以**服务身份**调用 ``/api/auth/portal-ticket``，
chat-api 校验服务身份后，为该 MOGO 终端用户签发一张一次性票据（本模块负责
签名）。门户把票据通过前端 ``window.history.state`` 带进 user-web，user-web 再
调用 ``/api/auth/portal-exchange`` 换票建会话（验签 + accept-once 在本模块）。

设计约束（来自 spec 029 / docs/MOGO-Web应用集成方案.md §1.3.2）：
- 票据是**一次性**换票凭证，TTL 固定 60 秒（fail-closed，过期即作废）。
- 签名密钥使用 ``settings.PORTAL_SSO_SECRET``，未单独配置时回退 END_USER_AUTH_SECRET。
- 验签 **fail-closed**：格式错、签名错、过期、被复用均拒绝。
- 票据**绝不下落 URL**；accept-once 用 ``upsert=True`` 兜底并发复用药。
- 复用与 022 admin_sso 相同的票据形状：``base64url(payload).base64url(HMAC-SHA256)``。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
from typing import Any

from app.core.config import get_settings

#: 029：票据只用于一次性 POST 换票，窗口固定 60 秒（与 022 admin_sso 保持一致）。
PORTAL_SSO_TOKEN_TTL_SECONDS = 60

#: end_user_sessions 中标记票据已消费的字段。
PORTAL_TICKET_EXCHANGED_FIELD = "exchanged"


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")


def _b64url_decode(payload: str) -> bytes:
    padding = "=" * (-len(payload) % 4)
    return base64.urlsafe_b64decode(payload + padding)


def create_portal_ticket(
    secret: str,
    *,
    user_id: str,
    username: str,
    tenant_id: str = "",
    ttl_seconds: int = PORTAL_SSO_TOKEN_TTL_SECONDS,
) -> tuple[str, int, str]:
    """签发一张一次性门户登录票据。

    返回 ``(token, expires_at_unix, session_id)``。``session_id`` 用作 accept-once
    的幂等键（与 022 admin_sso 一致）。
    """
    expires_at = int(time.time()) + max(1, int(ttl_seconds))
    session_id = str(uuid.uuid4())
    subject = {
        "user_id": str(user_id),
        "username": str(username),
        "tenant_id": str(tenant_id or ""),
        "session_id": session_id,
    }
    payload = {"sub": subject, "exp": expires_at}
    encoded_payload = _b64url_encode(
        json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    )
    signature = hmac.new(
        secret.encode("utf-8"),
        encoded_payload.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    encoded_signature = _b64url_encode(signature)
    return f"{encoded_payload}.{encoded_signature}", expires_at, session_id


def verify_portal_ticket(secret: str, token: str) -> dict[str, Any]:
    """验签并解析一次性门户登录票据。

    **fail-closed**：格式非法、签名不匹配或已过期均抛 ``PortalTicketInvalid``。
    成功返回 ``payload["sub"]``（含 ``user_id`` / ``username`` / ``tenant_id`` / ``session_id``）。
    """
    if not token or not isinstance(token, str):
        raise PortalTicketInvalid("empty_token")
    parts = token.split(".")
    if len(parts) != 2:
        raise PortalTicketInvalid("malformed")
    encoded_payload, encoded_signature = parts

    try:
        payload_bytes = _b64url_decode(encoded_payload)
        payload = json.loads(payload_bytes.decode("utf-8"))
    except Exception:  # noqa: BLE001 — 任何解析失败都视为非法票据
        raise PortalTicketInvalid("malformed")

    expected = hmac.new(
        secret.encode("utf-8"),
        encoded_payload.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    try:
        provided = _b64url_decode(encoded_signature)
    except Exception:  # noqa: BLE001
        raise PortalTicketInvalid("malformed")
    if not hmac.compare_digest(expected, provided):
        raise PortalTicketInvalid("bad_signature")

    exp = payload.get("exp")
    if not isinstance(exp, (int, float)):
        raise PortalTicketInvalid("missing_exp")
    if int(time.time()) >= int(exp):
        raise PortalTicketInvalid("expired")

    sub = payload.get("sub")
    if not isinstance(sub, dict) or not sub.get("user_id"):
        raise PortalTicketInvalid("missing_subject")
    return sub


class PortalTicketInvalid(ValueError):
    """票据验签失败的具体原因（签名错 / 过期 / 格式错）。"""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


async def mark_ticket_exchanged(db: Any, session_id: str) -> bool:
    """幂等消费票据：首次标记成功返回 ``True``，已消费返回 ``False``。

    使用条件更新 + ``upsert=True``：过滤器 ``{session_id, exchanged:{$ne:True}}`` 只在
    票据尚未消费时命中，命中的那一次 ``modified_count==1``（唯一赢家）；已消费的行
    不再命中，第二次及以后 ``modified_count==0`` → 拒绝，从而保证 accept-once。
    ``upsert`` 兜底并发/预插缺失场景，保证 fail-closed（缺行时不放行）。
    """
    from app.api.endpoints.auth import USER_SESSION_COLLECTION  # 避免循环导入

    result = await db[USER_SESSION_COLLECTION].update_one(
        {"session_id": session_id, PORTAL_TICKET_EXCHANGED_FIELD: {"$ne": True}},
        {"$set": {PORTAL_TICKET_EXCHANGED_FIELD: True, "exchanged_at": _now()}},
        upsert=True,
    )
    return result.modified_count == 1


def _now() -> Any:
    from datetime import datetime, timezone

    return datetime.now(tz=timezone.utc)


def portal_sso_secret() -> str:
    """返回门户票据签名密钥（含 PORTAL_SSO_SECRET → END_USER_AUTH_SECRET 回退）。"""
    return get_settings().PORTAL_SSO_SECRET
