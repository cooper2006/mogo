# Quickstart: API Contract & Semantics Hardening (025)

**Feature**: [spec.md](./spec.md) | [plan.md](./plan.md) | [tasks.md](./tasks.md)

本文件说明如何**启用并验证** API 契约与语义加固。

---

## 1. 前置

- 三个 FastAPI 服务：`services/admin-api`、`services/chat-api`、`services/document-parser`
- Python 3.13 + FastAPI + Pydantic v2（既有栈）
- Redis（限流 + 幂等键缓存）：`docker compose up -d redis`
- 依赖安装：
  ```bash
  pip install openapi-spec-validator spectral-cli redis-py httpx
  ```
- 契约文件已生成：`specs/025-api-contract-hardening/contracts/*.yaml`

---

## 2. 启用 US1 — API 语义

### 2.1 路径命名检查

```bash
python tools/api_check/path_naming.py \
  --services services/admin-api,~chat-api,~document-parser \
  --output path_naming_report.md
```

期望：报告列出所有动词段路径（`getXxx`/`listXxx`/`doXxx`），整改后报告为空。

### 2.2 载荷限制

编辑 `services/admin-api/app/config/payload_limits.yaml`：

```yaml
body_size_limit_mb: 10
json_max_depth: 16
array_max_length: 10000
```

启用中间件：在 `services/admin-api/app/main.py` 注册 `payload_limit` 中间件。

### 2.3 幂等与并发保护

编辑 `services/admin-api/app/config/rate_limit.yaml` 中的幂等配置，启用 `Idempotency-Key` 头支持。

### 2.4 分页稳定化

使用统一分页 schema（`services/admin-api/app/api/pagination.py`）替换各路由的自定义分页实现。

---

## 3. 启用 US2 — 错误处理

### 3.1 统一错误结构

确认 `services/*/app/core/error_handler.py` 已注册到 FastAPI app；所有错误响应遵循 `ErrorResponse` 结构（RFC 9457 扩展）。

### 3.2 限流

编辑 `services/admin-api/app/config/rate_limit.yaml`：

```yaml
dimensions:
  ip:
    limit: 100
    window: 60
  tenant:
    limit: 1000
    window: 60
  user:
    limit: 100
    window: 60
  endpoint:
    limit: 500
    window: 60
```

启用中间件：在 `services/admin-api/app/main.py` 注册 `rate_limit` 中间件。

### 3.3 批量接口

扫描 `services/admin-api/app/api/routes/knowledge_documents.py` 等批量接口，确保响应含逐项结果数组 + `partial` 字段；批量大小上限 100。

---

## 4. 启用 US3 — 契约测试

### 4.1 生成契约文件

```bash
# 从 OpenAPI 生成初始契约
python tools/openapi/generate.py \
  --services services/admin-api,~chat-api,~document-parser \
  --output specs/025-api-contract-hardening/contracts/
```

### 4.2 执行契约验证

```bash
# 提供方侧验证
python tools/contract/validate.py \
  --contract specs/025-api-contract-hardening/contracts/admin-api.yaml \
  --provider-url http://localhost:8000 \
  --side provider

# 消费方侧验证
python tools/contract/validate.py \
  --contract specs/025-api-contract-hardening/contracts/admin-api.yaml \
  --consumer-url http://localhost:5173 \
  --side consumer
```

### 4.3 兼容性 diff

```bash
python tools/contract/diff.py \
  --base specs/025-api-contract-hardening/contracts/admin-api.yaml \
  --head openapi.json \
  --fail-on-breaking
```

期望：不兼容变更返回非零退出码（CI 阻断）。

---

## 5. 启用 US4 — 演进与版本化

### 5.1 OpenAPI 生成与校验

```bash
# 生成 OpenAPI 3.1（三个服务；T040 用 subprocess 隔离 import，避免三服务共用顶层包名 app 互相污染）
python tools/openapi/generate.py --all
# 单服务：python tools/openapi/generate.py --service admin-api
# artifact 输出：specs/025-api-contract-hardening/openapi/{admin-api,chat-api,document-parser}-openapi.json

# 校验 OpenAPI（openapi-spec-validator + 内置 lint + 可选 spectral）
python tools/openapi/validate.py --all
# --skip-spectral：本地未装 spectral CLI 时跳过（内置 lint 仍执行）
```

期望：生成/校验均返回退出码 0；失败阻断 CI。T041 已据此修复 chat-api 两处 schema 缺陷（`required` 重复 `tenantId` 违反 uniqueItems；`ToolDescriptionGeneratePayload.name` 的 default 空串违反 `minLength`）。

### 5.2 版本方案（T042/T044/T045 落地）

- **主版本走 URL**：三服务路由统一迁移到 `/api/v1/...`（T045；admin-api / document-parser 改 `include_router(..., prefix="/api/v1")`，chat-api 33 处 `include_router` prefix + 8 个内部 router 硬编码的 `/api/...` prefix 一并迁移）。
- **旧路径永久重定向**：新中间件 `services/*/app/middleware/legacy_api_redirect.py` 的 `LegacyApiRedirectMiddleware` 把旧 `/api/*` 重定向到 `/api/v1/*`（保留 query）。**`GET`/`HEAD` → 301**；**`POST`/`PUT`/`PATCH`/`DELETE` → 308**（301 对非 GET 语义未定义，多数客户端会转成 GET 重发导致写操作丢失，308 保留方法与请求体）。验证：`TestClient` 下 `GET /api/auth/me` → 301 `/api/v1/auth/me`，`POST /api/auth/login` → 308。
- **小版本走响应头**：`services/admin-api/app/middleware/api_version.py` 的 `ApiVersionMiddleware` 在响应上写 `API-Version: 1.0.0`（契约主副本 `contracts/admin-api.yaml` 顶层 `version`）；`X-API-Version` 请求不拒绝。
- **口径文档**：`docs/api-versioning.md`（双轨模型、幅度规则复用 `tools/contract/diff.py` 的 `BREAKING_TYPES`/`COMPAT_TYPES`、废弃观察期对齐 FR-22 `bump_minor(version, minors=2)`、升级 7 步流程）。
- **错误码字典**：`docs/error-codes.md`（唯一权威字典，FR-30/FR-31）——通用 15 码 `api.*` + 业务码登记，含 `code`/`http_status`/`trigger`/`remedy` 四字段；`code` 值一经发布不可变更，映射变更属 `changed_status_semantics`（破坏性，须 major 升级）。

---

## 6. 验证清单

| # | 验证项 | 命令 | 期望 |
|---|---|---|---|
| 1 | 路径命名检查 | `python tools/api_check/path_naming.py` | 无动词段路径 |
| 2 | 状态码语义 | `pytest services/admin-api/tests/api/test_semantics.py -k status_code` | 200/201/204/406/413/422/429 语义正确 |
| 3 | 未知字段策略 | `pytest services/admin-api/tests/api/test_semantics.py -k unknown_fields` | 全局一致（不分裂） |
| 4 | 载荷限制 | `pytest services/admin-api/tests/api/test_semantics.py -k payload_limit` | 超限返回 413/422 |
| 5 | 幂等性 | `pytest services/admin-api/tests/api/test_semantics.py -k idempotent` | PUT/DELETE 重复调用无副作用 |
| 6 | 并发保护 | `pytest services/admin-api/tests/api/test_semantics.py -k concurrent` | 冲突返回 412 |
| 7 | 分页稳定 | `pytest services/admin-api/tests/api/test_semantics.py -k pagination` | 翻页无重复/漏项 |
| 8 | 错误结构统一 | `pytest services/admin-api/tests/api/test_errors.py -k error_structure` | 所有错误遵循 ErrorResponse |
| 9 | 错误码稳定 | `pytest services/admin-api/tests/api/test_errors.py -k error_code` | 错误码为稳定枚举 |
| 10 | 不泄漏内部信息 | `pytest services/admin-api/tests/api/test_errors.py -k no_leak` | 错误信息无内部组件/版本 |
| 11 | 限流 | `pytest services/admin-api/tests/api/test_errors.py -k rate_limit` | 超配额返回 429 + Retry-After |
| 12 | 批量语义 | `pytest services/admin-api/tests/api/test_errors.py -k batch` | 逐项结果 + partial 字段 |
| 13 | 契约测试（提供方） | `python tools/contract/validate.py --side provider` | 所有契约用例通过 |
| 14 | 契约测试（消费方） | `python tools/contract/validate.py --side consumer` | 所有契约用例通过 |
| 15 | 兼容性 diff | `python tools/contract/diff.py --fail-on-breaking` | 无不兼容变更 |
| 16 | OpenAPI 校验 | `python tools/openapi/validate.py` | 校验通过 |
| 17 | 错误码重名 | `python tools/api_check/error_codes_uniqueness.py` | 无跨服务重名 |
| 18 | 弃用字段观察期 | `python tools/contract/deprecation_check.py` | 无超期未移除字段 |
| 19 | 契约结构校验（三服务） | `python tools/contract/validate.py --all` | admin-api 46 / chat-api 63 / document-parser 10 interactions 全部合规 |
| 20 | 消费方源码证据 | `python tools/contract/consumer_refs.py --all` | 每条 interaction 在消费方源码有调用证据；仅契约已标注零消费方项 warn |
| 21 | 错误码映射稳定性 | `python tools/api_check/error_code_mapping.py` | 与基线快照一致；映射变更提示需 major 升级（FR-31） |
| 22 | OpenAPI 与实测一致性 | `python tools/openapi/probe.py --all` | 探针端点的路径/响应字段与 OpenAPI 一致 |
| 23 | OpenAPI 与契约一致（CI diff） | `python tools/openapi/generate.py --check` | 契约改动后 artifact 未重新生成即失败 |
| 24 | 旧路径重定向 | TestClient（`follow_redirects=False`） | `GET /api/x`→301、`POST /api/x`→308、`/health`→200 |

---

## 7. 单元测试（无需 DB/网络）

```bash
cd services/admin-api
PYTHONPATH=. python -m pytest tests/api/test_semantics.py tests/api/test_errors.py -o asyncio_mode=auto -q
```

期望：**语义域 12 项 + 错误域 12 项 = 24 项全部通过**。

---

## 8. 契约测试执行命令

```bash
# 全量契约测试（CI 执行）
python tools/contract/validate.py \
  --contract-dir specs/025-api-contract-hardening/contracts/ \
  --provider-url http://localhost:8000 \
  --consumer-url http://localhost:5173 \
  --fail-on-error

# 仅提供方侧
python tools/contract/validate.py \
  --contract-dir specs/025-api-contract-hardening/contracts/ \
  --provider-url http://localhost:8000 \
  --side provider

# 兼容性 diff（PR CI 阻断）
python tools/contract/diff.py \
  --base specs/025-api-contract-hardening/contracts/ \
  --head build/openapi/ \
  --fail-on-breaking
```

---

## 9. CI 接入（quality-gate.yml）

确认 `.github/workflows/quality-gate.yml` 包含 `api-contract-hardening` job（T048），依次执行：

```yaml
- name: Path Naming Check
  run: python tools/api_check/path_naming.py --services services/admin-api,~chat-api,~document-parser

- name: Error Codes Uniqueness
  run: python tools/api_check/error_codes_uniqueness.py --services services/admin-api,~chat-api,~document-parser

- name: Error Code Mapping Stability
  run: python tools/api_check/error_code_mapping.py --all

- name: Contract Validation
  run: python tools/contract/validate.py --all

- name: Compatibility Diff
  run: python tools/contract/diff.py --contract-dir specs/025-api-contract-hardening/contracts/ --base HEAD~1

- name: OpenAPI Generate + Validate
  run: |
    python tools/openapi/generate.py --all --check
    python tools/openapi/validate.py --all

- name: Deprecation Check
  run: python tools/contract/deprecation_check.py --all

- name: Consumer Evidence
  run: python tools/contract/consumer_refs.py --all
```

期望：所有 step 通过（退出码 0）；任一失败阻断 PR。

---

## 10. 故障注入验证（可选）

### 10.1 限流验证

```bash
# 快速触发限流（IP 维度 100/min）
for i in $(seq 1 110); do
  curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/v1/documents
done
# 期望：前 100 次返回 200，第 101+ 次返回 429 + Retry-After 头
```

### 10.2 幂等验证

```bash
# 相同 Idempotency-Key 重复调用
KEY=$(uuidgen)
curl -s -H "Idempotency-Key: $KEY" -X PUT http://localhost:8000/v1/documents/1 -d '{"name":"test"}'
curl -s -H "Idempotency-Key: $KEY" -X PUT http://localhost:8000/v1/documents/1 -d '{"name":"test"}'
# 期望：第二次调用返回相同响应（幂等）
```

### 10.3 并发冲突验证

```bash
# 获取 ETag
ETAG=$(curl -sI http://localhost:8000/v1/documents/1 | grep ETag | cut -d' ' -f2)
# 用旧 ETag 更新（应返回 412）
curl -s -o /dev/null -w "%{http_code}\n" \
  -X PUT -H "If-Match: $ETAG" -H "If-Match: W/\\"old\"" \
  http://localhost:8000/v1/documents/1 -d '{"name":"conflict"}'
# 期望：返回 412（条件失败）
```

---

## 11. 事件观测

- 错误响应含 `trace_id`（UUID），可通过日志系统追踪完整请求链路
- 限流事件记录到 `rate_limit_events` 日志表（维度/配额/触发时间/请求 IP）
- 契约测试失败记录到 `contract_violations` 日志表（契约文件/违反规则/提供方版本/消费方版本）
- OpenAPI diff 结果记录到 `openapi_diffs` 日志表（变更类型/是否破坏性/涉及路径）

---

## 12. 回退策略

- **路径重定向**：旧路径返回 301，客户端可无缝迁移到新路径
- **错误结构兼容**：`ErrorResponse` 含 `code`（稳定）+ `message`（可读），客户端可基于 `code` 做逻辑判断，不受 `message` 文案变更影响
- **版本兼容**：`/v1/` 前缀路由与旧路径并行，旧路径保留向后兼容（至少 2 个 minor 版本）
- **契约回退**：契约测试失败时，回退到上一个版本的契约文件（Git revert）即可恢复
