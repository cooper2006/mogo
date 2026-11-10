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

- **OQ-1**: 验收判定的结构化形态（领导 LLM 输出 JSON schema：verdict/opinion/target_member，解析失败 fail-closed 还是重试）。
- **OQ-2**: 重指派次数上限默认值与失败阈值的关系（supervisor 现阈值 1.0）。
- **OQ-3**: 接管触发条件的表达（仅验收分歧？达上限前自动触发？人工主动触发？）。
- **OQ-4**: 黑板尺寸上限与运行快照的尺寸约束（050 checkpoint 大上下文口径联动）。

## 跨特性关系（被依赖方视角，双向声明）

- **与 010/044**：引擎直接扩展，`VALID_MODES` 七模式；044 的 dispatch/事件/子节点口径全部沿用；契约联合刷新。
- **与 050（本批次）**：**硬依赖**——运行持久化、恢复、审批接管全部消费 050；050 未落地不得 implement。
- **与 051（本批次）**：软依赖——成员 employee_id 在 051 落地时生效，未落地忽略记事件（FR-010）。
- **与 046/021**：项目级持久黑板为二期，届时复用 project 上下文与 `mogo://` 寻址；首期不落项目。
- **与 001/007**：门禁与韧性不变，成员执行 = 原子节点，无治理旁路。

## Non-Goals

- 不做竞标机制（二期）。
- 不做项目级持久黑板（首期运行内）。
- 不做领导/成员 prompt 库与预设团队模板（053 的事）。
- 不做跨实例分布式团队协调（050 单活租约口径）。
- 不改既有六模式语义；不拷贝 StaffDeck（AGPL-3.0）代码。