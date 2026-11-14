# Implementation Plan: Multimodal Document Ingestion & Content Delivery

**Branch**: `003-document-ingestion-delivery` | **Date**: 2026-07-08 | **Spec**: [spec.md](./spec.md)

**Input**: 回溯规约，固化既有行为。plan 将"现有实现事实"技术化为可验收契约，不引入新架构。

## Summary

本特性不新增模块，而是把 `services/document-parser`（解析 + 预览）与 `services/chat-api/enterprise_capabilities/content`（生成 + 装配）两条既有管线写成技术契约。交付物：data-model.md（解析产物与任务态字段）、contracts/parse-contract.md、contracts/delivery-contract.md、quickstart.md（启用与验证步骤）。

## Technical Context

**Language/Version**: Python 3.13（沿用 document-parser/chat-api 既有栈）

**Primary Dependencies**: Docling（pinned，离线模型资产）+ LibreOffice + Redis/Celery + MongoDB；chat-api 侧 FastAPI + 既有 content 引擎

**Storage**: MongoDB `document_jobs`（任务态）+ 对象存储（预览 PDF / 解析产物）+ 向量库（RAG 检索）

**Testing**: pytest（document-parser/tests 既有 + content 引擎既有测试）

**Target Platform**: 自托管 Docker Compose（同一镜像跑 API 或 Celery worker）

**Project Type**: 既有服务契约化（brownfield）

## 现有实现事实（contract 依据）

### 解析管线（document-parser）
- 入口：`parse_document(path, filename) -> ParsedDocument`；`ParsedDocument{markdown, raw, raw_chunks, rag_chunks}`
- 格式分派（`document_parsing_service.py`）：
  - `TEXT_EXTENSIONS = {txt, md, markdown, csv, json}` → 纯文本
  - `DOCX_EXTENSIONS = {docx}` → Docling（无则 python-docx 子回退）
  - `PDF_EXTENSIONS = {pdf}` → Docling + RapidOCR 图片页（`_pdf_image_ocr_pages`）
  - `LEGACY_OFFICE_EXTENSIONS = {doc, ppt, xls}` → 明确失败（待 Docling/LibreOffice）
  - `IMAGE_EXTENSIONS = {png, jpg, jpeg, webp}` → OCR（`parse_image_with_ocr`）
  - XLSX/XLSM 走 Docling 表格通道
- 回退（`parse_with_fallback`）：Docling 未装时 TXT/MD/CSV/JSON/DOCX/文本型 PDF 用 python-docx / pypdf / 文本解析；其余报明确错误
- 引用锚点：`_docling_source_anchor(meta, fallback_page_no)` + `_table_row_source_anchor(row, ...)` 产出页码/表行锚点
- 噪声过滤：`_clean_chunk_text` / `_is_noise_chunk` / `_looks_like_flattened_table_text`

### 预览管线
- `POST /api/jobs/preview-convert`：Office → PDF（LibreOffice），产物写存储，回调 admin-api 元数据
- 长任务走 Celery worker（Redis 队列 `document_processing`）

### 内容生成管线（chat-api/content）
- `writer_engine`（compose_skill/pipeline）：输出规格驱动的交付物
  - `TRANSLATABLE_EXTENSIONS = {.pdf, .docx, .xlsx, .txt, .md}`，二进制 `.docx/.xlsx` 保持排版
  - 表格数据自动补 `xlsx` 格式
- `publish_assembly`（`assembler.py`）：
  - `_requests_pptx(output_spec)` 识别 PPTX 输出 → PPTX 渲染分支
  - 视觉槽位生成、重试、降级、样式契约

## Constitution Check

| 原则 | 结果 |
|---|---|
| I. Specification-First | 通过：spec 已固化既有行为 |
| II. Enterprise Production Readiness | 通过：任务态/失败原因码/离线模型部署约定 |
| III. Security | 通过：检索访问策略复用 retrieval_access_policy |
| IV. i18n | 通过：解析/生成不引入新 UI 文案 |
| V. Observability | 通过：document_jobs 任务态全量可查 |

## Project Structure

```text
specs/003-document-ingestion-delivery/
├── plan.md              # 本文件
├── data-model.md        # ParsedDocument / 任务态 / 产物字段契约
├── contracts/
│   ├── parse-contract.md    # 解析管线输入/输出/格式分派/回退
│   └── delivery-contract.md # 生成 + 装配输出规格/格式产物
└── quickstart.md        # 启用 + 各格式验证步骤
```

源码不改动（brownfield 契约化）；如需修回归，以 tasks.md 登记修复项。

## Open Questions
- OQ-1: XLSX 解析是走 Docling 表格通道还是独立 openpyxl 路径？（需确认现有行为以写准 contract）
- OQ-2: 图片 OCR 模型是 RapidOCR（PDF 内页）还是独立多模态通道？
- OQ-3: 产物留存策略是否已有默认保留期限，还是本特性留白给 001 治理？

## 下一步
`/speckit-clarify` 消解 OQ → 补齐 data-model.md / contracts / quickstart → `/speckit-checklist` → `/speckit-tasks` → `/speckit-analyze`。
