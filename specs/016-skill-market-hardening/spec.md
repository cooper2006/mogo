# Feature Specification: Skill Full-Lifecycle Marketplace Hardening

**Feature Branch**: `016-skill-market-hardening`

**Created**: 2026-07-08

**Status**: Draft

**Input**: 补齐规划文档清单 12 的"Skill 市场强化"部分（P2 规模化生态，知识库《自建平台》）：版本管理、灰度/回滚、调用监控、效果打分、低质量自动标记。沉淀闭环（会话→经验→Skill）已由特性 011（Dream Cycle）承载，本特性专注市场侧的强化。

## User Scenarios & Testing *(mandatory)*

用户故事按优先级排列，每个独立可交付、可测试。

### User Story 1 (P1) — Skill 调用监控

组织可查看 Skill 的调用量、成功率、平均耗时、异常数；按时间/版本维度统计。

**Acceptance Scenarios:**
- 列出某 Skill 调用监控 → 调用量/成功率/耗时
- 按版本对比 → 不同版本表现差异可见
- 异常调用可下钻到请求

### User Story 2 (P1) — 效果打分

Skill 执行结果按效果打分（质量/采纳/人工纠正率），用于识别优质与低质 Skill。

**Acceptance Scenarios:**
- 计算某 Skill 效果分（综合调用成功率 + 采纳 + 纠正）
- 效果分低 → 标记待优化
- 打分口径可配置

### User Story 3 (P2) — 版本灰度 / 回滚

Skill 新版本可灰度发布（首期按租户，按比例/按用户为后续扩展），异常时回滚到稳定版本。

**Acceptance Scenarios:**
- 新版本灰度 1 个租户 → 该租户走新版，其余租户仍走稳定版
- 灰度异常率超阈值（>20%，可配）→ 自动/手动回滚到上一稳定版
- 回滚可追溯（回滚前/后版本、触发原因）

### User Story 4 (P2) — 低质量自动标记

Skill 持续低效果分 / 高异常 → 自动标记低质量，进市场降权/隐藏。

**Acceptance Scenarios:**
- 效果分低于阈值且持续 → 自动标记 deprecated/低质量
- 标记后 → 市场降权，可人工恢复
- 标记事件进审计

### Notes / Assumptions
- 本特性补齐规划文档清单 12 的"市场强化"部分（P2 后置）；清单 12 的"沉淀闭环"已由 011 承载
- 与特性 004（skillhub-lifecycle）的关系：004 是"Skill 生命周期基础（草稿/发布/版本）"，016 是"市场侧强化（监控/打分/灰度/回滚/标记）"，二者分层
- 与特性 011（Dream Cycle）的关系：011 产出草稿 → 016 做市场强化与淘汰
- 调用监控数据源复用既有审计/事件通道
- 灰度策略、效果分口径、低质量阈值需 clarify

## Functional Requirements

- FR-1: Skill 调用监控（量/成功率/耗时/异常），按时间/版本统计；**"异常" = 失败 + 超时 + 异常退出（成功率与异常率互补）；时间粒度 = 分钟/小时/日（可配）；数据源 = `token_usage_logs`/审计事件通道**
- FR-2: 异常调用可下钻
- FR-3: Skill 效果打分（成功率/采纳/纠正综合）；**口径 = 成功率 0.5 + 采纳率 0.3 + 纠正率反向 0.2（权重可配）；采纳计数取推荐后实际调用，纠正取人工修正信号**。三维的**数据归因口径见 `plan.md` 的 OQ-6**（2026-10-03 决策）：`total_calls` 取 `skill.selected` 事件；`adopted` 按 `message_id` 关联 `enterprise_authoritative_deliveries.accepted=True`；`corrected` 以编辑产物（`save-blueprint`）为信号，**需新增编辑事件埋点**；`success` 口径待定。
- FR-4: 版本灰度发布（首期按租户，按比例/按用户为后续扩展）
- FR-5: 灰度异常回滚到稳定版本；**阈值 = 灰度版本异常率 > 20%（可配）自动回滚；"稳定版本" = 该 Skill 上一已发布稳定版本**
- FR-6: 低质量 Skill 自动标记/降权；**标记阈值 = 效果分 < 0.4 持续 7 天；降权行为 = 市场列表排序靠后（仍可搜索，不隐藏）；与 011 共用 `skill_status.marked_low_quality` 标记位**
- FR-7: 标记/灰度/回滚事件进审计
- FR-8: 打分口径、灰度策略、阈值可配置
- FR-9: 与 004 Skill 生命周期共用版本模型
- FR-10: **灰度异常率判定的最小样本量门槛 = 调用量 < 20 时不计入异常率判定（避免小样本误判）**
- FR-11: **低质量标记可人工恢复；恢复后重置低质量窗口（重新累计 7 天），并重新进入正常排序**
- FR-12: **同一 Skill 多版本并行灰度时，监控指标按版本维度分别归集（每版本独立统计量/成功率/耗时）**

## Non-Goals
- 不实现 Skill 自动沉淀生成（属 011 Dream Cycle）
- 不实现跨租户 Skill 市场（市场强化在组织内）
- 不改变 004 既有草稿/发布契约（仅叠加监控/灰度/标记）
- 不实现 Skill 计费/商业化（社区版无计费）

## Success Criteria
- 调用监控 100% 可查
- 灰度发布/回滚可追溯
- 低质量 Skill 100% 可自动标记
- 市场强化 100% 进审计

## Further Details
- 技术实现（监控聚合、效果分模型、灰度调度）由 plan.md 承载
- 口径与阈值需 clarify

## 033 扩展回填（2026-10-23）

本特性 FR-4 明示"首期按租户，**按比例/按用户为后续扩展**"。该扩展由特性
**033-canary-rollout**（比例灰度 + 影子发布）落地，本文件据此回填契约口径：
**016 的既有灰度/回滚语义不变**（按租户 `target_tenants`、20% 阈值、20 样本
门槛、5 分钟扫描、手动 `POST /{skill_id}/rollback`），仅**增加维度**。

### 新增字段（`skill_rollouts` 扩展，存量行读取默认值）

- `traffic_ratio`（float，0 < ratio ≤ 1）：按 `(tenant_id, user_id)` 确定性
  哈希取模分流比例；`target_tenants` 与 `traffic_ratio` 可叠加（租户子集内
  按比例分流），两者皆空 = 100% 全量。
- `ladder`（`LadderStep[]`：`ratio` / `min_samples?` / `entered_at` /
  `promoted_at?`）：阶梯档位，默认 1% → 10% → 50% → 100%。
- `current_step` / `ladder_history`：当前档位与逐档推进历史（可查）。
- `shadow_enabled`（bool）：影子模式开关（默认关闭）。

### 新增端点（`services/admin-api/app/api/routes/skill_canary.py`）

- `POST /api/skills/canary`：创建扩展接受 `traffic_ratio` / `ladder` /
  `shadow_enabled`（其余字段语义不变）。
- `GET /api/skills/canary/{skill_id}`：查询额外返回当前档位、推进历史与
  影子统计。
- `POST /api/skills/canary/{skill_id}/advance`：手动推进阶梯（条件同自动
  推进：当前档样本 ≥ `min_samples` 且异常率 ≤ `threshold`）。
- `POST /api/skills/canary/{skill_id}/shadow`：开 / 关影子模式。
- `POST /api/skills/canary/{skill_id}/rollback`：**原样保留**；回滚后
  `traffic_ratio` 归零、状态 `rolled_back`、`stable_version` 指向上一已发布
  稳定版本（016 FR-13 口径）。

### 新增集合

- `skill_shadow_runs`（影子双跑观察记录，只写 + 基础聚合；`tenant_id` 标量
  键，已纳入 `tenant_purge.TENANT_SCOPED_COLLECTIONS`）。

### 语义不变项（033 不改变）

- 自动回滚口径（异常率 > 20% 且样本 ≥ 20 → `rolled_back`）与
  `evaluate_canary` / `apply_rollback` 阈值体系不变。
- 阶梯推进到 100% 且稳定后置 `RolloutState.PROMOTED`（既有枚举值）。
- 影子执行**不计入** `call_count` / `error_count`，影子失败不触发回滚。
