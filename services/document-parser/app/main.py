from __future__ import annotations

from fastapi import FastAPI

from app.api.router import api_router
from app.core.config import settings
from app.core.db import close_db
from app.core.error_handler import register_error_handlers
from app.middleware.trace_id import TraceIdMiddleware
from app.observability.logging import init_doc_parser_logging
from app.observability.health import router as health_router
from app.repositories.job_repository import ensure_job_indexes


def create_app() -> FastAPI:
    is_prod = str(getattr(settings, "app_env", "development")).strip().lower() in {
        "production",
        "prod",
        "release",
    }
    app = FastAPI(
        title="MOGO Document Processing Service",
        # Keep in sync with the release version recorded in CHANGELOG.md: this
        # is the value published in /openapi.json info.version, i.e. an
        # externally visible contract, not a private cosmetic string.
        version="0.2.5",
        description="Async document preview conversion, parsing, chunking and indexing service for MOGO.",
    )
    # 023 T021：接入 structlog 结构化日志
    init_doc_parser_logging()
    # 023 T035: 初始化 OpenTelemetry 追踪（OTLP → Tempo）
    from app.common.observability_base import init_tracing, instrument_fastapi, instrument_httpx
    init_tracing("mogo-document-parser")
    instrument_httpx()
    # 025 Phase 1（T006）：trace_id 中间件 + 统一异常处理器（422/500）。
    app.add_middleware(TraceIdMiddleware)
    register_error_handlers(app, is_prod=is_prod)
    app.include_router(api_router, prefix="/api")
    # 023 T021：observability health_router（/ready 依赖可达性检查）
    app.include_router(health_router)

    # 023 T035: FastAPI 自动插桩（HTTP server span）
    instrument_fastapi(app)

    @app.on_event("startup")
    def startup() -> None:
        ensure_job_indexes()

    @app.on_event("shutdown")
    def shutdown() -> None:
        close_db()

    return app


app = create_app()
