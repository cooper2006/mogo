# Tasks: A2A Agent Gateway (AgentCard + JSON-RPC)

**Input**: Design documents from `/specs/012-a2a-agent-gateway/`

**Prerequisites**: plan.md (required), spec.md (required)

**Clarify Decisions (governing tasks, 2026-07-08)**:
- 协议版本 = A2A latest stable；本地 `a2a_agent_cards` 集合。
- 双向过 001 门禁/审计；先兼容 Dify 字段。

**Checklist Gate**: `checklists/requirements.md` 已 100% 勾选。

**Organization**: 落点 = `chat-api/app/a2a/`。

---

## Phase 1: Setup (Module Skeleton)

- [x] T001 创建 chat-api/app/a2a/ 包骨架 + 子模块
- [x] T002 定义核心数据模型/契约 schema

## Phase 2: Foundational (Blocking Prerequisites)

- [x] T003 [P] 实现核心纯逻辑（与 DB/网络解耦，可单测）
- [x] T004 [P] 实现声明式配置解析 + 校验

## Phase 3: User Story 1 (P1) — 对外暴露 AgentCard + JSON-RPC 端点

- [x] T005 实现 AgentCard 生成/注册（必含字段 + skills[]）
- [x] T006 实现 JSON-RPC 端点（message/send、tasks/get、tasks/result）
- [x] T007 实现任务幂等（同 task id 去重）
- [x] T008 US1 测试：AgentCard 可解析 + 任务全链路

## Phase 4: User Story 2 (P2) — A2A 客户端（对外调用）

- [ ] T009 实现客户端封装（超时 30s + failover + 复用 007 退避）
- [ ] T010 US2 测试：出站调用 + 错误码映射


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
- 跨特性关系已在 spec 双向声明；A2A 与 MCP 并存；AgentCard 仅对 018 的 a2a_exposed 资产生成。
- 未改 services 源码；本文件仅在 `specs/012-a2a-agent-gateway/` 下。
