# Implementation Plan: Skill Full-Lifecycle Marketplace Hardening

**Branch**: `016-skill-market-hardening` | **Date**: 2026-07-08 | **Spec**: [spec.md](./spec.md)

**Input**: 缺口新特性（P2 规模化生态，后置）。在特性 004（Skill 生命周期基础）之上做市场侧强化：调用监控、效果打分、版本灰度/回滚、低质量自动标记。沉淀闭环（会话→经验→Skill 草稿）由 011 承载，本特性专注市场强化。

## Summary

新增 `services/admin-api/app/services/skill_market/` 子模块：Skill 调用监控聚合（复用既有审计/事件通道 + token_usage）、效果打分模型、灰度调度器、低质量自动标记。与 004 `skill_lifecycle` 共用版本模型，016 是"市场侧"叠加层，不改变 004 草稿/发布契约。

## Technical Context

**Language/Version**: Python 3.13（admin-api/chat-api 既有栈）

**Primary Dependencies**: 既有 `admin-api/services/skill_lifecycle.py`（版本/发布模型）+ 既有审计通道 + `chat-api/token_usage`（调用指标）；新增灰度调度（`scheduled_tasks` 复用）

**Storage**: 新增 `skill_metrics`（调用/效果指标）+ `skill_rollouts`（灰度/回滚记录）+ 复用 004 `organization_skill_releases`

**Testing**: pytest（指标聚合单测 + 效果分模型测试 + 灰度调度测试 + 回滚测试 + 标记测试）

**Target Platform**: 自托管 Docker Compose

**Project Type**: 既有模块扩展（Skill 市场强化，P2 后置）

## 现有挂载点依据

- 版本模型：`admin-api/services/skill_lifecycle.py`（`OrganizationSkillLifecycle` 版本/发布，016 在其上叠加）
- 调用指标：复用既有审计/事件 + `chat-api/token_usage`（调用量/成功率来源）
- 灰度调度：复用 `chat-api/scheduled_tasks`（周期任务框架）
- 低质量标记：与 011 Dream Cycle 的"低采纳淘汰"口径对齐（011 做经验侧淘汰，016 做市场侧标记，二者不重复）

## Constitution Check

| 原则 | 结果 |
|---|---|
| I. Specification-First | 通过 |
| II. Production Readiness | 通过：灰度/回滚可追溯 |
| III. Security | 通过：标记/回滚事件审计 |
| IV. i18n | 通过 |
| V. Observability | 通过：本特性即调用监控刚需 |

## Project Structure

```text
services/admin-api/app/
├── services/
│   ├── skill_lifecycle.py   # 既有：版本/发布基础
│   └── skill_market/        # 新增市场强化
│       ├── __init__.py
│       ├── metrics.py        # 调用监控聚合
│       ├── scoring.py        # 效果打分模型
│       ├── rollout.py        # 灰度调度 + 回滚
│       └── marking.py        # 低质量自动标记
services/chat-api/app/scheduled_tasks/  # 既有：灰度周期调度复用
```

## Open Questions
- OQ-1: 效果分口径（成功率/采纳/纠正的综合权重，需 clarify 定值）
- OQ-2: 灰度策略（按比例 vs 按用户 vs 按租户，spec 写"按比例/按用户"需定默认）
- OQ-3: 回滚触发（自动阈值 vs 手动，spec 写"异常率超阈值自动/手动回滚"需定阈值）
- OQ-4: 低质量标记阈值与周期（持续低分的判定窗口）
- OQ-5: 与 011"低采纳淘汰"的分工边界（016 市场标记 vs 011 经验侧淘汰，是否同一标记位）

## 下一步
P2 后置。`/speckit-clarify` 消解 OQ → 补 research/data-model/contracts/quickstart → checklist → tasks → analyze → implement → converge。
