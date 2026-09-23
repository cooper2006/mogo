# Feature Specification: Thick/Thin Harness Elastic Configuration

**Feature Branch**: `019-harness-elastic-config`

**Created**: 2026-07-08

**Status**: Draft

**Input**: 补齐规划文档清单 15（P2 规模化生态）"厚/薄 Harness 弹性配置"（知识库《Harness 实践》）：按场景在厚 Harness（重治理/全门禁/强审计）与薄 Harness（轻启动/快执行）间切换，推进 HaaS（Harness as a Service）思路。

## User Scenarios & Testing *(mandatory)*

用户故事按优先级排列，每个独立可交付、可测试。

### User Story 1 (P1) — 按场景选择 Harness 厚度

用户/管理员可按场景选择 Harness 模式：
- 厚 Harness：全门禁（001 六层）+ 全审计 + 强治理，用于高风险/合规场景
- 薄 Harness：精简门禁 + 快启动，用于低风险/实验场景

**Acceptance Scenarios:**
- 选厚 Harness 执行 → 走 001 完整六层门禁 + 全量审计
- 选薄 Harness 执行 → 走精简门禁（如仅身份 + 审计），启动快
- 同一 Agent 可在不同场景用不同厚度

### User Story 2 (P1) — 厚度配置可声明

Harness 厚度以声明式配置表达（哪些门禁层启用/跳过、审计粒度、超时策略），按场景/租户/工具维度配置。

**Acceptance Scenarios:**
- 声明式配置指定场景厚度 → 执行按配置生效
- 按租户/工具维度差异化厚度
- 配置变更留审计

### User Story 3 (P2) — 红线不可降档（R4 始终厚）

无论薄/厚模式，R4 红线工具（特性 001）与关键合规门禁不可降档——薄模式只是"省略非红线门禁"，不是"绕过治理"。

**Acceptance Scenarios:**
- 薄 Harness 下调用 R4 工具 → 仍走 001 deny（红线不覆盖）
- 薄模式省略的是非红线层，红线层始终启用
- 薄模式不可关闭审计（审计是底线）

### Notes / Assumptions
- 本特性补齐规划文档清单 15（P2 规模化生态，后置），属缺口新特性
- 现状：MOVO 治理是统一厚模式（001 gatekeeper 设计），无"厚度切换"概念
- 与特性 001（gatekeeper）的关系：019 是 001 的"弹性配置层"——001 定义六层门禁，019 定义"按场景启用哪几层"
- 红线（R4）与审计是硬性底线，不可被薄模式绕过（constitution 原则 II/III）
- 与特性 009（Hooks）的关系：薄模式可跳过非红线 Hooks，但 fail_closed 底线保留
- 厚度维度（场景/租户/工具）默认策略需 clarify

## Functional Requirements

- FR-1: 支持厚/薄 Harness 两种模式，按场景选择
- FR-2: 厚度声明式配置（门禁层启用/跳过 + 审计粒度 + 超时）
- FR-3: 按场景/租户/工具维度差异化厚度
- FR-4: 同一 Agent 不同场景可用不同厚度
- FR-5: R4 红线工具在任何模式下始终走 001 deny（不可降档）
- FR-6: 审计是底线，薄模式不可关闭
- FR-7: 厚度配置变更留审计
- FR-8: 薄模式省略的非红线层需显式声明（默认厚模式，降级需显式配置）

## Non-Goals
- 不改变 001 六层门禁语义（019 是"启用哪几层"的开关层）
- 不实现 Harness 跨实例弹性调度（HaaS 的"按算力弹性"是后续）
- 不降低治理底线（红线 + 审计不可绕过）
- 不实现厚/薄自动切换（按场景配置，非运行时自动推断）

## Success Criteria
- 厚/薄模式 100% 可切换生效
- R4 红线 100% 不可降档（任何模式）
- 审计底线 100% 不关闭
- 厚度配置 100% 进审计

## Further Details
- 技术实现（厚度配置 schema、与 001 门禁链的层开关、审计底线守护）由 plan.md 承载
- 默认厚度策略与维度需 clarify
