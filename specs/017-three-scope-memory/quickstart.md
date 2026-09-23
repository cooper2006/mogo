# 017 Three-Scope Memory — Quickstart

## Modules (chat-api `app/memory/`)

| Module | Concern |
| --- | --- |
| `scope.py` | `Memory` + 三 scope（personal / workspace / org）+ 可见性 + 升级授权 |
| `lifecycle.py` | 衰减 / 清理（30 天默认，访问重置计时器） |
| `retrieval.py` | T010 记忆进 RAG 检索（按 scope 过滤 + 排序） |

## 1. 三 scope 可见性

```python
from app.memory.scope import Memory, visible_to, promote_to_org, MemoryScope

mem = Memory(content="note", scope="personal", owner_id="u1", memory_id="m1")
assert visible_to(mem, viewer_id="u1") is True
assert visible_to(mem, viewer_id="u2") is False
promote_to_org(mem, role="full_access_admin")   # -> org scope (需授权)
```

## 2. 记忆进 RAG 检索（T010）

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

## 3. 衰减（FR-8）

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
