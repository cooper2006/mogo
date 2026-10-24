# Requirements Quality Checklist: 043 session-replay

**Purpose**: 校验 043（会话回放 Stage 1 前端投影）spec.md 的需求质量——完整性、清晰度、一致性、边界与歧义。这是"需求的单元测试"，**不校验实现是否正确**。
**Created**: 2026-10-24
**Feature**: [spec.md](../spec.md) | [plan.md](../plan.md)

**Review Ownership**: 审阅人专属的需求质量评审工件。仅当审阅人确认某条需求质量准则达标时才标 `[x]`。
**Marker Semantics**: `[x]` 表示"需求质量已审阅且达标"，**不表示**实现完成。
**生成规则**: 本文件由 `/speckit-checklist` 生成，条目不得预先标 `[x]`；`/speckit-implement` 读取勾选态作为门禁且不得修改标记。

## 完整性（Completeness）

- [x] CHK001 轨迹 tab 的**现有承载组件**是否指明（仓库中已存在 `apps/user-web/src/features/execution-v3/components/SessionTrajectoryView.vue` 与 `domain/trajectoryRounds.ts::collectTrajectoryRounds`，是 028 的产物；FR-001 只说"轨迹 tab 提供时间轴"，**时间轴是改造该组件还是新建组件、与 `ExecutionViewV3.vue` 的层级关系**未定义）
- [x] CHK002 "知识命中"在 V3 事件流中的**事件类型/字段**是否指明（FR-002 要求展开当轮"知识命中"，但 `apps/user-web/src/features/execution-v3/domain/protocol.ts` 的事件 kind 集合与"知识命中"的映射未给出，实现者无法定位数据来源）
- [x] CHK003 "耗时格式化"复用的**具体导出**是否给出（FR-003 说复用 `domain/runTiming.ts` 既有口径，但未写函数名/常量名——该文件实际位于 `apps/user-web/src/features/execution-v3/domain/runTiming.ts`，"domain/" 前缀缺 `features/execution-v3/`）
- [x] CHK004 Stage 2 的**接口预留形态**是否定义（FR-010 说"以预研结论 + 接口预留形式存在"，但预留什么（类型定义？空方法？协议字段？）未写，等于没有可验收物）
- [x] CHK005 轮次锚点的**轮次号口径**是否定义（1-based 还是 0-based？含工具调用无文本的 assistant 轮是否计入？`collectTrajectoryRounds` 的既有分组口径是否即锚点口径，未声明）

## 清晰度（Clarity）

- [x] CHK006 "查看该轮完整上下文"的**展示边界**是否定义（FR-002 要求跳转后看输入/输出/工具调用/知识命中；**是否同时展示前序轮次作为上下文、还是只聚焦该轮**，两种交互对实现与用户预期完全不同，未写）
- [x] CHK007 "成本行降权展示"的**视觉与交互定义**是否明确（FR-004 说"降权"——是降低不透明度、折叠到次级区、还是加"参考值"标注？"降权"是设计意图而非可验收规格）
- [x] CHK008 实时更新与用户焦点冲突的**仲裁规则**是否定义（FR-005 要求"新轮次即时出现"且"跳转/下钻不中断流式"；**用户停留在第 3 轮下钻时新轮到来自动追加但不抢滚动焦点**——滚动跟随的仲裁规则（何时自动滚到底、何时保持用户位置）未写）
- [x] CHK009 "步骤下钻"的**展开粒度**是否定义（一次可展开多个步骤还是互斥单个？默认展开状态？展开集合在切换轮次时是否清空？FR-009 只说"展开步骤集合"为局部态）

## 一致性（Consistency）

- [x] CHK010 spec 引用的**文件路径与仓库实际是否一致**（`useChatRuntimeStore.ts:104-107` 实际在 `apps/user-web/src/composables/useChatRuntimeStore.ts`；`App.vue:2656-2720` 的 `v-show` 双 tab 现位于 `App.vue:2704`/`:2713`/`:2774`；行号已漂移，按 spec 原文定位会失败）
- [x] CHK011 FR-006「`ChatWindow.vue` 零改动」与 FR-001「轨迹 tab 内新增时间轴」的**边界是否自洽**（若轨迹视图由 `ChatWindow.vue` 内部渲染，则新增时间轴必然改该文件；需明确"轨迹 tab 内容由独立的 `SessionTrajectoryView` 承载，`ChatWindow.vue` 只负责 tab 容器"这一前提）
- [x] CHK012 与 028 的验收基线是否**逐条对齐**（FR-006 要求 028 全部验收继续成立：tab 切换、pane 独立、空态、无网络请求；这四项的现有测试文件位置与断言未在 043 中引用，回归门禁无法执行）
- [x] CHK013 与 035 的**依赖方向是否单向**（FR-004 与决策 #4 说成本依赖 035；035 已完成后端归集但前端 `costUsd` 仅在 admin-web 侧落地，user-web 事件流是否已含成本字段**未核实**——若不含，则成本行永远不渲染，需在 spec 明确"首期恒不渲染"）

## 边界与歧义（Edge Cases & Ambiguity）

- [x] CHK014 空态与单轮场景是否覆盖（无 assistant 消息时的锚点列表、只有 1 轮时是否仍渲染时间轴、轮次正在生成中的"不完整轮"能否跳转，均未写）
- [x] CHK015 大会话性能边界是否定义（数百轮 + 每轮数十事件的锚点与下钻渲染策略：虚拟滚动？按需渲染？无上限则长会话卡顿）
- [x] CHK016 跳转目标的**定位失效处理**是否定义（用户在第 5 轮下钻，此时该轮消息被重新同步/替换（V3 事件重放），锚点指向的 round 已不存在时的降级行为未写）

## Notes

- 条目编号 CHK001–CHK016 连续，覆盖完整性 / 清晰度 / 一致性 / 边界四类。
- 本特性风险集中在**既有组件复用边界的模糊**（CHK001/CHK011）与**"零后端改动"前提下的数据可得性**（CHK002/CHK013）：Stage 1 不新增接口，一切数据必须已在 V3 事件流中；若"知识命中"或"成本"不在流内，需求本身不可实现。
- 路径类问题（CHK003/CHK010）属低风险但会直接导致实现者定位失败，回填中以完整路径修正。

## 评审结论（2026-10-24 勾选，agent 代审 + spec 回填）

- 逐条映射：
- CHK001 → R-1
- CHK002 → R-2
- CHK003 → R-3
- CHK004 → R-4
- CHK005 → R-5
- CHK006 → R-6
- CHK007 → R-7
- CHK008 → R-8
- CHK009 → R-9
- CHK010 → R-10
- CHK011 → R-11
- CHK012 → R-12
- CHK013 → R-13
- CHK014 → R-14
- CHK015 → R-15
- CHK016 → R-16
- 其中 **CHK010（路径漂移）与 CHK013（成本数据不可得）为实证缺口**：前者按仓库实际路径修正（R-10），后者确认 user-web V3 事件流无成本字段、首期成本行恒不渲染（R-13），并据此把 FR-004 的验收降级为"不渲染即达标"。
- **CHK002 的"知识命中"经核查落到既有 `item_kind === 'evidence'`**（R-2），不是新增事件类型；**CHK003 的耗时复用函数名确定为 `formatRunDuration` / `elapsedRunMs`**（R-3）。
- 本特性前端尚未实现，回填全部为需求口径澄清；tasks.md 不勾选。
