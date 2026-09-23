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

Skill 新版本可灰度发布（按比例/按用户），异常时回滚到稳定版本。

**Acceptance Scenarios:**
- 新版本灰度 10% → 部分用户走新版
- 灰度异常率超阈值 → 自动/手动回滚到上一稳定版
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

- FR-1: Skill 调用监控（量/成功率/耗时/异常），按时间/版本统计
- FR-2: 异常调用可下钻
- FR-3: Skill 效果打分（成功率/采纳/纠正综合）
- FR-4: 版本灰度发布（按比例/用户）
- FR-5: 灰度异常回滚到稳定版本
- FR-6: 低质量 Skill 自动标记/降权
- FR-7: 标记/灰度/回滚事件进审计
- FR-8: 打分口径、灰度策略、阈值可配置
- FR-9: 与 004 Skill 生命周期共用版本模型

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
