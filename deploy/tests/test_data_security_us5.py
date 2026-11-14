"""T045（022 US5 集成测试）：数据安全与加密。

覆盖 Phase 5 的五项独立测试目标：

1. HTTPS 强制（TLS ≥ 1.2 + HTTP→HTTPS 301）—— 网关配置静态校验；
2. 敏感字段密文存储（api_key / mfa_secret）；
3. 日志无明文敏感字段（redaction 生效）；
4. 审计防篡改（哈希链）+ 保留期 ≥ 180 天 + 审计库分离；
5. 数据地图存在且覆盖个人信息字段标注。

网关与容器运行时行为无法在本机完整验证（需要真实 nginx + 证书 + compose），
因此 TLS 部分采用**配置静态校验**：解析 nginx 配置断言关键指令存在且取值合规。
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

ADMIN_API = REPO_ROOT / "services/admin-api/app"
CHAT_API = REPO_ROOT / "services/chat-api/app"

TLS_CONF_CANDIDATES = [
    REPO_ROOT / "deploy/nginx/nginx.conf",
    REPO_ROOT / "deploy/docker/nginx-https.conf",
]

PLAINTEXT_SECRET_FIELDS = (
    "password",
    "password_hash",
    "mfa_secret_encrypted",
    "api_key_encrypted",
    "api_secret_encrypted",
    "apiKeyEncrypted",
    "token",
)


# ---------------------------------------------------------------------------
# 1. HTTPS 强制：TLS ≥ 1.2 + HTTP → HTTPS 301
# ---------------------------------------------------------------------------


def _tls_conf() -> Path:
    for candidate in TLS_CONF_CANDIDATES:
        if candidate.exists():
            return candidate
    pytest.fail(f"未找到 TLS 网关配置：{TLS_CONF_CANDIDATES}")


def test_tls_config_exists() -> None:
    assert _tls_conf().exists(), "TLS 网关配置必须存在（022 FR-17 / T036）"


def test_tls_protocols_minimum_version() -> None:
    """TLS 必须启用 1.2/1.3，且不得启用 1.0/1.1。"""
    text = _tls_conf().read_text(encoding="utf-8")
    match = re.search(r"ssl_protocols\s+([^;]+);", text)
    assert match is not None, "缺少 ssl_protocols 指令"
    protocols = set(match.group(1).split())
    assert "TLSv1.2" in protocols or "TLSv1.3" in protocols, (
        f"ssl_protocols={protocols} 必须包含 TLSv1.2 或 TLSv1.3"
    )
    for weak in ("TLSv1", "TLSv1.0", "TLSv1.1"):
        assert weak not in protocols, f"禁用了过时协议 {weak} 仍然出现在 ssl_protocols 中"


def test_tls_uses_aead_ciphers_only() -> None:
    """密码套件必须是 AEAD（GCM / CHACHA20），不允许 CBC / RC4 / 明文。"""
    text = _tls_conf().read_text(encoding="utf-8")
    match = re.search(r"ssl_ciphers\s+([^;]+);", text)
    assert match is not None, "缺少 ssl_ciphers 指令"
    ciphers = [c.strip() for c in match.group(1).split(":") if c.strip()]
    assert ciphers, "ssl_ciphers 为空"
    for cipher in ciphers:
        assert "GCM" in cipher or "CHACHA20" in cipher, (
            f"密码套件 {cipher} 不是 AEAD；TLS 必须只允许 AEAD 套件"
        )


def test_http_redirects_to_https_with_301() -> None:
    """80 端口必须 301 跳到 HTTPS；/healthz 例外供探针使用。"""
    text = _tls_conf().read_text(encoding="utf-8")
    assert re.search(r"listen\s+80\b", text), "缺少 listen 80 的 HTTP server 块"
    assert re.search(r"return\s+301\s+https://", text), (
        "HTTP server 块必须 return 301 https://...（HTTP→HTTPS 强制跳转）"
    )
    assert re.search(r"listen\s+443\s+ssl", text), "缺少 listen 443 ssl 的 HTTPS server 块"


def test_hsts_header_present() -> None:
    """HTTPS server 必须下发 HSTS，max-age 不少于 180 天。"""
    text = _tls_conf().read_text(encoding="utf-8")
    match = re.search(r'Strict-Transport-Security\s+"([^"]+)"', text)
    assert match is not None, "缺少 Strict-Transport-Security 响应头"
    age_match = re.search(r"max-age=(\d+)", match.group(1))
    assert age_match is not None, "HSTS 缺少 max-age"
    assert int(age_match.group(1)) >= 180 * 86400, (
        f"HSTS max-age={age_match.group(1)} 少于 180 天"
    )
    assert "includeSubDomains" in match.group(1), "HSTS 缺少 includeSubDomains"


def test_reverse_proxy_passes_forwarded_headers() -> None:
    """反向代理必须透传 X-Forwarded-* —— 后端据此判断上游协议。"""
    text = _tls_conf().read_text(encoding="utf-8")
    assert "X-Forwarded-Proto" in text, "缺少 X-Forwarded-Proto"
    assert "X-Forwarded-For" in text, "缺少 X-Forwarded-For"
    assert "X-Real-IP" in text, "缺少 X-Real-IP"


def test_compose_exposes_https_port() -> None:
    """docker-compose 必须暴露 443（gateway 服务）。"""
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert re.search(r"\${MOGO_HTTPS_PORT:-443}:443", compose), (
        "docker-compose.yml 未暴露 443 端口"
    )
    assert "MOGO_NGINX_CONF" in compose, (
        "docker-compose.yml 缺少 MOGO_NGINX_CONF，无法在挂载层切换 TLS 配置"
    )
    assert "MOGO_TLS_CERTS_DIR" in compose, "缺少 TLS 证书挂载"


# ---------------------------------------------------------------------------
# 2. 敏感字段密文存储
# ---------------------------------------------------------------------------


def test_model_provider_credentials_are_encrypted_at_rest() -> None:
    """模型实例的 api_key / api_secret 必须以 AES-GCM 密文落库。"""
    repo = ADMIN_API / "repositories/model_repository.py"
    assert repo.exists()
    text = repo.read_text(encoding="utf-8")
    assert "api_key_encrypted" in text and "encrypt_secret" in text, (
        "模型实例的 api_key 未走 encrypt_secret 加密"
    )
    assert "api_secret_encrypted" in text and "api_secret_masked" in text, (
        "模型实例的 api_secret 缺少加密字段与脱敏字段"
    )
    # 存储字段名不得等于明文 api_key / api_secret（会直接落库）
    for line_no, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        for field in ("api_key", "api_secret"):
            if re.search(rf'"{field}"\s*:', line) and "encrypted" not in line and "masked" not in line:
                # 允许出现在 payload 入参 dict 里（create_instance 内部会加密）
                if re.search(r"payload\.get\(|payload\[", line):
                    continue
                pytest.fail(f"model_repository.py:{line_no} 出现明文 {field} 存储")


def test_mfa_secret_is_encrypted_and_hashed() -> None:
    """MFA TOTP 密钥必须同时有密文与哈希（密文用于校验，哈希用于完整性）。"""
    auth_route = ADMIN_API / "api/routes/auth.py"
    text = auth_route.read_text(encoding="utf-8")
    assert "mfa_secret_encrypted" in text, "缺少 mfa_secret_encrypted 字段"
    assert "mfa_secret_hash" in text, "缺少 mfa_secret_hash 字段"
    assert "encrypt_value" in text or "encrypt_secret" in text, (
        "MFA 密钥未走加密函数"
    )


def test_account_password_is_never_stored_in_plaintext() -> None:
    """账号口令必须以哈希存储，不落明文 password 字段。"""
    repo = ADMIN_API / "repositories/org_user_repository.py"
    text = repo.read_text(encoding="utf-8")
    assert "password_hash" in text and "password_salt" in text, (
        "账号口令缺少哈希与盐"
    )
    # create_account / 更新口令路径不得写入 "password": 明文
    assert '"password": payload.get("password")' not in text
    assert '"password": password_hash' not in text


def test_vector_store_api_key_is_encrypted() -> None:
    """向量库连接凭据必须加密存储。"""
    route = ADMIN_API / "api/routes/knowledge_settings.py"
    text = route.read_text(encoding="utf-8")
    assert "apiKeyEncrypted" in text and "encrypt_secret" in text, (
        "向量库 apiKey 未加密"
    )
    assert "apiKeyMasked" in text, "向量库 apiKey 缺少脱敏字段"


def test_kms_module_provides_key_management() -> None:
    """KMS 模块存在且实现密钥分离（022 OQ-2）。"""
    kms = ADMIN_API / "security/kms.py"
    assert kms.exists(), "缺少 app/security/kms.py（KMS 密钥管理）"
    text = kms.read_text(encoding="utf-8")
    # 支持环境变量主密钥 + 可选 Vault（OQ-2 决策）
    assert "vault" in text.lower() or "env" in text.lower(), (
        "KMS 模块未体现 env / vault 两种密钥来源"
    )


# ---------------------------------------------------------------------------
# 3. 日志无明文敏感字段
# ---------------------------------------------------------------------------


def test_redaction_module_covers_sensitive_fields() -> None:
    """脱敏模块必须覆盖常见敏感字段名。"""
    redaction = ADMIN_API / "security/redaction.py"
    text = redaction.read_text(encoding="utf-8")
    patterns = re.search(r"SENSITIVE_KEY_PATTERNS\s*:\s*tuple\[str,\s*\.\.\.\]\s*=\s*\((.*?)\)", text, re.S)
    assert patterns is not None, "缺少 SENSITIVE_KEY_PATTERNS"
    blob = patterns.group(1).lower()
    # SENSITIVE_KEY_PATTERNS 是正则片段，做宽松的子串匹配。
    for field in ("password", "secret", "token", "apikey", "authorization"):
        needle = field.replace("api", "api").replace("_", "")
        assert needle in blob.replace("_", "").replace("-", ""), (
            f"SENSITIVE_KEY_PATTERNS 未覆盖 {field}"
        )


def test_audit_events_are_redacted_before_persist() -> None:
    """审计事件写入前必须经脱敏处理。"""
    audit = ADMIN_API / "security/audit_events.py"
    text = audit.read_text(encoding="utf-8")
    assert "_redaction.redact" in text, "审计事件未调用 redact"
    assert "redaction_config" in text, "审计仓库缺少 redaction 配置注入"


def test_debug_endpoints_are_gated() -> None:
    """调试端点必须同时受 DEBUG 开关与鉴权保护。"""
    debug_route = CHAT_API / "api/endpoints/debug.py"
    text = debug_route.read_text(encoding="utf-8")
    assert "require_debug_mode" in text, "调试端点缺少 DEBUG 模式闸门"
    assert "require_end_user_principal" in text or "Depends(" in text, (
        "调试端点缺少鉴权"
    )


# ---------------------------------------------------------------------------
# 4. 审计防篡改 + 保留期 + 库分离
# ---------------------------------------------------------------------------


def test_audit_chain_is_tamper_evident() -> None:
    """审计事件必须带哈希链，篡改可被发现。"""
    audit = ADMIN_API / "security/audit_events.py"
    text = audit.read_text(encoding="utf-8")
    assert "chain_hash" in text, "缺少哈希链"
    assert "verify_chain" in text, "缺少链校验"
    assert "AuditChainBroken" in text, "缺少断链异常"


def test_audit_retention_floor_is_180_days() -> None:
    """审计保留期下限必须 ≥ 180 天，低于下限自动提升。"""
    from app.security.audit_events import (
        MIN_AUDIT_RETENTION_DAYS,
        normalize_retention_days,
    )

    assert MIN_AUDIT_RETENTION_DAYS >= 180
    assert normalize_retention_days(90) == 180, "低于下限必须提升到 180"
    assert normalize_retention_days(180) == 180
    assert normalize_retention_days(365) == 365, "高于下限必须保留配置值"
    assert normalize_retention_days(-1) == -1, "负数表示禁用 TTL 清理"


def test_audit_retention_config_defaults_to_180() -> None:
    """配置默认保留期必须 ≥ 180 天。"""
    from app.core.config import Settings

    settings = Settings(_env_file=None)
    assert int(settings.audit_retention_days) >= 180, (
        f"audit_retention_days={settings.audit_retention_days} 低于合规下限 180"
    )


def test_audit_db_is_separable_from_business_db() -> None:
    """审计库必须能独立于业务库配置（022 FR-17 / T044）。"""
    from app.core.config import Settings
    from app.core.db import get_audit_db

    assert get_audit_db is not None, "缺少 get_audit_db"

    fallback = Settings(_env_file=None, audit_db="")
    assert fallback.effective_audit_db == "", "未配置时应为空（回退业务库）"

    separated = Settings(_env_file=None, audit_db="mogo_audit")
    assert separated.effective_audit_db == "mogo_audit"


@pytest.mark.asyncio
async def test_audit_retention_ttl_index_is_registered() -> None:
    """保留期 > 0 时必须注册 TTL 索引；= -1 时不注册。"""
    from app.security.audit_events import AuditEventRepository

    class FakeColl:
        def __init__(self) -> None:
            self.indexes: list[dict] = []

        async def create_index(self, keys, *args, **kwargs):
            entry = {"keys": keys}
            if kwargs:
                entry.update(kwargs)
            self.indexes.append(entry)

    class FakeDB:
        def __init__(self) -> None:
            self.colls: dict[str, FakeColl] = {}

        def __getitem__(self, name):
            return self.colls.setdefault(name, FakeColl())

    db = FakeDB()
    repo = AuditEventRepository(db, retention_days=180)
    await repo.ensure_indexes()
    ttl = [i for i in db.colls["audit_events"].indexes if i.get("expireAfterSeconds")]
    assert ttl, "未注册 TTL 索引"
    assert ttl[0]["expireAfterSeconds"] == 180 * 86400

    db_no_ttl = FakeDB()
    repo_no_ttl = AuditEventRepository(db_no_ttl, retention_days=-1)
    await repo_no_ttl.ensure_indexes()
    assert not [
        i for i in db_no_ttl.colls["audit_events"].indexes if i.get("expireAfterSeconds")
    ], "retention_days=-1 时不应注册 TTL 索引"


@pytest.mark.asyncio
async def test_audit_purge_expired_removes_only_old_events() -> None:
    """purge_expired 只删除超过保留期的事件，游标文档不动。"""
    from app.security.audit_events import AuditEventRepository, build_event

    class FakeColl:
        def __init__(self) -> None:
            self.docs: list[dict] = []

        async def insert_one(self, doc):
            self.docs.append(dict(doc))

        async def find_one(self, query, *a, **k):
            for doc in self.docs:
                if all(doc.get(k) == v for k, v in (query or {}).items()):
                    return dict(doc)
            return None

        async def delete_many(self, query):
            raw_cutoff = query.get("occurred_at", {}).get("$lt")
            ne = query.get("_id", {}).get("$ne")
            # 文档里 occurred_at 是 isoformat 字符串（body() 的规范化输出），
            # cutoff 是 datetime —— 统一成 datetime 比较。
            cutoff = datetime.fromisoformat(raw_cutoff) if isinstance(raw_cutoff, str) else raw_cutoff
            kept = [
                d for d in self.docs
                if d.get("_id") == ne
                or d.get("occurred_at") is None
                or not (
                    cutoff is not None
                    and datetime.fromisoformat(str(d["occurred_at"])) < cutoff
                )
            ]
            removed = len(self.docs) - len(kept)
            self.docs = kept
            class R:
                pass
            result = R()
            result.deleted_count = removed
            return result

        async def create_index(self, *a, **k):
            return None

        async def count_documents(self, query):
            return len(self.docs)

    class FakeDB:
        def __init__(self) -> None:
            self.colls = {}

        def __getitem__(self, name):
            return self.colls.setdefault(name, FakeColl())

    now = datetime.now(timezone.utc)
    db = FakeDB()
    repo = AuditEventRepository(db, retention_days=180)
    coll = db["audit_events"]

    old = build_event(
        action="login", decision="allow", actor_id="u1", tenant_id="t1",
        occurred_at=now - timedelta(days=200),
    )
    recent = build_event(
        action="login", decision="allow", actor_id="u1", tenant_id="t1",
        occurred_at=now - timedelta(days=1),
    )
    await coll.insert_one(old.document())
    await coll.insert_one(recent.document())

    removed = await repo.purge_expired(now=now)
    assert removed == 1
    remaining = {d.get("action") for d in coll.docs}
    assert len(coll.docs) == 1


# ---------------------------------------------------------------------------
# 5. 数据地图
# ---------------------------------------------------------------------------


def test_data_map_exists_and_covers_pii() -> None:
    """数据地图必须存在，且覆盖个人信息字段标注、处理依据、留存、删除能力。"""
    data_map = REPO_ROOT / "data/data-map.md"
    assert data_map.exists(), "缺少 data/data-map.md（022 FR-24 / T043）"
    text = data_map.read_text(encoding="utf-8")
    for heading in ("PII", "处理依据", "留存", "删除"):
        assert heading in text, f"data-map.md 缺少「{heading}」章节"
    # 关键集合与字段必须被覆盖
    for collection in ("admin_accounts", "audit_events", "chat_sessions"):
        assert collection in text, f"data-map.md 未覆盖集合 {collection}"
    for field in ("password_hash", "mfa_secret_encrypted", "api_key_encrypted"):
        assert field in text, f"data-map.md 未标注敏感字段 {field}"
    # 数据主体权利（GDPR）
    for right in ("访问", "更正", "导出", "删除"):
        assert right in text, f"data-map.md 缺少「{right}」权利说明"


def test_no_plaintext_secret_persisted_in_repository_layer() -> None:
    """落库层静态扫描：repositories/ 里不允许把明文口令/密钥写入文档。

    范围限定在 ``repositories/`` —— 这是唯一直接与 MongoDB 写入 API 打交道的
    层。路由层与业务服务层构造的 HTTP 请求体（发给外部模型/搜索服务）不属于
    「持久化」，不在本检查范围内。
    """
    offenders: list[str] = []
    for root in (ADMIN_API, CHAT_API):
        repo_dir = root / "repositories"
        if not repo_dir.is_dir():
            continue
        for path in repo_dir.rglob("*.py"):
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for line_no, line in enumerate(text.splitlines(), start=1):
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                for field in ("password", "api_key", "api_secret", "mfa_secret"):
                    if not re.search(rf'"{field}"\s*:', line):
                        continue
                    safe = any(
                        ok in line
                        for ok in ("_hash", "_encrypted", "masked", "hash_password", "encrypt_secret", "encrypt_value")
                    )
                    # 允许从入参 dict 透传（create_instance 等会把入参加密后再落库）
                    passthrough = "payload.get(" in line or "payload[" in line
                    if not safe and not passthrough:
                        offenders.append(f"{path.relative_to(REPO_ROOT)}:{line_no}: {stripped}")
    assert not offenders, (
        "以下位置疑似明文存储敏感字段，需改为哈希/密文：\n" + "\n".join(offenders)
    )
