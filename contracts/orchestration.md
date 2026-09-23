# Orchestration Contract (010)

> 010-dag-orchestration-engine — 编排定义 schema + 四模式契约。
> 本文件定义 chat-api `app/orchestration/` 与 `app/services/dag/` 的对外接口与不变量。

## 编排定义 schema

```jsonc
{
  "version": "3",                 // T021 版本化：最新为 active，旧版可回看
  "mode": "graph",               // sequential | supervisor | hybrid | graph (VALID_MODES)
  "nodes": [
    {
      "id": "fetch",
      "condition": {"op": "==", "left": {"var": "total"}, "right": 0},  // 受限 JSON 条件（FR-4）
      "retry": {"max_attempts": 3, "base_seconds": 2.0, "factor": 2.0, "cap_seconds": 60.0}
    }
  ],
  "edges": [ {"from": "fetch", "to": "plan"} ]
}
```

- 条件为**受限 JSON 对象**（永不执行代码）：比较（`== != > >= < <= in has`）、
  逻辑（`and`/`or`/`not`）、`{"var": "path.to.value"}` 变量引用。
- 未知算子 / 形状错误 / 变量无法解析 → `ConditionError`（fail-closed）。

## 四模式契约

| 模式 | 语义 |
| --- | --- |
| `sequential` | 节点顺序执行 |
| `supervisor` | supervisor 调度子节点 |
| `hybrid` | 顺序 + 并行混合 |
| `graph` | DAG 拓扑执行（本特性主模式） |

## 条件跳过（T013-T015 / US3）

`evaluate_skip(graph, node_id, context, downstream_policy)` -> `SkipDecision`
- 条件真 → 跳过（reason=`condition_true`），下游按 `downstream_policy` 处理
  （`propagate` / `continue` / `none`）。
- 条件假 → 运行（reason=`condition_false`）。
- 无条件 → 运行（reason=`no_condition`）。
- 语法错误 → fail-closed 跳过（reason=`syntax_error`，记录 error，US3 三组验收之一）。

跳过追溯（T014）：`skip_trace_document(decision)` 输出
`{node_id, skipped, reason, result, error, affected_downstream}` —
reason = 求值结果 + 被跳过的下游标记。

## 节点重试（T016-T017 / US4）

`RetryPolicy(max_attempts, base_seconds, factor, cap_seconds, delegate_model_backoff)`
- `backoff_delay(attempt)` 指数退避：`base * factor^(attempt-1)`，封顶 `cap_seconds`。
- `run_node_with_retry(node_id, coro, policy, sleep, on_attempt)` 节点级重试。
- **分层不重复（T017）**：`delegate_model_backoff=True` 时，模型级退避归 007
  韧性调度器，节点层只做节点重试，不重复模型退避。

## 双轨迁移 + 等价回归（T018-T019）

`content_plan_dag` 把 legacy content-builder 的 semantic/structured/fallback 三路径
搬到 DAG（双轨：legacy 仍为 source of truth）。
`builder_equivalent(legacy_plan, dag_result, plan_getter?, keys?)` 断言新旧路径
输出一致（回归 0 破坏，T019）。

## 并发预算（T020 / FR-12）

多 DAG 并行受 007 LLM 网关并发预算约束：超限退避排队，不超网关。

## 版本化（T021）

编排定义带 `version`；版本递增，旧版可回看（`max(version)` 为 active）。
