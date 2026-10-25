# Requirements Quality Checklist: 025 api-contract-hardening

**Created**: 2026-10-12

**Feature**: [spec.md](../spec.md) | [plan.md](../plan.md)

**Purpose**: 校验 025（API 契约与语义加固）spec.md 的需求质量——完整性、清晰度、一致性、边界。这是"需求的单元测试"，**不校验实现是否正确**。

## 完整性（Completeness）

- [x] CHK001 路径资源化、状态码语义与内容协商（406/412/413/422/429，禁止 200 包裹错误）是否定义（FR-1/FR-3/FR-9）？
- [x] CHK002 未知字段全局策略（extra='ignore' 默认 / 'forbid' 严格）与载荷大小/深度/数组长度上限（10MB/16/10000，超限 413/422）是否定义（FR-4/FR-5）？
- [x] CHK003 基于 cursor 的稳定翻页 + 5 字段分页元信息（total/page/page_size/has_next/next_cursor，snake_case）是否定义（FR-6）？
- [x] CHK004 幂等键作用域（tenant+route+key，冲突 409）+ 并发保护（ETag/If-Match，冲突 412，读改写原子事务）是否定义（FR-7/FR-8）？
- [x] CHK005 统一 ErrorResponse（RFC 9457 扩展，code/message/detail/trace_id/field/path/docs_url）+ 稳定错误码枚举 + 定位信息是否定义（FR-10/FR-11）？
- [x] CHK006 不泄漏内部信息（无组件名/版本/SQL）+ 401/403 统一响应（不泄漏资源存在性）+ DEBUG 非 dev 环境强制关闭是否定义（FR-12）？
- [x] CHK007 限流（429+Retry-After+detail 含 limit/remaining/window/reset_at，维度 IP/tenant/user/endpoint）+ 批量（200+partial=true，逐项结果，上限 100）+ 降级（null+degraded=true）是否定义（FR-13/FR-14/FR-15）？
- [x] CHK008 契约测试框架（消费方定义、两侧验证、CI diff 阻断、可选字段容忍、弃用观察期 2 minor、序列化 JSON+snake_case 一致、环境隔离）是否定义（FR-16~FR-24）？
- [x] CHK009 OpenAPI 自动生成 + CI 校验阻断（openapi-spec-validator + spectral）+ 版本方案（URL /v1/ + API-Version 响应头双轨）+ 升级幅度规则 + 错误码字典（code/http_status/trigger/remedy 四字段）+ 映射稳定是否定义（FR-25~FR-31）？

## 一致性（Consistency）

- [x] CHK010 与 001 gatekeeper 关系：权限码归 001、API 契约归 025，001 配额维度（工具调用次数）作为 FR-13 限流输入，gatekeeper_internal 路由为本特性契约覆盖对象，是否声明（025↔001）？
- [x] CHK011 与 003 document-ingestion-delivery 关系：document-parser API（上传/解析/检索）为本特性契约测试重点提供方，003 批量解析接口为 FR-14 覆盖对象，document_parsing.py 路由需按 FR-1 路径命名与 FR-10 错误结构整改，是否声明（025↔003）？
- [x] CHK012 与 008 ops-dashboard 关系：本特性错误码字典（FR-30）与限流响应（FR-13）是 008 "API 质量看板"数据来源，008 消费 ErrorResponse.trace_id 做链路追踪，是否声明（025↔008）？
- [x] CHK013 5 个 Open Question 是否均已通过 Clarify 记录消解：OQ-1 错误响应采用 RFC 9457 扩展、OQ-2 幂等键作用域 tenant+route+key、OQ-3 批量 200+partial、OQ-4 版本 URL+Header 双轨、OQ-5 限流阈值 IP:100/tenant:1000/user:100/endpoint:500（Clarify OQ-1~OQ-5）？
- [x] CHK014 Non-Goals 与 4 域 FR 是否无冲突：不引入 GraphQL、不改变现有 RESTful 风格、不引入多版本并行（首期）、不改变认证/存储/网关、不做前端 UI 改动，是否与 FR-1~FR-31 矛盾（Non-Goals）？

## 边界与歧义（Edge cases & Ambiguity）

- [x] CHK015 401/403 统一响应（不泄漏资源存在性，FR-12）与限流维度（IP/tenant/user/endpoint，FR-13）在认证失败场景下是否有边界冲突或归因缺失（FR-12/FR-13）？
- [x] CHK016 批量整体状态码"全成功 200 / 全失败 4xx-5xx / 部分失败 200+partial=true"三态判定边界是否明确且与 Clarify OQ-3 决策一致（FR-14/OQ-3）？
- [x] CHK017 幂等键冲突（409，FR-7）与并发条件冲突（412，FR-8）在超时重试场景下的区分语义是否明确（FR-7/FR-8）？
- [x] CHK018 翻页稳定在插入/删除/更新三类数据变动下的 cursor 边界是否明确，且"基于 cursor 的稳定翻页"是否足够约束验收（FR-6/QF-213）？

## US3/US4 演进需求（2026-10-25 追加，随实现闭环回填）

> CHK019–CHK025 是对 CHK008/CHK009 的**落地细化**：把契约测试、OpenAPI 自动生成、版本化与错误码字典从"已定义"推进到"已具备可执行的验收命令与门禁"，构成 `/speckit-implement` 的最终拦截面。

- [x] CHK019 契约是否已实际生成三份（`contracts/admin-api.yaml` 46 interactions / `chat-api.yaml` 63 / `document-parser.yaml` 10），且每条含 `id`/`method`/`path`/`consumers[]`/`responses`/`error_codes`/`notes`，并通过 `tools/contract/validate.py --all`（FR-16）？
- [x] CHK020 消费方侧证据是否可自动核验（`tools/contract/consumer_refs.py --all` 扫描 `.ts`/`.vue` 源码，版本无关匹配契约 path；无调用证据且契约未标注零消费方的项必须报 error）（FR-16/FR-17）？
- [x] CHK021 提供方侧是否用 OpenAPI 结构级测试验证每条契约 interaction 存在、状态码/字段/错误码注册表与提供方一致（`services/admin-api/tests/contract/test_admin_api.py`，FR-17/FR-18/FR-29），并已修复 3 处 `/api/api/*` 双重前缀与 `items↔data` 字段断裂？
- [x] CHK022 OpenAPI 是否由代码自动生成（`tools/openapi/generate.py --all --check`，CI diff 阻断），且三份 artifact 均通过 `openapi-spec-validator` + 内置 lint（FR-25/FR-26）；chat-api 已修复 `required` 重复 `tenantId` 与 default 空串违反 `minLength`？
- [x] CHK023 版本方案是否具备可执行三要素——URL 主版本（三服务迁 `/api/v1`，T045）、响应头小版本（`ApiVersionMiddleware` 写 `API-Version: 1.0.0`，T044）、旧路径兼容（`LegacyApiRedirectMiddleware`：GET/HEAD 301、其他方法 308 保留方法，避免写操作被转成 GET 丢失），口径落在 `docs/api-versioning.md`（FR-27/FR-28）？
- [x] CHK024 错误码字典是否已跨服务汇总为唯一权威（`docs/error-codes.md`，通用 15 码 `api.*` + 业务码登记表），并具备**映射稳定性门禁**（`tools/api_check/error_code_mapping.py`：与基线快照比对，`changed_status_semantics` 变更须 major 升级；跨服务唯一由 `tools/api_check/error_codes_uniqueness.py` 保证）（FR-30/FR-31/QF-270）？
- [x] CHK025 CI 是否已装配 `api-contract-hardening` job，串起 path_naming → error_codes_uniqueness → error_code_mapping → contract validate → contract diff → openapi generate+validate → deprecation_check → consumer_refs 全链路（T048，`quality-gate.yml`）？

## Notes

- 本清单为需求质量门禁；CHK 检查项与 spec.md FR 双向对齐，构成 `/speckit-implement` 拦截。
- 标记 `[x]` 仅代表"需求质量达标"，不代表实现完成；实现状态以 tasks.md 勾选状态与 QualityForge 审计回写为准。
- 本特性的首个可独立验证切片为 Phase 1 + Phase 3（统一 ErrorResponse + 错误码注册表 + 限流中间件 + 批量语义），覆盖 api-errors 域全部实测 fail 项，可在 US3/US4 落地前独立交付。
- 跨特性双向声明（2026-10-11）已完成，001/003/008 三个被依赖方关系已声明一致，CHK010–CHK012 可确认无遗漏。
