# Feature Specification: 团队协作模式（team：拆解指派 + 黑板共享 + 验收循环 + 人工接管）

**Feature Branch**: `052-team-collaboration-mode`

**Created**: 2026-11-09

**Status**: Draft

**Input**: 整合方案 §4.3：010 引擎新增 `team` 模式——领导节点拆解任务 → 指派成员（首期）→ 成员异步执行 → 共享材料写入团队黑板 → 领导验收（不合格退回重做，轮次上限）→ 任意环节可人工接管。复用 supervisor 拆解/汇总、050 运行持久化与审批节点、046 project 共享上下文。

> **设计来源**：本规约来自 `docs/MOGO-StaffDeck整合方案.md` §4.3（2026-11-09 代码级勘察结论）。StaffDeck 为 AGPL-3.0，**仅借鉴产品设计，不拷贝代码**。
>
> **性质说明**：**已实现（2026-11-09，tasks 22/22）**——`team` 第七模式：拆解/分派 + 黑板 + 验收循环 + 失败传播 + 接管（T015，`_should_take_over` 人工主动触发 + 决策覆盖领导判定）落地；OQ-1~OQ-4 已按 spec 已定默认值消解并回填。
>
> **背景事实（代码级核实，2026-11-09）**：编排六模式 `services/chat-api/app/orchestration/graph.py:13`（`VALID_MODES`）；`supervisor.py`（分派 + 聚合 + 失败阈值传播，`DEFAULT_CHILD_FAILURE_THRESHOLD = 1.0`）；044 已落地 `round_robin.py` / `debate.py` / `dispatch.py:66`（统一分发入口 `execute_orchestration`）；节点级 mode 形状校验先例 `loader.py:282-309`；046 统一后的 `projects` 集合与项目共享上下文（021 `mogo://` 可寻址）；050（本批次，未落地）提供 `orchestration_runs` 运行持久化与 `human_approval` 节点。

## 定位（一句话）

010 引擎新增第七种模式 `team`：以"领导-成员"组织形态执行任务——领导拆解并指派、成员异步执行、材料进团队黑板、领导验收可退回重做（有轮次上限）、任意环节可人工接管；**首期只做指派，竞标为二期澄清项**；既有六模式语义零改动。

## 已定决策（2026-11-09，spec 撰写时拍板）

| # | 决策点 | 结论 | 落点 |
| --- | --- | --- | --- |
| 1 | 任务分配方式 | **首期 = 领导指派**（领导节点产出任务分派表：成员 × 子任务）；**竞标（成员能力自报 + 报价择优）为二期**，不在本 spec 范围（YAGNI，整合方案已声明） | `team.py` |
| 2 | 成员形态 | 成员 = 图中的普通节点（runner 注入执行体）；成员可声明 `employee_id` 引用 051 员工档案（051 未落地时该键忽略并记事件，不阻塞） | YAML `members` |
| 3 | 团队黑板 | 黑板 = 运行级共享材料区（键值 + 作者 + 版本），存于运行快照（050 `orchestration_runs`）；**项目级持久黑板复用 046 project 上下文为二期**，首期运行内黑板不落项目 | `team.py` blackboard |
| 4 | 验收循环 | 领导验收节点对成员产出判定 `accept` / `rework`（附意见）；rework 退回对应成员重做；**验收轮次上限默认 3（可配 1..5，越界钳制记事件）**；达上限仍不合格 → 团队运行失败（fail-closed，不静默接受） | `team.py` 验收循环 |
| 5 | 人工接管 | 复用 050 `human_approval` 节点语义：团队运行可声明接管点（验收分歧/达上限前），人工决策覆盖领导判定；接管决策全审计 | 050 消费 |
| 6 | 异步执行 | 成员执行经 050 运行持久化驱动（checkpoint + 恢复），单成员失败不拖垮团队（沿用 graph 失败传播语义 + 领导可重指派，重指派次数有上限） | 050 消费 |
| 7 | 领导节点形态 | 领导 = LLM 节点（拆解/验收经 runner 执行，prompt 由 YAML 承载）；引擎不内置"领导 prompt 库"（与 044 不内置辩论 prompt 同口径） | YAML |

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 领导拆解指派 + 成员执行 + 黑板共享 (Priority: P1) 🎯 MVP

编排作者定义 `mode: team`：领导节点把任务拆解为子任务并指派给成员节点；成员并行/异步执行，产出与中间材料写入团队黑板（带作者与版本）；领导可读取黑板全部材料。

**Why this priority**: 这是团队模式的最小完整形态（无验收循环也可交付"分工协作"价值）；复用 supervisor 拆解语义与 050 持久化，边际成本最低。

**Independent Test**: 定义 team（领导 + 2 成员，mock runner），领导产出分派表 → 断言两成员各执行自己的子任务、黑板含两份带作者材料、领导输出引用黑板键。

**Acceptance Scenarios**:

1. **Given** `mode: team` 且领导/成员节点就位，**When** 执行，**Then** 领导先产出分派表（成员 × 子任务），成员按分派执行。
2. **Given** 成员执行完成，**When** 产出写入，**Then** 黑板条目含作者（成员节点 ID）/版本/内容，其他成员与领导可读。
3. **Given** 单成员失败，**When** 失败传播，**Then** 其余成员不受影响；领导可重指派（次数上限内）或按失败阈值判定团队失败。
4. **Given** 成员声明 `employee_id` 且 051 已落地，**When** 执行，**Then** 按员工档案注入边界（051 口径）；051 未落地时忽略并记事件。

---

### User Story 2 - 领导验收与退回重做循环 (Priority: P1)

成员产出提交后领导验收：合格则团队完成；不合格附意见退回对应成员重做，重做产出再次验收；轮次上限内收敛，达上限仍不合格则团队运行失败。

**Why this priority**: 验收退回是 StaffDeck 团队形态区别于普通 supervisor 聚合的核心——质量闭环；轮次上限是引擎级正确性（不死循环），必须同批交付。

**Independent Test**: mock 领导首轮判 rework、次轮判 accept → 断言成员执行两次、黑板有两个版本、验收意见可查；mock 领导持续 rework → 断言达上限后团队失败（不无限循环）。

**Acceptance Scenarios**:

1. **Given** 成员产出提交，**When** 领导判 `accept`，**Then** 团队运行完成，最终产出 = 验收通过的成员材料合成。
2. **Given** 领导判 `rework`（附意见），**When** 退回，**Then** 对应成员读取意见重做，黑板追加新版本（旧版本保留）。
3. **Given** 验收轮次达上限仍不合格，**When** 循环判定，**Then** 团队运行 `failed`（fail-closed），审计记录各轮验收意见。
4. **Given** 轮次配置越界（0 或 >5），**When** 加载，**Then** 钳制到 1..5 并记事件（044 同风格）。

---

### User Story 3 - 人工接管 (Priority: P2)

团队运行在验收分歧或达上限前可触发人工接管：经 050 审批节点挂起，人工决策（接受当前产出 / 指定重做 / 终止）覆盖领导判定，决策全审计。

**Why this priority**: 接管是"效果靠不住的地方靠审批兜底"的团队版；依赖 050 审批节点，故列 P2 但同批设计。

**Independent Test**: 配置接管点，mock 领导判 rework 触发接管 → 断言运行挂起（050 语义）、人工判"接受"后团队完成且审计含接管决策。

**Acceptance Scenarios**:

1. **Given** 团队声明接管点，**When** 触发条件命中，**Then** 运行挂起等待人工（050 `awaiting_approval` 语义）。
2. **Given** 人工接管决策，**When** 提交，**Then** 覆盖领导判定继续执行，决策人/理由进审计。

---

### User Story 4 - 契约与文档同步（七模式口径） (Priority: P2)

010 `contracts/orchestration.md` 六模式表扩展为七模式，补 team 的 YAML 形态（members/验收轮次/接管点/黑板语义）；既有六模式测试零修改全绿。

**Why this priority**: 契约即真相（044 先例）；低于引擎本体但同批交付。

**Independent Test**: 契约 team 示例 YAML 可被 loader 加载执行；`VALID_MODES` 与契约表一致。

**Acceptance Scenarios**:

1. **Given** 契约文档更新，**When** 核对模式表，**Then** 七模式与 `VALID_MODES` 一致。
2. **Given** 既有六模式测试，**When** 全量运行，**Then** 零修改全绿。

---

### Edge Cases

- **领导节点失败**：团队运行失败（fail-closed），不进入成员执行。
- **分派表引用不存在成员**：加载期/执行期 fail-closed（与 044 arbiter 校验同风格）。
- **黑板键冲突**：同成员同键追加版本；不同成员同键视为命名空间隔离（键含作者前缀），不覆盖。
- **重指派次数达上限**：按失败阈值判定团队失败，不无限重指派。
- **接管与验收竞态**：接管挂起期间验收循环冻结（运行级状态以 050 为准）。
- **team 作为 graph 子节点**：对外表现为一次原子成功/失败（044 R-16 同口径），内部轮次/黑板明细收 payload。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 编排引擎 MUST 支持第七模式 `team`（`VALID_MODES` 扩展）；未声明 mode 仍默认 graph（loader 既有语义不变）。
- **FR-002**: team MUST 实现领导拆解指派：领导节点产出分派表（成员 × 子任务），成员按分派执行；分派表引用不存在成员 MUST fail-closed。
- **FR-003**: team MUST 提供运行级黑板：条目含作者/版本/内容，成员与领导可读；旧版本保留不覆盖。
- **FR-004**: team MUST 实现验收循环：accept 完成 / rework 附意见退回重做；轮次上限默认 3（可配 1..5，越界钳制记事件）；达上限不合格 MUST 团队失败，MUST NOT 无限循环。
- **FR-005**: 成员异步执行 MUST 经 050 运行持久化（checkpoint + 恢复）；单成员失败不拖垮其余成员；重指派次数有上限。
- **FR-006**: team MUST 支持人工接管点（复用 050 `human_approval` 语义）；接管决策覆盖领导判定并全审计。
- **FR-007**: team MUST 完整继承 010 设施（节点重试/条件跳过/Trace 事件/失败阻塞）；事件与既有 `item.*` 同构，轮次/黑板明细收 payload（044 R-9 口径）。
- **FR-008**: team 节点 MUST 可作为 graph 子节点（原子成功/失败，044 R-16 口径）。
- **FR-009**: 既有六模式执行路径与语义 MUST 零改动（既有测试零修改全绿）。
- **FR-010**: 成员 `employee_id` 引用 MUST 在 051 落地时按档案注入、未落地时忽略并记事件（不阻塞本特性交付）。
- **FR-011**: 010 `contracts/orchestration.md` MUST 同步扩展为七模式契约（team YAML 形态示例可加载执行）。

### Key Entities

- **TeamPlan**: 领导产出的分派表（成员 × 子任务 × 验收标准）。
- **BlackboardEntry**: 黑板条目（键/作者/版本/内容/时刻）。
- **ReviewVerdict**: 验收判定（accept/rework + 意见 + 轮次）。
- **TeamRunState**: 团队运行状态（轮次/重指派计数/接管状态），存于 050 运行快照。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: team 工作流 E2E：拆解 → 指派 → 双成员执行 → 黑板共享 → 验收通过完成；契约示例即可执行。
- **SC-002**: 验收循环有保证：任何配置下轮数 ≤ 上限；rework 意见传递到重做成员；达上限 fail-closed。
- **SC-003**: 单成员失败不拖垮团队；重启后团队运行可恢复（050 语义）。
- **SC-004**: 既有六模式测试零修改全绿；team 子节点原子性不变。
- **SC-005**: 接管决策全审计可还原（决策人/理由/覆盖前后判定）。

## Assumptions

- 领导/成员的 prompt 由 YAML 承载，引擎不内置 prompt 库（044 同口径）。
- 黑板首期运行内（不落项目级持久存储）；项目级黑板为二期。
- 竞标机制不在本 spec（二期澄清项）。
- 成员执行体经 runner 注入（transport-agnostic），模型调用过 007 韧性 + 001 门禁。

## 待澄清（clarify 门禁）

> **OQ 决议（2026-11-09 实现批次，按 spec 已定默认值消解并记录）**：
>
> - **OQ-1**: 领导判定 JSON `{verdict: accept|rework, opinion, target_member}`；
>   解析失败 **fail-closed**（不静默回退 accept，治理旁路），`team.py:ReviewVerdict.from_output`。
> - **OQ-2**: 重指派上限默认 **3**（钳制 1..10，`clamp_reassign`）；失败阈值沿用
>   supervisor 语义——单成员失败不拖垮团队，达重指派上限团队失败。
> - **OQ-3**: 接管触发条件首期 = **人工主动触发**（`takeover:` 声明接管点，命中记
>   `team.takeover` 事件）；**自动触发（验收分歧/达上限前）为二期**，与 050 跨模式
>   挂起（`RunDriver.start` 现仅 graph）同批后续——052 P1 MVP 不阻塞。
> - **OQ-4**: 黑板首期**运行内**（存 050 `orchestration_runs` 快照），尺寸上限
>   与 050 checkpoint 大上下文口径联动；项目级持久黑板为二期（决策 #3）。

- **OQ-1**（已消解，见「判定口径补充」R-2）：验收判定的结构化形态——领导 LLM 输出 JSON schema：verdict/opinion/target_member；解析失败 **fail-closed、首期不重试**（不静默回退 accept，避免治理旁路），定值以 R-2 为准。
- **OQ-2**: 重指派次数上限默认值与失败阈值的关系（supervisor 现阈值 1.0）。
- **OQ-3**: 接管触发条件的表达（仅验收分歧？达上限前自动触发？人工主动触发？）。
- **OQ-4**: 黑板尺寸上限与运行快照的尺寸约束（050 checkpoint 大上下文口径联动）。

## 跨特性关系（被依赖方视角，双向声明）

- **与 010/044**：引擎直接扩展，`VALID_MODES` 七模式；044 的 dispatch/事件/子节点口径全部沿用；契约联合刷新。
- **与 050（本批次）**：**硬依赖**——运行持久化、恢复、审批接管全部消费 050；050 未落地不得 implement。
- **与 051（本批次）**：软依赖——成员 employee_id 在 051 落地时生效，未落地忽略记事件（FR-010）。
- **与 046/021**：项目级持久黑板为二期，届时复用 project 上下文与 `mogo://` 寻址；首期不落项目。
- **与 001/007**：门禁与韧性不变，成员执行 = 原子节点，无治理旁路。

## 判定口径补充（2026-11-10，`/speckit-checklist` 回填）

以下补齐 checklist 识别出的需求缺口，作为实现与验收的一等口径（与 FR 同效力）。

- **R-1（CHK001 TeamPlan 分派表 schema）**：领导拆解输出 MUST 为 JSON 对象 `{assignments: {<member_id>: <subtask>}}`（与 010 `contracts/orchestration.md` §7 一致；`subtask` 为字符串或含 `description`/`acceptance`/`depends_on` 的对象），可附 `plan_id`；字段结构固定为「成员 → 子任务描述 / 验收标准 / 依赖关系（可选）」。分派表引用不存在成员 MUST fail-closed（FR-002）；拆解输出非法 JSON / 缺 `assignments` / 空分派表 MUST fail-closed 并记 `team.plan_invalid` 事件，MUST NOT 静默回退为「全部成员均分」或空分派。拆解输出与 R-2 验收判定同为领导 LLM 结构化输出，解析口径统一（fail-closed）。
- **R-2（CHK002 验收判定 schema / 解析失败 / 轮次上限与钳制）**：领导验收输出 MUST 为 JSON `{verdict: "accept"|"rework", opinion: str, target_member: str}`（OQ-1 决议 / `ReviewVerdict`）；解析失败（非法 JSON / 枚举越界 / 缺 `verdict`）MUST **fail-closed**：不回退 `accept`、不静默吞掉，首期**不重试**（消除「待澄清 OQ-1」与 `tasks.md`「fail-closed 或有限重试、重试次数未定」的残留歧义，以本条为准）。验收轮次上限默认 **3**、可配 **1..5**，越界钳制到边界并记事件（决策 #4 / FR-004 / US2-4）；达上限仍 `rework` → 团队运行 `failed`（fail-closed，不静默接受、不等其余成员）。轮次计数以「提交验收」为一步，排队 / 成员执行不计入。
- **R-3（CHK003 黑板尺寸 / 生命周期 / 键命名空间 / 超限）**：黑板条目键 MUST 为 `{author}:{key}`（作者节点 ID 前缀命名空间隔离，跨成员同键不覆盖；同成员同键追加版本、旧版本保留，FR-003 / Edge Cases）。首期黑板**运行内**：存于 050 `orchestration_runs` 共享上下文，随运行终态按 050 保留期（终态快照 180 天）清理，项目级持久黑板二期（OQ-4 决议 / 决策 #3）。尺寸约束：单条目默认上限 **64 KiB**、运行级黑板总量默认上限 **1 MiB**（可配，与 050 checkpoint 大上下文口径联动）；超限 MUST fail-closed：拒绝该次写入并记 `team.blackboard_overflow` 事件，MUST NOT 静默截断或丢弃旧版本。
- **R-4（CHK004 接管触发条件 / 硬软依赖首期口径）**：首期（P1 MVP）接管为 **P2 预留的软依赖**：复用 050 `human_approval` 的票据机制（`ApprovalRuntime.issue`/`validate_and_consume`）/ 决策回调 / 全审计语义（经 `approval_hook` 在成员 / 验收环节内联取人工决策），**不强制**进入 050 `awaiting_approval` 跨进程挂起——因 050 首期审批挂起仅 `graph` 模式支持（010 `contracts/orchestration.md` §6：其它模式声明审批节点加载期 fail-closed），而 `team` 是文档级第七模式（§7），真挂起需 050 `RunDriver` 跨模式挂起能力，留二期同批交付（与 OQ-3 决议「自动触发 / 跨模式挂起二期、P1 不阻塞」一致，消解 US3/FR-006「经 050 审批节点挂起」与 OQ-3 决议的口径张力）。接管触发条件首期 **仅人工主动触发**：YAML `takeover: {approver: <user_id>, points: [before_review | before_max_rounds]}` 声明接管点与审批人（`points` 为「允许人工介入的检查点」，**非系统自动触发条件**），命中记 `team.takeover` 事件；**自动触发（验收分歧 / 达上限前由系统自动挂起）为二期**。跨进程真挂起（`awaiting_approval` + checkpoint 恢复）留二期；二期前 US3 的「运行挂起」验收断言以「内联决策 + 全审计」软依赖口径为准，不改变本特性勾选判断。
- **R-5（CHK006 重指派语义 / 上限 / 与轮次独立 / 失败阈值）**：重指派 = 成员节点**执行失败**时对该子任务重新指派（首期为**同一成员重跑**，换成员择优属竞标二期，决策 #1）；**不包含**验收 `rework`（rework 是质量退回，走 R-2 轮次计数；重指派是失败恢复，走独立计数器——两者 MUST NOT 合并为单一计数器，`tasks.md` Notes）。上限 `max_reassign` 默认 **3**、钳制 **1..10**（`clamp_reassign`，OQ-2 决议 / 契约 §7）；达上限仍失败 → 按失败阈值判定团队 `failed`（fail-closed）。失败传播沿用 supervisor `DEFAULT_CHILD_FAILURE_THRESHOLD = 1.0` 语义：单成员失败不拖垮其余成员，领导可重指派（上限内）或判定团队失败。
- **R-6（CHK007 rework 意见传递形态 / 黑板历史可读）**：`rework` 意见 MUST 经成员 runner 的输入上下文键 `context["team"]["review_opinion"]`（含 `opinion` / `round` / `verdict`）传入重做成员，`target_member` 指定接收者（R-2 schema）；成员 MUST 可读黑板**全部历史版本**（FR-003 旧版本保留），经 `context["team"]["blackboard"]` 按 R-3 键命名空间读取；意见与历史版本 MUST NOT 混入成员自身产出键，避免与新版黑板条目混淆。
- **R-7（CHK008 最终产出合成 / 失败语义）**：团队完成 = **全部成员 `accept`**（R-12）后，由**引擎确定性拼接**（非领导 LLM、非额外模型调用，YAGNI / 044「引擎不内置评审器」同口径）按 TeamPlan 分派顺序拼接各成员验收通过的**最新黑板版本**，写入运行上下文 `context[<orchestration_id>]`。合成 MUST NOT 引入独立「成功」分支：其前置条件（全部 accept + 黑板条目可读）在验收阶段已保证；若拼接期黑板条目缺失 / 不可读，按 fail-closed 记 `team.synthesis_failed` 并使团队 `failed`，MUST NOT 输出半成品。
- **R-8（CHK009 接管决策选项集 / 结构化 / 重做与轮次上限）**：人工接管决策 MUST 为枚举 `accept | rework | terminate`（对应 US3「接受当前产出 / 指定重做 / 终止」，为 team 对 050 approve/reject 的三态扩展：`accept`≈批准续跑、`rework`≈指定重做、`terminate`≈驳回终止），结构化形态 `{decision: "accept"|"rework"|"terminate", decider: str, reason: str, target_member?: str}`（050 审计口径补 `decider`/`reason`）；决策覆盖领导判定并**全审计**（决策人 / 理由 / 覆盖前后判定，SC-005 / FR-006）。`rework` 决策 MUST 占用一轮验收轮次且 MUST NOT 超 R-2 轮次上限（轮次上限是引擎级死循环防护，人工决策同样受约束）；`terminate` → 团队 `failed`（fail-closed）；决策解析失败 / 非法枚举 → fail-closed（沿用 R-2）。
- **R-9（CHK010 050 快照结构兼容 / team 命名空间契约）**：TeamRunState / 黑板 / 验收记录 MUST 内嵌 050 `orchestration_runs` 的自由形态「共享上下文」字典（050 `OrchestrationRun` Key Entity 已含该字段），统一置于 `context["team"]` 命名空间下（键前缀 `team:`）；**不要求 050 新增顶层字段、不改 050 快照 schema**，故结构兼容成立，澄清 checklist「050 快照 schema 未冻结、假设需 050 设计期双向确认」的歧义。双向确认口径：052 只读写 `team` 命名空间内字段，对 050 其余字段**只增不改**（仿 032 R-11）；若 050 后续收紧 schema，由 052 侧适配器适配，MUST NOT 反向要求 050 为 team 改结构。快照尺寸受 R-3 上限与 050 checkpoint 大上下文口径约束。
- **R-10（CHK011 事件命名 / payload 结构与 044 R-9 同构）**：team 父节点（或作为 graph 子节点的 team 节点）产出**一层** `item.started`/`item.completed`/`item.failed`；轮次 / 验收 / 黑板 / 接管 / 重指派明细 MUST 收在 `payload.team = {rounds, verdicts, blackboard, takeover, reassign}`，MUST NOT 派生嵌套 `item.*` 子事件（044 R-9 口径，避免污染 001 审计流节点计数）。team 自有事件以 `team.*` 前缀（`team.plan_invalid` / `team.takeover` / `team.blackboard_overflow` / `team.synthesis_failed` / `team.verdict_invalid` / `team.employee_ignored`）经既有 `dag.*` 审计出口进 001 审计流，与既有 `item.*` 同构；明细口径与 044 `payload.candidates`/`payload.rounds` 同构（数组 + 状态，不另立计数口径）。
- **R-11（CHK013 employee_id 注入点与 051 双向声明）**：成员 `employee_id` 注入 MUST 与 051 口径对齐——051 `EmployeeProfile` 在**会话创建时**物化为档案注入快照（051 FR-003 / 决策 #3 / Key Entities）；team 成员是编排节点、非 agent 会话，故注入点定为**成员节点执行前**：按 `employee_id` 调 051 档案注入逻辑物化边界 / 知识库 / 记忆 / 模型配置进该成员 runner 上下文（与 051「档案注入快照、在途不受档案变更影响」同口径），MUST NOT 要求 051 为 team 引入会话级注入。051 未落地时忽略该键并记 `team.employee_ignored` 事件、不阻塞（FR-010 / US1-4）；档案引用失效按 051 OQ-2 **fail-closed**（不降级跳过）。
- **R-12（CHK014 混合 accept/rework / 逐成员判定 / 团队终态）**：验收 MUST 按**成员逐个判定**（`ReviewVerdict.target_member` 指向单一成员），每成员独立轮次计数；MUST NOT 整批一次判定。团队完成当且仅当**全部成员各自 `accept`**（R-7 合成前置）；部分 accept / 部分 rework 时，仅 rework 成员重做、其余成员产出冻结等待。任一成员达其轮次上限 → **整个团队 `failed`**（fail-closed，不静默接受该成员、不等其余成员收敛，与「团队对外一次原子成功 / 失败」044 R-16 口径一致）；审计记录各成员各轮验收意见。
- **R-13（CHK015 接管期间在途成员执行 / 044 R-6 软取消）**：接管挂起（首期软依赖，R-4）期间**验收循环冻结**（Edge Cases，运行级状态以 050 为准）；已启动但尚未完成的成员执行采用 **044 R-6 软取消**口径：不强制中断在途 runner（避免中断副作用与计费歧义），但**未启动**的成员直接不启动，在途成员结果在冻结期**暂不提交验收、不写新黑板版本**；人工决策（R-8）为 `accept`/`terminate` 后恢复或终止，`rework` 后按 R-6 重做。MUST NOT 在冻结期继续推进轮次计数。
- **R-14（CHK016 rework 指向未产出成员 / fail-closed）**：`target_member` 指向不存在成员、或该成员在当前轮**无黑板产出**（未执行 / 已终止 / 分派表外成员）时，MUST **fail-closed**：记 `team.verdict_invalid` 事件并使团队 `failed`，MUST NOT 忽略该判定、MUST NOT 回退 `accept`、MUST NOT 把意见转交其它成员（与 R-1 分派非法、R-2 解析失败同口径）。
- **R-15（CHK017 文档级 / 节点级 team 成员解析 / 044 R-17、R-18 口径）**：文档级 `team`（整图即团队）：领导由 `leader:` 指定（缺省第一个节点），成员 = `members:` 子集（缺省全部非领导节点，契约 §7）；节点级 `team`（作为 graph 子节点，`dispatch.wrap_node_runner`）：成员由该节点 `payload.members` / `payload.leader` 声明（044 R-17/R-18 节点级 `payload` 声明范式）。两种形态成员引用不存在节点 MUST 加载期 **fail-closed**（FR-002 / 044 arbiter 同风格）；节点级 `payload.members` 为空 = 单成员（缺省自身）。`mode` 解析沿用 044「节点级优先于文档级」（`registry.py` 既有语义）；文档级与节点级**成员解析口径**本条统一，避免实现期两处漂移。

## Non-Goals

- 不做竞标机制（二期）。
- 不做项目级持久黑板（首期运行内）。
- 不做领导/成员 prompt 库与预设团队模板（053 的事）。
- 不做跨实例分布式团队协调（050 单活租约口径）。
- 不改既有六模式语义；不拷贝 StaffDeck（AGPL-3.0）代码。