# Feature Specification: Enterprise Knowledge RAG & Multi-Source Research

**Feature Branch**: `005-knowledge-rag-research`

**Created**: 2026-07-08

**Status**: Draft

**Input**: 回溯固化 MOVO 既有优势能力（规划文档 §1.1"企业知识/RAG：内部文档+公开信息检索、多轮研究、保留引用、个人知识库可分享"）：多源检索（内部文档 + 公开来源）、带引用的知识问答、多轮研究、证据查看、个人知识目录/资源管理。

## User Scenarios & Testing *(mandatory)*

用户故事按优先级排列，每个独立可交付、可测试。

### User Story 1 (P1) — 多源知识检索与带引用问答

用户提问时，系统从内部文档与公开来源检索候选片段，生成回答时**必须保留引用**（引用可回链到源文档），用户可查看每条引用支撑的证据。

**Acceptance Scenarios:**
- 提问命中多个文档 → 回答附引用列表，每条引用可定位到源文档（documentId + chunkId）
- 不同文档存在相同 chunkId → 引用用 `documentId:chunkId` 复合键区分，不串引
- 无有效片段命中 → 回答标注"未找到依据"，不编造引用
- 用户查看某条引用 → 展示该 chunk 原文与出处

### User Story 2 (P1) — 检索访问策略（租户/组织隔离）

检索只在授权的租户/组织范围内返回候选；跨组织/无权限的文档不可见。

**Acceptance Scenarios:**
- 用户 A（租户 1）提问 → 只召回租户 1 的文档
- 组织级知识 → 仅该组织成员可召回
- 无权限文档 → 不在候选中出现

### User Story 3 (P2) — 多轮研究（research mode）

用户可发起多轮研究任务，围绕研究焦点持续检索与综合，产出带引用的研究结论；研究焦点可结构化。

**Acceptance Scenarios:**
- 发起研究 → 生成研究焦点（ResearchFocusBuilder）
- 多轮迭代 → 每轮基于前轮结果深化，引用累积
- 研究结论 → 带引用，可追溯

### User Story 4 (P2) — 个人知识目录与资源管理

用户可管理个人知识目录（增删改查）与资源；个人知识可分享（规划文档 §1.1"个人知识库（可分享）"）。

**Acceptance Scenarios:**
- 创建/更新/删除个人知识目录 → 操作成功且状态一致
- 列出个人知识资源 → 返回资源列表
- 分享个人知识 → 被分享者可见，分享范围受控

### Notes / Assumptions
- 本特性为**回溯固化**既有能力，目标把现有行为写成可验收契约，防止回归
- 知识模块：services/chat-api/app/knowledge（retrieval/citations/agents/prompting/research_focus_builder/skill_md_parser）
- 引用解析：citations/citation_resolver.py（parse_llm_json + resolve_citations）
- 检索客户端：knowledge/retrieval/retrieval_client.py + schemas.py
- 个人知识端点：api/endpoints/personal_knowledge.py（directories + resources CRUD）
- 检索访问策略：document-parser 的 retrieval_access_policy（租户/组织隔离）
- 与特性 003（文档解析）的关系：知识检索的候选片段来源于 003 的解析入库产物
- 与特性 001（gatekeeper）的关系：检索授权复用 001 权限码模型

## Functional Requirements

- FR-1: 知识问答从内部文档 + 公开来源多源检索，回答保留引用
- FR-2: 引用使用 documentId:chunkId 复合键，跨文档不串引
- FR-3: 无有效片段时回答标注"未找到依据"，不编造引用
- FR-4: 用户可查看每条引用的支撑证据（chunk 原文 + 出处）
- FR-5: 检索按租户/组织隔离，无权限文档不出现在候选
- FR-6: 多轮研究围绕结构化研究焦点迭代，引用累积可追溯
- FR-7: 个人知识目录支持增删改查，资源列表可查
- FR-8: 个人知识可分享，分享范围受控
- FR-9: 引用解析对 LLM 输出的 usedChunkIds 做容错（非法/缺失引用降级处理）
- FR-10: 检索与问答事件进入审计通道（与 001 联动）

## Non-Goals
- 不实现业务系统语义索引（CRM/采购/财务 RAG，规划文档 P2 第 10 项）
- 不实现知识图谱层（规划文档 P2 第 11 项）
- 不实现三范围 Memory 粒度（个人/Workspace/组织记忆，规划文档 P2 第 13 项）
- 不改变既有检索算法与向量库实现，仅固化行为契约
- 不实现跨组织知识共享

## Success Criteria
- 带引用回答中引用可定位率 100%（documentId:chunkId 复合键）
- 跨文档相同 chunkId 0 串引
- 无依据回答 100% 标注"未找到依据"（不编造）
- 租户/组织隔离检索 100% 无越权召回
- 个人知识分享后未授权成员 0 可见

## Further Details
- 技术实现（检索客户端、引用解析、研究焦点构建）由 plan.md 承载
- 与特性 003（文档解析）的关系：候选片段来源
- 与特性 001（gatekeeper）的关系：检索授权与审计

### 跨特性关系（被依赖方视角，2026-07-08 双向声明）
- **与 014（business-semantic-index）**：005 的检索客户端与引用锚点**可扩展支持"业务实体项"**——014 的业务实体检索结果与 005 文档检索结果走同一检索通道，`RetrievalChunkItem` 扩展实体类型字段（来源标注区分 文档片段/业务实体）。
- **与 015（knowledge-graph-layer）**：005 的检索结果**可与图谱推理结果融合**——015 的图谱推理与 005 的 RAG 检索并列返回，融合裁决见 015 FR-9。
- **与 017（three-scope-memory）**：005 的个人知识底层存储**可作为 017 personal scope 的存储基础**（不重复建库）；017 的记忆**进入 005 的 RAG 检索范围**（检索时按 scope 可见性过滤）。
