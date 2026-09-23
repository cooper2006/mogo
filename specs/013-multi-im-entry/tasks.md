# Tasks: Multi IM Entry (IM channel -> MOVO session)

**Input**: Design documents from `/specs/013-multi-im-entry/`

**Prerequisites**: plan.md (required), spec.md (required)

**Clarify Decisions (governing tasks, 2026-07-08)**:
- 首期渠道 = 飞书；纯文本 + 基础 markdown 卡片。
- IM 会话映射 MOVO 会话（`im_session_bindings`）；HMAC-SHA256 + nonce 防重放 5min。

**Checklist Gate**: `checklists/requirements.md` 已 100% 勾选。

**Organization**: 落点 = `chat-api/app/im_gateway/`。

---

## Phase 1: Setup (Module Skeleton)

- [x] T001 创建 chat-api/app/im_gateway/ 包骨架 + 子模块
- [x] T002 定义核心数据模型/契约 schema

## Phase 2: Foundational (Blocking Prerequisites)

- [x] T003 [P] 实现核心纯逻辑（与 DB/网络解耦，可单测）
- [x] T004 [P] 实现声明式配置解析 + 校验

## Phase 3: User Story 1 (P1) — 飞书渠道接入 + 消息映射

- [x] T005 实现 `adapter_base.py` + 飞书 adapter（消息/卡片/鉴权）
- [x] T006 实现 IM 会话 ↔ MOVO 会话映射（1:1 绑定）
- [x] T007 实现 webhook 安全（HMAC-SHA256 + nonce 去重）
- [x] T008 US1 测试：消息映射 + 响应回传 + 签名校验

## Phase 4: User Story 2 (P2) — 统一路由 + 渠道开关

- [x] T009 实现多渠道路由 + 租户级渠道开关
- [x] T010 US2 测试：路由 + 停用置只读


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
- 跨特性关系已在 spec 双向声明；首期仅飞书；IM 仅入口，能力面 = Web 全部。
- 未改 services 源码；本文件仅在 `specs/013-multi-im-entry/` 下。
