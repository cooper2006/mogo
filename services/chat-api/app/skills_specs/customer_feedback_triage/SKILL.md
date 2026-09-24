---
name: customer_feedback_triage
# The installable package name must be kebab-case (skill_packages/validator.py
# SKILL_NAME); the in-repo Skill id stays snake_case like the other built-ins.
packageName: customer-feedback-triage
version: 1.0.0
description: Batch-triage customer feedback into severity, category, and actionable summary.
whenToUse: Use when the user pastes or uploads a batch of customer feedback (tickets, emails, community posts, in-app reports) and asks for a structured triage report with severity grading and follow-up actions.
inputs:
  - feedback_source
  - product_line
  - tenant_context
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

在单一会话内对一批用户反馈做结构化分诊：按严重度（P0/P1/P2/P3）与问题类别聚类，
识别需要立即介入的紧急项，识别高频模式与趋势，输出可执行的跟进摘要。

本 Skill 面向**单智能体**场景：任务边界清晰（一批输入 → 一份报告），子任务之间是
顺序依赖（先分类，再排名，再写报告），无需并行、无需角色分工。所有 step 共享同一份
"批次上下文"，任何并行拆分都会带来上下文重建成本大于并行收益的问题。

# Step Contracts

## load_feedback

从 `feedback_source` 读取原始条目，支持 xlsx / csv / pdf / txt 与直接粘贴的文本。
表格类用 spreadsheets 的 `read_table` 接口，PDF 用文档解析器。每条反馈统一转为：

```
{ id, source_channel, timestamp, user_id?, subject, body, attachments? }
```

## normalize_batch

去重（正文 hash）、剔除空条目、字段规范化（时区统一 UTC+8）。
归一化后返回稳定的条目顺序，保证同一批次重复执行得到相同结果。

## classify_severity

对每条打 P0–P3 标签。启发式规则由 `scripts/severity_heuristics.py` 提供：

- P0：包含"无法登录""数据丢失""服务不可用""支付失败"等关键词，且情感极负面
- P1：功能异常、性能问题、影响主流程
- P2：功能请求、体验问题
- P3：建议、表扬、非阻断性反馈

`tenant_context.p0_keywords` 可覆盖默认 P0 关键词表。

## categorize_issue

按 `product_line` 与 `tenant_context.taxonomy` 归入类别（模块级）。
默认 8 大类：登录账号 / 数据同步 / 性能 / 计费 / 集成 / 内容 / 权限 / 其他。

## detect_pii_and_redact

对身份证号 / 手机号 / 银行卡 / 邮箱按策略（mask / abstract）替换为可逆占位符。
**原文不落盘**，脱敏文本进入报告。占位符与原文的映射只保留在内存中，供本次会话内
按权限回查。

## rank_action_items

在 P0+P1 中按（时间戳紧迫度 × 影响面 × 情感强度）打分排序，取 Top 20。

## compose_report

按 `templates/triage_report.md` 结构生成：

- Executive Summary（3 段内）
- P0/P1 Items（含引用原文脱敏片段 + 建议动作 + 责任人字段）
- Trend Analysis（本批 vs 最近 7 天：类别分布、环比）
- Recommended Actions（分"立即响应"和"周度跟进"两组）

`action_items.csv` 按 `templates/action_items.csv` 的列定义输出。

## trigger_approval_if_p0

当本批 P0 数量 ≥ 3 时，触发一次审批事件（R1 分级），审批人为租户配置的 P0 值班组。
否则直接跳过——这是 DAG 引擎 `skip_condition` 的典型场景。

# Acceptance

完整验收标准见 `validation.yaml`，与案例文档 `docs/cases/single-agent-customer-feedback-triage.md` §6 一一对应。
