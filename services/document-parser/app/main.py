from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.error_locale import localize_detail
from app.api.router import api_router
from app.core.config import settings
from app.core.db import close_db
from app.core.error_handler import register_error_handlers
from app.middleware.trace_id import TraceIdMiddleware
from app.middleware.legacy_api_redirect import LegacyApiRedirectMiddleware
from app.observability.logging import init_doc_parser_logging
from app.observability.health import router as health_router
from app.core.request_body_limit import RequestBodyLimitMiddleware
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
    from app.common.observability_base import init_tracing, instrument_fastapi, instrument_httpx, init_metrics, get_registry, metrics_asgi_app
    init_tracing("mogo-document-parser")
    instrument_httpx()
    # 023 T049: Prometheus metrics 初始化
    doc_metrics = init_metrics("mogo-document-parser")
    from app.observability.metrics import register_document_metrics
    register_document_metrics(get_registry("mogo-document-parser"))
    # 025 Phase 1（T006）：trace_id 中间件 + 统一异常处理器（422/500）。
    app.add_middleware(TraceIdMiddleware)
    register_error_handlers(app, is_prod=is_prod)
    app.include_router(api_router, prefix="/api/v1")
    # 023 T021：observability health_router（/ready 依赖可达性检查）
    app.include_router(health_router)
    # 025 T021（FR-10）：OpenAPI 暴露统一 ErrorResponse 并对 4xx/5xx $ref（对齐 admin-api）。
    # 必须在 include_router 之后调用（get_openapi 读调用时的 app.routes）。
    _patch_openapi_error_schema(app)
    # 025 T045（FR-27）：旧 /api/* 永久重定向到 /api/v1/*（GET/HEAD 301，其他 308）。
    app.add_middleware(LegacyApiRedirectMiddleware)

    # 026 T012: 性能埋点中间件（延迟分位数 / 并发 / 吞吐 → 进程内 RequestKPIStore）
    from app.common.perf_kpi import PerfMiddleware, RequestKPIStore
    app.add_middleware(PerfMiddleware, store=RequestKPIStore())

    # 023 T035: FastAPI 自动插桩（HTTP server span）
    instrument_fastapi(app)

    # 023 T049: Prometheus /metrics 端点
    app.mount("/metrics", metrics_asgi_app("mogo-document-parser"), name="metrics")
    app.add_middleware(RequestBodyLimitMiddleware)

    @app.exception_handler(StarletteHTTPException)
    async def localized_http_error(request: Request, exc: StarletteHTTPException):
        detail = localize_detail(exc.detail, exc.status_code, request.headers.get("accept-language"))
        if detail == exc.detail:
            return await http_exception_handler(request, exc)
        translated = StarletteHTTPException(status_code=exc.status_code, detail=detail, headers=exc.headers)
        return await http_exception_handler(request, translated)

    @app.on_event("startup")
    def startup() -> None:
        ensure_job_indexes()

    @app.on_event("shutdown")
    def shutdown() -> None:
        close_db()

    return app


# 025 T021（FR-10）：让 /openapi.json 暴露 `ErrorResponse` schema 并引用到通用错误响应。
# 只 patch 生成的 OpenAPI dict，不改任何路由函数签名（对齐 admin-api/app/main.py）。
_ERROR_SCHEMA_STATUSES = ("400", "401", "403", "404", "413", "422", "500")


def _patch_openapi_error_schema(application: FastAPI) -> None:
    """让 /openapi.json 暴露 `ErrorResponse` schema 并引用到通用错误响应。"""

    from fastapi.openapi.utils import get_openapi

    from app.core.errors import ErrorResponse as ErrorResponseModel

    def _openapi() -> dict:
        schema = get_openapi(
            title=application.title,
            version=application.version,
            description=application.description,
            routes=application.routes,
        )
        components = schema.setdefault("components", {}).setdefault("schemas", {})
        error_schema = ErrorResponseModel.model_json_schema(
            ref_template="#/components/schemas/{model}"
        )
        for name, value in (error_schema.pop("$defs", {}) or {}).items():
            components.setdefault(name, value)
        components.setdefault("ErrorResponse", error_schema)

        error_content = {
            "description": "统一错误响应（RFC 9457 + code/trace_id/field/path）",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        }
        for path_item in schema.get("paths", {}).values():
            for method in path_item.values():
                if not isinstance(method, dict):
                    continue
                responses = method.setdefault("responses", {})
                for status in _ERROR_SCHEMA_STATUSES:
                    existing = responses.get(status)
                    if isinstance(existing, dict):
                        existing["content"] = error_content["content"]
                    else:
                        responses[status] = dict(error_content)
                if "default" not in responses:
                    responses["default"] = dict(error_content)
        return schema

    application.openapi = _openapi


app = create_app()
