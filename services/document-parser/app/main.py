from __future__ import annotations

from fastapi import FastAPI

from app.api.router import api_router
from app.core.db import close_db
from app.repositories.job_repository import ensure_job_indexes


def create_app() -> FastAPI:
    app = FastAPI(
        title="MOGO Document Processing Service",
        # Keep in sync with the release version recorded in CHANGELOG.md: this
        # is the value published in /openapi.json info.version, i.e. an
        # externally visible contract, not a private cosmetic string.
        version="0.2.1",
        description="Async document preview conversion, parsing, chunking and indexing service for MOGO.",
    )
    app.include_router(api_router, prefix="/api")

    @app.on_event("startup")
    def startup() -> None:
        ensure_job_indexes()

    @app.on_event("shutdown")
    def shutdown() -> None:
        close_db()

    return app


app = create_app()
