# Tasks: Multimodal Document Ingestion & Content Delivery

> ⚠️ **落地审计说明**：本特性为回溯固化既有能力，任务条目标记当前落地状态。
> `[x]` 表示已实现；`[ ]` 表示规划中/待补。详见 [`specs/LANDING_AUDIT_2026-10-03.md`](../LANDING_AUDIT_2026-10-03.md)。

**Input**: Design documents from `/specs/003-document-ingestion-delivery/`

**Prerequisites**: plan.md (required), spec.md (required)

**Organization**: 任务按用户故事分组，每组可独立实现与测试。

---

## Phase 1: Foundational — 解析管线基础

**Goal**: 建立多格式文档解析的核心管线，保留表格结构与锚点。

- [x] T001 实现 `ParserService` 核心接口：统一解析入口，按文件类型路由到对应解析器
- [x] T002 实现 Docling 解析器：PDF/DOCX/PPTX/XLSX 解析，保留表格结构（非拍平文本）
- [x] T003 实现轻量子回退解析器：Docling 未安装时覆盖 TXT/MD/CSV/JSON/DOCX/文本型 PDF
- [x] T004 实现图片/图表 OCR 或多模态通道：文档内图片内容可检索
- [x] T005 实现切块与向量化：解析产物按配置切块，进入 RAG 检索范围
- [x] T006 实现 source anchor 保留：片段附带页码/表行/段落锚点（FR-3）

---

## Phase 2: User Story 1 (P1) — 多格式文档上传解析入库

**Goal**: 用户/Agent 上传文档，异步解析为结构化 Markdown，进 RAG 检索。

**独立测试**: 上传各格式 → 解析成功且产物结构正确；不支持格式 → 明确报错。

- [x] T007 [P] 实现上传入口 `POST /api/documents/upload`：接收文件，创建异步解析任务
- [x] T008 [P] 实现解析任务态存储：MongoDB 任务集合（成功/失败/进行中），失败原因可定位
- [x] T009 [P] 实现格式白名单与错误处理：不支持格式任务失败且错误明确（FR-1）
- [x] T010 单元测试：各格式解析路径覆盖（PDF/DOCX/XLSX/PPTX/CSV/TXT/MD/JSON/图片）
- [x] T011 集成测试：上传→解析→检索端到端流程

---

## Phase 3: User Story 2 (P1) — 引用可追溯

**Goal**: 检索命中片段可追溯源文档位置，回答引用不丢失出处。

**独立测试**: 检索返回片段 → 附带 anchor；引用缺失 → 降级为文档级引用。

- [x] T012 [P] 实现 citation resolver：`documentId:chunkId` 复合键，跨文档不串引
- [x] T013 [P] 实现引用回链：Agent 生成报告引用片段 → 引用可回链到原文档位置
- [x] T014 [P] 实现锚点降级策略：锚点缺失的片段降级为文档级引用，不伪造定位（FR-4）
- [x] T015 单元测试：引用解析容错（非法/缺失引用降级处理）

---

## Phase 4: User Story 3 (P1) — Office 预览转换

**Goal**: Office 文档上传后可转换预览为 PDF，转换异步不阻塞 API。

**独立测试**: 上传 DOCX/PPTX → 异步生成 PDF；LibreOffice 缺失 → 明确报错。

- [x] T016 [P] 实现 PreviewService：LibreOffice 转换 Office → PDF，产物落对象存储
- [x] T017 [P] 实现管理面元数据回调：预览成功后管理面收到元数据
- [x] T018 [P] 实现依赖缺失检测：LibreOffice 未安装时任务报明确错误（FR-5）
- [x] T019 集成测试：DOCX/PPTX 预览转换端到端流程

---

## Phase 5: User Story 4 (P2) — 内容交付物生成

**Goal**: Agent 内容生成流水线按输出规格产出交付物。

**独立测试**: 指定格式 → 生成对应产物；产物可下载且经治理审计。

- [x] T020 [P] 实现 WriterEngine：按输出规格生成报告/文章/表格（MD/PDF/DOCX/XLSX）
- [x] T021 [P] 实现 PPTX 生成：幻灯片结构符合输出规格（FR-6）
- [x] T022 [P] 实现翻译任务：支持 PDF/DOCX/XLSX/TXT/MD 源，二进制格式保持原排版
- [x] T023 [P] 实现交付物下载：产物可下载，留存策略与治理层联动
- [x] T024 治理审计联动：产物生成与下载复用特性 001 权限码与审计（FR-7）

---

## Phase 6: User Story 5 (P2) — 发布装配

**Goal**: 交付物经发布装配管线输出最终可发布形态。

**独立测试**: 输出规格含 pptx → 装配管线识别并走 PPTX 渲染分支。

- [x] T025 实现 PublishAssembly 管线：按输出规格装配最终形态（如 PPTX 发布包）
- [x] T026 实现装配失败定位：装配失败可定位到具体步骤（FR-8）
- [x] T027 集成测试：输出规格驱动装配端到端流程

---

## Phase 7: Cross-Cutting — 治理与安全

**Goal**: 检索与产物访问遵循租户/组织隔离，全部操作进审计。

- [x] T028 [P] 实现 retrieval_access_policy：检索按租户/组织隔离（FR-10）
- [x] T029 [P] 实现任务态全量可观测：解析/生成/预览任务全部有任务态，失败原因可定位（FR-9）
- [x] T030 [P] 实现审计联动：产物生成与下载经治理审计（001 联动）

---

## Phase 8: Testing & Verification

- [x] T031 格式集合 100% 有解析路径或明确格式错误（Success Criteria 1）
- [x] T032 检索命中片段带 source anchor 比例 ≥ 95%（Success Criteria 2）
- [x] T033 预览转换成功率 ≥ 99%，失败均有原因码（Success Criteria 3）
- [x] T034 交付物产物可打开、与输出规格一致（Success Criteria 4）
- [x] T035 内容生成产物 100% 经治理审计（Success Criteria 5）
