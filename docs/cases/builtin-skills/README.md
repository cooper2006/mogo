# 内置技能 ZIP 包（汉化版）

本目录存放 15 个内置技能中可打包的 14 个 ZIP，全部已汉化，可直接通过技能包安装流程导入。

- **导出时间**：2026-10-01
- **打包脚本**：`docs/cases/build_builtin_skill_zips.py`
- **源目录**：`services/chat-api/app/skills_specs/`
- **重新导出**：`services/chat-api/venv/bin/python docs/cases/build_builtin_skill_zips.py`

## 一次性导入（推荐）

`mogo-builtin-skills-1.0.0.zip` 把全部 14 个技能打包成**一个可导入的专家包**，上传一次即可。

```bash
services/chat-api/venv/bin/python docs/cases/build_builtin_expert_package.py
```

| 项 | 值 |
|---|---|
| 文件 | `mogo-builtin-skills-1.0.0.zip`（394KB） |
| 格式 | 专家包（`skillhub-expert-package`，`package_kind=expert_package`） |
| name / displayName | `mogo-builtin-skills` / 内置技能合集 |
| 子技能 | 14 个 |
| 展开文件数 | 192（上限 256） |
| 合体指令 | 55725 字节（上限 100000） |
| archive_digest | `4e460db419b53bf0297d5ab80fd48797690767eeb284dfd1077220ed733c1b0d` |

### 导入后是什么样

**技能列表里是 1 条**（名为「内置技能合集」），不是 14 条。这是运行时专家包的固有语义：`installer.py:153` 一次安装只 `insert_one` 一条记录，14 个子技能存在该记录的 `package_children` 元数据里（`skills.py:541` 不展开成独立列表项），`category` 为 `Imported Expert Package`。

使用能力不受影响：合体指令把 14 个子技能的完整正文逐字嵌入（14/14 验证通过），模型可直接调用全部能力，各子技能的资源文件在 `children/<slug>/` 下（如 `children/docx/ooxml.md`、`children/pptx/pptxgenjs.md`）。

### 与逐个导入的区别

| | 合并包 | 14 个独立 ZIP |
|---|---|---|
| 导入次数 | 1 | 14 |
| 技能列表条目 | 1 条（合集） | 14 条（各自独立） |
| 单独启用/停用 | 不支持 | 支持 |
| 适用场景 | 想一次装齐 | 想按需挑选、独立开关 |

两者可共存，按需选用。

### 已排除的文件

`docx`、`pptx`、`xlsx` 各带 39 个 `.xsd`（`ISO-IEC29500-4_2016`/`ecma`/`mce`/`microsoft` 的 OOXML 校验 schema），共 117 个，已从合并包中排除。

原因：专家包会把子技能展开到 `children/<slug>/...`，总文件数上限 256（`expert_validator.py:163`）；带 schema 时展开数为 309，直接超限。

代价：`ooxml/scripts/validate.py` 与 `scripts/office/validate.py` 的 XSD 校验在合并包内不可用。**三个技能的 SKILL.md 正文都没有让模型运行这些脚本** —— docx 走 `ooxml/scripts/{unpack,pack}.py`，pptx 的「校验循环」是渲染成图后目视比对，xlsx 用 `scripts/recalc.py` 重算。需要完整 XSD 校验时请改用单独的 `docx-1.0.0.zip` / `pptx-1.0.0.zip` / `xlsx-1.0.0.zip`。

加 `--keep-schemas` 会保留它们，但构建会以 `too_many_files` 失败（这是预期行为，脚本会在写盘前中止，不会破坏已有产物）。

## 说明

- `customer_feedback_triage` **不在本目录**，它由 `docs/cases/build_skill_zip.py` 单独打包，因此合并包里也不含它。
- 技能的 `name` 始终保持 kebab-case（安装 slug、目录名、Python 导入路径依赖它）；界面显示名取自 frontmatter 的 `displayName`，已全部中文化。

## 包清单

| ZIP | name（kebab） | displayName（界面显示） | description 摘要 |
|---|---|---|---|
| `blog-article-style-v1-1.0.0.zip` | `blog-article-style-v1` | 博客与公众号文章风格 | 博客与微信公众号文章的写作风格 |
| `deep-research-report-style-v1-1.0.0.zip` | `deep-research-report-style-v1` | 深度研究报告风格 | 分析师级长篇报告的写作风格 |
| `docx-1.0.0.zip` | `docx` | Word 文档处理 | 专业文档的创建、编辑与分析 |
| `financial-analysis-v1-1.0.0.zip` | `financial-analysis-v1` | 财务分析 | 对上市公司竞争对手做量化财务分析与估值 |
| `market-intelligence-v1-1.0.0.zip` | `market-intelligence-v1` | 市场情报 | 采集某公司的市场情报 |
| `pdf-1.0.0.zip` | `pdf` | PDF 处理 | 全套 PDF 处理工具包 |
| `pptx-1.0.0.zip` | `pptx` | PPT 演示文稿 | 演示文稿的创建、读取、编辑与质检 |
| `product-analysis-v1-1.0.0.zip` | `product-analysis-v1` | 产品分析 | 分析竞品——功能清单、定位与能力差距 |
| `report-synthesis-v1-1.0.0.zip` | `report-synthesis-v1` | 研究报告综合 | 把上游子智能体产出综合成分析师级研究报告 |
| `research-1.0.0.zip` | `research` | 通用调研 | 联网检索、归纳事实并产出带来源的报告 |
| `sentiment-monitor-v1-1.0.0.zip` | `sentiment-monitor-v1` | 舆情监测 | 针对竞争对手做社媒舆情监测与话题聚类 |
| `stock-analysis-1.0.0.zip` | `stock-analysis` | 个股分析 | 单只上市公司的深度分析与风险复核 |
| `theme-factory-1.0.0.zip` | `theme-factory` | 主题工厂 | 为交付物套用主题样式的工具包 |
| `xlsx-1.0.0.zip` | `xlsx` | Excel 表格处理 | Excel 文件的创建、编辑与分析 |

## 校验

14 个 ZIP 均通过项目自带的技能包校验器 `app.services.skill_packages.validator.validate_skill_zip`：

```
VALID  blog-article-style-v1-1.0.0.zip            name=blog-article-style-v1            display_name=博客与公众号文章风格
VALID  deep-research-report-style-v1-1.0.0.zip    name=deep-research-report-style-v1    display_name=深度研究报告风格
VALID  docx-1.0.0.zip                             name=docx                             display_name=Word 文档处理
VALID  financial-analysis-v1-1.0.0.zip            name=financial-analysis-v1            display_name=财务分析
VALID  market-intelligence-v1-1.0.0.zip           name=market-intelligence-v1           display_name=市场情报
VALID  pdf-1.0.0.zip                              name=pdf                              display_name=PDF 处理
VALID  pptx-1.0.0.zip                             name=pptx                             display_name=PPT 演示文稿
VALID  product-analysis-v1-1.0.0.zip              name=product-analysis-v1              display_name=产品分析
VALID  report-synthesis-v1-1.0.0.zip              name=report-synthesis-v1              display_name=研究报告综合
VALID  research-1.0.0.zip                         name=research                         display_name=通用调研
VALID  sentiment-monitor-v1-1.0.0.zip             name=sentiment-monitor-v1             display_name=舆情监测
VALID  stock-analysis-1.0.0.zip                   name=stock-analysis                   display_name=个股分析
VALID  theme-factory-1.0.0.zip                    name=theme-factory                    display_name=主题工厂
VALID  xlsx-1.0.0.zip                             name=xlsx                             display_name=Excel 表格处理
```

## 汉化范围

- **已汉化**：`displayName`（界面显示名）、`description`、`whenToUse` / `when_to_use`、技能正文的标题与说明文字。
- **保持原文**（刻意的，非遗漏）：
  - 代码块、命令行、库名与 API 名（`openpyxl`、`markitdown`、`LibreOffice`、`#REF!` 等错误码）
  - 参考文档文件名（`docx-js.md`、`ooxml.md`、`pptxgenjs.md`、`themes/*.md`）
  - DAG 编排用的步骤标识符（`load_feedback`、`compose_report` 等，与 frontmatter `steps:` 一致）
  - `validation.required_sections` / `must_include_fields` 里的产物结构契约名，以及 `templates/*.md` 中对应的区块标题——它们与 Python 生成逻辑（如 `app/cases/customer_feedback_triage.py:616`）及测试断言（`tests/cases/test_customer_feedback_triage.py:344`）共享，汉化会造成文档与实现不一致
  - `pdf` 技能里的 `pdftotext（poppler-utils）`、`qpdf` 等工具名
