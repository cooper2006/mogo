# Session Versioning Contract (002)

> 002-session-versioning — commit / log / resume / share 契约。
> 本文件定义 chat-api `app/services/session_versioning/` 的对外接口与不变量；
> 与 `specs/002-session-versioning/spec.md`、`plan.md` 配套。

## 不变量

- **线性时间线（FR-3/FR-6）**：`Timeline.seqs` 严格递增；`append` 拒绝 `seq <= max`
  （即拒绝分叉）。`resume_from` 永远从快照 seq 之后继续，绝不重置回 1。
- **乐观锁（FR-4）**：`check_and_advance(current, expected)` 在 `expected == current`
  时成功；冲突时调用方必须重读最新 `current` 并重试，超过 `max_retries` 后
  `fail-closed`（抛 `LinearTimelineError`）。
- **Secret 过滤（FR-7/US6）**：commit / log / share 视图永远 0 明文密钥；
  `secret_fields` 恒为空，`secret` / `token` / `password` 不渲染。
- **空态（FR-7）**：无快照 -> 空日志；无有效 share -> 空视图（`active=False`）。

## commit（US1）

`build_snapshot(session_id, seq, trigger, actor, changed_refs, attachments, snapshot_id)`
-> `SessionSnapshot`
- `trigger` ∈ `CommitTrigger`（manual / idle_timeout / key_tool / share）。
- `attachments` 仅存指针（`AttachmentRef`），永不含字节（OQ-1）。
- 存于独立集合 `session_snapshots`，绝不内联进会话文档。

## log（US2 / US3）

`SessionSnapshot.as_document()` 输出固定字段：`snapshot_id / session_id / seq /
trigger / actor / summary / changed_refs / attachment_refs / created_at`。
线性历史由 `Timeline` + `merge_linear` 保证：去重、排序、单链，永不分叉。

## resume（US2 acceptance 1）

`Timeline(seqs).resume_from(snapshot_seq)` 返回 `snapshot_seq + 1`。
- 要求 `snapshot_seq <= max_seq`（领先于当前 -> `LinearTimelineError`）。
- 续接永远向"后"，不复位 seq=1（历史永不产生分叉）。

## share（US4 / FR-8）

`build_share(session_id, snapshot_id, actor, receiver, visibility,
receiver_role, ttl_seconds)` -> `ShareRecord`
- `visibility`：`user` / `org` / `role`（006 RBAC 联动，接收者有效权限决定
  编辑或只读）。
- `receiver_role`：`ROLE_EDITOR`（交接后可编辑）/ `ROLE_VIEWER`（只读）。
- token：短时效（默认 300s）、一次性（`mark_redeemed` 后不可再用）。
- 失效语义（US4 acceptance 2）：过期 / 撤销 / 已赎回 -> `to_view` 返回
  `active=False` 的空视图（诚实空态，不伪造成功）。

## 共享契约（跨用户访问）

- `ShareStore.create_share / redeem / revoke_share`：
  - 赎回成功 = 一次性 token 仍有效；
  - 赎回失败 = `ShareError`（已用 / 已撤 / 已过期）。
- 交接是**单向权限转移**（FR-8）：交接者降级为只读，接手者可编辑。

## 并发与协同（FR-5）

`CoPresence(db, heartbeat_ttl)`
- `heartbeat(session_id, user_id)`：Mongo 短轮询心跳（不引入 Redis）。
- `online(session_id)`：心跳新鲜（< TTL）的编辑者为在线；离编者被剔除
  （但其贡献已合并进线性时间线，离线贡献保留）。
- `merge_messages(session_id, incoming)`：把并发写入折叠成单条严格递增
  时间线（去重、排序、单链），永不分叉。

## 审计（FR-9 / T021）

`record_session_event(audit_sink, session_id, event_type, actor, target_ref)`
- `event_type` ∈ `enter / leave / commit / resume / share / dereference`。
- 必含字段（`SESSION_AUDIT_FIELDS`）：`actor / ts / session_id / event_type /
  target_ref`。
- 委托 001 gatekeeper 审计落点（`gate_events`），与会话事件共用同一审计
  追踪、保留与合规报告。

## 错误

- `SnapshotError` / `LinearTimelineError` / `ShareError`：均为 `ValueError`
  子类，调用方可统一 `except ValueError` 捕获。
- `ConflictResult.ok == False` 表示 seq 冲突：重读 `actual_seq` 后重试。
