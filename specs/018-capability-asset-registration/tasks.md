# Tasks: Capability Asset Registration (discover -> registry)

**Input**: Design documents from `/specs/018-capability-asset-registration/`

**Prerequisites**: plan.md (required), spec.md (required)

**Clarify Decisions (governing tasks, 2026-07-08)**:
- 契约 schema = 输入/输出/错误/SLA 四段 JSON。
- 自动扫描 REST/MCP；非标准人工补全；资产与 004 多对多（skill_refs）；下线审批 = 全能力管理员。

**Checklist Gate**: `checklists/requirements.md` 已 100% 勾选。

**Organization**: 落点 = `admin-api/app/services/capability_assets/`。

---

## Phase 1: Setup (Module Skeleton)

- [x] T001 创建 admin-api/app/services/capability_assets/ 包骨架 + 子模块
- [x] T002 定义核心数据模型/契约 schema

## Phase 2: Foundational (Blocking Prerequisites)

- [x] T003 [P] 实现核心纯逻辑（与 DB/网络解耦，可单测）
- [x] T004 [P] 实现声明式配置解析 + 校验

## Phase 3: User Story 1 (P1) — 能力发现 + 资产注册

- [x] T005 实现能力扫描（REST/MCP 契约抽取）
- [x] T006 实现资产注册（契约四段 + 版本 + owner）
- [x] T007 实现扫描去重（端点+方法）
- [x] T008 US1 测试：发现 + 注册 + 去重

## Phase 4: User Story 2 (P2) — 治理视图 + 状态管理

- [x] T009 实现全量资产治理视图（列表 + 详情下钻）
- [x] T010 实现状态管理（active/deprecated/offline + 审批）
- [x] T011 实现 a2a_exposed 标记（供 012 生成 AgentCard）
- [x] T012 US2 测试：视图 + 状态 + 标记


## Polish & Cross-Cutting Concerns

- [x] T999 [P] 审计/可观测接入
- [x] T998 写 `quickstart.md` + `contracts/` 契约文档

---

## Dependencies

```text
Phase 1 → Phase 2 → 各用户故事（按 spec 优先级 P1→P2）→ Polish
```

## MVP Scope
- **最小 = Phase 1 + Phase 2 + 首个 P1 故事**；其余按优先级增量。

## Notes
- 跨特性关系已在 spec 双向声明；资产化是 004 叠加层；不实现能力执行。
- 未改 services 源码；本文件仅在 `specs/018-capability-asset-registration/` 下。
