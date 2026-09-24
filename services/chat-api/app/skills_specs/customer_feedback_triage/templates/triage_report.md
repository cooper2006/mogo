# 客户反馈分诊报告 · {{ batch_date }}

> 来源批次：`{{ batch_id }}`
> 分类时间：{{ classified_at }}（UTC+8）
> 条目总数：{{ total_items }} ｜ P0：{{ p0_count }} ｜ P1：{{ p1_count }} ｜ P2：{{ p2_count }} ｜ P3：{{ p3_count }}

## Executive Summary

{{ executive_summary }}

## P0 / P1 Items

| # | 严重度 | 类别 | 时间 | 摘要（已脱敏） | 建议动作 |
|---|--------|------|------|----------------|----------|
{{ action_item_rows }}

## Trend Analysis

{{ trend_analysis }}

## Recommended Actions

### 立即响应

{{ immediate_actions }}

### 周度跟进

{{ weekly_actions }}

---

*本报告由 `customer_feedback_triage` Skill 生成。原文中的身份信息已按租户策略脱敏，
报告不包含可直接识别的个人数据。*
