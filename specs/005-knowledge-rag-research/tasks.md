# Tasks: Enterprise Knowledge RAG & Multi-Source Research

> ⚠️ **落地审计说明**：本特性为回溯固化既有能力，任务条目标记当前落地状态。

**Input**: Design documents from `/specs/005-knowledge-rag-research/`

**Prerequisites**: plan.md (required), spec.md (required)

**Organization**: 任务按用户故事分组，每组可独立实现与测试。

---

## Phase 1: Foundational — 检索基础设施

**Goal**: 建立多源检索客户端与引用解析核心。

- [x] T001 实现 `RetrievalClient`：多源检索入口（内部文档 + 公开来源）
- [x] T002 实现 `retrieval/schemas.py`：检索结果 schema（chunk/document/type 字段）
- [x] T003 实现 `RetrievalChunkItem` 扩展：支持文档片段/业务实体类型字段
- [x] T004 实现 `CitationResolver`：`parse_llm_json` + `resolve_citations` 引用解析
- [x] T005 实现 documentId:chunkId 复合键：跨文档不串引（FR-2）
- [x] T006 实现引用容错：非法/缺失引用降级处理（FR-9）

---

## Phase 2: User Story 1 (P1) — 多源知识检索与带引用问答

**Goal**: 多源检索，回答保留引用，引用可回链源文档。

**独立测试**: 命中多文档→附引用列表；无命中→标注"未找到依据"。

- [x] T007 [P] 实现多源检索管线：内部文档 + 公开来源统一检索通道
- [x] T008 [P] 实现回答生成：检索命中片段注入 LLM，回答附引用
- [x] T009 [P] 实现无依据标注：无有效片段命中→标注"未找到依据"（FR-3）
- [x] T010 [P] 实现证据查看：用户可查看每条引用支撑的 chunk 原文与出处（FR-4）
- [x] T011 单元测试：引用解析与复合键区分
- [x] T012 集成测试：检索→引用→问答端到端流程

---

## Phase 3: User Story 2 (P1) — 检索访问策略

**Goal**: 检索按租户/组织隔离，无权限文档不可见。

**独立测试**: 用户 A→只召回租户 1 文档；无权限→不在候选。

- [x] T013 [P] 实现 `retrieval_access_policy`：租户/组织隔离检索（FR-5）
- [x] T014 [P] 实现授权范围过滤：检索候选按用户权限过滤
- [x] T015 单元测试：租户/组织隔离检索
- [x] T016 集成测试：跨组织检索越权验证

---

## Phase 4: User Story 3 (P2) — 多轮研究

**Goal**: 多轮研究围绕结构化焦点迭代，引用累积可追溯。

**独立测试**: 发起研究→生成焦点；多轮→引用累积。

- [x] T017 [P] 实现 `ResearchFocusBuilder`：结构化研究焦点构建
- [x] T018 [P] 实现多轮迭代检索：每轮基于前轮结果深化
- [x] T019 [P] 实现引用累积：每轮引用累积，结论带引用可追溯（FR-6）
- [x] T020 单元测试：研究焦点构建与多轮迭代

---

## Phase 5: User Story 4 (P2) — 个人知识目录与资源管理

**Goal**: 个人知识目录 CRUD + 资源管理 + 分享。

**独立测试**: 创建/更新/删除目录→状态一致；分享→范围受控。

- [x] T021 [P] 实现个人知识目录 CRUD：`personal_knowledge` 端点（FR-7）
- [x] T022 [P] 实现资源列表：列出个人知识资源
- [x] T023 [P] 实现知识分享：个人知识可分享，范围受控（FR-8）
- [x] T024 单元测试：目录 CRUD 与分享全链路

---

## Phase 6: Cross-Cutting — 治理与安全

- [x] T025 [P] 实现检索/问答事件审计：与 001 联动（FR-10）
- [x] T026 [P] 实现检索结果脱敏：敏感片段在检索结果中脱敏处理
- [x] T027 [P] 实现与 003 联动：候选片段来源为 003 解析入库产物

---

## Phase 7: Testing & Verification

- [x] T028 带引用回答中引用可定位率 100%（Success Criteria 1）
- [x] T029 跨文档相同 chunkId 0 串引（Success Criteria 2）
- [x] T030 无依据回答 100% 标注"未找到依据"（Success Criteria 3）
- [x] T031 租户/组织隔离检索 100% 无越权召回（Success Criteria 4）
- [x] T032 个人知识分享后未授权成员 0 可见（Success Criteria 5）
