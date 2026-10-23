# Feature Specification: 可视化编排画布（Visual Orchestration Canvas）

**Feature Branch**: `039-visual-orchestration`

**Created**: 2026-10-23

**Status**: Draft

**Input**: 整合方案（`docs/MOGO-AgentOS整合方案.md`）§4.8（P2，Wave 3）与 §2.2 界面 3：给 010 DAG 引擎补前端可视化画布——文章"十界面"之一，把"会写代码"的编排门槛降到"会描述业务"。

> **设计来源**：本特性为**全新特性**（代码尚未开工）。设计细节以整合方案 §4.8 为准，本文件在其上补充落地口径；冲突时以本 spec 的 FR 与已定决策表为准。

> **性质说明**：与 031 的"回溯补规格"本质不同——本特性代码零落地（前端全库无 vue-flow/logicflow 命中、无编排页；010 为纯后端引擎），tasks.md 全部任务未勾选（`- [ ]`）。

## 定位（一句话）

给 010 DAG 引擎（`services/chat-api/app/orchestration/`：`engine.py` 的 `run_graph`/`run_sequential`、`supervisor.py` 的 `run_hybrid`、`loader.py` YAML 装载、`store.py` `dag_definitions` 集合持久化、`topo.py` 拓扑/环检测、`conditions.py` 条件跳过）补一个前端可视化画布——**YAML 为权威定义、画布为投影**，画布 JSON 与 010 YAML 双向互转（不新增第三种定义格式），画布搭建的流程可保存并被 010 引擎真实执行。

## 背景事实（代码级核实，2026-10-23）

| 事实 | 证据 |
| --- | --- |
| 010 引擎为纯后端 | `services/chat-api/app/orchestration/`：四模式（`graph.py` `VALID_MODES = ("sequential","supervisor","hybrid","graph")`）+ 拓扑/环检测 + 条件跳过 + 节点重试 |
| 前端无画布库 | vue-flow / logicflow 全库 0 命中（整合方案附录 B） |
| 前端无编排页 | user-web / admin-web 均无编排视图 |
| user-web 的 `workflow.*` 文案不是画布 | `apps/user-web/src/components/MySkillConfigPage.vue` 实为 Skill 业务步骤编辑；`apps/user-web/src/workflow/browserAutomationNode.ts` 为单类浏览器步骤配置 |
| `dag_definitions` 无 HTTP API | `store.py` 仅内部加载（`load_orchestration_persisted`），`services/chat-api/app/api/endpoints/` 无 orchestration 路由 |

## 已定决策（2026-10-23，立项拍板）

| # | 决策点 | 结论 | 落点 |
| --- | --- | --- | --- |
| 1 | 承载端与库选型 | **user-web 承载 + vue-flow（`@vue-flow/core`）**：编排主体是业务用户（"把会写代码降到会描述业务"），admin-web 是平台管理端；vue-flow 为 Vue 3 原生、TS 支持好、MIT，自研画布（拖拽/缩放/连线/小地图）成本远超收益，logicflow 非 Vue 生态 | user-web 新页面 |
| 2 | 位置信息存储口径 | **YAML 顶层 `layout` 字段**（投影元数据，权威仍是拓扑定义）：`loader.py` 不改（`raw` 已透传全量文档），`store.py` 的 `_document_shape` 增加 `layout` 透传（**联合改动点**，需同步 010 spec）；位置丢失不影响定义有效性（验收明示容忍丢失） | `orchestration/store.py:92` |
| 3 | 首期模式覆盖 | **sequential + graph 两模式优先**：graph 为通用形态，sequential 是其无并行特化（序列化自然退化）；supervisor/hybrid 二期（监督节点语义需额外可视化建模） | 序列化模块模式分支 |
| 4 | 权威定义 | **YAML 为权威，画布是投影**：序列化/反序列化模块是唯一转换层；不新增第三种定义格式；画布保存 = 画布 JSON → 010 YAML → 走 `dag_definitions` | 序列化模块 |
| 5 | 权限模型 | **编排权与发布权分离**：画布编辑为草稿态（租户内可见，`orchestration:write` 类能力）；发布（注册进 `dag_definitions` 生效版本）走 001 gatekeeper 权限与审批语义——**画布不绕过 gatekeeper** | 发布动作挂点 |

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 画布搭建流程并保存，可被 010 引擎真实执行（Priority: P1）

业务用户在 user-web 打开编排画布，从节点面板添加节点（选 Skill/工具）、拖拽连线定义依赖，右侧属性面板编辑节点属性；点保存后系统把画布序列化为 010 YAML 写入 `dag_definitions`；随后该流程经 010 引擎既有入口真实执行——画布产物与手写 YAML 走同一条执行链。

**Why this priority**: 这是整个特性的核心价值与唯一写入口——"画布搭建的流程可保存并真实执行"。没有它，画布只是玩具。

**Independent Test**: 在画布搭一个两节点 graph 流程（A→B），保存后直接以 010 引擎执行（`DagEngine.run_graph` + mock 节点 runner），断言执行顺序与依赖正确、产出写入共享上下文；再断言 `dag_definitions` 中的文档可被 `load_orchestration_document` 原样装载。

**Acceptance Scenarios**:

1. **Given** 空画布，**When** 用户添加两个节点并用连线建立 A→B，**Then** 保存生成的 YAML 含 `orchestration.mode=graph`、两节点与一条 `depends_on` 边。
2. **Given** 画布流程已保存，**When** 经 010 引擎执行，**Then** A 先于 B 执行，B 能读到 A 写入共享上下文的输出（`output_key`）。
3. **Given** 用户把模式切为 sequential，**When** 保存并执行，**Then** 节点按线性顺序执行（序列化为无并行 graph 特化）。
4. **Given** 节点属性面板选择了 Skill 与工具，**When** 保存，**Then** YAML 节点 payload 含 `skill`/`tools` 字段（010 loader `_PAYLOAD_KEYS` 既有键，不改 loader）。

---

### User Story 2 - 手工 YAML 可在画布打开，双向不丢信息（Priority: P1）

用户（或 another 工具/CI）手工编写的 010 YAML 流程，可在画布中打开：节点、边、模式、条件、重试全部还原为画布元素；反之画布保存再打开，拓扑信息不丢失。节点位置信息容忍丢失（无 `layout` 时自动布局）。

**Why this priority**: "双向不丢信息"是画布可信度的前提——若画布只能写不能读手写 YAML，既有资产（如 `enterprise_capabilities/research/orchestrations/competitor_deep_dive.yaml`）与 YAML 工作流用户都被排除在外。

**Independent Test**: 用 `competitor_deep_dive.yaml`（四并行分析节点 + 合成节点 + 两个 `skip_condition`）反序列化开画布，断言节点/边/模式/条件全还原；再序列化回 YAML，除 `layout` 外与原文语义等价（经 `load_orchestration_document` 装载结果一致）。

**Acceptance Scenarios**:

1. **Given** 一份含 `skip_condition`（`expr` + `reason`）的手工 YAML，**When** 在画布打开，**Then** 条件以节点属性呈现（含 reason 文案），不丢失。
2. **Given** 画布从无 `layout` 的 YAML 打开，**When** 渲染，**Then** 自动布局（位置容忍丢失，不报错）。
3. **Given** 画布保存后的 YAML 再次打开，**When** 对比，**Then** 节点/边/模式/条件零丢失（拓扑级往返稳定）。
4. **Given** YAML 含画布不认识的顶层键（如 `data_contract`/`audit`），**When** 打开再保存，**Then** 原样保留（`raw` 透传，不透写丢失）。

---

### User Story 3 - 画布校验与引擎侧一致（环/孤立节点）（Priority: P1）

用户在画布连出环或留下孤立节点时，保存前即在画布得到错误提示，错误内容与引擎侧一致（环报错含节点 ID 序列，如 `A -> B -> C -> A`）；校验不通过的流程不得保存。

**Why this priority**: 画布若允许保存非法图，错误会延迟到引擎执行期才爆——把 010 的既有校验（`topo.py` `CycleError` / `registry.validate()`）前置到画布保存点，是"画布不降低质量底线"的保证，与 US1 同批交付。

**Independent Test**: 画布构造 A→B→C→A，点保存，断言画布高亮环路径且提示文本与 `topological_order` 抛出的 `CycleError` 消息一致（同节点序列）；构造孤立节点，断言有提示；两者均不得产出保存动作。

**Acceptance Scenarios**:

1. **Given** 画布存在环，**When** 保存，**Then** 拒绝保存并高亮环上节点，错误信息含环路径节点序列（与 `topo.py` 输出同格式）。
2. **Given** 画布存在孤立节点（无入无出且非单节点图），**When** 保存，**Then** 给出提示（可保存但标记警告——孤立节点在引擎侧合法，画布只警示不阻断；环才阻断）。
3. **Given** 节点条件表达式非法，**When** 保存，**Then** 按引擎口径 fail-closed 拒绝并提示（与 `registry.validate()` 的 `RegistryError` 对齐）。

---

### User Story 4 - 节点属性面板复用现有 Skill/工具选择器（Priority: P2）

节点属性面板不新造选择器：Skill 选择复用 user-web 既有 Skill 列表（`MySkillsPage` 数据源），工具选择复用既有工具列表；节点可配置 `description`/`timeout`/`retry`/`skip_condition` 等 010 既有字段。

**Why this priority**: 属性面板是画布的"填写"侧，复用既有选择器让用户选到的是自己已装的 Skill/已连的工具——但即使首期用简化输入（手填 ID）也不阻塞画布主链路，故列 P2。

**Independent Test**: 属性面板打开 Skill 选择器，列表数据来自既有 Skills API（非硬编码）；选定后 YAML payload 的 `skill` 字段更新；工具多选同理。

**Acceptance Scenarios**:

1. **Given** 选中一个节点，**When** 打开属性面板，**Then** 展示 010 节点既有字段（skill/tools/description/timeout/retry/skip_condition/output_key），未知 payload 键只读展示不透写。
2. **Given** 属性面板选择 Skill，**When** 选定，**Then** 节点 payload `skill` 更新且保存后 YAML 可见。

---

### User Story 5 - 发布走版本化与门禁，画布不绕过（Priority: P2）

画布草稿保存后，"发布"动作把流程注册为 `dag_definitions` 的生效版本：版本号递增、旧版本保留可回看（010 FR-8 版本化语义，与 002 工作流版本化对齐）；发布动作过 001 gatekeeper（权限码 + 适用审批语义），无权限用户只能存草稿。

**Why this priority**: 发布是治理动作（影响生产执行），必须有门禁与版本化；但草稿保存-执行闭环（US1）不依赖发布流，故列 P2。

**Independent Test**: 有发布权限的用户发布 → `dag_definitions` 版本 +1、旧版可查；无发布权限的用户点发布 → 被 001 门禁拒绝且审计可查；草稿态对同租户其他用户不可见（或按权限码可见）。

**Acceptance Scenarios**:

1. **Given** 已保存草稿，**When** 有权限用户发布，**Then** `dag_definitions` 记录新版本，`history` 可回看旧版（010 `OrchestrationRegistry.history` 语义）。
2. **Given** 无发布权限用户，**When** 尝试发布，**Then** 被 gatekeeper 拒绝（提示权限原因），审计留痕；草稿仍可编辑。
3. **Given** 同一流程的旧版本正在被执行，**When** 新版本发布，**Then** 旧版本定义保留不删（执行中实例不受影响，回看可证）。

---

### Edge Cases

- **环与自环**：自环（A→A）同样阻断保存（引擎 `topo.py` 亦拒绝）；画布禁止节点连自身。
- **空图保存**：零节点不得保存（010 loader 要求 `nodes` 非空，画布前置同一口径）。
- **重复节点 ID**：画布内即时禁止（重名节点不允许存在），不靠保存期报错。
- **sequential 模式的边**：sequential 画布仍可连线表达顺序，序列化为 `depends_on` 链（顺序 = 连线序）；乱序连线在 sequential 下按拓扑序归一（引擎行为，画布不发明新语义）。
- **条件极性**：010 YAML 的 `skip_condition`（为真则跳过）与引擎内部 `condition`（为真则执行）极性相反，loader 已用 `not` 包装（`loader.py:193-205`）——画布只暴露 `skip_condition` 自然语言面，不透出引擎内部条件对象。
- **`layout` 损坏**（手写 YAML 里 `layout` 结构非法）：反序列化时忽略该字段并自动布局，不让坏布局堵死打开路径（投影元数据可丢）。
- **大图**：百节点级画布首期不做性能优化（记录限制即可，YAGNI）；节点量过大时提示拆分。
- **并发编辑**：首期不做多人协同编辑（后写覆盖前写，保存时按版本号提示冲突）——Non-Goal 明示。
- **浏览器步骤节点**：user-web 既有 `browserAutomationNode` 配置组件与本画布节点属性面板不合并（前者是 Skill 内步骤，后者是编排节点），避免两套语义混淆。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 系统 MUST 在 user-web 提供可视化编排画布页面（vue-flow）：节点增删、拖拽布局、连线定义依赖、缩放与概览。
- **FR-002**: 系统 MUST 提供画布 JSON ↔ 010 YAML 的双向序列化/反序列化模块，作为**唯一转换层**；MUST NOT 新增第三种编排定义格式。
- **FR-003**: 画布保存 MUST 走 010 既有持久化通道（`dag_definitions` 集合，`orchestration/store.py`），保存产物 MUST 能被 `load_orchestration_document` 原样装载。
- **FR-004**: 画布搭建的流程 MUST 可被 010 引擎真实执行（同一 YAML，引擎入口不变）。
- **FR-005**: 手工编写的 010 YAML MUST 可在画布打开，往返后拓扑信息（节点/边/模式/条件/重试）零丢失；节点位置信息（`layout`）容忍丢失。
- **FR-006**: 画布保存前 MUST 做校验且与引擎侧一致：环（含自环）阻断保存并高亮环路径（错误信息含节点 ID 序列，与 `topo.py` `CycleError` 同格式）；孤立节点警示不阻断；非法条件按引擎 fail-closed 口径拒绝。
- **FR-007**: 首期画布 MUST 覆盖 sequential 与 graph 两种模式；supervisor/hybrid 二期（超出部分 MUST 在 UI 明示"暂不支持"而非静默降级）。
- **FR-008**: 节点属性面板 MUST 复用既有 Skill/工具选择器（数据源为既有 Skills/工具 API），可编辑 010 既有节点字段；未知 payload 键 MUST 只读保留、不透写丢失。
- **FR-009**: 发布动作 MUST 走 001 gatekeeper（权限与适用审批语义），画布 MUST NOT 提供绕过门禁的保存即生效路径。
- **FR-010**: 编排产物 MUST 走版本化语义：发布递增版本、旧版本保留可回看（010 FR-8，与 002 工作流版本化对齐）。
- **FR-011**: 本特性 MUST NOT 修改 010 引擎执行语义（`engine.py`/`supervisor.py`/`topo.py`/`conditions.py` 不改行为）；若实现确需引擎侧调整，MUST 在 tasks 中列为联合改动点并注明同步 010 spec。
- **FR-012**: `layout` 字段 MUST 为投影元数据：存于 YAML 顶层，损坏或缺失不影响定义有效性与引擎执行。

### Key Entities

- **CanvasDocument**: 画布内存模型——`{orchestration 头（id/version/mode/max_concurrency/timeout/retry）, nodes[], edges[], layout?}`；序列化模块的输入/输出。
- **LayoutHint**: `{node_id: {x, y}}`，节点位置投影（顶层 `layout` 字段内容；可丢失）。
- **OrchestrationYaml（010 权威定义）**: `orchestration` 头 + `nodes`（`id`/`skill`/`tools`/`depends_on`/`skip_condition`/`retry`/`output_key`/`timeout`/`description`）+ `edges`（`source`/`target`），即 `loader.py` 接受的文档形状。
- **DagDefinitionRecord**: `dag_definitions` 集合文档（`orchestration_id`/`version`/`document`/`created_at`），010 store 的运行时权威来源。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 画布搭建的流程保存后可被 010 引擎真实执行——E2E 中画布产物与手写 YAML 产物经同一引擎执行结果一致（顺序/并行/条件跳过/产出传递）。
- **SC-002**: 手工 YAML → 画布 → YAML 往返，拓扑信息保留率 100%（节点/边/模式/条件/重试；位置可丢）。
- **SC-003**: 画布环检测与引擎侧一致——同一含环图，画布拒绝保存的错误信息与 `topo.py` 抛出的环路径节点序列相同。
- **SC-004**: 010 引擎既有测试回归 0 破坏（orchestration 全模块测试全绿；`competitor_deep_dive` 案例装载/执行不变）。
- **SC-005**: 发布路径 100% 过 001 gatekeeper——无权限发布尝试 100% 拒绝且审计可查，无任何"画布直通生产"路径。

## Assumptions

- 假设 chat-api 需新增编排定义读写 HTTP 端点（当前 `dag_definitions` 无 API，仅 store 内部加载）——本特性新增，属 chat-api 既有模式的扩展，不改变 store/loader 语义。
- 假设 user-web 前端可引入 vue-flow 依赖（pnpm 工作区新增 `@vue-flow/core`）；其 MIT 许可与仓库既有依赖策略兼容。
- 假设 user-web 页面注册沿用组件式模式（`apps/user-web/src/App.vue` 懒加载注册，非 vue-router），API client 沿用 `apps/user-web/src/api/` 既有模式。
- 假设画布首期只做单租户单用户编辑（无协同、无锁）；并发冲突按"后写覆盖 + 版本号提示"处理。
- 假设 010 的四模式中 supervisor/hybrid 暂不可视化不构成对既有用户的阻塞（当前 dag_definitions 仅注册 competitor_deep_dive 一例 graph 模式）。
- 假设节点可选的 Skill/工具来自既有资产（004 SkillHub / 工具注册），画布不新建资产类型。

## 跨特性关系（被依赖方视角，2026-10-23 双向声明）

- **与 010（dag-orchestration-engine）**：本特性**直接依赖** 010 的 loader/store/registry/topo（消费其装载、持久化、版本化与校验），**不改引擎执行语义**。两处联合改动点需同步 010 spec：① `store.py:_document_shape` 增加 `layout` 透传（T0xx）；② chat-api 新增编排定义读写端点（010 此前无 HTTP API）。除此之外 010 零改动。
- **与 002（session-versioning）**：画布产物走工作流版本化语义——010 FR-8 已声明"编排定义含 `version`、旧版本保留可回看"并与 002 工作流版本化对接；本特性的发布版本化沿用该语义，不新建版本机制（002 的会话级 commit/resume 不适用于编排定义，两者版本化对象不同：会话状态 vs 流程定义）。
- **与 004（skillhub-lifecycle）**：节点可选 Skill——属性面板的 Skill 选择器消费 004 的 Skill 资产与生命周期状态（草稿/已发布态可见性），画布不改变 004 的生命周期规则。
- **与 001（gatekeeper-governance）**：编排产物的权限与门禁——发布过 001 权限码与审批语义，画布不绕过 gatekeeper；审计落点复用 001 通道（发布事件）。
- **与 038（egress-sandbox）**：画布不管控出站——节点内工具执行期的出站检查由 038 在工具调用链落地（执行期治理）；画布只负责定义，两特性在"定义期/执行期"分层，无共同改动文件。
- **与 022（security-hardening）**：画布页面本身遵循 022 既有 Web 安全基线（认证/会话/权限码），不新增例外。

## Non-Goals

- 不实现 supervisor/hybrid 模式的画布可视化（二期；首期 UI 明示不支持）。
- 不实现多人协同编辑/实时画布同步/节点评论（YAGNI；后写覆盖 + 版本提示足够）。
- 不新增第三种编排定义格式（画布 JSON 是内存模型，不是持久化格式）。
- 不实现画布直接执行引擎（执行一律走 010 既有入口，画布不旁路）。
- 不实现编排执行的轨迹回放/可视化调试（属 012 会话回放与 028 轨迹范围）。
- 不合并 user-web 既有 Skill 业务步骤编辑（`MySkillConfigPage`）与编排画布的两套节点语义。
