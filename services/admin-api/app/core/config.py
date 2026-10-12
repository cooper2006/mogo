import logging
import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.internal_service_auth import resolve_backend_service_token

logger = logging.getLogger(__name__)

# 022 FR-11（T015）：access token 生命周期上限 1h（超出即启动告警，不阻断启动）
MAX_ACCESS_TOKEN_TTL_SECONDS = 3600


class Settings(BaseSettings):
    app_env: str = "development"
    # 022 FR-18（T042）：调试模式开关。生产环境强制为 false ——
    # 生产环境不启用 FastAPI debug 行为（自动 reload、详细 traceback）。
    debug: bool = False
    cors_origins: list[str] = ["http://localhost:3100"]
    mongodb_uri: str = ""
    mongodb_db: str = ""
    # 022 FR-17（T044）：审计日志与业务库分离。
    # 留空时复用 mongodb_db（向后兼容的默认）；生产环境应指向独立库，
    # 以获得独立的备份、权限与生命周期 —— 避免业务运维误删或改写审计链。
    audit_db: str = ""
    # 022 FR-17（T044）：审计日志保留期，下限 180 天（合规取证基线）。
    # 低于 180 会被提升到 180 并打告警；负数表示禁用 TTL 自动清理。
    audit_retention_days: int = 180
    jwt_secret: str = ""
    # 022 FR-11（T015）：access token TTL 上限 1h；默认值已收紧到 3600s。
    access_token_ttl_seconds: int = 3600
    tenant_bootstrap_admin_enabled: bool = False
    tenant_bootstrap_admin_username: str = "admin"
    tenant_bootstrap_admin_password: str = ""
    tenant_bootstrap_admin_display_name: str = "系统管理员"
    tenant_bootstrap_admin_role_name: str = "租户管理员"
    tenant_bootstrap_admin_org_name: str = "MOVO 平台"
    platform_admin_username: str = "platform"
    platform_admin_password: str = ""
    platform_admin_display_name: str = "平台管理员"
    bootstrap_tenant_id: str = "default"
    user_portal_base_url: str = "http://localhost:3100"
    invite_token_ttl_hours: int = 72
    model_test_ca_bundle: str = ""
    model_test_insecure_skip_verify: bool = False
    backend_base_url: str = "http://127.0.0.1:8000"
    backend_service_token: str = ""
    public_base_url: str = ""
    redis_url: str = "redis://127.0.0.1:6379/0"
    weaviate_endpoint: str = "http://127.0.0.1:8080"
    knowledge_storage_type: str = "local"
    knowledge_local_storage_dir: str = "data/knowledge-documents"
    knowledge_max_upload_mb: int = 200
    knowledge_allowed_extensions: str = "pdf,doc,docx,ppt,pptx,xls,xlsx,txt,md,png,jpg,jpeg,webp"
    knowledge_oss_endpoint: str = "https://oss-cn-beijing.aliyuncs.com"
    knowledge_oss_bucket: str = "askagentic"
    knowledge_oss_access_key_id: str = ""
    knowledge_oss_access_key_secret: str = ""
    knowledge_oss_prefix: str = "knowledge-documents"
    document_processing_base_url: str = "http://127.0.0.1:8200"
    document_processing_service_token: str = ""
    document_processing_callback_token: str = ""
    admin_api_public_base_url: str = "http://127.0.0.1:8101"
    # 022 US3 (T027)：默认必须是绝对路径。相对路径会解析到 WORKDIR
    # (/app)，在 read_only: true 的容器里 mkdir 直接失败。
    admin_static_dir: str = "/data/admin-static"
    avatar_max_upload_mb: int = 2
    knowledge_min_chunk_size: int = 800
    knowledge_chunk_size: int = 1500
    knowledge_chunk_overlap: int = 120

    model_config = SettingsConfigDict(
        env_prefix="ASKAI_ADMIN_",
        env_file=".env",
        extra="ignore",
    )

    @property
    def effective_mongodb_uri(self) -> str:
        return self.mongodb_uri or os.getenv("MONGODB_URI", "") or _read_env_file_value("MONGODB_URI")

    @property
    def effective_mongodb_db(self) -> str:
        return self.mongodb_db or os.getenv("MONGODB_DB", "") or _read_env_file_value("MONGODB_DB") or "mogo_dev"

    @property
    def effective_audit_db(self) -> str:
        """022 FR-17（T044）：审计库名；未配置时回退到业务库。"""
        return self.audit_db or os.getenv("MONGODB_AUDIT_DB", "") or _read_env_file_value("MONGODB_AUDIT_DB")


def _read_env_file_value(key: str) -> str:
    candidate_paths = [
        Path(".env"),
        Path("../chat-api/.env"),
        Path("../../services/chat-api/.env"),
        Path("../../backend/.env"),
        Path("../backend/.env"),
        Path("backend/.env"),
    ]
    for candidate_path in candidate_paths:
        if not candidate_path.exists():
            continue
        try:
            for raw_line in candidate_path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                current_key, current_value = line.split("=", 1)
                if current_key.strip() == key:
                    return current_value.strip().strip('"').strip("'")
        except OSError:
            continue
    return ""


settings = Settings()
settings.backend_service_token = resolve_backend_service_token(settings.backend_service_token)
if not settings.mongodb_uri:
    settings.mongodb_uri = settings.effective_mongodb_uri
if not settings.mongodb_db:
    settings.mongodb_db = settings.effective_mongodb_db
if not settings.knowledge_oss_access_key_id:
    settings.knowledge_oss_access_key_id = os.getenv("OSS_ACCESS_KEY_ID", "") or _read_env_file_value("OSS_ACCESS_KEY_ID")
if not settings.knowledge_oss_access_key_secret:
    settings.knowledge_oss_access_key_secret = os.getenv("OSS_ACCESS_KEY_SECRET", "") or _read_env_file_value("OSS_ACCESS_KEY_SECRET")

# QF-433~441: validate JWT secret at startup — reject empty or short secrets in production.
import secrets as _secrets_mod

if not settings.jwt_secret or len(settings.jwt_secret) < 32:
    if settings.app_env == "production":
        # Auto-generate a secure secret if none is configured in production.
        logger.warning("JWT secret is missing or too short; generating a secure one")
        settings.jwt_secret = _secrets_mod.token_urlsafe(64)
        logger.warning("Use a persistent JWT_SECRET in production to avoid invalidating sessions on restart")
    elif settings.app_env in ("local", "development"):
        # Single-developer convenience only. A predictable secret is acceptable on
        # a developer's own machine but MUST NOT be used in shared/staging or
        # production, where it would allow forging admin tokens.
        if not settings.jwt_secret:
            settings.jwt_secret = "dev-secret-change-me-in-production"
        logger.warning(
            "Using DEV JWT secret (app_env=%s). DO NOT use this in shared/staging/production.",
            settings.app_env,
        )
    else:
        # staging / test / production (non-dev) without a configured secret is a
        # misconfiguration: refuse to start so we never sign tokens with a known key.
        raise RuntimeError(
            "JWT_SECRET is missing or shorter than 32 chars and app_env is "
            f"'{settings.app_env}'. Set ASKAI_ADMIN_JWT_SECRET before starting. "
            "Refusing to start with a predictable dev secret in this environment."
        )
if settings.access_token_ttl_seconds > MAX_ACCESS_TOKEN_TTL_SECONDS:
    logger.warning(
        "Access token TTL %ss exceeds the %ss security ceiling (022 FR-11); "
        "tokens will outlive the 1h session guarantee",
        settings.access_token_ttl_seconds,
        MAX_ACCESS_TOKEN_TTL_SECONDS,
    )

