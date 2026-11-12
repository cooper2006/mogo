# Quickstart: 审批单一内核（056）

**Feature**: `specs/056-unified-approval-kernel/spec.md`

## 本特性解决什么问题

当前 mogo 的审批能力分属于三套独立状态机：
1. admin-api 的 `ApprovalRegistry`（MongoDB `gate_approvals` 集合，处理工具调用审批）
2. chat-api 的 `ApprovalRuntime`（进程内 dict，已废弃但仍有引用）
3. chat-api portal 的申领单（`portal_requests` 集合，applied→granted→revoked）
4. chat-api orchestration 的 `human_approval` 节点（`run_store.claim_pending`，050 SOP 运行）

四套并存导致：身份校验口径不一、取消与决策竞态无原子保护、SOP 审批事件不进 001 审计汇、改派出口残缺。

## 核心设计决策

- **一个内核**：新建 `ApprovalKernel` 类，封装 issue / decide / cancel / reassign / list_todos 五个方法，内部用 `revision` 字段做条件更新仲裁
- **三种来源**：通过 `ApprovalSource` 枚举（TOOL / PORTAL / SOP）区分，审计事件前缀如 `approval.sop.decided`
- **不改 API 契约**：现有端点签名不变，只替换内部实现；旧 shim 层保留至下个版本再删
- **双后端透明**：Kernel 基于 `get_db()` 抽象，Mongo 和 PanWeiDB 均支持

## 如何验证

### 单元测试（本地）

```bash
# 进入 chat-api 服务目录
cd services/chat-api

# 跑新增的单测
pytest tests/test_approval_kernel.py -v
pytest tests/test_approval_kernel_concurrency.py -v

# 跑 orchestration 全量回归（基准 207 passed）
pytest tests/orchestration/ -v
```

### 集成验证（需起服）

1. 起 admin-api + chat-api + Mongo
2. 创建一条 SOP 运行（含 human_approval 节点）：
   ```bash
   curl -X POST http://localhost:8000/api/v1/orchestrations/run \
     -H "Content-Type: application/json" \
     -d '{"definition": {"nodes": [{"type": "mock"}, {"type": "human_approval", "approver": "<user_id>"}]}}'
   ```
3. 查看待办：
   ```bash
   curl http://localhost:8000/api/v1/admin/approvals/todos?approver=<user_id>
   ```
4. 批准：
   ```bash
   curl -X POST http://localhost:8000/api/v1/admin/approvals/sop/<source_id>/decide \
     -H "Content-Type: application/json" \
     -d '{"token": "<ticket_token>", "approved": true, "reason": "approved"}'
   ```
5. 验审计：查询 `gate_events` 集合，应有 `approval.sop.decided` 事件

### 并发压测

```bash
pytest tests/test_approval_kernel_concurrency.py::test_cancel_vs_decide_race -v --tb=short
```

## 回滚

设置环境变量 `APPROVAL_KERNEL_ENABLED=false` 即可切回旧路径，无需重新部署代码。

## 相关特性

- 001 gatekeeper（审计汇 `gate_events` 基础设施）
- 050 sop-human-handoff（本次合并的直接消费方之一）
- 037 unified-portal（本次合并的直接消费方之二）
