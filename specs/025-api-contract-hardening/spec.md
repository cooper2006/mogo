# Feature Specification: API Contract & Semantics Hardening

**Feature Branch**: `025-api-contract-hardening`

**Created**: 2026-10-11

**Status**: Draft

**Input**: QualityForge 审计（50 个 P0/P1 缺陷，覆盖 API 语义、错误处理、契约、演进）。审计范围覆盖 `services/admin-api`、`services/chat-api`、`services/document-parser` 三个 FastAPI 服务的对外/内部 RESTful API；本特性聚焦**语义一致性、错误规范、契约验证、版本演进**四域，不引入新协议，不改变既有 RESTful 风格。

## User Scenarios & Testing *(mandatory)*

用户故事按优先级排列，每个独立可交付、可测试；每个故事引用 QualityForge 缺陷编号（QF-xxx）作为可追溯锚点。

### User Story 1 (P1) — API 语义规范

资源表达、状态码、幂等、并发、内容协商等语义在跨服务 API 中全局一致；无历史遗留的路径/状态码"补丁式实现"。

- QF-202 路径表达资源而非动作（如 `/users` 而非 `/getUsers`）
- QF-203 媒体类型声明与载荷一致
- QF-204 成功路径返回语义正确状态码（200/201/204）
- QF-207 重定向与缓存状态码正确（301/302/304）
- QF-210 未知字段处理策略全局一致
- QF-211 载荷大小/深度/数组长度有上限
- QF-213 翻页期间数据变动不产生重复或漏项
- QF-216 分页元信息可程序化消费
- QF-218 PUT/DELETE 幂等
- QF-219 幂等键作用域与冲突语义
- QF-220 超时重试不重复扣减
- QF-221 并发更新不静默丢失数据
- QF-222 条件请求与版本标识
- QF-223 读改写原子性
- QF-224 竞态窗口可识别且被保护
- QF-225 不支持的 Accept 明确拒绝
- QF-227 压缩协商按声明生效

**Acceptance Scenarios:**
- 新增/现存路由路径全部资源化（无 `getXxx`/`doXxx`/`listXxx` 动词段），CI 路径命名检查通过
- 200/201/204/202/301/302/304/406/413/422/429 各语义状态码按 HTTP 语义正确使用，无"200 包裹错误"
- PUT/DELETE 重复调用不产生副作用；幂等键冲突返回明确语义（409 或 200，规则全局一致）
- 并发 PUT 通过 ETag/If-Match 保护，冲突返回 412 而非静默覆盖
- 分页元信息（`total`/`page`/`page_size`/`has_next`/`next_cursor`）可程序化消费，翻页期间数据变动无重复/漏项
- 未知 `Accept` 返回 406；未知字段全局一致策略（不各服务分裂）
- 载荷超限返回 413（大小）/422（结构）而非 500

### User Story 2 (P1) — 错误处理规范

所有错误响应结构统一、错误码稳定、定位信息可观测、不泄漏内部信息、限流语义明确、批量语义清晰。

- QF-229 全部错误响应同一结构与字段语义
- QF-230 错误体含稳定错误码
- QF-231 错误响应含定位信息（`trace_id`、`field`、`path`）
- QF-232 错误结构与文档化定义一致
- QF-234 错误信息不暴露内部组件与版本
- QF-235 认证/授权失败不泄漏资源存在性
- QF-236 调试模式在非开发环境强制关闭
- QF-237 超配额返回 429 而非 5xx
- QF-238 限流响应带可解析重试提示
- QF-239 限流响应说明配额维度与余额
- QF-240 限流维度与阈值有文档且与实现一致
- QF-245 批量接口逐项返回处理结果
- QF-247 批量大小有上限且超限被拒绝
- QF-248 批量整体状态码与局部失败匹配
- QF-252 降级不返回错误的空值语义

**Acceptance Scenarios:**
- 三个服务所有错误响应遵循同一 `ErrorResponse` 结构（`code`/`message`/`detail`/`trace_id`/`field`/`path`/`docs_url`）
- 错误码为稳定字符串枚举（如 `api.not_found`、`api.rate_limited`），跨服务无重复、有字典
- 401/403 不泄漏"资源是否存在"（统一返回 401 或 403，不区分"用户不存在"vs"密码错"、不区分"资源不存在"vs"无权限"）
- 生产/预发环境 `DEBUG=false` 强制；异常栈不出现在响应体
- 超配额返回 429 + `Retry-After` 头（秒数或 HTTP-date），不返回 500/503
- 限流响应 `detail` 含 `limit`/`remaining`/`window`/`reset_at`，客户端可解析
- 批量接口（如 `POST /batches/{kind}`）返回逐项结果数组 + 整体 `status`；超限（>N）返回 422；整体 `207 Multi-Status` 或 `200 + 部分失败`（规则全局一致）
- 降级场景返回明确空值语义（如 `null` + `degraded=true`），不返回误导性的空数组/空对象

### User Story 3 (P1) — 契约测试

契约由消费方（chat-api/admin-web）定义，在提供方（admin-api/document-parser）与消费方两侧同时验证；不兼容改动被 CI 阻断；破坏性变更伴随新版本或并行提供。

- 契约由消费方定义并在两侧验证
- 契约覆盖代码实际依赖的字段与状态码
- 不兼容的提供方改动被契约测试阻断
- 破坏性变更伴随新版本或并行提供
- 兼容性由自动化 diff 在 CI 中检查
- 新增可选字段不破坏旧消费方
- 弃用字段在移除前有观察期
- 删除字段前确认无消费方读取
- 序列化格式与字段命名两侧一致
- 契约验证不依赖共享可变环境

**Acceptance Scenarios:**
- 契约文件（YAML/JSON）存放于 `specs/025-api-contract-hardening/contracts/`，由消费方仓库持有主副本
- 契约测试在 CI 中执行（`pytest -m contract`），提供方与消费方两侧各跑一次
- OpenAPI 与契约文件的兼容性 diff 在 PR CI 中阻断（失败即红）
- 新增可选字段（schema 中 `optional: true`）不触发契约失败
- 弃用字段（`deprecated: true`）保留观察期（默认 2 个 minor 版本）后才允许移除
- 删除字段前 CI 检查"无消费方读取"（基于契约引用扫描）
- 序列化格式（JSON）与字段命名（snake_case）两侧一致，测试用例中显式断言

### User Story 4 (P1) — API 演进与版本化

OpenAPI 定义从源码自动生成、与实测一致、CI 校验阻断；版本方案全局一致、错误码集中管理、字典含触发条件与处理建议。

- QF-253 接口定义可从源码自动生成
- QF-254 定义中的路径/参数/响应与实测一致
- QF-255 定义校验在 CI 中执行且失败阻断
- QF-264 版本方案全局一致且有文档
- QF-267 版本升级幅度与变更性质匹配
- QF-268 错误码集中定义且全局唯一
- QF-269 字典包含触发条件与处理建议
- QF-270 错误码与 HTTP 状态码映射稳定

**Acceptance Scenarios:**
- 三个服务的 OpenAPI 3.1 定义由 FastAPI 自动生成，`openapi.json` 在 CI 中生成并 diff
- 定义中的路径/参数/响应与实测（`pytest -m integration` + 探针）一致，无漂移
- OpenAPI 校验（`openapi-spec-validator` / `spectral`）在 CI 中执行且失败阻断 PR
- 版本方案：URL 路径版本（`/v1/...`）+ `API-Version` 响应头，全局一致，有 `docs/api-versioning.md`
- 版本升级幅度规则：新增字段 → patch；新增端点 → minor；破坏性 → major（首期仅 minor 兼容路径）
- 错误码集中定义于 `app/core/errors.py`（每服务），字典含 `code`/`http_status`/`trigger`/`remedy` 四字段
- 错误码跨服务全局唯一（CI 检查重名）；错误码与 HTTP 状态码映射稳定（变更需版本升级）

## Notes / Assumptions

- 本特性是 **QualityForge 审计整改**，输入是 50 个 P0/P1 缺陷（QF-202 ~ QF-270 子集），不涉及新业务能力
- 现有基础：三个服务均已用 FastAPI + Pydantic v2 生成 OpenAPI；已有 `app/core/security.py`（JWT 依赖）；已有 `app/api/routes/*` 路由；已有 `docs/api/` 部分文档
- **api-semantics 与 api-errors 两域在审计中有实际 `fail` 项**（非纯 `na`/`pending`），本特性的修复以实测 fail 为强约束，不能只补文档
- 与特性 001（gatekeeper）的关系：001 管**权限码与配额维度**，本特性管**API 契约与错误语义**——001 的 `gatekeeper_internal` 路由是本特性契约的覆盖对象之一
- 与特性 003（document-ingestion-delivery）的关系：003 的 `document-parser` API 契约（上传/解析/检索）是本特性契约测试的重点提供方
- 首期不引入 GraphQL、不引入多版本并行（单版本 + 向后兼容演进），见 Non-Goals
- 版本方案、错误码字典、限流阈值的具体取值需 `/speckit-clarify` 定值（见 plan.md OQ）

## Functional Requirements

### US1 — API 语义（FR-1 ~ FR-9）

- **FR-1** 路径资源化（QF-202）：所有路由路径表达资源（`/users`/`/documents/{id}`），禁动词段（`/getUsers`/`/listDocuments`）；CI 新增 `tools/api_check/path_naming.py` 校验
- **FR-2** 媒体类型一致（QF-203）：请求/响应 `Content-Type` 与载荷一致；非 JSON 载荷（文件上传/下载）显式声明 `multipart/form-data`/`application/octet-stream`；OpenAPI schema 中 `content` 声明与代码一致
- **FR-3** 状态码语义正确（QF-204, QF-207）：成功 200/201/204；已接受 202；重定向 301/302；缓存 304；不支持 406；载荷过大 413；校验失败 422；限流 429；条件失败 412——**禁止 200 包裹错误**
- **FR-4** 未知字段策略全局一致（QF-210）：全局 Pydantic 配置 `model_config = ConfigDict(extra='ignore')`（默认）或按 schema 显式声明 `extra='forbid'`（严格）；不允许各服务/各 schema 分裂
- **FR-5** 载荷限制（QF-211）：请求体大小上限（默认 10MB，可配）；JSON 嵌套深度上限（默认 16）；数组长度上限（默认 10000）；超限返回 413/422
- **FR-6** 翻页稳定 + 元信息可程序化（QF-213, QF-216）：分页响应含 `total`/`page`/`page_size`/`has_next`/`next_cursor`（5 字段，snake_case）；翻页期间数据变动不产生重复或漏项（基于 cursor 的稳定翻页）
- **FR-7** 幂等性（QF-218, QF-219, QF-220）：PUT/DELETE 幂等；支持 `Idempotency-Key` 请求头；幂等键作用域 = 租户 + 路由 + 键值；冲突返回 409；超时重试不重复扣减（针对计费/计数类接口）
- **FR-8** 并发更新保护（QF-221, QF-222, QF-223, QF-224）：PUT 支持 `If-Match` + ETag；冲突返回 412；读改写操作走原子事务（`SELECT ... FOR UPDATE` 或 `UPDATE ... WHERE version = ?`）；竞态窗口（如"检查再写"）通过原子操作消除
- **FR-9** 内容协商（QF-225, QF-227）：不支持的 `Accept` 返回 406 + `Vary: Accept`；`Accept-Encoding` 按声明生效（gzip/br）；`Vary` 头正确声明

### US2 — 错误处理（FR-10 ~ FR-15）

- **FR-10** 错误响应结构统一（QF-229, QF-232）：全局 `ErrorResponse` 结构：`{ code: string, message: string, detail?: object, trace_id: string, field?: string, path?: string, docs_url?: string }`；OpenAPI 中定义 `ErrorResponse` schema 且所有错误响应引用它
- **FR-11** 稳定错误码 + 定位信息（QF-230, QF-231）：`code` 为稳定字符串枚举（如 `api.not_found`、`api.rate_limited`、`api.conflict`）；错误体含 `trace_id`（链路追踪）、`field`（字段级错误）、`path`（JSONPath）
- **FR-12** 不泄漏内部信息（QF-234, QF-235, QF-236）：错误信息不含内部组件名/版本号/文件路径/SQL；401/403 不泄漏资源存在性（统一响应）；`DEBUG` 在非 dev 环境强制关闭（`os.environ.get("ENV", "prod") != "dev"`）
- **FR-13** 限流响应（QF-237, QF-238, QF-239, QF-240）：超配额返回 429 + `Retry-After` 头；`detail` 含 `limit`/`remaining`/`window`/`reset_at`；限流维度（IP/tenant/user/endpoint）与阈值有 `docs/rate-limiting.md`，与实现代码一致
- **FR-14** 批量接口（QF-245, QF-247, QF-248）：批量响应含逐项结果数组 + 整体 `status`；批量大小上限（默认 100，可配）；超限返回 422；整体状态码规则：全成功 200、全失败 4xx/5xx、部分失败 207 或 200+`partial=true`（全局一致，首期选 200+`partial`）
- **FR-15** 降级空值语义（QF-252）：降级场景返回 `null` + `degraded: true` 元信息，不返回误导性空数组/空对象

### US3 — 契约测试（FR-16 ~ FR-24）

- **FR-16** 契约由消费方定义（US3-1）：契约文件（Pact 风格 YAML 或自定义 JSON Schema）由消费方仓库持有主副本，存放在 `specs/025-api-contract-hardening/contracts/`
- **FR-17** 契约覆盖实际依赖（US3-2）：契约测试用例覆盖消费方代码实际读取的字段、状态码、错误码，不覆盖"可能用到"的字段
- **FR-18** 不兼容改动阻断（US3-3）：提供方改动若破坏契约（删除字段、改类型、改状态码），CI 契约测试失败阻断 PR
- **FR-19** 破坏性变更伴随版本（US3-4）：破坏性改动必须伴随新版本或并行提供（与 FR-28 版本升级规则联动）
- **FR-20** 兼容性 diff 自动化（US3-5）：CI 中执行 OpenAPI/契约 diff（`oasdiff` 或自研），不兼容变更红
- **FR-21** 新增可选字段不破坏（US3-6）：新增字段标记 `optional: true`，契约测试容忍缺失
- **FR-22** 弃用观察期 + 删除前确认（US3-7, US3-8）：`deprecated: true` 标记后保留观察期（默认 2 个 minor 版本）；删除字段前 CI 检查"无消费方读取"
- **FR-23** 序列化一致（US3-9）：JSON + snake_case 两侧一致，契约测试显式断言
- **FR-24** 契约验证环境隔离（US3-10）：契约验证使用独立测试容器/fixture，不依赖共享可变环境（DB/Redis 状态）

### US4 — 演进与版本化（FR-25 ~ FR-31）

- **FR-25** OpenAPI 自动生成（QF-253）+ 与实测一致（QF-254）：三个服务的 OpenAPI 3.1 由 FastAPI 自动生成；`openapi.json` 在 CI 中生成并 diff；定义与实测（集成测试 + 探针）一致
- **FR-26** OpenAPI 校验阻断（QF-255）：CI 中执行 `openapi-spec-validator` + `spectral lint`，失败阻断 PR
- **FR-27** 版本方案全局一致（QF-264）：URL 路径版本（`/v1/...`）+ `API-Version` 响应头；`docs/api-versioning.md` 文档化；跨服务一致
- **FR-28** 版本升级幅度（QF-267）：新增字段 → patch；新增端点 → minor；破坏性 → major（首期仅 minor 兼容路径）
- **FR-29** 错误码集中定义（QF-268）：错误码集中定义于 `app/core/errors.py`（每服务），跨服务全局唯一（CI 检查重名）
- **FR-30** 错误码字典（QF-269）：字典含 `code`/`http_status`/`trigger`/`remedy` 四字段，`docs/error-codes.md` 文档化
- **FR-31** 错误码映射稳定（QF-270）：错误码与 HTTP 状态码映射稳定，变更需版本升级

## Non-Goals

- **不引入 GraphQL**：保持 RESTful + JSON
- **不改变现有 RESTful 风格**：现有路由命名风格（除动词段）保留
- **不引入多版本并行**（首期）：单版本 + 向后兼容演进；破坏性变更走新版本但不同步提供两版
- **不改变认证/授权机制**：JWT/OAuth2 由 001 gatekeeper 负责
- **不改变存储/缓存方案**：DB/Redis 选型不变
- **不引入 API 网关**：路由/限流在 FastAPI 中间件层实现
- **不做前端 UI 改动**：admin-web 契约测试通过即可，不引入前端重构

## Success Criteria

- **API 语义域 P0/P1 缺陷清零**：QF-202 ~ QF-227 子集（17 项）全部从 `fail`/`pending` 转为 `pass`/`na`（有理由）
- **错误处理域 P0/P1 缺陷清零**：QF-229 ~ QF-252 子集（15 项）全部清零
- **契约测试域 P0/P1 缺陷清零**：10 项契约规则全部落地并 CI 阻断
- **演进与版本化域 P0/P1 缺陷清零**：QF-253 ~ QF-270 子集（8 项）全部清零
- **回归 0 破坏**：现有生产调用方（admin-web、chat-api 消费方）行为不变（除错误结构统一化）
- **CI 阻断生效**：契约测试、OpenAPI 校验、路径命名检查、错误码重名检查在 PR CI 中全部执行且失败阻断

## Further Details

- 技术实现（错误处理器、契约测试框架、OpenAPI 校验脚本）由 `plan.md` 承载
- 错误码字典、版本方案、限流阈值的具体取值需 `/speckit-clarify` 定值
- 与 001（gatekeeper）的关系：001 的配额维度（工具调用次数）是限流的一个维度；本特性的限流维度（IP/tenant/user/endpoint）是补充，不冲突
- 与 003（document-ingestion-delivery）的关系：003 的 document-parser API 契约是本特性契约测试的重点提供方；003 的批量解析接口是 FR-14 批量语义的覆盖对象

### 跨特性关系（被依赖方视角，2026-10-11 双向声明）

- **与 001（gatekeeper）**：001 管**权限码 + 配额维度**，本特性管**API 契约 + 错误语义**。001 的 `gatekeeper_internal` 路由（`/internal/gatekeeper/*`）是本特性契约的覆盖对象；001 的配额维度（工具调用次数）是本特性 FR-13 限流维度的输入之一。二者维度不同但概念一致（都是治理层约束）。
- **与 003（document-ingestion-delivery）**：003 的 document-parser API（上传/解析/检索）是本特性契约测试的重点提供方。003 的批量解析接口（`POST /documents/parsing/batch`）是 FR-14 批量语义的覆盖对象。003 的 `document_parsing.py` 路由需在本特性的路径命名检查（FR-1）与错误结构统一（FR-10）下整改。
- **与 008（ops-dashboard）**：本特性的错误码字典（FR-30）与限流响应（FR-13）是 008 运营看板"API 质量看板"的数据来源；008 消费 `ErrorResponse.trace_id` 做链路追踪。

## Clarify 记录（/speckit-clarify，2026-10-11）

### OQ-1 错误响应结构选择
- **决策**：采用 RFC 9457 Problem Details（`application/problem+json`）作为基础，扩展 `code`/`trace_id`/`field`/`path` 字段。
- **依据**：RFC 9457 是 IETF 标准，OpenAPI 3.1 原生支持；`application/problem+json` 媒体类型业界通用。
- **影响**：FR-10 的 `ErrorResponse` 结构对齐 RFC 9457；`docs_url` 映射 RFC 9457 的 `instance`。

### OQ-2 幂等键作用域
- **决策**：幂等键作用域 = `tenant_id + route + key_value`，作用域内键冲突返回 409，跨作用域不冲突。
- **依据**：避免不同租户/不同路由的幂等键碰撞；与 001 的多租户模型对齐。
- **影响**：FR-7 实现需引入 Redis（`idempotency:{tenant}:{route}:{key}` → 响应体缓存，TTL 24h）。

### OQ-3 批量接口整体状态码
- **决策**：首期采用 `200 + partial=true`（非 207）。
- **依据**：207 Multi-Status 浏览器/代理兼容性差；200 + 部分失败标志更通用。
- **影响**：FR-14 整体状态码规则明确为 200 + `partial` 字段。

### OQ-4 版本方案选择
- **决策**：URL 路径版本（`/v1/...`）+ `API-Version` 响应头双轨。
- **依据**：URL 版本化对消费方最直观；响应头便于网关/代理做版本路由。
- **影响**：FR-27 实现需新增 `API-Version` 中间件；现有路由迁移到 `/v1/` 前缀（破坏性，走版本升级流程）。

### OQ-5 限流维度与阈值
- **决策**：维度 = IP/tenant/user/endpoint 四级；阈值默认 IP:100/min、tenant:1000/min、user:100/min、endpoint:500/min（均可配）。
- **依据**：与 001 配额模型对齐；阈值取自审计实测的常见流量上限。
- **影响**：FR-13 实现需引入 Redis 滑动窗口限流器；阈值配置化于 `app/config/rate_limit.yaml`。
