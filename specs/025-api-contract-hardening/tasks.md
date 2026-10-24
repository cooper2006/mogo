# Tasks: API Contract & Semantics Hardening

**Input**: Design documents from `/specs/025-api-contract-hardening/`

**Prerequisites**: plan.md (required), spec.md (required)

**Clarify Decisions (governing tasks, 2026-10-11)**:
- 错误响应结构：**RFC 9457 Problem Details 扩展**（`code`/`trace_id`/`field`/`path`/`docs_url`），媒体类型 `application/problem+json`。
- 幂等键作用域：**`tenant + route + key`**，Redis 缓存 TTL 24h。
- 批量状态码：**200 + `partial=true`**（非 207）。
- 版本方案：**URL 路径 `/v1/` + `API-Version` 响应头双轨**。
- 限流阈值：IP:100/min、tenant:1000/min、user:100/min、endpoint:500/min（均可配）。

**Checklist Gate**: `checklists/requirements.md` 未勾选项构成 `/speckit-implement` 拦截门禁；本任务文件仅规划，不修改 checklist 标记。

**Organization**: 任务按用户故事分组，每组可独立实现与测试；`[P]` 标记可并行任务。

**⚠️ 审计实测 fail 提示**:
- **api-semantics 域**：QF-202（路径动词段）、QF-204（状态码语义错误）、QF-210（未知字段策略分裂）、QF-213（翻页重复）、QF-218（PUT 非幂等）等为**实测 fail**，修复必须以实测为准，不能只补文档。
- **api-errors 域**：QF-229（错误结构分裂）、QF-230（无稳定错误码）、QF-234（错误信息泄漏内部组件）、QF-237（超配额返回 5xx）等为**实测 fail**，修复必须以实测为准。
- **api-contracts 域**：全 `pending`（无契约测试框架），本特性从零搭建。
- **api-evolution 域**：全 `pending`（无 OpenAPI CI 校验），本特性从零搭建。

---

## Phase 1: Setup (基础设施 — 被 US1/US2/US3 复用)

**Goal**: 建立错误码注册表、统一 `ErrorResponse` 结构、`trace_id` 中间件——US1/US2/US3 的共同载体。

- [x] T001 [P] 创建 `services/admin-api/app/core/errors.py`：错误码注册表（Python Enum + 字典）+ `ErrorResponse` Pydantic 模型（RFC 9457 扩展），定义 `code`/`message`/`detail`/`trace_id`/`field`/`path`/`docs_url` 字段
- [x] T002 [P] 创建 `services/admin-api/app/core/errors_codes.md`：错误码字典（每服务独立，含 `code`/`http_status`/`trigger`/`remedy` 四字段）
- [x] T003 创建 `services/admin-api/app/core/error_handler.py`：统一异常处理器（`HTTPException` + `RequestValidationError` + `Exception` → `ErrorResponse`），注册到 FastAPI app
- [x] T004 [P] 创建 `services/admin-api/app/middleware/trace_id.py`：`trace_id` 注入中间件（从 `X-Trace-ID` 头或生成 UUID，写入响应 `ErrorResponse.trace_id` + 日志上下文）
- [x] T005 [P] 同步 T001-T004 到 `services/chat-api/app/core/`（`errors.py` + `errors_codes.md` + `error_handler.py` + `middleware/trace_id.py`）
- [x] T006 [P] 同步 T001-T004 到 `services/document-parser/app/core/`（`errors.py` + `errors_codes.md` + `error_handler.py` + `middleware/trace_id.py`）
- [x] T007 跨服务错误码重名检查脚本：`tools/api_check/error_codes_uniqueness.py`，CI 执行（FR-29）

**关键依赖**: T001-T004 被 US1/US2/US3 全部复用；T005/T006 是 T001-T004 的跨服务同步。

---

## Phase 2: User Story 1 (P1) — API 语义规范

**Goal**: 路径资源化、状态码语义、幂等/并发保护、分页稳定、内容协商。
**独立测试**: 路径命名检查 CI 通过；状态码语义单测通过；PUT 重复调用幂等；并发 PUT 返回 412；翻页稳定；不支持 Accept 返回 406。

**修复优先级**: 审计实测 fail 项（QF-202, 204, 210, 213, 218）优先修复。

- [ ] T008 创建 `tools/api_check/path_naming.py`：路径命名检查脚本（扫描所有路由，检测动词段 `get/list/create/update/delete/do`，输出违规清单）（FR-1, QF-202）
- [ ] T009 整改 `services/admin-api/app/api/routes/` 下动词段路径（实测 fail QF-202）：如 `/getUsers` → `/users`、`/listDocuments` → `/documents`；保留向后兼容别名（旧路径返回 301 重定向到新路径）
- [ ] T010 整改 `services/document-parser/app/api/routes/` 下动词段路径（QF-202）：如 `/parseDocument` → `/document-parsing`
- [ ] T011 [P] 状态码语义修复（QF-204, QF-207）：扫描 `services/*/app/api/routes/` 所有路由，把"200 包裹错误"改为语义正确状态码（4xx/5xx）；成功路径返回 200/201/204；重定向 301/302；缓存 304
- [ ] T012 未知字段策略统一（QF-210）：全局 Pydantic 配置 `model_config = ConfigDict(extra='ignore')`（默认）；严格 schema 显式声明 `extra='forbid'`；扫描 `services/*/app/schemas/` 所有 schema 文件确保一致
- [ ] T013 [P] 创建 `services/admin-api/app/middleware/payload_limit.py`：载荷大小/深度/数组长度限制中间件（FR-5, QF-211）；超限返回 413/422
- [ ] T014 创建 `services/admin-api/app/config/payload_limits.yaml`：载荷限制配置（大小 10MB/深度 16/数组 10000，可配）
- [ ] T015 [P] 创建 `services/admin-api/app/core/idempotency.py`：幂等键中间件（FR-7, QF-218, QF-219, QF-220）；支持 `Idempotency-Key` 头；Redis 缓存 `idempotency:{tenant}:{route}:{key}` → 响应体，TTL 24h；冲突返回 409
- [ ] T016 [P] 创建 `services/admin-api/app/core/etag.py`：ETag/If-Match 条件请求中间件（FR-8, QF-221, QF-222, QF-223, QF-224）；PUT 支持 ETag；冲突返回 412；读改写走原子事务
- [ ] T017 [P] 创建 `services/admin-api/app/api/pagination.py`：统一分页 schema + cursor 翻页助手（FR-6, QF-213, QF-216）；分页响应含 `total`/`page`/`page_size`/`has_next`/`next_cursor`（5 字段，snake_case）
- [ ] T018 整改 `services/admin-api/app/api/routes/knowledge_documents.py` 等分页路由：使用 T017 统一分页 schema；基于 cursor 的稳定翻页
- [ ] T019 [P] 创建 `services/admin-api/app/middleware/content_negotiation.py`：内容协商中间件（FR-9, QF-225, QF-227）；不支持 Accept 返回 406 + `Vary: Accept`；`Accept-Encoding` 按声明生效
- [ ] T020 US1 集成测试：`services/admin-api/tests/api/test_semantics.py`（路径命名、状态码、幂等、并发、分页、内容协商 6 组 Acceptance）

---

## Phase 3: User Story 2 (P1) — 错误处理规范

**Goal**: 统一错误响应结构、稳定错误码、不泄漏内部信息、限流语义、批量语义、降级空值。
**独立测试**: 错误结构统一；错误码稳定；401/403 不泄漏资源存在性；429 + `Retry-After`；批量逐项结果；降级空值语义明确。

**修复优先级**: 审计实测 fail 项（QF-229, 230, 234, 237）优先修复。

- [ ] T021 错误结构统一化（FR-10, QF-229, QF-232）：扫描 `services/*/app/api/routes/` 所有错误响应，改为引用 T001 的 `ErrorResponse` schema；OpenAPI 中所有错误响应引用 `ErrorResponse`
- [ ] T022 稳定错误码 + 定位信息（FR-11, QF-230, QF-231）：扫描所有错误响应，确保 `code` 字段使用 T001 注册表的稳定枚举；错误体含 `trace_id`（T004 注入）、`field`（字段级）、`path`（JSONPath）
- [ ] T023 不泄漏内部信息（FR-12, QF-234, QF-235, QF-236）：扫描所有错误信息，移除内部组件名/版本号/文件路径/SQL；401/403 统一响应（不区分"用户不存在"vs"密码错"）；`DEBUG` 在非 dev 环境强制关闭
- [ ] T024 [P] 创建 `services/admin-api/app/middleware/rate_limit.py`：限流中间件（FR-13, QF-237, QF-238, QF-239, QF-240）；Redis 滑动窗口；超配额返回 429 + `Retry-After` 头；`detail` 含 `limit`/`remaining`/`window`/`reset_at`
- [ ] T025 [P] 创建 `services/admin-api/app/config/rate_limit.yaml`：限流维度与阈值配置（IP:100/min、tenant:1000/min、user:100/min、endpoint:500/min）
- [ ] T026 创建 `docs/rate-limiting.md`：限流维度与阈值文档（FR-13, QF-240）
- [ ] T027 批量语义（FR-14, QF-245, QF-247, QF-248）：扫描 `services/admin-api/app/api/routes/knowledge_documents.py` 等批量接口，响应含逐项结果数组 + 整体 `status` + `partial` 字段；批量大小上限 100，超限返回 422
- [ ] T028 降级空值语义（FR-15, QF-252）：扫描所有降级场景，返回 `null` + `degraded: true` 元信息，不返回误导性空数组/空对象
- [ ] T029 [P] 错误处理集成测试：`services/admin-api/tests/api/test_errors.py`（错误结构、错误码、不泄漏、限流、批量、降级 6 组 Acceptance）

---

## Phase 4: User Story 3 (P1) — 契约测试

**Goal**: 契约由消费方定义 + 两侧验证 + CI diff 阻断 + 兼容性检查自动化。
**独立测试**: 契约测试 CI 执行；不兼容改动阻断；新增可选字段不破坏；弃用字段观察期。

- [ ] T030 [P] 创建 `specs/025-api-contract-hardening/contracts/admin-api.yaml`：admin-api 契约文件（Pact 风格 YAML，含路径/方法/请求/响应/错误码/状态码）
- [ ] T031 [P] 创建 `specs/025-api-contract-hardening/contracts/chat-api.yaml`：chat-api 契约文件
- [ ] T032 [P] 创建 `specs/025-api-contract-hardening/contracts/document-parser.yaml`：document-parser 契约文件（重点提供方，含 003 的批量解析接口契约）
- [ ] T033 创建 `tools/contract/validate.py`：契约验证脚本（FR-16 ~ FR-24）；消费方定义契约，两侧验证（提供方测试 + 消费方测试）；覆盖实际依赖字段/状态码/错误码
- [ ] T034 创建 `tools/contract/diff.py`：兼容性 diff 脚本（FR-20, US3-5）；OpenAPI/契约 diff，不兼容变更红
- [ ] T035 契约测试用例：`services/admin-api/tests/contract/test_admin_api.py`（提供方侧验证）
- [ ] T036 契约测试用例：`services/admin-web/tests/contract/test_admin_api.py`（消费方侧验证，如 admin-web 有测试目录）
- [ ] T037 弃用字段观察期检查：`tools/contract/deprecation_check.py`（FR-22, US3-7, US3-8）；扫描契约文件 `deprecated: true` 标记，检查观察期（2 个 minor 版本）后才允许移除
- [ ] T038 序列化一致性测试（FR-23, US3-9）：契约测试显式断言 JSON + snake_case
- [ ] T039 契约验证环境隔离（FR-24, US3-10）：契约测试使用独立测试容器/fixture，不依赖共享可变环境

---

## Phase 5: User Story 4 (P1) — API 演进与版本化

**Goal**: OpenAPI 自动生成 + 校验 + CI 阻断；版本方案全局一致；错误码集中管理。
**独立测试**: OpenAPI CI 生成并 diff；校验失败阻断；版本方案文档化；错误码字典含触发条件与处理建议。

- [ ] T040 [P] 创建 `tools/openapi/generate.py`：OpenAPI 生成脚本（FR-25, QF-253）；三个服务的 OpenAPI 3.1 由 FastAPI 自动生成；输出 `openapi.json` 到 CI artifact
- [ ] T041 [P] 创建 `tools/openapi/validate.py`：OpenAPI 校验脚本（FR-26, QF-255）；执行 `openapi-spec-validator` + `spectral lint`，失败阻断 PR
- [ ] T042 [P] 创建 `docs/api-versioning.md`：版本方案文档（FR-27, FR-28, QF-264, QF-267）；URL 路径 `/v1/` + `API-Version` 响应头双轨；版本升级幅度规则
- [ ] T043 [P] 创建 `docs/error-codes.md`：错误码字典文档（FR-30, QF-269）；跨服务汇总所有错误码，含 `code`/`http_status`/`trigger`/`remedy` 四字段
- [ ] T044 创建 `API-Version` 中间件：`services/admin-api/app/middleware/api_version.py`（FR-27, QF-264）；注入 `API-Version` 响应头
- [ ] T045 路由迁移到 `/v1/` 前缀（FR-27, QF-264）：扫描 `services/*/app/api/routes/`，添加 `/v1` 路由前缀；旧路径保留向后兼容（301 重定向）
- [ ] T046 错误码映射稳定性检查（FR-31, QF-270）：CI 检查错误码与 HTTP 状态码映射变更，需版本升级
- [ ] T047 OpenAPI 与实测一致性检查（FR-25, QF-254）：CI 中执行探针验证 OpenAPI 定义中的路径/参数/响应与实测一致

---

## Phase 6: CI 接入 & Polish

- [ ] T048 [P] 更新 `.github/workflows/quality-gate.yml`：新增 job `api-contract-hardening`，执行：
  - `tools/api_check/path_naming.py`（路径命名检查，FR-1）
  - `tools/api_check/error_codes_uniqueness.py`（错误码重名检查，FR-29）
  - `tools/contract/validate.py`（契约测试，FR-16 ~ FR-24）
  - `tools/contract/diff.py`（兼容性 diff，FR-20）
  - `tools/openapi/generate.py` + `tools/openapi/validate.py`（OpenAPI 生成 + 校验，FR-25, FR-26）
  - `tools/contract/deprecation_check.py`（弃用字段观察期，FR-22）
- [ ] T049 [P] 创建 `specs/025-api-contract-hardening/checklists/requirements.md`：需求质量门禁（CHK 检查项，`/speckit-implement` 拦截）
- [ ] T050 写 `quickstart.md`（本特性的启用 + 验证步骤）
- [ ] T051 [P] 错误码字典跨服务汇总：`docs/error-codes.md`（FR-30，T043 的详细版，含三个服务所有错误码）
- [ ] T052 [P] QualityForge 审计回写：50 个 QF 项状态从 `fail`/`pending` 转为 `pass`/`na`（有理由），回写到 `.qualityforge/audit.json`

---

## Dependencies

```text
Phase 1 (基础设施：错误码 + ErrorResponse + trace_id) → Phase 2 (US1 语义) + Phase 3 (US2 错误)
Phase 2 + Phase 3 → Phase 4 (US3 契约测试)
Phase 4 → Phase 5 (US4 演进)
Phase 5 → Phase 6 (CI 接入 & Polish)
关键依赖: T001-T004 被 US1/US2/US3/US4 全部复用；T030-T032 契约文件被 T033-T039 复用；T040-T041 OpenAPI 工具被 T048 CI 复用
```

## Parallel Opportunities

- **Phase 1**: T001-T004 可并行（三个服务同步）；T005/T006 可并行
- **Phase 2**: T011（状态码扫描）可与其他任务并行；T013/T015/T016/T017/T019 互不依赖可并行
- **Phase 3**: T024/T025（限流）互不依赖可并行；T029 测试可独立
- **Phase 4**: T030/T031/T032（契约文件）可并行；T035/T036（两侧测试）可并行
- **Phase 5**: T040/T041/T042/T043 互不依赖可并行
- **Phase 6**: T048/T049/T051 可并行

## MVP Scope

- **最小可交付 = Phase 1 + Phase 3**（T001-T007 + T021-T029）：统一错误响应结构 + 错误码注册表 + 限流 + 批量语义——**api-errors 域实测 fail 项全部清零**。
- 增量交付：US1（语义，含实测 fail 修复）→ US3（契约测试）→ US4（演进）。

## Implementation Strategy

- **先 MVP（US2 错误处理）**：因为审计实测 fail 项集中在 api-errors 域（QF-229, 230, 234, 237），且 US2 不依赖契约测试框架，可独立交付
- **再 US1（语义）**：修复 api-semantics 域实测 fail 项（QF-202, 204, 210, 213, 218）
- **再 US3（契约测试）**：从零搭建契约测试框架
- **最后 US4（演进）**：OpenAPI 校验 + 版本方案
- 每故事完成即独立可测（Acceptance Scenarios 即测试基准）
- 实测 fail 项优先修复，不能只补文档

## Notes

- 本 tasks.md 为 `/speckit-tasks` 产出，含 025 的 clarify 决策（RFC 9457 错误结构、幂等键作用域、批量 200+partial、URL+Header 双轨版本、限流阈值）。
- **api-semantics 和 api-errors 两域有实际 fail 项**，修复必须以实测为准（不能只补文档）。
- 实现需先通过 `checklists/requirements.md` 门禁；CHK 检查项需与 spec.md FR 双向对齐。
- **实现进展（2026-10-24）**：Phase 1 T001–T007 已落地——三服务各自新增 `app/core/errors.py`（错误码注册表 + `ErrorResponse` + `build_error_payload`）、`app/core/error_handler.py`（接管 422/500；路由级 `HTTPException` 形状不动，属 T011 范围）、`app/middleware/trace_id.py`（`X-Trace-ID` 沿用/生成 + 响应头回写）、`app/core/errors_codes.md`（四字段字典）；`tools/api_check/error_codes_uniqueness.py` 已接入 `.github/workflows/quality-gate.yml`（backend-quality，admin-api 单次执行）。兼容口径：错误体并存 `detail`（字符串，前端既有消费）/`message`（chat-api envelope）/RFC 9457 键（type/title/status/instance），结构化 detail 移至 `error_detail`；chat-api 旧数值 code 按 FR-11 废弃为字符串稳定码，SSE 流内帧不受影响。验证：admin-api 全量 pytest 通过（含新增 `tests/test_error_contract_phase1.py` 14 项）、chat-api 全量通过、document-parser 全量通过、check_python_static 三服务门禁通过、uniqueness 脚本 OK。
- 跨服务错误码重名检查（T007）需在三个服务都完成后执行。
- 契约测试（T033-T039）需三个服务的 OpenAPI 生成（T040）后才能完整执行。
