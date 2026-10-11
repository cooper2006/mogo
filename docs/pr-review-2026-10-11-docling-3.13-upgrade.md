# PR 交接单：document-parser Python 3.10 → 3.13 + docling 2.109.0

**作者**：AI Agent（分析验证）  
**状态**：等待人工评审与 `git add` 提交  
**风险等级**：中（需抽样对比 OCR 输出）

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
| docling 2.109.0 + rapidocr 3.8.4 + 485MB bundle | ✅ `StandardPdfPipeline(backend=onnxruntime)` 装配成功 |
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

## 验收步骤（提交后）

```bash
# 1. 构建镜像
docker build -t document-parser:3.13 ./services/document-parser

# 2. 离线验证
docker run --rm -v $PWD/services/document-parser/docling-models-bundle.tar.gz:/models.tar.gz document-parser:3.13 \
  bash -c "tar -xzf /models.tar.gz -C /opt/docling/models && python -m scripts.verify_docling_runtime"
# 预期: Docling offline runtime ready: /opt/docling/models

# 3. 抽样对比（关键）
# - 同一份扫描 PDF → 3.10 容器 / 3.13 容器分别转换
# - diff 输出 markdown，重点看表格/OCR 区域
```

---

## 附：分水岭决策记录

- **选 2.109.0 而非 2.137.0**：`rapidocr 3.8.4` (v4) vs `3.9.0+` (v6)；现有 bundle 仅含 v4，重建成本 485MB + 验收期
- **`rapidocr==3.8.4` 必须显式写入 requirements**：隐式依赖不可控
- **SJTU CPU 源替代官方源**：同速更快（0.14s vs 1.3s）、同含 cp313 产物
