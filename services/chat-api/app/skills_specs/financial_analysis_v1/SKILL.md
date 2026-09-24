---
name: financial_analysis_v1
packageName: financial-analysis-v1
version: 1.0.0
description: Quantitative financial analysis and valuation for a listed competitor.
role: subagent
parent_skill: competitor_deep_dive
whenToUse: Invoked as a sub-agent node of the competitor_deep_dive graph orchestration; not selected directly by end users.
inputs:
  - competitor_name
  - fiscal_year
  - currency
outputs:
  - financial_analysis_result
tools:
  - fetch_financials
  - compute_valuation
steps:
  - resolve_ticker_or_entity
  - collect_financial_statements
  - compute_ratios
  - build_valuation_model
  - produce_financial_summary
validation:
  required_sections:
    - Financial Snapshot
    - Key Ratios
    - Valuation
    - Comparables
  must_include_fields:
    - Reporting period
    - Currency and units
    - Data source
resources:
  - templates/financial_analysis.md
  - scripts/ratio_math.py
  - validation.yaml
---

# Purpose

作为 `competitor_deep_dive` 编排的**子智能体**，负责财务维度。当竞品为私有公司（`competitor_is_private == true`）时该节点会被 `skip_condition` 跳过，此时下游合成节点改用融资估值口径。

# Execution notes

- 本 Skill 由 `competitor_deep_dive` 编排按节点调用，输入来自编排的共享上下文。
- 输出写入 financial_analysis_result，供下游节点按 data_contract 的 output_key 读取。
- 节点级超时与指数退避重试由编排统一管理（见 `competitor_deep_dive.yaml`）。
- 所有节点执行事件进入 001 gatekeeper 审计。
