# Tasks: Business Semantic Index (CRM/ERP semantic retrieval)

**Input**: Design documents from `/specs/014-business-semantic-index/`

**Prerequisites**: plan.md (required), spec.md (required)

**Clarify Decisions (governing tasks, 2026-07-08)**:
- 首期 CRM（DB 只读副本）；实体 客户/订单/供应商/账目。
- 定时拉取（不做 CDC）；PII 走 001 脱敏。

**Checklist Gate**: `checklists/requirements.md` 已 100% 勾选。

**Organization**: 落点 = `chat-api/app/business_index/`。

---

## Phase 1: Setup (Module Skeleton)

- [x] T001 创建 chat-api/app/business_index/ 包骨架 + 子模块
- [x] T002 定义核心数据模型/契约 schema

## Phase 2: Foundational (Blocking Prerequisites)

- [x] T003 [P] 实现核心纯逻辑（与 DB/网络解耦，可单测）
- [x] T004 [P] 实现声明式配置解析 + 校验

## Phase 3: User Story 1 (P1) — 业务实体索引 + 语义检索

- [x] T005 实现连接器（CRM DB 只读）+ 实体抽取
- [x] T006 实现索引（`biz_entities`，含来源/类型/对齐键）
- [ ] T007 实现语义检索（复用 005 检索客户端 + 引用锚点）
- [x] T008 US1 测试：实体入索引 + 检索带来源

## Phase 4: User Story 2 (P2) — 增量 + 跨系统对齐

- [x] T009 实现定时增量拉取（复用 scheduled_tasks）
- [x] T010 实现跨系统实体对齐（业务主键映射）
- [x] T011 US2 测试：增量 + 对齐失败降级


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
- 跨特性关系已在 spec 双向声明；不替代业务系统、不写业务库；检索复用 005。
- 未改 services 源码；本文件仅在 `specs/014-business-semantic-index/` 下。
