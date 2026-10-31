"""Private, streamed Skill archive delivery to the MOGO DSH host adapter."""

from __future__ import annotations

import hmac
import re

from fastapi import APIRouter, Header, HTTPException, Request
from motor.motor_asyncio import AsyncIOMotorGridFSBucket
from starlette.responses import StreamingResponse

from app.core.config import get_settings
from app.core.db import get_db
from app.dsh_runtime.model_gateway.token import ModelGatewayTokenService
from app.dsh_runtime.profile.store import PROFILE_COLLECTION
from app.services.skill_packages.archive_store import BUCKET_NAME, MAX_ARCHIVE_BYTES


router = APIRouter(prefix="/internal/dsh/skill-bundles", tags=["dsh-internal"])
FILE_ID = re.compile(r"^[0-9a-f]{32}$")
DIGEST = re.compile(r"^[0-9a-f]{64}$")


@router.get("/{file_id}")
async def download(file_id: str, request: Request, digest: str, authorization: str = Header(default="")):
    settings = get_settings()
    secret = str(settings.DSH_RUNTIME_HOST_TOKEN or "")
    host_authorized = bool(secret and hmac.compare_digest(authorization, f"Bearer {secret}"))
    model_claims = None
    if not host_authorized:
        token = authorization.removeprefix("Bearer ") if authorization.startswith("Bearer ") else ""
        if token:
            signing_secret = str(settings.DSH_MODEL_GATEWAY_SIGNING_SECRET or settings.ASKAI_ADMIN_JWT_SECRET or "")
            try:
                model_claims = ModelGatewayTokenService(signing_secret).verify(token)
            except ValueError as exc:
                raise HTTPException(status_code=401, detail="Invalid DSH bundle credential") from exc
        elif secret or not request.client or request.client.host not in {"127.0.0.1", "::1"}:
            raise HTTPException(status_code=401, detail="DSH bundle credential is required")
    if not FILE_ID.fullmatch(file_id) or not DIGEST.fullmatch(digest):
        raise HTTPException(status_code=404, detail="Skill archive not found")

    db = get_db()
    record = await db[f"{BUCKET_NAME}.files"].find_one({"_id": file_id})
    if not record or int(record.get("length") or 0) > MAX_ARCHIVE_BYTES:
        raise HTTPException(status_code=404, detail="Skill archive not found")
    if (record.get("metadata") or {}).get("digest") != digest:
        raise HTTPException(status_code=404, detail="Skill archive not found")
    if model_claims and (record.get("metadata") or {}).get("main_id") != model_claims.tenant_id:
        raise HTTPException(status_code=404, detail="Skill archive not found")
    if model_claims:
        profile = await db[PROFILE_COLLECTION].find_one({
            "profile_version": model_claims.profile_version,
            "tenant_id": model_claims.tenant_id,
            "subject_user_id": model_claims.user_id,
            "skills": {"$elemMatch": {"bundle_archive_id": file_id, "bundle_digest": digest}},
        }, {"_id": 1})
        if profile is None:
            raise HTTPException(status_code=404, detail="Skill archive not found")
    stream = await AsyncIOMotorGridFSBucket(db, bucket_name=BUCKET_NAME).open_download_stream(file_id)

    async def chunks():
        while chunk := await stream.read(1024 * 1024):
            yield chunk

    return StreamingResponse(chunks(), media_type="application/zip")
