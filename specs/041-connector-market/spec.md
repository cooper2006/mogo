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
