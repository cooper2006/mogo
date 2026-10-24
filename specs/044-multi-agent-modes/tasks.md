# Tasks: 多 Agent 轮询择优 / 辩论对质模式（044-multi-agent-modes）

**Input**: Design documents from `/specs/044-multi-agent-modes/`

**Prerequisites**: plan.md (required), spec.md (required)

**性质**: **2026-10-24 完成**（本会话按门禁实现并勾选 26/26）——改 010 引擎，含 010 spec/契约联合改动点。

**Tests**: `services/chat-api/tests/orchestration/` pytest（新增三测试文件；既有四测试文件零修改全绿）。

**Organization**: Phase 0 研究与澄清 → Phase 1 设计 → Phase 2 实现 → Phase 3 验证与接线；T001 起连续编号，全部 `- [x]`。

---

## Phase 0: 研究与澄清

- [x] T001 建立 spec/plan/tasks 三件套（`specs/044-multi-agent-modes/`，本文件）
- [x] T002 核实 010 引擎既有分发缺口：`competitor_deep_dive.py:372-394` 直接调 `run_graph`（mode 未参与分发）、`Node.mode`（`graph.py:25`）与 `registry.py:49` 的节点级 mode 解析现状，确定统一分发入口的迁移面
- [x] T003 澄清 `fair_selection.py` 复用方式：核实 `enterprise_capabilities/__init__.py` 与 `research/competitor_deep_dive.py` 的 import 方向（后者 import `app.orchestration`），确认跨包 import 会造成依赖倒置/循环风险，落实"包内纯函数复刻 + docstring 标注来源"方案
- [x] T004 澄清择优与收敛的确定性口径：`highest_score` 的 score 字段约定（候选输出的哪个键）、`majority` 的归一化规则（去空白/大小写折叠）、收敛相似度算法（Jaccard vs `difflib.SequenceMatcher`）与默认阈值
- [x] T005 澄清 Trace 事件形态：确认新模式事件与既有 `started/completed/failed/skipped/blocked` 的同构方式（新增 `candidate_*` / `debate_round_*` / `converged` 等事件类型），以及与 `competitor_deep_dive._emit("dag.*")` 审计出口的对接点

## Phase 1: 设计

- [x] T006 设计 `round_robin.py` 契约：`RoundRobinPlan`（候选/策略/并发）、`CandidateOutcome`、`SelectionResult` 的字段与执行签名（runner 注入，transport-agnostic）
- [x] T007 设计 `debate.py` 契约：`DebateProtocol` 状态机（轮次/正反历史/收敛原因/裁决置信度）、`ArbiterVerdict`、共享上下文轮次键命名（`debate.round_N.pro/con`）与终止判定顺序
- [x] T008 设计 `dispatch.py` 入口：`execute_orchestration(loaded, runner, *, context)` 的 mode → 执行器路由表；六模式中四个委托既有实现（`run_graph` / `run_sequential` / `Supervisor` / `run_hybrid`），两个走新模块
- [x] T009 设计 loader/registry 扩展：`_PAYLOAD_KEYS` 新键（`instances` / `select` / `arbiter` / `max_rounds` / `convergence_threshold`）与 `VALID_MODES` 六模式校验的落点；`max_rounds` 越界钳制（1..10）与 `arbiter` 不存在时的加载期报错
- [x] T010 设计契约文档结构：`contracts/orchestration.md` 六模式表 + 两种新模式 YAML 形态（示例须可被 `load_orchestration_text` 加载）
- [x] T011 Constitution Check 复核（plan.md 门禁）：确认既有四模式零行为改动、无新依赖、无治理旁路、均衡选取不跨包 import

## Phase 2: 实现

- [x] T012 [P] `graph.py`：`VALID_MODES` 扩展为六模式（`("sequential", "supervisor", "hybrid", "graph", "round_robin", "debate")`）
- [x] T013 [P] `round_robin.py`（新增）：候选执行（信号量并发，默认 4）+ 三策略择优器（first_success / highest_score / majority，含既定回退规则）+ 均衡分组纯函数（复刻 `round_robin_take` 思想，docstring 标注来源）+ 择优依据记录
- [x] T014 [P] `debate.py`（新增）：多轮交锋循环（每轮读对方上轮输出）+ 三类终止条件（轮次上限钳制 / 置信度阈值 / 相似度收敛）+ 裁决消费与 `ArbiterVerdict` 产出
- [x] T015 [P] `dispatch.py`（新增）：统一分发入口（T008 路由表）；`__init__.py` 导出新符号
- [x] T016 `loader.py`：`_PAYLOAD_KEYS` 扩展新键（T009）；`max_rounds` 越界钳制 + 记事件；`arbiter` 不存在时加载期报错（fail-closed）
- [x] T017 `registry.py`：`validate()` 的 mode 校验接受六模式（`to_graph` 结构不变）
- [x] T018 `enterprise_capabilities/research/competitor_deep_dive.py`：调用点迁移到 `dispatch.execute_orchestration`（L372-394 区域），graph 行为不变
- [x] T019 `contracts/orchestration.md`：四模式契约表 → 六模式；新增 round_robin / debate 的 YAML 形态与语义小节

## Phase 3: 验证与接线

- [x] T020 [P] `tests/orchestration/test_round_robin.py`（新增）：三策略语义、无 score/无多数回退、单实例退化、并发上限、全失败 → 节点 failed + 下游阻塞
- [x] T021 [P] `tests/orchestration/test_debate.py`（新增）：轮次 ≤ 上限（含复读型对抗输入）、三类终止条件各自触发、arbiter 缺失加载期报错、正反失败传播
- [x] T022 [P] `tests/orchestration/test_mode_dispatch.py`（新增，实际文件名）六模式路由正确；迁移后 `competitor_deep_dive` 行为不变（graph 仍走 `run_graph`）
- [x] T023 YAML 加载用例：契约文档中的两种新模式示例可加载；新键非法值（如 `instances` 为空、`arbiter` 不存在）加载期 fail-closed
- [x] T024 回归门禁：`tests/orchestration/` 既有四文件（`test_engine.py` / `test_supervisor.py` / `test_orchestration.py` / `test_competitor_deep_dive.py`）**零修改**全绿；`git diff` 断言 `engine.py` / `supervisor.py` 既有函数无行为改动
- [x] T025 **联合改动点**：同步更新 `specs/010-dag-orchestration-engine/spec.md` 与 `plan.md` 的模式枚举描述（四模式 → 六模式，新增两模式的语义摘要与指向 044 的引用）；010 tasks.md 补记本轮联合改动条目
- [x] T026 文档接线：在 001/007 对应 spec 的"跨特性关系"补记本特性的双向声明（仅文档，不改代码）；本目录 tasks 勾选状态更新（含本条）

---

## Dependencies & Execution Order

- Phase 0（T001-T005）全部完成后进入 Phase 1；T003 的结论是 T013 实现方式的输入，T004 是 T013/T014 的默认值输入，T005 是事件形态输入。
- Phase 1：T006-T010 为 Phase 2 契约；T011 门禁在 Phase 2 前必须通过。
- Phase 2：T012-T015 四个 [P] 可并行；T016 依赖 T009；T017 依赖 T012；T018 依赖 T015；T019 依赖 T006/T007/T010。
- Phase 3：T020-T023 可并行；T024 为回归门禁（必须先于 T025/T026 通过）；T025/T026 收尾。
- Checkpoint：Phase 1 完 = 三模块契约 + 分发路由 + 文档结构冻结；Phase 2 完 = 六模式可加载可执行 + 契约刷新；Phase 3 完 = 新测试全绿 + 既有零修改全绿 + 010 文档联合刷新。

## Notes

- `VALID_MODES` 扩展是 010 的联合改动：代码改 `graph.py`，文档改 010 spec/plan 与 `contracts/orchestration.md`——三处必须同批，避免"代码六模式、契约四模式"的分叉（T012/T019/T025）。
- 均衡选取复刻而非 import：`round_robin_take` 仅 18 行纯函数（`fair_selection.py`），复刻成本趋近于零，而跨包 import 会倒置依赖（T003 论证）；复刻处 docstring MUST 标注思想来源路径。
- 择优/收敛全部确定性口径：引擎不调 LLM 做评审——"评分"由候选执行体自带（score 字段），"收敛"由文本相似度判定；需要语义级评审时用 `arbiter` 节点（编排声明），这是本特性与"内置评审器"路线的根本分界。
- 迁移 `competitor_deep_dive.py` 只改调用点（`run_graph` → `dispatch.execute_orchestration`），不改其 runner/审计/发布逻辑；该文件的既有测试（`test_competitor_deep_dive.py` + `_audit.py`）是行为不变的判据。

## 验收状态（2026-10-24 实现复核）

**已勾选 26/26**。落地文件（`services/chat-api/app/orchestration/`）：
`graph.py`（`VALID_MODES` 六模式）、`registry.py`（validate 校验 mode）、`loader.py`
（`_PAYLOAD_KEYS` 新键 + `_validate_044_shapes` 加载期 fail-closed）、
`round_robin.py`（新增）、`debate.py`（新增）、`dispatch.py`（新增）、`__init__.py`
（导出）；迁移 `enterprise_capabilities/research/competitor_deep_dive.py`
（`run_graph` → `execute_orchestration`，T018）。

**测试证据**：
- 新增 `tests/orchestration/test_round_robin.py` + `test_debate.py` +
  `test_mode_dispatch.py`：**45 passed**（T020/T021/T022）。
- 回归门禁（T024）：`tests/orchestration/` 全量 **136 passed**，既有
  `engine.py` / `supervisor.py` 零改动；`test_competitor_deep_dive.py` +
  `_audit.py` 迁移后 **28 passed**（graph 行为不变）。
- 跑法：`cd services/chat-api && python3 -m pytest tests/orchestration -o addopts="" -q -p no:cacheprovider`。

**联合文档（T025/T026）**：新建
`specs/010-dag-orchestration-engine/contracts/orchestration.md`（六模式 YAML 形态）；
`quickstart.md` §5 "Four modes" → "Six modes"；010 `spec.md` 补「跨特性关系（044 补记）」、
`plan.md` 补「文档产出（044 联合更新）」。044 spec 补 R-17~R-20（实现期回填）。

**实现期口径澄清**（与 spec 原文差异，已按实现回填）：
1. T022 测试文件实际命名为 `test_mode_dispatch.py`（任务原文 `test_dispatch.py`）。
2. R-13 预研假设 `engine.py::run_orchestration` 存在——实际该函数不存在，
   生产调用点仅 `competitor_deep_dive.py` 一处，已按实际枚举并迁移。
3. `supervisor` / `hybrid` 当前无生产调用点，`execute_orchestration` 要求调用方
   显式传入 `sequential_ids` / `parallel_ids` / `supervisor_id`（R-19）。
