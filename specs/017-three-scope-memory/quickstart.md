# 017 Three-Scope Memory — Quickstart

> **口径（v3 / D4，2026-11-06）**：范围轴已是 `personal / project / department`（`workspace/org` 直接改名、**无运行时兼容层**）。**B0 / B1 已落地**（统一身份解析 + P0 修复，有测试证据），**B2–B7 正在落地、尚未全部验收**；下列各示例中的 `viewer_id` / `is_workspace_member` 为旧版占位，运行时身份一律由服务端 `MemoryViewerContext` 构造（见 §1）。**D4 代码替换与数据迁移须在同一维护窗口原子切换，切换前必读** [`rollout-017-d4-cutover.md`](./rollout-017-d4-cutover.md)；目标态细则见 [`design-2026-11-05-project-department-scopes.md`](./design-2026-11-05-project-department-scopes.md) 与 [`spec.md`](./spec.md)。N1 / N2 / C-7 见文末「v3 补充口径」。

## Modules (chat-api `app/memory/`)

| Module | Concern |
| --- | --- |
| `scope.py` | `Memory` + 三 scope（personal / project / department）+ `visible_to` + 升级授权 + 密度分层字段 |
| `tiering.py` | L0/L1/L2 密度模型（FR-13/14/15）：写时摘要 + 读时懒刷新 |
| `address.py` | `mogo://memory/<personal\|project\|department>/<owner>/<id>/[L0\|L1\|L2]` 地址解析（FR-18） |
| `store.py` | MongoDB `memories` 集合，按 `(tenant_id, memory_id)` upsert；FR-16 硬限制 |
| `sediment.py` | 会话 → 分层记忆沉淀（FR-5/FR-19/FR-20），009 `SessionEnd` 消费者 |
| `retrieval.py` | 记忆进 RAG（按 scope 过滤 + 排序）+ 渐进式加载 `progressive_memory_retrieval` |
| `lifecycle.py` | 衰减 / 清理（30 天默认，访问重置计时器） |

## 0. 两条正交轴（先读这个）

017 有两条**互相正交**的轴，别混：

- **范围轴**（scope）= `personal` / `project` / `department` —— 管「**谁能看**」，由 `visible_to` 强制
- **密度轴**（tier）= `L0` / `L1` / `L2` —— 管「**喂多少**」，由 `tier_content` / `_select_tier` 决定

一条记忆同时有 scope 和 tier：`mogo://memory/department/u1/m1/L1` = department 范围的第 1 层内容。

## 1. 三 scope 可见性

> v3 起**可见性的唯一判据是 `visible_to(memory, MemoryViewerContext)`**；`MemoryViewerContext` 只由服务端 `resolve_viewer_context()`（HTTP）/ `resolve_viewer_from_identity()`（RAG）构造，禁止从 auth 字典或请求体自报 `user_id` / `role` / `is_workspace_member`。

```python
from app.memory.scope import Memory, visible_to, promote_to_department, MemoryScope
from app.memory.viewer import MemoryViewerContext, resolve_viewer_context

viewer: MemoryViewerContext = resolve_viewer_context(...)   # 服务端构造，fail-closed；示意
mem = Memory(content="note", scope="personal", owner_id="u1", memory_id="m1")
assert visible_to(mem, viewer) is True                     # 本人可见
assert visible_to(mem, other_viewer) is False              # 他人不可见
promote_to_department(mem, viewer=viewer, department_id="d1")  # 需 full_access_admin（G-1）
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
    viewer=viewer,            # 服务端 MemoryViewerContext，不再传散参数
    include_tier="L1",        # 先喂概览
    session_id="s1", turn_id="t1",
)
# trace.candidates[0]["uri"] == "mogo://memory/personal/u1/m1/L1"（FR-17 可回看）
```

## 3. 记忆进 RAG 检索（T010）

```python
from app.memory.retrieval import memory_rag_candidates, scope_filter

candidates = memory_rag_candidates(
    [department_mem, project_mem, personal_mem],
    viewer=viewer,             # 服务端 MemoryViewerContext
    top_n=8,
)
# department (weight 3) > project (2) > personal (1)，scope 过滤保证越权不可见
```

## 4. 地址（FR-18）

```python
from app.memory.address import MemoryAddress, parse_memory_uri

MemoryAddress(scope="department", owner_id="u1", memory_id="m1", tier="L1").uri()
# 'mogo://memory/department/u1/m1/L1'

addr = parse_memory_uri("mogo://memory/department/u1/m1/L1")
addr.scope, addr.tier      # ('department', 'L1')
addr.with_tier("L2")       # 换层不改身份
```

跨 spec 解析（含 resource / skill / session 三根）走 021 的统一入口：

```python
from app.context_space.router import resolve_memory

out = await resolve_memory("mogo://memory/department/u1/m1/L0", viewer=viewer, tenant_id="t1")
out["resolved"]["content"]   # 该层内容
out["trace"]                 # 统一检索轨迹（FR-17）
```

HTTP 入口（生产接线）：`POST /api/v1/context/resolve`（依据 `services/chat-api/app/api/endpoints/context_space.py` 的 router 前缀 `/api/v1/context` + `@router.post("/resolve")`，以及 `contracts/memory-context-contract.md`「HTTP 契约」节），详见 `specs/021-unified-context-address/`。

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

## v3 补充口径（N1 / N2 / C-7 / D4）

- **N1（项目归属消歧，D8 强制）**：`projects._id` 在租户内不保证唯一，故 `project` 记忆必带 `project_owner_id`，按 `(tenant_id, project_id, project_owner_id)` 判定可见性；`project_owner_id` **不进地址**，由服务端反查 `projects.user_id` 固化。历史缺该字段的记忆一律不可见（SC-13）。
- **N2（`default` 隔离，D7 强制）**：049 的默认项目 `"default"` 对同租户所有用户可见，017 **不继承该豁免**——显式写 `project_id="default"` 返回 400、会话沉淀回落 `personal`（不回落 department）、历史归档、地址解析 404，否则项目记忆会全租户泄露（SC-3）。
- **C-7（成员变更审计，首期必做）**：成员变更直接改变记忆可见面，须在 049 `PATCH /projects/{id}` 按 `member_user_ids` diff 落 `project.member.granted` / `project.member.revoked`（`feature="049"` → 001 审计），admin `/audit` 新增「记忆管理」module 可查；只改 `title`/`status` 或空 diff 不发事件，审计桥异常只留观测日志、不阻断 PATCH、不改响应码（SC-14）。017 只消费、不新建成员端点、不改 049 业务语义（见 `specs/049-project-members/spec.md` FR-011 与 tasks「017 C-7 增量」节）。
- **D4（一次性原子切换）**：`workspace/org → project/department` 直接改名，**无别名 / 双写 / `normalize_scope` / 字段级三级回退**；代码全量替换与数据迁移在同一维护窗口原子切换，回滚须「代码回退 + 迁移 `--reverse`」成对执行。**切换步骤、冻结写入与成对回滚 SOP 以** [`rollout-017-d4-cutover.md`](./rollout-017-d4-cutover.md) **为准**；迁移步骤 S1–S7 见 v3 设计文档 §10 与 `spec.md` J-2 / J-6。
