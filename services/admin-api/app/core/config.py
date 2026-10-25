import logging
import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.internal_service_auth import resolve_backend_service_token

logger = logging.getLogger(__name__)

# 022 FR-11（T015）：access token 生命周期上限 1h（超出即启动告警，不阻断启动）
MAX_ACCESS_TOKEN_TTL_SECONDS = 3600

_FEATURE_FLAG_RESOLVER = None


def _feature_flag_entrypoint():
    """定位并加载共享 feature flag 模块（services/common/feature_flags.py）。

    优先走常规 import（PYTHONPATH 已含 services/），失败则从本文件逐级向上搜索
    `common/feature_flags.py`，覆盖容器 /app/<svc> 与本地两种布局。全程不抛
    异常：加载失败时 `_feature_flag_value` 回退到「环境变量 + 显式 default」。
    """
    try:
        import common.feature_flags as _cff  # type: ignore[import-not-found]

        return _cff.resolve_flag
    except Exception:
        pass
    try:
        import importlib.util
        import sys

        probe = Path(__file__).resolve()
        for ancestor in [probe, *probe.parents]:
            candidate = ancestor / "common" / "feature_flags.py"
            if candidate.is_file():
                spec = importlib.util.spec_from_file_location(
                    "mogo_feature_flags", str(candidate)
                )
                module = importlib.util.module_from_spec(spec)
                sys.modules["mogo_feature_flags"] = module
                spec.loader.exec_module(module)  # type: ignore[union-attr]
                return module.resolve_flag
    except Exception:
        pass
    return None


def _feature_flag_value(name: str, default: bool = False) -> bool:
    global _FEATURE_FLAG_RESOLVER
    if _FEATURE_FLAG_RESOLVER is None:
        _FEATURE_FLAG_RESOLVER = _feature_flag_entrypoint()
    if _FEATURE_FLAG_RESOLVER is not None:
        return bool(_FEATURE_FLAG_RESOLVER(name, default))
    raw = os.environ.get("MOGO_FLAG_" + name.upper().replace("-", "_"))
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


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
    # ── 数据后端开关（MongoDB → PanWeiDB 迁移，见
    # docs/mongo-to-panweidb-migration-plan.md）────────────────────────
    # 留空 = "mongo"（默认，行为与迁移前完全一致）。
    # 取值 "panweidb" 时走 openGauss 内核 / PostgreSQL 兼容线协议。
    # 规范环境变量是 MOGO_DATA_BACKEND（不带服务前缀，便于三服务统一切换）。
    data_backend: str = ""
    # PanWeiDB 连接参数。留空时按 127.0.0.1:5432 回退，方便对接本地 OrbStack。
    panweidb_host: str = ""
    panweidb_port: int = 0
    panweidb_user: str = ""
    panweidb_password: str = ""
    panweidb_db: str = ""
    panweidb_schema: str = ""
    # 024 T054 (FR-027)：统一 feature flag 读取入口。默认值来自
    # deploy/flags/flags.yml，运行时可用 MOGO_FLAG_<NAME_UPPER> 环境变量覆盖。
    def feature_flag(self, name: str, default: bool = False) -> bool:
        """读取特性开关当前值（布尔语义；未登记时返回 default）。"""
        return bool(_feature_flag_value(name, default))
    # 022 FR-17（T044）在 PG 侧的对应物：审计与业务**分离**。
    # MongoDB 用独立 database，PanWeiDB 用独立 schema。留空 = 与业务同 schema
    # （仅用于本地开发；生产应显式配置，否则审计链与业务共享备份/权限边界）。
    panweidb_audit_schema: str = ""
    panweidb_sslmode: str = ""
    panweidb_pool_min_size: int = 1
    panweidb_pool_max_size: int = 10
    panweidb_connect_timeout: int = 5
    jwt_secret: str = ""
    # 022 FR-11（T015）：access token TTL 上限 1h；默认值已收紧到 3600s。
    access_token_ttl_seconds: int = 3600
    tenant_bootstrap_admin_enabled: bool = False
    tenant_bootstrap_admin_username: str = "admin"
    tenant_bootstrap_admin_password: str = ""
    tenant_bootstrap_admin_display_name: str = "系统管理员"
    tenant_bootstrap_admin_role_name: str = "租户管理员"
    tenant_bootstrap_admin_org_name: str = "MOGO 平台"
    bootstrap_tenant_id: str = "default"
    user_portal_base_url: str = "http://localhost:3100"
    invite_token_ttl_hours: int = 72
    model_test_ca_bundle: str = ""
    model_test_insecure_skip_verify: bool = False
    backend_base_url: str = "http://127.0.0.1:8000"
    backend_service_token: str = ""
    # 032-eval-gate: chat-api 模型网关用签名令牌（HMAC，见
    # chat-api/app/dsh_runtime/model_gateway/token.py），不是 backend_service_token
    # 那套 v1|... 服务令牌（spec R-12）。
    dsh_model_gateway_signing_secret: str = ""
    eval_gate_profile_version: str = "eval-gate"
    eval_gate_model_instance_id: str = ""
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

    # ── PanWeiDB（MongoDB → PanWeiDB 迁移）────────────────────────────
    @property
    def effective_data_backend(self) -> str:
        """数据后端：``mongo``（默认）或 ``panweidb``。"""
        raw = (
            self.data_backend
            or os.getenv("MOGO_DATA_BACKEND", "")
            or _read_env_file_value("MOGO_DATA_BACKEND")
            or "mongo"
        )
        return raw.strip().lower()

    def effective_data_backend_for(self, domain: str) -> str:
        """按域取数据后端；未设 ``MOGO_DATA_BACKEND_<DOMAIN>`` 时回退全局。

        域级覆盖用于 R3 的**增量灰度切流**：可先把某个数据域（如 ``audit``）
        切到 PanWeiDB，其余保持 Mongo，再逐步扩大覆盖面。域名的非字母数字字符
        统一规范成 ``_``（例如 ``document-parser`` → ``MOGO_DATA_BACKEND_DOCUMENT_PARSER``）。

        注意：本方法只做**配置解析**。运行时真正按域路由到不同后端需要两个后端
        连接池同时存活（当前架构是「整体切换、单池」），因此逐域路由的接线属于 R3
        工作；这里先把「开关能力」落地，避免后续重复设计。
        """
        key = "MOGO_DATA_BACKEND_" + "".join(
            c if c.isalnum() else "_" for c in domain.upper()
        )
        raw = os.getenv(key, "") or _read_env_file_value(key)
        if raw:
            return raw.strip().lower()
        return self.effective_data_backend

    @property
    def effective_panweidb_host(self) -> str:
        return (
            self.panweidb_host
            or os.getenv("PANWEIDB_HOST", "")
            or _read_env_file_value("PANWEIDB_HOST")
            or "127.0.0.1"
        )

    @property
    def effective_panweidb_port(self) -> int:
        raw = self.panweidb_port or os.getenv("PANWEIDB_PORT", "") or _read_env_file_value("PANWEIDB_PORT")
        try:
            return int(raw) if raw else 5432
        except (TypeError, ValueError):
            return 5432

    @property
    def effective_panweidb_user(self) -> str:
        return (
            self.panweidb_user
            or os.getenv("PANWEIDB_USER", "")
            or _read_env_file_value("PANWEIDB_USER")
        )

    @property
    def effective_panweidb_password(self) -> str:
        return (
            self.panweidb_password
            or os.getenv("PANWEIDB_PASSWORD", "")
            or _read_env_file_value("PANWEIDB_PASSWORD")
        )

    @property
    def effective_panweidb_db(self) -> str:
        return (
            self.panweidb_db
            or os.getenv("PANWEIDB_DB", "")
            or _read_env_file_value("PANWEIDB_DB")
            or self.effective_mongodb_db
        )

    @property
    def effective_panweidb_schema(self) -> str:
        return (
            self.panweidb_schema
            or os.getenv("PANWEIDB_SCHEMA", "")
            or _read_env_file_value("PANWEIDB_SCHEMA")
            or "public"
        )

    @property
    def effective_panweidb_audit_schema(self) -> str:
        """审计 schema；未配置时与业务同 schema（FR-17 的 PG 侧等价物）。"""
        return (
            self.panweidb_audit_schema
            or os.getenv("PANWEIDB_AUDIT_SCHEMA", "")
            or _read_env_file_value("PANWEIDB_AUDIT_SCHEMA")
            or self.effective_panweidb_schema
        )


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
settings.backend_service_token = resolve_backend_service_token(settings.backend_service_token)  # pragma: allowlist secret
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
            settings.jwt_secret = "dev-secret-change-me-in-production"  # pragma: allowlist secret
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

