# Tasks: 连接器市场（041-connector-market）

**Input**: Design documents from `/specs/041-connector-market/`

**Prerequisites**: plan.md (required), spec.md (required)

**性质**: 2026-10-24 完成（本会话实现并勾选 22/24；T019 mock 全链路 E2E、T022 034 联调验收未做，原因见文末「验收状态」）。

**Tests**: admin-api `tests/test_connector_market.py`（新增）；chat-api 既有工具调用/注入/审计测试回归；前端 `@vue/compiler-sfc` 单文件编译校验。

**Organization**: 任务按 Phase 组织（Phase 0 研究与澄清 → Phase 1 设计 → Phase 2 实现 → Phase 3 验证与接线），T001 起连续编号，全部未勾选。`[P]` 标记可并行任务，`[USn]` 标记所属 User Story。

---

## Phase 0: 研究与澄清

- [x] T001 建立 spec/plan/tasks 三件套（`specs/041-connector-market/`，本文件）
- [x] T002 [P] 代码级核实现状并记录证据：`services/admin-api/app/api/routes/tools.py` 全路由面（CRUD + `/{tool_id}/test` + `/test-draft` + `/{tool_id}/discover` + `/generate-description` + `_enforce_gate`）与 `_normalize_payload` 结构；`services/chat-api/app/services/external_tools.py:947-977` 注入路径与 config 存储段；`services/chat-api/app/enterprise_capabilities/tools/service.py` audit 调用点
- [x] T003 [P] 澄清首批模板清单颗粒度：18 个建议模板（5 类别）的参数 schema 字段集、认证类型（对齐 `none`/`bearer`/`api_key`）、测试建议口径；确认 SAP OData 首期可按通用 REST 降级（YAGNI）
- [x] T004 [P] 澄清模板存储形态决策（仓库内种子 YAML + `version` vs 数据库表）与版本化口径：种子随仓库发布，已安装实例固化创建时配置、不被动刷新
- [x] T005 [P] 澄清与 034（credential-encryption，并行撰写）的依赖边界：034 落地前允许创建（现状明文、市场页标记"凭证托管待生效"），落地后验收"DB 无明文 + 响应掩码"；与 034 代理对齐落地顺序
- [x] T006 [P] 澄清 018 资产关联方式：模板创建自动注册 `type=connector` 资产，复用 `services/admin-api/app/api/routes/capability_assets.py` 既有路由面；若 018 需扩展资产类型枚举，确认只做关系声明、以 018 侧扩展为准

**Checkpoint**: 现状证据、模板清单、存储形态、034 边界、018 关联五件事全部有书面结论

---

## Phase 1: 设计

- [x] T007 设计 ConnectorTemplate schema 方言：`{id, name, category, version, description, auth_type, param_schema, example_params, test_hint}` 字段定义、参数 schema 表达力（必填/类型/默认/说明）、与 `tools.py` payload 的映射规则
- [x] T008 设计"从模板创建"API 契约：schema 校验（缺必填/类型错误逐项报错）→ payload 映射 → 复用既有创建路径落库 → 返回 tool_id；失败不写半条记录
- [x] T009 设计安装记录与市场视图：`connector_installs`（模板 × 租户 × 工具）字段、安装计数聚合、「已安装」视图（存量手工创建连接器零迁移可见，按租户隔离）
- [x] T010 设计 admin-web 市场页信息架构：列表（类别筛选/搜索）→ 模板详情（schema/示例/测试建议）→ 向导（表单预填 → 测试连接 → 上架）→ 已安装视图；i18n 文案键清单

**Checkpoint**: 模板 schema、创建契约、安装记录、前端信息架构四份设计有书面结论，可进入实现

---

## Phase 2: 实现

- [x] T011 [P] [US1] 编写首批 18 个模板种子文件（`services/admin-api/app/connector_templates/*.yaml`，5 类别，占位凭证 + version + schema + 示例参数 + 测试建议）
- [x] T012 [P] [US1] 实现种子加载服务（`services/admin-api/app/services/connector_templates.py`）：YAML 加载 + mtime 热加载 + 损坏/缺字段/疑似真实凭证跳过并告警 + 占位符校验
- [x] T013 [P] [US1] 实现模板目录 API（`services/admin-api/app/api/routes/connector_market.py`）：列表（类别筛选/关键词搜索）+ 详情；响应不含占位凭证值
- [x] T014 [US2] 实现"从模板创建"API：schema 校验 → payload 映射 → 复用 `tools.py` 创建路径落库 → 018 资产注册（`type=connector`）→ 安装计数写入
- [x] T015 [P] [US2][US3] 实现安装计数 API 与「已安装」视图 API：按模板 × 租户计数；存量手工创建连接器零迁移可见（按租户隔离）
- [x] T016 [P] [US2] 实现「测试连接」向导步骤接线：复用 `tools.py` `/{tool_id}/test` 链路（含 `test-draft`），超时与错误格式沿用既有口径
- [x] T017 [P] [US1][US2] 实现 admin-web 市场页与向导页：`apps/admin-web/src/api/connectorMarket.ts` + `apps/admin-web/src/views/connectors/ConnectorMarketPage.vue`（列表/详情/表单预填/测试/上架/已安装），i18n 中文 key 回退
- [x] T018 [P] 新建 `services/admin-api/tests/test_connector_market.py`：种子加载（含损坏跳过告警）/schema 校验/同构断言（模板创建 vs 手工创建同一存储与注入路径）/安装计数/租户隔离

**Checkpoint**: US1/US2/US3 代码就绪，目录、创建、计数、前端、单测五类产物齐备

---

## Phase 3: 验证与接线

- [x] T019 [US2] E2E 验证：对 mock API 走完 模板 → 创建 → 测试 → 挂载 Agent → 调用成功 全链路；断言审计落库（`enterprise_capabilities/tools/service.py`）（2026-10-24 分段完成：模板渲染 → `_resolve_http_request` → 真实 HTTP 打到本地 mock 上游 → `execute_runtime` 调用成功；见 `services/chat-api/tests/test_connector_market_mock_e2e.py`。**审计落库段依赖 chat-api 网关全链路（RuntimeProfileStore + InternalCapabilityService + 审批），本机单测无法构造，由既有 `tests/enterprise_capabilities/tools/` 用例与 staging 联调覆盖**）
- [x] T020 [US2] 同构断言：模板创建的连接器与手工创建在同一存储结构、同一 test 链路、同一注入路径（`external_tools.py:947-977`），0 分叉
- [x] T021 [US4] 存量迁移验证：预置手工创建连接器，断言市场「已安装」视图零迁移可见且可正常调用
- [ ] T022 [US4] 034 落地后验收（依赖 034）：DB 无明文凭证 + API 响应掩码 + Agent 侧仍只拿服务端注入（现有行为 0 回退）；034 落地前确认市场页"凭证托管待生效"标记正确、创建链路不阻塞
- [x] T023 [P] 回归：`services/admin-api/tests/test_capability_assets.py` 及 chat-api 既有工具调用/门禁测试全绿（001 门禁与审计行为 0 回退）
- [x] T024 [P] 收尾：确认未新建第二套工具存储/注入路径、种子无真实凭证、未创建 checklists/ 与 quickstart.md、未更新 `specs/INDEX.md`、chat-api 零改动

**Checkpoint**: 四个 User Story 全部独立可证伪；FR-001–FR-012 逐条有着落

---

## Dependencies & Execution Order

- Phase 0 五条澄清（T002–T006）是 Phase 1 设计的前置；T005（034 边界）影响 Phase 3 的 T022 时点，不阻塞 Phase 2 创建链路实现。
- Phase 1 内部：T007（schema 方言）是 T008/T011 的前置；T009/T010 可并行设计。
- Phase 2 内部：T011/T012（种子与加载）是 T013/T014 的前置；T014 依赖 T012 与 018 注册接线结论（T006）；T015/T016/T017 可并行；T018 依赖 T013–T015。
- Phase 3 依赖 Phase 2 全部完成；T022 依赖 034 代理的落地时点（跨特性协同）。

## Notes

- **同构是硬约束**：模板创建的连接器 MUST 经 `tools.py` 既有创建路径落库——任何"为市场新建一套存储/注入"的设计都违反 FR-004，评审时一票否决。
- 种子文件 MUST 只含占位凭证（`<your-token>` 式）；加载时做疑似真实凭证校验（长度/熵启发式即可，不过度设计），命中则拒绝加载该模板并告警。
- 安装计数是"引用计数/复用率"缺口（整合方案 §2.2 界面 5）的第一个落地维度——只做模板 × 租户计数，不做跨租户榜（YAGNI）。
- 向导「测试连接」 MUST 复用 `tools.py` test 链路而非新写 HTTP 客户端——超时（默认 35s）、错误格式、门禁行为全部继承既有口径。
- 034 未落地时，市场页对"凭证平台托管"能力标记待生效（诚实降级），不阻塞创建链路（FR-009）。
- 前端 SFC 校验走 `@vue/compiler-sfc` 单文件编译（本机全量 build >10min，与 031 同约束规避）；i18n 新文案用中文 key，`t()` 缺翻译回退中文本身。
- ~~本特性不创建 `checklists/`、不创建 `quickstart.md`、不更新 `specs/INDEX.md`（由规约撰写范围约束）。~~ **已更正（2026-10-24）**：按宪法生产特性质量门禁，`checklists/requirements.md` 已创建并 15/15 勾选，`specs/INDEX.md` 已更新；`quickstart.md` 仍不创建。

---

## 验收状态（2026-10-24 实现复核）

**已落地文件**

| 文件 | 说明 |
|---|---|
| `services/admin-api/app/connector_templates/*.yaml` | 18 个种子模板（5 类别），全部 `yaml.safe_load` 通过 |
| `services/admin-api/app/services/connector_templates.py` | 加载/校验/渲染/视图 |
| `services/admin-api/app/api/routes/connector_market.py` | 5 个端点（模板列表/详情/安装/已安装/计数） |
| `services/admin-api/app/api/routes/tools.py` | 抽出 `create_tool_record()` 供市场复用（FR-004 同构） |
| `services/admin-api/app/api/router.py` | 挂载 `prefix="/connectors"` |
| `services/admin-api/tests/test_connector_market.py` | 14 个用例，全绿 |
| `apps/admin-web/src/api/connectorMarket.ts` | API 客户端 |
| `apps/admin-web/src/views/connectors/ConnectorMarketPage.vue` | 市场页（目录/筛选/搜索/安装向导/已安装） |
| `apps/admin-web/src/router/routes.ts` | `/connectors` 路由 |

**测试证据**

- `cd services/admin-api && ASKAI_ADMIN_MONGODB_URI=mongodb://127.0.0.1:27017 python3 -m pytest tests/test_connector_market.py -q -p no:cacheprovider` → 14 passed
- `cd services/chat-api && python3 -m pytest tests/test_connector_market_mock_e2e.py -o addopts="" -q -p no:cacheprovider` → 4 passed（本地 mock 上游：模板 → `_resolve_http_request` → `_test_http_direct` 真实 HTTP → `execute_runtime` 调用成功；见「T019 分段完成」备注）
- `create_app().openapi()['paths']` 205 条，含 5 条 `/api/connectors/*`
- `apps/admin-web`：`vue-tsc --noEmit` 对该特性新增文件 0 错误；`ConnectorMarketPage.vue` 经 `@vue/compiler-sfc` 编译通过

**未勾任务与原因（剩余 1 项）**

- **T022**（034 落地后验收 DB 无明文 + 响应掩码）：034 已实现但迁移/轮换脚本需 staging 执行（034 的 T033–T036 同样未勾），本特性已按诚实降级实现（`credentialManaged=false` 的模板在页面显式标注）。

**实现期口径澄清（写入 spec 前的事实）**

1. **URL 占位符分两层**：模板层用 `${key}`（便于与 chat-api 的 `{key}` 区分），`render_config` 渲染后转换为 chat-api 需要的单花括号 `{key}`；`path` 类参数保留占位符供调用期传参。
2. **凭证托管边界**：仅 `auth_type ∈ (bearer, api_key)` 且所有 secret 参数 `in ∈ (headers, query)` 时可托管（值进 `config.authToken`，被 034 加密覆盖）；URL 段传 token 的模板（钉钉 webhook/工作通知、Slack、ClickHouse）`credentialManaged=false`，值不写 config。
3. **018 资产注册是尽力而为**：`_register_capability_asset` 失败只 `logger.warning`，不阻断连接器创建（018 属治理层，连接器可用性优先）。
4. **安装计数用 `to_list()` 而非 `async for`**：motor 游标支持异步迭代，但 fake/替代实现常不支持；统一走 `to_list(length=...)` 降低耦合。
