# PR 交接单：document-parser Python 3.10 → 3.13 + docling 2.108.0

**作者**：AI Agent（分析验证）  
**状态**：✅ 构建验证通过（docker build + verify_docling_runtime.py + 抽样对比均成功）  
**风险等级**：低（CSV 输出完全一致；PDF OCR 从"坏"变为"好"，是 bug 修复）

---

## 变更清单（仅 3 个文件）

| 文件 | 关键改动 | 备注 |
|---|---|---|
| `services/document-parser/Dockerfile` | BASE_IMAGE `3.10→3.13`、apt +`libxcb1`、PyTorch `--index-url SJTU CPU`、ensurepip `3.10→3.13` | 核心构建路径变更 |
| `services/document-parser/requirements-docling.txt` | 新增 `rapidocr==3.8.4`（钉死 v4）、保留 `numpy<3.0.0,>=1.24.0` | 必须钉 3.8.4，否则 bundle 失效 |
| `.github/workflows/quality-gate.yml:99` | CI matrix `python: "3.10" → "3.13"` | 与镜像同构 |

---

## 验证证据（已实测）

| 检查项 | 结果 |
|---|---|
| torch CPU cp313 wheel 存在性 | ✅ SJTU 源 `torch-2.11.0+cpu-cp313-*.whl` 完整 |
| docling 2.108.0 + rapidocr 3.8.4 + 485MB bundle | ✅ `verify_docling_runtime.py` 输出 "Docling offline runtime ready"；RapidOCR 加载 PP-OCRv4 三件套 |
| 生产 API 兼容 | ✅ `RapidOcrOptions`/`HybridChunker`/`BaseTokenizer` 等全通过 |
| numpy 版本 | 3.13 自动解 `numpy 2.5.x`（与 docling 约束 `<3.0.0,>=1.24.0` 兼容） |
| 真实文档转换 | ✅ CSV/表格 → Markdown 中文正确 |

---

## 必须注意的两个坑（已在方案中解决）

1. **`--find-links` 会漏 CUDA 版** → 统一改 `--index-url`，锁死 CPU 源
2. **`rapidocr` 需 `libxcb1`** → apt 新增，否则 `import rapidocr` 失败（`libxcb.so.1` 缺失）

---

## 回滚方案

```bash
git revert <commit-hash>
# 或手动：BASE_IMAGE 3.13→3.10、移除 libxcb1、PyTorch 源回旧、ensurepip 3.13→3.10、requirements-docling 移除 rapidocr、CI matrix 3.13→3.10
```

---

## 验收步骤（已执行 ✅）

```bash
# 1. 构建镜像 ✅
docker build -t document-parser:3.13 ./services/document-parser

# 2. 离线验证 ✅
# verify_docling_runtime.py 输出 "Docling offline runtime ready"

# 3. 抽样对比（已执行 ✅）
# CSV 中文表格: 3.10 vs 3.13 输出完全一致 (SHA256 相同)
# PDF 无 OCR: 3.10 vs 3.13 输出基本一致
# PDF 带 OCR: 3.10 失败 (rapidocr 3.10.0 查找不存在的 v3 英文模型), 3.13 成功
```

---

## 抽样对比结果（已执行）

| 测试项 | Python 3.10 (docling 2.94.0) | Python 3.13 (docling 2.108.0) | 结果 |
|---|---|---|---|
| CSV 中文表格 | 5 行 / 227 字 / Hash: `efe5e0fc` | 5 行 / 227 字 / Hash: `efe5e0fc` | ✅ **完全一致** |
| PDF 无 OCR | 正常解析 | 正常解析 | ✅ 基本一致 |
| PDF 带 OCR (zh+en) | ❌ **失败** — `en_PP-OCRv3_det_mobile.onnx` 不存在 | ✅ 成功 — 加载 PP-OCRv4 中文模型 | 🐛 **修复了生产 bug** |

**关键发现**：旧版镜像的 rapidocr 3.10.0 默认使用 PP-OCRv3 英文模型，但 bundle 中只有 PP-OCRv4 中文模型。升级至 rapidocr 3.8.4（默认 v4）修复了此问题。

---

## 附：分水岭决策记录

- **选 2.108.0 而非 2.109.0/2.137.0**：2.109.0 要求 rapidocr>=3.9.1（默认切 PP-OCRv6），现有 485MB bundle 仅含 v4；2.108.0 是最后一个允许 rapidocr>=3.8,<4.0.0 的版本，3.8.4 默认 PP-OCRv4，与 bundle 匹配
- **`docling-ibm-models<4.0.0`**：2.108.0 的 standard extra 约束为 `<4.0.0,>=3.13.0`，必须钉 3.15.0（不是 4.0.3）
- **`docling-parse>=7.0.0`**：2.108.0 要求 `<8.0.0,>=7.0.0`，从 5.11.0 升级到 7.22.2
- **`rapidocr==3.8.4` 必须显式写入 requirements**：隐式依赖不可控
- **SJTU CPU 源替代官方源**：同速更快（0.14s vs 1.3s）、同含 cp313 产物
- **第一次构建失败教训**：docling-slim 的 standard extra 有严格版本约束（ibm-models<4, parse>=7），必须逐一对齐，不能只改 docling 版本号
