# Feature Specification: Five-Event Hooks Interception Mechanism

**Feature Branch**: `009-hooks-interception`

**Created**: 2026-07-08

**Status**: Draft

**Input**: 补齐规划文档清单 4（P1）"Hooks 拦截机制"：五事件 SessionStart / PreToolUse / PostToolUse / SessionEnd / MemoryCommit + 超时保护 + fail_closed + 声明式规则（deny_tool / require_field / observe）。重点强调会话生命周期事件（SessionStart/End/MemoryCommit）——会话级是 Hooks 最核心触发维度；可先做 PreToolUse 单一事件切入，作为合规拦截/字段校验/工具禁用扩展点。

## User Scenarios & Testing *(mandatory)*

用户故事按优先级排列，每个独立可交付、可测试。

### User Story 1 (P1) — PreToolUse 单一事件切入（低成本）

工具调用执行前触发 PreToolUse 钩子，按声明式规则判定：
- `deny_tool` → 直接拒绝该工具调用（合规拦截）
- `require_field` → 校验必填字段，缺失则拒绝
- `observe` → 仅记录观察事件，不拦截
钩子超时按 fail_closed 处理（超时即拒绝，不放行）。

**Acceptance Scenarios:**
- 配置 deny_tool 规则命中某工具 → 调用前被拒，审计记录拒绝原因
- 配置 require_field 校验必填字段缺失 → 拒绝并提示缺哪个字段
- observe 规则 → 记录事件但不拦截，工具正常执行
- 钩子超时 → fail_closed 拒绝（不默认放行）

### User Story 2 (P1) — 超时保护 + fail_closed

每个钩子执行有超时保护；超时、异常或规则无法解析时按 fail_closed 处理（拒绝而非放行），避免钩子故障导致越权执行。

**Acceptance Scenarios:**
- 钩子执行超阈值 → 超时，按 fail_closed 拒绝并记录
- 钩子抛异常 → fail_closed 拒绝，异常可定位
- 规则声明解析失败 → fail_closed（不静默跳过规则）

### User Story 3 (P2) — 会话生命周期事件（SessionStart / SessionEnd / MemoryCommit）

会话进入/结束/记忆提交时触发对应钩子，作为会话级治理扩展点（与特性 002 会话版本化、001 脱敏联动）。

**Acceptance Scenarios:**
- 会话开始 → SessionStart 钩子执行（可注入上下文）
- 会话结束 → SessionEnd 钩子执行（可收尾/清理）
- 记忆提交 → MemoryCommit 钩子执行（可触发经验沉淀，与特性 011 联动）

### User Story 4 (P2) — PostToolUse 结果钩子

工具调用完成后触发 PostToolUse，可对结果做后处理（如脱敏、审计、状态回写）。

**Acceptance Scenarios:**
- 工具成功 → PostToolUse 执行
- 工具失败 → PostToolUse 仍执行（区分成功/失败路径）

### Notes / Assumptions
- 本特性补齐规划文档清单 4（P1，低成本高扩展），属缺口新特性
- 现状：仓库无自身钩子/拦截器框架（"hooks" 仅出现在 browser engine 与第三方库），MOGO 当前基本空缺
- 现有近似挂载点：`dsh_runtime/turn_admission.py`（admit_skill_selection）、`governance/approval_runtime.py`（ApprovalRuntime）、`dsh_runtime/tool_gateway`
- 与特性 001（gatekeeper）的关系：PreToolUse 是 001 六层门禁链的"可扩展拦截"扩展点，二者互补（001 是固定六层，009 是声明式规则驱动）
- 与特性 002（session-versioning）的关系：SessionStart/End/MemoryCommit 是 002 会话生命周期事件的钩子载体
- 落地策略：先 PreToolUse 单事件切入，再补齐其余四事件
- 钩子超时阈值与 fail_closed 默认行为需 clarify

## Functional Requirements

- FR-1: 支持五事件钩子：SessionStart / PreToolUse / PostToolUse / SessionEnd / MemoryCommit；**五事件为目标态，首期交付仅 PreToolUse（其余按节奏补齐）**
- FR-2: PreToolUse 支持声明式规则：deny_tool（**拒绝指定工具调用**）/ require_field（**请求缺必填字段则拒绝**）/ observe（**仅记录不改拦截结果**，唯一可配置为"只记录不拦截"的规则类型）
- FR-3: 每个钩子有超时保护，**默认 5s（`hook_timeout_seconds` 可配）**；超时/异常/规则解析失败按 fail_closed 拒绝（**不可配置为放行**）
- FR-4: 钩子规则声明式配置（`hook_rules{scope, rule_type, rule_config, enabled}`），无需改代码增删（扩展点）；**规则变更即时生效（下一工具调用即按新规则求值）**
- FR-5: 钩子执行事件进入审计通道（与 001 联动，复用 001 审计落点）
- FR-6: PostToolUse 区分成功/失败路径均执行
- FR-7: 会话生命周期事件（SessionStart/End/MemoryCommit）与特性 002 联动
- FR-8: 钩子规则支持作用域（按工具/按会话/按租户）；**同一调用命中多作用域时叠加求值，合并语义：任一 deny 命中即拒绝（deny 优先于 require），observe 规则全部记录**
- FR-9: **规则求值顺序：先按作用域（工具 > 会话 > 租户）求值，再按规则类型（deny > require > observe）；deny 命中即短路返回，不再求值后续规则**
- FR-10: **deny_tool 拒绝返回 403 + 明确提示"被钩子规则拒绝"（与门禁层拒绝区分：门禁拒绝提示权限/配额原因，钩子拒绝提示规则原因）**
- FR-11: **"规则解析失败" 三类均 fail_closed：规则 JSON 非法 / 必填字段缺失 / 未知 rule_type**
- FR-12: **五事件各自可携带/可修改数据：SessionStart 可注入初始上下文（如租户/PII 策略）；PreToolUse 可读取工具入参并可拒绝/改参；PostToolUse 可读取结果并可记录/脱敏；SessionEnd 可清理会话级临时态；MemoryCommit 可读取待提交记忆并可过滤**
- FR-13: **钩子执行延迟预算：单次工具调用的钩子总延迟上限 = 5s（多钩子叠加共享该预算，超限按 fail_closed 拒绝），不额外叠加**

## Non-Goals
- 不实现钩子的外部插件沙箱（本期为声明式规则，非任意代码执行）
- 不改变 DSH 运行时单会话 Agent 执行语义
- 不实现钩子的灰度/AB（属独立能力）
- 不实现钩子跨实例同步
- 先做 PreToolUse，其余事件按节奏补齐（非一次全量）

## Success Criteria
- PreToolUse 声明式规则 100% 生效（deny/require/observe）
- 钩子超时/异常 100% fail_closed（无越权放行）
- 五事件钩子全部可触发
- 钩子执行 100% 进审计
- 声明式配置增删规则无需改代码

## Further Details
- 技术实现（钩子注册、超时、fail_closed、规则解析）由 plan.md 承载
- 与特性 001（gatekeeper）互补：PreToolUse 是 001 门禁链的扩展点
- 落地顺序与超时阈值需 clarify

### 跨特性关系（被依赖方视角，2026-07-08 双向声明）
- **与 001（gatekeeper）**：009 的 PreToolUse 钩子是 001 六层门禁链的**扩展点**；钩子执行事件进 **001 的审计落点**（不另建钩子审计集合）。
- **与 002（session-versioning）**：009 的 SessionStart/SessionEnd/MemoryCommit 钩子**以 002 的会话生命周期事件为载体**（002 提供事件语义，009 提供挂载点）。
- **与 010（dag-orchestration）**：010 的**节点执行**（节点启动前/完成后）是 009 的 PreToolUse/PostToolUse 钩子**触发点之一**（节点内工具调用过钩子）。
- **与 019（harness-elastic-config）**：019 薄模式可跳过 009 的**非红线钩子**；**fail_closed 底线保留**（钩子故障仍 fail_closed，不可因薄模式放行）；"非红线"= 不含 R4 红线工具拦截的 observe/require 钩子。

## Clarify 记录（/speckit-clarify，2026-07-08）

### OQ-1 钩子超时阈值默认值
- **决策**：默认 **5s**，可配置（`hook_timeout_seconds`）。
- **依据**：`enterprise_capabilities/tools/execution_timeout.py` 已有 `ExecutionTimeoutPolicy`（total_seconds + inactivity 双层），钩子超时复用该策略模式，5s 是声明式规则求值的合理上限。

### OQ-2 fail_closed 默认行为
- **决策**：超时/异常/规则解析失败**一律 fail_closed 拒绝**（不放行），且**不可配置为放行**。
- **理由**：constitution 原则 III（Security fail-closed）+ 019 底线守护——钩子故障若默认放行等于绕过治理，合规场景不可接受。仅"observe 规则"可配置为只记录不拦截。

### OQ-3 首期范围
- **决策**：**首期仅落 PreToolUse 单事件**（规划文档"落地建议 3"），SessionStart/End/MemoryCommit/PostToolUse 按节奏补齐。
- **依据**：`turn_admission.admit_skill_selection` 是 PreToolUse 的天然切入挂载点，最小代价获得合规拦截能力。

### OQ-4 规则作用域存储 schema
- **决策**：`hook_rules{scope ∈ {tool, session, tenant}, rule_type ∈ {deny_tool, require_field, observe}, rule_config, enabled}`，作用域字段决定匹配粒度。
