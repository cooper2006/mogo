# 案例二：竞品深度调研（多智能体协同）

> 场景类型：多 Skill · 多智能体 · DAG graph 编排
> 目标用户：战略部、产品部、投资部、市场情报团队
> 依赖能力：DAG 编排引擎（010）· 研究模式（progressive）· RAG · 浏览器 Agent · 报告风格约束 · 成本聚合

## 1. 场景描述

**痛点**：战略团队需要定期出一份竞品的深度调研报告，覆盖市场、产品、财务、舆情四个维度。人工完成一份报告需要 2–3 周，涉及多团队并行，且各维度数据源分散（新闻、财报、社媒、竞品官网、第三方数据平台）。

**期望**：用户输入一个竞品名（如"钉钉"），一次交互得到一份 analyst-grade 深度调研报告，含市场情报、产品功能对比、财务估值、社媒舆情四章 + 综合判断。

**为什么是多智能体**：

| 维度 | 数据源 | 分析模式 | 独立子智能体 |
|---|---|---|---|
| 市场情报 | 新闻、财报披露、行业报告 | 检索 + 时间线 | 是 |
| 产品分析 | 官网、功能页、更新日志 | 浏览器抓取 + 对比 | 是 |
| 财务分析 | 招股书、财报、估值数据 | 定量 + 估值模型 | 是 |
| 舆情监测 | 微博、知乎、V2EX、Reddit | 情感 + 聚类 | 是 |
| 报告合成 | 前 4 个输出 | 交叉引用 + 判断 | 是（最后触发） |

**关键架构决策**：4 个分析节点**可并行**（数据源互不依赖），报告合成节点**必须等待**其他 4 个完成——这是典型的 **DAG graph** 拓扑，movo 的 010 编排引擎原生支持。

## 2. 架构图

```
                    ┌─────────────────────────┐
                    │   用户输入 competitor    │
                    │   (e.g. "钉钉")           │
                    └────────────┬────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │  supervisor 协调节点     │
                    │  (planner + aggregator) │
                    └────────────┬────────────┘
                                 │
         ┌───────────────────────┼───────────────────────┐
         │                       │                       │
         ▼                       ▼                       ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│ market_intel    │  │ product_analysis│  │ financial_      │  │ sentiment_      │
│ (市场情报员)    │  │ (产品分析师)    │  │ analysis        │  │ monitor         │
│                 │  │                 │  │ (财务分析师)    │  │ (舆情监测员)    │
│ 检索 + 时间线  │  │ 浏览器 + 对比   │  │ 定量 + 估值     │  │ 情感 + 聚类     │
└────────┬────────┘  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘
         │                    │                     │                    │
         │  [条件跳过]         │  [失败重试]          │  [私有公司则跳过]   │
         ▼                    ▼                     ▼                    ▼
         └────────────────────┴─────────────────────┴────────────────────┘
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │  report_synthesis       │
                    │  (报告合成师)            │
                    │  引用 4 节点输出         │
                    │  + 综合判断             │
                    └────────────┬────────────┘
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │  research_report.md     │
                    │  + evidence.json        │
                    └─────────────────────────┘
```

## 3. DAG 编排定义

放置位置：`services/chat-api/app/enterprise_capabilities/research/orchestrations/competitor_deep_dive.yaml`

```yaml
orchestration:
  id: competitor_deep_dive
  version: 1.0.0
  mode: graph                     # 010 四模式之一：graph
  max_concurrency: 4              # dag_max_concurrency 默认 4
  timeout: 900                    # 15 分钟总超时，与 §8 验收标准一致（不是 1800）
  retry:
    max_attempts: 2               # 每节点最多重试 2 次
    backoff: exponential          # 指数退避
    base_seconds: 5

nodes:
  - id: market_intel
    skill: market_intelligence_v1
    timeout: 600
    tools: [search_web, fetch_news, firecrawl_collect]

  - id: product_analysis
    skill: product_analysis_v1
    timeout: 900
    tools: [browser_agent, fetch_url, compare_features]
    depends_on: []                # 与 market_intel 并行

  - id: financial_analysis
    skill: financial_analysis_v1
    timeout: 600
    tools: [fetch_financials, compute_valuation]
    skip_condition:               # 010 FR-4 条件跳过
      expr: "competitor_is_private == true"
      reason: "private company has no public financials"

  - id: sentiment_monitor
    skill: sentiment_monitor_v1
    timeout: 600
    tools: [social_media_scrape, sentiment_score]
    depends_on: []                # 与上面 3 个并行

  - id: report_synthesis
    skill: report_synthesis_v1
    timeout: 600
    depends_on: [market_intel, product_analysis, financial_analysis, sentiment_monitor]
    skip_condition:
      expr: "completed_children_count < 3"
      reason: "insufficient upstream data — emit degraded report instead"

# 数据契约：上游节点输出写入共享上下文（key 引用），下游按 key 读取
# 010 FR-1：节点间数据传递 = 上游节点输出写入共享上下文
data_contract:
  market_intel.output_key: market_intel_result
  product_analysis.output_key: product_analysis_result
  financial_analysis.output_key: financial_analysis_result
  sentiment_monitor.output_key: sentiment_monitor_result

# 010 FR-11：supervisor 失败传播（本例为 graph 模式，规则等价）
failure_propagation:
  on_all_children_failed: mark_parent_skipped
  on_p0_child_failed: retry_with_backoff_then_mark_failed

# 审计：所有节点执行事件进入 001 gatekeeper 审计
audit:
  enabled: true
  emit_events: [node_start, node_complete, node_skip, node_retry, node_fail]
```

## 4. 子智能体 Skill 定义（示例：market_intelligence_v1）

放置位置：`services/chat-api/app/skills_specs/market_intelligence_v1/SKILL.md`

```yaml
---
name: market_intelligence_v1
version: 1.0.0
description: Gather market intelligence on a company — funding, market share, growth.
role: subagent
parent_skill: competitor_deep_dive
inputs:
  - competitor_name
  - time_window          # default: last 12 months
  - industry             # optional
outputs:
  - market_intel_result
tools:
  - search_web
  - fetch_news
  - firecrawl_collect
  - fetch_financial_disclosures
steps:
  - identify_competitor_legal_entity
  - collect_recent_news
  - extract_funding_events
  - extract_market_share_claims
  - build_timeline
  - produce_structured_intel
validation:
  required_sections:
    - Company Overview
    - Funding & Market
    - Growth Trajectory
    - Key Milestones Timeline
  must_include_fields:
    - Data source URLs
    - Collection timestamp
    - Confidence score per claim
resources:
  - templates/market_intel.md
  - scripts/entity_resolution.py
  - validation.yaml
---

# Purpose
作为 `competitor_deep_dive` 编排的**子智能体**，负责市场维度。
不直接面向用户输出最终报告，只向下游 `report_synthesis` 节点提供
结构化的 market_intel_result。
```

**其他 3 个子智能体 Skill 同构**：`product_analysis_v1`（浏览器抓取 + 功能对比）、`financial_analysis_v1`（估值模型 + 财务比率）、`sentiment_monitor_v1`（社媒情感分析 + 聚类）。

**报告合成 Skill**：`report_synthesis_v1` 引用 `deep_research_report_style_v1` 作为风格约束，读取 4 个上游节点的 output_key，输出最终报告。

## 5. 关键能力调用点

| 能力 | 项目位置 | 用途 |
|---|---|---|
| DAG 编排引擎 | `services/chat-api/app/orchestration/graph.py` | 拓扑排序 + 环检测 + 并行调度 |
| 条件跳过 | `services/chat-api/app/services/dag/skip.py` | 私有公司跳过财务分析 |
| 节点重试 | `services/chat-api/app/services/dag/retry.py` | 数据源超时重试 |
| 研究模式 | `services/chat-api/app/enterprise_capabilities/research/progressive/` | 渐进式检索 |
| 浏览器 Agent | `services/chat-api/app/enterprise_capabilities/browser/` | 抓竞品官网 |
| RAG | `services/chat-api/app/services/rag_service/` | 检索企业内部知识库 |
| 报告风格 | `services/chat-api/app/skills_specs/deep_research_report_style_v1/` | 15 项 analyst 写作约束 |
| 会话版本化 | `services/chat-api/app/services/session_versioning/` | 报告 commit 交接 |
| 成本聚合 | `services/chat-api/app/llm/resilience/metering.py` | 各节点成本分项 |
| 审计 | `services/admin-api/app/governance/layers/` | 全链路追踪 |

## 6. 数据流与失败处理

### 6.1 数据传递

每个子智能体节点完成时，其 `outputs` 写入共享上下文（`dag_result[node_id]`）。`report_synthesis` 节点通过 `data_contract.output_key` 读取所有上游输出，交叉引用。

### 6.2 失败传播

按 010 FR-11：
- 单个子节点失败（含重试后）→ 其他子节点继续，合成节点根据 `completed_children_count` 决定行为
- ≥ 3 个子节点完成 → 正常合成，缺失维度在报告中标注"数据不足"
- < 3 个子节点完成 → 合成节点**跳过**，输出"调研因数据不足中止"降级报告
- supervisor 失败（本例 graph 模式等价）→ 整个编排失败

### 6.3 私有公司特例

如果 `financial_analysis` 节点被 skip（`competitor_is_private == true`），合成节点仍能正常执行——因为其他 3 个节点完成数 = 3，满足 skip_condition 阈值。合成节点在报告中写：

```markdown
## 财务分析
本节因竞品为私有公司且未公开财报而跳过。
建议参考：
- 最近一轮融资估值（来自 market_intel_result.funding_events）
- 同行上市公司对标（见"同行对比"章节）
```

### 6.4 节点重试

- `base_seconds: 5`，指数退避：5s → 10s
- 单次节点最多重试 2 次
- 总编排超时 30 分钟（防止某节点无限重试拖垮整批）
- 重试事件进审计

## 7. 输入输出契约

### 输入示例

```json
{
  "intent": "competitor_deep_dive",
  "competitor_name": "钉钉",
  "our_product": "movo",
  "industry": "企业协作 SaaS",
  "time_window": "last 12 months",
  "depth": "deep"  // deep | standard | quick
}
```

### 输出示例

`research_report.md`（结构，截取）：
```markdown
# 钉钉 · 竞品深度调研报告（2026-09）

> Analyst-grade report. Data window: 2025-09 to 2026-09.
> 所有主张可追溯至 evidence.json。

## 执行摘要
本批调研覆盖 4 个维度，3 个子智能体完成，1 个（财务）因竞品为
阿里巴巴子公司不适用独立财报口径而跳过。总体判断：...

## 一、市场情报
（来自 market_intel_result）
- 最近融资轮次：...（$XX 亿，2026-Q1）
- 市场份额：企业协作 SaaS 中国市场份额 XX%（IDC 2026-Q2）
- 关键里程碑时间线：...

## 二、产品功能对比
（来自 product_analysis_result）
| 能力 | 钉钉 | movo | 差距 |
|---|---|---|---|
| 会话记忆 | 有 | 有 | 深度相当 |
...

## 三、财务分析（已跳过）
竞品为阿里巴巴子公司，财务数据随母公司披露，本节不适用独立分析。
建议关注阿里巴巴企业协作业务分部数据。

## 四、舆情监测
（来自 sentiment_monitor_result）
- 微博 12 个月情感评分：正面 62% / 中性 24% / 负面 14%
- 主要负面主题：账号体系切换、企业版价格上调
...

## 五、综合判断与决策建议
（来自 report_synthesis_result）
- 主路径：...
- 次路径：...
- 优先级建议：...
- 有效期边界：...

## 附录 · 证据追溯
所有引用附证据 ID，见 `evidence.json`。
```

## 8. 验收标准

| # | 标准 | 验证方式 |
|---|------|----------|
| 1 | 4 个分析节点并行执行（并发度 ≥ 3） | 编排审计日志显示时间重叠 |
| 2 | 总耗时 ≤ 15 分钟（标准深度） | 端到端计时 |
| 3 | 环检测：手工构造循环依赖 → 拒绝执行 | 单元测试 |
| 4 | 条件跳过正确：私有公司跳过财务分析 | `skip_reason` 出现在报告 |
| 5 | 节点重试：模拟一次超时 → 自动重试 | 观测到 2 次 attempt 事件 |
| 6 | 失败传播：< 3 子节点完成时合成节点跳过 | 编排状态检查 |
| 7 | Evidence 追溯：报告所有主张附证据 ID | `evidence.json` 反查 |
| 8 | 风格约束：报告符合 15 项 analyst 约束 | 人工 review + 正则 |
| 9 | 成本分项：4 个节点各自 token 消耗可查 | `token_usage` 表按 node_id 聚合 |
| 10 | 会话可 commit / share / resume | 002 session-versioning 验证 |

## 9. 为什么不用 sequential 或 hybrid

- **sequential**：4 个分析节点必须顺序执行 → 总耗时 = 各节点之和（15+ 分钟），不可接受
- **hybrid**：监督 + 部分并行，但本例 4 个分析节点**全部可并行**，不需要监督分派；监督的开销（决策 + 聚合）本可由 graph 的拓扑排序取代
- **graph**：拓扑排序 + 并行度可配 + 条件跳过 + 失败传播——**完美匹配本场景**

**hybrid 的适用场景**：子节点之间的依赖需要**运行时动态决定**（例如根据市场情报结果决定是否触发财务分析）。本例依赖是**静态的**（DAG 拓扑预先定义），用 graph 更清晰。

## 10. 后续演进

- **v1.1**：`market_intel` 与 `sentiment_monitor` 结果**互相影响**——舆情监测可以订阅市场情报的融资事件时间线（010 数据契约扩展）
- **v1.2**：`report_synthesis` 支持**追问**——用户对报告某一节不满意可发起"重新合成"，只重跑合成节点
- **v2.0**：接入 017 three-scope-memory，让子智能体学习"哪些数据来源最可靠"（经验沉淀），周期扫描发现重复抓取模式自动生成 Skill 草稿（Dream Cycle）

## 11. 参考

- DAG 编排引擎：`specs/010-dag-orchestration-engine/spec.md`
- 编排图结构：`services/chat-api/app/orchestration/graph.py`
- 条件跳过：`services/chat-api/app/services/dag/skip.py`
- 节点重试：`services/chat-api/app/services/dag/retry.py`
- 研究模式：`services/chat-api/app/enterprise_capabilities/research/progressive/`
- 报告风格：`services/chat-api/app/skills_specs/deep_research_report_style_v1/SKILL.md`
- 会话版本化：`specs/002-session-versioning/spec.md`
- 审计：`services/admin-api/app/governance/`
