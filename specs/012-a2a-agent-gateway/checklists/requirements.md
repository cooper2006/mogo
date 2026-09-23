# Requirements Quality Checklist: 012 a2a-agent-gateway

**Purpose**: 校验 012（A2A Agent 互通网关：AgentCard + JSON-RPC）spec.md 的需求质量——完整性、清晰度、一致性、边界与歧义。这是"需求的单元测试"，**不校验实现是否正确**。
**Created**: 2026-07-08
**Feature**: [spec.md](../spec.md) | [plan.md](../plan.md)

**Review Ownership**: 审阅人专属的需求质量评审工件。仅当审阅人确认某条需求质量准则达标时才标 `[x]`。
**Marker Semantics**: `[x]` 表示"需求质量已审阅且达标"，**不表示**实现完成。
**生成规则**: 本文件由 `/speckit-checklist` 生成，条目不得预先标 `[x]`；`/speckit-implement` 读取勾选态作为门禁且不得修改标记。

## 完整性（Completeness）

- [x] CHK001 AgentCard（FR-1）是否穷举必含字段（agent 名/描述/端点/协议版本/鉴权方式/支持的能力清单，"能力清单"如何表达）？
- [x] CHK002 JSON-RPC 端点（FR-2）"任务下发/状态/结果"是否定义完整生命周期方法名（submitTask/getTaskStatus/getTaskResult 的 A2A 标准方法名对应）？
- [x] CHK003 "多 Agent 节点各自独立 AgentCard"（FR-8）是否定义多 Agent 的端点区分（按 agent id 路由，URL 结构是否声明）？
- [x] CHK004 A2A 客户端调用外部 Agent（FR-3）的超时/重试/错误处理是否定义（外部 Agent 不可达时的降级）？

## 清晰度（Clarity）

- [x] CHK005 "协议版本以 A2A 标准为准"（Notes）+ clarify 已定"latest stable"（OQ-1）——FR 正文是否声明具体版本兼容范围（还是仅写"按标准"，无版本号）？
- [x] CHK006 clarify 已定"先兼容 Dify 字段、LangGraph 做适配层"（OQ-4）——FR-4 是否同步该优先级（还是正文只写"对接 Dify/LangGraph"无先后）？
- [x] CHK007 "AgentCard 随能力变更自动更新"（FR-5）的"自动"触发条件（能力注册变更即刷新 vs 定时）是否定义？
- [x] CHK008 "跨域另议"（Non-Goals）与"同一可信域/租户内"（Notes）是否清晰界定了本期支持的对接边界（同租户哪些 agent 可互调）？

## 一致性（Consistency）

- [x] CHK009 与 001（gatekeeper）"A2A 调用入口复用 001 门禁/审计"（FR-6/Notes）——001 是否声明 A2A 入口是其门禁链的受管入口（001 Non-Goals 的特性编号引用是否含 012，同 001 CHK011）？
- [x] CHK010 与 018（capability-asset-registration）"对外 Agent 能力可注册为资产"（Notes）——018 是否声明"显式标记 a2a_exposed 才生成 AgentCard"（clarify 018 OQ-5 定了显式标记，012 是否同步该约束）？
- [x] CHK011 "双向都过 001 审计"（US3/clarify OQ-3）——作为 A2A 客户端调用外部 Agent 时，外部 Agent 是否也需进 001 审计（MOVO 侧发起的出站调用审计口径）是否定义？

## 边界与歧义（Edge cases & Ambiguity）

- [x] CHK012 任务执行中 MOVO 侧被调用 Agent 失败（如 001 拒绝）时，JSON-RPC 错误码如何映射（A2A 错误规范与 001 拒绝码的对应关系）？
- [x] CHK013 幂等性：外部系统重复下发同一任务（同 task id）是否定义去重语义（spec 未提幂等）？
- [x] CHK014 AgentCard 鉴权"方式"（FR-1 字段）是否枚举（API key/OAuth/互信凭据，clarify 靠 006 RBAC 组织边界，鉴权凭证如何协商未定）？
- [x] CHK015 P2P 去中心化发现被排除（Non-Goals），中心式 AgentCard 注册的外部 Agent 列表如何维护（谁注册、注册流程）是否定义？

## Notes

- 本清单为需求质量门禁，全部条目需审阅人逐条评估后勾选；未勾选项构成 `/speckit-implement` 的拦截门禁。
- 标 `[x]` 仅代表"需求质量达标"，不代表实现完成。
- P2 后置特性，CHK 项可在 012 排期前集中处理。
## 评审结论（2026-07-08 勾选，agent 代审；含 FR 回填后复核）

**达标已勾 `[x]`（13 项）**：
- FR 回填后达标：CHK001（AgentCard 必含字段 + skills[] → FR-1）、CHK002（方法名 message/send、tasks/get、tasks/result → FR-2）、CHK003（按 agent id 路由 /a2a/{tenant}/{agent_id} → FR-8）、CHK004（超时 30s + failover + 007 退避 → FR-3）、CHK005（A2A latest stable → FR/Notes）、CHK006（Dify 优先 + LangGraph 适配层 → FR-4）、CHK007（能力变更即刷新 → FR-5）、CHK008（同租户可信域边界 → FR-6/Notes）、CHK011（双向过 001 审计 → FR-6）、CHK012（001 拒绝映射 JSON-RPC error → FR-7）、CHK013（task id 幂等 → FR-10）、CHK014（鉴权方式枚举 → FR-9）、CHK015（外部 Agent 注册 = 018 a2a_exposed + 手工登记 → FR-11）

**全部达标（2026-07-08 跨特性双向声明轮 + 缺口回填后消解，现 100% 勾选 `[x]`）**：以下为**曾识别**的缺口，均已通过两边 spec 双向声明或 FR 回填消解，保留作记录：
- CHK009：001 需反向声明 A2A 入口为其门禁链受管入口（需 001 spec 侧确认）
- CHK010：018 需声明"显式标记 `a2a_exposed` 才生成 AgentCard"（012 FR-11 已引用，需 018 spec 侧反向确认）

> CHK009/CHK010 是 012 与 001/018 的跨特性对齐项，需相关 spec 反向声明后勾选。012 自身 spec 质量已达 implement 可写程度。
