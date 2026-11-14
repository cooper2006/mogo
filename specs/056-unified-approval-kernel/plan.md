# Plan: 审批单一内核（056-unified-approval-kernel）

**Input**: `specs/056-unified-approval-kernel/spec.md`

**Created**: 2026-11-12

## 实施范围

### 新增文件

| 路径 | 用途 |
|---|---|
| `services/chat-api/app/governance/approval_kernel.py` | 统一状态机核心实现 |
| `services/chat-api/app/governance/approval_kernel_types.py` | 类型定义（ApprovalState / ApprovalSource / ApprovalTicket 等 dataclass） |
| `services/chat-api/tests/test_approval_kernel.py` | Kernel 单测（含并发竞态测试） |
| `services/chat-api/tests/test_approval_kernel_concurrency.py` | 并发压测用例（cancel vs decide race） |

### 修改文件（按影响面排序）

| 路径 | 变更内容 |
|---|---|
| `services/admin-api/app/governance/layers/approval.py` | `ApprovalRegistry.decide()` → 内部调 `ApprovalKernel.decide(source=TOOL,...)`；保留旧 API 为兼容 shim（标记 deprecated） |
| `services/chat-api/app/orchestration/human_approval.py` | `human_decide()` → 内部调 `ApprovalKernel.decide(source=SOP,...)` |
| `services/chat-api/app/services/portal/requests.py` | `PortalRequestService.approve()` → 内部调 `ApprovalKernel.decide(source=PORTAL,...)` |
| `services/chat-api/app/orchestration/run_store.py` | `cancel()`、`record_decision()`、`set_status()` 内部逻辑下沉至 Kernel；保留 `run_store` 的公开方法签名不变 |
| `services/chat-api/app/api/endpoints/orchestration_runs.py` | `resolve_review` 端点增加 `reassign` 选项 |
| `services/admin-api/app/api/endpoints/portal_admin.py` | 决策端增加 `actor == approver_id` 校验（R-5） |
| `docs/error-codes.md` | 新增 `approval.actor_mismatch`、`approval.conflict` 两个错误码 |

### 不修改的文件

- `services/admin-api/app/core/pg_compat.py`（R-4 约束：不动兼容层，Kernel 通过 `get_db()` 抽象访问）
- `services/chat-api/app/security/audit_events.py`（已有 `gate_events` 写入基础设施，直接复用）
- `contracts/orchestration.md`（只增 R-19「approval_kernel 路由说明」，不改现有六模式契约）

## 实施步骤

### Phase 1：类型与内核骨架（阻塞后续所有阶段）

1. 创建 `approval_kernel_types.py`：定义 `ApprovalState`（Enum）、`ApprovalSource`（Enum）、`ApprovalTicket`（frozen dataclass）、`ApprovalOutcome`（frozen dataclass）、`ApprovalTodo`（dataclass）、`ApprovalConflictError`（Exception）
2. 创建 `approval_kernel.py` 骨架类，方法签名全为 `pass` + docstring
3. 写最小 fake 集合（InMemoryApprovalCollection），支持 `find_one_and_update` with `$inc revision`
4. 单元测试骨架：各 method 的 stub 测试均 pass

### Phase 2：核心实现（decide / cancel / list_todos）

5. 实现 `issue()`：调用底层 `_col.find_one_and_update` 插入新文档（`$setOnInsert` 设初始状态），返回 token（hex 32）
6. 实现 `decide()`：`update_one` filter = `{_id, status: "pending", revision: expected_revision}`，成功后回调业务侧（通过 strategy pattern 注入 `on_decide` hook）
7. 实现 `cancel()`：filter = `{source_id, status: "pending"}`，成功后清空 pending_approvals、写事件
8. 实现 `list_todos()`：`find` 聚合查询，按 source_type 分组，return document 中过滤 approver_id 匹配项
9. 集成测试：起 Mongo fake db，端到端走完 issue→decide/cancel/list 生命周期

### Phase 3：审计汇接（R-6 / P1-3）

10. 在 `issue()` / `decide()` / `cancel()` / `reassign()` / `resolve_timeout()` 中各加入 `audit_event()` 调用
11. 用 `build_event()` 构造事件（来自 `app/security/audit_events.py`），`source_service="chat-api"`，action 前缀如 `approval.sop.decided`
12. 测试：mock audit_repo，断言每次 kernel 操作都产生一条 gate_events 记录

### Phase 4：改派出口补齐（R-4 / P1-4）

13. 实现 `reassign()`：原子更新 approver_id + deadline + resume_token + $inc revision
14. `resolve_review` 端点加 `"reassign"` action 分支
15. 测试：并发改派+决策竞态（同一节点先后被改派和批准，以先到者为准）

### Phase 5：身份一致性校验（R-5 / P1-1）

16. `decide()` 增加 `actor_id == approver_id` 校验（角色型暂 skip + warning log）
17. admin-api 决策端点加 RBAC 校验（审批人须持有 `approval:decide` 权限）
18. 测试：actor_mismatch 场景返回 403，正常路径返回 200

### Phase 6：旧代码迁移与清理

19. 改造 admin-api `ApprovalRegistry.decide()` → 内部调 Kernel.decide(source=TOOL)
20. 改造 chat-api `human_approval.decide()` → 内部调 Kernel.decide(source=SOP)
21. 改造 portal `approve()` → 内部调 Kernel.decide(source=PORTAL)
22. 删除 `ApprovalRegistry.validate_and_consume()`（已废弃）的生产引用点
23. grep 全仓验证：`grep -rn "ApprovalRegistry\|validate_and_consume" services/ --include="*.py" | grep -v test | grep -v __pycache__` 结果仅保留 deprecated shim

### Phase 7：回归与文档

24. 跑 `tests/orchestration/` 全量（目标 ≥ 207 passed，维持接线会话基准）
25. 跑 `tests/admin-api/test_approval*` 全量
26. 跑 `tests/chat-api/test_portal*` 全量
27. 更新 `specs/INDEX.md`（056 条目 + SDD 路径段）
28. 更新 `CHANGELOG.md`

## 依赖关系

```
Phase 1 (types/skeleton) ──┬── Phase 2 (core impl) ──┬── Phase 4 (reassign)
                           │                          ├── Phase 5 (identity check)
                           │                          └── Phase 3 (audit)
                           └── Phase 6 (migration)
                                                 │
                                              Phase 7 (regression)
```

## 测试策略

| 测试类型 | 位置 | 覆盖重点 |
|---|---|---|
| 单测 | `tests/test_approval_kernel.py` | issue / decide / cancel / list_todos / reassign 基础语义 |
| 并发单测 | `tests/test_approval_kernel_concurrency.py` | cancel↔decide 竞态、同 node 双 approvals、超时后批准 |
| 集成测试 | `tests/orchestration/test_run_store_integration.py` | run_store 方法与 Kernel 的对接 |
| 回归测试 | `tests/orchestration/` 全量 | 无新增 failure |
| 契约测试 | `contracts/orchestration.md` §R-19 | 新增 approve/reassign 路由说明 |

## 回滚方案

- Kernel 模块以 feature flag `APPROVAL_KERNEL_ENABLED`（默认 True）控制开关
- Flag=False 时所有 public method 转发到旧实现（shim 层），零行为变化
- 若发现严重 bug，回滚到上一版本 commit + 设置 flag=False 即可恢复
