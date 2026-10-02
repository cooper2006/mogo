# Tasks: Skill Market Hardening (monitor / score / canary)

**Input**: Design documents from `/specs/016-skill-market-hardening/`

**Prerequisites**: plan.md (required), spec.md (required)

**Clarify Decisions (governing tasks, 2026-07-08)**:
- 效果分 = 成功率0.5 + 采纳率0.3 + 纠正率反向0.2。
- 首期按租户灰度；异常率>20% 回滚；效果分<0.4 持续7天低质量（共用 011 标记位）。

**Checklist Gate**: `checklists/requirements.md` 已 100% 勾选。

**Organization**: 落点 = `admin-api/app/services/skill_market/`。

---

## Phase 1: Setup (Module Skeleton)

- [x] T001 创建 admin-api/app/services/skill_market/ 包骨架 + 子模块
- [x] T002 定义核心数据模型/契约 schema

## Phase 2: Foundational (Blocking Prerequisites)

- [x] T003 [P] 实现核心纯逻辑（与 DB/网络解耦，可单测）
- [x] T004 [P] 实现声明式配置解析 + 校验

## Phase 3: User Story 1 (P1) — 调用监控聚合

- [x] T005 实现监控聚合（量/成功率/耗时/异常，按版本）
- [x] T006 实现异常下钻
- [x] T007 US1 测试：指标口径 + 下钻

## Phase 4: User Story 2 (P2) — 效果打分 + 灰度回滚

- [x] T008 实现效果分模型（0.5/0.3/0.2）
- [x] T009 实现灰度调度 + 自动回滚（异常率>20%）
- [x] T010 实现低质量标记（<0.4 持续7天，共用标记位）
- [x] T011 US2 测试：打分 + 回滚 + 标记


## Polish & Cross-Cutting Concerns

- [x] T999 [P] 审计/可观测接入
- [x] T998 写 `quickstart.md` + `contracts/` 契约文档

## Phase 5: 效果分三维数据归因（OQ-6，2026-10-03 决策后新增）

口径决策见 `plan.md` OQ-6。`total_calls` 已实现（T020）；其余三维待实现。

- [x] T020 调用总数采集：从 `kernel_event_projections` 滚 `skill.selected` → `skill_quality_metrics`
      （admin-api `quality_metrics.collect_skill_activity_metrics`，水位幂等）+ 完整性门槛防误杀
- [ ] T021 采纳维度：按 `message_id` 关联 `enterprise_authoritative_deliveries`（`accepted=True`）写
      `adopted_calls`（数据已存在，仅需关联，无需新埋点）
- [ ] T022 纠正维度：在 `POST /documents/save-blueprint` 新增"产物编辑事件"埋点（记录
      `blueprint_object_path` / tenant / user / 编辑前后指纹 / 来源 `message_id`），再据此写 `corrected_calls`
- [ ] T023 成功维度：确认"该轮 tool 成败"归因口径（`tools/service.py` 的 `execution_succeeded`）后写
      `successful_calls`；口径确认后与 T021/T022 一齐放开 `evaluate_skill_quality` 的完整性门槛
- [ ] T024 放开门槛后回归：确认三维齐备时低质量标记可被真实触发（端到端可证伪）

---

## Dependencies

```text
Phase 1 → Phase 2 → 各用户故事（按 spec 优先级 P1→P2）→ Polish
```

## MVP Scope
- **最小 = Phase 1 + Phase 2 + 首个 P1 故事**；其余按优先级增量。

## Notes
- 跨特性关系已在 spec 双向声明；016 是 004 市场侧叠加层，不改 004 契约。
- 未改 services 源码；本文件仅在 `specs/016-skill-market-hardening/` 下。
