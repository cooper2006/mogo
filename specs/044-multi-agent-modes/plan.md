# Implementation Plan: 多 Agent 轮询择优 / 辩论对质模式（044-multi-agent-modes）

**Branch**: `044-multi-agent-modes` | **Date**: 2026-10-23 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/044-multi-agent-modes/spec.md`

**Note**: **全新特性**（整合方案 §4.13 立项，代码尚未开工）——spec 先行，tasks 全部未勾选；本特性改 010 引擎（含 010 spec/契约的联合改动点），既有四模式零改动。

## Summary

在 010 DAG 引擎（`services/chat-api/app/orchestration/`）新增两种协作模式：

- **`round_robin`**（新模块 `round_robin.py`）：同一任务节点的多份 `instances:` 候选经同一 runner 接口执行（并发受 `max_concurrency` 约束），按可配置策略择优——`first_success` / `highest_score`（默认，无 score 回退 first_success）/ `majority`（无多数回退 first_success）；候选分组均衡选取的思想复刻自 `enterprise_capabilities/evidence/foundation/fair_selection.py` 的 `round_robin_take`（**以包内轻量纯函数复刻，不跨包 import**——理由见 Complexity Tracking）；择优结果与依据进 Trace。
- **`debate`**（新模块 `debate.py`）：正反 Agent 多轮交锋（每轮读对方上轮输出，共享上下文按轮次键写入），`arbiter` 裁决节点产出结论 + 置信度；终止条件 = 轮次上限（默认 3，可配 1..10）/ 置信度 ≥ 0.8 / 正反连续两轮高相似（Jaccard 口径，思想同源 011）——保证不死循环。

两种模式完整继承 010 既有设施（`RetryPolicy` 节点重试、`conditions.py` 条件跳过、`dag.*` Trace 事件、FR-6 失败阻塞闭包），并可作为 graph 子节点（`Node.mode` 声明 + 新增统一分发入口 `dispatch.py`）。`VALID_MODES` 扩展为六模式；`contracts/orchestration.md` 与 010 spec/plan 同步刷新（联合改动点）。既有四模式执行路径零改动。

## Technical Context

**Language/Version**: Python 3.11+（chat-api）

**Primary Dependencies**: 既有 `app.orchestration` 包（`engine.py` / `graph.py` / `topo.py` / `conditions.py` / `registry.py` / `loader.py` / `supervisor.py`）、`app.services.dag.retry.RetryPolicy`、`yaml`（loader 已在用）；**不引入新第三方依赖**；标准库 `statistics`/`difflib`（Jaccard 可用 `difflib.SequenceMatcher` 或自写，避免引第三方文本相似度库）

**Storage**: 编排定义经既有 `dag_definitions` 集合持久化（`orchestration/store.py` 的 `load_orchestration_persisted`，competitor_deep_dive 已用）；新模式无新集合——`instances:` / `arbiter` / `max_rounds` / `select` 全部进节点 payload 或文档级设置（loader `_PAYLOAD_KEYS` 扩展）

**Testing**: pytest（`services/chat-api/tests/orchestration/` 既有树）：新增 `test_round_robin.py` / `test_debate.py` / `test_dispatch.py`；既有 `test_engine.py` / `test_supervisor.py` / `test_orchestration.py` / `test_competitor_deep_dive.py` 零修改全绿；YAML 加载用例（新键合法/非法）

**Target Platform**: Docker Compose（chat-api）

**Project Type**: web-service 后端引擎扩展（同 010）

**Performance Goals**: round_robin 候选并发受既有 `max_concurrency`（默认 4）约束，超限排队（与 graph 同口径，FR-2 延续）；debate 轮次有硬上限，最坏 token 消耗 = 轮次上限 × 单轮正反+裁决，可预算；无轮次的循环 MUST NOT 存在（收敛条件全部为确定性判定，无外部阻塞等待）

**Constraints**: 不改既有四模式函数行为（`run_graph` / `run_sequential` / `Supervisor` / `run_hybrid` 零行为改动）；`contracts/orchestration.md` 与 010 spec/plan 必须同批刷新（联合改动点）；引擎保持 transport-agnostic（节点工作 = 任意 async callable，不依赖 DSH runtime/DB）；新模式无治理旁路（审计出口不变）

**Scale/Scope**: 2 个新模块（round_robin / debate）+ 1 个分发模块 + 3 处枚举/读取扩展（`graph.py` VALID_MODES、`loader.py` payload 键、`registry.py` mode 校验）+ 1 个调用点迁移（competitor_deep_dive）+ 契约/010 文档刷新；0 新依赖、0 新集合

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Specification-First**: ✅ 本三件套先于代码；五个决策点（策略/实例来源/轮次与终止/裁决形态/组合关系）已拍板，YAML 契约形态进 FR 与契约文档。
- **II. Enterprise Production Readiness**: ✅ 失败路径全部显式：候选/轮次全失败 → 节点 failed + 下游阻塞（FR-6）；`arbiter` 不存在 → 加载期 fail-closed；越界配置钳制 + 记事件；无死循环由"轮次硬上限 + 确定性收敛判定"保证；既有四模式零回归由测试门禁守护。
- **III. Security and Data Protection**: ✅ 无新数据出口：新模式经既有 runner 注入执行体，模型调用仍过 007 韧性 + 001 门禁（节点 = 原子执行，门禁粒度不变）；审计出口不变（`dag.*` 事件进 001 审计流）；择优/收敛判定为纯文本计算，无额外数据外传。
- **IV. Cross-Platform and i18n**: ✅ 纯后端引擎，无用户界面文案；YAML 键与错误信息沿用既有中文口径（`OrchestrationLoadError` 等既有风格）。
- **V. Observability and Simplicity**: ✅ 复用而非另起：重试/条件/Trace/阻塞全部委托既有实现；新模式仅各自一个模块 + 一个薄分发层；择优与收敛均为确定性口径（无内置 LLM 评审器）；均衡选取以包内小纯函数复刻而不引入跨包依赖（见下）。

## Project Structure

### Documentation (this feature)

```text
specs/044-multi-agent-modes/
├── spec.md              # 特性规约（六模式扩展/FR/SC/关联特性）
├── plan.md              # 本文件
└── tasks.md             # 任务清单（Phase 0-3，全部未勾选）
```

### Source Code (repository root)

```text
services/chat-api/app/orchestration/
├── graph.py               # 【修改】VALID_MODES 扩展为六模式（+round_robin +debate）；
│                           #  Node.mode 字段已存在（L25），不改
├── loader.py              # 【修改】_PAYLOAD_KEYS 扩展（instances/select/arbiter/
│                           #  max_rounds/convergence_threshold 等新键进 payload）；
│                           #  L274 mode 读取逻辑不变（未声明即 graph）
├── registry.py            # 【修改】mode 校验接受六模式（validate 与 to_graph 保持既有结构）
├── round_robin.py         # 【新增】候选执行 + 三种择优策略 + CandidateOutcome/SelectionResult；
│                           #  均衡分组思想复刻自 fair_selection.py（包内纯函数，docstring 标注来源）
├── debate.py              # 【新增】DebateProtocol 多轮循环 + 三类终止条件 + 裁决消费 +
│                           #  ArbiterVerdict；轮次上限钳制
├── dispatch.py            # 【新增】统一分发入口：文档级 mode → 模式执行器
│                           #  （sequential/supervisor/hybrid/graph 委托既有实现，
│                           #   round_robin/debate 走新模块）
└── __init__.py            # 【修改】导出新符号（RoundRobin*/Debate*/dispatch）

services/chat-api/app/enterprise_capabilities/research/
└── competitor_deep_dive.py  # 【修改】调用点迁移到 dispatch 入口（L372-394 区域），
                              #  graph 行为不变（仍走 run_graph）

contracts/
└── orchestration.md       # 【修改】四模式契约表 → 六模式；新增两种模式 YAML 形态与语义

specs/010-dag-orchestration-engine/   # 【联合改动】010 spec/plan 模式枚举描述刷新为六模式
                                      #  （任务列于 tasks.md，不在本特性任务外另建 spec）

services/chat-api/tests/orchestration/
├── test_round_robin.py    # 【新增】三策略语义/回退/并发/全失败
├── test_debate.py         # 【新增】轮次上限/三类收敛/arbiter 缺失/失败传播
└── test_dispatch.py       # 【新增】六模式分发路由 + 既有调用点行为不变
# 【零修改】test_engine.py / test_supervisor.py / test_orchestration.py /
#           test_competitor_deep_dive.py（既有四模式回归门禁）
```

**Structure Decision**: 严格沿袭 010 的既有模块格局——每个协作模式一个模块（`supervisor.py` 是先例：Supervisor 类 + `run_hybrid` 函数同居），引擎核心（`engine.py`）不放模式特化逻辑；分发收敛到单一入口 `dispatch.py`，消除 `competitor_deep_dive.py:394` 式"直接调 `run_graph`"的硬编码，为后续所有模式（含未来扩展）提供同一入口。均衡选取**不跨包 import** `enterprise_capabilities`：`enterprise_capabilities/__init__.py` 导入能力包体系、其 `research/competitor_deep_dive.py` 反向 import `app.orchestration`——orchestration 回 import 该包会造成依赖倒置与循环风险；以 10 行包内纯函数复刻 `round_robin_take` 思想并 docstring 标注来源，保持 orchestration 包"dependency-light core"的既有定位（其 `__init__.py` docstring 明示）。

## Complexity Tracking

> 无 constitution 违规，无需复杂度论证。

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| （无） | — | — |

**已评估并拒绝的复杂度**（记录备查）：① 跨包 import `fair_selection.round_robin_take`——造成 orchestration → enterprise_capabilities 依赖倒置（后者已 import 前者），循环风险；改为包内复刻 + 来源标注。② 内置 LLM 评审器做择优/收敛——把非确定性引入引擎核心，违背 transport-agnostic 与可测试性；改为确定性口径 + 显式回退 + `arbiter` 节点（评审是编排声明的事）。③ 候选结果缓存/同输入去重——无场景数据支撑，YAGNI。④ 新模式的独立 Trace 体系——必然与既有 `dag.*` 事件分叉；改为同构事件 + 同一审计出口。
