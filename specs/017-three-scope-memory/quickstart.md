# 017 Three-Scope Memory — Quickstart

## Modules (chat-api `app/memory/`)

| Module | Concern |
| --- | --- |
| `scope.py` | `Memory` + 三 scope（personal / workspace / org）+ 可见性 + 升级授权 + 密度分层字段 |
| `tiering.py` | L0/L1/L2 密度模型（FR-13/14/15）：写时摘要 + 读时懒刷新 |
| `address.py` | `mogo://memory/<scope>/<owner>/<id>/[L0\|L1\|L2]` 地址解析（FR-18） |
| `store.py` | MongoDB `memories` 集合，按 `(tenant_id, memory_id)` upsert；FR-16 硬限制 |
| `sediment.py` | 会话 → 分层记忆沉淀（FR-5/FR-19/FR-20），009 `SessionEnd` 消费者 |
| `retrieval.py` | 记忆进 RAG（按 scope 过滤 + 排序）+ 渐进式加载 `progressive_memory_retrieval` |
| `lifecycle.py` | 衰减 / 清理（30 天默认，访问重置计时器） |

## 0. 两条正交轴（先读这个）

017 有两条**互相正交**的轴，别混：

- **范围轴**（scope）= `personal` / `workspace` / `org` —— 管「**谁能看**」，由 `visible_to` 强制
- **密度轴**（tier）= `L0` / `L1` / `L2` —— 管「**喂多少**」，由 `tier_content` / `_select_tier` 决定

一条记忆同时有 scope 和 tier：`mogo://memory/org/u1/m1/L1` = org 范围的第 1 层内容。

## 1. 三 scope 可见性

```python
from app.memory.scope import Memory, visible_to, promote_to_org, MemoryScope

mem = Memory(content="note", scope="personal", owner_id="u1", memory_id="m1")
assert visible_to(mem, viewer_id="u1") is True
assert visible_to(mem, viewer_id="u2") is False
promote_to_org(mem, role="full_access_admin")   # -> org scope (需授权)
```

## 2. 密度分层（FR-13/14/15）

```python
from app.memory.tiering import tier_content, NoopSummarizer

# 写时摘要：调用方（上游 LLM）已生成 L0/L1，直接带上 → 首次读取零成本
supplied = tier_content(
    long_text,
    NoopSummarizer(),
    l0_summary="一句话结论",
    l1_overview="要点 1/2/3",
    summary_generated_at=time.time(),   # 标记新鲜，避免被懒刷新覆盖
)

# 读时懒兜底：没给摘要且超过 refresh_days → 调 Summarizer 现场生成
class MySummarizer:
    def summarize(self, content: str) -> tuple[str, str]:
        return (content[:80], content[:400])

lazy = tier_content(long_text, MySummarizer(), refresh_days=30)
```

取指定层内容（`L2` = 原始 content）：

```python
from app.memory.retrieval import _select_tier   # 或 app.context_space.adapters.memory._select_tier
_select_tier(mem, "L0")   # l0_summary or content（缺失时优雅降级）
_select_tier(mem, "L1")   # l1_overview or l0_summary or content
_select_tier(mem, "L2")   # content
```

**渐进式检索**（默认只喂 L1，需要时再钻 L2）：

```python
from app.memory.retrieval import progressive_memory_retrieval

candidates, trace = progressive_memory_retrieval(
    [mem],
    viewer_id="u1",
    include_tier="L1",        # 先喂概览
    session_id="s1", turn_id="t1",
)
# trace.candidates[0]["uri"] == "mogo://memory/personal/u1/m1/L1"（FR-17 可回看）
```

## 3. 记忆进 RAG 检索（T010）

```python
from app.memory.retrieval import memory_rag_candidates, scope_filter

candidates = memory_rag_candidates(
    [org_mem, ws_mem, personal_mem],
    viewer_id="u1",
    is_workspace_member=True,
    top_n=8,
)
# org (weight 3) > workspace (2) > personal (1)，scope 过滤保证越权不可见
```

## 4. 地址（FR-18）

```python
from app.memory.address import MemoryAddress, parse_memory_uri

MemoryAddress(scope="org", owner_id="u1", memory_id="m1", tier="L1").uri()
# 'mogo://memory/org/u1/m1/L1'

addr = parse_memory_uri("mogo://memory/org/u1/m1/L1")
addr.scope, addr.tier      # ('org', 'L1')
addr.with_tier("L2")       # 换层不改身份
```

跨 spec 解析（含 resource / skill / session 三根）走 021 的统一入口：

```python
from app.context_space.router import resolve_memory

out = await resolve_memory("mogo://memory/org/u1/m1/L0", tenant_id="t1", viewer_id="u1")
out["resolved"]["content"]   # 该层内容
out["trace"]                 # 统一检索轨迹（FR-17）
```

HTTP 入口（生产接线）：`POST /api/context/resolve`，详见 `specs/021-unified-context-address/`。

## 5. 会话沉淀（FR-5/FR-19/FR-20）

```python
from app.memory.sediment import sediment_session_end

await sediment_session_end(
    session_id="sess-1",
    session_doc=chat_session_doc,     # 002 的 chat_sessions 文档
    store=MemoryStore(),
    owner_id="u1",
    tenant_id="t1",
)
# 产出带 source_session_id / source_type="session" 的分层记忆
```

**触发时机**：002 会话**结束**时（`POST /api/sessions/{id}/end` → `end_session()` → 009 `SessionEnd` 事件 → 本模块作为订阅者消费）。`delete_session` 仅对从未结束过的会话做兜底沉淀。

## 6. 衰减（FR-8）

```python
from app.memory.lifecycle import MemoryLifecycle, is_expired, touch

policy = MemoryLifecycle(decay_days=30)
last = touch(memory.last_accessed_at, now=time.time())  # 访问重置计时器
assert is_expired(last_accessed_at=last, now=now + 86400) is False
```

## T999 审计接入

`memory.promoted` / `memory.decayed` / `memory.restored` 事件经
`app/services/feature_audit.py::record_feature_event("017", ...)` 进 001
审计落点。
