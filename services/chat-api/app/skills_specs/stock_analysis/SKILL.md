name: stock_analysis
displayName: 个股分析
version: 1.0.0
description: 单只上市公司的深度分析，含财务数据与风险复核。
inputs:
  - company_name
  - ts_code（可选）
  - output_spec（可选）
outputs:
  - report.md
tools:
  - search_web
  - get_stock_basic_info
  - get_stock_daily
  - get_stock_financial
  - get_stock_forecast
  - get_stock_moneyflow
  - get_top10_holders
  - get_main_business
  - get_report_dates
when_to_use:
  - intent == "stock_analysis"
steps:
  - resolve_company_code
  - fetch_news
  - fetch_financials
  - analyze_trends
  - compose_report
validation:
  required_sections:
    - Conclusion
    - Evidence
    - Risks
  must_include_fields:
    - Data source
    - Date range
resources:
  - templates/report.md
  - scripts/normalize_stock_code.py
  - validation.yaml
