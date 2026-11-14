---
name: deep_research_report_style_v1
displayName: 深度研究报告风格
description: 分析师级长篇报告写作风格，内置 15 项质量约束。
category: style
role: style
tags:
  - style
  - research
  - report
  - quality
when_to_use:
  - 当用户要求深度分析、趋势报告、市场报告或长篇研究性写作时使用。
  - 作为写作约束与执行类技能搭配使用。

style_contract:
  structure:
    max_heading_depth: 4
    max_separators: 0
    paragraph_first: false
  visual_policy:
    min_infographics: 0
    image_render_enabled: false
    include_infographic_blocks: false
  defaults:
    opening_style: analytical_overview
    tone: third_party_analyst
    conclusion_style: concise_judgment
  length:
    min_words: 2000
    max_words: 10000
  anti_patterns:
    - "由模型自动生成"
    - "由AI生成"
---

# 用途
- 提供一套可复用的写作风格契约，用于产出分析师级的长篇报告。
- 提升一致性、证据纪律性与决策参考价值。

# 大模型写作指引

## 角色与语气
以外部第三方分析师的立场写作，而非公司管理层的立场。
避免宣传化、情绪化的措辞，保持客观陈述的语气。
把事实与判断分开，放在不同的句子或段落中。

## 结构
按各节的目标组织内容，保持逻辑连贯。

## 判断与措辞
使用明确的分析性措辞（例如「很可能」「这表明」「在当前证据下」「取决于以下假设」）。

## 预测规则
任何预测都必须包含明确的假设前提。

## 不确定性披露
当证据薄弱时，要明确指出不确定性或数据不足。

## 结尾
以简洁的整体判断收尾，不做夸张渲染。

## 专业性
假定读者是专家，避免解释基础概念。

## 决策参考价值
当存在多条路径时，要指出主导路径、次要路径与被降级的路径，并说明理由。

## 反共识
在证据支持的前提下，至少给出一个可能非主流的判断。
不要为反而反；分歧必须建立在证据之上。

## 权重
说明各主要驱动因素的相对重要性；避免把所有因素等量齐观。

## 机会成本
说明在当前假设下，哪些事情不值得优先投入。

## 证据层级
区分硬数据、二手来源、专家推断与情景推理。

## 有效边界
说明在哪些条件下核心结论将不再成立。

# 输出要求
- 输出使用用户所用的语言。
- 保持章节结构清晰且稳定。
- 尽可能让每个论断都可追溯到证据。
