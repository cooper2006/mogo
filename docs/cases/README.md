# MOVO 智能体案例集

本目录收录基于 MOVO 项目实际能力（企业能力 + Skill 系统 + DAG 编排引擎）设计的落地案例。每个案例均包含：

- 场景描述与业务价值
- 架构图
- Skill / 编排定义（YAML，可直接放 `skills_specs/` 参考实现）
- 关键能力调用点（对应项目代码位置）
- 输入输出契约
- 验收标准

## 案例索引

| 案例 | 类型 | 核心能力 | 适用场景 |
|---|---|---|---|
| [客户反馈智能分诊](./single-agent-customer-feedback-triage.md) | 单智能体 · 单 Skill | 文档解析 · Spreadsheet · RAG · PII · 审批 · 审计 | 客服工单 / 售后运营 |
| [竞品深度调研](./multi-agent-competitor-deep-dive.md) | 多智能体 · DAG graph | DAG 编排 · 并行执行 · 条件跳过 · 报告合成 · 成本聚合 | 战略 / 产品 / 投资 |

## 单智能体 vs 多智能体：什么时候用哪个？

| 维度 | 单智能体 | 多智能体 |
|---|---|---|
| 任务边界 | 清晰、单一 | 跨越多个领域 |
| 子任务关系 | 顺序依赖 | 可并行、有明确依赖拓扑 |
| 上下文共享 | 天然共享（同一会话） | 通过数据契约跨节点传递 |
| 典型编排模式 | 线性 steps | `graph` / `hybrid` |
| 失败处理 | 单点失败 → 全流程失败 | 单节点失败 → 其他节点继续 |
| 成本 | 低（单模型调用） | 高（多子智能体调用） |
| 典型 Skill 数 | 1 | 2+ |

**决策指南**：

1. **能用单智能体解决就别上多智能体**——上下文重建成本 > 并行收益。
2. 判断"是否多智能体"的核心问题：**子任务之间是否有独立的数据源或分析模式？**
   - 有 → 多智能体
   - 无 → 单智能体
3. 判断 DAG 编排模式：
   - 子任务全部并行、依赖静态 → **graph**
   - 子任务间依赖需运行时决定 → **hybrid**
   - 子任务串行 → **sequential**
   - 需要监督节点动态分派 → **supervisor**

## 案例设计原则

所有案例遵循以下约束：

1. **贴合项目实际能力**：每个能力调用点必须对应 `services/chat-api/app/` 下真实存在的模块
2. **Skill 规范符合内置范式**：YAML 结构参照 `skills_specs/stock_analysis/SKILL.md`
3. **不引入新工具依赖**：只使用 movo 已有的 tools（`search_web` / `browser_agent` / `rag_search` 等）
4. **验收标准可测试**：每条标准都能通过单元测试 / 集成测试 / 人工 review 验证
5. **成本可观测**：所有多智能体案例要求成本分项可查（`token_usage` 按 node_id 聚合）

## 参考

- Skill 规范：`services/chat-api/app/skills_specs/stock_analysis/SKILL.md`（内置参考实现）
- DAG 编排：`specs/010-dag-orchestration-engine/spec.md`
- 企业能力：`services/chat-api/app/enterprise_capabilities/`
- 治理层：`services/admin-api/app/governance/`
