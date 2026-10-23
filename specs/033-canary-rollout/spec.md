# Feature Specification: 资产发布管控增强（比例灰度 + 影子发布）

**Feature Branch**: `033-canary-rollout`

**Created**: 2026-10-23

**Status**: Draft

**Input**: 整合方案《MOGO × 企业 Agent OS 整合方案》§4.2（治理四道防线②「发布管控」）：把 016 canary 从"按租户灰度"扩展到"按比例阶梯"（1%→10%→50%→100% 可配置）+ 影子模式（只跑不生效，影子流量不计入用户结果，复用 011 `apply_shadow` 思路做实）。

> **设计来源**：本规约把整合方案 §4.2 与 §2.3 防线②的设计要点落成可验收契约。背景事实（2026-10-23 代码级核实）：016 已实现按租户 canary + 错误率 >20% 且样本 ≥20 自动回滚 + 5 分钟周期扫描（`services/admin-api/app/services/skill_market/canary.py`、`services/admin-api/app/api/routes/skill_canary.py`）；016 spec 明示"首期按租户，**按比例/按用户为后续扩展**"；影子模式目前仅 011 自进化有轻量标记（`services/chat-api/app/services/dream_cycle/runner.py:102-126`，`DEFAULT_SHADOW_RATIO=0.1`）；024 的灰度回滚属 Docker 镜像部署层且自述"不存在灰度通道"（其回滚为版本回退演练）。
>
> **性质说明**：**全新特性，代码尚未开工**——本文件先于实现落地（与 031 的"回溯补规格"本质不同），后续按 tasks.md 正向推进。

## 定位（一句话）

在 016 既有按租户 canary 之上增加两个发布管控维度——**按比例阶梯灰度**（`traffic_ratio` 1%→10%→50%→100% 可配置阶梯，样本与异常率达标自动推进）与**影子发布**（影子流量双跑只记录不返回、不计入用户结果与回滚判定）——让 Agent/Skill 新版本发布从"按租户粗粒度"细化为"可控比例渐进 + 零风险预跑"，异常率超阈值自动回滚与手动一键回滚能力完整保留。

## 已定决策（2026-10-23，spec 撰写时拍板）

| # | 决策点 | 结论 | 落点 |
| --- | --- | --- | --- |
| 1 | 与 016 的边界 | **只加维度、不改语义**：`Rollout` 增加 `traffic_ratio` 与阶梯字段；`evaluate_canary` / `apply_rollback` / `CanaryRollbackScanner`（20% 阈值 + 20 样本 + 5 分钟扫描）**原样复用**，不新造阈值体系 | `skill_market/canary.py` |
| 2 | tenants 与 ratio 叠加口径 | 两维**可叠加**：`target_tenants` 限定租户子集，`traffic_ratio` 在子集内按用户分流；两者皆空 = 100% 全量 | `Rollout` 字段 + 分流函数 |
| 3 | 分流粒度与粘滞 | 按 `(tenant_id, user_id)` **确定性哈希取模**分流，同一用户在整个灰度期内版本一致（粘滞）；纯函数、无需额外存储 | 分流纯函数 |
| 4 | 阶梯默认值与推进条件 | 默认 **1%→10%→50%→100%** 可配置；推进需当前档样本 ≥ `min_samples`（20）且异常率 ≤ `threshold`（20%），由既有 5 分钟扫描循环自动评估；**手动推进与手动回滚保留** | 阶梯推进器 + scanner |
| 5 | 影子模式语义 | 影子流量 = **未命中 ratio 的用户**双跑候选版本，结果**只记录不返回**；**不计入** `Rollout.call_count/error_count`（影子失败不触发回滚），影子指标仅观察 | chat-api 分流点 + `skill_shadow_runs` |
| 6 | 影子比例默认 | 复用 011 `DEFAULT_SHADOW_RATIO=0.1`（`services/chat-api/app/services/dream_cycle/runner.py:20`）作为影子模式默认 ratio 参考值，租户可配 | 影子配置 |
| 7 | 与 024 的边界 | **024 管 Docker 镜像/服务部署层**灰度（nginx 网关分流、版本回退演练），**本特性管 Agent 资产（Skill 版本）发布层**灰度；两层互不依赖、互不影响，指标口径不互相定义 | — |
| 8 | `PROMOTED` 状态启用 | 阶梯推进到 100% 且样本/异常率稳定后，`RolloutState.PROMOTED`（既有枚举值）置位，灰度结束 | 阶梯推进器 |
| 9 | 影子执行隔离 | 影子执行异常/超时**一律吞并并记录**，绝不影响用户请求路径（用户请求只由稳定版响应） | chat-api 分流点 |
| 10 | 存量数据兼容 | `skill_rollouts` 旧行无 `traffic_ratio` 等新字段时，读取默认 `ratio=1.0`、`shadow=false`——016 既有按租户灰度行为**不回退** | `_row_to_rollout` |

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 按比例阶梯灰度创建与自动推进（Priority: P1）🎯 MVP

运营者创建灰度时除租户外可指定 `traffic_ratio` 与阶梯（默认 1%→10%→50%→100%）：系统按 `(tenant_id, user_id)` 确定性哈希把子集内流量按当前档比例分流到候选版本；每档样本 ≥20 且异常率 ≤20% 时由 5 分钟扫描循环自动推进到下一档，直到 100% 置 `PROMOTED`；样本不足则停在当前档等待。

**Why this priority**: 这是整合方案 §4.2 的核心增量——把"按租户一刀切"细化为比例渐进，直接对齐文章防线②的"灰度 1%→10%→50%→100%"要求；也是影子模式（US2）与配置页（US4）的展示载体。

**Independent Test**: 契约测试直接驱动推进器：注入样本/异常率序列，断言档位按条件推进（样本不足停档、达标推进、到 100% 置 promoted）；分流函数单测断言确定性与比例近似。

**Acceptance Scenarios**:

1. **Given** 创建 `traffic_ratio=0.01` 且 ladder 为默认四档的灰度，**When** 首批流量进入，**Then** 约 1% 的（租户子集内）用户被分流到候选版本，且同一用户多次请求分配结果一致。
2. **Given** 当前档样本 ≥20 且异常率 ≤20%，**When** 扫描循环评估，**Then** 自动推进到下一档（`traffic_ratio` 更新、档位历史落库）。
3. **Given** 当前档样本 <20，**When** 扫描循环评估，**Then** 停在当前档不推进（与 016 FR-10 小样本保护一致）。
4. **Given** 阶梯推进到 100% 且稳定，**When** 扫描循环评估，**Then** rollout 状态置 `PROMOTED`，灰度结束。

---

### User Story 2 - 影子发布：只跑不生效（Priority: P1）

运营者对候选版本开启影子模式：未命中灰度比例的用户在获得稳定版响应的同时，系统对其请求**双跑**候选版本，候选结果只记录不返回、不计入用户结果；影子执行异常被隔离吞并，不影响用户请求，也不触发回滚。

**Why this priority**: 影子模式是"零风险预跑"的载体——在不影响任何用户的前提下积累候选版本的真实表现数据，是比例灰度决策（推/回）的依据来源；与 US1 共同构成整合方案 §4.2 的完整形态。

**Independent Test**: 契约测试模拟一次带影子开启的请求：断言用户响应 100% 来自稳定版；`skill_shadow_runs` 有对应记录；影子执行抛异常时用户请求仍成功且回滚判定不受影响。

**Acceptance Scenarios**:

1. **Given** 影子模式开启且用户未命中灰度比例，**When** 用户请求到达，**Then** 用户收到稳定版响应，同时候选版本被双跑执行，结果落 `skill_shadow_runs` 且不返回给用户。
2. **Given** 影子执行超时或抛异常，**When** 用户请求到达，**Then** 用户请求正常完成（稳定版响应），异常被记录，不影响用户路径。
3. **Given** 影子执行连续失败，**When** 扫描循环评估回滚，**Then** 影子失败**不触发**回滚（不计入 `call_count/error_count`）。
4. **Given** 用户命中灰度比例（真实走候选版），**When** 请求到达，**Then** 直接返回候选版结果，无需再影子双跑。

---

### User Story 3 - 异常自动回滚与手动一键回滚（Priority: P1）

灰度（含比例维度）进行中，候选版本错误率 >20% 且样本 ≥20 时自动回滚到上一已发布稳定版本；运营者也可随时手动一键回滚。既有 016 的回滚语义与路由完整保留，扩展到比例维度后依然生效。

**Why this priority**: 回滚是"敢发布"的底线能力——整合方案 §4.2 验收口径明示"异常一键回滚（已有手动回滚需保留）"；自动回滚 + 手动回滚双通道是止血的最后防线。

**Independent Test**: 契约测试回归 016 既有回滚用例（20%/20 自动回滚、手动 `POST /{skill_id}/rollback`）+ 新增比例维度用例（ratio 灰度下回滚后 ratio 归零、状态 `rolled_back`、`stable_version` 指向上一已发布稳定版）。

**Acceptance Scenarios**:

1. **Given** 比例灰度进行中且候选版错误率 >20% 且样本 ≥20，**When** 扫描循环评估，**Then** 自动回滚：状态置 `rolled_back`、流量切回稳定版、回滚记录可查（含错误率与原因）。
2. **Given** 灰度进行中，**When** 运营者调手动一键回滚，**Then** 立即回滚到上一已发布稳定版本，`traffic_ratio` 归零，记录可查。
3. **Given** 样本 <20，**When** 扫描循环评估，**Then** 即使错误率高也不自动回滚（小样本保护）。
4. **Given** 回滚完成，**When** 查询 rollout，**Then** 可见回滚前/后版本与触发原因（016 FR-7 可追溯口径）。

---

### User Story 4 - admin-web 灰度配置页（Priority: P2）

运营者在 admin-web 灰度配置页完成：创建/查看灰度（租户 + 比例阶梯 + 影子开关）、查看当前档位与推进历史、查看影子统计、一键回滚。

**Why this priority**: 配置页是前三能力（US1-US3）的运营入口，没有它所有能力只能走 API；优先级低于核心机制，因为它不改变管控语义本身。

**Independent Test**: `@vue/compiler-sfc` 编译灰度配置页通过；手动核对：阶梯与影子可配置、进度与影子统计可见、一键回滚可用。

**Acceptance Scenarios**:

1. **Given** 打开某 Skill 的灰度配置页，**When** 查看，**Then** 展示当前 rollout 状态、当前档位、推进历史与影子统计（影子调用数/成功率）。
2. **Given** 创建灰度时选择比例模式，**When** 提交，**Then** 阶梯（默认四档可改）与影子开关随配置生效。
3. **Given** 灰度进行中，**When** 点「一键回滚」，**Then** 调用既有手动回滚路由并展示回滚结果。

---

### Edge Cases

- **`traffic_ratio` 非法值**：`ratio=0` 或 `>1` → 创建/更新校验拒绝（400），不进分流逻辑。
- **阶梯推进中样本不足**：停在当前档等待，不推进、不回滚（与 016 FR-10 小样本保护同构）。
- **灰度中再次创建同 Skill rollout**：`replace_one` upsert 替换（既有行为保留），旧档位历史保留在 `ladder_history` 字段中可查。
- **回滚目标**：`stable_version` = 该 Skill 上一已发布稳定版本（016 FR-13 口径）；回滚后 `traffic_ratio` 归零、状态 `rolled_back`。
- **影子与比例同时开启**：命中比例的用户真实走候选版（直接返回，不再影子双跑）；未命中用户在稳定版响应外双跑候选版（只记录）——决策表第 5 条语义。
- **影子执行崩溃/超时**：吞并并记录，用户请求无感（绝不影响用户路径）。
- **存量 `skill_rollouts` 行无新字段**：读取默认 `ratio=1.0`、`shadow=false`，016 既有按租户灰度行为不回退（决策表第 10 条）。
- **租户灰度与比例灰度并存于同一 Skill**：叠加语义（租户子集内按比例分流），文档与 API 明示，不提供第三种互斥模式（YAGNI）。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `Rollout` MUST 增加 `traffic_ratio`（0 < ratio ≤ 1）与阶梯字段（`ladder` / `current_step` / `ladder_history` / `shadow_enabled`）；既有 `target_tenants` / `state` / `error_count` / `call_count` / `stable_version` 语义 MUST 不变。
- **FR-002**: 灰度定位 MUST 支持 `target_tenants`、`traffic_ratio` 及两者叠加；两者皆空 = 100% 全量。
- **FR-003**: 分流 MUST 按 `(tenant_id, user_id)` 确定性哈希取模实现，同一用户在整个灰度期内版本一致（粘滞）；MUST 为可单测的纯函数。
- **FR-004**: 阶梯推进器 MUST 按默认 1%→10%→50%→100%（租户可配置）在当前档样本 ≥ `min_samples` 且异常率 ≤ `threshold` 时自动推进；样本不足 MUST NOT 推进。
- **FR-005**: 阶梯当前档位与推进历史 MUST 落库（`skill_rollouts` 扩展字段），可查询。
- **FR-006**: 影子模式 MUST 对未命中比例的用户双跑候选版本，结果只记录不返回，MUST NOT 计入用户结果。
- **FR-007**: 影子执行 MUST 隔离：异常/超时吞并并记录，MUST NOT 影响用户请求路径。
- **FR-008**: 影子执行记录 MUST 落 `skill_shadow_runs`（`skill_id` / `version` / `tenant_id` / `user_id` / 耗时 / 结果 / 错误），MUST NOT 参与回滚判定。
- **FR-009**: 自动回滚 MUST 保留既有口径（异常率 > 20% 且样本 ≥ 20 → `rolled_back`）；影子失败 MUST NOT 触发回滚。
- **FR-010**: 手动一键回滚 MUST 保留（`services/admin-api/app/api/routes/skill_canary.py` 的 `POST /{skill_id}/rollback` 路由与语义不变）。
- **FR-011**: 阶梯推进到 100% 且样本/异常率稳定后，rollout MUST 置 `RolloutState.PROMOTED`。
- **FR-012**: canary 路由 MUST 扩展创建/查询参数（`traffic_ratio` / `ladder` / `shadow`）；查询 MUST 返回当前档位、推进历史与影子统计。
- **FR-013**: admin-web MUST 提供灰度配置页：阶梯与影子配置、进度与影子统计查看、一键回滚。
- **FR-014**: 契约测试 MUST 覆盖：阶梯推进（含样本不足停档）、影子双跑不污染用户结果与回滚判定、自动/手动回滚、分流确定性与存量行兼容。

## Key Entities

- **Rollout（扩展，`skill_rollouts`）**: `{skill_id, version, stable_version, target_tenants, traffic_ratio, ladder[], current_step, ladder_history[], shadow_enabled, state, error_count, call_count, updated_at}`——一次灰度发布的完整状态；`ladder_history` 记录每档进入/推进时间与当时指标。
- **LadderStep**: `{ratio, min_samples?, entered_at, promoted_at?}`——阶梯中的一档；`min_samples` 可档位覆盖（缺省用全局 20）。
- **ShadowRun（`skill_shadow_runs`）**: `{skill_id, version, tenant_id, user_id, duration_ms, ok, error, created_at}`——一次影子双跑的观察记录，只写不读回用户路径。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 契约测试：分流确定性（同一用户多次分配结果一致）且大样本下比例近似（偏差在统计容差内）；`target_tenants` 与 `traffic_ratio` 叠加语义正确。
- **SC-002**: 契约测试：阶梯按条件推进——样本不足停在当前档；达标推进 1%→10%→50%→100%；到 100% 稳定后置 `PROMOTED`；推进历史可查。
- **SC-003**: 契约测试：影子双跑下用户结果 100% 来自稳定版；`skill_shadow_runs` 有记录；影子执行失败不触发回滚、不影响用户请求。
- **SC-004**: 契约测试：错误率 >20% 且样本 ≥20 自动回滚触发；手动一键回滚一键完成；两者记录（前/后版本、原因）均可查。
- **SC-005**: 存量兼容：无 `traffic_ratio` 字段的 `skill_rollouts` 行读取默认 100%，016 既有按租户灰度与回滚用例零回归。
- **SC-006**: admin-web 灰度配置页 SFC 编译通过；阶梯/影子配置、进度与影子统计查看、一键回滚可手动走通。

## Assumptions

- 假设 Skill 调用入口（chat-api `dsh_runtime`）可获取 `tenant_id` / `user_id`（门禁链身份上下文已有），分流点由 Phase 0 研究确认（tasks T002）。
- 假设哈希分流无需额外存储（确定性纯函数），灰度期内用户集合稳定（用户 id 不变）。
- 假设 016 的 20% / 20 样本 / 5 分钟扫描口径延续，本特性不新造阈值体系。
- 假设影子双跑的执行成本（双倍 LLM 调用）由租户**显式开启**影子时承担，默认关闭。
- 假设 admin-web 灰度配置页为新增页面，复用既有 naive-ui 组件与 skills API client 模式（`apps/admin-web/src/api/skills.ts`）。
- 假设 `stable_version`（上一已发布稳定版本）在创建灰度时由创建方提供或从 004 发布记录推导，具体口径在 Phase 1 设计定稿（tasks T005）。

## 跨特性关系（被依赖方视角，2026-10-23 双向声明）

- **与 016（skill-market-hardening）**：**直接扩展对象**。本特性不改 016 既有语义——按租户灰度（US3）、20%/20 自动回滚（FR-5）、5 分钟扫描器、效果分降权——只增加 `traffic_ratio` / 阶梯 / 影子三个维度；016 spec 明示"首期按租户，按比例/按用户为后续扩展"，本特性即该扩展的落地，016 的契约测试在本特性中作为回归保留。
- **与 011（dream-cycle-self-evolution）**：**影子机制思想来源**——`services/chat-api/app/services/dream_cycle/runner.py:102-126` 的 `apply_shadow`（按 `shadow_ratio` 路由 + journal 记录）提供了"只跑不生效"的原始形态；本特性把影子落到 **Skill 调用入口**做实（真实双跑 + 隔离 + 落库），011 自进化侧的影子语义不变，两者不共用代码路径。
- **与 024（deployment-hardening）**：**分层区分**。024 管**部署层**（Docker 镜像发布灰度/回滚，nginx 网关分流，其 spec 自述"不存在灰度通道"、回滚为版本回退演练）；本特性管**资产发布层**（Skill 版本流量管控）。两者层级不同、互不依赖，指标口径（错误率/样本）各自定义，不互相引用。
- **与 032（eval-gate）**：**发布链路互补**。032 在 `publish()` **前**管质量门禁（评测不达标阻断发布），本特性在 `publish()` **后**管流量管控（灰度/影子/回滚）；同挂 Skill 发布链路但不重叠，可独立交付、独立验收。
- **与 004（skillhub-lifecycle）**：本特性复用 004 的版本模型（`skill_id` + `version` + `stable_version` = 上一已发布稳定版本，源自 `organization_skill_releases`），不改变 004 的草稿/发布/快照契约。

## Non-Goals

- 不做按用户标签/人群包灰度（首期 `target_tenants` + `traffic_ratio` 两维）。
- 不做 A/B 指标显著性检验（只做异常率阈值判定，不引入统计检验框架）。
- 不改 016 的 `evaluate_canary` / `apply_rollback` / `CanaryRollbackScanner` 核心函数（只扩展 `Rollout` 维度与路由参数）。
- 不管 Docker 镜像/服务部署层灰度与回滚（024 领域，边界见跨特性关系）。
- 不做影子流量的深度比对报告（首期只记录与基础统计：调用数/成功率/耗时）。
- 不实现跨版本流量并排对比看板（查询接口返回当前档位与影子统计即可，UI 深化留待后续）。
