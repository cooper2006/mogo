from __future__ import annotations


DEFAULT_SHORTCUT_ENTRIES = [
    ("content.wechat", "content", "内容生成", "微信/小红书", "newspaper", "帮我生成一篇适合微信或小红书发布的内容，主题是：{主题}。要求标题有吸引力，正文有场景、有痛点、有解决方案，并给出3个标题备选。"),
    ("content.report", "content", "内容生成", "报告方案", "document", "帮我生成一份{主题}报告方案，包含背景、现状、核心问题、原因分析、解决建议和执行计划。"),
    ("content.ppt", "content", "内容生成", "PPT生成", "easel", "帮我生成一份{主题}汇报PPT大纲，适合给管理层展示，控制在12页以内，每页包含标题、要点和可视化建议。"),
    ("content.image_prd", "content", "内容生成", "图片转PRD", "image", "我会上传产品截图，请根据界面内容整理一份PRD，包含页面目标、功能说明、交互规则、字段说明和验收标准。"),
    ("content.translate", "content", "内容生成", "文档翻译", "language", "我会上传一份文档，请翻译成中文，并保留原有结构、标题层级、表格和关键术语。"),
    ("content.fill_form", "content", "内容生成", "文档填表", "grid", "我会上传文档和表格模板，请根据文档内容提取信息并填入表格，缺失字段请标记为“待补充”。"),
    ("external.web", "external", "外部搜索", "联网查资料", "search", "请帮我联网搜索{主题}的最新公开资料，整理来源、核心观点、关键数据和风险提示。"),
    ("external.industry", "external", "外部搜索", "行业研究", "earth", "请围绕{行业/主题}做一份行业研究，包含市场趋势、主要玩家、关键数据、机会和风险。"),
    ("external.competitor", "external", "外部搜索", "竞品分析", "analytics", "请帮我调研{竞品/领域}，对比产品定位、核心功能、价格策略、优劣势和可借鉴点。"),
    ("external.policy_news", "external", "外部搜索", "政策/新闻", "shield", "请搜索{主题}相关的最新政策或新闻，按时间线整理，并说明对业务可能产生的影响。"),
    ("external.overview", "external", "外部搜索", "资料综述", "albums", "请收集并综述{主题}的公开资料，按观点分类，标注来源，并给出结论摘要。"),
    ("external.fact_check", "external", "外部搜索", "事实核查", "stats", "请联网核查以下说法是否准确：{待核查内容}。请给出依据、可信度和不确定点。"),
    ("internal.search", "internal", "内部知识", "搜知识库", "qa", "请在内部知识库中搜索和{主题}相关的资料，整理成背景、关键事实、可引用观点和待确认问题。"),
    ("internal.history", "internal", "内部知识", "查历史文档", "files", "请检索历史文档中与{主题}相关的内容，按文档来源、核心结论和可复用材料整理。"),
    ("internal.policy", "internal", "内部知识", "查企业制度", "briefcase", "请查询企业制度中关于{主题}的规定，整理适用范围、关键要求、注意事项和执行建议。"),
    ("internal.project", "internal", "内部知识", "查项目资料", "albums", "请检索项目资料中与{项目/客户/主题}相关的信息，整理项目背景、进展、问题和下一步建议。"),
    ("internal.customer", "internal", "内部知识", "查客户资料", "people", "请查询客户资料中关于{客户名称/客户群体}的信息，整理客户背景、历史沟通、需求和风险点。"),
    ("internal.training", "internal", "内部知识", "查培训材料", "document", "请检索培训材料中与{主题}相关的内容，整理成学习提纲、关键概念和实践要点。"),
    ("systems.sales", "systems", "连接系统", "查销售", "cart", "请查询本周销售情况，按门店、品类、销售额、订单量、转化率汇总，并指出异常波动。"),
    ("systems.root_cause", "systems", "连接系统", "找根因", "analytics", "请根据最近30天销售数据，分析销售下滑的主要原因，区分流量、转化率、客单价、库存、活动和价格因素。"),
    ("systems.inventory", "systems", "连接系统", "查库存", "files", "请查询当前库存和近7天销量，识别即将缺货、库存积压和需要补货的商品。"),
    ("systems.customer", "systems", "连接系统", "查客户", "people", "请查询最近30天客户增长、复购、流失情况，并找出需要重点运营的人群。"),
    ("systems.daily", "systems", "连接系统", "经营日报", "document", "请生成今日经营日报，包含销售、订单、客户、库存、异常问题和明日建议。"),
    ("systems.mcp", "systems", "连接系统", "调用MCP", "build", "请调用已配置的 MCP 工具完成以下任务：{任务目标}。请先说明会使用哪些工具，再执行并汇总结果。"),
]

CATEGORY_ICON_KEYS = {
    "content": "create",
    "external": "globe",
    "internal": "library",
    "systems": "server",
}


def default_entries() -> list[dict[str, object]]:
    return [
        {
            "id": entry_id,
            "type": "prompt",
            "categoryKey": category_key,
            "categoryLabel": category_label,
            "label": label,
            "iconKey": icon_key,
            "categoryIconKey": CATEGORY_ICON_KEYS.get(category_key, "grid"),
            "iconSvg": "",
            "categoryIconSvg": "",
            "prompt": prompt,
            "resourceId": "",
            "enabled": True,
            "locked": False,
        }
        for entry_id, category_key, category_label, label, icon_key, prompt in DEFAULT_SHORTCUT_ENTRIES
    ]
