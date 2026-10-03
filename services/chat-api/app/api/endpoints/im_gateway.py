"""IM gateway webhook endpoint (feature 013).

Production wiring: receives inbound IM webhooks, verifies HMAC signatures
(FR-13), and routes to the appropriate channel adapter. Session bindings are
persisted via ``PersistedSessionBindingRegistry`` (``im_session_bindings`` /
``im_channels`` collections, FR-10); when the DB is unavailable the webhook
degrades to the in-memory registry rather than fabricating state.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request

from app.im_gateway.bindings import PersistedSessionBindingRegistry
from app.im_gateway.router import ChannelRouter
from app.im_gateway.webhook import NonceCache, verify_signature

router = APIRouter(prefix="/internal/im", tags=["im-gateway-internal"])

# Module-level router with an in-memory nonce cache.
_router = ChannelRouter()
_nonce_cache = NonceCache()
_bindings = PersistedSessionBindingRegistry()


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

    # 013 FR-10: channel switch state is persisted (im_channels). A disabled
    # channel rejects new messages (FR-9); DB unavailability degrades to
    # "enabled" (fail-open for routing, the switch itself was never persisted).
    tenant_id = str(await request.headers.get("x-im-tenant", "default")) or "default"
    if not await _bindings.is_channel_enabled(channel, tenant_id=tenant_id):
        raise HTTPException(status_code=409, detail="channel_disabled")

    # Parse and route.
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid_json")

    msg = _router.route(channel, payload)
    # 013 FR-10: persist the conversation <-> session binding (first binder
    # wins, FR-14) so a restart does not lose the 1:1 mapping.
    session_ref = str(payload.get("session_id") or payload.get("movoSessionId") or "")
    if session_ref:
        await _bindings.bind(
            channel=msg.channel,
            conversation_id=msg.channel_conversation_id,
            movo_session_id=session_ref,
            tenant_id=tenant_id,
            initiator=str(payload.get("sender_id") or ""),
        )
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
