# 案例一：客户反馈智能分诊（单智能体）

> 场景类型：单 Skill · 单会话 · 单智能体
> 目标用户：客服运营、产品经理、售后负责人
> 依赖能力：文档解析 · Spreadsheet · RAG · PII 脱敏 · RBAC 审批 · 审计 · 成本驾驶舱

## 1. 场景描述

**痛点**：某 SaaS 企业每天收到 200–500 条用户反馈（来自客服工单、邮件、社群、应用内反馈）。人工分诊耗时 4–6 小时/日，且紧急问题（P0）容易被埋没。

**期望**：用户把一批反馈（Excel / CSV / 邮件转发文本）丢给智能体，一次交互得到一份结构化分诊报告：按严重度分级、去重聚类、识别 P0 需要立即响应、生成跟进摘要、必要时触发审批。

**为什么是单智能体**：任务边界清晰（一批输入 → 一份报告），子任务之间是**顺序依赖**（先分类，再排名，再写报告），无需并行，也无需角色分工——单 Skill 单会话就能覆盖。

## 2. 架构图

```
┌─────────────────────────────────────────────────────────────┐
│                    用户会话（chat-api）                       │
│                                                              │
│  ┌──────────────┐    ┌──────────────────────────────────┐  │
│  │  用户上传     │───▶│  customer_feedback_triage Skill   │  │
│  │  feedback_   │    │                                    │  │
│  │  batch.xlsx  │    │  steps:                           │  │
│  └──────────────┘    │   1. load_feedback                │  │
│                      │   2. normalize_batch               │  │
│  输出：              │   3. classify_severity              │  │
│  ├─ triage_report.md │   4. categorize_issue              │  │
│  ├─ action_items.csv │   5. detect_pii_and_redact         │  │
│  └─ (审批事件)       │   6. rank_action_items             │  │
│                      │   7. compose_report                │  │
│                      │   8. trigger_approval_if_p0        │  │
│                      └──────────────────────────────────┘  │
│                              │                                │
│                              ▼                                │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  底层能力（enterprise_capabilities + governance）        │ │
│  │  - documents.py / spreadsheets.py（解析）               │ │
│  │  - rag_service/（历史工单检索）                          │ │
│  │  - governance/pii.py（PII 脱敏）                        │ │
│  │  - governance/layers/quota.py（配额+审批）              │ │
│  │  - governance/layers/rbac.py（权限）                    │ │
│  │  - 001 gatekeeper（审计）                                │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

## 3. Skill 定义（YAML）

放置位置：`services/chat-api/app/skills_specs/customer_feedback_triage/SKILL.md`

```yaml
---
name: customer_feedback_triage
version: 1.0.0
description: Batch-triage customer feedback into severity, category, and actionable summary.
inputs:
  - feedback_source       # file path (xlsx/csv/pdf/txt) or pasted text
  - product_line          # optional, for scope filtering
  - tenant_context        # optional, injects tenant-specific taxonomy
outputs:
  - triage_report.md
  - action_items.csv
tools:
  - read_file
  - parse_spreadsheet
  - parse_pdf
  - rag_search
  - pii_redact
  - audit_log
when_to_use:
  - intent == "feedback_triage"
  - input has > 10 items and matches feedback pattern
steps:
  - load_feedback
  - normalize_batch
  - classify_severity
  - categorize_issue
  - detect_pii_and_redact
  - rank_action_items
  - compose_report
  - trigger_approval_if_p0
validation:
  required_sections:
    - Executive Summary
    - P0 P1 Items
    - Trend Analysis
    - Recommended Actions
  must_include_fields:
    - Source batch id
    - Classification timestamp
    - Total items count
    - P0 count
    - P1 count
resources:
  - templates/triage_report.md
  - templates/action_items.csv
  - scripts/severity_heuristics.py
  - validation.yaml
---

# Purpose
在单一会话内对一批用户反馈做结构化分诊：
按严重度（P0/P1/P2/P3）与问题类别聚类，识别需要立即介入
的紧急项，识别高频模式与趋势，输出可执行的跟进摘要。

# Step Contracts

## load_feedback
从 `feedback_source` 读取原始条目。支持 xlsx / csv / pdf / txt。
xlsx/csv 用 `spreadsheets.py` 的 `read_table` 接口；pdf 用
`document_parser.py`。每条反馈统一转为：
```
{ id, source_channel, timestamp, user_id?, subject, body, attachments? }
```

## normalize_batch
去重（正文 hash）、剔除空条目、字段规范化（时区统一 UTC+8）。

## classify_severity
对每条打 P0–P3 标签。启发式规则：
- P0：包含"无法登录""数据丢失""服务不可用""支付失败"或
       `severity_heuristics.py` 中定义的关键词 + 情感极负面
- P1：功能异常、性能问题、影响主流程
- P2：功能请求、体验问题
- P3：建议、表扬、非阻断性反馈

## categorize_issue
按 `product_line` 与 `tenant_context.taxonomy` 归入类别（模块级）。
默认 8 大类：登录账号 / 数据同步 / 性能 / 计费 / 集成 / 内容 / 权限 / 其他。

## detect_pii_and_redact
调用 `governance/pii.py`，对身份证号/手机号/银行卡/邮箱按策略
（mask / abstract）替换为可逆占位符；原文不落盘，脱敏文本进入报告。

## rank_action_items
在 P0+P1 中按（时间戳紧迫度 × 影响面 × 情感强度）打分排序，取 Top 20。

## compose_report
按 `templates/triage_report.md` 结构生成：
- Executive Summary（3 段内）
- P0/P1 Items（含引用原文脱敏片段 + 建议动作 + 责任人字段）
- Trend Analysis（本批 vs 最近 7 天：类别分布、环比）
- Recommended Actions（分"立即响应"和"周度跟进"两组）

## trigger_approval_if_p0
如果本批 P0 数量 ≥ 3，调用 `governance/layers/approval.py`
触发一次审批事件（R1 分级），审批人为租户配置的 P0 值班组。
否则直接跳过（010 DAG 引擎的 `skip_condition` 场景）。
```

## 4. 关键能力调用点

| Skill Step | 底层能力 | 项目位置 |
|---|---|---|
| `load_feedback` | `spreadsheets.py` / `document_parser.py` | `services/chat-api/app/services/` |
| `normalize_batch` | 内置（Python 纯逻辑） | Skill scripts |
| `classify_severity` | LLM + `severity_heuristics.py` | Skill scripts + `app/llm/` |
| `categorize_issue` | LLM + `tenant_context.taxonomy` | `app/services/site_profiles.py` |
| `detect_pii_and_redact` | `governance/pii.py` | `services/admin-api/app/governance/pii.py` |
| `rank_action_items` | 内置打分（无 LLM） | Skill scripts |
| `compose_report` | LLM + `deep_research_report_style_v1` 风格约束 | `app/skills_specs/deep_research_report_style_v1/` |
| `trigger_approval_if_p0` | `governance/layers/approval.py` | `services/admin-api/app/governance/layers/` |

**为什么不用多智能体**：以上所有 step 共享同一份"批次上下文"，任何并行拆分都会导致上下文重建成本 > 并行收益。

## 5. 输入输出契约

### 输入示例

```json
{
  "intent": "feedback_triage",
  "feedback_source": "/data/inputs/feedback_2026-09-24.xlsx",
  "product_line": "askai-pro",
  "tenant_context": {
    "taxonomy": {
      "modules": ["登录账号", "数据同步", "性能", "计费", "集成", "内容", "权限", "其他"],
      "p0_keywords": ["无法登录", "数据丢失", "支付失败", "服务不可用"]
    }
  }
}
```

### 输出示例

`triage_report.md`（截取）：
```markdown
# 客户反馈分诊报告 · 2026-09-24

## Executive Summary
本批 342 条反馈，识别出 5 条 P0、28 条 P1、61 条 P2、248 条 P3。
P0 集中在"登录账号"与"计费"两类，与 09-22 发布的登录态改动强相关。

## P0 / P1 Items
| # | 严重度 | 类别 | 时间 | 摘要 | 建议动作 |
|---|--------|------|------|------|----------|
| 1 | P0 | 登录账号 | 09-24 08:12 | 部分企业用户无法登录（脱敏） | 立即联系值班 SRE，回滚登录态 |
...

## Trend Analysis
- "登录账号"环比 +340%（09-23 基线 6 → 本批 26）
- "计费"环比 +80%
- 整体 P0 数量超过 7 日均值 3 倍

## Recommended Actions
### 立即响应
- 回滚 09-22 登录态变更（P0 主因）
- 联系受影响租户（Top 5）人工安抚
### 周度跟进
- 优化登录态变更的灰度策略
- 增加 P0 关键词的实时监控告警
```

## 6. 验收标准

| # | 标准 | 验证方式 |
|---|------|----------|
| 1 | 单批 500 条反馈处理 ≤ 3 分钟 | 端到端计时 |
| 2 | P0 识别召回率 ≥ 95%（人工标注 100 条对照） | 混淆矩阵 |
| 3 | PII 泄漏率 = 0（脱敏后报告扫描敏感词） | 正则 + Shannon 熵双判定 |
| 4 | P0 ≥ 3 时审批事件正确触发 | `approval_events` 表验证 |
| 5 | 成本记录（token）进入 008 ops-dashboard | `token_usage` 表验证 |
| 6 | 全链路审计（001 gatekeeper）事件完整 | 审计查询 |
| 7 | 会话 `commit` 后报告可 resume（002 session-versioning） | 手动 resume 验证 |
| 8 | Skill 打包可被 skillhub 安装（019 skill packages） | `skill_package_install` 验证 |

## 7. 后续演进

- **v1.1**：接入实时数据流（WebSocket）而非批量文件，支持"边到边分"
- **v1.2**：接入审批人的"分诊决策历史"，学习个性化严重度判断（017 three-scope-memory）
- **v2.0**：与 `competitor_deep_dive` 类似的多智能体方案对比测试——若反馈来源跨多个系统（工单 + 邮件 + 社群 + 应用内），拆分到多子智能体并行抓取更有意义

## 8. 参考

- Skill 规范结构：`services/chat-api/app/skills_specs/stock_analysis/SKILL.md`（内置参考实现）
- PII 策略引擎：`services/admin-api/app/governance/pii.py`
- 审批流：`services/admin-api/app/governance/layers/approval.py`
- RBAC：`services/admin-api/app/governance/layers/rbac.py`
- 成本驾驶舱：`services/chat-api/app/api/dashboard_usage.py`
- 会话版本化：`services/chat-api/app/services/session_versioning/`
