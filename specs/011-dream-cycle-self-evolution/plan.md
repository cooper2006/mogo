# Implementation Plan: Dream Cycle Self-Evolution

**Branch**: `011-dream-cycle-self-evolution` | **Date**: 2026-07-08 | **Spec**: [spec.md](./spec.md)

**Input**: 缺口新特性（P2 后置）。在特性 004（Skill 生命周期）与 002（会话版本化）之上构建"会话→经验→Skill 草稿"自进化引擎。

## Summary

新增 `services/chat-api/app/self_evolution/` 子模块：friction 检测（捕获经验片段）+ 周期扫描（发现重复模式）+ Skill 草稿生成（进 004 草稿态）+ 自动建 MR（高置信）+ 低采纳淘汰。复用既有：`scheduled_tasks`（周期扫描 job）、`skills_specs`（Skill 规格）、004 `skill_lifecycle`（草稿/发布生命周期）。P2 后置，工作量最大。

## Technical Context

**Language/Version**: Python 3.13（chat-api）

**Primary Dependencies**: 既有 `scheduled_tasks`（周期 job 框架）+ `skills_specs`（Skill 规格 schema）+ 004 `skill_lifecycle`（草稿态）+ 002 会话快照（经验源）

**Storage**: 新增 `experience_logs`（经验片段）+ `skill_evolution_drafts`（自进化草稿）+ 复用 skills 集合（最终发布）

**Testing**: pytest（friction 检测 + 模式发现 + 草稿生成 + 淘汰单测；周期 job 集成测试）

**Target Platform**: 自托管 Docker Compose

**Project Type**: 新增模块（自进化引擎，P2 后置）

## 现有实现事实（复用依据）

- `scheduled_tasks/`：`runner` + `scheduler` + `schedule`（周期任务框架，自进化扫描复用）
- `skills_specs/`：Skill 规格定义（草稿生成的 schema 参照）
- `admin-api/services/skill_lifecycle.py`：`OrganizationSkillLifecycle.initialize/save/publish`（草稿进 004 生命周期）
- `chat-api/enterprise_capabilities/skills/`：Skill 注册/加载（草稿发布后的落地）

## Constitution Check

| 原则 | 结果 |
|---|---|
| I. Specification-First | 通过 |
| II. Production Readiness | 通过：草稿需人工审阅，不自动合入 |
| III. Security | 通过：经验片段经既有脱敏（001 联动） |
| IV. i18n | 通过 |
| V. Observability | 通过：自进化事件审计 |

## Project Structure

```text
services/chat-api/app/
└── self_evolution/              # 新增自进化引擎（P2）
    ├── __init__.py
    ├── friction.py             # friction 检测 → 经验片段
    ├── scanner.py              # 周期扫描 → 重复模式发现
    ├── draft_gen.py            # Skill 草稿生成（进 004）
    ├── mr.py                   # 高置信自动建 MR
    └── deprecation.py          # 低采纳淘汰
services/admin-api/app/
└── services/skill_lifecycle.py # 既有：草稿/发布复用
```

## Open Questions（已 clarify 消解）
- OQ-1 friction 判定：**失败后成功（重试 ≥ 1）+ 人工纠正/驳回 + 用户显式标记（前两类默认捕获，第三类需主动标记）**。
- OQ-2 相似度算法：**Jaccard（场景特征向量）+ 编辑距离（动作序列）双指标**，首期不引入向量库（控依赖）；阈值联动 OQ-3。
- OQ-3 自动建 MR 阈值：**Jaccard ≥ 0.7 且样本 ≥ 5 触发**；目标为当前租户 004 Skill 草稿目录（非直接合入主干，人工审阅后发布）。
- OQ-4 淘汰阈值：**持续 14 天推荐曝光 ≥ 20 且采纳率 < 10% 标记 deprecated**，与 016 市场标记共用同一标记位（避免双写）。
- OQ-5 P2 节奏：**可独立延期，不影响 004/002 已交付能力**；扫描 job 复用 `scheduled_tasks`（已支持 once/daily/weekly）。

## 下一步
OQ 已 clarify 消解。P2 后置，按路线图节奏推进：`/speckit-checklist` → `/speckit-tasks` → `/speckit-analyze` → `/speckit-implement` → `/speckit-converge`。
