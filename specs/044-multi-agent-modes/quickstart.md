# Quickstart: 多 Agent 协作模式 (044)

**Feature**: [spec.md](./spec.md) | [plan.md](./plan.md) | [tasks.md](./tasks.md) | [checklists/requirements.md](./checklists/requirements.md)

本文件说明如何**启用并验证** 多 Agent 协作模式（044）。

---

## 1. 前置

- 相关服务已部署：chat-api（视特性所属服务而定）
- MongoDB 可用（或 PanWeiDB 可选后端；`MOGO_DATA_BACKEND` 未设置即 MongoDB，行为不变）
- 后端测试需 Python 3.10+ 与对应服务 venv；前端测试需 Node/pnpm

## 2. 该特性做了什么

扩展 010 引擎协作模式，新增 `round_robin`（多实例并行/轮询 + 可配置择优）与 `debate`（正反 Agent 多轮交锋 + 裁决收敛）两种 mode，走 010 既有基础设施，不改既有四模式语义。

关键功能需求（FR 摘要）：
- FR-001：编排引擎 MUST 支持六模式：`sequential | supervisor | hybrid | graph | round_robin | debate`（`graph.py` `VALID_MODES` 扩展；`registry.py` 默认值与 `loader.py:274` 读取逻辑保
- FR-002：`round_robin` 模式 MUST 对同一任务节点的多份 `instances:` 候选执行，并 MUST 支持三种可配置择优策略 `first_success` / `highest_score` / `majority`；默认 `highest_score`，无评分字段时回退 `firs
- FR-003：`round_robin` 的候选执行 MUST 受 `max_concurrency` 约束（与 graph 模式同口径，默认 4），超限排队不拒绝。
- FR-004：`round_robin` 的择优结果 MUST 可解释：Trace/事件流 MUST 含各候选输出、评分/状态与择优依据（选中项 + 策略 + 回退原因）。
- FR-005：`debate` 模式 MUST 实现正反 Agent 多轮交锋：每轮双方可读取对方上一轮输出（共享上下文按轮次键写入）。

关键验收点（Success Criteria）：
- SC-001: 两种新模式可经 YAML 定义并真实执行（`load_orchestration_text` 加载 → 分发执行 → 结果写入共享上下文），契约文档示例即可执行。
- SC-002: round_robin 三种择优策略行为正确且结果可解释：Trace 可见各候选与择优依据；策略回退（无 score / 无多数）有记录。
- SC-003: debate 有轮次上限与收敛保证：任何配置下轮数 ≤ `max_rounds`，三类终止条件均可触发提前收敛且原因可查；无死循环（含复读型对抗输入）。
- SC-004: 既有四模式回归零改动通过：`tests/orchestration/` 全量（`test_engine.py` / `test_supervisor.py` / `test_orchestration.py` / `test_competitor_deep_div

## 3. 如何启用

无显式开关，随代码落地生效；六模式经 010 YAML `mode:` 声明（`round_robin`/`debate` 为新增），其余四模式语义不变。

## 4. 如何验证

### 4.1 自动化测试（首选）

逐服务运行下列实测测试文件（INDEX 记录全绿）：


**chat-api（后端）**：
```bash
cd services/chat-api && python -m pytest services/chat-api/tests/orchestration/test_round_robin.py services/chat-api/tests/orchestration/test_debate.py services/chat-api/tests/orchestration/test_mode_dispatch.py services/chat-api/tests/orchestration/test_competitor_deep_dive.py -q
```

## 5. 注意事项

- 标准深度审计（2026-11-04）确认本特性 `tasks.md` 已 100% 勾选、代码已落地；测试以 INDEX 记录的全绿数为准，**发布前仍建议 CI 跑一次对应服务全量 pytest 对齐计数**。
- 跨特性依赖已在 spec「跨特性关系 / 判定口径补充」节声明（如 036→001/032、037→016/018/036、041→018/034、042→020/008、046→035/042），启用时注意相关特性就绪状态。
