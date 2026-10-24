# Feature Specification: 评测门禁（发布前硬阈值阻断）

**Feature Branch**: `032-eval-gate`

**Created**: 2026-10-23

**Status**: Draft

**Input**: 整合方案《MOGO × 企业 Agent OS 整合方案》§4.1（治理四道防线①「评测门禁」，整合方案认定的**第一缺口 / 全文最大缺口**）：黄金测试集管理（按 Agent/Skill 维度维护用例集）→ 发布前评测执行 → 硬阈值阻断（幻觉率/拒答率/任务成功率）→ 不达标时 `skill_lifecycle.publish()` 直接拒绝 + 审计事件。

> **设计来源**：本规约把整合方案 §4.1 与 §2.3 防线①的设计要点落成可验收契约。背景事实（2026-10-23 代码级核实）：mogo 当前发布链路**无任何质量卡点**——`skill_lifecycle.publish()` 只做 digest 快照 + 版本号递增（`services/admin-api/app/services/skill_lifecycle.py:39-52`）；016 效果分是事后滚动窗口降权置尾、**不阻断发布**（`services/admin-api/app/services/skill_market/quality_metrics.py:429-476`）；内容评测管线明示 **non-blocking**（`services/chat-api/app/enterprise_capabilities/content/evaluation/pipeline.py:41-46`）；011 仅有自进化侧的 Jaccard/样本量候选过滤（`services/chat-api/app/services/dream_cycle/mr.py`）。
>
> **性质说明**：**全新特性，代码尚未开工**——本文件先于实现落地（与 031 的"回溯补规格"本质不同），后续按 tasks.md 正向推进。

## 定位（一句话）

在 Skill 发布链路 `skill_lifecycle.publish()` 写入版本快照之前插入硬门禁：用租户按 Skill 维度维护的黄金测试集对待发布草稿执行**发布时点**评测，以三项可计算指标（**引用支撑率 / 拒答正确率 / 任务成功率**）对照租户阈值策略判定，不达标时直接拒绝发布（fail-closed）并落审计事件——把"资产腐化"的治理从事后降权（016）**前移为事前阻断**。

## 已定决策（2026-10-23，spec 撰写时拍板）

| # | 决策点 | 结论 | 落点 |
| --- | --- | --- | --- |
| 1 | **「幻觉率」的落地口径（本特性最大澄清点）** | 首期**不直接测量不可证伪的"幻觉率"**，落地为可计算代理指标：**引用支撑率 + 拒答正确率**，加上第三项**任务成功率**。理由：幻觉率无 ground truth 可自动计算（需人工标注或 LLM-as-judge），首期以规则可判定的代理指标保证可验收；LLM-as-judge 列为后续增强 | `eval_gate/judges.py` 判定器 |
| 2 | 阻断强度 | **硬阈值阻断 + 默认 fail-closed**：门禁**不可整体关闭**，租户仅可调阈值松紧；评测执行失败 / 超时 / 无测试集 / 样本不足，一律按阻断处理（与 001 未知权限码 fail-closed 同构） | `eval_gate/gate.py` |
| 3 | 无测试集时的行为 | **阻断**并提示先建测试集（黄金测试集是门禁前提，与整合方案口径一致）；**不提供"跳过门禁"逃生通道**（YAGNI，且逃生通道会稀释治理语义、迟早沦为常开） | `eval_gate/policies.py` |
| 4 | 评测执行位置与 LLM 调用 | admin-api 新模块 `eval_gate/` 内经 `settings.backend_base_url` + `settings.backend_service_token` 调用 **chat-api 模型网关**执行用例，**复用 007 韧性**（重试/退避/超时分类由 chat-api 侧网关负责）；admin-api **不引入新 LLM 客户端、不引入新网络库**（沿用 `urllib` + `asyncio.to_thread` 既有范式） | `eval_gate/executor.py` |
| 5 | 判定器形态 | 首期为**规则判定**（引用存在性、拒答话术/低置信信号、用例期望要点匹配），确定性可复现；**不引入 LLM-as-judge**（YAGNI，二期） | `eval_gate/judges.py` |
| 6 | 样本量门槛 | 复用 011 思想：用例数 < **5**（对齐 `services/chat-api/app/self_evolution/similarity.py` 的 `DEFAULT_MIN_SAMPLES`）时评测结论 insufficient，按 fail-closed 阻断 | `eval_gate/policies.py` |
| 7 | 执行时序 | **同步执行**：`publish()` 请求内完成评测（版本号唯一性检查**之后**、release 落库**之前**）；单次用例上限（默认 50）与整体超时（默认 300s）可配，超限按失败 fail-closed；**不引入任务队列** | `skill_lifecycle.py` 挂卡点 |
| 8 | 审计落点 | 复用 001 审计汇聚点 **`gate_events` 集合**（与 `services/admin-api/app/governance/layers/audit.py` 同库同集合），事件类型 `eval_gate.passed` / `eval_gate.blocked`；publish 不是工具调用，**不挂六层门禁链**，只复用同一审计汇聚点，不新建审计集合 | `eval_gate/gate.py` |
| 9 | 与 016 的数据关系 | 032 **不写** 016 的 `skill_quality_metrics` 日桶（那是运行时滚动聚合），发布时点评测结果落**新集合 `skill_eval_runs`**；036 可信评级消费 `skill_eval_runs` | `eval_gate/models.py` |
| 10 | dry-run 试运行 | 提供**不阻断的试运行端点**（结果标记 `dry_run`），供发布前预览；dry-run 不产生发布、不落阻断审计 | `api/routes/skill_eval.py` |
| 11 | 评测记录的内容边界 | `skill_eval_runs.case_results` 只存**判定摘要与理由**，不存完整 LLM 输出，避免评测库成为业务数据副本（Security & Data Protection） | `eval_gate/executor.py` |

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 黄金测试集管理（按 Skill 维度）（Priority: P1）

租户管理员按 Skill 维度维护黄金测试集：每条用例 = 输入 + 期望要点 + 期望引用来源 + 应拒答标记（可附 agent 标签分组）。测试集是门禁的输入前提，经 CRUD API 维护，按租户严格隔离。

**Why this priority**: 测试集是门禁的输入前提——没有它门禁只能 fail-closed 全量阻断，US2 的验收（构造低于阈值 Skill）依赖本故事先落地。但优先级不高于 US2：它是使能器而非价值本身。

**Independent Test**: 直接对测试集 CRUD API 发请求：创建 → 查询 → 更新 → 删除，断言按 `(tenant_id, skill_id)` 隔离、跨租户不可见、用例可带 agent 标签过滤。

**Acceptance Scenarios**:

1. **Given** 某 Skill 无测试集，**When** 创建 3 条用例，**Then** 查询返回 3 条且全部归属该 Skill 与本租户。
2. **Given** 已存在用例，**When** 更新其中一条的期望引用来源，**Then** 再次查询反映更新内容。
3. **Given** 其他租户存在同名 Skill，**When** 本租户查询，**Then** 只能看到本租户的测试集（租户隔离，无越权读取）。
4. **Given** 用例带 agent 标签，**When** 按标签查询，**Then** 返回该标签分组用例；标签仅作分组，不改变门禁判定口径。

---

### User Story 2 - 发布前评测执行与硬阈值阻断（Priority: P1）🎯 核心验收

平台治理方视角：`publish()` 在写入版本快照前对待发布草稿执行评测，三项可计算指标低于租户阈值时**直接拒绝发布**（不生成 release 记录）并落审计事件；全部达标才放行。

**Why this priority**: 这是整个特性的核心价值——整合方案认定的"第一缺口"，把发布链路的质量卡点从无到有。验收口径即整合方案原文：构造低于阈值的 Skill，`publish()` 返回阻断且审计可查。

**Independent Test**: 构造低于阈值的 Skill（测试集中多数用例不达标）调用 `POST /api/skills/{id}/publish`，断言返回 4xx 阻断、`organization_skill_releases` 无新记录、`gate_events` 有 `eval_gate.blocked` 事件且含指标明细；再构造全达标 Skill 断言发布成功且有 `eval_gate.passed` 事件。

**Acceptance Scenarios**:

1. **Given** 三项指标中任一低于租户阈值的 Skill，**When** 调 `publish()`，**Then** 返回 4xx 阻断（含未达标指标与阈值对照），`organization_skill_releases` 不产生新记录，`gate_events` 落 `eval_gate.blocked` 事件。
2. **Given** 三项指标全部达标的 Skill，**When** 调 `publish()`，**Then** 正常生成 release 快照（digest + 版本号），`gate_events` 落 `eval_gate.passed` 事件含指标明细。
3. **Given** 某指标恰等于阈值，**When** 判定，**Then** 判为通过（`>=` 口径，边界从严不误伤）。
4. **Given** 评测执行中 LLM 网关超时/不可用，**When** 调 `publish()`，**Then** 按 fail-closed 阻断，不静默放行、不返回空结果。
5. **Given** 测试集为空或用例数 < 5，**When** 调 `publish()`，**Then** fail-closed 阻断并提示补充测试集（样本不足）。

---

### User Story 3 - 阈值策略租户可配与评测报告展示（Priority: P2）

租户管理员按租户配置三项指标阈值（默认 fail-closed 策略）；发布对话框展示最近一次评测报告（试运行或上次发布），阻断时高亮未达标指标与阈值对照，使阻断可解释、可行动。

**Why this priority**: 策略可配让门禁适配不同质量基线；报告展示把"黑盒阻断"变为"可行动指引"。低于 US1/US2，因为不阻塞核心门禁链路本身。

**Independent Test**: 修改租户阈值后重新判定，断言行为随阈值变化；前端用 `@vue/compiler-sfc` 编译 `SkillPublishDialog.vue` 通过，手动核对阻断场景展示未达标指标与阈值对照。

**Acceptance Scenarios**:

1. **Given** 租户未配置过策略，**When** 查询，**Then** 返回默认策略：三项指标有默认阈值、门禁启用（fail-closed）、无整体关闭开关。
2. **Given** 收窄某指标阈值，**When** 重新评测同一 Skill，**Then** 判定结果随阈值变化（原达标变为不达标）。
3. **Given** 发布被阻断，**When** 打开发布对话框，**Then** 展示最近评测报告的未达标指标与阈值对照（哪项、实测值、阈值）。
4. **Given** 点击「试运行评测」，**When** 执行完成，**Then** 展示评测报告且不产生发布、不落阻断审计事件。

---

### Edge Cases

- **用例类型分支**：标记「应拒答」的用例只计入**拒答正确率**，不计入任务成功率分母；期望引用为空的用例不参与引用支撑率分母——两类分支口径在判定器中显式实现，避免指标互相污染。
- **版本号重复优先**：`publish()` 先做版本号唯一性检查（既有 409），再跑门禁——避免为非法版本浪费一次 LLM 评测。
- **超大测试集**：用例数超上限（默认 50）时创建被拒（400），防止发布请求被超大测试集拖死超时。
- **评测整体超时**（默认 300s）：按失败 fail-closed 阻断，超时本身不是"通过"的证据（与内容评测管线 "A timeout is not evidence that the content passed" 的口径一致）。
- **并发发布同一 Skill**：既有版本唯一约束兜底；门禁不引入额外锁（YAGNI）。
- **拒答信号来源**：输出命中拒答话术或知识问答低置信拒答（参考 `services/chat-api/app/knowledge/agents/knowledge_qa_agent.py` 的拒答机制）；引用信号参考 `services/chat-api/app/knowledge/citations/citation_resolver.py` 的引用解析机制。
- **存量 Skill 首次发布**：无历史测试集的存量 Skill 同样被阻断（fail-closed 一致语义），管理员需先补测试集——这是治理基线从 0 到 1 的预期代价。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 系统 MUST 提供测试集 CRUD API，按 `(tenant_id, skill_id)` 隔离；用例 MUST 含 `input` / `expectations` / `expected_refs` / `expect_refusal`，可附 `agent_tag`。
- **FR-002**: 测试集用例数 MUST 有上限（默认 50，可配），超限创建被拒（400）。
- **FR-003**: `skill_lifecycle.publish()` MUST 在 release 落库前调用评测门禁；不达标时直接拒绝且**不产生 release 记录**（skill 保持已发布态不变）。
- **FR-004**: 评测执行器 MUST 经 chat-api 模型网关（`settings.backend_base_url` + `settings.backend_service_token`）执行用例，**复用 007 韧性**隔离重试与超时，不在 admin-api 重复实现重试逻辑。
- **FR-005**: 系统 MUST 计算三项指标——引用支撑率、拒答正确率、任务成功率——由**确定性规则判定器**产出（引用存在性、拒答话术、期望要点匹配）。
- **FR-006**: 阈值策略 MUST 租户可配（`skill_eval_policies` 集合），**默认 fail-closed**；门禁 MUST NOT 提供整体关闭开关。
- **FR-007**: 无测试集或用例数 < 5（对齐 011 `DEFAULT_MIN_SAMPLES`）时，MUST fail-closed 阻断并提示补充测试集。
- **FR-008**: 阻断与放行 MUST 都落审计事件（`gate_events`，`event_type=eval_gate.passed|blocked`），含 `skill_id`、版本、三项指标实测值、阈值、判定结论。
- **FR-009**: 评测运行记录 MUST 落 `skill_eval_runs`（含逐用例判定摘要、三项指标、耗时、`dry_run` 标记）；**不存完整 LLM 输出**。
- **FR-010**: 系统 MUST 提供 dry-run 试运行端点：执行评测并返回报告，不阻断、不产生发布、不落阻断审计。
- **FR-011**: 评测 MUST 同步执行且有整体超时（默认 300s，可配）；超时/失败按 fail-closed 阻断，不静默放行。
- **FR-012**: admin-web 发布对话框 MUST 展示最近一次评测报告；阻断时 MUST 高亮未达标指标与阈值对照，并提供试运行评测入口。

## Key Entities

- **EvalCase（黄金测试用例）**: `{id, tenant_id, skill_id, agent_tag, input, expectations, expected_refs, expect_refusal, created_at}`——测试集条目，存 `skill_eval_cases`。
- **EvalPolicy（阈值策略）**: `{tenant_id, skill_id?, min_citation_support, min_refusal_accuracy, min_task_success, min_cases, max_cases, timeout_seconds, updated_at}`——租户级（可下钻 Skill 级）阈值，存 `skill_eval_policies`；门禁恒启用。
- **EvalRun（评测运行记录）**: `{id, tenant_id, skill_id, version, dry_run, metrics{citation_support, refusal_accuracy, task_success}, passed, blocked_reason, case_results[], duration_ms, created_at}`——发布时点（或 dry-run）的一次评测产出，存 `skill_eval_runs`；036 可信评级消费本实体。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 构造低于阈值的 Skill → `publish()` 返回 4xx 阻断，`organization_skill_releases` 无新记录，`gate_events` 可查 `eval_gate.blocked` 事件及三项指标明细。
- **SC-002**: 全部达标的 Skill → `publish()` 正常生成 release，`gate_events` 可查 `eval_gate.passed` 事件。
- **SC-003**: 默认策略 fail-closed；租户修改阈值后判定行为随之变化；全系统无"关闭门禁"入口。
- **SC-004**: 三条 fail-closed 路径（无测试集 / 样本不足 <5 / LLM 不可用超时）均有单测覆盖且全部阻断。
- **SC-005**: 三项指标计算有单测覆盖，含边界：等于阈值通过、拒答类不计入任务成功率分母、空期望引用不参与支撑率分母。
- **SC-006**: `SkillPublishDialog.vue` SFC 编译通过；阻断场景下报告展示未达标指标与阈值对照。

## Assumptions

- 假设 chat-api 模型网关可经 `backend_base_url` 服务调用（admin-api 已有 `backend_service_token` 服务间凭据，`services/admin-api/app/core/config.py`）；具体端点契约由 Phase 0 研究确认（tasks T002）。
- 假设引用信号与拒答信号可从用例执行输出结合既有引用/拒答机制获得（`services/chat-api/app/knowledge/citations/citation_resolver.py`、`services/chat-api/app/knowledge/agents/knowledge_qa_agent.py`）。
- 假设首期判定器为规则判定；LLM-as-judge 为后续增强，不进本特性。
- 假设评测同步执行、不引入任务队列；publish 请求延迟随用例数增长（默认上限 50、超时 300s）。
- 假设 admin-web 发布对话框既有挂载于 `SkillConfigPage.vue`（`apps/admin-web/src/views/skills/SkillConfigPage.vue` 引用 `SkillPublishDialog.vue`），报告展示在该组件内增量实现。

## 跨特性关系（被依赖方视角，2026-10-23 双向声明）

- **与 016（skill-market-hardening）**：016 效果分（`quality_metrics.py` 滚动窗口聚合）是**事后**降权置尾，与本特性**发布时点**门禁互补而非替代；本特性**不写** 016 的 `skill_quality_metrics` 日桶，只新增 `skill_eval_runs`。016 的 spec 把"市场强化"限定在监控/打分/灰度/标记，不包含发布阻断，本特性补齐该缺口。
- **与 004（skillhub-lifecycle）**：本特性在 004 的 `publish()`（`services/admin-api/app/services/skill_lifecycle.py:39-52`）**挂卡**，不改变 004 的草稿/版本/快照契约，仅在写入 release 前增加门禁判定；004 的 Non-Goals 曾把"市场强化"划归后续特性，本特性即该边界内的发布质量层。
- **与 001（gatekeeper-governance）**：本特性**复用 001 审计汇聚点** `gate_events`（`services/admin-api/app/governance/layers/audit.py`），不挂六层门禁链（publish 不是工具调用）、不新建审计集合；001 的 fail-closed 语义（未知权限码拒绝）是本特性门禁默认值的设计参照。
- **与 011（dream-cycle-self-evolution）**：本特性借鉴 011 的**样本量门槛思想**（`services/chat-api/app/self_evolution/similarity.py` `DEFAULT_MIN_SAMPLES=5`），门禁最小用例数取值与其对齐；011 的自进化草稿经 004 发布时同样受本门禁约束（上游质量责任前移）。
- **与 007（llm-gateway-resilience）**：评测执行的 LLM 调用**复用 007 韧性**（`services/chat-api/app/llm/resilience/retry.py` 的重试/退避/超时分类），本特性不在 admin-api 重复实现重试；这是整合方案 §4.1 风险条（"评测执行依赖 LLM 调用，需隔离重试与超时"）的落地口径。
- **与 036（可信评级，规划中）**：036 消费本特性产出的 `skill_eval_runs` 实现"连续 3 周评测不达标自动降级"；**本特性只负责产出评测数据与发布阻断，不实现降级逻辑**——双向边界在此声明，036 立项时须以 `skill_eval_runs` 为数据源。

## 判定口径补充（2026-10-23，`/speckit-checklist` 回填）

以下 13 条补齐 checklist 识别出的需求缺口，作为实现与验收的一等口径（与 FR 同效力）。

- **R-1 分母为 0 的指标口径**：当某指标的适用用例数为 0（全部用例无 `expected_refs` / 无 `expect_refusal` / 无 `expectations`）时，该指标 MUST 记为"不适用"（`null`）并**跳过阈值比较**，不得按 `0.0` 阻断——否则一个全部为拒答用例的测试集会因"引用支撑率 0"被误杀。`skill_eval_runs.metrics` 因此允许 `null` 值。
- **R-2 拒答话术词表**：判定器 MUST 以显式词表判定拒答，最小必需集合为"无法回答 / 不能回答 / 不便提供 / 不予回答 / 抱歉 / 对不起 / i cannot / i can't / unable to / cannot answer / not enough information / insufficient information"（大小写不敏感，**命中任一即判拒答**）；词表随判定器维护，MUST 有单测锁定。
- **R-3 expectations 匹配语义**：每个 `expectation` MUST 以子串形式（大小写不敏感）出现在输出中，**AND 语义（全部命中才算任务成功）**；`expectations` 为空的用例不计入任务成功率分母。
- **R-4 dry-run 产出边界**：dry-run MUST 落 `skill_eval_runs`（`dry_run=true`）供前端回看，MUST NOT 落 `gate_events`；低于阈值时返回 **200 + `passed=false` + 指标/阈值明细**，不返回 4xx（试运行不阻断）。
- **R-5 策略默认值表**：`min_citation_support=0.6`、`min_refusal_accuracy=0.6`、`min_task_success=0.6`、`min_cases=5`、`max_cases=50`、`timeout_seconds=300`；六项 MUST 均可按租户级（`skill_id` 为空）或 Skill 级配置，Skill 级优先；策略文档 MUST NOT 含 `enabled` 之类关闭开关字段。
- **R-6 单用例超时与整体超时**：admin-api 侧单用例等待上限默认 60s（含 chat-api 侧 007 重试耗时），整体上限默认 300s；每用例实际超时 MUST 取 `min(60s, 剩余整体预算)`，整体预算耗尽按超时 fail-closed。
- **R-7 阻断状态码分层**：指标不达标 / 无测试集 / 样本不足 / 用例超上限 MUST 返回 **409**（提示补数据或调阈值）；网关不可用 / 整体超时 MUST 返回 **502**（提示稍后重试）；审计写入失败 MUST 返回 **503**。前端依状态码区分"补数据"与"重试"两类引导。
- **R-8 expected_refs 匹配粒度**：`expected_refs` 元素 MAY 为 `document_id` 或 `document_id:chunk_id` 复合串（与 `citation_resolver.py` 的 citation id 同形）；匹配 MUST 为"输出文本子串包含"（大小写不敏感），空数组不参与分母。
- **R-9 审计写入失败 fail-closed**：`gate_events` 写入失败时 MUST 阻断发布（与 001 `audit.py` 落库异常判 DENY 的语义一致），对应 R-7 的 503；不得"审计失败仍放行"。
- **R-10 gate_events 字段映射**：事件 MUST 复用 001 既有字段 `event_id`/`occurred_at`/`tenant_id`/`decision`/`layer`/`reason`/`detail`，并补 `skill_id`/`skill_version`/`event_type`/`metrics`/`thresholds`；其中 `decision` 取 `"blocked"|"passed"`，与 001 六层链的 `ALLOW/DENY` **不同枚举**——故本特性的 `eval_gate.*` 事件 MUST NOT 参与六层链判定，消费方 MUST 先按 `event_type` 前缀过滤。
- **R-11 对 036 的消费契约**：036 消费 `skill_eval_runs` 的 `tenant_id`/`skill_id`/`passed`/`metrics`/`created_at` 五个字段；本特性 MUST 保证这五个字段只增不改（新增字段不改变其语义）。
- **R-12 凭据传递不锁定头名**：FR-004 的 `backend_service_token` 只约束"服务间凭据来源"，具体头名与令牌形态 MUST 以 chat-api 模型网关的实际契约（T002 研究确认的 `Authorization: Bearer` + NDJSON 流）为准，spec 不锁定 HTTP 头名以免与网关演进冲突。
  - **R-12.1 令牌形态澄清（实现确认）**：chat-api 网关只接受 HMAC 签名令牌（`b64url(payload).b64url(hmac_sha256(sha256(secret)))`，`aud=askai-model-gateway`，900s 有效，见 `services/chat-api/app/dsh_runtime/model_gateway/token.py`），**不接受** `app/security/service_token.py` 的 `v1|<payload>|<mac>` 服务令牌；admin-api 侧由 `eval_gate/gateway_auth.py` 用共享密钥（`ASKAI_ADMIN_DSH_MODEL_GATEWAY_SIGNING_SECRET`，缺省回落到两服务共享的 `ASKAI_ADMIN_JWT_SECRET`）签发，密钥缺失或短于 16 字符时 MUST 显式报错而非发出注定被 401 的令牌。
  - **R-12.2 请求体字段齐备**：`ModelGatewayRequest` 为 `extra="forbid"`，请求体 MUST 恰好携带 `profileVersion`/`modelInstanceId`/`provider`（恒为 `askai-model-gateway`）/`model`/`messages` 五个字段，且前三个 MUST 与令牌 claims 完全一致（否则 `profile_scope_mismatch`/`model_scope_mismatch`/`provider_scope_mismatch`）；不得发送 `stream` 字段。
- **R-13 用例上限与并发取舍**：创建期（400）与执行期（409）使用同一 `max_cases`；执行期超限仅作历史数据/降配场景的防御。并发发布同一 Skill MUST 接受"各跑一次评测（双倍 LLM 成本）"这一既定取舍——不引入评测锁（YAGNI），正确性由既有版本唯一约束兜底。

## Non-Goals

- 不做 LLM-as-judge 语义评判（首期规则判定，确定性优先）。
- 不做测试集自动生成（不从历史流量自动沉淀黄金用例）。
- 不做 Agent 维度独立测试集（仅 Skill 维度 + 用例 `agent_tag` 标签分组）。
- 不改 016 的事后降权/低质标记/效果分语义。
- 不做评测调度平台与批量评测 UI（仅发布时点评测 + dry-run 试运行）。
- 不提供跳过门禁的逃生通道/临时关闭开关。
- 不改造内容评测管线（`services/chat-api/app/enterprise_capabilities/content/evaluation/pipeline.py` 的 non-blocking 语义保持不变，两者服务不同阶段）。
