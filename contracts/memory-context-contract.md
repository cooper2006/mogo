# Memory Context Contract (017 + 021) — D4 目标态

> 017-three-scope-memory（三 scope 记忆 + 密度分层）与 021-unified-context-address
> （`mogo://` 统一地址空间）的对外契约。本文件定义 chat-api `app/memory/` 与
> `app/context_space/` 的接口与不变量；与 `specs/017-three-scope-memory/spec.md`、
> `specs/021-unified-context-address/spec.md` 配套。
>
> **D4（2026-11-06 一次性改名）**：`workspace` / `org` 已原子切换为
> `project` / `department`。**无运行时兼容层** —— 无别名、无 `normalize_scope`、
> 无双写、无字段级三级回退。旧值仅由离线迁移脚本
> `scripts/migrate_017_scopes.py` 转换；运行时一律拒绝 / fail-closed。
> 其它特性（如 `projects.py` / `dsh_runtime/*`）里的 `workspace_id` 是别的模块
> 的字段名，不在本契约范围。

## 核心模型：两条正交轴

| 轴 | 取值 | 管什么 | 强制点 |
| --- | --- | --- | --- |
| **范围轴** scope | `personal` / `project` / `department` | **谁能看** | `scope.visible_to(memory, MemoryViewerContext)` |
| **密度轴** tier | `L0` / `L1` / `L2` | **喂多少** | `tiering.tier_content()` / `_select_tier()` |

一条记忆同时携带两者：`mogo://memory/department/u1/m1/L1` 表示
「department 范围、第 1 密度层」。
**scope 不影响 tier 的降级规则，tier 不影响可见性判断** —— 两轴互不推导。

`MemoryScope.{PERSONAL, PROJECT, DEPARTMENT}`、`Visibility`、
`SCOPE_VISIBILITY` 是权威枚举；`Memory.__post_init__` 拒绝三值之外的 scope。

## 不变量

- **无越权（FR-2 / B-4）**：`visible_to(memory, viewer)` 是**唯一**可见性判据，
  第二参数必须是服务端构造的 `app.memory.viewer.MemoryViewerContext`
  （不是 `viewer_id` / `viewer_role` / `is_workspace_member` / `viewer_org_id` 散参数，
  更不是请求体里的身份字段）。021 地址层**只委托不重写**：
  `ViewerContext.memory_viewer` 原样转给 `visible_to`，缺 `memory` 或缺
  `memory_viewer` 一律 fail-closed。
- **无运行时兼容层（D4）**：017 的 scope 值与文档字段只认
  `personal|project|department` / `project_id|project_owner_id|department_id`；
  旧 `workspace` / `org` 段与 `workspace_id` / `org_id` 字段在运行时不别名、
  不归一化、不双写、不回退。
- **范围轴封闭**：`Memory.scope` 只能是 `personal|project|department` 三值。
- **N1（项目归属消歧）**：`project` 记忆必带 `project_owner_id`。
  `projects._id` 在租户内**不唯一**（唯一索引是
  `{tenant_id, user_id, workspace_id}`），因此可见性比较的是
  `(project_id, project_owner_id)` **对**（`MemoryViewerContext.visible_project_keys`
  为 `frozenset[(project_id, project_owner_id)]`）。
  **`project_owner_id` 不进地址**：地址只承载 `<scope>/<owner>/<id>`，归属对在
  存储层与 viewer 侧比较，绝不由客户端在 URI 里指定。
- **N2（049 默认行豁免不继承）**：租户级回退行 `_id="default"` 永不承载
  `project` 记忆；`project_id == "default"` 写入返回 `400
  default_project_not_shareable`，沉淀侧 `resolve_default_scope` 视其为无项目
  上下文、回落 `personal`（E-4）。
- **升级需授权（FR-4 / G-1）**：`promote_to_department(memory, *, viewer,
  department_id)` / `can_promote_to_department(viewer)` 仅
  `full_access_admin`（`DEPARTMENT_PROMOTION_ROLES`）可调用，且目标
  `department_id` 必须在 `viewer.visible_department_ids` 内；否则抛
  `MemoryAccessError`。
- **D-6（增量提升）**：提升只以 `MemoryStore.update_fields()` 的 `$set` 更新
  `scope` / `department_id` / `updated_at`，**绝不** `replace_one` 全量覆盖
  （必须保留 L0/L1/L2、provenance、`archived`、`project_owner_id`）。
- **分层只降不升（FR-14）**：`_select_tier` 在高层缺失时向下退
  （`L1 → l0_summary → content`），**绝不返回空串**给上层。
- **FR-16 硬限制**：`tierable=False` 且内容超 `MEMORY_L2_HARD_MAX_BYTES`
  时**拒绝写入**（抛 `MemoryTooLargeError`），不静默截断。
- **写入必须 await（motor）**：`MemoryStore.save`（新建，`replace_one(upsert=True)`）
  与 `MemoryStore.update_fields`（增量 `$set`）都是 `async`，必须 await。
- **所有 DB 查询带 tenant 边界**：`list_for_viewer(viewer=...)` / `get` /
  `delete` / `update_fields` 的查询条件恒含 `tenant_id`；解析失败 fail-closed。
- **地址可逆**：`MemoryAddress.uri()` → `parse_memory_uri()` 往返一致；
  `safe=""` 保证 id 内的 `/` 被百分号编码。旧 `workspace` / `org` 段
  `parse_memory_uri` 抛 `ValueError`（端点映射 404）。
- **不可见即不泄露（B-9）**：跨租户 / 越权 / 旧地址统一 404 或 403，
  **不返回任何内容字段**；批量解析中不可见项逐项报告、不拖垮整批。
- **溯源必备（FR-19）**：会话沉淀的记忆带 `source_session_id` +
  `source_type="session"`，可回溯到 002 会话。
- **生命周期唯一（FR-20）**：一次会话**至多沉淀一次**（`_SEDIMENTED` 账本），
  `end → delete` 不产生重复记忆；沉淀失败不阻塞会话结束，但落观测日志。
- **H-2（访问刷新衰减）**：`list_for_viewer` 命中后对返回条目调用
  `app.memory.lifecycle.touch()`（真实签名为模块级
  `touch(last_accessed_at, now) -> float`），失败只留日志不阻断。
- **T022（L0 非空）**：生产沉淀路径默认注入 `NoopSessionSummarizer()`（不是
  `None`），`build_session_memory` 在 `l0_summary` 为空时调用 summarizer；
  读时惰性补全在 `store.list_for_viewer` / retrieval 侧以 `tier_content`
  接线并留可观测日志。

## Scope 身份字段（不在地址中）

| 字段 | 含义 |
| --- | --- |
| `project_id` | 项目 id（D4 由 `workspace_id` 改名） |
| `project_owner_id` | 项目归属者 id（N1 消歧，**不进地址**） |
| `department_id` | 部门 id（D4 由 `org_id` 改名，含所有后代可见） |

`Memory` 位置参数顺序保持
`content, scope, owner_id, project_id, tenant_id, department_id, ...`，
`project_owner_id` 追加在末尾。

`MemoryViewerContext` 字段：`tenant_id` / `user_id` / `role_keys` /
`primary_department_id` / `visible_department_ids` / `visible_project_keys` /
`active_project_id` / `session_participants`；属性 `is_valid` /
`is_full_access_admin` / `project_is_visible()` / `department_is_visible()`。
入口仅 `resolve_viewer_context()`（HTTP）与 `resolve_viewer_from_identity()`
（RAG 运行时）；`build_viewer_context()` 是纯构造器。

## 密度分层（017 FR-13/14/15）

`Memory` 的分层字段：

| 字段 | 含义 |
| --- | --- |
| `l0_summary` | 一句话结论（相关性预筛） |
| `l1_overview` | 概览 / 要点（决定是否下钻） |
| `l2_raw` | 原始细节（`== content`，按需取） |
| `tierable` | 是否可分层（二进制/不可抽取文本为 False） |
| `summary_generated_at` | 摘要生成时间戳（懒刷新判据） |
| `summary_refresh_days` | 刷新窗口，默认 30 |

**两条生成路径（FR-15）**：

1. **写时**：调用方传入 `l0_summary` / `l1_overview` + 新鲜的
   `summary_generated_at` → 首次读取零 LLM 成本；沉淀写时由
   `NoopSessionSummarizer` 兜底保证 L0 非空。
2. **读时懒兜底**：摘要缺失或 `is_summary_stale()` 为真时，调用注入的
   `Summarizer` 现场生成（T022 接线点在 `store.list_for_viewer` / retrieval）。

> ⚠️ 写时摘要**必须**同时打新鲜时间戳，否则会被懒刷新路径覆盖。

## 统一地址空间（021）

### 语法

```
mogo://memory/<personal|project|department>/<owner>/<id>/[L0|L1|L2]  017
mogo://resource/doc/<tenantId>/<documentId>/<chunkId>  005
mogo://resource/biz/<tenantId>/<system>/<type>/<recordId>  014
mogo://resource/kg/<tenantId>/<nodeId>              015
mogo://skill/<orgId>/<skillId>[/<version>]          004
mogo://skill/asset/<assetKey>                       018
mogo://session/<tenantId>/<sessionId>/[L0|L1|L2]    002
```

- 例：`mogo://memory/project/u1/m1` / `mogo://memory/department/u1/m1/L1`。
- `project_owner_id` **不进地址**（见 N1）；地址不含 `workspace` / `org` 段。
- tier 段**可省略**，省略时回落 `L0`。
- 每个 resource 子根的**第一段恒为 owning tenant**（租户隔离锚点）。

### 解析与分发

`parse_context_uri(uri)` 按 root 分发到对应 Address 对象；未知 root /
非 `mogo://` scheme / 旧 scope 段抛 `ValueError`（客户端错误，端点映射 404）。

`resolve_memory(uri, *, viewer: MemoryViewerContext, tenant_id="", ...)` 是
**唯一**运行时入口（`tenant_id` 仅供非 memory root 的粗守卫，缺省取
`viewer.tenant_id`）：
路由到归属适配器 → 把 `viewer` 装进 `ViewerContext.memory_viewer` 委托可见性
→ 返回 `{"resolved": {...}, "trace": {...}}`。

### TierAdapter 接口

```python
class TierAdapter(ABC):
    root: str
    async def resolve(self, *, uri, tier, tenant_id, viewer) -> ResolvedTier: ...
```

**降本原则**：只有 `memory`（自由文本）需要 LLM 生成 L0/L1；
`doc` / `biz` / `kg` / `skill` / `asset` / `session` 复用后端既有结构化字段，
**不调 LLM**。

### 可见性委托矩阵

| root | 委托给 | 粗守卫 / 转发 |
| --- | --- | --- |
| `memory` | 017 `visible_to(memory, MemoryViewerContext)` | `ViewerContext.memory_viewer` 转发；缺 `memory` 或缺 viewer fail-closed；scope 规则（personal 仅 owner / project 比对 `(project_id, project_owner_id)` / department 比对 `visible_department_ids`） |
| `resource` | 005/014/015 租户隔离 | `addr.tenant_id == ctx.tenant_id` |
| `skill` | 004/018 org scope | `addr.identifiers[0] == ctx.tenant_id`；asset 交后端治理 |
| `session` | 002 参与者集合 | `addr.tenant_id == ctx.tenant_id` |

`ctx.tenant_id` 为空时视为「以归属租户为准」，放行（best-effort，非提权）；
memory root 不受此 best-effort 影响 —— 它只看 `visible_to`。

## HTTP 契约（生产入口）

`POST /api/v1/context/resolve` — 解析单个或批量地址。

请求：

```json
{
  "uri": "mogo://memory/project/u1/m1/L0",
  "uris": ["mogo://resource/kg/t1/n-42"],
  "tier": "L1",
  "session_id": "s1",
  "turn_id": "t1"
}
```

响应：

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "items": [
      {"uri": "...", "ok": true, "resolved": {"content": "...", "tier_used": "L0", "meta": {}}},
      {"uri": "...", "ok": false, "error": "visibility_denied", "reason": "visibility_denied"}
    ],
    "resolved_count": 1,
    "failed_count": 1,
    "traces": [ /* 统一检索轨迹，FR-17 */ ]
  }
}
```

- 批量上限 50；单条失败**不影响**同批其他项。
- 未知 root / 非 `mogo://` → **400**（客户端格式错误）；
  旧 `workspace` / `org` 地址 → **404**（视为不存在、不泄露）；
  地址不存在 / 不可见 → `200` + 逐项标记。
- 轨迹进内存环形缓冲（200 条，可回看），属可观测通道，**不进 001 审计流**。
- `GET /api/v1/context/trace/{id}` 按 `MemoryViewerContext.tenant_id` 做租户守卫，
  跨租户 404。

### 017 写入 / 提升端点（B-6 / B-9）

- create：scope 仅三新值，旧值 / 显式 `workspace_id` / `org_id` →
  `400 scope_invalid`；`project` 由服务端按 `visible_project_keys` 校验并固化
  `project_owner_id`（客户端 `project_owner_id` 忽略，`"default"` →
  `400 default_project_not_shareable`，非成员 → `403 project_not_member`）；
  `department` 需 `is_full_access_admin` 且 `department_id` 在
  `visible_department_ids`。
- list：旧 `scope` 查询值 → `400 scope_invalid`；响应逐条回显
  `actual_scope` / `resolved_from`（`explicit|default|default_fallback|sediment`，
  **无 `legacy_alias`**）/ `project_id` / `project_owner_id` / `department_id`。
- delete / promote：不可见 404、未授权 403；promote 走
  `update_fields()` 增量 `$set`。

## 会话沉淀接线（FR-20）

```
POST /api/sessions/{id}/end
  → SessionPersistenceService.end_session()      置 ended_at / end_reason（幂等）
  → dispatch_session_end()                       009 事件派发
  → _on_session_end_event()                      017 订阅者
  → sediment_session_end() → on_session_end() → MemoryStore.save() 分层记忆落库
```

- 项目上下文来源（046 **会话取值来源优先级**，非 017 字段回退）：
  `session_doc.project_id` → `session_doc.workspace_id`（046 迁移期会话字段）
  → 空；`resolve_default_scope(has_project_context=bool(project_id and
  project_id != "default"))`。
- 沉淀字段为 `project_id` / `project_owner_id`（不含 `workspace_id` / `org_id`）。
- `DELETE /api/sessions/{id}` 仅对**从未结束过**的会话做兜底沉淀（经账本去重）。

## 存储

`memories` 集合，按 `(memory_id, tenant_id)` upsert。文档字段：
`content` / `scope` / `owner_id` / `project_id` / `project_owner_id` /
`tenant_id` / `department_id` / 时间戳 / 分层字段 / provenance / `archived`。
分数字段与内容同文档存储，无独立向量库 —— 检索依赖 scope 过滤 +
权重排序（`department 3 > project 2 > personal 1`），非向量召回。
检索 trace 的 `skipped` 对每个被过滤记忆归因：
`scope_invisible` / `default_project_excluded` / `missing_project_owner` /
`archived` / `unknown_scope`（F-3）。
