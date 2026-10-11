from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, status

from app.core.config import settings


def constant_time_equals(candidate: str, expected: str) -> bool:
    """Compare two secrets in constant time.

    Both sides are encoded to UTF-8 first so that a non-ASCII header value
    cannot make ``hmac.compare_digest`` raise ``TypeError``, which would turn
    an auth rejection into a 500.
    """
    return hmac.compare_digest(
        str(candidate or "").encode("utf-8"),
        str(expected or "").encode("utf-8"),
    )


async def verify_service_token(authorization: str | None = Header(default=None)) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    token = authorization.replace("Bearer ", "", 1).strip()
    if not constant_time_equals(token, settings.service_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid service token")
