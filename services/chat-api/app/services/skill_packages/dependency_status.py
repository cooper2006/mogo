"""Read dependency preparation state through the authenticated manager API."""

from __future__ import annotations

import os

import httpx


async def dependency_status(digest: str) -> str:
    url = os.environ.get("MOGO_SANDBOX_MANAGER_URL", "").strip().rstrip("/")
    if not url:
        return "disabled"
    token = os.environ.get("MOGO_SANDBOX_MANAGER_TOKEN", "")
    if len(token) < 32:
        return "unavailable"
    try:
        async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
            response = await client.get(
                f"{url}/v1/skill-environments/{digest}",
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()
            return str(response.json().get("status") or "unavailable")
    except (httpx.HTTPError, ValueError):
        return "unavailable"
