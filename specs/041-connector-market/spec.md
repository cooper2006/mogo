# Feature Specification: 连接器市场（预置模板目录 + 从模板创建 + 凭证托管依赖）

**Feature Branch**: `041-connector-market`

**Created**: 2026-10-23

**Status**: Draft

**Input**: User description: "把现有租户级 HTTP/MCP 工具连接升级为'连接器市场'形态——预置连接器目录（OA/ERP/数据平台常见 API 模板）+ 自定义连接器快速接入模板 + 凭证平台托管；文章口径'42 个开箱即用、自定义 30 分钟接入'，但数量不承诺"

> **设计来源**：本规约落地《docs/MOGO-AgentOS整合方案.md》§4.10（连接器市场，对应文章界面 7，见整合方案 §2.2 与 §6.2）。整合方案基线：31 个 SDD 特性（specs/001–031）+ 代码级核实（2026-10-23）。
>
> **性质说明**：**全新特性，代码尚未开工**——现有租户级工具连接（`tools.py` CRUD + `external_tools` 注入）已存在但无预置连接器目录、无市场页；本文件为 spec → plan → tasks 先行，后续按 tasks.md 实现。

## 定位（一句话）

把现有"租户级 HTTP/MCP 工具连接"升级为"连接器市场"形态：**仓库内种子模板目录**（首批 10–20 个常见系统 API 模板，含参数 schema/描述/示例参数）→ admin-web「从模板创建」向导（选模板 → 填参数 → 测试连接 → 上架）→ 落**既有工具存储与注入路径**（与手工创建同构）→ 自动注册为 018 能力资产（`type=connector`）并计安装计数；凭证存储加密**依赖 034（credential-encryption，并行撰写，只做关系声明）**。

## 背景事实（代码级核实，2026-10-23）

| 事实 | 证据 |
| --- | --- |
| 租户自助注册的企业工具连接已存在（CRUD + 测试 + 发现 + 描述生成 + 门禁） | `services/admin-api/app/api/routes/tools.py`（`GET/POST ""`、`/{tool_id}` CRUD、`/{tool_id}/test`、`/test-draft`、`/{tool_id}/discover`、`/generate-description`、`_enforce_gate`） |
| Agent 侧凭证服务端注入、明文拿不到 | `services/chat-api/app/services/external_tools.py:947-977`（bearer/api_key 注入 + runtime identity headers 最后应用、不可伪造） |
| 但存储侧凭证明文（034 修复对象） | `services/chat-api/app/services/external_tools.py` config 段（整合方案附录 B：`app/security/encryption.py`、`kms.py` 已实现但零生产调用方） |
| 调用全程可审计 | `services/chat-api/app/enterprise_capabilities/tools/service.py`（创建/测试/执行/拦截全程 `_repository.audit(...)`） |
| 无预置连接器目录 | specs 中仅 `specs/014-business-semantic-index/plan.md:48` 规划过 `connectors/` 目录（未落地）；前端无市场页（`apps/admin-web/src/views/` 无 connectors 目录） |
| 018 能力资产注册已具备路由面 | `services/admin-api/app/api/routes/capability_assets.py`（`/discover`、列表、详情、`/contract`、`/state`、`/owner`、`/a2a-exposed`） |

## 已定决策（2026-10-23）

| # | 决策点 | 结论 | 落点 |
| --- | --- | --- | --- |
| 1 | 模板存储形态 | **仓库内种子文件（YAML，每模板一个文件，带 `version` 字段）+ 版本化**——首批人工维护、随仓库发布走；**不建数据库表**（模板是平台方资产，非租户数据；数据库化留后） | `services/admin-api/app/connector_templates/*.yaml` |
| 2 | 首批范围 | **10–20 个常见系统模板**（建议清单 18 个、5 类别见 plan.md）；**数量不承诺**（整合方案 §6.2："42 个"是运营目标，先建市场框架） | 种子文件 + plan.md 清单 |
| 3 | 市场可见性 | **租户内**：模板目录种子为平台级共享可见；安装记录与「已安装」视图**按租户隔离**；不做跨租户/全球市场 | 市场 API 租户维度 |
| 4 | 与既有"企业工具连接"的关系 | **升级而非并行**：模板创建的连接器与手工创建落**同一存储、同一 test 链路、同一注入路径**（`tools.py` CRUD/test + `external_tools` 注入）；存量连接**零迁移**即出现在「已安装」视图 | 向导最终落库走既有创建路径 |
| 5 | "30 分钟接入"落地口径 | **向导（选模板 → 填参数 → 测试 → 上架）+ 模板预填 + 文档**；**不承诺计时**——"30 分钟"是运营口径不是 SLO | 向导 API + admin-web 向导页 |
| 6 | 与 018 资产关联形态 | 模板创建的连接器**自动注册为 018 能力资产**（`type=connector`），复用契约/版本/owner/审计；安装计数复用资产视图做引用统计；**若 018 需扩展资产类型枚举，只做关系声明**（本特性不改 018 语义） | `capability_assets.py` 注册调用 |
| 7 | 凭证加密依赖 | **依赖 034（credential-encryption，并行撰写）**：模板创建的连接器凭证写入路径 MUST 经 034 加密；**034 落地前允许创建但保持现状明文**（不阻塞市场框架），034 落地后验收"DB 无明文 + 响应掩码" | 存储写入路径 + 034 关系声明 |

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 浏览连接器模板目录（Priority: P1）

租户管理员在 admin-web「连接器市场」页浏览预置模板目录：名称/类别/描述/所需参数一目了然，可按类别筛选、按关键词搜索；模板详情展示参数 schema、示例参数与测试建议。

**Why this priority**: 市场目录是特性本体——没有目录就没有"市场"，也没有"开箱即用"的框架底座（数量是运营目标，框架先行）。

**Independent Test**: 种子加载服务返回模板清单（含 schema/描述/示例参数，无敏感占位泄露）；admin-web 市场页渲染列表与详情（`@vue/compiler-sfc` 编译通过）。

**Acceptance Scenarios**:

1. **Given** 种子目录含 N 个模板文件，**When** 调市场列表 API，**Then** 返回全部模板元信息（标识/名称/类别/版本/描述/认证类型），支持按类别筛选与关键词搜索。
2. **Given** 某模板（如"飞书机器人 Webhook"），**When** 查看详情，**Then** 展示参数 schema（必填/类型/说明）、示例参数与测试建议。
3. **Given** 某模板文件损坏或缺必填字段，**When** 加载，**Then** 跳过该模板并记录告警，不影响其余模板可用。

---

### User Story 2 - 从模板创建连接器（选模板 → 填参数 → 测试 → 上架）（Priority: P1）

管理员选模板 → 向导按 schema 渲染表单并预填示例值 → 填参提交 → 「测试连接」→ 通过后上架（`active`）→ 连接器可挂载到 Agent 发起调用。

**Why this priority**: 这是"30 分钟接入"（运营口径）的落地形态，也是市场从"浏览"到"可用"的关键一跳；没有创建链路，目录只是说明书。

**Independent Test**: 对 mock API 走完 创建 → 测试 → 挂载 Agent → 调用成功 全链路；断言落库记录与手工创建同构（同一集合、同一 payload 结构）。

**Acceptance Scenarios**:

1. **Given** 选中模板并填写参数，**When** 提交创建，**Then** 生成的连接器经既有创建路径落库，与手工创建的记录同构（`type`/`config`/`status`/schema 字段一致）。
2. **Given** 创建后点「测试连接」，**When** 目标 API 可达且参数正确，**Then** 返回成功；不可达或参数错误时返回可读错误（复用 `tools.py` test 链路，不静默卡死）。
3. **Given** 测试通过并上架，**When** 挂载到 Agent 发起调用，**Then** 凭证服务端注入生效（Agent 拿不到明文），调用成功且审计落库。
4. **Given** 参数不符合 schema（缺必填/类型错误），**When** 提交，**Then** 校验拒绝并逐项提示缺项，不落库。

---

### User Story 3 - 连接器作为能力资产关联与安装计数（Priority: P2）

模板创建的连接器自动注册为 018 能力资产（`type=connector`）并出现在 018 资产视图，可被 Agent 发现；模板安装计数（按模板 × 租户）在市场页可见。

**Why this priority**: 资产化是连接器"可治理"的前提（复用 018 注册/审计/状态机，不新建治理体系）；安装计数是整合方案点名的"引用计数/复用率"缺口的第一个落地维度。P2 因为 US1/US2 已构成可交付 MVP。

**Independent Test**: 创建连接器后断言 018 资产列表出现对应资产（契约/owner/审计齐）；同一模板多次创建后断言安装计数按租户递增。

**Acceptance Scenarios**:

1. **Given** 从模板创建连接器成功，**When** 查 018 资产视图，**Then** 出现该连接器资产（`type=connector`，契约/版本/owner/审计按 018 FR-3）。
2. **Given** 同一租户多次从同一模板创建，**When** 查市场页，**Then** 该模板安装计数按租户递增。
3. **Given** 连接器在 018 走下线审批（offline），**When** Agent 尝试调用，**Then** 调用被拒（001 门禁不变）。

---

### User Story 4 - 存量连接无缝迁移与凭证加密验收（Priority: P2）

存量手工创建的连接器无需任何迁移操作即出现在市场「已安装」视图；034 落地后，验证模板创建与手工创建的凭证均不明文存储、Agent 侧仍只拿服务端注入。

**Why this priority**: "升级而非并行"的承诺必须可证伪（存量零迁移）；"凭证不明文"是文章"凭证平台托管"的存储侧验收，依赖 034 落地（关系声明，不阻塞本特性主体）。

**Independent Test**: 预置一条手工创建的连接器，断言市场「已安装」视图可见且可正常调用；034 落地后查 DB 断言无明文凭证。

**Acceptance Scenarios**:

1. **Given** 租户已有手工创建的连接器，**When** 打开市场页，**Then** 该连接器出现在「已安装」，无需迁移操作、行为不变。
2. **Given** 034 已落地，**When** 从模板创建连接器并写入凭证，**Then** DB 中无明文凭证、API 响应掩码（与 034 验收口径一致）。
3. **Given** 034 已落地，**When** Agent 侧调用，**Then** 仍只拿服务端注入凭证（`external_tools.py:947-977` 现有行为 0 回退）。

---

### Edge Cases

- **模板 schema 与 `tools.py` payload 结构不一致**：创建时按模板 schema 校验参数，再映射到既有 payload（`type=http/mcp` + `config`）；映射失败返回可读错误，不写半条记录。
- **多认证形态**：首期模板 `authType` MUST 对齐 `external_tools` 既有注入能力（`none`/`bearer`/`api_key`）；oauth 等留后（模板声明即拒绝创建，提示不支持）。
- **同名模板重复安装**：允许（一个模板多实例，如连接多个环境）；安装计数递增；实例命名由用户自定，不强制唯一。
- **模板可选带"获取列表"式探测提示**（借鉴 031 discover 思路）：首期模板可带 discovery 提示字段，不强制实现，不做路由级依赖。
- **测试连接超时**：复用 `tools.py` test 的超时与错误格式（默认 35s，见 `tools.py` `_tool_timeout_seconds`），不静默卡死。
- **模板种子含真实凭证**：种子文件 MUST 只含占位符（如 `<your-token>`）；仓库级检查 + 加载时校验，发现疑似真实凭证拒绝加载该模板并告警。
- **租户隔离**：模板目录平台级共享；安装记录、已安装视图、安装计数 MUST 按租户隔离（复用既有租户维度）。
- **034 未落地时**：允许创建（行为同现状明文），市场页对"凭证托管"能力标记为待生效，不阻塞创建链路。
- **模板版本升级**：种子 `version` 递增；已安装实例继续用创建时固化的配置，不被动刷新（升级只影响新安装）。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 系统 MUST 提供连接器模板目录（仓库内种子 YAML，每模板一文件、带 `version`），每模板 MUST 含：标识/名称/类别/版本/描述/认证类型/参数 schema/示例参数/测试建议。
- **FR-002**: 系统 MUST 提供市场列表与详情 API（模板元信息），支持按类别筛选与关键词搜索；MUST NOT 在响应中泄露种子中的占位凭证值。
- **FR-003**: 系统 MUST 提供"从模板创建"API：按模板 schema 校验参数 → 映射为既有工具 payload → 经既有创建路径落库（同一存储与结构）。
- **FR-004**: 模板创建的连接器 MUST 与手工创建的**行为一致**：同一存储、同一 test 链路（`tools.py` `/{tool_id}/test`）、同一注入路径（`external_tools.py:947-977` 服务端注入）。
- **FR-005**: 创建向导 MUST 提供「测试连接」步骤并复用既有 test 链路；失败 MUST 返回可读错误，不静默。
- **FR-006**: 模板创建的连接器 MUST 自动注册为 018 能力资产（`type=connector`），复用 018 的契约/版本/owner/审计；若 018 需扩展资产类型枚举，MUST 只做关系声明，本特性 MUST NOT 改 018 既有语义。
- **FR-007**: 系统 MUST 记录模板安装计数（按模板 × 租户）并在市场页可见。
- **FR-008**: 存量手工创建的连接器 MUST 无需迁移即出现在市场「已安装」视图（升级而非并行）。
- **FR-009**: 连接器凭证写入路径 MUST 依赖 034（credential-encryption）的存储加密；034 落地后 DB MUST 无明文凭证、响应 MUST 掩码；034 落地前 MUST NOT 阻塞市场创建链路（保持现状）。
- **FR-010**: Agent 侧调用 MUST 保持服务端注入语义（Agent 不接触凭证明文）；调用 MUST 全程过 001 门禁与 audit（`enterprise_capabilities/tools/service.py` + `tools.py` `_enforce_gate`）。
- **FR-011**: 首批模板 MUST 覆盖 10–20 个常见系统（OA/ERP/数据平台/DevOps/通知 IM 五类，建议清单见 plan.md）；数量 MUST NOT 作对外承诺（整合方案 §6.2）。
- **FR-012**: 市场可见性 MUST 为租户内：模板目录种子平台级共享，安装记录/已安装视图/安装计数 MUST 按租户隔离。

### Key Entities

- **ConnectorTemplate**: `{id, name, category, version, description, auth_type, param_schema, example_params, test_hint}`——预置模板（种子 YAML，平台方维护，租户不可编辑）。
- **ConnectorInstall**: `{template_id, tenant_id, tool_id, installed_at, installed_by}`——安装记录（安装计数来源，按租户隔离）。
- **ConnectorAsset**: 即 018 能力资产（`type=connector`）——契约四段 + 版本 + owner + 审计，复用 018，不新建资产模型。
- **Tool（既有实体，复用）**: `external_tools` 连接器记录（`type`/`config`/`status`）——模板创建与手工创建落同一存储，同构是硬约束。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 从模板到可用连接器全链路（创建 → 测试 → 挂载 Agent → 调用成功）E2E 通过。
- **SC-002**: 模板创建的连接器与手工创建行为一致——契约测试断言同一存储结构与同一注入路径，0 分叉。
- **SC-003**: 034 落地后 DB 无明文凭证；Agent 侧仍只拿服务端注入（现有行为 0 回退）。
- **SC-004**: 存量连接 0 迁移即出现在「已安装」视图且可正常调用。
- **SC-005**: 首批 ≥10 个模板可加载、可创建、可测试（建议清单 18 个，运营可扩，不承诺数量）。

## Assumptions

- 模板由平台方维护（仓库内种子文件），租户基于模板创建立即实例，不可编辑模板本身。
- 首期认证类型对齐 `external_tools` 既有注入能力（`none`/`bearer`/`api_key`），oauth 等留后。
- 034（credential-encryption）由并行特性交付存储加密；本特性只做依赖声明与落地后验收，不重复实现加密。
- 018 资产类型若需扩展（`connector` 枚举），以 018 侧扩展为准，041 只做关系声明。
- admin-web 市场页为新增页面，复用现有工具管理的数据契约（`apps/admin-web/src/api/tools.ts` 与 `views/tools/` 既有模式）。
- 安装计数不做跨租户全局榜（租户内可见，决策 3）。

## 跨特性关系（被依赖方视角，双向声明）

- **与 034（credential-encryption，并行撰写）**：041 依赖 034 的凭证存储加密——模板创建的连接器凭证写入 MUST 经 034 加密（FR-009）；034 未落地时 041 可创建但保持现状明文（不阻塞），落地后验收"DB 无明文 + 响应掩码"。反向声明：034 对 `external_tools`/`tools.py` 存储路径的加密接线，同时覆盖 041 经模板新建的连接器（同一写入路径，无需 034 感知 041）。
- **与 018（capability-asset-registration）**：041 的模板创建自动注册 018 资产（`type=connector`），安装计数复用资产视图做引用统计（FR-006）；若 018 需扩展资产类型枚举只做关系声明，041 不改 018 语义。反向声明：018 的资产注册/审计/状态机是连接器资产化的唯一通道，041 不新建平行治理体系。
- **与 016（skill-market-hardening）**：市场形态（上架/评分/灰度机制）可借鉴 016；首期**不强制复用**其发布流（模板目录是平台种子，不是租户发布物流转）。
- **与 031（model-provider-discover）**：模板可选带"获取列表"式探测提示（031 discover 思路，如 API 根路径探测），首期不强制、不做路由级依赖。
- **与 001（gatekeeper-governance）**：连接器调用的门禁与审计不变（`tools.py` `_enforce_gate` + `enterprise_capabilities/tools/service.py` audit + R4 红线），041 不新开治理通道。反向声明：041 新建的连接器实例天然继承 001 既有门禁，无需 001 改动。

## 判定口径补充（2026-10-24，/speckit-checklist 回填）

> 本节答复 `checklists/requirements.md` 的 CHK001–CHK016，为 FR-001…FR-012 / 决策 #1–#7 补可执行口径。**实现现状以 2026-10-24 代码级核查为准**：041 代码全未开工。凡写"**首期未实现**"者为"设计口径已定、待按 tasks.md 落地"；凡写"**已接线**"者为代码中已存在、041 只需复用。

### 实现现状核查（2026-10-24，代码级；041 代码零开工）

| # | 未实现项 | 建议落点 |
| --- | --- | --- |
| 1 | 模板种子目录（首批 18 个 YAML） | `services/admin-api/app/connector_templates/*.yaml` |
| 2 | 种子加载（mtime 热加载 + 损坏跳过 + 占位符校验） | `services/admin-api/app/services/connector_templates.py` |
| 3 | 市场 API（列表/详情/安装/已安装/计数） | `services/admin-api/app/api/routes/connector_market.py`（prefix `/api/connector-market`） |
| 4 | 安装记录集合 + 计数聚合 | 集合 `connector_installs`；写入在市场路由，级联删除挂 `tools.py:delete_tool` 之后 |
| 5 | 018 资产注册接线 | 市场创建成功分支调 `POST /api/capabilities/discover`（带 `service_token`） |
| 6 | 前端市场页 + 向导 | `apps/admin-web/src/views/connectors/ConnectorMarketPage.vue`，路由挂 `apps/admin-web/src/router/routes.ts`（现仅 `/tools`、`/tools/new`、`/tools/:id/edit` 三条） |
| 7 | 前端 API 客户端 | `apps/admin-web/src/api/connectorMarket.ts`（仿既有 `apps/admin-web/src/api/tools.ts`） |
| 8 | i18n 文案键 | `apps/admin-web/src/locales/messages.ts` |
| 9 | 单测 | `services/admin-api/tests/test_connector_market.py`（当前不存在，本特性零测试） |

**已存在、仅复用（不改语义）**：`services/admin-api/app/api/routes/tools.py`（CRUD/test/test-draft/discover/generate-description/`_enforce_gate`）、`services/chat-api/app/services/external_tools.py`（凭证注入与解密）、`services/admin-api/app/services/capability_assets/`（018 注册/契约/状态机）、`services/admin-api/app/security/tool_credentials.py`（034 加密）。

### R-1 模板目录结构（答 CHK001）

`services/admin-api/app/connector_templates/<template_id>.yaml`，一模板一文件；文件名即 `template_id`（`^[a-z0-9][a-z0-9-]{1,63}$`，如 `feishu-bot-webhook.yaml`）。加载器 `app/services/connector_templates.py` 启动全量加载 + mtime 热加载（与 chat-api `ModelRouter._load_config` 同模式）。`id` 字段 MUST 等于文件名，不重复；重复 `id` 视为损坏（R-4 a 通道）。**首期未实现**（目录不存在）。

### R-2 模板文件字段与 schema 方言（答 CHK001 / CHK002）

必填字段：`id`、`name`、`category`、`version`、`description`、`auth_type`、`param_schema`、`example_params`。

- `category` 枚举：`oa | erp | data | devops | im`（对齐 plan.md:35-41 五类）；非法值 → 跳过加载。
- `version`：整数，从 `1` 起，单调递增。
- `description`：中文主文案；可选 `description_en`（plan.md:52 双语约束）。
- `auth_type` 枚举：`none | bearer | api_key`（对齐 `external_tools` 既有注入能力）。
- `param_schema`：**与既有 MCP `inputSchema` 同构的扁平节点数组**，节点 `{name, type(String|Number|Boolean|Object|Array), required, location(Query|Path|Header|Body), description, default}`。**`param_schema` 只描述"业务入参"**，连接参数不进 schema（见 R-3 的 `connection` 段）。
- `example_params`：`{参数名: 占位值}`，键集 MUST ⊆ `param_schema` 中 `required=true` 的 `name` 集；值 MUST 为占位符（如 `<your-token>`）。
- `test_hint`（可选）：结构化 `{endpoint, expected_status}`（plan.md:43），**仅详情展示，不参与创建链路**、不做路由级依赖（对齐 Edge Case「模板可选带获取列表式探测提示」）。

### R-3 参数 → 既有 payload 的字段映射（答 CHK001）

模板用 `connection` 段提供连接参数，与 `param_schema`（业务入参）分离：

| 模板 `connection` | 映射到 `ToolPayload` |
| --- | --- |
| `type: http` | `type="http"`，`config.url`、`config.method`、`config.headers`、`config.timeoutSeconds` |
| `type: mcp` | `type="mcp"`，`config.endpoint`、`config.inputSchema`（= `param_schema`） |
| `auth_type`/`auth_token_placeholder`/`api_key_header` | `config.authType` / `config.authToken`（用户填值）/ `config.apiKeyHeader`（缺省 `X-API-Key`） |
| 用户填的实例名 | `name`（必填；缺省 `模板名`） |
| `category` | `tags = ["connector", category]` |
| `description` | `description`（模板描述；可追加实例后缀） |

校验顺序固定：**模板 schema 校验 → 映射为 `ToolPayload` → 走既有 `POST /api/tools`**（服务层 `_normalize_payload` 会自动加密凭证，见 R-9）。任一步失败返回 400 且不落库（对齐 Edge Case「不写半条记录」）。

### R-4 种子加载与告警（答 CHK004）

三级分离，只落进程日志（模板加载是平台事件，不写租户审计集合）：

- **(a) 跳过**：YAML 解析失败 / 缺必填 / `id` 与文件名不符 / `category` 或 `auth_type` 非法 → `logger.warning("connector_template_skipped id=%s reason=%s")`。
- **(b) 拒绝加载（更严重）**：检出疑似真实凭证（`auth_token`/`api_key`/`headers` 值不在占位符白名单，或匹配 `^(sk-|xox[bap]-|ghp_|AKIA|-----BEGIN)`）→ `logger.error("connector_template_rejected_credential id=%s")`。
- **(c) 成功**：`logger.info("connector_template_loaded id=%s version=%s")`。

被跳过的模板**不计入列表 `total`**，但列表响应携带 `skipped: [{id, reason, level}]` 供运维排障（a/b 两级用 `level` 区分）。

### R-5 首批清单与验收判据（答 CHK005）

按 plan.md:35-41 交付 **18 个**模板（5 类别各 ≥2）。**SC-005 的"≥10"是最低硬下限、18 是计划值**——测试断言"加载成功数 ≥10 且 5 类别各 ≥2"，18 与 ≥10 不冲突（18 覆盖 ≥10）。"可创建/可测试"用 **mock API** 验收（不依赖外网，第三方真实 API 不进 CI）。

### R-6 上架与 018 资产注册的字段映射（答 CHK007 / CHK012）

**上架 = 两步，第一步不改既有语义**：

1. `POST /api/tools` 创建 —— 既有实现**恒定 `status="disabled"`**（`_normalize_payload` 的 status 被字典字面量后置覆盖），041 不改此行为。
2. 安装成功后由服务端 `PATCH /api/tools/{tool_id}` `{"status":"active"}`，经 `_validate_final_activation`：`type=mcp` 且 `active` 时要求 `enabled_mcp_tool_names(config)` 非空（`app/api/tool_limits.py:26-32`），失败返回 400 并保持 `disabled`。

测试未通过（`last_test_status != "passed"`）**允许上架**（与手工创建一致，不额外收紧），但市场页标记"未验证"。

**018 字段映射（018 无 `type` 字段，只有 `kind`）**：

| 041 概念 | 018 实际字段 | 取值 |
| --- | --- | --- |
| 连接器类型 | `kind` | 工具 `type=http` → `rest`；`type=mcp` → `mcp`（`AUTO_DISCOVERABLE_KINDS={"rest","mcp"}`） |
| 资产标识 | `asset_id` | `dedupe_key(endpoint, method) = f"{METHOD}:{endpoint.lower()}"` |
| `type=connector` | **无对应字段** | 语义落 `connector_installs.template_id` + 工具 `tags=["connector"]`；枚举扩展诉求挂 018 侧（与 FR-006"只做关系声明"一致） |

注册路径只有 `POST /api/capabilities/discover`（需 `service_token`、批量 `candidates=[{name, endpoint, method, kind, contract}]`；**无单资产注册路由**，`connector` 会让 `discover_assets` 落入 `needs_manual`）。**首期未实现**（无 connector 相关代码）。

### R-7 测试连接的判定（答 CHK006）

"测试通过" = `POST /api/tools/{tool_id}/test` 满足 **`success is not False` ∧ `status == "passed"` ∧ HTTP 2xx**（等价响应头 `X-MOGO-Operation-Result == "success"`，即 `_operation_succeeded` 口径）。

- 门禁拒绝（`_enforce_gate` 抛 403/409/503）**不写 `last_test_status`**，向导记为 `blocked(reason)`——既不算通过也不算失败。
- 实例未落库前用 `POST /api/tools/test-draft`（body 内嵌 `{tool: {...}}`，`_tool_timeout_seconds` 读 `body.tool.config`）试连；落库后用 `/{tool_id}/test`。两路径判定口径一致。
- 超时沿用 `_config_timeout_seconds`：`config.timeoutSeconds` 缺省 35s，clamp `[35,180]`；不静默卡死（对齐 Edge Case「测试连接超时」）。

### R-8 安装记录与安装计数存储（答 CHK003 / CHK008）

新集合 `connector_installs`，一行一次安装：`{_id, tenant_id, template_id, template_version, tool_id, installed_at, installed_by}`。**唯一键 `(tenant_id, template_id, tool_id)`**；同一模板多实例 = 多行（对齐 Edge Case「同名模板重复安装」）。

- **计数 = 行数聚合** `count_documents({tenant_id, template_id})`，**不设冗余计数器字段**（避免并发 `$inc` 丢更新）。
- 删除连接器时级联 `connector_installs.delete_many({tool_id})`（落点在 `tools.py:delete_tool` 之后调用 `connector_templates.record_uninstall`）。
- 计数为 0 的模板仍返回（`install_count: 0`）。
- `template_version` 存**安装记录**而非工具记录（工具记录无此字段，见 R-12）。

**首期未实现**（全仓无 `connector_installs` 引用）。

### R-9 与 034 凭证加密的关系（答 CHK011）

**034 已接线，041 不新增任何加密接线**：

- 写侧：`tools.py:_normalize_payload` → `encrypt_credentials`（识别 `authToken`/`apiKeyHeader`/`headers.*` 等键；`KmsConfigError` → **503 fail-closed**，不落明文兜底）；PATCH/PUT 时 `merge_credential_preserve` 保留响应掩码后未回传的密文凭据。
- 响应：`_serialize` 经 `redact_credentials` 掩码为 `***`。
- 读侧：`external_tools.py:784`（HTTP 直连/测试）与 `1010`（runtime/MCP）`decrypt_credentials` 宽容解密（明文/密文双跑兼容，调用不中断）。

因此模板创建的凭证**只要走既有 `POST /api/tools` 即自动加密**。决策 #7 / FR-009 的"034 落地前保持明文、落地后验收"分级**已不适用**：验收改为单一判据——创建后 `external_tools.config` 无明文、`GET /api/tools` 响应掩码（`***`），且不再阻塞。原文保留作历史记录，本条为准。

### R-10 租户/组织隔离判定键（答 CHK013）

市场「已安装」视图与安装计数 MUST 复用 `organization_tool_query(tenant_id)`（`tenant_id` + `$or[{scope:"organization"},{scope 缺失},{scope:""}]`），即**只统计组织级工具，排除 `scope="user"` 个人工具**。模板目录本身平台级共享、不按租户过滤（决策 #3）。所有 `connector_installs` 读写 MUST 带 `tenant_id` 条件，禁止无租户条件的聚合。

### R-11 列表/详情/搜索口径（答 CHK009）

`GET /api/connector-market/templates?category=&q=`：

- `category` 非法值 → **400 `invalid_category`**（不静默返回空列表，避免前端误判）。
- `q` 空/缺省 = 不过滤；关键词对 `name`/`description`/`description_en`/`tags`/`param_schema[].description` 做 `casefold()` 子串匹配（中文首期不额外分词，朴素匹配）。
- 排序固定 `category asc, name asc`。
- 详情 `GET .../templates/{id}`：未知 id → 404；响应 MUST NOT 含 `example_params` 之外的任何疑似凭证，`test_hint` 原样返回。

### R-12 模板来源留痕与版本固化（答 CHK003 / CHK014）

`ToolPayload` 无模板字段，因此**模板来源只落 `connector_installs`（`template_id` + `template_version`）**，工具记录保持零改动（同构硬约束优先于留痕便利）。"固化"判据 = 服务端**不存在任何按 `template_id` 回写已有工具 `config` 的代码路径**；模板 `version` 升级只影响新安装。市场详情对已装实例比对 `connector_installs.template_version < template.version` 时展示"模板已升级（不影响现有实例）"，**首期不做升级动作**，也无实例升级按钮。**首期未实现**。

### R-13 不支持的 `authType` 拒绝时机（答 CHK015）

**加载期处理**：`auth_type ∉ {none, bearer, api_key}` 的模板按 `reason=unsupported_auth_type` 走 R-4 的 (a) 通道跳过 → **不出现在市场列表**（不会列一个必然失败的模板）。创建期再兜一次 `400 unsupported_auth_type`（防 mtime 热加载竞态）。即 Edge Case「模板声明即拒绝创建」= "加载期不暴露 + 创建期兜底"双重实现。

### R-14 向导与门禁审批交互（答 CHK016）

`_enforce_gate` 拒绝按层映射，三种都**不写 `last_test_status`**，向导状态 `blocked(reason)`：

- **403**（身份/RBAC）→ 提示"无权限，联系管理员"，并**禁用上架按钮**。
- **409**（审批待办）→ 提示"已提交审批，通过后可测试/上架"，**不记为测试失败**，也不允许绕过上架。
- **503**（依赖不可用，如加密主密钥缺失）→ 提示重试。

### R-15 创建链路的事务与补偿（答 CHK003）

顺序固定：**模板 schema 校验 → `POST /api/tools` 落库 → 写 `connector_installs` → 注册 018 资产 → 尝试上架（PATCH active）**。

第 2 步成功而第 3/4/5 步失败时：**不回滚工具记录**（工具本身可用，与手工创建行为一致），返回 `201` + `warnings: ["install_record_failed" | "asset_register_failed" | "activation_failed"]`，并 `logger.error` 供运维补齐。同一请求重放以 `(tenant_id, template_id, tool_id)` 幂等，不产生重复安装行。**首期未实现**。

### R-16 引用更正（答 CHK010）

本文件三处 `external_tools.py:947-977`（背景事实表、FR-004、US4-3）作为"凭证服务端注入"证据**行号有误**：该区间实为 `_flatten_schema`/`_build_debug_trace`。正确落点为 **`784-802`（HTTP 直连/测试注入）与 `1010-1031`（runtime/MCP 注入，`runtime_headers` 最后应用、不可伪造）**；`enterprise_capabilities/tools/service.py` 的审计引用不变。SC-002 的"同一注入路径"验收以这两段为准。

### 验收证据

2026-10-24 代码级核查（**本回填不含任何代码改动，041 代码零开工**）：`services/chat-api/app/services/external_tools.py`（784-802 / 1010-1031）、`services/admin-api/app/api/routes/tools.py`（`ToolPayload` 207-215、`create_tool` 241-261、`_normalize_payload` 87-140、`/{tool_id}/test` 323-336、`/test-draft` 338-346、`_enforce_gate` 349-400、`_serialize` 67-86）、`services/admin-api/app/services/capability_assets/registry.py`（21/27/34-37/51/119-155）、`services/admin-api/app/services/capability_assets/contract.py`、`services/admin-api/app/api/routes/capability_assets.py`（七条路由）、`services/admin-api/app/services/organization_tools.py:14-16`、`services/admin-api/app/api/tool_limits.py:26-32`、`services/admin-api/app/security/tool_credentials.py`（104/137/189）、`apps/admin-web/src/views/tools/`（仅 `ToolsPage.vue`/`ToolEditPage.vue`）、`apps/admin-web/src/api/`、`apps/admin-web/src/router/routes.ts:96-110`。**无测试**：`services/admin-api/tests/` 无 `test_connector_market.py`，测试项待 tasks.md 落地。

## 判定口径补充（2026-10-24，实现期回填）

- **R-17 URL 占位符分两层**：模板种子用 `${key}`（与 chat-api 运行时 `{key}` 区分）；`render_config` 渲染时把 `query`/`body`/`headers` 类参数替换为具体值，`path` 类参数**保留**为 `{key}` 供调用期传参（chat-api `_ordered_path_keys_from_schema` 依据 `config.inputSchema` 中 `location == "Path"` 决定注入顺序）。
- **R-18 凭证托管适用面**：仅当 `auth_type ∈ {bearer, api_key}` 且全部 `secret: true` 参数的 `in ∈ {headers, query}` 时 `credentialManaged=true`，值写入 `config.authToken`（034 加密覆盖该键）；对必须以 URL 段传 token 的模板（钉钉 webhook / 钉钉工作通知 / Slack / ClickHouse）种子标 `auth_type: none` + 参数 `secret: false`，渲染保留 `{key}`、**值绝不写入 config**，市场页显式标注「凭证托管暂不支持」（FR-009 诚实降级）。
- **R-19 018 资产注册为尽力而为**：`_register_capability_asset` 构造 `CapabilityAsset(asset_id=f"connector:{tool_id}", kind="connector")` 并注册，失败仅 `logger.warning`，**不阻断**连接器创建（018 属治理层，连接器可用性优先）。
- **R-20 存储同构的实现锚点**：市场创建调用 `tools.py::create_tool_record()`（由 `create_tool` 抽出的落库段），保证 `_id`/`tenant_id`/`organization_tool_fields()`/`_normalize_payload()`/`status="disabled"`/`last_test_status="untested"` 与手工创建逐字段一致；`_normalize_payload` 内含 034 的 `encrypt_credentials`，无 KMS 主密钥时按 034 R-4 返回 503（市场页透传该错误，不静默降级为明文）。
## Non-Goals

- 不承诺"42 个"数量（整合方案 §6.2：先建市场框架，数量是运营目标）。
- 不做跨租户/全球连接器市场（租户内可见）。
- 不做模板的租户自定义编辑（租户基于模板创建立即实例）。
- 不实现 oauth2 等复杂认证流（首期 `none`/`bearer`/`api_key`）。
- 不改 `external_tools` 注入语义、不改 001 门禁与审计、不新建第二套工具存储。
- 不做连接器自动编排/组合（编排归 010 DAG）。
- 不做 admin-web 之外的新端（移动端按 ADR-7 不单独建设）。

## Further Details

- 技术实现（模板 schema 方言、向导 API 契约、安装记录存储、首批清单）由 plan.md 承载。
- 与 034 的接线时点（034 落地前后的创建行为差异）需在实现期与 034 代理对齐落地顺序。
