# MOGO API 规范

本文档定义 MOGO 服务的 RESTful API 设计规范，包括内容协商、错误处理、幂等性与安全约束。

## 1. 内容协商（Content Negotiation）

### 1.1 支持的媒体类型

MOGO API **仅支持** `application/json` 作为请求和响应的媒体类型。

| 请求头 | 值 | 说明 |
|--------|-----|------|
| `Content-Type` | `application/json` | 必须，请求体格式 |
| `Accept` | `application/json` | 必须，响应格式 |

### 1.2 不支持的 Accept 处理

**当前行为**：所有请求返回 JSON，忽略 Accept 头。

**QF-225 修复计划**：
- 在网关层（nginx）或应用中间件对不兼容的 Accept 返回 `406 Not Acceptable`
- 支持的 Accept 值：`application/json`、`*/*`
- 不支持的值：`application/xml`、`application/pdf` 等

```http
# 错误示例
GET /api/quota/me HTTP/1.1
Accept: application/pdf

HTTP/1.1 406 Not Acceptable
Content-Type: application/json
{
  "code": "UNSUPPORTED_MEDIA_TYPE",
  "message": "Only application/json is supported",
  "supported_types": ["application/json"]
}
```

### 1.3 压缩协商

**QF-227 修复计划**：
- 入口 nginx 配置 `gzip on`，支持 `application/json` 和 `text/event-stream`
- SSE 流式响应需排除 gzip 或注意缓冲

## 2. 错误响应规范

### 2.1 错误响应结构（RFC 9457 problem+json）

所有错误响应使用统一的 envelope 结构：

```json
{
  "code": "ERROR_CODE",
  "message": "人类可读的错误描述",
  "details": {
    "field": "具体字段或资源",
    "value": "问题值"
  },
  "trace_id": "请求追踪 ID",
  "request_id": "请求 ID"
}
```

### 2.2 错误码字典

| 错误码 | HTTP 状态码 | 说明 |
|--------|-------------|------|
| `VALIDATION_ERROR` | 422 | 请求验证失败 |
| `UNAUTHORIZED` | 401 | 未认证或 token 无效 |
| `FORBIDDEN` | 403 | 权限不足 |
| `NOT_FOUND` | 404 | 资源不存在 |
| `CONFLICT` | 409 | 资源冲突 |
| `PRECONDITION_FAILED` | 412 | 前置条件失败 |
| `UNPROCESSABLE_ENTITY` | 422 | 请求语义错误 |
| `UNSUPPORTED_MEDIA_TYPE` | 415 | 不支持的媒体类型 |
| `NOT_ACCEPTABLE` | 406 | 不支持的响应格式 |
| `TOO_MANY_REQUESTS` | 429 | 请求过多（限流） |
| `PAYMENT_REQUIRED` | 402 | 配额已用尽 |
| `INTERNAL_ERROR` | 500 | 服务器内部错误 |
| `SERVICE_UNAVAILABLE` | 503 | 服务不可用 |

### 2.3 错误信息不暴露内部组件

**QF-234 要求**：
- 生产环境关闭 Swagger 文档（`docs_url=None`）
- 健康检查不暴露依赖版本明细
- 错误消息不包含堆栈跟踪或内部路径

### 2.4 认证失败不泄漏资源存在性

**QF-235 要求**：
- 对不可公开的资源命名空间，认证失败统一返回 404
- 示例：访问其他租户的资源返回 404，而非 403

```http
GET /api/v1/tenant/other-tenant-id/resources HTTP/1.1
Authorization: Bearer invalid-token

HTTP/1.1 404 Not Found
Content-Type: application/json
{
  "code": "NOT_FOUND",
  "message": "Resource not found"
}
```

## 3. 幂等性与重试

### 3.1 幂等键

**QF-219 要求**：
- 写接口支持 `Idempotency-Key` 请求头
- 幂等窗口：24 小时（receipts 集合 TTL）
- 同键不同载荷返回 409 冲突

```http
POST /api/v1/messages HTTP/1.1
Idempotency-Key: unique-request-id-12345
Content-Type: application/json

{ "content": "Hello" }

HTTP/1.1 201 Created
Location: /api/v1/messages/abc123
{
  "id": "abc123",
  "content": "Hello",
  "created_at": "2026-10-11T23:00:00Z"
}
```

### 3.2 DELETE 语义

**QF-218 要求**：
- 重复 DELETE 返回 204（幂等）
- 统一约定：`DELETE` 对已删除资源返回 204，而非 404

```http
# 第一次删除
DELETE /api/v1/documents/abc123 HTTP/1.1

HTTP/1.1 204 No Content

# 重复删除
DELETE /api/v1/documents/abc123 HTTP/1.1

HTTP/1.1 204 No Content
```

### 3.3 PUT 语义

**QF-218 要求**：
- PUT 是幂等的：重复 PUT 同一资源返回相同结果
- 使用 ETag 支持条件更新

```http
PUT /api/v1/users/abc123 HTTP/1.1
If-Match: "etag-v1"
Content-Type: application/json

{ "name": "New Name" }

HTTP/1.1 200 OK
ETag: "etag-v2"
{ "id": "abc123", "name": "New Name" }
```

## 4. 分页规范

### 4.1 分页元信息

**QF-216 要求**：
- 统一分页响应 envelope 规范

```json
{
  "items": [...],
  "total": 100,
  "page": 1,
  "page_size": 20,
  "has_more": true,
  "next_cursor": "cursor-value"
}
```

### 4.2 翻页稳定性

**QF-213 要求**：
- 使用游标分页（cursor-based）确保翻页期间数据变动不产生重复或漏项
- 页大小默认 20，最大 100

## 5. 限流规范

### 5.1 限流维度与阈值

**QF-240 要求**：
- 按用户维度限流
- 默认阈值：每用户每分钟 100 请求
- 超限返回 429 与 `Retry-After` 头

### 5.2 限流响应

```http
HTTP/1.1 429 Too Many Requests
Content-Type: application/json
Retry-After: 60
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 1728721200

{
  "code": "TOO_MANY_REQUESTS",
  "message": "Rate limit exceeded",
  "retry_after": 60,
  "limit": 100,
  "remaining": 0,
  "reset_time": 1728721200
}
```

### 5.3 配额响应

**QF-237 要求**：
- 配额用尽返回 402 Payment Required
- 响应包含重置时间

```http
HTTP/1.1 402 Payment Required
Content-Type: application/json
X-Quota-Remaining: 0
X-Quota-Reset: 1728721200

{
  "code": "PAYMENT_REQUIRED",
  "message": "Quota exceeded",
  "remaining": 0,
  "reset_time": 1728721200
}
```

## 6. 安全约束

### 6.1 HTTPS 强制

**QF-645 要求**：
- 生产环境强制 HTTPS
- 明文 HTTP 请求重定向到 HTTPS 或返回错误

### 6.2 调试模式

**QF-236 要求**：
- 生产环境强制关闭调试模式
- 启动时校验环境配置

### 6.3 批量接口

**QF-247 要求**：
- 批量请求上限：500 项
- 超限返回 400

**QF-248 要求**：
- 4xx = 全单未生效
- 200 = 全部生效

## 7. 状态码使用规范

| HTTP 状态码 | 使用场景 |
|-------------|----------|
| 200 OK | 成功获取/更新资源 |
| 201 Created | 成功创建资源 |
| 204 No Content | 成功删除资源（无响应体） |
| 308 Permanent Redirect | 永久重定向（保留方法） |
| 400 Bad Request | 请求格式错误 |
| 401 Unauthorized | 未认证 |
| 402 Payment Required | 配额用尽 |
| 403 Forbidden | 权限不足 |
| 404 Not Found | 资源不存在 |
| 406 Not Acceptable | 不支持的响应格式 |
| 409 Conflict | 资源冲突 |
| 412 Precondition Failed | 前置条件失败 |
| 415 Unsupported Media Type | 不支持的请求格式 |
| 422 Unprocessable Entity | 请求语义错误 |
| 429 Too Many Requests | 请求过多 |
| 500 Internal Server Error | 服务器内部错误 |
| 503 Service Unavailable | 服务不可用 |

## 8. 版本标识与条件请求

**QF-222 要求**：
- 资源返回强 ETag
- PUT/PATCH 支持 `If-Match` → 412

```http
GET /api/v1/users/abc123 HTTP/1.1

HTTP/1.1 200 OK
ETag: "abc123-2026-10-11"
Content-Type: application/json

{ "id": "abc123", "name": "User" }
```

## 9. 批量接口规范

**QF-245 要求**：
- 批量接口逐项返回处理结果
- 保持原子语义（全有全无）

```json
{
  "code": "BATCH_OK",
  "message": "All items processed",
  "total": 50,
  "results": [
    { "id": 1, "status": "success" },
    { "id": 2, "status": "success" }
  ]
}
```

## 10. 路径规范

**QF-202 要求**：
- 路径表达资源而非动作
- 动作型子资源使用 `{id}/action` 格式

| 资源 | 路径 | 动作 | 路径 |
|------|------|------|------|
| 消息 | `/messages` | 创建消息 | `POST /messages` |
| 消息 | `/messages/{id}` | 删除消息 | `DELETE /messages/{id}` |
| 文档 | `/documents` | 创建文档 | `POST /documents` |
| 文档 | `/documents/{id}/parse` | 解析文档 | `POST /documents/{id}/parse` |
| 文档 | `/documents/{id}/restore` | 恢复文档 | `POST /documents/{id}/restore` |

## 11. 未知字段处理

**QF-210 要求**：
- 写接口默认 `forbid`（拒绝未知字段）
- 跨端兼容接口显式标注 `ignore`

## 12. 载荷限制

**QF-211 要求**：
- messages 字段：`Field(max_length=50000)`
- 单请求总长度校验
- 数组长度上限：100 项

## 13. 并发控制

**QF-221 要求**：
- 可并发编辑资源引入 `updated_at`/版本字段
- 条件更新使用 `find_one_and_update with version filter`
- 冲突返回 409/412

**QF-223 要求**：
- 序号/计数使用原子 `$inc` 操作
- 额度扣减使用原子 `$inc` + 余额条件过滤

## 14. 降级策略

**QF-252 要求**：
- 依赖不可用路径统一抛 503
- 禁止静默空值

```http
HTTP/1.1 503 Service Unavailable
Content-Type: application/json

{
  "code": "SERVICE_UNAVAILABLE",
  "message": "Upstream service unavailable",
  "trace_id": "request-123"
}
```

---

*本文档对应 QualityForge 审计项：QF-202, QF-203, QF-204, QF-207, QF-210, QF-211, QF-213, QF-216, QF-218, QF-219, QF-222, QF-225, QF-227, QF-230, QF-232, QF-234, QF-235, QF-236, QF-237, QF-238, QF-239, QF-240, QF-245, QF-247, QF-248, QF-252, QF-221, QF-223*
