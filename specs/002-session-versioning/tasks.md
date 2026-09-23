# Tasks: Session Versioning (commit / log / resume / share / co-presence)

**Input**: Design documents from `/specs/002-session-versioning/`

**Prerequisites**: plan.md (required), spec.md (required)

**Clarify Decisions (governing tasks, 2026-07-08)**:
- 快照用独立 collection **`session_snapshots`**（不内嵌 session 文档）；附件存既有存储，快照仅存引用指针。
- 低熵秘密识别 = **Shannon 熵 ≥ 3.5 bits/char 且长度 ≥ 16**，叠加正则前缀（`sk-`/`ghp_`/`AKIA`/`Bearer `）双判定。
- co-presence **不引入 Redis**，用 MongoDB 会话状态 + 短轮询。
- share 用**短时效 token + 组织内可见范围**，与 006 RBAC 权限码联动。
- 并发续写 seq 冲突用 **MongoDB 乐观锁（CAS + 重试）**。

**Checklist Gate**: `checklists/requirements.md` 已 100% 勾选（agent 代审 + 跨特性双向声明）；实现须满足已勾选需求项。

**Organization**: 任务按用户故事分组；`[P]` 标记可并行。落点 = `chat-api/app/services/session_versioning/` + `chat-api/app/api/endpoints/sessions.py`。

---

## Phase 1: Setup (Module Skeleton)

- [x] T001 创建 `services/chat-api/app/services/session_versioning/__init__.py` + 子模块骨架（snapshots/store/timeline/secrets/placeholder/co_presence）
- [x] T002 创建快照数据模型（`session_snapshots`：session_id/seq/trigger/actor/summary/changed_refs/attachment_refs/created_at）+ MongoDB 索引（session_id+seq 唯一）
- [ ] T003 调研既有 `chat-api/app/api/endpoints/sessions.py` 的 session 模型（seq/versions 现状），确认快照与既有会话的挂接点

## Phase 2: Foundational (Blocking Prerequisites)

- [x] T004 [P] 实现 `timeline.py`：线性时间线约束（seq 单调、resume 永不分叉的校验）
- [x] T005 [P] 实现 `secrets.py`：低熵识别（熵 ≥3.5 + 长度 ≥16 + 正则前缀双判定）+ 白名单/手动标记
- [x] T006 [P] 实现 `placeholder.py`：可逆占位符（替换/还原，仅所有者+全能力管理员可解引用，解引用落审计）
- [x] T007 实现 `store.py`：`session_snapshots` 读写 + 附件引用指针（附件走既有存储）

## Phase 3: User Story 1 (P1) — commit / log（快照与回看）

**Goal**: 显式+自动 commit 生成快照；log 可回看并预览摘要。
**独立测试**: commit 后 log 出现快照；预览摘要正确；自动触发（idle/保存/关键工具后）生成快照。

- [x] T008 实现 `snapshots.py`：commit（手动 + 规则自动触发：idle 超时/显式保存/关键工具后，可配）
- [x] T009 实现 log 查询（按时间线列快照 + 预览摘要），接入 `sessions.py` 端点
- [x] T010 US1 测试：commit→log→预览 三组 Acceptance

## Phase 4: User Story 2 (P1) — resume（恢复续编）

**Goal**: 从指定/最新快照恢复，seq 续编，历史线性无分叉。
**独立测试**: resume 后 seq 从快照最大 seq 续编；历史无分叉记录。

- [x] T011 实现 `snapshots.py` resume：从指定快照/最新恢复 + seq 续编（不重置）
- [x] T012 US2 测试：resume 起点正确 + seq 续编 + 无分叉断言

## Phase 5: User Story 3 (P1) — 并发续写（乐观锁）

**Goal**: 先到者为准，落后者重读最新状态重试。
**独立测试**: 并发续写冲突 → CAS 拒绝 → 重读重试成功；无丢失无乱序。

- [ ] T013 实现 seq 乐观锁（CAS + 冲突重读重试，最多 N 次后 fail-closed）
- [ ] T014 US3 测试：并发冲突重试成功 + 顺序一致性 100%

## Phase 6: User Story 4 (P1) — share（交接）

**Goal**: 短时效 token 交接，交接者保留只读、接手者编辑；失效空态。
**独立测试**: share 生成 token；接手者获编辑权；过期/取消后访问"链接已失效"。

- [ ] T015 实现 share：短时效 token + 可见范围（006 RBAC 联动）+ 权限转移（交接者只读/接手者编辑）
- [ ] T016 实现 share 失效（过期/取消）空态
- [ ] T017 US4 测试：交接权限转移 + 失效空态两组 Acceptance

## Phase 7: User Story 5 (P2) — co-presence（多人协同）

**Goal**: 多人同会话线性合并；离线成员贡献保留；不引入 Redis。
**独立测试**: 多客户端消息线性合并；离线成员贡献保留；短轮询在线态。

- [ ] T018 实现 `co_presence.py`：在线态（MongoDB + 短轮询，不引入 Redis）+ 消息线性合并
- [ ] T019 US5 测试：消息线性合并 + 离线贡献保留

## Phase 8: Polish & Cross-Cutting Concerns

- [ ] T020 [P] 秘密过滤覆盖率自检：commit/log/share 视图 0 明文（Success 基准）
- [ ] T021 [P] 会话事件审计：进入/离开/commit/resume/share/解引用进 001 审计落点（字段：操作者/时间/会话 ID/事件类型/引用对象）
- [ ] T022 写 `quickstart.md` + `contracts/session-versioning-contract.md`（commit/log/resume/share 契约）

---

## Dependencies

```text
Phase 1 (骨架/模型) → Phase 2 (时间线/秘密/占位符/存储) → US1 → US2 → US3 → US4 → US5 → Polish
关键: T005/T006 被 US1/US4 共用（commit/share 均过滤秘密）；T007 被全部故事共用
```

## Parallel Opportunities
- T004/T005/T006（Phase 2）互不依赖，可并行
- US1-3（commit/resume/并发）顺序推进（共用 snapshots.py）；US4/US5 可与 US1-3 部分并行

## MVP Scope
- **最小 = Phase 1 + Phase 2 + US1 + US2**（T001–T012）：commit/log/resume 跑通 + 秘密过滤，即"会话版本化"核心可用。
- 增量：US3（并发）→ US4（share）→ US5（co-presence）。

## Notes
- 复用既有 `sessions.py` 的 session/seq 模型；快照独立集合；不引入 Redis。
- 与 009（会话事件钩子）、017（记忆沉淀）、011（经验源）的跨特性关系已在 spec 双向声明。
- 未改 services 源码；本文件仅在 `specs/002-session-versioning/` 下。
