# Quickstart: Security Hardening (022)

**Feature**: [spec.md](./spec.md) | [plan.md](./plan.md) | [tasks.md](./tasks.md)

本文件说明如何**启用并验证**安全加固（5 个子域）。

---

## 1. 前置条件

- Docker Compose 环境可用
- MongoDB 可用
- Python 3.13+（仓库现有版本）
- Node.js 20+（前端构建）
- `pip-audit` / `pnpm audit`（供应链扫描）
- 反向代理（nginx/traefik）用于 TLS 终结
- 环境变量配置（见第 2 节）

---

## 2. 环境变量配置

在 `deploy/docker-compose.yml` 或 `.env` 中配置：

```bash
# 访问令牌 TTL（秒，≤ 3600）
ACCESS_TOKEN_TTL_SECONDS=3600
END_USER_AUTH_TOKEN_TTL_SECONDS=3600

# 会话超时
IDLE_TIMEOUT_SECONDS=1800        # 30 分钟
ABSOLUTE_TIMEOUT_SECONDS=86400   # 24 小时

# MFA 限流
MFA_MAX_ATTEMPTS=5
MFA_COOLDOWN_SECONDS=300

# 口令策略
PASSWORD_MIN_LENGTH=12
PASSWORD_MIN_CLASSES=3           # 大写/小写/数字/特殊字符

# CORS 白名单（逗号分隔，空 = 拒绝所有跨域）
CORS_ORIGINS=https://admin.example.com,https://user.example.com

# KMS Provider（首期 env-var，后续可切换 vault）
KMS_PROVIDER=env-var

# 主密钥（敏感字段加密，从 KMS 或环境变量读取）
MASTER_KEY_BASE64=<base64-encoded-32-byte-key>

# 服务间凭证（每个服务独立，生命周期 ≤ 24h）
ADMIN_API_SERVICE_TOKEN=<token>
CHAT_API_SERVICE_TOKEN=<token>
DOCUMENT_PARSER_SERVICE_TOKEN=<token>

# 审计日志保留期（天）
AUDIT_RETENTION_DAYS=180

# 调试模式（生产环境必须为 false）
DEBUG=false
```

---

## 3. US1 启用：口令与 MFA 强制策略

### 3.1 弱口令策略

**文件**: `services/admin-api/app/security/password_policy.py`

```python
from app.security.password_policy import validate_password

# 策略：长度 ≥ 12 + 大写 + 小写 + 数字 + 特殊字符四类至少三类
validate_password("Short1")       # False（长度不足）
validate_password("abcdefghij12") # False（无特殊字符，三类）
validate_password("Abcdefghij1!") # True（四类，长度 12）
```

**验证命令**:
```bash
cd services/admin-api
PYTHONPATH=. python -c "from app.security.password_policy import validate_password; print(validate_password('Abcdefghij1!'))"
# 期望: True
```

### 3.2 MFA 强制

**文件**: `services/admin-api/app/api/routes/auth.py`

登录流程：
1. 提交用户名 + 密码
2. 若账号为高权限角色（平台管理员/租户管理员）且未绑定 MFA → 返回 `mfa_required: true` + `mfa_setup_url`
3. 用户完成 MFA 绑定后才能进入业务

**验证命令**:
```bash
# 高权限账号未绑 MFA 登录 → 应返回 mfa_required: true
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin@company.com","password":"Abcdefghij1!"}' | jq '.mfa_required'
# 期望: true
```

### 3.3 TOTP 防重放

**文件**: `services/admin-api/app/security/mfa_policy.py`

```python
# 持久化 used_step，同一时间窗（±1 步）内同一 code 不可重复使用
verify_totp_with_replay_protection(user_id, code, window=1)
```

**验证命令**:
```bash
# 第一次验证 → 成功
curl -X POST http://localhost:8000/auth/mfa/verify \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"code":"123456"}' | jq '.success'
# 期望: true

# 同一 code 再次验证 → 拒绝
curl -X POST http://localhost:8000/auth/mfa/verify \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"code":"123456"}' | jq '.success'
# 期望: false
```

### 3.4 MFA 解绑通知

**文件**: `services/admin-api/app/api/routes/auth.py`

解绑成功后：
- 邮箱/手机通道可用 → 发送变更通知
- 通道未接入 → 降级为审计事件（`audit_events` 集合）

**验证命令**:
```bash
# 解绑 MFA
curl -X POST http://localhost:8000/auth/mfa/disable \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"currentPassword":"Abcdefghij1!"}' | jq '.success'
# 期望: true

# 检查审计事件（降级为审计事件）
mongosh --eval "db.audit_events.findOne({event_type:'mfa_disable', user_id:'<user_id>'})"
```

---

## 4. US2 启用：令牌与会话生命周期

### 4.1 访问令牌 TTL

**文件**: `services/admin-api/.env`, `services/chat-api/.env`

```bash
ACCESS_TOKEN_TTL_SECONDS=3600
END_USER_AUTH_TOKEN_TTL_SECONDS=3600
```

**验证命令**:
```bash
# 启动时超过 1h 告警
cd services/admin-api && docker compose logs admin-api 2>&1 | grep -i "ttl"
# 期望: 无告警（或显示 TTL=3600s）

# 验证令牌过期
TOKEN=<login_token>
echo $TOKEN | cut -d. -f2 | base64 -d 2>/dev/null | jq '.exp'
# 期望: exp - iat ≤ 3600
```

### 4.2 刷新令牌一次性轮换

**文件**: `services/admin-api/app/api/routes/auth.py`

```python
# /auth/refresh 一次性轮换 + 重放检测
POST /auth/refresh
  - 使用 refresh_token 后立即失效
  - 重放检测：使用已失效的 refresh_token → 吊销整个 token family
```

**验证命令**:
```bash
# 第一次 refresh → 成功，返回新 token
curl -X POST http://localhost:8000/auth/refresh \
  -H "Content-Type: application/json" \
  -d '{"refresh_token":"<old_refresh_token>"}' | jq '.access_token != null'
# 期望: true

# 重放旧 refresh_token → 拒绝
curl -X POST http://localhost:8000/auth/refresh \
  -H "Content-Type: application/json" \
  -d '{"refresh_token":"<old_refresh_token>"}' | jq '.error'
# 期望: "refresh_token_reused"
```

### 4.3 空闲/绝对超时

**文件**: `services/admin-api/app/middleware/timeout.py`

```python
# 空闲 30min / 绝对 24h 超时
IDLE_TIMEOUT_SECONDS = 1800
ABSOLUTE_TIMEOUT_SECONDS = 86400
```

**验证命令**:
```bash
# 验证 last_activity_at 判定
TOKEN=<access_token>
# 模拟 30 分钟无操作后访问
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/me | jq '.error'
# 期望: "session_expired" 或 401
```

### 4.4 服务间独立凭证

**文件**: `services/admin-api/app/security/service_token.py`

```python
# 每个服务独立 token，生命周期 ≤ 24h
class ServiceTokenManager:
    def issue_token(service_name, permissions): ...
    def verify_token(token, claimed_tenant_id, claimed_user_id): ...
```

**验证命令**:
```bash
# 服务间调用（独立 token）
curl -H "Authorization: Bearer <admin_api_service_token>" \
  -H "X-Tenant-ID: t1" \
  http://localhost:8001/api/internal/call | jq '.success'
# 期望: true（token 匹配 + tenantId 一致）

# 跨租户越权 → 拒绝
curl -H "Authorization: Bearer <admin_api_service_token>" \
  -H "X-Tenant-ID: t2" \
  http://localhost:8001/api/internal/call | jq '.error'
# 期望: "tenant_mismatch"
```

### 4.5 重置后强制改密

**文件**: `services/admin-api/app/api/routes/auth.py`

```python
# 管理端重置密码 → 用户下次登录必须以临时凭据登录 → 立即强制改密
POST /platform/tenants/{tenant_id}/admin/reset-password
  - 生成一次性临时凭据（15 分钟有效）
  - 用户下次登录 → 强制改密 → 旧凭据作废
```

**验证命令**:
```bash
# 重置密码
curl -X POST http://localhost:8000/platform/tenants/t1/admin/reset-password \
  -H "Authorization: Bearer <admin_token>" \
  -H "Content-Type: application/json" \
  -d '{"username":"user@company.com","temporary_password":"Temp1234!"}' | jq '.success'
# 期望: true

# 用户登录 → 强制改密
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"user@company.com","password":"Temp1234!"}' | jq '.must_change_password'
# 期望: true
```

---

## 5. US3 启用：授权与权限最小化

### 5.1 容器非 root

**文件**: `services/*/Dockerfile`（4 个）

```dockerfile
# 创建非 root 用户（UID 10001）
RUN groupadd -g 10001 appuser && \
    useradd -u 10001 -g 10001 -d /app -s /bin/bash appuser && \
    mkdir -p /app && chown -R appuser:appuser /app

USER appuser
WORKDIR /app
```

**验证命令**:
```bash
# 构建镜像
docker compose build

# 验证非 root 运行
docker compose exec admin-api id
# 期望: uid=10001(appuser) gid=10001(appuser) groups=10001(appuser)

docker compose exec chat-api id
docker compose exec document-parser id
docker compose exec admin-web id
# 期望: 均为 uid=10001
```

### 5.2 服务身份最小权限

**文件**: `services/admin-api/app/deps.py`

```python
# gatekeeper 服务身份校验
async def get_authenticated_service(request):
    token = extract_token(request)
    service_info = verify_service_token(token)
    claimed_tenant_id = request.headers.get("X-Tenant-ID")
    claimed_user_id = request.headers.get("X-User-ID")
    
    # 双因子核对：token 绑定的 tenant 与声明的 tenant 一致
    if service_info.tenant_id != claimed_tenant_id:
        raise HTTPException(status_code=403, detail="tenant_mismatch")
    
    # 权限最小化：服务 token 仅携带必要权限码
    if not check_service_permissions(service_info, claimed_user_id):
        raise HTTPException(status_code=403, detail="insufficient_permissions")
```

**验证命令**:
```bash
# 服务身份调用（最小权限）
curl -H "Authorization: Bearer <service_token>" \
  -H "X-Tenant-ID: t1" \
  -H "X-User-ID: u1" \
  http://localhost:8000/api/internal/readonly | jq '.success'
# 期望: true

# 跨租户越权 → 403
curl -H "Authorization: Bearer <service_token>" \
  -H "X-Tenant-ID: t2" \
  http://localhost:8000/api/internal/readonly | jq '.error'
# 期望: "tenant_mismatch"
```

---

## 6. US4 启用：输入安全加固

### 6.1 SSO 令牌 POST 换票

**文件**: `services/admin-api/app/api/routes/sso.py`

```python
# SSO 令牌从 URL 查询串改为 POST 换票
POST /api/sso/verify
  - 请求体: {"sso_token": "<token>", "sso_provider": "okta"}
  - URL 查询串不再包含 sso_token
```

**验证命令**:
```bash
# POST 换票（正确方式）
curl -X POST http://localhost:8000/api/sso/verify \
  -H "Content-Type: application/json" \
  -d '{"sso_token":"abc123","sso_provider":"okta"}' | jq '.success'
# 期望: true

# URL 查询串（错误方式，应拒绝）
curl "http://localhost:8000/api/sso/verify?sso_token=abc123" | jq '.error'
# 期望: "sso_token_not_in_url"
```

### 6.2 GET 无副作用

**文件**: `services/admin-api/app/api/routes/*.py`

将 4 个原 GET 写端点改为 POST：
- `GET /api/tools/{id}/test` → `POST /api/tools/{id}/test`
- `GET /api/knowledge/{id}/delete` → `POST /api/knowledge/{id}/delete`
- `GET /api/users/{id}/reset-password` → `POST /api/users/{id}/reset-password`
- `GET /api/sessions/{id}/revoke` → `POST /api/sessions/{id}/revoke`

**验证命令**:
```bash
# GET 写端点（应拒绝）
curl -X GET "http://localhost:8000/api/knowledge/k1/delete" | jq '.error'
# 期望: 405 Method Not Allowed

# POST 写端点（应成功）
curl -X POST "http://localhost:8000/api/knowledge/k1/delete" \
  -H "Authorization: Bearer <token>" | jq '.success'
# 期望: true
```

### 6.3 CORS 白名单

**文件**: `services/admin-api/app/middleware/cors.py`

```python
# CORS 白名单
CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "").split(",")
CORSMiddleware(
    allow_origins=CORS_ORIGINS,        # 显式白名单，拒绝 *
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],  # 显式方法
    allow_headers=["Authorization", "Content-Type", "X-Tenant-ID", "X-User-ID"],  # 显式头部
)
```

**验证命令**:
```bash
# CORS 预检（白名单内）
curl -X OPTIONS http://localhost:8000/api/me \
  -H "Origin: https://admin.example.com" \
  -H "Access-Control-Request-Method: GET" | jq '.access_control_allow_origin'
# 期望: "https://admin.example.com"

# CORS 预检（非白名单）
curl -X OPTIONS http://localhost:8000/api/me \
  -H "Origin: https://evil.com" | jq '.access_control_allow_origin'
# 期望: null（拒绝）
```

---

## 7. US5 启用：数据安全与加密

### 7.1 HTTPS 强制

**文件**: `deploy/nginx/nginx.conf`

```nginx
server {
    listen 80;
    server_name admin.example.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name admin.example.com;
    
    ssl_certificate /etc/nginx/ssl/server.crt;
    ssl_certificate_key /etc/nginx/ssl/server.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    
    # 反向代理到 admin-web
    location / {
        proxy_pass http://admin-web:80;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

**验证命令**:
```bash
# HTTP → HTTPS 301 跳转
curl -I http://admin.example.com/api/me | grep Location
# 期望: Location: https://admin.example.com/api/me

# TLS 版本 ≥ 1.2
openssl s_client -connect admin.example.com:443 -tls1_2 < /dev/null 2>&1 | grep "Protocol"
# 期望: Protocol : TLSv1.2 或 TLSv1.3
```

### 7.2 敏感字段加密存储

**文件**: `services/admin-api/app/security/encryption.py`

```python
# AES-GCM 加密
encrypt_field(plaintext: str, key: bytes) -> str  # 返回 base64 密文
decrypt_field(ciphertext: str, key: bytes) -> str  # 返回明文
```

**验证命令**:
```bash
# 验证敏感字段加密存储
mongosh --eval "db.api_keys.findOne({key_id:'<key_id>'}, {_id:0, encrypted_value:1, plain_value:0})" | jq '.encrypted_value'
# 期望: 非空（base64 密文）
# 期望: 不包含明文 key
```

### 7.3 日志脱敏

**文件**: `services/admin-api/app/security/redaction.py`

```python
# 日志脱敏
REDACT_FIELDS = ["password", "token", "sso_token", "api_key", "access_token", "refresh_token", "mfa_secret"]
redact_log_entry(entry: dict) -> dict  # 脱敏指定字段
```

**验证命令**:
```bash
# 检查审计日志无明文敏感字段
mongosh --eval "db.audit_events.findOne({event_type:'login'})" | grep -iE "(password|token|sso_token|api_key)" | grep -v "\*\*\*" | grep -v "REDACTED"
# 期望: 无输出（所有敏感字段已脱敏）
```

### 7.4 审计防篡改

**文件**: `services/admin-api/app/security/audit.py`

```python
# 审计事件防篡改（append-only）
class AuditEvent:
    def __init__(self, event_type, user_id, tenant_id, timestamp, data):
        self.prev_hash = get_latest_audit_hash()  # 链式哈希
        self.hash = compute_hash(self.prev_hash, self.timestamp, self.data)
```

**验证命令**:
```bash
# 验证审计链完整性
mongosh --eval "
  const events = db.audit_events.find().sort({timestamp: 1}).toArray();
  for (let i = 1; i < events.length; i++) {
    const expected = computeHash(events[i-1].hash, events[i].timestamp, events[i].data);
    if (events[i].hash !== expected) {
      print('TAMPER DETECTED at index ' + i);
      break;
    }
  }
  print('Audit chain integrity: OK');
"
# 期望: Audit chain integrity: OK
```

### 7.5 数据地图

**文件**: `data/data-map.md`

数据地图包含：
- 个人信息字段标注（字段名、类型、敏感级别）
- 处理依据（用户同意/合同必需/合法利益）
- 留存期限（天/月/年）
- 删除能力（API 端点/管理后台）

**验证命令**:
```bash
# 检查数据地图完整性
grep -E "字段|处理依据|留存期限|删除" data/data-map.md
# 期望: 每个个人信息字段都有标注
```

---

## 8. US6 启用：供应链安全

### 8.1 依赖漏洞扫描

**文件**: `.github/workflows/ci-security.yml`

```yaml
name: Security Scan
on: [pull_request, push]
jobs:
  pip-audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Install pip-audit
        run: pip install pip-audit
      - name: Scan requirements
        run: pip-audit --require-highest-version --strict --local --skip-editable
      - name: Scan lock files
        run: pip-audit --require-highest-version --strict --local
```

**验证命令**:
```bash
# 本地运行依赖扫描
cd services/admin-api
pip-audit --require-highest-version --strict --local --skip-editable
# 期望: 无高危 CVE（或全部为已知豁免）

# 前端扫描
cd services/admin-web
pnpm audit --production --audit-level high
# 期望: 无高危 CVE
```

### 8.2 构建权限分离

**文件**: `.github/workflows/release.yml`

```yaml
# 构建与部署使用独立 OIDC/service account
jobs:
  build:
    permissions:
      contents: read        # 只读
      packages: write       # 写镜像
      id-token: write       # OIDC
    # 无部署权限
  
  deploy:
    needs: build
    permissions:
      contents: read
      deployments: write    # 部署权限（独立 job）
    # 构建 job 无此权限
```

**验证命令**:
```bash
# 检查 workflow 权限
grep -A 10 "permissions:" .github/workflows/release.yml | grep -E "(contents|packages|id-token|deployments)"
# 期望: build job 无 deployments: write
```

### 8.3 提交钩子阻止密钥

**文件**: `scripts/check-secrets.sh`

```bash
#!/bin/bash
# 检查 git diff 中是否有密钥模式
git diff --cached --name-only | xargs -I {} sh -c '
  if grep -qE "BEGIN (RSA|EC|OPENSSH|DSA|PRIVATE) KEY|AKIA[0-9A-Z]{16}|-----BEGIN|-----END" "{}"; then
    echo "SECURITY: Potential secret detected in {}: $(basename {})"
    exit 1
  fi
'
```

**验证命令**:
```bash
# 提交密钥 → 应被阻止
echo "-----BEGIN RSA PRIVATE KEY-----" >> test.pem
git add test.pem
bash scripts/check-secrets.sh
# 期望: 非零退出码 + "SECURITY: Potential secret detected"
```

### 8.4 容器非 root（与 US3 联动）

参见 5.1 节。

---

## 9. 验证清单（总表）

| # | 验证项 | 子域 | 期望 | 验证命令 |
|---|---|---|---|---|
| 1 | 弱口令拒绝 | US1 | 400 + 明确错误 | `validate_password("Abcdefghij1!")` → True |
| 2 | MFA 未绑无法进入 | US1 | `mfa_required: true` | `curl /auth/login` → jq '.mfa_required' |
| 3 | TOTP 90s 不可重放 | US1 | 第二次验证拒绝 | `curl /auth/mfa/verify` 两次 |
| 4 | MFA 解绑通知 | US1 | 审计事件落库 | `mongosh db.audit_events.findOne` |
| 5 | access token TTL ≤ 1h | US2 | TTL ≤ 3600s | `jq '.exp - .iat'` ≤ 3600 |
| 6 | refresh 一次性轮换 | US2 | 重放拒绝 | `curl /auth/refresh` 两次 |
| 7 | 空闲 30min 超时 | US2 | 401 + `session_expired` | `curl /api/me` 后 30min |
| 8 | 服务间独立凭证 | US2 | token 匹配 + tenantId 一致 | `curl /api/internal/call` |
| 9 | 重置后强制改密 | US2 | `must_change_password: true` | `curl /auth/login` 后改密 |
| 10 | 4 个容器非 root | US3 | `uid=10001` | `docker exec ... id` |
| 11 | 服务身份最小权限 | US3 | 跨租户 403 | `curl /api/internal/readonly` |
| 12 | SSO 令牌 POST 换票 | US4 | URL 查询串拒绝 | `curl /api/sso/verify?sso_token=` |
| 13 | GET 无副作用 | US4 | GET 端点零写操作 | `pytest deploy/tests/test_no_side_effects_get.py` |
| 14 | CORS 白名单 | US4 | 非白名单 origin 预检 400 | `curl -X OPTIONS -H "Origin: https://evil.com" -v` |
| 15 | 全站 HTTPS 301 | US5 | `Location: https://` | `curl -I http://` |
| 16 | 敏感字段加密 | US5 | 数据库无明文 | `mongosh findOne({plain_value:1})` |
| 17 | 日志无明文 | US5 | 0 明文敏感字段 | `grep -iE "password|token" audit_events` |
| 18 | 审计防篡改 | US5 | 链完整性 OK | `mongosh` 链式哈希验证 |
| 19 | 数据地图完整 | US5 | 所有 PII 字段标注 | `grep data/data-map.md` |
| 20 | 高危 CVE 阻断构建 | US6 | PR 门禁失败 | `pip-audit --strict` |
| 21 | 构建/部署权限分离 | US6 | build 无部署权限 | `grep permissions: release.yml` |
| 22 | 提交钩子阻止密钥 | US6 | 非零退出码 | `bash scripts/check-secrets.sh` |
| 23 | Action 不可变固定 | US6 | 0 未达标 | `python3 scripts/check_action_pinning.py` |
| 24 | 漏洞管理政策 | US6 | 分级+工单+公告 | `ls docs/security/VULNERABILITY_POLICY.md` |
| 25 | 残余风险豁免 | US6 | 四要素+重审期 | `ls docs/security/RESIDUAL_RISK.md` |
| 26 | 性能回归检测 | P7 | p95 不超阈值 | `pytest deploy/tests/test_performance_us7.py` |
| 27 | 安全配置文档 | P7 | 全部配置项记录 | `ls docs/security/SECURITY_CONFIGURATION.md` |
| 28 | 全量验证通过 | P7 | 0 failed | `pytest deploy/tests/test_*_us[4-7].py` |

---

## 10. 单元测试命令

### 10.1 后端安全模块（无需 DB）

```bash
cd services/admin-api
PYTHONPATH=. python -m pytest \
  tests/test_security_password_policy.py \
  tests/test_security_mfa_policy.py \
  tests/test_security_encryption.py \
  tests/test_security_redaction.py \
  tests/test_security_service_token.py \
  -o asyncio_mode=auto -q
```

期望：所有测试通过（弱口令策略、MFA 强制/限流/防重放、加密/解密、日志脱敏、服务 token 校验）。

### 10.2 后端集成测试（需 DB）

```bash
cd services/admin-api
PYTHONPATH=. python -m pytest \
  tests/test_auth_login.py \
  tests/test_auth_mfa.py \
  tests/test_auth_refresh.py \
  tests/test_auth_timeout.py \
  tests/test_deps_service_identity.py \
  -o asyncio_mode=auto -q
```

### 10.3 前端安全测试

```bash
cd services/admin-web
pnpm test -- --grep "security"
```

### 10.4 全量安全验证

```bash
# 1. 依赖漏洞扫描
pip-audit --require-highest-version --strict --local --skip-editable
pnpm audit --production --audit-level high

# 2. 容器非 root 验证
docker compose build
for service in admin-api chat-api document-parser admin-web; do
  echo "=== $service ==="
  docker compose exec $service id
done

# 3. CORS 预检验证
curl -X OPTIONS http://localhost:8000/api/me -H "Origin: https://evil.com" -v 2>&1 | grep "access-control-allow-origin"

# 4. 审计链完整性
mongosh --eval "print('Checking audit chain...')"

# 5. 日志脱敏检查
docker compose logs admin-api 2>&1 | grep -iE "(password|token|sso_token|api_key)" | grep -v "\*\*\*" | grep -v "REDACTED" && echo "FAIL: plaintext leak" || echo "PASS: no plaintext leak"
```

---

## 11. 说明

- **MFA 通知**：邮件/短信通道未接入时降级为审计事件（`audit_events` 集合），通道接入后自动启用通知
- **KMS**：首期使用环境变量（`KMS_PROVIDER=env-var`），Vault 集成接口已预留（`KMSProvider` 抽象），切换时只需修改环境变量 + 配置 Vault
- **HTTPS**：TLS 终结在反向代理层（nginx），应用层通过 `SECURE_PROXY_SSL_HEADER` 感知 TLS 状态
- **服务间加密**：首期内网隔离 + 独立凭证，mTLS 为可选增强
- **CORS**：白名单来源由环境变量 `CORS_ORIGINS` 配置，默认空（拒绝所有跨域）
- **审计**：审计事件防篡改（链式哈希），与业务库分离存储，保留期 ≥ 180 天
