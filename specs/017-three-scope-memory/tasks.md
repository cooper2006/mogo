# Tasks: Three-Scope Memory (personal / workspace / org)

**Input**: Design documents from `/specs/017-three-scope-memory/`

**Prerequisites**: plan.md (required), spec.md (required)

**Clarify Decisions (governing tasks, 2026-07-08)**:
- 单人会话默认 personal、多人默认 workspace、组织需显式提升。
- 衰减 30 天（访问重置）；组织提升经 006 全能力管理员授权。

**Checklist Gate**: `checklists/requirements.md` 已 100% 勾选。

**Organization**: 落点 = `chat-api/app/memory/`。

---

## Phase 1: Setup (Module Skeleton)

- [ ] T001 创建 chat-api/app/memory/ 包骨架 + 子模块
- [ ] T002 定义核心数据模型/契约 schema

## Phase 2: Foundational (Blocking Prerequisites)

- [ ] T003 [P] 实现核心纯逻辑（与 DB/网络解耦，可单测）
- [ ] T004 [P] 实现声明式配置解析 + 校验

## Phase 3: User Story 1 (P1) — 三级记忆写入与隔离

- [ ] T005 实现 scope 模型（personal/workspace/org）+ 存储隔离
- [ ] T006 实现可见性隔离（个人/成员/全组织）
- [ ] T007 US1 测试：三级隔离无越权

## Phase 4: User Story 2 (P2) — 范围升级 + 生命周期

- [ ] T008 实现范围升级授权（经 006 + 审计）
- [ ] T009 实现衰减/清理（30 天，访问重置）
- [ ] T010 实现记忆进 RAG 检索（按 scope 过滤）
- [ ] T011 US2 测试：升级授权 + 衰减 + 检索过滤


## Polish & Cross-Cutting Concerns

- [ ] T999 [P] 审计/可观测接入
- [ ] T998 写 `quickstart.md` + `contracts/` 契约文档

---

## Dependencies

```text
Phase 1 → Phase 2 → 各用户故事（按 spec 优先级 P1→P2）→ Polish
```

## MVP Scope
- **最小 = Phase 1 + Phase 2 + 首个 P1 故事**；其余按优先级增量。

## Notes
- 跨特性关系已在 spec 双向声明；复用 005 个人知识底层；不改变 005 契约。
- 未改 services 源码；本文件仅在 `specs/017-three-scope-memory/` 下。
