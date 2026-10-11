# Quickstart: Multimodal Document Ingestion & Content Delivery (003)

**Feature**: [spec.md](./spec.md) | [plan.md](./plan.md)

本文件说明如何**启用并验证**多格式文档解析入库、引用追溯、Office 预览转换与内容交付物生成。

---

## 1. 前置

- `services/document-parser` 已部署（Celery + Redis + MongoDB）
- `services/chat-api` 已部署（内容生成流水线）
- Docling 运行时已安装（`requirements-docling.txt`，Pin 版本见 plan.md）
- LibreOffice 可用（Office → PDF 预览转换，需中文字体）

---

## 2. 多格式文档上传解析

上传入口（`POST /api/documents/upload`），支持 PDF/DOCX/XLSX/PPTX/CSV/TXT/MD/JSON/图片。

```python
from app.enterprise_capabilities.document.parser_service import ParserService

result = await ParserService.parse(
    file_bytes=b"...",
    filename="report.pdf",
    tenant_id="t1",
)
# result.markdown → 结构化 Markdown（保留表格）
# result.anchors → 页码/表行/段落锚点
```

**验证**：上传含表格与图片的 PDF → 解析产物保留表格结构，图片走 OCR/多模态通道。

---

## 3. 引用可追溯

检索命中片段附带 source anchor，回答中引用可回链原文档位置。

```python
from app.knowledge.citations.citation_resolver import resolve_citations

citations = resolve_citations(
    chunk_ids=["chunk-1", "chunk-2"],
    document_ids=["doc-1", "doc-2"],
)
# citations[0].anchor → 页码或表格行锚点
# citations[0].source_uri → mogo://resource/doc/<tenant>/<docId>/<chunkId>
```

**验证**：检索返回片段 → 附带 source anchor；Agent 生成报告引用 → 引用可回链原文档位置。

---

## 4. Office 预览转换

```python
from app.enterprise_capabilities.document.preview_service import PreviewService

result = await PreviewService.convert_to_pdf(
    file_id="doc-123",
    tenant_id="t1",
)
# result.pdf_url → 预览 PDF 对象存储 URL
# result.status → "success" | "failed"
```

**验证**：上传 DOCX/PPTX → 异步生成预览 PDF，成功后管理面收到元数据回调；LibreOffice 缺失 → 报明确依赖错误。

---

## 5. 内容交付物生成

```python
from app.enterprise_capabilities.content.writer_engine import WriterEngine

artifact = await WriterEngine.generate(
    spec={"format": "pptx", "sections": [...]},
    tenant_id="t1",
    user_id="u1",
)
# artifact.download_url → 可下载的 .pptx
# artifact.governance_audit → 治理审计记录（特性 001 联动）
```

**验证**：指定 PPTX 输出 → 生成可打开的 .pptx；XLSX → 表格内容完整；产物可下载且经治理审计。

---

## 6. 验证清单

| # | 验证项 | 期望 |
|---|---|---|
| 1 | 上传含表格 PDF | 解析产物保留表格结构 |
| 2 | 上传 DOCX | 段落与表格正确还原 |
| 3 | 上传不支持格式 | 任务失败且错误明确（不静默丢内容） |
| 4 | Docling 未安装 | 轻量子回退处理 TXT/MD/CSV/JSON/DOCX |
| 5 | 检索命中引用 | 附带 source anchor（页码/表行/段落） |
| 6 | 锚点缺失片段 | 降级为文档级引用，不伪造定位 |
| 7 | 上传 PPTX 预览 | 异步生成 PDF，管理面收到回调 |
| 8 | LibreOffice 缺失 | 报明确依赖缺失错误 |
| 9 | 生成 PPTX 交付物 | 可打开，结构符合输出规格 |
| 10 | 交付物下载 | 经治理审计（001 联动） |

---

## 7. 单元测试

```bash
cd services/document-parser
PYTHONPATH=. python -m pytest \
  tests/test_parser_formats.py \
  tests/test_citation_anchors.py \
  -o asyncio_mode=auto -q

cd services/chat-api
PYTHONPATH=. python -m pytest \
  tests/test_writer_engine.py \
  tests/test_publish_assembly.py \
  -o asyncio_mode=auto -q
```

---

## 8. 说明

- 解析服务使用 Celery 异步任务，任务态落 MongoDB（不阻塞 API）
- 内容生成流水线复用特性 001 的权限码与审计
- 产物留存策略随特性 001 治理层落地
- Docling 版本 pin 与离线模型资产是部署约定（客户环境首传不下载模型）
