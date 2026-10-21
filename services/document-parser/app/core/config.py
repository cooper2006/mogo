from __future__ import annotations

import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


# 品牌归一（movo→mogo）：规范前缀为 MOGO_DOC_PROCESSING_。
# MOVO_ 前缀已随品牌迁移移除，不再被接受。
# 过渡期语义：同名后缀字段按 MOGO_ > ASKAI_ 的优先级取值；
# ASKAI_（更早期一代）仍被接受，另行处理。
ENV_PREFIX = "MOGO_DOC_PROCESSING_"
# 更早一代（askai 时期）的前缀，保留为最后一级回退（原有逻辑）。
ANCIENT_ENV_PREFIX = "ASKAI_DOC_PROCESSING_"
# 旧前缀按优先级排列；运行时只接受这些前缀下的键作为 MOGO_ 的回退。
LEGACY_ENV_PREFIXES = (ANCIENT_ENV_PREFIX,)


class Settings(BaseSettings):
    app_env: str = "development"
    service_token: str = ""
    callback_token: str = ""
    # 022 US3 (T027)：必须是绝对路径。旧默认是相对路径
    # (../admin-api/data/knowledge-documents)，在容器里既不存在也不可写；
    # compose 已把 knowledge-storage 卷挂到 /data/knowledge-documents。
    local_storage_dir: str = "/data/knowledge-documents"
    artifacts_prefix: str = "artifacts"
    oss_endpoint: str = "https://oss-cn-beijing.aliyuncs.com"
    oss_bucket: str = "askagentic"
    oss_access_key_id: str = ""
    oss_access_key_secret: str = ""
    libreoffice_bin: str = ""
    conversion_timeout_seconds: int = 180
    max_concurrent_jobs: int = 2
    redis_url: str = "redis://127.0.0.1:6379/0"
    celery_queue: str = "document_processing"
    mongodb_uri: str = ""
    mongodb_db: str = ""
    # ── 数据后端开关（MongoDB → PanWeiDB 迁移，见
    # docs/mongo-to-panweidb-migration-plan.md）────────────────────────
    # 留空 = "mongo"（默认，行为与迁移前完全一致）；"panweidb" 走 openGauss 内核
    # / PostgreSQL 兼容线协议。规范环境变量 MOGO_DATA_BACKEND（不带服务前缀）。
    data_backend: str = ""
    panweidb_host: str = ""
    panweidb_port: int = 0
    panweidb_user: str = ""
    panweidb_password: str = ""
    panweidb_db: str = ""
    panweidb_schema: str = ""
    panweidb_sslmode: str = ""
    panweidb_pool_min_size: int = 1
    panweidb_pool_max_size: int = 10
    panweidb_connect_timeout: int = 5
    jobs_collection: str = "document_jobs"
    azure_embedding_endpoint: str = ""
    azure_embedding_deployment_name: str = "text_embedding"
    azure_embedding_api_version: str = "2025-04-01-preview"
    azure_embedding_api_key: str = ""
    weaviate_endpoint: str = "http://127.0.0.1:8080"
    weaviate_api_key: str = ""
    weaviate_collection_name: str = "AskAIKnowledgeChunks"
    weaviate_distance_metric: str = "cosine"
    dashscope_api_key: str = ""
    admin_jwt_secret: str = ""

    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX,
        env_file=".env",
        extra="ignore",
    )

    @property
    def resolved_local_storage_dir(self) -> str:
        return str(Path(self.local_storage_dir).expanduser().resolve())

    @property
    def effective_mongodb_uri(self) -> str:
        return self.mongodb_uri or os.getenv("MONGODB_URI", "") or _read_env_file_value("MONGODB_URI")

    @property
    def effective_mongodb_db(self) -> str:
        return self.mongodb_db or os.getenv("MONGODB_DB", "") or _read_env_file_value("MONGODB_DB") or "mogo_dev"

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

        域级覆盖用于 R3 增量灰度切流（先把某域切到 PanWeiDB，其余保持 Mongo）。
        运行时逐域路由需双池，属 R3；这里先落地开关能力。
        """
        key = "MOGO_DATA_BACKEND_" + "".join(
            c if c.isalnum() else "_" for c in domain.upper()
        )
        raw = os.getenv(key, "")
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
        return self.panweidb_user or os.getenv("PANWEIDB_USER", "") or _read_env_file_value("PANWEIDB_USER")

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


def _read_env_file_value(key: str) -> str:
    candidate_paths = [
        Path(".env"),
        Path("../admin-api/.env"),
        Path("../../services/admin-api/.env"),
        Path("../chat-api/.env"),
        Path("../../services/chat-api/.env"),
        Path("../admin/api/.env"),
        Path("../../admin/api/.env"),
        Path("../backend/.env"),
        Path("../../backend/.env"),
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


def _apply_legacy_env_prefix(current_settings: Settings) -> None:
    # 过渡期旧前缀回退（.env 文件路径兜底）：MOGO_ 优先（env_prefix + new_key
    # 检查），未设置时回退 ASKAI_（更早期前缀，原有逻辑保留为最后一级）。
    # MOVO_ 前缀已随品牌迁移移除。
    for field_name, field_info in Settings.model_fields.items():
        env_name = f"{field_name}".upper()
        new_key = f"{ENV_PREFIX}{env_name}"
        if os.getenv(new_key, "") or _read_env_file_value(new_key):
            continue
        raw_value = ""
        for legacy_prefix in LEGACY_ENV_PREFIXES:
            legacy_key = f"{legacy_prefix}{env_name}"
            raw_value = os.getenv(legacy_key, "") or _read_env_file_value(legacy_key)
            if raw_value != "":
                break
        if raw_value == "":
            continue
        annotation = field_info.annotation
        if annotation is int:
            try:
                setattr(current_settings, field_name, int(raw_value))
            except ValueError:
                continue
        else:
            setattr(current_settings, field_name, raw_value)


def _promote_legacy_env_vars() -> None:
    """构造 Settings() 前把 os.environ 里的旧前缀变量提升到 MOGO_ 前缀。

    pydantic-settings 的 env_prefix 只认一个前缀（现为 MOGO_），所以 compose /
    entrypoint / CI 注入的 ASKAI_（更早期一代）前缀变量需要先映射成 MOGO_ 键。
    MOVO_ 前缀已随品牌迁移移除，不再提升。
    语义：幂等、不覆盖——MOGO_ 键已有非空值时保持不动；旧前缀按
    LEGACY_ENV_PREFIXES 顺序取第一个非空值。`.env` 文件中的旧前缀键由
    _apply_legacy_env_prefix() 兜底（env_file 读取同样只认单一前缀）。
    """
    for legacy_prefix in LEGACY_ENV_PREFIXES:
        for name, value in list(os.environ.items()):
            if not name.startswith(legacy_prefix) or not value:
                continue
            new_key = f"{ENV_PREFIX}{name[len(legacy_prefix):]}"
            # 不覆盖：已有 MOGO_ 值（或已被更高优先级旧前缀填充）时跳过。
            if os.environ.get(new_key):
                continue
            os.environ[new_key] = value


# 先提升旧前缀环境变量（ASKAI_ → MOGO_；MOVO_ 已随品牌迁移移除），再构造 Settings，
# 使 pydantic-settings 的单一 env_prefix=MOGO_ 能读到过渡期旧值。
_promote_legacy_env_vars()
settings = Settings()
_apply_legacy_env_prefix(settings)
if not settings.mongodb_uri:
    settings.mongodb_uri = settings.effective_mongodb_uri
if not settings.mongodb_db:
    settings.mongodb_db = settings.effective_mongodb_db
if not settings.oss_access_key_id:
    settings.oss_access_key_id = os.getenv("OSS_ACCESS_KEY_ID", "") or _read_env_file_value("OSS_ACCESS_KEY_ID")
if not settings.oss_access_key_secret:
    settings.oss_access_key_secret = os.getenv("OSS_ACCESS_KEY_SECRET", "") or _read_env_file_value("OSS_ACCESS_KEY_SECRET")
if not settings.oss_endpoint:
    settings.oss_endpoint = os.getenv("OSS_ENDPOINT", "") or _read_env_file_value("OSS_ENDPOINT") or "https://oss-cn-beijing.aliyuncs.com"
if not settings.oss_bucket:
    settings.oss_bucket = (
        os.getenv("OSS_BUCKET_NAME", "")
        or os.getenv("OSS_BUCKET", "")
        or _read_env_file_value("OSS_BUCKET_NAME")
        or _read_env_file_value("OSS_BUCKET")
        or "askagentic"
    )
if not settings.azure_embedding_api_key:
    settings.azure_embedding_api_key = (
        os.getenv("AZURE_EMBEDDING_API_KEY", "")
        or os.getenv("AZURE_OPENAI_API_KEY", "")
        or os.getenv("OPENAI_API_KEY", "")
        or _read_env_file_value("AZURE_EMBEDDING_API_KEY")
        or _read_env_file_value("AZURE_OPENAI_API_KEY")
        or _read_env_file_value("OPENAI_API_KEY")
    )
if not settings.dashscope_api_key:
    settings.dashscope_api_key = os.getenv("DASHSCOPE_API_KEY", "") or _read_env_file_value("DASHSCOPE_API_KEY")
if not settings.admin_jwt_secret:
    settings.admin_jwt_secret = os.getenv("JWT_SECRET", "") or _read_env_file_value("JWT_SECRET")
