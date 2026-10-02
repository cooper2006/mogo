name: research
displayName: 通用调研
version: 1.0.0
description: 通用调研技能，联网检索并归纳事实，产出带来源的报告。
inputs:
  - topic
  - output_spec（可选）
outputs:
  - report.md
tools:
  - search_web
when_to_use:
  - intent == "research"
steps:
  - collect_sources
  - summarize_findings
  - compose_report
validation:
  required_sections:
    - Summary
    - Sources
resources:
  - templates/report.md
  - validation.yaml
