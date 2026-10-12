# 安全配置参考

> 022 Phase 7 (T055)。本文档汇总 022 安全加固引入的全部环境变量与配置项，
> 按子域分组。完整的配置参考见 [`docs/configuration-reference.md`](../configuration-reference.md)。

## 令牌与会话

| 配置项 | 默认值 | 范围 | 说明 |
|--------|--------|------|------|
| `ACCESS_TOKEN_TTL_SECONDS` | `3600` | ≤ 3600 | admin-api 访问令牌 TTL。超过 3600 秒会被自动截断到 3600 并告警（`MAX_ACCESS_TOKEN_TTL_SECONDS`）。 |
| `END_USER_AUTH_TOKEN_TTL_SECONDS` | `3600` | ≤ 3600 | chat-api 终端用户令牌 TTL。同样有 3600 秒上限。 |
| `END_USER_AUTH_SECRET` | `""` | ≥ 32 字符 | chat-api JWT 签名密钥。生产环境必须显式配置。 |
| `JWT_SECRET` | `""` | ≥ 32 字符 | admin-api JWT 签名密钥。生产环境必须显式配置；本地/开发环境自动生成随机值并告警。 |
| `BACKEND_SERVICE_TOKEN` | `""` | — | 服务间通信令牌。未配置时回退到静态共享密钥（灰度兼容），配置后启用独立凭证。 |
| `DOCUMENT_PROCESSING_SERVICE_TOKEN` | `""` | — | document-parser 服务令牌。 |
| `INVITE_TOKEN_TTL_HOURS` | `72` | > 0 | 邀请令牌有效期（小时）。 |

## 会话超时

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `IDLE_TIMEOUT_SECONDS` | `1800` | 空闲超时：30 分钟内无操作则令牌失效。 |
| `ABSOLUTE_TIMEOUT_SECONDS` | `86400` | 绝对超时：24 小时后无论是否活跃都失效。 |

两者取先到达者。由 `session_timeout.py` 在每次请求时校验。

## CORS

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `CORS_ORIGINS` | `""` | 允许的跨域来源，逗号分隔。**空字符串是合法状态**（拒绝所有跨域），但会在启动时告警。不支持通配符（`*`、`*.example.com`）—— 在 `allow_credentials=True` 下 Starlette 无法正确反射通配源。 |
| `CORS_ALLOW_METHODS` | 显式白名单 | `GET,POST,PUT,PATCH,DELETE,OPTIONS`。 |
| `CORS_ALLOW_HEADERS` | 显式白名单 | `Authorization,Content-Type,Accept,X-Requested-With`。 |

## 审计与保留

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `MONGODB_AUDIT_DB` | `""` | 审计日志独立数据库名。未配置时回退到业务库（`MONGODB_DB`）。生产环境**必须**显式配置以启用审计库分离。 |
| `AUDIT_RETENTION_DAYS` | `180` | 审计日志保留天数。低于 180 会自动提升到 180 并告警（`MIN_AUDIT_RETENTION_DAYS`）。设为 `-1` 禁用 TTL 索引（不建议）。 |

## 调试与诊断

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `APP_ENV` | `development` | 运行环境。生产环境使用 `production`/`prod`/`release` 别名。生产环境强制 `debug=False`。 |
| `DEBUG` | `false` | 调试模式。生产环境被强制关闭，误配降级为告警。 |
| `LOG_DEBUG_PAYLOADS` | `false` | 是否在日志中输出请求/响应负载。默认关闭（防止敏感数据进入日志）。 |

## 加密与密钥管理

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `KMS_PROVIDER` | `local` | 密钥管理提供商。`local` 使用内置 AES-GCM；`vault` 使用 HashiCorp Vault（可选）。 |
| `KMS_VAULT_ADDR` | `""` | Vault 地址。仅在 `KMS_PROVIDER=vault` 时需要。 |
| `KMS_VAULT_TOKEN` | `""` | Vault token。建议在 Vault 侧使用短期 token 而非长期 token。 |

## TLS

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `MOGO_HTTPS_PORT` | `443` | 网关 HTTPS 端口。 |
| `MOGO_NGINX_CONF` | `""` | 自定义 nginx 配置路径。未设置时使用默认配置。 |
| `MOGO_TLS_CERT_PATH` | — | TLS 证书路径（PEM 格式）。 |
| `MOGO_TLS_KEY_PATH` | — | TLS 私钥路径（PEM 格式）。 |

## 验证命令

```bash
# 检查所有安全配置是否正确
python3 -c "
import os, sys
errors = []
checks = {
    'JWT_SECRET': (32, 'admin-api JWT 密钥'),
    'END_USER_AUTH_SECRET': (32, 'chat-api JWT 密钥'),
}
for key, (min_len, desc) in checks.items():
    val = os.environ.get(key, '')
    if len(val) < min_len:
        errors.append(f'{key}: 长度 {len(val)} < {min_len}（{desc}）')
if os.environ.get('APP_ENV') in ('production', 'prod', 'release'):
    if os.environ.get('DEBUG', 'false').lower() == 'true':
        errors.append('DEBUG=true 在 prod 下被强制关闭')
    if not os.environ.get('MONGODB_AUDIT_DB', ''):
        errors.append('MONGODB_AUDIT_DB 未配置（审计库未分离）')
if errors:
    print('配置检查失败：')
    for e in errors:
        print(f'  ✗ {e}')
    sys.exit(1)
print('✓ 安全配置检查通过')
"
```

## 变更记录

| 日期 | 变更 |
|------|------|
| 2026-10-12 | 初版（022 Phase 7 / T055） |
