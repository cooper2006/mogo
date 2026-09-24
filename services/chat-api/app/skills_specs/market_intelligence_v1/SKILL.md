---
name: market_intelligence_v1
packageName: market-intelligence-v1
version: 1.0.0
description: Gather market intelligence on a company — funding, market share, growth.
role: subagent
parent_skill: competitor_deep_dive
whenToUse: Invoked as a sub-agent node of the competitor_deep_dive graph orchestration; not selected directly by end users.
inputs:
  - competitor_name
  - time_window
  - industry
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

作为 `competitor_deep_dive` 编排的**子智能体**，负责市场维度。不直接面向用户输出最终报告，只向下游 `report_synthesis` 节点提供结构化的 market_intel_result。

# Execution notes

- 本 Skill 由 `competitor_deep_dive` 编排按节点调用，输入来自编排的共享上下文。
- 输出写入 market_intel_result，供下游节点按 data_contract 的 output_key 读取。
- 节点级超时与指数退避重试由编排统一管理（见 `competitor_deep_dive.yaml`）。
- 所有节点执行事件进入 001 gatekeeper 审计。
