---
name: xlsx
displayName: Excel 表格处理
description: "当电子表格文件是主要输入或输出时，随时使用本技能。这涵盖用户希望执行的任何任务：打开、读取、编辑或修复已有的 .xlsx、.xlsm、.csv 或 .tsv 文件（例如添加列、计算公式、设置格式、绘制图表、清理杂乱数据）；从零开始或基于其他数据源创建新的电子表格；或在各种表格文件格式之间转换。当用户按名称或路径引用某个电子表格文件时尤其要触发——即使是随口提及（例如 \"the xlsx in my downloads\"）——并且希望对它做些什么或由它产出些什么。对于把杂乱的表格数据文件（格式错误的行、错位的表头、垃圾数据）清理或重构为规范电子表格的任务，也要触发。交付物必须是一个电子表格文件。当主要交付物是 Word 文档、HTML 报告、独立的 Python 脚本、数据库管道或 Google Sheets API 集成时，不要触发本技能，即使其中涉及表格数据。"
license: Proprietary. LICENSE.txt has complete terms
tools: []
---

# 交付物的要求

## 所有 Excel 文件

### 专业字体
- 除非用户另有指示，否则所有交付物都应使用一致、专业的字体（例如 Arial、Times New Roman）

### 公式零错误
- 每一个 Excel 模型交付时都必须做到公式零错误（#REF!、#DIV/0!、#VALUE!、#N/A、#NAME?）

### 保留已有模板（在更新模板时）
- 修改文件时，必须研究并**完全**匹配现有的格式、样式与约定
- 绝不把标准化格式强加于已有既定模式的文件
- 现有模板的约定**始终**优先于本指南

## 财务模型

### 颜色编码标准
除非用户或现有模板另有说明

#### 行业标准颜色约定
- **Blue text（蓝色文字）（RGB: 0,0,255）**：硬编码的输入值，以及用户会针对不同情景修改的数字
- **Black text（黑色文字）（RGB: 0,0,0）**：所有公式与计算
- **Green text（绿色文字）（RGB: 0,128,0）**：同一工作簿内引用其他工作表的链接
- **Red text（红色文字）（RGB: 255,0,0）**：指向其他文件的外部链接
- **Yellow background（黄色背景）（RGB: 255,255,0）**：需要关注的关键假设，或需要更新的单元格

### 数字格式标准

#### 必需的格式规则
- **年份**：格式化为文本字符串（例如 "2024" 而非 "2,024"）
- **货币**：使用 $#,##0 格式；**始终**在表头中注明单位（"Revenue ($mm)"）
- **零值**：使用数字格式让所有零显示为 "-"，包括百分比（例如 "$#,##0;($#,##0);-"）
- **百分比**：默认使用 0.0% 格式（一位小数）
- **倍数**：估值倍数（EV/EBITDA、P/E）格式化为 0.0x
- **负数**：使用括号 (123)，而非负号 -123

### 公式构建规则

#### 假设的放置
- 把所有假设（增长率、利润率、倍数等）放在独立的假设单元格中
- 公式中使用单元格引用，而不是硬编码的值
- 示例：使用 =B5*(1+$B$6) 而不是 =B5*1.05

#### 公式错误预防
- 核实所有单元格引用都正确
- 检查区域范围是否存在差一错误
- 确保所有预测期间的公式保持一致
- 用边界情况测试（零值、负数）
- 核实没有意外的循环引用

#### 硬编码值的文档要求
- 在注释中或紧邻的单元格中（若在表格末尾）标明。格式："Source: [System/Document], [Date], [Specific Reference], [URL if applicable]"
- 示例：
  - "Source: Company 10-K, FY2024, Page 45, Revenue Note, [SEC EDGAR URL]"
  - "Source: Company 10-Q, Q2 2025, Exhibit 99.1, [SEC EDGAR URL]"
  - "Source: Bloomberg Terminal, 8/15/2025, AAPL US Equity"
  - "Source: FactSet, 8/20/2025, Consensus Estimates Screen"

# XLSX 的创建、编辑与分析

## 概述

用户可能要求你创建、编辑或分析 .xlsx 文件的内容。针对不同任务，可选用不同的工具与工作流。

## 重要要求

**重新计算公式需要 LibreOffice**：可以假定已安装 LibreOffice，用于通过 `scripts/recalc.py` 脚本重新计算公式值。该脚本会在首次运行时自动配置 LibreOffice，包括在 Unix socket 受限的沙箱环境中也是如此（由 `scripts/office/soffice.py` 处理）

## 读取与分析数据

### 使用 pandas 做数据分析
对于数据分析、可视化与基础操作，使用 **pandas**，它提供强大的数据处理能力：

```python
import pandas as pd

# Read Excel
df = pd.read_excel('file.xlsx')  # Default: first sheet
all_sheets = pd.read_excel('file.xlsx', sheet_name=None)  # All sheets as dict

# Analyze
df.head()      # Preview data
df.info()      # Column info
df.describe()  # Statistics

# Write Excel
df.to_excel('output.xlsx', index=False)
```

## Excel 文件工作流

## 关键：使用公式，而非硬编码值

**始终使用 Excel 公式，而不是在 Python 中计算数值再硬编码写入。** 这样才能保证电子表格保持动态、可更新。

### ❌ 错误做法 - 硬编码计算出的数值
```python
# Bad: Calculating in Python and hardcoding result
total = df['Sales'].sum()
sheet['B10'] = total  # Hardcodes 5000

# Bad: Computing growth rate in Python
growth = (df.iloc[-1]['Revenue'] - df.iloc[0]['Revenue']) / df.iloc[0]['Revenue']
sheet['C5'] = growth  # Hardcodes 0.15

# Bad: Python calculation for average
avg = sum(values) / len(values)
sheet['D20'] = avg  # Hardcodes 42.5
```

### ✅ 正确做法 - 使用 Excel 公式
```python
# Good: Let Excel calculate the sum
sheet['B10'] = '=SUM(B2:B9)'

# Good: Growth rate as Excel formula
sheet['C5'] = '=(C4-C2)/C2'

# Good: Average using Excel function
sheet['D20'] = '=AVERAGE(D2:D19)'
```

这适用于所有计算——合计、百分比、比率、差值等。当源数据发生变化时，电子表格应能重新计算。

## 通用工作流
1. **选择工具**：数据处理用 pandas，公式/格式用 openpyxl
2. **创建/加载**：创建新工作簿或加载已有文件
3. **修改**：添加/编辑数据、公式与格式
4. **保存**：写入文件
5. **重新计算公式（使用公式时强制要求）**：使用 scripts/recalc.py 脚本
   ```bash
   python scripts/recalc.py output.xlsx
   ```
6. **核实并修复任何错误**：
   - 脚本会返回带错误详情的 JSON
   - 如果 `status` 为 `errors_found`，检查 `error_summary` 以了解具体的错误类型与位置
   - 修复识别出的错误并再次重新计算
   - 需要修复的常见错误：
     - `#REF!`：无效的单元格引用
     - `#DIV/0!`：除零错误
     - `#VALUE!`：公式中的数据类型错误
     - `#NAME?`：无法识别的公式名称

### 创建新的 Excel 文件

```python
# Using openpyxl for formulas and formatting
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment

wb = Workbook()
sheet = wb.active

# Add data
sheet['A1'] = 'Hello'
sheet['B1'] = 'World'
sheet.append(['Row', 'of', 'data'])

# Add formula
sheet['B2'] = '=SUM(A1:A10)'

# Formatting
sheet['A1'].font = Font(bold=True, color='FF0000')
sheet['A1'].fill = PatternFill('solid', start_color='FFFF00')
sheet['A1'].alignment = Alignment(horizontal='center')

# Column width
sheet.column_dimensions['A'].width = 20

wb.save('output.xlsx')
```

### 编辑已有的 Excel 文件

```python
# Using openpyxl to preserve formulas and formatting
from openpyxl import load_workbook

# Load existing file
wb = load_workbook('existing.xlsx')
sheet = wb.active  # or wb['SheetName'] for specific sheet

# Working with multiple sheets
for sheet_name in wb.sheetnames:
    sheet = wb[sheet_name]
    print(f"Sheet: {sheet_name}")

# Modify cells
sheet['A1'] = 'New Value'
sheet.insert_rows(2)  # Insert row at position 2
sheet.delete_cols(3)  # Delete column 3

# Add new sheet
new_sheet = wb.create_sheet('NewSheet')
new_sheet['A1'] = 'Data'

wb.save('modified.xlsx')
```

## 重新计算公式

由 openpyxl 创建或修改的 Excel 文件，其中的公式只是字符串，并没有计算出的值。使用提供的 `scripts/recalc.py` 脚本重新计算公式：

```bash
python scripts/recalc.py <excel_file> [timeout_seconds]
```

示例：
```bash
python scripts/recalc.py output.xlsx 30
```

该脚本会：
- 在首次运行时自动安装 LibreOffice 宏
- 重新计算所有工作表中的所有公式
- 扫描**所有**单元格以查找 Excel 错误（#REF!、#DIV/0! 等）
- 返回带详细错误位置与计数的 JSON
- 同时支持 Linux 与 macOS

## 公式验证清单

用于确保公式正常工作的快速检查：

### 必要验证
- [ ] **测试 2-3 个样本引用**：在构建完整模型之前，先核实它们能取到正确的值
- [ ] **列映射**：确认 Excel 列匹配（例如第 64 列是 BL，而不是 BK）
- [ ] **行偏移**：记住 Excel 行是从 1 开始编号的（DataFrame 的第 5 行 = Excel 的第 6 行）

### 常见陷阱
- [ ] **NaN 处理**：用 `pd.notna()` 检查空值
- [ ] **最右侧的列**：财年数据往往在第 50 列以后
- [ ] **多重匹配**：搜索所有出现位置，而不只是第一处
- [ ] **除零**：在公式中使用 `/` 之前先检查分母（#DIV/0!）
- [ ] **错误引用**：核实所有单元格引用都指向预期的单元格（#REF!）
- [ ] **跨表引用**：链接工作表时使用正确格式（Sheet1!A1）

### 公式测试策略
- [ ] **从小处着手**：先在 2-3 个单元格上测试公式，再大范围应用
- [ ] **核实依赖项**：检查公式中引用的所有单元格都存在
- [ ] **测试边界情况**：包含零、负数与极大的数值

### 解读 scripts/recalc.py 的输出
该脚本会返回带错误详情的 JSON：
```json
{
  "status": "success",           // or "errors_found"
  "total_errors": 0,              // Total error count
  "total_formulas": 42,           // Number of formulas in file
  "error_summary": {              // Only present if errors found
    "#REF!": {
      "count": 2,
      "locations": ["Sheet1!B5", "Sheet1!C10"]
    }
  }
}
```

## 最佳实践

### 库的选择
- **pandas**：最适合数据分析、批量操作与简单的数据导出
- **openpyxl**：最适合复杂格式、公式以及 Excel 特有功能

### 使用 openpyxl
- 单元格索引从 1 开始（row=1, column=1 指单元格 A1）
- 使用 `data_only=True` 读取计算出的值：`load_workbook('file.xlsx', data_only=True)`
- **警告**：如果用 `data_only=True` 打开后保存，公式会被值替换并永久丢失
- 对于大文件：读取时使用 `read_only=True`，写入时使用 `write_only=True`
- 公式会被保留但不会被求值——使用 scripts/recalc.py 更新值

### 使用 pandas
- 指定数据类型以避免推断问题：`pd.read_excel('file.xlsx', dtype={'id': str})`
- 对于大文件，只读取特定列：`pd.read_excel('file.xlsx', usecols=['A', 'C', 'E'])`
- 正确处理日期：`pd.read_excel('file.xlsx', parse_dates=['date_column'])`

## 代码风格指引
**重要**：为 Excel 操作生成 Python 代码时：
- 编写最小、简洁的 Python 代码，不要有多余的注释
- 避免冗长的变量名与冗余操作
- 避免不必要的 print 语句

**对于 Excel 文件本身**：
- 为含复杂公式或重要假设的单元格添加注释
- 为硬编码的值记录数据来源
- 为关键计算与模型区块添加说明
