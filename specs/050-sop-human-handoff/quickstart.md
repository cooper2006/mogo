# Quickstart: 050 SOP 转人工节点（human_approval）

**状态**：已实现（2026-11-09/10 三波次）；本文件于 2026-11-11 standard 深度全量 QA 审计补齐，使五件套齐备。

## 做了什么

在 010 DAG 编排引擎里新增第七类节点 `human_approval`：执行到该节点**挂起并持久化运行态**（不在进程内等待），向指定审批人发出长效待办；批准续跑、驳回按 `on_reject` 分支或终止，超时默认 fail-closed。决策瞬间经 `ApprovalRuntime.issue` 签发短 TTL 票据并立即 `validate_and_consume`，发起人自审被拒。

- 运行持久化：`services/chat-api/app/orchestration/run_store.py` → `orchestration_runs`（运行创建锁定定义版本、节点完成写 checkpoint、恢复不重复执行）。
- 节点与恢复：`services/chat-api/app/orchestration/human_approval.py`、`turn_recovery` 恢复扫描。
- 前端：user-web 039 编排画布「转人工节点」属性面板；`apps/user-web/src/components/orchestration/ApproverPicker.vue` 按**本租户部门树 + end_users 候选**选择审批人（FR-010 / T018），不暴露自由文本 `user_id` 输入框；选中后写入 `node.data.approver` 仍是 user_id 字符串。

## 前置条件

1. kiri 生产栈在线：`docker --context kiri exec kiri-k8s kubectl get pods -n mogo`（10 Pod Running）；网关 `curl -s -o /dev/null -w '%{http_code}' http://localhost:3000/admin/setup` = 200。
2. 同一租户下至少 2 个 `end_users`（审批人与发起人不能是同一人）+ 至少一个部门。
3. 数据后端为 ServeBay Mongo；全库主键已归一为 32-hex（见 `docs/id-unification-hex32-runbook.md`）。

## 如何启用

在编排 YAML 的 `nodes` 中声明：

```yaml
nodes:
  - id: approve_budget
    type: human_approval
    payload:
      approver: <end_users._id 32-hex>
      prompt: "请复核本季度预算"
      timeout: 86400          # 秒；超时 fail-closed，不自动批准
      on_reject: reject_branch  # 或 null 表示终止
```

加载期 `loader.py` 校验 `approver` 与 `on_reject` 目标存在，失败即拒绝加载（fail-closed）。

## 如何验证

```bash
# 1) 后端节点 / 持久化 / 恢复回归
cd /Users/cooper/mogo/services/chat-api
./.venv/bin/python -m pytest tests/orchestration/ -q -o addopts=

# 2) 审批人选择器前端编译
cd /Users/cooper/mogo/apps/user-web && npx vue-tsc --noEmit

# 3) 画布往返（YAML ↔ 画布字段无损）
#    approver / prompt / on_reject / timeout 均须回读一致
```

浏览器手工：user-web → 编排画布 → 拖入「转人工」节点 → 属性面板点「选择审批人」→ 按部门过滤 + 关键字搜索 → 选中 → 保存 YAML，`node.data.approver` 应为 32-hex user_id。

## 注意事项

- 审批人按**租户 + 部门**选择，跨租户候选不返回；前端刷新后需重新登录（32-hex 归一后旧 24-hex 会话/缓存失效）。
- 超时未决策 → 节点失败、下游按 010 FR-6 阻塞，并写审计事件；**没有自动批准**。
- 服务重启后恢复扫描重建挂起运行，长效待办不丢；同一运行不会被并发恢复（租约）。
- `orchestration_runs` 已纳入 `tenant_purge` 租户清除清单（2026-11-11 审计修复）。

## 通过判据

- [ ] `tests/orchestration/` 全绿，`vue-tsc --noEmit` exit 0
- [ ] 画布往返四个 payload 字段无损
- [ ] 挂起运行可在 `orchestration_runs` 查到，批准后续跑且已完成节点不重复执行
- [ ] 发起人自审被拒、超时 fail-closed、驳回走 `on_reject`
