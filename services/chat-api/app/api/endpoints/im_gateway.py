"""IM gateway webhook endpoint (feature 013).

Minimal production wiring: receives inbound IM webhooks, verifies HMAC
signatures (FR-13), and routes to the appropriate channel adapter.
Persisted session bindings are tracked as a follow-up (FR-4 / FR-9).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request

from app.im_gateway.router import ChannelRouter
from app.im_gateway.webhook import NonceCache, verify_signature

router = APIRouter(prefix="/internal/im", tags=["im-gateway-internal"])

# Module-level router with an in-memory nonce cache.
_router = ChannelRouter()
_nonce_cache = NonceCache()


@router.post("/webhook/{channel}")
async def handle_webhook(
    channel: str,
    request: Request,
    x_im_timestamp: str = Header(alias="X-IM-Timestamp"),
    x_im_nonce: str = Header(default="", alias="X-IM-Nonce"),
    x_im_signature: str = Header(default="", alias="X-IM-Signature"),
    authorization: str = Header(default=""),
) -> dict[str, Any]:
    """Receive an inbound IM webhook, verify signature, and route (FR-13)."""
    from app.api.endpoints.auth import _resolve_session_user
    from app.core.config import get_settings

    await _resolve_session_user(authorization)

    settings = get_settings()
    secret = str(settings.IM_WEBHOOK_SECRET or "")
    if not secret:
        raise HTTPException(status_code=500, detail="webhook_secret_not_configured")

    body = await request.body()
    try:
        timestamp = int(x_im_timestamp)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="missing_or_invalid_X_IM_Timestamp")

    # Replay protection.
    if not _nonce_cache.check_and_store(x_im_nonce, now=timestamp):
        raise HTTPException(status_code=409, detail="replayed_nonce")

    try:
        verify_signature(
            secret=secret,
            body=body,
            nonce=x_im_nonce,
            timestamp=timestamp,
            signature=x_im_signature,
        )
    except Exception as exc:  # WebhookSignatureError subclasses PermissionError
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    # Parse and route.
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid_json")

    msg = _router.route(channel, payload)
    # Acknowledge receipt; actual reply is handled by the adapter asynchronously.
    return {
        "code": 0,
        "message": "received",
        "data": {
            "channel": msg.channel,
            "conversation_id": msg.channel_conversation_id,
            "sender_id": msg.sender_id,
        },
    }


__all__ = ["router"]
