# Feature Specification: General-Purpose DAG Orchestration Engine

**Feature Branch**: `010-dag-orchestration-engine`

**Created**: 2026-07-08

**Status**: Draft

**Input**: 补齐规划文档清单 5（P1）"DAG 编排引擎"：四模式（sequential / supervisor / hybrid / graph）、DAG 拓扑排序 + 环检测、条件跳过（表达式求值）、节点级重试（指数退避）。通用化 MOVO 当前的"内容规划/研究模式"（`enterprise_capabilities/content/planning`），使其不再仅限内容场景。

## User Scenarios & Testing *(mandatory)*

用户故事按优先级排列，每个独立可交付、可测试。

### User Story 1 (P1) — 通用 DAG 图模式（graph）

用户可定义节点（任务）与有向边（依赖），编排引擎按 DAG 拓扑执行：无依赖的节点可并行，有依赖的节点在就绪后执行；环检测保证拓扑可解。

**Acceptance Scenarios:**
- 定义 A→B, A→C, B→D, C→D 的 DAG → 拓扑序执行，B/C 可并行，D 最后
- 定义含环（A→B→C→A）→ 环检测拒绝并指出环路径
- 节点失败 → 下游依赖节点阻塞（不执行）

### User Story 2 (P1) — 拓扑排序 + 环检测

编排引擎执行前做拓扑排序与环检测；环时报错并指明环路径，不进入执行。

**Acceptance Scenarios:**
- 无环 DAG → 拓扑序正常
- 有环 → 报错含环路径（如 A→B→C→A）
- 自环（A→A）→ 检测拒绝

### User Story 3 (P2) — 条件跳过（表达式求值）

节点可配置跳过条件表达式；执行到该节点时求值，为真则跳过（及其可选下游），记录跳过原因。

**Acceptance Scenarios:**
- 条件表达式为真 → 跳过节点，下游按依赖处理
- 条件表达式为假 → 正常执行
- 表达式语法错误 → 默认 fail_closed（该节点跳过 + 审计记录，不静默），可配置为"报错中断"

### User Story 4 (P2) — 节点级重试（指数退避）

节点执行失败可按配置指数退避重试，达上限则节点失败；与特性 007 LLM 网关重试解耦（本层是节点级，007 是模型调用级）。

**Acceptance Scenarios:**
- 节点失败 → 按退避重试至成功或上限
- 重试次数/退避可配置
- 节点最终失败 → 下游阻塞，事件记录

### User Story 5 (P2) — 其他编排模式（sequential / supervisor / hybrid）

- sequential：节点线性依次执行
- supervisor：一个监督节点协调子节点
- hybrid：监督 + 部分并行

**Acceptance Scenarios:**
- sequential → 节点顺序执行，前完成才启动后
- supervisor → 监督节点分派/聚合子节点
- hybrid → 监督协调 + 子节点可并行

### Notes / Assumptions
- 本特性补齐规划文档清单 5（P1 可靠性），属缺口新特性
- 现状：仓库无通用 DAG 引擎（grep 无 dag/topological/cyclic 命中）；现有"内容规划"是场景特化的（`content/planning`：ContentPlanBuilder + 语义/结构化/降级多路径构建），非通用编排
- 通用化目标：把"内容规划/研究模式"的多路径执行抽象为通用 DAG 编排引擎，可复用
- 与特性 007（LLM 网关韧性）的关系：节点内可能调 LLM，但节点级重试与模型级重试分层
- 与特性 009（Hooks）的关系：节点执行前后挂 PreToolUse/PostToolUse 钩子
- 与特性 002（session-versioning）的关系：工作流版本化（GraphSpec）是 002 的后续范围，本特性提供引擎
- 表达式求值的安全边界（禁用任意代码）需 clarify

## Functional Requirements

- FR-1: 支持四编排模式：sequential / supervisor / hybrid / graph
- FR-2: graph 模式按 DAG 拓扑执行，无依赖节点可并行
- FR-3: 执行前拓扑排序 + 环检测，环报错含环路径
- FR-4: 节点支持条件跳过（表达式求值），跳过可追溯；语法错误默认 fail_closed（跳过 + 审计），可配置为报错中断
- FR-5: 节点支持指数退避重试，次数/退避可配置
- FR-6: 节点失败阻塞其下游依赖
- FR-7: 编排执行事件（节点启动/完成/失败/跳过/重试）进审计
- FR-8: 编排定义声明式（节点/边/条件/重试），可复用、可版本化（与 002 工作流版本化对接）
- FR-9: 现有"内容规划/研究模式"可迁移到通用 DAG 引擎（向后兼容）

## Non-Goals
- 不实现工作流版本发布/灰度/回滚/轨迹回放（属 002 后续，本特性只提供引擎）
- 不实现条件表达式的沙箱化任意代码执行（仅受限表达式）
- 不实现跨实例编排协调（单实例内）
- 不改变现有内容规划场景的行为（迁移后行为等价）

## Success Criteria
- 四模式全部可编排执行
- 环检测 100% 拒绝含环图（报错含环路径）
- 条件跳过 100% 可追溯
- 节点重试按配置生效，最终失败阻塞下游
- 现有内容规划场景迁移后行为等价（回归 0 破坏）

## Further Details
- 技术实现（拓扑排序算法、环检测、表达式求值、并行调度）由 plan.md 承载
- 与特性 002/007/009 的关系已述
- 表达式安全边界与迁移策略需 clarify

## Clarify 记录（/speckit-clarify，2026-07-08）

### OQ-1 条件表达式求值语言
- **决策**：用 **JSON 条件对象**（受限算子：`==`/`!=`/`>`/`>=`/`<`/`<=`/`and`/`or`/`not`/`in`/`has`），**不用任意代码 AST**。
- **依据**：仓库已有 `ast.literal_eval` 用法（`tools/pdf.py`）但仅限字面量；条件对象是声明式、可序列化、可审计（与 009 钩子声明式规则同风格），杜绝代码注入。
- **影响**：`orchestration/conditions.py` 实现 JSON 条件求值器，不支持 lambda/函数调用。

### OQ-2 并行度上限
- **决策**：无依赖节点并行默认 **并发度 = 4**（可配 `dag_max_concurrency`）。
- **依据**：避免节点无限制并行打爆下游（LLM/工具）；与 007 网关韧性配合（并行度超限时退避）。

### OQ-3 节点重试与 007 模型重试分层
- **决策**：**分层**——007 做模型调用级重试（provider failover + 退避），010 做节点级重试（节点整体失败后重跑节点，含内部模型调用）。节点重试包裹 007 的模型调用，二者不重复。
- **影响**：`orchestration/retry.py` 节点重试指向上游 007 的韧性调度器，不在节点内再套一层模型退避。

### OQ-4 现有内容规划场景迁移策略
- **决策**：**双轨并行 + 等价测试**（不一次替换）。
- **依据**：`content/planning/builder.py` 现有 semantic/structured/projected/fallback 多路径，迁移到 DAG 引擎需等价测试保证行为不漂移；双轨期新编排走 DAG，旧场景保留至等价验证通过。
- **影响**：`orchestration/` 不绑定内容语义，`content/planning` 作为"可迁入 DAG 的既有场景"做迁移验证。

### OQ-5 表达式语法错误策略（checklist CHK013 补齐，2026-07-08）
- **决策**：默认 **fail_closed**——语法错误的条件表达式节点被跳过 + 审计记录，不静默放行；可配置为"报错中断整个编排"。
- **依据**：与 009 hooks 的 fail_closed 底线一致（constitution 原则 III）；默认跳过比中断对业务更友好，但"跳过"必须留审计，杜绝静默。
