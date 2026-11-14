---
name: pptx
displayName: PPT 演示文稿
description: "只要涉及 .pptx 文件（无论作为输入、输出还是两者兼有），都应使用本技能。包括：创建幻灯片、路演稿或演示文稿；读取、解析或提取任何 .pptx 文件的文本（即使提取出的内容将用于其他用途，例如写邮件或做摘要）；编辑、修改或更新现有演示文稿；合并或拆分幻灯片文件；处理模板、版式、演讲者备注或批注。只要用户提到 “deck”“slides”“presentation”，或给出某个 .pptx 文件名，无论其后续打算如何使用内容，都请触发本技能。如果需要打开、创建或改动某个 .pptx 文件，就使用本技能。"
license: Proprietary. LICENSE.txt has complete terms
---

# PPTX 技能

## 快速参考

| 任务 | 指南 |
|------|-------|
| 读取/分析内容 | `python -m markitdown presentation.pptx` |
| 基于模板编辑或创建 | 阅读 [editing.md](editing.md) |
| 从零创建 | 阅读 [pptxgenjs.md](pptxgenjs.md) |

---

## 读取内容

```bash
# Text extraction
python -m markitdown presentation.pptx

# Visual overview
python scripts/thumbnail.py presentation.pptx

# Raw XML
python scripts/office/unpack.py presentation.pptx unpacked/
```

---

## 编辑工作流

**完整细节请阅读 [editing.md](editing.md)。**

1. 用 `thumbnail.py` 分析模板
2. 解包 → 操作幻灯片 → 编辑内容 → 清理 → 打包

---

## 从零创建

**完整细节请阅读 [pptxgenjs.md](pptxgenjs.md)。**

在没有可用模板或参考演示文稿时使用。

---

## 设计思路

**不要做乏味的幻灯片。** 白底加普通项目符号无法打动任何人。每一页都可从下面这份清单里找灵感。

### 动手之前

- **选定大胆且贴合内容的配色方案**：配色应当让人感觉是为「这个主题」量身设计的。如果把你的配色换到一份完全不同的演示文稿里依然「说得通」，那说明你的选择还不够具体。
- **主次分明，而非平均分配**：应当有一种颜色占主导（约 60-70% 的视觉比重），搭配 1-2 种辅助色调和一个锐利的强调色。绝不要让所有颜色权重相同。
- **深浅对比**：标题页与结论页用深色背景，内容页用浅色背景（「三明治」结构）。或者全程坚持深色，营造高级感。
- **坚持一种视觉母题**：挑选一个独特的元素并反复使用——圆角图片边框、置于彩色圆圈中的图标、单侧粗边框等。让它贯穿每一页。

### 配色方案

选择与主题相符的颜色——不要默认用通用的蓝色。可参考以下配色方案：

| 主题 | 主色 | 辅色 | 强调色 |
|-------|---------|-----------|--------|
| **Midnight Executive**（午夜高管） | `1E2761`（藏青） | `CADCFC`（冰蓝） | `FFFFFF`（白） |
| **Forest & Moss**（森林苔藓） | `2C5F2D`（森林绿） | `97BC62`（苔藓绿） | `F5F5F5`（奶油白） |
| **Coral Energy**（珊瑚活力） | `F96167`（珊瑚红） | `F9E795`（金） | `2F3C7E`（藏青） |
| **Warm Terracotta**（暖陶土） | `B85042`（陶土红） | `E7E8D1`（沙色） | `A7BEAE`（鼠尾草绿） |
| **Ocean Gradient**（海洋渐变） | `065A82`（深蓝） | `1C7293`（青蓝） | `21295C`（午夜蓝） |
| **Charcoal Minimal**（炭黑极简） | `36454F`（炭灰） | `F2F2F2`（灰白） | `212121`（黑） |
| **Teal Trust**（信赖青绿） | `028090`（青绿） | `00A896`（海沫绿） | `02C39A`（薄荷绿） |
| **Berry & Cream**（莓果奶油） | `6D2E46`（莓果红） | `A26769`（灰玫瑰） | `ECE2D0`（奶油色） |
| **Sage Calm**（鼠尾草静谧） | `84B59F`（鼠尾草绿） | `69A297`（桉树绿） | `50808E`（石板蓝） |
| **Cherry Bold**（樱桃浓烈） | `990011`（樱桃红） | `FCF6F5`（灰白） | `2F3C7E`（藏青） |

### 每一页幻灯片

**每页都需要一个视觉元素**——图片、图表、图标或形状。纯文字的幻灯片很难让人记住。

**版式选项：**
- 两栏（左侧文字，右侧插图）
- 图标 + 文字行（图标置于彩色圆圈中，粗体标题，下方描述）
- 2x2 或 2x3 网格（一侧放图，另一侧放内容区块网格）
- 半出血图片（占满左侧或右侧）叠加内容

**数据呈现：**
- 大号数据强调（60-72pt 的大数字，下方配小号标签）
- 对比列（前后对比、优缺点、并排方案）
- 时间线或流程（带编号的步骤、箭头）

**视觉打磨：**
- 小节标题旁配上置于小彩色圆圈中的图标
- 关键数据或口号使用斜体强调文字

### 字体排版

**选择一组有特色的字体搭配**——不要默认用 Arial。挑一款有个性的标题字体，搭配一款干净的正文字体。

| 标题字体 | 正文字体 |
|-------------|-----------|
| Georgia | Calibri |
| Arial Black | Arial |
| Calibri | Calibri Light |
| Cambria | Calibri |
| Trebuchet MS | Calibri |
| Impact | Arial |
| Palatino | Garamond |
| Consolas | Calibri |

| 元素 | 字号 |
|---------|------|
| 幻灯片标题 | 36-44pt 粗体 |
| 小节标题 | 20-24pt 粗体 |
| 正文 | 14-16pt |
| 图注 | 10-12pt 弱化色 |

### 间距

- 页边距至少 0.5"
- 内容区块之间 0.3-0.5"
- 留出呼吸空间——不要塞满每一寸

### 应避免的做法（常见错误）

- **不要重复同一种版式**——在各页之间变换栏式、卡片和强调块
- **不要把正文居中**——段落和列表左对齐，只有标题居中
- **不要在字号对比上偷懒**——标题需要 36pt 以上，才能与 14-16pt 的正文拉开层次
- **不要默认用蓝色**——挑选能反映具体主题的颜色
- **不要随意混用间距**——选定 0.3" 或 0.5" 的间隔并保持一致
- **不要只精心设计一页而其余粗糙**——要么整份都用心，要么全程保持简洁
- **不要做纯文字幻灯片**——加入图片、图标、图表或视觉元素；避免「标题 + 项目符号」的单调组合
- **不要忘记文本框内边距**——当需要让文字与形状的边界对齐时，把文本框设为 `margin: 0`，或对形状做相应偏移以抵消内边距
- **不要使用低对比度的元素**——图标和文字都需要与背景形成强对比；避免浅色文字配浅色背景，或深色文字配深色背景
- **绝不要在标题下方加装饰线**——这是 AI 生成幻灯片的典型特征；改用留白或背景色

---

## 质检（必做）

**假定一定存在问题。你的任务就是把它们找出来。**

你第一次渲染出来的结果几乎不可能是正确的。要把质检当作一次找 bug 的行动，而不是走过场的确认。如果初次检查一个问题都没发现，那说明你看得还不够仔细。

### 内容质检

```bash
python -m markitdown output.pptx
```

检查是否有缺失内容、拼写错误、顺序错误。

**使用模板时，检查是否残留占位符文本：**

```bash
python -m markitdown output.pptx | grep -iE "xxxx|lorem|ipsum|this.*(page|slide).*layout"
```

如果 grep 有返回结果，先修好再宣布完成。

### 视觉质检

**⚠️ 使用子智能体**——哪怕只有 2-3 页也要用。你盯着代码看了太久，看到的会是你预期的样子，而不是实际的样子。子智能体有一双新眼睛。

把幻灯片转换为图片（参见[转换为图片](#转换为图片)），然后使用这段提示词：

```
Visually inspect these slides. Assume there are issues — find them.

Look for:
- Overlapping elements (text through shapes, lines through words, stacked elements)
- Text overflow or cut off at edges/box boundaries
- Decorative lines positioned for single-line text but title wrapped to two lines
- Source citations or footers colliding with content above
- Elements too close (< 0.3" gaps) or cards/sections nearly touching
- Uneven gaps (large empty area in one place, cramped in another)
- Insufficient margin from slide edges (< 0.5")
- Columns or similar elements not aligned consistently
- Low-contrast text (e.g., light gray text on cream-colored background)
- Low-contrast icons (e.g., dark icons on dark backgrounds without a contrasting circle)
- Text boxes too narrow causing excessive wrapping
- Leftover placeholder content

For each slide, list issues or areas of concern, even if minor.

Read and analyze these images:
1. /path/to/slide-01.jpg (Expected: [brief description])
2. /path/to/slide-02.jpg (Expected: [brief description])

Report ALL issues found, including minor ones.
```

### 验证循环

1. 生成幻灯片 → 转换为图片 → 检查
2. **列出发现的问题**（如果一个都没发现，就用更挑剔的眼光再看一遍）
3. 修复问题
4. **重新验证受影响的幻灯片**——修好一处常常会引出另一个问题
5. 重复以上步骤，直到完整跑一遍不再出现新问题

**在至少完成一轮「修复—验证」循环之前，不要宣布完成。**

---

## 转换为图片

把演示文稿转换为单页幻灯片图片，以便做视觉检查：

```bash
python scripts/office/soffice.py --headless --convert-to pdf output.pptx
pdftoppm -jpeg -r 150 output.pdf slide
```

这会生成 `slide-01.jpg`、`slide-02.jpg` 等文件。

修复后要重新渲染指定幻灯片：

```bash
pdftoppm -jpeg -r 150 -f N -l N output.pdf slide-fixed
```

---

## 依赖

- `pip install "markitdown[pptx]"` - 文本提取
- `pip install Pillow` - 缩略图网格
- `npm install -g pptxgenjs` - 从零创建
- LibreOffice（`soffice`）- PDF 转换（在沙箱环境中通过 `scripts/office/soffice.py` 自动配置）
- Poppler（`pdftoppm`）- PDF 转图片
