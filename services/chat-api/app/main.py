from app.infrastructure.observability.config import log_print
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import logging
import os
import sys
import time
import uuid

from app.core.db import close_backend, get_db, init_backend
from app.core.error_handler import register_error_handlers
from app.middleware.cors import build_cors_middleware_kwargs
from app.core.config import get_settings
from app.infrastructure.observability.config import configure_logging
from app.infrastructure.observability.spans import log_span
from app.observability.logging import init_chat_logging
from app.observability.health import router as health_router
from app.infrastructure.request_context import merge_request_context, reset_request_context
from app.infrastructure.runtime_services import action_receipt_store, token_usage_dispatcher
from pymongo.errors import OperationFailure


def _ensure_utf8_stdio() -> None:
    # Some runtime shells default to ASCII and crash when logging Chinese text.
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    for stream in (sys.stdout, sys.stderr):
        try:
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception as exc:
            log_print(f"[main] startup failed: {exc}", flush=True)


_ensure_utf8_stdio()

settings = get_settings()
configure_logging(settings)
init_chat_logging()

# 023 T034: 初始化 OpenTelemetry 追踪（OTLP → Tempo）
from app.common.observability_base import init_tracing, instrument_fastapi, instrument_httpx, init_metrics, get_registry, metrics_asgi_app
init_tracing("mogo-chat-api")
instrument_httpx()

# 023 T048: Prometheus metrics 初始化
chat_metrics = init_metrics("mogo-chat-api")
from app.observability.metrics import circuit_breaker_metrics, register_chat_metrics
register_chat_metrics(get_registry("mogo-chat-api"))
# 023 T088: 熔断器/限流/背压指标
from app.middleware.resilience import ResilienceMiddleware, bind_metrics, middleware_kwargs
bind_metrics(circuit_breaker_metrics(get_registry("mogo-chat-api"), "mogo-chat-api"))

logger = logging.getLogger(__name__)

app = FastAPI(
    title="MOGO Backend",
    description="API for Multi-Agent Platform",
    # Keep in sync with pyproject.toml / CHANGELOG: this is the value
    # published in /openapi.json info.version, i.e. an externally visible
    # contract, not a private cosmetic string.
    version="0.2.5"
)
_receipt_gc_task: asyncio.Task | None = None

origins = settings.allowed_origins_list()

# 022 FR-16（T034）：allow_methods / allow_headers 从 ['*'] 收敛为显式白名单。
# Starlette 对 ['*'] 会把预检请求提出的任意方法/头部原样反射回响应，
# 等价于对跨域预检整体放行 —— 见 app.middleware.cors 的说明。
app.add_middleware(
    CORSMiddleware,
    **build_cors_middleware_kwargs(origins),
)

# 023 T087: 限流 + 背压中间件（租户级速率/并发 + 在途量上限 → 429）
app.add_middleware(ResilienceMiddleware, **middleware_kwargs())
from app.middleware.legacy_api_redirect import LegacyApiRedirectMiddleware
# 025 T045（FR-27）：旧 /api/* 永久重定向到 /api/v1/*（GET/HEAD 用 301，其他 308）。
# 最后 add 即最外层，拦截未匹配的旧路径。
app.add_middleware(LegacyApiRedirectMiddleware)

# 023 T034: FastAPI 自动插桩（HTTP server span）
instrument_fastapi(app)

# 023 T048: Prometheus /metrics 端点
app.mount("/metrics", metrics_asgi_app("mogo-chat-api"), name="metrics")

# 022 FR-18（T042）：生产环境禁止回显异常详情与堆栈。
# 完整异常仍记录到服务端日志（logger.exception），客户端只拿到通用错误码。
# 开发/本地环境保留 str(exc) 便于调试。
_ENV_NORMALIZE = {"production", "prod", "release"}
_IS_PROD = str(getattr(settings, "APP_ENV", "") or "").strip().lower() in _ENV_NORMALIZE

# 022 FR-18（T042）：生产环境强制关闭调试模式 —— 即使有人误配 DEBUG=true，
# 生产环境也不允许回显异常详情（信息泄露面），只降级为告警。
if _IS_PROD and bool(getattr(settings, "DEBUG", False)):
    logger.warning(
        "APP_ENV=%s 时 DEBUG 必须为 false；已忽略 DEBUG=true 的误配置",
        settings.APP_ENV,
    )
    settings.DEBUG = False


# 025 Phase 1（T005）：统一异常处理器接管 422/500，响应体为 RFC 9457 扩展的
# ErrorResponse 结构（code/message/trace_id/field/path + detail 兼容键）。
# 路由内显式 HTTPException 形状不变（T011 状态码语义整改波次处理）。
register_error_handlers(app, is_prod=_IS_PROD)


# 025 T021（FR-10）：把统一 `ErrorResponse` schema 暴露到 OpenAPI，并让所有 4xx/5xx
# 通用错误响应 `$ref` 到它（对齐 admin-api/app/main.py 的实现）。只 patch 生成的
# OpenAPI dict，不改任何路由函数签名 —— 可回滚、对运行时行为零影响。
_ERROR_SCHEMA_STATUSES = ("400", "401", "403", "404", "408", "409", "413", "422", "500")


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


# 实际调用放在文件最末尾（所有 include_router / 路由装饰器之后）：
# get_openapi 读取调用时刻的 app.routes，早调会漏掉业务路径。见文件末尾。

@app.middleware("http")
async def trace_id_middleware(request, call_next):
    # 025 T005：trace_id 解析 + 响应头回写（放在 http 中间件层，早于业务处理，
    # 使异常处理器与日志上下文都能取到同一值）。
    from app.middleware.trace_id import resolve_trace_id

    trace_id = resolve_trace_id(request)
    response = await call_next(request)
    response.headers["X-Trace-ID"] = trace_id
    return response

@app.middleware("http")
async def request_logging_middleware(request, call_next):
    http_request_id = request.headers.get("X-Request-ID") or f"http_{uuid.uuid4().hex[:12]}"
    started_at = time.monotonic()
    previous_context = merge_request_context(
        {
            "http_request_id": http_request_id,
            "method": request.method,
            "path": request.url.path,
        }
    )
    logger.info(
        "http request started",
        extra={
            "event": "http.request_started",
            "http_request_id": http_request_id,
            "method": request.method,
            "path": request.url.path,
            "client_ip": request.client.host if request.client else "",
        },
    )
    try:
        async with log_span("http.request", method=request.method, path=request.url.path):
            response = await call_next(request)
        duration_ms = int((time.monotonic() - started_at) * 1000)
        response.headers["X-Request-ID"] = http_request_id
        logger.info(
            "http request completed",
            extra={
                "event": "http.request_completed",
                "http_request_id": http_request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        return response
    except Exception:
        duration_ms = int((time.monotonic() - started_at) * 1000)
        logger.exception(
            "http request failed",
            extra={
                "event": "http.request_failed",
                "http_request_id": http_request_id,
                "method": request.method,
                "path": request.url.path,
                "duration_ms": duration_ms,
            },
        )
        raise
    finally:
        reset_request_context(previous_context)

from app.api.endpoints import (
    a2a,
    auth,
    context_space,
    dsh_chat,
    dsh_session_versioning,
    debug,
    documents,
    dsh_model_gateway,
    dsh_tool_gateway,
    external_tools,
    harness_profiles,
    im_gateway,
    knowledge_graph,
    knowledge_sources,
    memory,
    models,
    orchestrations,
    projects,
    product,
    quota,
    scheduled_tasks,
    shortcuts,
    sessions,
    site_profiles,
    skills,    skill_package_install,
    skill_lifecycle,
    skill_updates,
    skill_share_direct,
    skill_shares,
    resource_feedback,
    personal_knowledge,
    research,
    tasks,
    business_index,
    token_usage,
    ontology_grants,
    portal,
)
from app.scheduled_tasks import scheduled_task_scheduler
from app.services.dream_cycle import runtime as dream_cycle_runtime
from app.governance.suspensions import suspension_service
from app.browser import ws_endpoint as browser_ws_endpoint

app.include_router(dsh_chat.router, prefix="/api/v1")
app.include_router(dsh_session_versioning.router, prefix="/api/v1")
app.include_router(auth.router, prefix="/api/v1")
app.include_router(debug.router, prefix="/api/v1")
app.include_router(documents.router, prefix="/api/v1")
app.include_router(knowledge_sources.router, prefix="/api/v1")
app.include_router(external_tools.router, prefix="/api/v1")
app.include_router(models.router, prefix="/api/v1")
app.include_router(projects.router, prefix="/api/v1")
app.include_router(product.router, prefix="/api/v1")
app.include_router(sessions.router, prefix="/api/v1")
app.include_router(tasks.router, prefix="/api/v1")
app.include_router(skills.router, prefix="/api/v1")
app.include_router(skill_package_install.router, prefix="/api/v1")
app.include_router(skill_lifecycle.router, prefix="/api/v1")
app.include_router(skill_updates.router, prefix="/api/v1")
app.include_router(skill_share_direct.router, prefix="/api/v1")
app.include_router(skill_shares.router, prefix="/api/v1")
app.include_router(resource_feedback.router, prefix="/api/v1")
app.include_router(personal_knowledge.router, prefix="/api/v1")
app.include_router(site_profiles.router, prefix="/api/v1")
app.include_router(token_usage.router, prefix="/api/v1")
app.include_router(quota.router, prefix="/api/v1")
app.include_router(scheduled_tasks.router, prefix="/api/v1")
app.include_router(shortcuts.router, prefix="/api/v1")
app.include_router(browser_ws_endpoint.router, prefix="/api/v1")
app.include_router(dsh_model_gateway.router)
app.include_router(dsh_tool_gateway.internal_router)
app.include_router(dsh_tool_gateway.public_router, prefix="/api/v1")
# 012 / 013: minimal production wiring for A2A agent card lookup and IM webhook.
app.include_router(a2a.router)
app.include_router(im_gateway.router)
# 017: three-scope memory CRUD (scope/visibility enforced server-side).
app.include_router(memory.router)
# 021: unified mogo:// context address space — the production entry for the
# router + four tenant adapters (without this the whole layer was test-only).
app.include_router(context_space.router)
# 010: research DAG orchestration (competitor deep-dive) — production entry.
app.include_router(research.router, prefix="/api/v1")
# 014: business semantic index — search / index / align production surface.
app.include_router(business_index.router)
# 030: 终端用户侧本体授权自查（admin-web 本体页的 user-web 迁移；只读）。
app.include_router(ontology_grants.router)
# 037: 统一门户 —— 目录 / 详情 / 自助申领（end_user 会话，租户隔离）。
app.include_router(portal.router)
# 039: 可视化编排画布 —— 端用户侧编排草稿保存 / 发布门禁（画布为投影，文档为权威）。
app.include_router(orchestrations.router)
# 015: knowledge graph query surface (FR-2 / FR-10 minimal wiring).
app.include_router(knowledge_graph.router)
# 019: harness elastic-config CRUD (FR-7 / FR-9 — admin-only writes).
app.include_router(harness_profiles.router)

from app.product.extensions import get_product_extension

product_extension = get_product_extension()
for extension_router in product_extension.routers:
    app.include_router(extension_router, prefix="/api/v1")

if settings.ENABLE_DEMO_ENDPOINTS:
    from app.api.endpoints import (
        mock_manufacturing,
        mock_sales_review,
        mock_store_audit,
        mock_store_diagnosis,
    )

    app.include_router(mock_manufacturing.router, prefix="/api/v1")
    app.include_router(mock_sales_review.router, prefix="/api/v1")
    app.include_router(mock_store_audit.router, prefix="/api/v1")
    app.include_router(mock_store_diagnosis.router, prefix="/api/v1")
    # 023 T018：observability health_router（/ready 依赖可达性检查）
    app.include_router(health_router)

async def _ensure_end_user_login_name_index(db) -> None:
    desired_key = {"tenant_id": 1, "login_name": 1}
    async for index in db.end_users.list_indexes():
        if index.get("key") == desired_key and index.get("unique") is True:
            logger.info(
                "reusing existing end_users login_name unique index",
                extra={
                    "event": "db.index.reused",
                    "collection": "end_users",
                    "index_name": index.get("name", ""),
                },
            )
            return
    try:
        await db.end_users.create_index(
            [("tenant_id", 1), ("login_name", 1)],
            unique=True,
            name="user_tenant_login_name_unique",
            partialFilterExpression={"login_name": {"$exists": True, "$type": "string"}},
        )
    except OperationFailure as exc:
        if getattr(exc, "code", None) == 85:
            logger.warning(
                "end_users login_name unique index already exists with different options; reusing it",
                extra={
                    "event": "db.index.reused_conflict",
                    "collection": "end_users",
                    "error": str(exc),
                },
            )
            return
        raise

@app.on_event("startup")
async def startup_event() -> None:
    global _receipt_gc_task
    await init_backend()
    db = get_db()
    # Keep session history list query fast: find by user_id and sort by updated_at desc.
    await db.chat_sessions.create_index([("user_id", 1), ("updated_at", -1)])
    await db.chat_sessions.create_index([("user_id", 1), ("updated_at", -1), ("_id", -1)])
    await db.chat_sessions.create_index([("user_id", 1), ("created_at", -1)])
    await db.chat_sessions.create_index([("tenant_id", 1), ("user_id", 1), ("updated_at", -1)])
    await db.chat_sessions.create_index([("tenant_id", 1), ("user_id", 1), ("updated_at", -1), ("_id", -1)])
    await db.chat_messages.create_index([("tenant_id", 1), ("user_id", 1), ("session_id", 1), ("seq", 1)])
    await db.execution_logs.create_index([("tenant_id", 1), ("session_id", 1), ("message_id", 1)])
    await db.user_skills.create_index([("tenant_id", 1), ("user_id", 1), ("created_at", -1)])
    await db.user_skills.create_index(
        [("tenant_id", 1), ("user_id", 1), ("package_slug", 1)],
        unique=True,
        partialFilterExpression={"source_kind": "zip"},
        name="personal_zip_skill_slug",
    )
    await db.skill_packages.create_index([("tenant_id", 1), ("owner_scope", 1), ("owner_id", 1), ("digest", 1)])
    await db.skill_shares.create_index([("tenant_id", 1), ("token_hash", 1)], unique=True)
    await db.skill_shares.create_index([("tenant_id", 1), ("owner_user_id", 1), ("source_skill_id", 1), ("created_at", -1)])
    await db.skill_share_deliveries.create_index(
        [("tenant_id", 1), ("recipient_user_id", 1), ("status", 1), ("_id", -1)],
        name="skill_share_recipient_inbox",
    )
    await db.skill_share_deliveries.create_index(
        [("tenant_id", 1), ("sender_user_id", 1), ("source_skill_id", 1), ("recipient_user_id", 1), ("status", 1)],
        name="skill_share_sender_recipient",
    )
    await db.skill_releases.create_index([("tenant_id", 1), ("skill_id", 1), ("version", 1)], unique=True)
    await db.skill_distributions.create_index(
        [("tenant_id", 1), ("owner_user_id", 1), ("source_skill_id", 1), ("status", 1)], unique=True,
    )
    await db.skill_distribution_releases.create_index(
        [("tenant_id", 1), ("distribution_id", 1), ("digest", 1)], unique=True,
    )
    await db.skill_distribution_members.create_index(
        [("tenant_id", 1), ("distribution_id", 1), ("recipient_user_id", 1)], unique=True,
    )
    await db.skill_update_notifications.create_index(
        [("tenant_id", 1), ("recipient_user_id", 1), ("status", 1), ("created_at", -1)],
    )
    await db.resource_comments.create_index(
        [("tenant_id", 1), ("resource_type", 1), ("resource_id", 1), ("status", 1), ("created_at", 1)],
    )
    await db.resource_reactions.create_index(
        [("tenant_id", 1), ("resource_type", 1), ("resource_id", 1), ("user_id", 1), ("reaction", 1)], unique=True,
    )
    await db.resource_comment_reactions.create_index(
        [("tenant_id", 1), ("comment_id", 1), ("user_id", 1), ("reaction", 1)], unique=True,
    )
    await db.resource_feedback_notifications.create_index(
        [("tenant_id", 1), ("recipient_user_id", 1), ("status", 1), ("created_at", -1)],
    )
    await db.knowledge_resources.create_index(
        [("tenant_id", 1), ("owner_user_id", 1), ("directory_id", 1), ("deleted_at", 1), ("updated_at", -1)],
        name="personal_knowledge_owner_directory",
    )
    await db.personal_knowledge_directories.create_index(
        [("tenant_id", 1), ("owner_user_id", 1), ("parent_id", 1), ("name", 1)],
        name="personal_knowledge_directory_name",
    )
    await db.resource_grants.create_index(
        [("tenant_id", 1), ("resource_type", 1), ("resource_id", 1), ("recipient_user_id", 1)],
        unique=True, name="resource_grant_recipient",
    )
    await db.resource_grants.create_index(
        [("tenant_id", 1), ("resource_type", 1), ("recipient_user_id", 1), ("status", 1), ("updated_at", -1)],
        name="resource_grant_inbox",
    )
    await db.end_users.create_index([("tenant_id", 1), ("status", 1), ("_id", 1)], name="skill_share_member_page")
    await db.end_users.create_index([("tenant_id", 1), ("status", 1), ("name", 1)], name="skill_share_member_name")
    await db.end_users.create_index([("tenant_id", 1), ("status", 1), ("login_name", 1)], name="skill_share_member_login")
    await db.end_users.create_index([("tenant_id", 1), ("status", 1), ("email", 1)], name="skill_share_member_email")
    await db.end_users.create_index([("tenant_id", 1), ("status", 1), ("mobile", 1)], name="skill_share_member_mobile")
    await db.site_profiles.create_index([("tenant_id", 1), ("owner_user_id", 1), ("updated_at", -1)])
    await db.external_tools.create_index([("tenant_id", 1), ("updated_at", -1)])
    await db.external_tools.create_index([("tenant_id", 1), ("status", 1), ("type", 1)])
    await db.external_tools.create_index([("tenant_id", 1), ("scope", 1), ("owner_user_id", 1), ("updated_at", -1)])
    await db.project_memories.create_index([("tenant_id", 1), ("user_id", 1), ("project_id", 1), ("key", 1)])
    await db.desktop_projects.create_index([("tenant_id", 1), ("user_id", 1), ("workspace_id", 1)], unique=True)
    await db.desktop_projects.create_index([("tenant_id", 1), ("user_id", 1), ("updated_at", -1)])
    await db.token_usage_logs.create_index([("tenant_id", 1), ("user_id", 1), ("created_at", -1)])
    await db.token_usage_logs.create_index([("session_id", 1), ("created_at", -1)])
    await db.token_usage_logs.create_index([("trace_id", 1), ("created_at", -1)])
    await db.token_usage_logs.create_index([("user_request_id", 1), ("created_at", -1)])
    await db.token_usage_logs.create_index("request_id", unique=True)
    await _ensure_end_user_login_name_index(db)
    await db.end_user_sessions.create_index([("token_id", 1)], unique=True)
    await db.end_user_sessions.create_index([("tenant_id", 1), ("user_id", 1), ("status", 1), ("expires_at", -1)])
    await db.end_user_sessions.create_index([("expires_at", 1)], expireAfterSeconds=0)
    await db.end_user_login_challenges.create_index([("challenge_token", 1)], unique=True)
    await db.end_user_login_challenges.create_index([("expires_at", 1)], expireAfterSeconds=0)
    from app.dsh_runtime.application import dsh_runtime_application
    await dsh_runtime_application.start()
    await action_receipt_store.ensure_indexes()
    await suspension_service.store.ensure_indexes()
    await action_receipt_store.recover_stale_running()
    await action_receipt_store.reconcile_abandoned()
    await token_usage_dispatcher.start()
    await scheduled_task_scheduler.start()
    await dream_cycle_runtime.ensure_indexes(db)
    await dream_cycle_runtime.dream_cycle_scanner.start()
    for callback in product_extension.startup:
        result = callback()
        if asyncio.iscoroutine(result):
            await result
    async def _receipt_gc_loop() -> None:
        while True:
            try:
                await action_receipt_store.recover_stale_running()
                await action_receipt_store.reconcile_abandoned()
            except Exception as exc:
                log_print(f"[main] shutdown failed: {exc}", flush=True)
            await asyncio.sleep(60)
    _receipt_gc_task = asyncio.create_task(_receipt_gc_loop())

    # 017 FR-8: periodic memory decay sweep (archival / deletion by policy).
    # Best-effort: a DB error must never take the app down with it.
    from app.memory.lifecycle import clean_decayed_memories, MemoryLifecycle

    async def _memory_decay_loop() -> None:
        while True:
            try:
                db_now = get_db()
                if db_now is not None:
                    outcome = clean_decayed_memories(db=db_now, lifecycle=MemoryLifecycle())
                    pending = outcome.get("_pending")
                    if pending is not None:
                        outcome = await pending
                    outcome.pop("_pending", None)
                    if outcome.get("removed") or outcome.get("archived"):
                        logger.info(
                            "memory decay sweep",
                            extra={"event": "memory.decay_sweep", **outcome},
                        )
            except Exception:
                logger.exception("memory decay sweep failed")
            await asyncio.sleep(3600)  # hourly

    _memory_decay_task = asyncio.create_task(_memory_decay_loop())
    # MongoDB → PanWeiDB 迁移：openGauss 无原生 TTL 索引，用后台循环定期清理过期
    # 文档（对兼容层登记的 expireAfterSeconds 声明）。mongo 模式下 start() 为 no-op。
    from app.core.ttl_purge import ttl_purge_loop

    await ttl_purge_loop.start()
    settings = get_settings()
    logger.info(
        "application startup complete",
        extra={
            "event": "app.startup",
            "debug": settings.DEBUG,
            "use_azure": settings.USE_AZURE,
            "azure_deployment": settings.AZURE_DEPLOYMENT_NAME,
            "pipeline_mode": settings.PIPELINE_MODE,
        },
    )


@app.on_event("shutdown")
async def shutdown_event() -> None:
    global _receipt_gc_task, _memory_decay_task
    for callback in reversed(product_extension.shutdown):
        result = callback()
        if asyncio.iscoroutine(result):
            await result
    if _receipt_gc_task is not None:
        _receipt_gc_task.cancel()
        _receipt_gc_task = None
    if _memory_decay_task is not None:
        _memory_decay_task.cancel()
        _memory_decay_task = None
    from app.core.ttl_purge import ttl_purge_loop

    await ttl_purge_loop.stop()
    await dream_cycle_runtime.dream_cycle_scanner.stop()
    await scheduled_task_scheduler.stop()
    await token_usage_dispatcher.stop()
    from app.dsh_runtime.application import dsh_runtime_application
    await dsh_runtime_application.stop()
    await close_backend()

@app.get("/health")
async def health_check():
    """Health check endpoint to verify backend status.

    In multi-replica deployments the payload lists per-replica DSH Runtime Host
    health (``dsh_hosts``), so an operator can see exactly which replica is down
    rather than a single aggregate boolean.
    """
    from app.dsh_runtime.application import dsh_runtime_application
    dsh_healthy = await dsh_runtime_application.probe_host()
    hosts = [
        {
            "url": detail["url"],
            "healthy": detail["healthy"],
            "state": (detail["detail"] or {}).get("state"),
            "instance_id": (detail["detail"] or {}).get("instanceId"),
            "runtimes": len((detail["detail"] or {}).get("runtimes") or []),
            "version": (detail["detail"] or {}).get("version"),
            "error": detail["error"],
        }
        for detail in dsh_runtime_application.host_health_details
    ]
    # 数据后端快照：MOGO_DATA_BACKEND=mongo（默认）时不引入额外连接开销，
    # =panweidb 时附带一次真实连通性探测。
    try:
        from app.core import pg

        backend_info = await pg.health_payload()
    except Exception:  # pragma: no cover - 健康检查自身绝不应抛错
        backend_info = {}
    return {
        "status": "ok",
        # Read the version off the FastAPI app instead of a second literal: the
        # literal here sat at 0.1.0 for the entire 0.2.0 line (introduced in
        # 82e4d20, never touched again) because nothing pointed at a single
        # source of truth. app.version is also what the CI version-consistency
        # gate pins, so this payload can no longer drift.
        "version": app.version,
        "service": "MOGO Backend",
        "agent_kernel": "dsh",
        "dsh_host": "healthy" if dsh_healthy else "degraded",
        "dsh_hosts": hosts,
        **backend_info,
    }


@app.get("/ready")
async def readiness_check():
    """Readiness requires at least one DSH Runtime Host replica to be reachable.

    With multiple replicas this no longer fails when ``base_urls[0]`` alone is
    down but the load balancer can still route around it to a healthy replica.
    """
    from app.dsh_runtime.application import dsh_runtime_application
    if not await dsh_runtime_application.probe_host():
        raise HTTPException(status_code=503, detail="DSH Runtime Host is unavailable")
    return {
        "status": "ready",
        "service": "MOGO Backend",
        "agent_kernel": "dsh",
        "dsh_host": "healthy",
    }

@app.get("/")
async def root():
    return {"message": "Welcome to MOGO Agent Platform API"}


# 025 T021：OpenAPI 暴露统一 ErrorResponse —— 放在文件最末尾，确保所有
# include_router / 路由装饰器已注册（get_openapi 读调用时刻的 app.routes）。
_patch_openapi_error_schema(app)
