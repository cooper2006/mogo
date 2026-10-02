---
name: docx
displayName: Word 文档处理
description: "创建、编辑与分析专业文档（.docx），支持修订留痕、批注、格式保留与文本提取。当需要处理专业文档（.docx 文件）以完成以下任务时使用：(1) 创建新文档，(2) 修改或编辑内容，(3) 处理修订留痕，(4) 添加批注，或其他任何文档任务"
license: Proprietary. LICENSE.txt has complete terms
---

# DOCX 文档的创建、编辑与分析

## 概述

用户可能要求你创建、编辑或分析 .docx 文件的内容。.docx 文件本质上是一个 ZIP 归档，内部包含 XML 文件及其他资源，可直接读取或编辑。针对不同任务，可选用不同的工具与工作流。

## 工作流决策树

### 读取/分析内容
使用下文「文本提取」或「原始 XML 访问」章节

### 创建新文档
使用「创建新的 Word 文档」工作流

### 编辑已有文档
- **自己的文档 + 简单修改**
  使用「基础 OOXML 编辑」工作流

- **他人的文档**
  使用 **「修订留痕工作流」**（推荐的默认做法）

- **法律、学术、商务或政府文档**
  使用 **「修订留痕工作流」**（必须）

## 读取与分析内容

### 文本提取
如果只需读取文档的文本内容，应使用 pandoc 把文档转换为 markdown。Pandoc 能很好地保留文档结构，并可展示修订留痕：

```bash
# Convert document to markdown with tracked changes
pandoc --track-changes=all path-to-file.docx -o output.md
# Options: --track-changes=accept/reject/all
```

### 原始 XML 访问
以下场景需要访问原始 XML：批注、复杂格式、文档结构、内嵌媒体与元数据。遇到这些需求时，需要解包文档并读取其原始 XML 内容。

#### 解包文件
`python ooxml/scripts/unpack.py <office_file> <output_directory>`

#### 关键文件结构
* `word/document.xml` —— 文档主体内容
* `word/comments.xml` —— document.xml 中引用的批注
* `word/media/` —— 内嵌图片与媒体文件
* 修订留痕使用 `<w:ins>`（插入）与 `<w:del>`（删除）标签

## 创建新的 Word 文档

从零创建 Word 文档时，使用 **docx-js**，它允许用 JavaScript/TypeScript 创建 Word 文档。

### 工作流
1. **必做——完整读取文件**：从头到尾完整读取 [`docx-js.md`](docx-js.md)（约 500 行）。**读取该文件时绝不要设置任何范围限制。** 在开始创建文档之前，先读完整个文件，掌握详细语法、关键格式规则与最佳实践。
2. 使用 Document、Paragraph、TextRun 等组件创建 JavaScript/TypeScript 文件（可假定依赖均已安装；若未安装，参见下文依赖章节）
3. 用 Packer.toBuffer() 导出为 .docx

### 渲染 Markdown（项目默认方式）

使用内置渲染器以保留当前项目格式：

```bash
python scripts/render_markdown.py /path/to/report.md output.docx
```

## 编辑已有的 Word 文档

编辑已有 Word 文档时，使用 **Document 库**（一个用于 OOXML 操作的 Python 库）。该库会自动处理基础设施搭建，并提供文档操作方法。对于复杂场景，可通过该库直接访问底层的 DOM。

### 工作流
1. **必做——完整读取文件**：从头到尾完整读取 [`ooxml.md`](ooxml.md)（约 600 行）。**读取该文件时绝不要设置任何范围限制。** 读完全部内容，掌握 Document 库 API 与直接编辑文档文件的 XML 模式。
2. 解包文档：`python ooxml/scripts/unpack.py <office_file> <output_directory>`
3. 使用 Document 库编写并运行 Python 脚本（参见 ooxml.md 的「Document Library」章节）
4. 打包最终文档：`python ooxml/scripts/pack.py <input_directory> <office_file>`

Document 库既为常见操作提供高层方法，也为复杂场景提供直接 DOM 访问。

## 文档评审的修订留痕工作流

该工作流允许先用 markdown 规划完整的修订留痕，再在 OOXML 中落地。**关键**：要做完整的修订留痕，必须系统性地实现全部改动。

**批处理策略**：把相关改动归入每批 3-10 处的批次。这样既能控制调试难度，又能保持效率。每批测试通过后再进入下一批。

**原则：最小化、精确的编辑**
实现修订留痕时，只标记真正发生变化的文本。重复未改动的文本会让修订难以评审，并显得不专业。把替换拆解为：[未改动文本] + [删除] + [插入] + [未改动文本]。对于未改动的文本，从原始内容中取出 `<w:r>` 元素并复用，以保留其原始 RSID。

示例——把句中的 "30 days" 改为 "60 days"：
```python
# BAD - Replaces entire sentence
'<w:del><w:r><w:delText>The term is 30 days.</w:delText></w:r></w:del><w:ins><w:r><w:t>The term is 60 days.</w:t></w:r></w:ins>'

# GOOD - Only marks what changed, preserves original <w:r> for unchanged text
'<w:r w:rsidR="00AB12CD"><w:t>The term is </w:t></w:r><w:del><w:r><w:delText>30</w:delText></w:r></w:del><w:ins><w:r><w:t>60</w:t></w:r></w:ins><w:r w:rsidR="00AB12CD"><w:t> days.</w:t></w:r>'
```

### 修订留痕工作流

1. **获取 markdown 表示**：把文档转换为 markdown，并保留修订留痕：
   ```bash
   pandoc --track-changes=all path-to-file.docx -o current.md
   ```

2. **识别并归类改动**：审阅文档，找出所有需要的改动，并把它们组织成逻辑批次：

   **定位方法**（用于在 XML 中找到改动位置）：
   - 章节/标题编号（如 "Section 3.2"、"Article IV"）
   - 段落标识（如有编号）
   - 带唯一上下文的 grep 模式
   - 文档结构（如「第一段」、「签署栏」）
   - **不要使用 markdown 行号**——它们与 XML 结构不对应

   **批次组织**（每批归入 3-10 处相关改动）：
   - 按章节：「批次 1：第 2 节修订」、「批次 2：第 5 节更新」
   - 按类型：「批次 1：日期更正」、「批次 2：当事方名称变更」
   - 按复杂度：先做简单文本替换，再处理复杂的结构性改动
   - 按顺序：「批次 1：第 1-3 页」、「批次 2：第 4-6 页」

3. **阅读文档并解包**：
   - **必做——完整读取文件**：从头到尾完整读取 [`ooxml.md`](ooxml.md)（约 600 行）。**读取该文件时绝不要设置任何范围限制。** 特别留意「Document Library」与「Tracked Change Patterns」章节。
   - **解包文档**：`python ooxml/scripts/unpack.py <file.docx> <dir>`
   - **记下建议的 RSID**：解包脚本会给出一个用于修订留痕的 RSID 建议值。复制该 RSID，在第 4b 步使用。

4. **分批实现改动**：按逻辑归类（按章节、按类型或按位置邻近）改动，并在同一个脚本中一起实现。这样做：
   - 更易调试（批次越小，越容易定位错误）
   - 支持增量推进
   - 保持效率（每批 3-10 处改动效果最好）

   **建议的批次划分方式：**
   - 按文档章节（如「第 3 节改动」、「定义」、「终止条款」）
   - 按改动类型（如「日期改动」、「当事方名称更新」、「法律术语替换」）
   - 按位置邻近（如「第 1-3 页的改动」、「文档前半部分的改动」）

   对于每一批相关改动：

   **a. 把文本映射到 XML**：在 `word/document.xml` 中 grep 文本，确认文本是如何拆分到多个 `<w:r>` 元素中的。

   **b. 创建并运行脚本**：用 `get_node` 定位节点，实现改动，然后 `doc.save()`。模式参见 ooxml.md 的 **「Document Library」** 章节。

   **注意**：每次写脚本之前都要先 grep `word/document.xml`，以获取当前行号并核实文本内容。每次脚本运行后行号都会变化。

5. **打包文档**：所有批次完成后，把解包目录转回 .docx：
   ```bash
   python ooxml/scripts/pack.py unpacked reviewed-document.docx
   ```

6. **最终验证**：对完整文档做一次全面检查：
   - 把最终文档转换为 markdown：
     ```bash
     pandoc --track-changes=all reviewed-document.docx -o verification.md
     ```
   - 验证所有改动都已正确应用：
     ```bash
     grep "original phrase" verification.md  # Should NOT find it
     grep "replacement phrase" verification.md  # Should find it
     ```
   - 检查是否引入了非预期的改动


## 把文档转换为图片

要对 Word 文档做可视化分析，可用两步流程把它转换为图片：

1. **把 DOCX 转换为 PDF**：
   ```bash
   soffice --headless --convert-to pdf document.docx
   ```

2. **把 PDF 页面转换为 JPEG 图片**：
   ```bash
   pdftoppm -jpeg -r 150 document.pdf page
   ```
   这会生成 `page-1.jpg`、`page-2.jpg` 等文件。

选项：
- `-r 150`：设置分辨率为 150 DPI（在质量与体积之间权衡调整）
- `-jpeg`：输出 JPEG 格式（如偏好 PNG 可用 `-png`）
- `-f N`：起始页（如 `-f 2` 从第 2 页开始）
- `-l N`：结束页（如 `-l 5` 到第 5 页为止）
- `page`：输出文件前缀

指定页面范围的示例：
```bash
pdftoppm -jpeg -r 150 -f 2 -l 5 document.pdf page  # Converts only pages 2-5
```

## 代码风格指引
**重要**：为 DOCX 操作生成代码时：
- 写简洁的代码
- 避免冗长的变量名与冗余操作
- 避免不必要的 print 语句

## 依赖

所需依赖（如缺失请安装）：

- **pandoc**：`sudo apt-get install pandoc`（用于文本提取）
- **docx**：`npm install -g docx`（用于创建新文档）
- **LibreOffice**：`sudo apt-get install libreoffice`（用于 PDF 转换）
- **Poppler**：`sudo apt-get install poppler-utils`（提供 pdftoppm，把 PDF 转为图片）
- **defusedxml**：`pip install defusedxml`（用于安全 XML 解析）
