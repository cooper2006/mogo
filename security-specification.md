# MOGO 安全规范

本文档定义 MOGO 服务的安全设计规范，覆盖加密、访问控制、数据保护、部署安全等领域。

## 1. 传输与存储加密

### 1.1 HTTPS 强制

**QF-645 要求**：
- 生产环境强制 HTTPS
- 默认挂载 `nginx-https.conf`
- 明文 HTTP 请求重定向到 HTTPS

```nginx
# nginx-https.conf 示例
server {
    listen 80;
    server_name api.example.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name api.example.com;
    
    ssl_certificate /etc/ssl/certs/example.com.pem;
    ssl_certificate_key /etc/ssl/private/example.com.key;
    
    # ... rest of config
}
```

### 1.2 内部链路加密

**QF-649 要求**：
- 内部网络视为受控边界
- Redis 启用 `requirepass`
- MongoDB 启用用户认证
- 自托管部署文档明确声明 internal 网络边界

```yaml
# docker-compose.internal.yml 示例
services:
  redis:
    command: redis-server --requirepass ${REDIS_PASSWORD}
    environment:
      - REDIS_PASSWORD=${REDIS_PASSWORD}
  
  mongo:
    environment:
      - MONGO_INITDB_ROOT_USERNAME=${MONGO_USER}
      - MONGO_INITDB_ROOT_PASSWORD=${MONGO_PASSWORD}
```

### 1.3 静态数据加密

**QF-650 要求**：
- 手机号等高敏感字段加密存储
- 密钥由环境变量注入，不入库不入码

**QF-653 要求**：
- 备份链提供可选 `gpg`/`age` 加密
- 备份目录权限 700，仅 root 可访问

```bash
# 加密备份示例
tar czf - -C /var/lib/mogo . | gpg -c -o backup-$(date +%Y%m%d).tar.gz.gpg

# 解密恢复示例
gpg -d backup-20261011.tar.gz.gpg | tar xzf - -C /var/lib/mogo
```

## 2. 密钥管理

### 2.1 KMS 集成指引

**QF-651 要求**：
- 自托管部署支持本地密钥注入
- 云部署建议使用 KMS（AWS KMS、Azure Key Vault、GCP KMS）

```bash
# AWS KMS 示例
export MOGO_MASTER_KEY=$(aws kms decrypt --ciphertext-blob fileb://master.key.enc | jq -r '.Plaintext' | base64 -d)

# Azure Key Vault 示例
export MOGO_MASTER_KEY=$(az keyvault secret show --name mogo-master --vault-name $KEYVAULT --query value -o tsv)
```

### 2.2 密钥轮换

**QF-455 要求**：
- 支持双密钥窗口轮换
- 模型密钥与 JWT 密钥分离派生
- 轮换窗口：24 小时

```python
# 密钥轮换示例
class KeyRotation:
    def __init__(self):
        self.current_key = os.environ['MOGO_MASTER_KEY']
        self.previous_key = os.environ.get('MOGO_PREVIOUS_KEY')
        self.rotation_window = 24 * 3600  # 24 小时
    
    def decrypt(self, ciphertext, key_id):
        if key_id == 'current':
            return self._decrypt(self.current_key, ciphertext)
        elif key_id == 'previous' and self.previous_key:
            return self._decrypt(self.previous_key, ciphertext)
        else:
            raise ValueError(f"Unknown key: {key_id}")
```

## 3. 访问控制

### 3.1 MFA 策略

**QF-525 要求**：
- 高权限账号强制 MFA
- 未绑定 MFA 时拒绝登录或强制进入绑定流程

**QF-526 要求**：
- 第二因子校验失败 5 次后锁定 300 秒
- 锁定后强制重新登录

**QF-527 要求**：
- TOTP 验证码在同一时间窗内不可重放
- 记录已用时间步，要求提交步严格大于已记录值

**QF-530 要求**：
- MFA 解绑需要双因子确认（当前 TOTP + 当前口令）
- 解绑后通知持有人并写入审计事件

### 3.2 令牌管理

**QF-532 要求**：
- 会话令牌 TTL 2-4 小时
- 支持 refresh token 滑动续期

**QF-533 要求**：
- Refresh token 一次性轮换
- 检测重放（family_id 会话族）

**QF-535 要求**：
- 空闲超时 30 分钟
- 绝对超时 24 小时
- 任一超期即 401

```python
# 令牌管理示例
class TokenManager:
    SESSION_TTL = 4 * 3600  # 4 小时
    IDLE_TIMEOUT = 30 * 60  # 30 分钟
    ABSOLUTE_TIMEOUT = 24 * 3600  # 24 小时
    
    def validate_session(self, session):
        now = time.time()
        
        # 检查空闲超时
        if now - session['last_activity_at'] > self.IDLE_TIMEOUT:
            self.revoke_session(session)
            return False
        
        # 检查绝对超时
        if now > session['token_expires_at']:
            self.revoke_session(session)
            return False
        
        # 更新活动时间
        session['last_activity_at'] = now
        return True
```

## 4. 数据保护

### 4.1 用户数据权利

**QF-669 要求**：
- 提供数据导出（JSON 格式）
- 提供注销端点（映射到 purge/匿名化）
- 响应时限：30 天内

```http
GET /api/v1/user/data/export HTTP/1.1
Authorization: Bearer <token>

HTTP/1.1 200 OK
Content-Type: application/json
Content-Disposition: attachment; filename="user-data-export.json"

{
  "user": { ... },
  "messages": [ ... ],
  "documents": [ ... ],
  "exported_at": "2026-10-11T23:00:00Z"
}

DELETE /api/v1/user/account HTTP/1.1
Authorization: Bearer <token>

HTTP/1.1 204 No Content
```

### 4.2 数据留存

**QF-671 要求**：
- 消息留存：租户可配置，默认 90 天
- 执行日志留存：90 天
- 审计日志留存：1 年（法定要求）

| 数据类型 | 默认留存期 | 可配置 | 到期处置 |
|----------|------------|--------|----------|
| 消息记录 | 90 天 | 是 | 删除 |
| 执行日志 | 90 天 | 是 | 删除 |
| 审计日志 | 1 年 | 否 | 归档 |
| 备份 | 30 天 | 是 | 删除 |
| 临时文件 | 7 天 | 否 | 删除 |

### 4.3 PII 脱敏

**QF-659 要求**：
- 日志与错误上报中无明文敏感字段
- 使用 `pii.redact_text` 接入日志 formatter

```python
# 日志脱敏示例
import logging
from pii.redact_text import redact

class RedactingFormatter(logging.Formatter):
    def format(self, record):
        original_msg = record.getMessage()
        redacted_msg = redact(original_msg)
        record.msg = redacted_msg
        record.args = None
        return super().format(record)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[logging.StreamHandler()]
)
logging.getLogger().setLevel(logging.INFO)
```

## 5. 部署安全

### 5.1 非 root 运行

**QF-818 要求**：
- 所有容器镜像使用非 root 用户运行
- 创建专用 `appuser` 用户

```dockerfile
# Dockerfile 示例
FROM python:3.13-slim

RUN addgroup --system appgroup && \
    adduser --system --ingroup appgroup --home /app appuser

WORKDIR /app
COPY --chown=appuser:appgroup . .

USER appuser
CMD ["python", "app/main.py"]
```

### 5.2 基础设施安全配置

**QF-706 要求**：
- Weaviate 默认关闭匿名访问
- MongoDB/Redis 启用认证初始化
- 卷加密依赖宿主磁盘层

```yaml
# docker-compose.secure.yml 示例
services:
  weaviate:
    environment:
      - AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED=false
      - AUTHENTICATION_APIKEY_ENABLED=true
      - AUTHENTICATION_APIKEY_USERS=${WEAVIATE_API_KEY}
      - AUTHORIZATION_ADMINLIST_ENABLED=true
      - AUTHORIZATION_ADMINLIST_USERS=${WEAVIATE_ADMIN_USER}
  
  mongo:
    command: mongod --auth
    environment:
      - MONGO_INITDB_ROOT_USERNAME=${MONGO_USER}
      - MONGO_INITDB_ROOT_PASSWORD=${MONGO_PASSWORD}
  
  redis:
    command: redis-server --requirepass ${REDIS_PASSWORD}
    environment:
      - REDIS_PASSWORD=${REDIS_PASSWORD}
```

### 5.3 密钥泄露防护

**QF-698 要求**：
- pre-commit 钩子阻止密钥提交
- CI 扫描所有分支 push
- 文档化误报豁免流程

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.18.0
    hooks:
      - id: gitleaks

# gitleaks.toml
[[rules]]
id = "mogo-api-key"
description = "MOGO API keys"
regex = '''mogo-[a-zA-Z0-9]{32}'''
```

## 6. 安全监控

### 6.1 日志保留

**QF-678 要求**：
- 集中采集（Loki/ELK）
- 最小保留期：90 天
- 可检索性要求

```yaml
# Loki 配置示例
scrape_configs:
  - job_name: mogo-app
    static_configs:
      - targets: ['localhost:3100']
    pipeline_stages:
      - static:
          level: info
    scheme: http
    static_configs:
      - targets: ['localhost:3100']
```

### 6.2 安全审计

**QF-530 要求**：
- 所有敏感操作写入审计事件
- 审计事件包含：操作者、IP、UA、时间戳

```python
# 审计事件示例
class AuditEvent:
    def __init__(self, actor_id, action, resource, ip, user_agent):
        self.actor_id = actor_id
        self.action = action
        self.resource = resource
        self.ip = ip
        self.user_agent = user_agent
        self.timestamp = datetime.utcnow()
        self.status = 'success'
    
    def to_dict(self):
        return {
            'actor_id': self.actor_id,
            'action': self.action,
            'resource': self.resource,
            'ip': self.ip,
            'user_agent': self.user_agent,
            'timestamp': self.timestamp.isoformat(),
            'status': self.status
        }
```

## 7. 合规与声明

### 7.1 残余风险声明

以下风险为自托管部署的可接受残余风险：

| 风险项 | 风险描述 | 缓解措施 | 接受理由 |
|--------|----------|----------|----------|
| 明文存储 | 手机号等字段可能明文存储 | 文档建议加密 | 自托管用户可自行配置 |
| 本地密钥 | 密钥存储在本地环境变量 | 文档建议 KMS | 自托管用户可自行管理 |
| 内部网络 | 内部服务间无加密 | 文档声明受控边界 | 容器网络隔离 |
| 备份加密 | 备份默认未加密 | 文档提供加密指引 | 性能考虑 |

### 7.2 合规声明

MOGO 自托管部署的用户承担以下责任：

1. **数据保护**：用户负责配置数据加密和访问控制
2. **密钥管理**：用户负责生成、存储和轮换密钥
3. **合规义务**：用户负责满足所在地法律法规要求
4. **安全监控**：用户负责配置日志采集和安全监控

---

*本文档对应 QualityForge 审计项：QF-455, QF-525, QF-526, QF-527, QF-530, QF-532, QF-533, QF-535, QF-645, QF-649, QF-650, QF-651, QF-653, QF-659, QF-669, QF-671, QF-678, QF-698, QF-706, QF-818*
