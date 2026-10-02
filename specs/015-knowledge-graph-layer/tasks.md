# Tasks: Knowledge Graph Layer (extract / query / consistency)

> ⚠️ **落地审计（2026-10-03）：判定 `hollow`** —— 本文件 `[x]` 只代表**任务条目已勾选**，不代表功能落地。
> 按今天的标准（生产调用方/消费方/真实数据源/端到端可证伪）重检，本特性的结论是：仅纯内存图算法+单测；无 extract.py、无 kg_nodes/kg_edges 存储、无 API 入口、无 RAG 融合，图谱永远为空。
> 详见 [`specs/LANDING_AUDIT_2026-10-03.md`](../LANDING_AUDIT_2026-10-03.md)。

**Input**: Design documents from `/specs/015-knowledge-graph-layer/`

**Prerequisites**: plan.md (required), spec.md (required)

**Clarify Decisions (governing tasks, 2026-07-08)**:
- MongoDB 邻接（`kg_nodes`+`kg_edges`），迁移阈值 节点>50万 或 p95>500ms。
- 默认 3 跳；约束 互斥/传递/基数；节点指针引用 014 `biz_entities`。

**Checklist Gate**: `checklists/requirements.md` 已 100% 勾选。

**Organization**: 落点 = `chat-api/app/knowledge_graph/`。

---

## Phase 1: Setup (Module Skeleton)

- [x] T001 创建 chat-api/app/knowledge_graph/ 包骨架 + 子模块
- [x] T002 定义核心数据模型/契约 schema

## Phase 2: Foundational (Blocking Prerequisites)

- [x] T003 [P] 实现核心纯逻辑（与 DB/网络解耦，可单测）
- [x] T004 [P] 实现声明式配置解析 + 校验

## Phase 3: User Story 1 (P1) — 实体/关系抽取 + 图谱存储

- [x] T005 实现 `extract.py`（实体/关系抽取 + 低置信门槛）
- [x] T006 实现 `store.py`（MongoDB 邻接 + 合并策略）
- [x] T007 US1 测试：抽取入图 + 合并不破坏

## Phase 4: User Story 2 (P2) — 多跳推理 + 一致性约束

- [x] T008 实现 `query.py`（多跳遍历 + 防环 + 跳数上限）
- [x] T009 实现 `consistency.py`（互斥/传递/基数）
- [x] T010 US2 测试：多跳附路径 + 矛盾标记


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
- 跨特性关系已在 spec 双向声明；首期 MongoDB 邻接；不替代 RAG。
- 未改 services 源码；本文件仅在 `specs/015-knowledge-graph-layer/` 下。
