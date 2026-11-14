"""Token-protected read-only deployment status service."""

from __future__ import annotations

import hmac
import os

from fastapi import FastAPI, Header, HTTPException

from .deployment_status import inventory
from .docker_engine import DockerEngine


app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


def _authorize(authorization: str | None) -> None:
    # MOVO_ 是 MOGO_ 的历史别名，两个前缀指向同一个密钥（bootstrap 同步写入）。
    # 这里按 MOVO_ → MOGO_ 的顺序回退，旧卷里只写了一个名字时也能鉴权通过。
    token = (
        os.environ.get("MOVO_SANDBOX_MANAGER_TOKEN")
        or os.environ.get("MOGO_SANDBOX_MANAGER_TOKEN", "")
    )
    supplied = (authorization or "").removeprefix("Bearer ")
    if not token or not hmac.compare_digest(token, supplied):
        raise HTTPException(status_code=401, detail="Unauthorized")


@app.get("/health")
def health(authorization: str | None = Header(default=None)) -> dict:
    _authorize(authorization)
    engine = DockerEngine()
    try:
        engine.request("GET", "/_ping")
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Docker Engine unavailable") from exc
    finally:
        engine.client.close()
    return {"ok": True}


@app.get("/status")
def status(authorization: str | None = Header(default=None)) -> dict:
    _authorize(authorization)
    engine = DockerEngine()
    try:
        return inventory(engine)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Deployment status unavailable") from exc
    finally:
        engine.client.close()
