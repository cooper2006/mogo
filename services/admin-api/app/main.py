from fastapi import FastAPI, Body, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import logging
import os
from typing import Any

from app.api.router import api_router
from app.core.config import settings
from app.core.error_handler import register_error_handlers
from app.middleware.cors import build_cors_middleware_kwargs
from app.middleware.trace_id import TraceIdMiddleware
from app.core.db import close_backend, init_backend
from app.core.product_edition import migrate_bootstrapped_community_organization
from app.repositories.model_repository import ensure_indexes as ensure_model_indexes
from app.api.routes.skills import ensure_indexes as ensure_skill_indexes
from app.api.routes.skill_lifecycle import ensure_indexes as ensure_skill_lifecycle_indexes
from app.api.routes.portal_admin import ensure_indexes as ensure_portal_indexes
from app.api.routes.tools import ensure_indexes as ensure_tool_indexes
from app.api.routes.external_search import ensure_indexes as ensure_external_search_indexes
from app.api.routes.knowledge_documents import ensure_indexes as ensure_knowledge_document_indexes
from app.api.routes.knowledge_directories import ensure_indexes as ensure_knowledge_directory_indexes
from app.api.routes.knowledge_settings import ensure_indexes as ensure_knowledge_settings_indexes
from app.api.routes.page_collection import ensure_indexes as ensure_page_collection_indexes
from app.services.eval_gate import ensure_indexes as ensure_eval_gate_indexes
from app.services.admin_bootstrap import bootstrap_admin_user
from app.services.directory_bootstrap import bootstrap_directory
from app.services.platform_bootstrap import bootstrap_platform_admin
from app.services.tenant_registry import ensure_indexes as ensure_tenant_indexes
from app.services.tenant_registry import backfill_tenants_from_accounts
from app.services.tenant_purge import cleanup_expired_tombstones
from app.services.organization_tools import repair_role_referenced_personal_tools
from app.system_audit import SystemAuditMiddleware, SystemAuditRepository
from app.product.extensions import get_admin_product_extension
from app.services.skill_market.quality_metrics import SkillQualityScanner
from app.services.skill_market.canary import CanaryRollbackScanner
from app.api.routes.trust_ratings import ensure_trust_indexes
from app.services.trust_rating.downgrade_scanner import TrustRatingDowngradeScanner
from app.observability.logging import init_admin_logging, get_admin_logger
from app.observability.health import router as health_router


# 016 periodic effect-score assessment (closed-loop write to skill_adoption).
_QUALITY_SCANNER = SkillQualityScanner()
# 016 FR-5 residual: auto-rollback scheduled scan for active canary rollouts.
_CANARY_ROLLBACK_SCANNER = CanaryRollbackScanner()
# 036 FR-10/FR-11: periodic trust-rating downgrade scan (032/016 quality signal).
_TRUST_DOWNGRADE_SCANNER = TrustRatingDowngradeScanner()


logger = get_admin_logger(__name__)


def create_app() -> FastAPI:
    # 023 T014: 初始化结构化日志（structlog JSON）
    init_admin_logging()

    # QF-447/448: Disable docs endpoints in production
    # 022 FR-18（T042）：生产环境判定覆盖 prod/release 别名。
    is_prod = str(settings.app_env).strip().lower() in {"production", "prod", "release"}

    # 生产环境强制关闭调试模式：即使误配 debug=true 也降级为告警，
    # 避免启用自动 reload / 详细 traceback 造成信息泄露。
    if is_prod and bool(settings.debug):
        logger.warning("app_env=%s 时 debug 必须为 false；已忽略 debug=true 的误配置", settings.app_env)
        settings.debug = False
    app = FastAPI(
        title="MOGO Admin API",
        # Keep in sync with pyproject.toml / CHANGELOG: this is the value
        # published in /openapi.json info.version, i.e. an externally visible
        # contract, not a private cosmetic string.
        version="0.2.5",
        description="Control plane API for MOGO admin backend",
        docs_url=None if is_prod else "/docs",
        redoc_url=None if is_prod else "/redoc",
        openapi_url=None if is_prod else "/openapi.json",
    )

    # 022 FR-16（T033）：allow_methods / allow_headers 从 ['*'] 收敛为显式白名单。
    # Starlette 对 ['*'] 会把预检请求提出的任意方法/头部原样反射回响应，
    # 等价于对跨域预检整体放行 —— 见 app.middleware.cors 的说明。
    app.add_middleware(
        CORSMiddleware,
        **build_cors_middleware_kwargs(settings.cors_origins),
    )
    app.add_middleware(SystemAuditMiddleware)
    # 025 Phase 1（T004）：trace_id 注入中间件——最后 add 即最外层，
    # 保证任何异常处理器 / 业务代码都能从 request.state.trace_id 取到值。
    app.add_middleware(TraceIdMiddleware)

    @app.get("/health", tags=["system"])
    async def health() -> dict[str, Any]:
        """存活 + 数据后端快照。

        ``backend`` 反映 ``MOGO_DATA_BACKEND``；``reachable`` 仅在 PanWeiDB 模式下
        做一次真实探测（MongoDB 模式保持原样的轻量返回，不引入额外连接开销）。
        """
        payload: dict[str, Any] = {"status": "ok", "service": "mogo-admin-api"}
        try:
            from app.core import pg

            payload.update(await pg.health_payload())
        except Exception:  # pragma: no cover - 健康检查自身绝不应抛错
            logger.warning("采集数据后端健康信息失败", exc_info=True)
        return payload

    # 023 T016: /ready 就绪检查端点（依赖不可达返回 503）
    app.include_router(health_router)

    @app.post("/admin/log-level", tags=["system"])
    async def set_log_level(body: dict = Body(...)) -> dict[str, Any]:
        """023 T017 / FR-2：运行时切换日志级别。

        仅允许 DEBUG/INFO/WARNING/ERROR/CRITICAL；
        非法值返回 400，不修改当前级别。
        """
        level = str(body.get("level", "")).upper()
        valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if level not in valid:
            raise HTTPException(
                status_code=400,
                detail=f"invalid log level '{level}'; must be one of {sorted(valid)}",
            )
        import logging as _logging
        _logging.getLogger().setLevel(level)
        return {"level": level, "service": "mogo-admin-api"}

    @app.on_event("startup")
    async def on_startup() -> None:
        # 001 运维加固：启动即打印构建标识，用于核对「运行中代码 == git HEAD」。
        # 背景：98bfb22 修好的 redaction.py 有 85 分钟处于「容器文件已更新、进程仍
        # 加载旧模块」的状态（镜像是提交前 build 的），日志无任何版本线索，导致
        # 误判为「代码没修」。GIT_SHA 由 Dockerfile 的 ARG 注入；本地/未注入时
        # 为 unknown，不影响启动。
        logger.info(
            "admin-api build git_sha=%s image=%s",
            os.environ.get("GIT_SHA", "unknown"),
            os.environ.get("IMAGE_TAG", "unknown"),
        )
        await init_backend()
        await bootstrap_admin_user()
        if get_admin_product_extension().edition == "community":
            await migrate_bootstrapped_community_organization()
        await bootstrap_directory()
        await SystemAuditRepository().ensure_indexes()
        await ensure_model_indexes()
        await ensure_skill_indexes()
        await ensure_skill_lifecycle_indexes()
        await ensure_eval_gate_indexes()
        await ensure_trust_indexes()
        await ensure_tool_indexes()
        await repair_role_referenced_personal_tools()
        await ensure_external_search_indexes()
        await ensure_page_collection_indexes()
        await ensure_knowledge_settings_indexes()
        await ensure_knowledge_document_indexes()
        await ensure_knowledge_directory_indexes()
        await ensure_tenant_indexes()
        await ensure_portal_indexes()
        await backfill_tenants_from_accounts()
        await bootstrap_platform_admin()
        await cleanup_expired_tombstones()  # T052: reap tombstones older than 1 month
        for callback in get_admin_product_extension().startup:
            result = callback()
            if hasattr(result, "__await__"):
                await result
        # 016 FR-3/FR-6: periodically roll up skill effect metrics and down-rank
        # sustained-low-quality skills. Best-effort: a DB/loop error must never
        # break app startup.
        try:
            await _QUALITY_SCANNER.start()
        except Exception:  # pragma: no cover - defensive
            logger.exception("failed to start skill quality scanner")
        # 016 FR-5 residual: periodic auto-rollback scan for active canary
        # rollouts. Best-effort: a DB/loop error must never break app startup.
        try:
            await _CANARY_ROLLBACK_SCANNER.start()
        except Exception:  # pragma: no cover - defensive
            logger.exception("failed to start canary rollback scanner")
        # 036 FR-10/FR-11: periodic trust-rating downgrade scan. Best-effort, same
        # discipline as the 016 scanners above.
        try:
            await _TRUST_DOWNGRADE_SCANNER.start()
        except Exception:  # pragma: no cover - defensive
            logger.exception("failed to start trust downgrade scanner")
        # MongoDB → PanWeiDB 迁移：openGauss 无原生 TTL 索引，用后台循环定期清理
        # 过期文档（对兼容层登记的 expireAfterSeconds 声明）。Best-effort：绝不应
        # 阻断启动；mongo 模式下 start() 为 no-op。
        try:
            from app.core.ttl_purge import ttl_purge_loop

            await ttl_purge_loop.start()
        except Exception:  # pragma: no cover - defensive
            logger.exception("failed to start ttl purge loop")


    @app.on_event("shutdown")
    async def on_shutdown() -> None:
        try:
            await _QUALITY_SCANNER.stop()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("quality scanner stop failed: %s", exc)
        try:
            await _CANARY_ROLLBACK_SCANNER.stop()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("canary rollback scanner stop failed: %s", exc)
        try:
            await _TRUST_DOWNGRADE_SCANNER.stop()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("trust downgrade scanner stop failed: %s", exc)
        try:
            from app.core.ttl_purge import ttl_purge_loop

            await ttl_purge_loop.stop()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("ttl_purge_loop stop failed: %s", exc)
        await close_backend()

    # QF-447/449: Global exception handler - no stack traces in production
    # 025 Phase 1（T003）：统一异常处理器接管 422（RequestValidationError）与 500
    # （未处理 Exception），响应体为 RFC 9457 扩展的 ErrorResponse 结构
    # （code/message/trace_id/field/path，并保留 detail 兼容键）。路由内显式
    # HTTPException 的形状不变——那属于 T011 状态码语义整改的范围。
    register_error_handlers(app, is_prod=is_prod)

    app.include_router(api_router, prefix="/api")
    for extension_router in get_admin_product_extension().routers:
        app.include_router(extension_router, prefix="/api")
    static_dir = Path(settings.admin_static_dir).expanduser().resolve()
    # 022 US3 (T027)：read_only 容器 + 未配置静态卷时 mkdir 会失败。静态文件
    # 挂载属于可选能力，不能因为它阻断整个 API 启动 —— 降级为告警并跳过挂载。
    try:
        static_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning(
            "admin_static_dir %s is not writable (%s); /static mount skipped. "
            "Mount a volume at %s or set ASKAI_ADMIN_ADMIN_STATIC_DIR to a "
            "writable path.",
            static_dir,
            exc,
            static_dir,
        )
        return app
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    return app


app = create_app()
