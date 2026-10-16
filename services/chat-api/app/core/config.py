from pydantic import field_validator
from pydantic_settings import BaseSettings
from functools import lru_cache
import os

class Settings(BaseSettings):
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "MOGO"
    ALLOWED_ORIGINS: str = "http://localhost:3000,http://localhost:8080"
    
    # OpenAI
    # Model credentials are configured after the self-hosted control plane is
    # available, so an empty key must not prevent the API container from booting.
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    OPENAI_MODEL: str = "gpt-3.5-turbo"
    OPENAI_MODEL_GENERAL: str = "gpt-5.2"
    OPENAI_MODEL_CHAT: str = "gpt-5.2-chat"
    OPENAI_MODEL_CODING: str = "gpt-5.3-codex"

    # Azure OpenAI
    USE_AZURE: bool = False
    AZURE_OPENAI_ENDPOINT: str = ""
    AZURE_OPENAI_API_VERSION: str = "2023-05-15"
    AZURE_DEPLOYMENT_NAME: str = ""
    AZURE_DEPLOYMENT_CHAT: str = ""
    AZURE_DEPLOYMENT_GENERAL: str = ""
    AZURE_DEPLOYMENT_CODING: str = ""

    # Azure GPT Image

    # Qwen (DashScope OpenAI-compatible)
    USE_QWEN: bool = False
    QWEN_API_KEY: str = ""
    QWEN_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    QWEN_MODEL: str = "qwen-plus"

    # Multimodal Vision (DashScope OpenAI-compatible)
    USE_MULTIMODAL: bool = True
    DASHSCOPE_API_KEY: str = ""
    VISION_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    VISION_MODEL: str = "qwen3-vl-plus"
    VISION_ENABLE_THINKING: bool = True
    VISION_THINKING_BUDGET: int = 81920

    # Deep Search
    SERPAPI_API_KEY: str = ""  # Set via env; leave empty to disable
    SERPAPI_ENABLED: bool = False  # Disable SerpAPI when quota is exhausted
    SERPER_API_KEY: str = ""  # Set via env for google.serper.dev
    TAVILY_API_KEY: str = ""  # Set via env for Tavily search
    BAIDU_QIANFAN_API_KEY: str = ""  # Set via env for Baidu Qianfan ai_search/web_search
    BAIDU_QIANFAN_SEARCH_URL: str = "https://qianfan.baidubce.com/v2/ai_search/web_search"
    ARK_API_KEY: str = ""  # Set via env for Volcengine Ark Bot
    ARK_BOT_MODEL: str = ""  # e.g. bot-20260218195230-n4jrq
    ARK_BOT_BASE_URL: str = "https://ark.cn-beijing.volces.com/api/v3/bots"
    CRAWLER_API_URL: str = "http://localhost:8000/crawler"
    DOC_PARSER_API_URL: str = ""
    TOKEN_USAGE_PUSH_ENABLED: bool = False
    TOKEN_USAGE_PUSH_URL: str = ""
    TOKEN_USAGE_PUSH_TIMEOUT_SECONDS: float = 2.0
    TOKEN_USAGE_QUEUE_SIZE: int = 512

    # Internal knowledge base retrieval. When configured, kb_search calls this
    # service directly and does not fall back to local chat/session retrieval.
    KNOWLEDGE_CANDIDATES_API_URL: str = ""
    KNOWLEDGE_CANDIDATES_BASE_URL: str = ""
    KNOWLEDGE_CANDIDATES_TIMEOUT_SECONDS: float = 20.0
    KNOWLEDGE_CANDIDATES_MIN_RERANK_SCORE: float = 10.0
    DOCUMENT_PROCESSING_BASE_URL: str = "http://127.0.0.1:8200"
    DOCUMENT_PROCESSING_SERVICE_TOKEN: str = ""
    DOCUMENT_PROCESSING_TIMEOUT_SECONDS: float = 30.0
    DOCUMENT_PROCESSING_SYNC_PARSE_TIMEOUT_SECONDS: float = 180.0
    KNOWLEDGE_STORAGE_TYPE: str = "local"
    KNOWLEDGE_LOCAL_STORAGE_DIR: str = "../admin-api/data/knowledge-documents"
    KNOWLEDGE_OSS_BUCKET: str = ""
    KNOWLEDGE_OSS_ENDPOINT: str = ""
    
    # Financial Data
    TUSHARE_TOKEN: str | None = None
    
    # Tianyancha
    TIANYANCHA_TOKEN: str = ""

    # MongoDB
    MONGODB_URI: str = ""
    MONGODB_DB: str = "mogo_dev"
    # ── 数据后端开关（MongoDB → PanWeiDB 迁移，见
    # docs/mongo-to-panweidb-migration-plan.md）────────────────────────
    # 留空 = "mongo"（默认，行为与迁移前完全一致）；"panweidb" 走 openGauss 内核
    # / PostgreSQL 兼容线协议。规范环境变量 MOGO_DATA_BACKEND（不带服务前缀）。
    DATA_BACKEND: str = ""
    PANWEIDB_HOST: str = ""
    PANWEIDB_PORT: int = 0
    PANWEIDB_USER: str = ""
    PANWEIDB_PASSWORD: str = ""
    PANWEIDB_DB: str = ""
    PANWEIDB_SCHEMA: str = ""
    PANWEIDB_AUDIT_SCHEMA: str = ""
    PANWEIDB_SSLMODE: str = ""
    PANWEIDB_POOL_MIN_SIZE: int = 1
    PANWEIDB_POOL_MAX_SIZE: int = 10
    PANWEIDB_CONNECT_TIMEOUT: int = 5
    # 022 FR-11（T014）：终端用户 access token TTL 上限 1h；默认值已收紧到 3600s。
    END_USER_AUTH_TOKEN_TTL_SECONDS: int = 3600
    END_USER_AUTH_SECRET: str = ""
    # 029：门户 SSO 接收方票据签名密钥。留空时复用 END_USER_AUTH_SECRET（见下方校验器）。
    PORTAL_SSO_SECRET: str = ""

    @field_validator("PORTAL_SSO_SECRET")
    @classmethod
    def _fallback_portal_sso_secret(cls, value: str, info) -> str:
        # 029：未单独配置 PORTAL_SSO_SECRET 时，回退到终端用户会话密钥，
        # 保证不配置也能跑通；独立配置则可让门户票据与用户会话密钥解耦。
        if value:
            return value
        return str((info.data or {}).get("END_USER_AUTH_SECRET") or "")
    # 022 FR-18（T042）：运行环境标识。production 时强制关闭调试模式
    # （DEBUG 视为 False）、禁止回显异常详情与堆栈。
    APP_ENV: str = "development"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"
    LOG_FILE_ENABLED: bool = False
    LOG_FILE_PATH: str = "backend.log"
    LOG_FILE_FORMAT: str = "json"
    LOG_CONSOLE_PRETTY: bool = True
    LOG_CAPTURE_PRINTS: bool = True
    LOG_DEBUG_PAYLOADS: bool = False
    LOG_REQUEST_HEARTBEAT_SECONDS: float = 15.0
    LOG_SLOW_SPAN_MS: int = 10000
    LLM_SLOW_MS: int = 30000
    TOOL_SLOW_MS: int = 20000
    DB_SLOW_MS: int = 3000
    PRESENTATION_PAGE_SLOW_MS: int = 20000
    DEBUG_ARTIFACTS_ENABLED: bool = False
    DEBUG_ARTIFACT_RETENTION_DAYS: int = 7
    REQUEST_DEBUG_SNAPSHOT_ENABLED: bool = False
    ENABLE_BROWSER_PLANNING: bool = True
    ENABLE_CODING_PLANNING: bool = True
    PLAN_ONLY_MODE: bool = False
    PIPELINE_MODE: str = "task_network"
    # Deprecated — retained so existing .env files continue to load. The
    # presentation pipeline now trusts the LLM's first-shot geometry and has no
    # repair / normalize / fast-mode / raw-render switches to toggle.
    PRESENTATION_PIPELINE_VERSION: str = ""
    PRESENTATION_IMAGE_NATIVE_PAGE_CONCURRENCY: int = 2
    PRESENTATION_RAW_RENDER: str = ""
    PRESENTATION_V5_RAW_RENDER: str = ""
    ASKAI_ADMIN_JWT_SECRET: str = ""
    ADMIN_BACKEND_SERVICE_TOKEN: str = ""
    ADMIN_API_BASE_URL: str = "http://127.0.0.1:8100"
    DSH_MODEL_GATEWAY_SIGNING_SECRET: str = ""
    DSH_TOOL_GATEWAY_URL: str = "http://127.0.0.1:8000/internal/dsh/tools"
    DSH_RUNTIME_HOST_URL: str = "http://127.0.0.1:8101"
    # Comma separated list of Runtime Host instances for horizontal scaling.
    # Left empty, the transport falls back to DSH_RUNTIME_HOST_URL. When set,
    # every request of one kernel session sticks to one host (X-Session-Id).
    DSH_RUNTIME_HOSTS_URL: str = ""
    DSH_RUNTIME_HOST_TOKEN: str = ""
    DSH_MODEL_GATEWAY_URL: str = "http://127.0.0.1:8000/internal/dsh/model/generate"
    DSH_RUNTIME_HTTP_TIMEOUT_SECONDS: float = 5.0
    # Replica addresses used only by the §12.4 session ownership probe. Behind a
    # sticky LB, DSH_RUNTIME_HOST_URL points at the LB and the transport cannot
    # address a single replica; this list lets it ask each one "do you hold this
    # session?". Business traffic still goes through DSH_RUNTIME_HOST_URL.
    DSH_RUNTIME_REPLICA_URLS: str = ""
    # Session -> Runtime Host affinity cache (§12.4 option B). It only engages
    # when both a replica list and a Redis URL are configured; otherwise the
    # coordinator keeps its previous resume-blind behaviour.
    DSH_SESSION_AFFINITY_CACHE_TTL_SECONDS: float = 7200.0
    DSH_KERNEL_REDIS_URL: str = ""
    # Runtime creation lock (§ M2). Serialises runtime creation for one
    # isolation key across chat-api instances and pool replicas so a tenant's
    # kernel state cannot fork across replicas. Requires DSH_KERNEL_REDIS_URL;
    # degrades to uncoordinated creation when it is empty or unreachable.
    DSH_RUNTIME_DISTRIBUTED_LOCK: bool = True
    DSH_RUNTIME_LOCK_TTL_SECONDS: float = 30.0
    # L3 backpressure: cap on concurrent in-flight DSH turns per chat-api
    # process. 0 disables the cap (legacy unbounded behaviour). Set when
    # scaling chat-api so the LLM gateway's load grows sub-linearly with
    # replica count.
    DSH_RUNTIME_TURN_MAX_CONCURRENT: int = 32

    # SkillHub is a server-owned distribution source. Model-supplied URLs are
    # never fetched; only validated slugs are sent to this configured API.
    SKILLHUB_API_BASE_URL: str = "https://api.skillhub.cn"
    SKILLHUB_DOWNLOAD_TIMEOUT_SECONDS: float = 45.0

    # Optional demo APIs are excluded from production by default.
    ENABLE_DEMO_ENDPOINTS: bool = False
    # Upload limits. Defaults are intentionally generous to preserve existing
    # workflows while preventing accidental unbounded in-memory reads.
    MAX_UPLOAD_IMAGE_BYTES: int = 50 * 1024 * 1024
    # Harness thickness mode (019). "thick" = all six layers; "thin" = drop
    # approval + quota only (identity/rbac/redaction/audit stay, enforced at the
    # floor). Resolved per-request from the incoming payload; falls back to this
    # setting when the caller omits it.
    HARNESS_MODE: str = "thick"
    # 013 IM webhook HMAC secret. Set via environment; empty disables signature
    # verification (returns 500 until configured — intentional fail-closed).
    IM_WEBHOOK_SECRET: str = ""
    # 012 outbound A2A agents: server-owned JSON map of
    # agent name -> JSON-RPC endpoint URL. Outbound calls only ever target
    # endpoints listed here (SSRF: model/user input never selects the URL).
    A2A_OUTBOUND_AGENTS: str = ""
    MAX_UPLOAD_SKILL_SOURCE_BYTES: int = 200 * 1024 * 1024
    MAX_UPLOAD_TEMPLATE_BYTES: int = 200 * 1024 * 1024

    # 017 memory density tiers (FR-13 / FR-16). How long a generated L0/L1
    # summary stays fresh before a lazy re-generation (OQ-6, aligned with the
    # 30-day decay default); and the hard cap on non-tierable content.
    MEMORY_SUMMARY_REFRESH_DAYS: int = 30
    MEMORY_L2_HARD_MAX_BYTES: int = 1_000_000

    # Object storage. STORAGE_BACKEND=oss preserves the existing enterprise
    # Aliyun OSS behavior; STORAGE_BACKEND=local stores artifacts on disk and
    # serves them through /api/files.
    STORAGE_BACKEND: str = "local"
    # 022 US3 (T027)：compose 会把 askai-storage 卷挂到 /app/storage 并显式
    # 设置本变量；这里保留相对默认值以便 host 侧 dev/测试直接跑。
    LOCAL_STORAGE_PATH: str = "storage"
    FILE_PUBLIC_BASE_URL: str = ""
    FILE_PUBLIC_PATH_PREFIX: str = "/askai-api/api/files"
    BACKEND_INTERNAL_BASE_URL: str = "http://127.0.0.1:8000"
    OSS_ACCESS_KEY_ID: str = ""
    OSS_ACCESS_KEY_SECRET: str = ""
    OSS_BUCKET_NAME: str = "movo-artifacts"
    OSS_ENDPOINT: str = "https://oss-cn-beijing.aliyuncs.com"
    OSS_REGION: str = "cn-beijing"
    OSS_SIGN_EXPIRE_SECONDS: int = 3600

    @field_validator("DEBUG", mode="before")
    @classmethod
    def _normalize_debug(cls, value):
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"release", "prod", "production", "false", "0", "off", "no"}:
                return False
            if lowered in {"debug", "true", "1", "on", "yes"}:
                return True
        return value

    def allowed_origins_list(self) -> list[str]:
        return [
            origin.strip()
            for origin in str(self.ALLOWED_ORIGINS or "").split(",")
            if origin.strip()
        ]

    def is_planning_intent_enabled(self, intent: str) -> bool:
        token = str(intent or "").strip().lower()
        if token == "task":
            return True
        if token == "browser_automation":
            return bool(self.ENABLE_BROWSER_PLANNING)
        if token == "coding":
            return bool(self.ENABLE_CODING_PLANNING)
        return True

    def allowed_planning_intents(self) -> list[str]:
        intents = ["chat", "task"]
        return [intent for intent in intents if self.is_planning_intent_enabled(intent)]

    # ── PanWeiDB（MongoDB → PanWeiDB 迁移）────────────────────────────
    @property
    def effective_data_backend(self) -> str:
        """数据后端：``mongo``（默认）或 ``panweidb``。"""
        raw = self.DATA_BACKEND or os.getenv("MOGO_DATA_BACKEND", "") or "mongo"
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
        return self.PANWEIDB_HOST or os.getenv("PANWEIDB_HOST", "") or "127.0.0.1"

    @property
    def effective_panweidb_port(self) -> int:
        raw = self.PANWEIDB_PORT or os.getenv("PANWEIDB_PORT", "")
        try:
            return int(raw) if raw else 5432
        except (TypeError, ValueError):
            return 5432

    @property
    def effective_panweidb_user(self) -> str:
        return self.PANWEIDB_USER or os.getenv("PANWEIDB_USER", "")

    @property
    def effective_panweidb_password(self) -> str:
        return self.PANWEIDB_PASSWORD or os.getenv("PANWEIDB_PASSWORD", "")

    @property
    def effective_panweidb_db(self) -> str:
        return self.PANWEIDB_DB or os.getenv("PANWEIDB_DB", "") or self.MONGODB_DB

    @property
    def effective_panweidb_schema(self) -> str:
        return self.PANWEIDB_SCHEMA or os.getenv("PANWEIDB_SCHEMA", "") or "public"

    @property
    def effective_panweidb_audit_schema(self) -> str:
        return (
            self.PANWEIDB_AUDIT_SCHEMA
            or os.getenv("PANWEIDB_AUDIT_SCHEMA", "")
            or self.effective_panweidb_schema
        )

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"

# 022 FR-11（T014）：终端用户 access token 生命周期上限 1h。
MAX_END_USER_TOKEN_TTL_SECONDS = 3600


@lru_cache()
def get_settings():
    """返回进程级单例配置；首次调用即启动校验（超过 1h TTL 告警）。"""
    s = Settings()
    if s.END_USER_AUTH_TOKEN_TTL_SECONDS > MAX_END_USER_TOKEN_TTL_SECONDS:
        import logging

        logging.getLogger(__name__).warning(
            "END_USER_AUTH_TOKEN_TTL_SECONDS=%ss exceeds the %ss security ceiling "
            "(022 FR-11); tokens will outlive the 1h session guarantee",
            s.END_USER_AUTH_TOKEN_TTL_SECONDS,
            MAX_END_USER_TOKEN_TTL_SECONDS,
        )
    return s


# 模块级单例，供 ttl_purge 等模块直接 import使用
settings = get_settings()
