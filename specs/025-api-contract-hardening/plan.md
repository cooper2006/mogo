# Implementation Plan: API Contract & Semantics Hardening

**Branch**: `025-api-contract-hardening` | **Date**: 2026-10-11 | **Spec**: [spec.md](./spec.md)

**Input**: QualityForge 审计整改特性。把 50 个 P0/P1 缺陷（QF-202 ~ QF-270 子集）技术化到三个 FastAPI 服务（admin-api / chat-api / document-parser）+ CI 流水线。改动集中在 API 语义层、错误处理层、契约测试框架、OpenAPI 校验脚本，不引入新业务模块。

## Summary

在既有 FastAPI + Pydantic v2 栈之上引入**四层加固**：

1. **语义层**（US1）：路径命名检查、状态码规范、幂等/并发保护、分页稳定化、内容协商——集中在路由装饰器 + 中间件
2. **错误层**（US2）：统一 `ErrorResponse`（RFC 9457 扩展）、错误码注册表、限流中间件、批量语义——集中在 `app/core/errors.py` + `app/middleware/`
3. **契约层**（US3）：消费方定义契约 + 两侧验证 + CI diff 阻断——新增 `contracts/` + `tools/contract/`
4. **演进层**（US4）：OpenAPI 自动生成 + 校验、版本方案、错误码字典——新增 `tools/openapi/` + `docs/`

改动模式：**中间件 + 装饰器 + 工具脚本**，不重做路由、不改存储。影响面可控。

## Technical Context

**Language/Version**: Python 3.13（三个服务既有栈）

**Framework**: FastAPI（OpenAPI 3.1 原生支持）+ Pydantic v2（schema 定义）+ Starlette（中间件基座）

**Primary Dependencies**:
- 既有：`fastapi`、`pydantic>=2`、`uvicorn`、`redis`（限流/幂等）
- 新增：`openapi-spec-validator`（OpenAPI 校验）、`spectral-cli`（lint，或 Python 包）、`oasdiff`（兼容性 diff，或自研 Python 脚本）、`redis-py`（限流/幂等存储）
- 测试：`pytest`、`pytest-asyncio`、`httpx`（契约测试客户端）

**Storage**:
- 幂等键缓存：Redis（`idempotency:{tenant}:{route}:{key}` → 响应体，TTL 24h）
- 限流计数：Redis（`ratelimit:{dim}:{key}:{window}` → 滑动窗口计数）
- 错误码注册表：代码内 Python 枚举（`app/core/errors.py`），非 DB
- 契约文件：Git 仓库（`specs/025-api-contract-hardening/contracts/*.yaml`）

**Testing**: pytest（语义单测 + 错误处理单测 + 契约测试 + OpenAPI 校验 + 集成测试）

**Target Platform**: 自托管 Docker Compose

**Project Type**: 既有服务加固（中间件 + 装饰器 + 工具脚本，非新业务模块）

## 现有实现事实（contract 依据）

- **三个服务结构**：
  - `services/admin-api/app/api/routes/`：30+ 路由文件（含 `gatekeeper_internal.py`、`knowledge_documents.py`、`platform/tenants.py` 等）
  - `services/chat-api/app/`：无传统 `api/routes/`，走 `enterprise_capabilities/` + 对话链路
  - `services/document-parser/app/api/routes/`：6 路由文件（`document_parsing.py`、`retrieval.py`、`document_indexing.py`、`vector_maintenance.py`、`preview_conversion.py`、`health.py`）
- **既有安全**：`services/*/app/core/security.py`（JWT 依赖），`gatekeeper_internal.py` 已有权限码联动
- **既有 OpenAPI**：FastAPI 自动生成，但无 CI 校验、无 diff、无契约测试
- **既有错误处理**：各服务分散实现，无统一 `ErrorResponse`；部分路由返回 200 包裹错误
- **QualityForge 审计实测 fail 项**：
  - `api-semantics` 域：QF-202（路径动词段）、QF-204（状态码语义）、QF-210（未知字段分裂）、QF-213（翻页重复）、QF-218（PUT 非幂等）等**实际 fail**
  - `api-errors` 域：QF-229（错误结构分裂）、QF-230（无稳定错误码）、QF-234（错误信息泄漏内部组件）、QF-237（超配额返回 5xx）等**实际 fail**
  - `api-contracts` 域：无契约测试框架，全 `pending`
  - `api-evolution` 域：无 OpenAPI CI 校验，全 `pending`

## Constitution Check

| 原则 | 结果 |
|---|---|
| I. Specification-First | 通过：spec.md 完整定义 4 域 31 FR |
| II. Production Readiness | 通过：语义/错误/契约/演进 4 域加固直接提升生产 API 质量 |
| III. Security | 通过：FR-12 明确不泄漏内部信息、认证失败不泄漏资源存在性 |
| IV. i18n | 通过：错误信息英文（机器可读），文档中文；snake_case 字段命名 |
| V. Observability | 通过：`trace_id` 贯穿错误响应；OpenAPI diff 可观测 |

## Project Structure

```text
services/{admin-api,chat-api,document-parser}/app/
├── core/
│   ├── errors.py              # 新增：错误码注册表 + ErrorResponse 结构
│   ├── error_handler.py       # 新增：统一异常处理器（HTTPException + Exception → ErrorResponse）
│   ├── errors_codes.md        # 新增：错误码字典（trigger/remedy/http_status）
│   ├── idempotency.py         # 新增：幂等键中间件（Redis 缓存）
│   ├── etag.py                # 新增：ETag/If-Match 条件请求中间件
│   └── security.py            # 既有：保留 JWT 依赖
├── middleware/                # 新增子目录（或合并到 core/）
│   ├── rate_limit.py          # 新增：限流中间件（Redis 滑动窗口）
│   ├── content_negotiation.py # 新增：Accept/Encoding 协商中间件
│   ├── payload_limit.py       # 新增：载荷大小/深度/数组长度限制中间件
│   └── trace_id.py            # 新增：trace_id 注入中间件
├── api/
│   ├── routes/                # 既有：路由文件（本特性整改路径命名、状态码、分页）
│   └── pagination.py          # 新增：统一分页 schema + cursor 翻页助手
└── config/
    ├── rate_limit.yaml        # 新增：限流维度与阈值配置
    └── payload_limits.yaml    # 新增：载荷限制配置

specs/025-api-contract-hardening/
├── contracts/                 # 新增：契约文件（YAML，消费方定义）
│   ├── admin-api.yaml
│   ├── chat-api.yaml
│   └── document-parser.yaml
└── checklists/
    └── requirements.md        # 新增：需求质量门禁

tools/                         # 新增：跨服务工具脚本
├── api_check/
│   ├── path_naming.py         # 路径命名检查（FR-1）
│   ├── status_codes.py        # 状态码语义检查（FR-3）
│   └── unknown_fields.py      # 未知字段策略检查（FR-4）
├── contract/
│   ├── validate.py            # 契约验证脚本（FR-16 ~ FR-24）
│   └── diff.py                # 兼容性 diff 脚本（FR-20）
└── openapi/
    ├── generate.py            # OpenAPI 生成脚本（FR-25）
    └── validate.py            # OpenAPI 校验脚本（FR-26）

docs/                          # 新增文档
├── api-versioning.md          # 版本方案文档（FR-27, FR-28）
├── error-codes.md             # 错误码字典文档（FR-30）
└── rate-limiting.md           # 限流维度与阈值文档（FR-13）

.github/workflows/
└── quality-gate.yml           # 既有：新增契约测试 + OpenAPI 校验 + 路径命名检查 job
```

## 实施顺序（US1 → US2 → US3 → US4）

按依赖关系，先落地语义层和错误层（被契约测试覆盖的对象），再落地契约测试框架，最后落地演进层（OpenAPI 校验 + 版本方案）。

```text
Phase 1 (基础设施) → US1 (语义) → US2 (错误) → US3 (契约测试) → US4 (演进)
```

- **Phase 1**：错误码注册表 + ErrorResponse 结构 + trace_id 中间件（被 US1/US2/US3 复用）
- **US1**：路径命名检查 + 状态码规范 + 幂等/并发 + 分页稳定 + 内容协商
- **US2**：统一错误处理器 + 限流 + 批量语义 + 降级空值
- **US3**：契约文件 + 验证脚本 + diff 脚本 + CI 接入
- **US4**：OpenAPI 生成/校验 + 版本方案 + 错误码字典文档

## Open Questions（已 clarify 消解，见 spec.md §Clarify 记录）

- **OQ-1 错误响应结构**：RFC 9457 Problem Details 扩展（`code`/`trace_id`/`field`/`path`），非自研结构。
- **OQ-2 幂等键作用域**：`tenant + route + key`，Redis 缓存 TTL 24h。
- **OQ-3 批量状态码**：200 + `partial=true`（非 207）。
- **OQ-4 版本方案**：URL 路径 `/v1/` + `API-Version` 响应头双轨。
- **OQ-5 限流阈值**：IP:100/min、tenant:1000/min、user:100/min、endpoint:500/min（可配）。

## 与现有特性关系

- **001 gatekeeper（权限码联动）**：本特性不改变 001 的权限码机制；001 的 `gatekeeper_internal` 路由是本特性契约覆盖对象之一；001 的配额维度是 FR-13 限流维度的输入之一。
- **003 document-ingestion-delivery（API 契约）**：003 的 document-parser API 是本特性契约测试的重点提供方；003 的批量解析接口是 FR-14 覆盖对象。
- **008 ops-dashboard（运营看板）**：本特性的错误码字典与限流响应是 008 API 质量看板的数据来源。

## 下一步

`/speckit-clarify`（OQ 已消解）→ `/speckit-checklist` → `/speckit-tasks` → `/speckit-analyze` → `/speckit-implement` → `/speckit-converge`。

实施入口：`tasks.md`（按 US 分组，含具体文件路径与并行标记）。
