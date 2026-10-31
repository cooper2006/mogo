"""Authenticated archive delivery to the DSH host adapter."""

from __future__ import annotations

import hmac
import re

from fastapi import APIRouter, Header, HTTPException, Request
from motor.motor_asyncio import AsyncIOMotorGridFSBucket
from starlette.responses import StreamingResponse

from app.core.config import get_settings
from app.core.db import get_db
from app.dsh_runtime.model_gateway.token import ModelGatewayTokenService
from app.dsh_runtime.plugin_management.archive_store import BUCKET_NAME, MAX_ARCHIVE_BYTES
from app.dsh_runtime.profile.store import PROFILE_COLLECTION

router = APIRouter(prefix="/internal/dsh/plugin-archives", tags=["dsh-internal"])
FILE_ID = re.compile(r"^[0-9a-f]{32}$")
DIGEST = re.compile(r"^[0-9a-f]{64}$")


@router.get("/{archive_id}")
async def download(archive_id: str, digest: str, request: Request, authorization: str = Header(default="")):
    settings = get_settings()
    host_secret = str(settings.DSH_RUNTIME_HOST_TOKEN or "")
    host_authorized = bool(host_secret and hmac.compare_digest(authorization, f"Bearer {host_secret}"))
    claims = None
    if not host_authorized and not (
        not host_secret and not authorization and request.client and request.client.host in {"127.0.0.1", "::1"}
    ):
        token = authorization.removeprefix("Bearer ") if authorization.startswith("Bearer ") else ""
        secret = str(settings.DSH_MODEL_GATEWAY_SIGNING_SECRET or settings.ASKAI_ADMIN_JWT_SECRET or "")
        try:
            claims = ModelGatewayTokenService(secret).verify(token)
        except ValueError as exc:
            raise HTTPException(status_code=401, detail="Invalid plugin archive credential") from exc
    if not FILE_ID.fullmatch(archive_id) or not DIGEST.fullmatch(digest):
        raise HTTPException(status_code=404, detail="Plugin archive not found")
    db = get_db()
    record = await db[f"{BUCKET_NAME}.files"].find_one({"_id": archive_id})
    if not record or int(record.get("length") or 0) > MAX_ARCHIVE_BYTES or (record.get("metadata") or {}).get("digest") != digest:
        raise HTTPException(status_code=404, detail="Plugin archive not found")
    if claims:
        if (record.get("metadata") or {}).get("main_id") != claims.tenant_id:
            raise HTTPException(status_code=404, detail="Plugin archive not found")
        profile = await db[PROFILE_COLLECTION].find_one({
            "profile_version": claims.profile_version,
            "tenant_id": claims.tenant_id,
            "subject_user_id": claims.user_id,
            "plugins": {"$elemMatch": {"archive_id": archive_id, "archive_digest": digest}},
        }, {"_id": 1})
        if profile is None:
            raise HTTPException(status_code=404, detail="Plugin archive not found")
    stream = await AsyncIOMotorGridFSBucket(db, bucket_name=BUCKET_NAME).open_download_stream(archive_id)

    async def chunks():
        while chunk := await stream.read(1024 * 1024):
            yield chunk

    return StreamingResponse(chunks(), media_type="application/gzip")
