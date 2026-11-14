# Quickstart: Enterprise Knowledge RAG & Multi-Source Research (005)

**Feature**: [spec.md](./spec.md) | [plan.md](./plan.md)

本文件说明如何**启用并验证**多源知识检索与带引用问答、租户/组织隔离检索、多轮研究、个人知识目录管理。

---

## 1. 前置

- `services/chat-api` 已部署（知识检索与问答）
- `services/document-parser` 已部署（候选片段来源，特性 003 联动）
- MongoDB + 向量库可用（检索基础设施）
- 特性 003（文档解析入库）已落地（候选片段来源）

---

## 2. 多源知识检索与带引用问答

```python
from app.knowledge.retrieval.retrieval_client import RetrievalClient
from app.knowledge.citations.citation_resolver import resolve_citations

client = RetrievalClient()

# 多源检索（内部文档 + 公开来源）
results = await client.retrieve(
    query="如何配置租户隔离？",
    tenant_id="t1",
    user_id="u1",
    max_chunks=10,
)

# 解析引用（documentId:chunkId 复合键）
citations = resolve_citations(
    used_chunk_ids=results.chunk_ids,
    document_ids=results.document_ids,
)
# citations[0].source_uri → mogo://resource/doc/<tenant>/<docId>/<chunkId>
```

**验证**：提问命中多文档→回答附引用列表；不同文档相同 chunkId→复合键区分不串引；无命中→标注"未找到依据"。

---

## 3. 检索访问策略（租户/组织隔离）

检索在授权范围内返回候选，跨组织/无权限文档不可见。

```python
# retrieval_access_policy 自动按租户/组织过滤
results = await client.retrieve(
    query="...",
    tenant_id="t1",       # 仅召回 t1 的文档
    org_id="org-1",       # 组织级知识仅该组织成员可召回
)
```

**验证**：用户 A（租户 1）提问→只召回租户 1 文档；无权限文档→不在候选中出现。

---

## 4. 多轮研究（Research Mode）

```python
from app.knowledge.agents.research_focus_builder import ResearchFocusBuilder

builder = ResearchFocusBuilder()

# 生成研究焦点
focus = await builder.build(
    topic="企业知识库最佳实践",
    context={"tenant_id": "t1"},
)

# 多轮迭代检索
for round_num in range(3):
    results = await client.retrieve(
        query=focus.query,
        tenant_id="t1",
    )
    # 每轮引用累积
    citations = resolve_citations(...)
    focus.update(results)
```

**验证**：发起研究→生成焦点；多轮迭代→引用累积；结论→带引用可追溯。

---

## 5. 个人知识目录与资源管理

```python
from app.api.endpoints.personal_knowledge import (
    create_directory,
    list_resources,
    share_knowledge,
)

# 创建个人知识目录
directory = await create_directory(
    user_id="u1",
    name="我的知识库",
)

# 列出资源
resources = await list_resources(
    user_id="u1",
    directory_id=directory.id,
)

# 分享（范围受控）
await share_knowledge(
    user_id="u1",
    directory_id=directory.id,
    share_to="u2",
)
```

**验证**：创建/更新/删除目录→操作成功且状态一致；分享→被分享者可见，范围受控。

---

## 6. 验证清单

| # | 验证项 | 期望 |
|---|---|---|
| 1 | 多源检索 | 内部文档 + 公开来源候选 |
| 2 | 带引用回答 | 每条引用可定位（documentId:chunkId） |
| 3 | 跨文档相同 chunkId | 复合键区分，不串引 |
| 4 | 无命中 | 标注"未找到依据"，不编造引用 |
| 5 | 查看引用 | 展示 chunk 原文与出处 |
| 6 | 租户隔离 | 仅召回授权范围文档 |
| 7 | 组织隔离 | 组织级知识仅成员可见 |
| 8 | 多轮研究 | 引用累积可追溯 |
| 9 | 个人知识分享 | 分享范围受控，未授权 0 可见 |
| 10 | 检索/问答事件 | 进入审计通道（001 联动） |

---

## 7. 单元测试

```bash
cd services/chat-api
PYTHONPATH=. python -m pytest \
  tests/test_knowledge_retrieval.py \
  tests/test_citation_resolver.py \
  tests/test_research_focus_builder.py \
  tests/test_personal_knowledge.py \
  -o asyncio_mode=auto -q
```

---

## 8. 说明

- 本特性为回溯固化既有能力，目标是把现有行为写成可验收契约，防止回归
- 候选片段来源于特性 003（文档解析入库产物）
- 检索授权复用特性 001 权限码模型
- 引用使用 documentId:chunkId 复合键，跨文档不串引
- 与特性 017（three-scope-memory）关系：个人知识底层存储可作为 017 personal scope 的存储基础
