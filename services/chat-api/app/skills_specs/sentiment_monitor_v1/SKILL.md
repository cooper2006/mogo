---
name: sentiment_monitor_v1
packageName: sentiment-monitor-v1
version: 1.0.0
description: Social sentiment monitoring and topic clustering for a competitor.
role: subagent
parent_skill: competitor_deep_dive
whenToUse: Invoked as a sub-agent node of the competitor_deep_dive graph orchestration; not selected directly by end users.
inputs:
  - competitor_name
  - channels
  - time_window
outputs:
  - sentiment_monitor_result
tools:
  - social_media_scrape
  - sentiment_score
steps:
  - collect_mentions
  - normalise_records
  - score_sentiment
  - cluster_topics
  - produce_sentiment_summary
validation:
  required_sections:
    - Sentiment Distribution
    - Negative Themes
    - Positive Themes
    - Volume Trend
  must_include_fields:
    - Channel
    - Sample size
    - Collection window
resources:
  - templates/sentiment.md
  - scripts/topic_cluster.py
  - validation.yaml
---

# Purpose

作为 `competitor_deep_dive` 编排的**子智能体**，负责舆情维度：汇总社媒讨论、给出情感分布与主要负面主题聚类。

# Execution notes

- 本 Skill 由 `competitor_deep_dive` 编排按节点调用，输入来自编排的共享上下文。
- 输出写入 sentiment_monitor_result，供下游节点按 data_contract 的 output_key 读取。
- 节点级超时与指数退避重试由编排统一管理（见 `competitor_deep_dive.yaml`）。
- 所有节点执行事件进入 001 gatekeeper 审计。
