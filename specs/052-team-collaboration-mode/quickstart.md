# Quickstart: 052 团队协作模式（team）

**状态**：已实现（22/22 tasks 全勾）；T015 按「人工接管 = 050 跨模式挂起，P2 预留」定清首期软依赖边界。

## 做了什么

010 编排引擎扩展第七模式 `team`：领导节点拆解任务并指派成员 → 成员异步执行 → 共享材料写团队黑板（版本保留、不覆盖）→ 领导验收（accept / rework 退回重做，轮次上限默认 3，可配 1..5）→ 达上限仍不合格则团队失败，不无限循环。完整继承 010 的节点重试 / 条件跳过 / Trace 事件 / 失败阻塞，可作为 graph 子节点。

- 代码：`services/chat-api/app/orchestration/` 的 `graph.py`（`VALID_MODES`）、`team.py` / `engine.py`；运行持久化复用 050 的 `orchestration_runs`（checkpoint + 恢复）。
- 黑板条目含作者 / 版本 / 内容；单成员失败不拖垮其余成员，重指派次数有上限。
- 人工接管复用 050 `human_approval` 语义，决策覆盖领导判定并全审计。

## 前置条件

1. kiri 生产栈在线；050 的 `human_approval` 节点与 `orchestration_runs` 可用。
2. 编排定义中声明的成员 id 均存在（分派表引用不存在成员会 fail-closed）。
3. 046 project 共享上下文可用（成员间共享材料依赖）。

## 如何启用

```yaml
mode: team
nodes:
  - id: lead
    type: supervisor          # 拆解 + 指派 + 验收
  - id: member_a
    type: worker
  - id: member_b
    type: worker
team:
  max_rounds: 3              # 1..5，越界钳制并记事件
  blackboard: true
```

未声明 `mode` 仍默认 `graph`（loader 既有语义不变）。

## 如何验证

```bash
cd /Users/cooper/mogo/services/chat-api
./.venv/bin/python -m pytest tests/orchestration/test_team.py -q -o addopts=
./.venv/bin/python -m pytest tests/orchestration/ -q -o addopts=   # 六模式零回归
```

## 注意事项

- 事件与既有 `item.*` 同构，轮次 / 黑板明细收在 payload（044 R-9）。
- team 节点作为 graph 子节点时按原子成功 / 失败处理（044 R-16）。
- 首期人工接管按 050 跨模式挂起实现；P2 的独立接管 UI 属预留，不在此验收范围。
- 成员异步执行走 050 持久化，服务重启后可恢复；已完成节点不重复执行。

## 通过判据

- [ ] `test_team.py` 与 `tests/orchestration/` 全绿
- [ ] 分派表引用不存在成员时 fail-closed
- [ ] rework 达上限团队失败且无无限循环
- [ ] 黑板旧版本保留；单成员失败不影响其余成员
