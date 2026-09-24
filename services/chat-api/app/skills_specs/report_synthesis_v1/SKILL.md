---
name: report_synthesis_v1
packageName: report-synthesis-v1
version: 1.0.0
description: Synthesise upstream sub-agent outputs into an analyst-grade research report.
role: subagent
parent_skill: competitor_deep_dive
whenToUse: Invoked as a sub-agent node of the competitor_deep_dive graph orchestration; not selected directly by end users.
inputs:
  - competitor_name
  - our_product
  - market_intel_result
  - product_analysis_result
  - financial_analysis_result
  - sentiment_monitor_result
outputs:
  - research_report
  - evidence_json
tools:
  - compose_report
steps:
  - load_upstream_outputs
  - cross_reference_claims
  - apply_style_constraints
  - emit_evidence_index
  - compose_final_report
validation:
  required_sections:
    - 执行摘要
    - 市场情报
    - 产品功能对比
    - 财务分析
    - 舆情监测
    - 综合判断与决策建议
    - 附录 · 证据追溯
  must_include_fields:
    - Data window
    - Skipped sections with reason
    - Evidence ID per claim
resources:
  - templates/research_report.md
  - scripts/evidence_index.py
  - validation.yaml
---

# Purpose

作为 `competitor_deep_dive` 编排的**汇总节点**，读取四个上游节点的 output_key，交叉引用后输出最终 `research_report.md` 与 `evidence.json`。当完成的上游节点少于 3 个时该节点会被 `skip_condition` 跳过，改出降级报告。

# Execution notes

- 本 Skill 由 `competitor_deep_dive` 编排按节点调用，输入来自编排的共享上下文。
- 输出写入 research_report，供下游节点按 data_contract 的 output_key 读取。
- 节点级超时与指数退避重试由编排统一管理（见 `competitor_deep_dive.yaml`）。
- 所有节点执行事件进入 001 gatekeeper 审计。
