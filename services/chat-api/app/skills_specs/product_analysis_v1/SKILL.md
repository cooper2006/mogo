---
name: product_analysis_v1
displayName: 产品分析
packageName: product-analysis-v1
version: 1.0.0
description: 分析竞品——功能清单、市场定位与能力差距。
role: subagent
parent_skill: competitor_deep_dive
whenToUse: 作为 competitor_deep_dive 图编排的子智能体节点被调用，不由最终用户直接选择。
inputs:
  - competitor_name
  - our_product
  - feature_focus
outputs:
  - product_analysis_result
tools:
  - browser_agent
  - fetch_url
  - compare_features
steps:
  - discover_product_surfaces
  - capture_feature_inventory
  - diff_against_our_product
  - assess_positioning
  - produce_feature_matrix
validation:
  required_sections:
    - Product Overview
    - Feature Matrix
    - Positioning
    - Capability Gaps
  must_include_fields:
    - Feature evidence URL
    - Capture timestamp
    - Gap severity
resources:
  - templates/product_analysis.md
  - scripts/feature_normalize.py
  - validation.yaml
---

# Purpose

作为 `competitor_deep_dive` 编排的**子智能体**，负责产品维度：抓取竞品官网与更新日志，产出可对比的功能矩阵，供 `report_synthesis` 交叉引用。

# Execution notes

- 本 Skill 由 `competitor_deep_dive` 编排按节点调用，输入来自编排的共享上下文。
- 输出写入 product_analysis_result，供下游节点按 data_contract 的 output_key 读取。
- 节点级超时与指数退避重试由编排统一管理（见 `competitor_deep_dive.yaml`）。
- 所有节点执行事件进入 001 gatekeeper 审计。
