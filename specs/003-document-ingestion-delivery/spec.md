# Feature Specification: Multimodal Document Ingestion & Content Delivery

**Feature Branch**: `003-document-ingestion-delivery`

**Created**: 2026-07-08

**Status**: Draft

**Input**: 回溯固化 MOGO 既有优势能力（规划文档 §1.2 确认的"文档理解 + 内容生成"差异化强项）：多格式文档解析（PDF/DOCX/XLSX/PPTX/CSV/MD + 文档内图片图表）、解析产物进 RAG 检索（保留引用锚点）、Office 预览转换、以及报告/文章/PPTX/表格/PDF/MD 交付物生成与发布装配。

## User Scenarios & Testing *(mandatory)*

用户故事按优先级排列，每个独立可交付、可测试。

### User Story 1 (P1) — 多格式文档上传解析入库

用户或 Agent 上传文档（PDF/DOCX/XLSX/PPTX/CSV/TXT/Markdown/JSON），异步任务将其解析为结构化 Markdown（含表格），按配置切块并向量化，进入 RAG 检索范围；文档内的图片与图表内容一并可检索。

**Acceptance Scenarios:**
- 上传含表格与图片的 PDF → 解析产物保留表格结构（非拍平文本），图片走 OCR/多模态通道
- 上传 XLSX → 每工作表结构可解析，字段可检索
- 上传 DOCX → 段落与表格正确还原
- 不支持的格式 → 任务失败且错误信息明确（不因格式静默丢内容）
- Docling 未安装时 → 轻量子回退解析器处理 TXT/MD/CSV/JSON/DOCX/文本型 PDF，其余格式报明确错误

### User Story 2 (P1) — 引用可追溯（解析产物保留源锚点）

检索命中返回的片段可追溯到源文档的位置（页码/表行/段落锚点），回答或报告中引用不丢失出处。

**Acceptance Scenarios:**
- 检索返回片段 → 附带 source anchor（页码或表格行锚点）
- Agent 生成报告引用片段 → 引用可回链到原文档位置
- 锚点缺失的片段（如纯文本）→ 降级为文档级引用，不伪造定位

### User Story 3 (P1) — 文档预览转换（Office → PDF）

Office 文档（含 PPTX/XLSX/DOCX）上传后可转换预览为 PDF，预览产物落对象存储，管理面回调携带预览元数据；转换任务长耗时不阻塞 API。

**Acceptance Scenarios:**
- 上传 DOCX/PPTX → 异步生成预览 PDF，成功后管理面收到元数据回调
- 转换失败 → 任务状态失败且原因可见（如 LibreOffice 缺中文字体）
- 无 LibreOffice 环境 → 任务报明确依赖缺失错误，不静默跳过

### User Story 4 (P2) — 内容交付物生成（多格式产物）

Agent 的内容生成流水线可按输出规格产出交付物：报告/文章（Markdown/PDF/DOCX）、PPTX（幻灯片）、表格（XLSX）、图片、翻译（DOCX/XLSX 等）；生成结果作为可下载/可发布的产物留存。

**Acceptance Scenarios:**
- 指定 PPTX 输出 → 生成可打开的 .pptx，结构符合输出规格
- 指定 XLSX 输出（含表格数据）→ 生成 .xlsx，表格内容完整
- 翻译任务 → 支持 PDF/DOCX/XLSX/TXT/MD 源，二进制格式保持原排版
- 产物可下载，留存策略与治理层（特性 001）的审计联动

### User Story 5 (P2) — 发布装配（publish assembly）

交付物经发布装配管线输出最终可发布形态（如含 PPTX 的发布包），装配过程受输出规格驱动，产物与源规格一致。

**Acceptance Scenarios:**
- 输出规格含 pptx → 装配管线识别并走 PPTX 渲染分支
- 装配产物与规格声明的格式一致
- 装配失败可定位到具体步骤

### Notes / Assumptions
- 本特性为**回溯固化**既有能力（规划文档 §1.2"MOGO 已强于 EntAgent、不应重复投入"的边界），目标是把现有行为写成可验收的契约，防止回归
- 解析服务：services/document-parser（Celery + Redis + MongoDB 任务态 + Docling 运行时 + LibreOffice 预览）
- 内容生成：services/chat-api 的 enterprise_capabilities/content（writer_engine + publish_assembly）
- Docling 版本 pin 与离线模型资产是部署约定（客户环境首传不下载模型）
- 检索访问策略（retrieval_access_policy）沿用现有租户/组织隔离
- 产物落库与留存遵循 constitution 原则 II（可观测、可审计）

## Functional Requirements

- FR-1: 支持解析格式：PDF/DOCX/XLSX/XLSM/PPTX/CSV/TXT/MD/JSON/图片（PNG/JPG/JPEG/WEBP），不支持的格式任务失败且错误明确
- FR-2: 解析产物为结构化 Markdown + 表格结构保留 + 图片/图表 OCR 或多模态通道
- FR-3: 切块与向量化进 RAG 检索，片段保留 source anchor（页码/表行/段落）
- FR-4: 检索片段引用可回链原文档；锚点缺失时降级为文档级引用
- FR-5: Office 预览转 PDF（LibreOffice），产物落对象存储 + 管理面元数据回调；长耗时异步
- FR-6: 内容生成支持输出规格驱动的交付物：报告/文章（MD/PDF/DOCX）、PPTX、XLSX、图片、翻译（PDF/DOCX/XLSX/TXT/MD 源）
- FR-7: 交付物可下载、可发布；产物与源规格一致
- FR-8: 发布装配管线按输出规格装配最终形态（如 PPTX 发布包）
- FR-9: 解析/生成/预览任务全部有任务态（成功/失败/进行中），失败原因可定位
- FR-10: 检索与产物访问遵循租户/组织隔离（retrieval_access_policy）
- FR-11: Docling 未安装时子回退解析器覆盖 TXT/MD/CSV/JSON/DOCX/文本型 PDF，其余格式报明确错误

## Non-Goals
- 不改变现有 Docling 版本 pin 策略与离线模型资产约定
- 不引入新的文档格式（如 EPUB/CAJ），仅固化现有支持集
- 不重做 RAG 检索算法，仅保证产物进检索与引用锚点
- 不改变 LibreOffice 预览的部署依赖约定
- 产物留存治理（保留期限、清理策略）不在本特性，随特性 001 治理层落地

## Success Criteria
- 现有支持格式集合 100% 有解析路径或明确的格式错误（无静默丢内容）
- 检索命中片段带 source anchor 的比例 ≥ 95%（文本型文档允许降级）
- 预览转换成功率 ≥ 99%（失败均有原因码）
- 交付物生成产物可打开、与输出规格一致（PPTX/XLSX/DOCX/PDF/MD）
- 内容生成产物 100% 经治理审计（特性 001 落库联动）

## Further Details
- 技术实现（解析管线、装配管线、任务态存储）由 plan.md 承载
- 与特性 001（gatekeeper）的关系：产物生成与下载复用 001 的权限码与审计
- 与特性 002（session-versioning）的关系：内容生成会话的 commit/share 沿用 002 快照与秘密过滤
