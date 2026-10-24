# Feature Specification: 多 Agent 轮询择优 / 辩论对质模式（010 引擎扩展）

**Feature Branch**: `044-multi-agent-modes`

**Created**: 2026-10-23

**Status**: Draft

**Input**: 整合方案 §4.13：010 引擎扩两种 mode——round_robin（同任务多实例投票择优，可复用证据模块 `fair_selection.py` 的均衡选取思想）、debate（正反 Agent 多轮 + 裁决节点）。属引擎扩展，不影响既有四模式。文章五种模式中 mogo 缺两种：轮询择优、辩论对质。

> **设计来源**：本规约来自 `docs/MOGO-AgentOS整合方案.md` §4.13（2026-10-23 代码级勘察结论）。
>
> **性质说明**：**全新特性，代码尚未开工**——与 031 的"回溯补规格"本质不同，本特性先把规约拍板再进入实现；`tasks.md` 全部任务未勾选。
>
> **背景事实（代码级核实）**：`services/chat-api/app/orchestration/engine.py`（`run_graph` L84-195 信号量并发 + 上游失败阻塞闭包、`run_sequential` L197-215、`_run_single` L217-238）；`supervisor.py:63-146`（分派 + 聚合 + 失败阈值传播，`DEFAULT_CHILD_FAILURE_THRESHOLD = 1.0` L25）与 `run_hybrid` L149-180；模式枚举 `graph.py:13` `VALID_MODES = ("sequential", "supervisor", "hybrid", "graph")`，模式声明 `registry.py:29`（`mode: str = "graph"`）与 loader 读取 `loader.py:274`（`mode = str(header.get("mode") or "graph")`）；`Node` 自带 `mode` 字段（`graph.py:25`）；`round_robin` 全仓唯一无关命中是 `services/chat-api/app/enterprise_capabilities/evidence/foundation/fair_selection.py` 的 `round_robin_take`（证据分组均衡选取，纯函数无包依赖）；`debate`/辩论 0 命中；生产分发点在 `enterprise_capabilities/research/competitor_deep_dive.py:372-394`（构造 `DagEngine` 后直接调 `run_graph`，mode 尚未参与分发）。

## 定位（一句话）

扩展 010 DAG 引擎的协作模式——新增 `round_robin`（同一任务多实例并行/轮询执行 + 可配置择优：首个成功 / 评分最高 / 多数一致）与 `debate`（正反 Agent 多轮交锋 + 裁决节点收敛，轮次上限 + 终止条件防无限辩论）两种 mode；两者走 010 既有节点/条件/重试/Trace 基础设施，复用 `fair_selection.py` 的均衡选取思想做候选分组，**不改既有四模式语义**。

## 已定决策（2026-10-23，spec 撰写时拍板）

| # | 决策点 | 结论 | 落点 |
| --- | --- | --- | --- |
| 1 | 轮询择优的择优策略 | 首版支持三种可配置策略：`first_success`（首个成功即采用，余量候选取消）、`highest_score`（评分最高，候选输出须带 `score` 字段）、`majority`（多数一致，输出归一化后投票）；**默认 `highest_score`，无评分字段时回退 `first_success`**（YAGNI：不内置 LLM 评审器） | `round_robin.py` 择优器 |
| 2 | 实例来源 | 候选实例 = 同一任务节点的**多份实例配置**，由 YAML `instances:` 列表声明（每实例可覆写 model/temperature/prompt 变体），即"同模型多温度 / 多模型混合"；**不新建实例注册中心**（YAGNI，声明式即定义） | `loader.py` payload 键扩展 |
| 3 | debate 轮次上限与终止条件 | 默认 `max_rounds: 3`（可配 1..10）；终止条件（任一满足即收敛）：① 达到轮次上限；② 裁决节点置信度 ≥ `convergence_threshold`（默认 0.8）；③ 正反输出连续两轮相似度 ≥ 阈值（复用 011 Jaccard 思想，纯文本相似度，不调 LLM）。**保证不死循环** | `debate.py` 协议循环 |
| 4 | 裁决节点形态 | 首版 = **独立裁决 Agent 节点**（debate 的 `arbiter` 字段指定一个普通节点 ID 作为裁决者，读取正反交锋记录产出结论 + 置信度）；规则聚合（如"取正方"）不做（YAGNI，留扩展） | `debate.py` + YAML `arbiter` 键 |
| 5 | 与既有四模式的组合关系 | **新模式的节点可作为 graph 的子节点**（`Node.mode` 字段已存在于 `graph.py:25`，定义态已支持节点级 mode 声明；运行时由本特性补上分发）：debate/round_robin 节点嵌入 graph 时，作为该节点的一次完整子执行（其内部 Trace/重试自成一体），对外仍表现为一个普通节点的成功/失败。论证：子节点语义正是"一个节点 = 一次可重试的原子执行"（010 FR-10），新模式不破坏原子性 | `dispatch.py` 分发 + `graph` 执行器 |

## User Scenarios & Testing *(mandatory)*

### User Story 1 - round_robin：同一任务多实例执行 + 可配置择优 (Priority: P1)

编排作者在 YAML 中把一个节点的 `mode` 声明为 `round_robin` 并用 `instances:` 列出多个候选实例（如两个不同温度的同一模型、或两个不同模型）；引擎并行/轮询执行全部候选，按配置的择优策略（默认评分最高）选出唯一结果写入共享上下文；Trace 中可见各候选的输出、评分/状态与择优依据。

**Why this priority**: 轮询择优是"多 Agent 协作"最常用的可靠性模式（多抽奖、多模型互备），也是两种新模式里实现与语义都更轻的一个；它复用 010 的并行调度与共享上下文，边际成本最低。

**Independent Test**: 定义 `mode: round_robin`、`instances:` 三个实例（mock runner 分别返回带 score 的输出），分别配置 `highest_score` / `first_success` / `majority` 跑三次，断言每次选中项与策略语义一致，且 Trace/事件流含各候选与择优依据。

**Acceptance Scenarios**:

1. **Given** 节点声明 `mode: round_robin` 且 `instances:` 有 N 个候选，**When** 执行，**Then** 全部候选经同一 runner 接口执行（并发受 `max_concurrency` 约束，与 graph 模式同口径）。
2. **Given** 择优策略为 `highest_score` 且候选输出带 `score`，**When** 执行完成，**Then** 选中 score 最高者，其输出写入共享上下文（节点 ID 为 key，延续 010 FR-1 数据传递语义）。
3. **Given** 择优策略为 `first_success`，**When** 任一候选成功，**Then** 立即采用该结果并取消/忽略余量候选（不等待全部完成）。
4. **Given** 择优策略为 `majority`，**When** 候选输出可归一化比较，**Then** 取得票多数者为选中；无多数时回退 `first_success` 并记录原因。
5. **Given** 任一策略下全部候选失败，**When** 执行结束，**Then** 该节点失败（`failed`），下游按 010 FR-6 阻塞，事件记录全部候选的失败原因。

---

### User Story 2 - debate：正反 Agent 多轮交锋 + 裁决节点收敛 (Priority: P1)

编排作者定义 `mode: debate` 的节点组：正方与反方 Agent 围绕同一议题多轮交锋（每轮读取对方上一轮输出），`arbiter` 指定的裁决节点在每轮末评估；达到轮次上限、置信度达标或输出收敛（连续两轮高相似）任一条件即终止，裁决节点产出最终结论。全程有轮次上限，不死循环。

**Why this priority**: 辩论对质是文章五种模式中 mogo 缺失的另一种协作形态，服务于"红蓝对抗 / 方案权衡"类场景；其收敛保证（轮次上限 + 终止条件）是引擎级正确性问题，必须与模式本身同批交付。

**Independent Test**: 定义 `mode: debate`（正/反/裁决三个节点，`max_rounds: 3`，mock runner 输出可控文本），断言：① 交锋轮数 ≤ 3；② 置信度 ≥ 0.8 时提前终止；③ 正反输出连续两轮 Jaccard ≥ 阈值时提前终止；④ 终止后裁决节点消费完整交锋记录并产出结论。

**Acceptance Scenarios**:

1. **Given** `mode: debate` 且正反节点就位，**When** 执行，**Then** 正反轮流发言，每轮可读取对方上一轮输出（共享上下文按轮次键写入，如 `debate.round_1.pro / con`）。
2. **Given** `max_rounds: 3`，**When** 三个终止条件均不满足，**Then** 第 3 轮后强制收敛（轮数 = 上限，绝不超过）。
3. **Given** 裁决节点在某轮给出置信度 ≥ 0.8，**When** 该轮结束，**Then** 提前收敛（剩余轮次不再执行）并记录收敛原因（`arbiter_confidence`）。
4. **Given** 正反连续两轮输出相似度 ≥ 阈值，**When** 检测到，**Then** 提前收敛并记录原因（`output_converged`）。
5. **Given** 收敛发生，**When** 查看结果，**Then** 裁决节点输出 = 最终结论，完整交锋记录可从 Trace/事件流还原（轮次、正反输出、收敛原因）。
6. **Given** 正方或反方节点失败，**When** 执行中，**Then** 辩论失败（节点失败语义），不进入裁决；下游按 FR-6 阻塞。

---

### User Story 3 - 新模式继承 010 既有基础设施（Trace/重试/条件/失败阻塞） (Priority: P1)

两种新模式不另起炉灶：节点级重试（`retry.py` / `RetryPolicy`）、条件跳过（`conditions.py`）、Trace 事件（每轮/每候选/每次收敛均发事件）与失败阻塞闭包（FR-6）全部沿用 010 既有实现；既有四模式的执行路径零改动。

**Why this priority**: 这是"引擎扩展而非引擎分叉"的证明——如果新模式自带一套重试/Trace，可观测性与失败语义就会漂移，两套语义长期必然分叉；继承既有设施是本特性不增加系统复杂度的前提（宪法 V）。

**Independent Test**: 对 round_robin 节点配置 `retry`，使首个候选前两次失败第三次成功，断言重试事件（attempt/delay）按 `RetryPolicy` 记录；对 debate 的裁决节点配条件跳过，断言跳过原因可追溯；既有四模式测试（`tests/orchestration/` 全量）零修改全绿。

**Acceptance Scenarios**:

1. **Given** 新模式节点配置了 `retry`，**When** 候选/轮次执行失败，**Then** 按节点级指数退避重试（与 007 模型级重试分层不重复，延续 010 OQ-3）。
2. **Given** 新模式执行，**When** 查看事件流，**Then** 每候选启动/完成/失败、每轮交锋、每次收敛均发事件（与既有 `started/completed/failed/skipped` 同构），可进 001 审计流（`competitor_deep_dive.py` 的 `_emit("dag.*")` 口径）。
3. **Given** debate 节点作为 graph 子节点且内部失败，**When** 执行结束，**Then** 该子节点标记 `failed`，其下游闭包阻塞（010 FR-6 语义不变）。
4. **Given** 改造完成，**When** 运行既有四模式测试与 `test_competitor_deep_dive.py`，**Then** 全绿且零修改。

---

### User Story 4 - 契约与文档同步（六模式口径） (Priority: P2)

`contracts/orchestration.md` 的"四模式契约"表扩展为六模式，补充两种新模式的 YAML 形态（`instances:` / `arbiter` / `max_rounds` / 策略键）与语义；010 spec 的模式枚举描述同步更新（FR-1 口径），保证"契约即真相"。

**Why this priority**: 契约文档是 chat-api `orchestration` 包的对外接口真相（其 header 明示"定义对外接口与不变量"）；新模式不进契约，下游（编排作者、competitor_deep_dive 等消费方）就无法可信使用。低于引擎本体的优先级，但同批交付。

**Independent Test**: 人工核对 `contracts/orchestration.md` 六模式表与代码 `VALID_MODES` 一致；按契约文档中的 YAML 示例能成功加载并执行两种新模式（文档示例即可执行口径）。

**Acceptance Scenarios**:

1. **Given** 契约文档更新，**When** 查看模式表，**Then** 六模式（sequential/supervisor/hybrid/graph/round_robin/debate）语义齐备，与 `graph.py` `VALID_MODES` 一致。
2. **Given** 契约中的 round_robin / debate YAML 示例，**When** 用 `load_orchestration_text` 加载，**Then** 成功且字段（策略/实例/arbiter/轮次）进入节点 payload 或文档级设置。
3. **Given** 010 spec/plan 文档，**When** 查看模式枚举描述，**Then** 与六模式口径一致（联合改动点落地）。

---

### Edge Cases

- **候选/轮次全部失败**：round_robin 节点失败、debate 失败——均按 010 FR-6 阻塞下游，不静默成功。
- **`majority` 无多数**：回退 `first_success` 并记录原因（事件可见），不悬而不决。
- **`highest_score` 候选无 score 字段**：按已定决策 #1 回退 `first_success`；全部候选无 score 时同理。
- **`instances:` 只有一个实例**：round_robin 退化为单执行（仍走新模式路径，保证行为可预期），不报错。
- **debate 的 `arbiter` 指向不存在的节点**：加载期报错（fail-closed，与 registry validate 同风格），不进执行。
- **debate 轮次中一方持续复读**：收敛条件③（连续两轮高相似）触发提前终止，防止空转烧 token。
- **新 mode 与旧分发点共存**：`competitor_deep_dive.py` 现直接调 `run_graph`；本特性引入统一分发（`dispatch.py`）后，既有调用点行为不变（graph 仍走 `run_graph`）。
- **节点级 mode 与文档级 mode 冲突**：以节点级为准（`registry.py:49` 已按 `raw.get("mode") or self.mode` 解析），文档级为默认值——既有语义延续。
- **`max_rounds` 越界（0 或 >10）**：加载期钳制到 1..10 并记事件，不拒绝加载（与 `normalize_period` 的宽容归一化同风）。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 编排引擎 MUST 支持六模式：`sequential | supervisor | hybrid | graph | round_robin | debate`（`graph.py` `VALID_MODES` 扩展；`registry.py` 默认值与 `loader.py:274` 读取逻辑保持"未声明即 graph"不变）。
- **FR-002**: `round_robin` 模式 MUST 对同一任务节点的多份 `instances:` 候选执行，并 MUST 支持三种可配置择优策略 `first_success` / `highest_score` / `majority`；默认 `highest_score`，无评分字段时回退 `first_success`，`majority` 无多数时回退 `first_success` 并记录原因。
- **FR-003**: `round_robin` 的候选执行 MUST 受 `max_concurrency` 约束（与 graph 模式同口径，默认 4），超限排队不拒绝。
- **FR-004**: `round_robin` 的择优结果 MUST 可解释：Trace/事件流 MUST 含各候选输出、评分/状态与择优依据（选中项 + 策略 + 回退原因）。
- **FR-005**: `debate` 模式 MUST 实现正反 Agent 多轮交锋：每轮双方可读取对方上一轮输出（共享上下文按轮次键写入）。
- **FR-006**: `debate` MUST 有轮次上限（默认 3，可配 1..10，越界钳制并记事件）与三类终止条件（轮次上限 / 裁决置信度 ≥ 阈值（默认 0.8）/ 正反输出连续两轮高相似），任一满足即收敛——MUST NOT 无限辩论。
- **FR-007**: `debate` MUST 支持 `arbiter` 指定的独立裁决节点（读完整交锋记录，产出结论 + 置信度）；`arbiter` 指向不存在节点 MUST 加载期报错（fail-closed）。
- **FR-008**: 两种新模式 MUST 完整继承 010 既有设施：节点级重试（`RetryPolicy`，与 007 模型级分层不重复）、条件跳过（`conditions.py`）、Trace 事件（与既有 `started/completed/failed/skipped` 同构，可进 001 审计流）、失败阻塞闭包（FR-6）。
- **FR-009**: 新模式节点 MUST 可作为 graph 的子节点执行（`Node.mode` 声明 + 统一分发），子节点对外仍表现为一次原子的成功/失败（010 FR-10 语义不变）。
- **FR-010**: 既有四模式的执行路径与语义 MUST 零改动（`engine.py` / `supervisor.py` 既有函数不改行为；既有测试零修改全绿）。
- **FR-011**: `contracts/orchestration.md` MUST 同步扩展为六模式契约（含两种新模式的 YAML 形态与语义）；010 spec/plan 的模式枚举描述 MUST 同步（联合改动点）。
- **FR-012**: 新模式 MUST 引入统一分发入口（文档级 mode → 模式执行器），`competitor_deep_dive.py` 等既有调用点迁移到该入口后行为不变（graph 仍走 `run_graph`）。

### Key Entities

- **RoundRobinPlan**：轮询择优执行计划（候选实例列表 + 策略 + 并发度），由节点 payload 的 `instances:` / `select` / `max_concurrency` 物化。
- **CandidateOutcome**：单个候选的执行结果（实例 ID / 输出 / score / 状态 / 错误），择优器输入。
- **SelectionResult**：择优结果（选中候选 + 策略 + 依据 / 回退原因），写入共享上下文并进 Trace。
- **DebateProtocol**：辩论协议状态（轮次 / 正反历史 / 收敛原因 / 裁决置信度），驱动多轮循环与终止判定。
- **ArbiterVerdict**：裁决节点产出（结论 + 置信度），debate 的最终结果。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 两种新模式可经 YAML 定义并真实执行（`load_orchestration_text` 加载 → 分发执行 → 结果写入共享上下文），契约文档示例即可执行。
- **SC-002**: round_robin 三种择优策略行为正确且结果可解释：Trace 可见各候选与择优依据；策略回退（无 score / 无多数）有记录。
- **SC-003**: debate 有轮次上限与收敛保证：任何配置下轮数 ≤ `max_rounds`，三类终止条件均可触发提前收敛且原因可查；无死循环（含复读型对抗输入）。
- **SC-004**: 既有四模式回归零改动通过：`tests/orchestration/` 全量（`test_engine.py` / `test_supervisor.py` / `test_orchestration.py` / `test_competitor_deep_dive.py` 等）零修改全绿。
- **SC-005**: 新模式节点可作为 graph 子节点执行，子节点原子性（一次成功/失败）与下游阻塞语义不变。
- **SC-006**: 契约文档六模式表与 `VALID_MODES` 代码一致；010 spec/plan 联合改动点落地。

## Assumptions

- 候选实例的模型/温度覆写由既有模型配置体系消费（节点 payload 声明式传递），本特性不新建模型注册或路由（与 031/007 的边界：选"用哪个实例配置"是编排声明，选"哪个 provider 可达"是 007/031 的事）。
- `majority` 的"归一化比较"为首版简单口径（去空白/大小写折叠后的等价判定 + 可选字数分桶），不引入语义相似度模型；语义级投票留后续。
- 正反/裁决 Agent 的 prompt 模板由编排 YAML 的实例配置承载（payload 声明式），引擎不内置辩论 prompt 库。
- 收敛相似度阈值默认取一个保守值（如 Jaccard ≥ 0.9 视为复读收敛），租户可按场景调整——先有可用的默认，不追求理论最优。
- 010 引擎保持"transport-agnostic：节点工作是任意 async callable"（engine.py docstring）——新模式同样通过 runner 注入执行体，引擎不直接依赖 DSH runtime 或 DB。

## 跨特性关系（被依赖方视角，双向声明）

- **与 010（dag-orchestration-engine）**：本特性是 010 引擎的**直接扩展**——`VALID_MODES`（`graph.py:13`）、统一分发、Trace/重试/条件/阻塞全部落在 010 的代码与契约上；**既有四模式语义零改动**是硬约束（FR-010）。tasks 中列有"同步更新 010 spec/plan 与 `contracts/orchestration.md`"的联合改动点（FR-011/SC-006）——010 的对外契约文档由本特性负责扩展到六模式，010 spec 的模式枚举描述同步刷新。
- **与 001（gatekeeper-governance）**：新模式的门禁与审计**不变**——新模式的每轮/每候选事件经同一 `dag.*` 审计出口（`competitor_deep_dive.py` 的 `_emit` 口径）进 001 审计流；新模式不新增治理旁路，001 的六层门禁对 round_robin/debate 节点与其内部候选同样生效（节点 = 一次原子执行，门禁粒度不变）。
- **与 007（llm-gateway-resilience）**：新模式的模型调用走既有韧性——候选/轮次执行体经 runner 注入，模型调用仍过 007 的 failover/降级/退避/计量；节点级重试与模型级重试分层不重复（延续 010 OQ-3）。新模式不碰网关韧性代码。
- **与 011（dream-cycle-self-evolution）**：debate 的收敛相似度判定复用 011 的 Jaccard 思想（纯函数口径，非代码复用）；011 的自进化候选过滤与辩论择优是不同场景，仅思想同源。
- **与 016/018（市场/资产）**：轮询择优的候选实例指向既有已发布资产（Skill/Agent），经既有市场消费路径解析——本特性不新建资产通道（关系声明）。

## 判定口径补充（2026-10-24，/speckit-checklist 回填）

> 本节消解 `checklists/requirements.md` CHK001–CHK016 的口径缺口，不新增范围。核查基线：`services/chat-api/app/orchestration/`（`graph.py`、`registry.py`、`loader.py`、`engine.py`、`supervisor.py`、`topo.py`、`conditions.py`）、`services/chat-api/app/enterprise_capabilities/evidence/foundation/fair_selection.py`、`services/chat-api/app/enterprise_capabilities/research/competitor_deep_dive.py`、`services/chat-api/app/self_evolution/similarity.py`。**本特性尚未实现**（`VALID_MODES` 仍为四模式），以下为可执行规格。

- **R-1（CHK001 `instances` schema）**：`instances` 为节点级 `list[dict]`，每项允许覆盖键：`model`、`temperature`、`prompt`（与节点 `payload` 同名键的浅覆盖）、`label`（可选，用于 Trace 标识）。**不允许**覆盖 `retry`/`conditions`/`depends_on`（它们属节点级语义，覆盖会造成执行图歧义）；出现禁止键 → 加载期 `OrchestrationLoadError`（fail-closed）。`instances` 为空或缺失 → 视为单候选（退化为普通节点）。
- **R-2（CHK002 `score` 来源）**：`score` 由候选节点**自身输出**提供，取 `payload.score`（数值，`0.0–1.0`，越界夹取）；来源可以是模型 JSON 输出字段或节点配置的静态分。判定序：① 全部候选有 `score` → `highest_score`；② 部分候选有 `score` → 仅在有分候选间比较，无分候选**不参与择优但保留输出**；③ 全无 `score` → 回退 `first_success` 并在 Trace 记 `fallback_reason="no_score"`。
- **R-3（CHK003 `majority` 归一化）**：归一化 = `str(output).strip().lower()`，再去除所有空白字符（`re.sub(r"\s+", "", text)`）；不做标点/语义归一（YAGNI）。票数相同（平票）→ 取**最先完成**的候选，Trace 记 `majority_tie`。
- **R-4（CHK004 debate 上下文键）**：key 格式 `debate:{orchestration_id}:{node_id}:round:{n}:{side}`，`side ∈ {"pro","con"}`；存放于该 debate 节点的**局部共享字典**（不写入全局会话上下文，避免污染其他节点）；每轮开始前双方均可读 `round:{n-1}` 的对侧输出，**不可读**本轮对侧输出（保证交替）。
- **R-5（CHK005 相似度算法）**：终止条件③使用 `services/chat-api/app/self_evolution/similarity.py` 的 **Jaccard token 相似度**（`jaccard_similarity`，token 化按空白切分并小写），阈值默认 **0.9**、可配 `similarity_threshold`；"连续两轮"= 第 n 轮与第 n-1 轮的**同侧**输出相似度均 ≥ 阈值（pro 与 con 各自判定，均满足才终止）。
- **R-6（CHK006 取消语义）**：`first_success` 命中后，未完成候选**软取消**——已发出的执行不强制中断（避免中断副作用与计费歧义），但结果**被丢弃**、不进入 Trace 的"采用"分支，仅以 `status="discarded"` 记录；`max_concurrency` 队列中尚未启动的候选直接**不启动**。
- **R-7（CHK007 无 arbiter 的收敛）**：`arbiter` 为**可选**；未声明时收敛结论 = `{"conclusion": <最后一轮 pro 输出>, "confidence": <相似度或 1.0-相似度？否>}`——口径定为 `confidence = None`（不伪造置信度），Trace 标 `arbiter="absent"`，需要置信度的下游必须自行判空。**若声明了 `arbiter` 则该节点必须存在**（FR-007 fail-closed）。
- **R-8（CHK008 钳制事件）**：事件名 `debate.rounds_clamped`，字段 `{requested, applied, min:1, max:10}`，写入该 debate 节点的 Trace 事件流（与 `item.*` 同构）。
- **R-9（CHK009 Trace 结构）**：父节点产出 `item.started`/`item.completed`；候选/轮次的明细放在 **`payload.candidates` / `payload.rounds` 数组**（**不**额外派生 `item.*` 子事件），避免污染 001 审计流的节点计数口径；择优依据放 `payload.selection = {strategy, chosen, fallback_reason}`。
- **R-10（CHK010 contracts 存在性）**：`specs/010-dag-orchestration-engine/` 下**无 `contracts/` 目录**，010 的契约描述落在 `quickstart.md:69`（`Modes: sequential / supervisor / hybrid / graph (VALID_MODES)`）。本特性的同步动作改为：① 新建 `specs/010-dag-orchestration-engine/contracts/orchestration.md` 记录六模式 YAML 形态；② 更新 `quickstart.md:69` 为六模式。010 目录名以实际 `010-dag-orchestration-engine` 为准（spec 原文 `010-dag-orchestration` 为笔误）。
- **R-11（CHK011 模式校验时机）**：`VALID_MODES` 校验在**加载期**（`loader.py` 构造 `OrchestrationDefinition` 时）执行；执行期遇到未知 mode → `OrchestrationLoadError` 同口径 fail-closed，不做静默回退 graph（只有**未声明** mode 才回退 `graph`，见 `loader.py:274`）。
- **R-12（CHK012 fair_selection 复用粒度）**：**只借鉴思想，不调用函数**。`services/chat-api/app/enterprise_capabilities/evidence/foundation/fair_selection.py::round_robin_take(groups, *, limit)` 是"跨源组轮流取项避免早期源垄断容量"，用于证据检索配额，**与候选实例择优（多选一）语义不同**；`round_robin` 模式的候选调度按其自身语义实现（选一的策略执行器），不 import 该模块。
- **R-13（CHK013 调用点清单）**：现有调用点以实际文件为准——`services/chat-api/app/enterprise_capabilities/research/competitor_deep_dive.py`（经 `run_graph`/`run_hybrid` 调用）、`services/chat-api/app/orchestration/engine.py::run_orchestration`（若有）。实现时以 `grep -rn "run_graph\|run_sequential\|run_hybrid" services/` 为准枚举，迁移后由既有 `tests/orchestration/` 全量回归（当前 91 passed）证明行为不变。
- **R-14（CHK014 round_robin 失败边界）**：全部候选失败 → 节点整体失败（`failed`，聚合各候选错误到 `payload.errors`）；部分成功 → 按 R-2 择优；`majority` 平票按 R-3 取最先完成；`highest_score` 下有分候选全失败而无分候选成功 → 采用无分候选（`fallback_reason="scored_all_failed"`）。
- **R-15（CHK015 debate 异常边界）**：任一方失败 → 立即终止 debate，节点 `failed`，已产生轮次写 `payload.rounds` 保留；`arbiter` 执行失败 → 节点 `failed`（fail-closed，**不**回退到最后一方输出）；`max_rounds` 计时以**轮次计数**为准，排队等待不计入轮次。
- **R-16（CHK016 graph 子节点继承）**：新模式节点作为 graph 子节点时，`retry`/`timeout`/`conditions` **由子节点自身配置决定**（缺省继承父图默认值）；Trace 以该子节点为 `item_id` 产出**一层** `item.*`，其内部候选/轮次明细按 R-9 收在 `payload`，不产 nested item 层级。

- **R-17（round_robin 候选形态，实现期补）**：文档级 `round_robin` 把**每个 graph 节点视为同一逻辑任务的一个候选**（label = 节点 id），按文档 `max_concurrency`（缺省 4）并发，策略取 `header.select`（缺省 `highest_score`）。节点级 `round_robin` 用 `payload.instances` 声明候选，**只允许**覆盖 `model` / `temperature` / `prompt` / `label`；出现 `retry` / `conditions` / `condition` / `depends_on` / `mode` 一律加载期 fail-closed（`RoundRobinError` → `OrchestrationLoadError`）。`instances` 为空或缺失 = 单候选（label 缺省 `default`）。
- **R-18（debate 角色解析，实现期补）**：文档级 `debate` 按节点 `role`（`pro` / `con` / `arbiter`）解析；header 声明 `arbiter` 时必须存在 `role=arbiter` 节点，否则加载期 fail-closed。节点级 `debate` 从 `payload.pro` / `payload.con` / `payload.arbiter` 取节点 id；指向不存在的节点加载期 fail-closed（FR-007）。双方通过 `context["debate"] = {round, side, opponent_previous}` 读对方**上一轮**输出，`pro`/`con` 键按 `debate:{oid}:{nid}:round:{n}:{side}` 存入局部字典，不污染全局 context（R-4）。
- **R-19（分发入口，实现期补）**：新增 `dispatch.execute_orchestration(loaded, runner, *, context=None, engine=None, sequential_ids=None, parallel_ids=None, supervisor_id=None)` 为统一分发入口（FR-012）；`graph` / `sequential` 委托 `DagEngine`（传 `engine` 复用 010 调用方的引擎，行为不变）；`supervisor` / `hybrid` 的 grouping 由调用方显式传入（当前无生产调用点，R-13）。`dispatch.wrap_node_runner` 使新模式可作为 graph 子节点。`competitor_deep_dive.py` 已迁移到 `execute_orchestration`（T018），既有 `tests/orchestration/` 全量回归通过。
- **R-20（返回形状与事件，实现期补）**：文档级 `round_robin` 返回 `(SelectionResult, context)`（写入 `context[{orchestration_id}] = chosen.output`），文档级 `debate` 返回 `DebateResult`；节点级 `wrap_node_runner` 的 round_robin 返回 `chosen.output`（原始 dict，非文本）、debate 返回 `result.as_payload()`。择优依据收在 `payload.selection = {strategy, chosen, fallback_reason}`，明细收在 `payload.candidates` / `payload.rounds`（R-9）。`max_rounds` 越界钳制 1..10 并记 `clamped=True`。

## Non-Goals

- 不做可视化编排画布（整合方案 §4.8 另立）——本特性只做引擎与 YAML 契约。
- 不新建实例注册中心 / 模型路由（实例来源即 YAML 声明，YAGNI）。
- 不内置 LLM 评审器或语义相似度模型（择优/收敛均为可配置的确定性口径 + 显式回退）。
- 不做辩论 prompt 库与预设角色模板（由编排 YAML 承载）。
- 不改既有四模式的任何语义与代码路径。
- 不做跨实例/分布式辩论协调（单实例内，延续 010"不实现跨实例编排协调"）。
- 不做新模式的结果缓存/去重执行（同输入复用）——留后续。
