# Memory Context Contract (017 + 021)

> 017-three-scope-memory（三 scope 记忆 + 密度分层）与 021-unified-context-address
> （`mogo://` 统一地址空间）的对外契约。本文件定义 chat-api `app/memory/` 与
> `app/context_space/` 的接口与不变量；与 `specs/017-three-scope-memory/spec.md`、
> `specs/021-unified-context-address/spec.md` 配套。

## 核心模型：两条正交轴

| 轴 | 取值 | 管什么 | 强制点 |
| --- | --- | --- | --- |
| **范围轴** scope | `personal` / `workspace` / `org` | **谁能看** | `scope.visible_to()` |
| **密度轴** tier | `L0` / `L1` / `L2` | **喂多少** | `tiering.tier_content()` / `_select_tier()` |

一条记忆同时携带两者：`mogo://memory/org/u1/m1/L1` 表示「org 范围、第 1 密度层」。
**scope 不影响 tier 的降级规则，tier 不影响可见性判断** —— 两轴互不推导。

## 不变量

- **无越权（FR-2）**：`visible_to` 是唯一可见性判据，021 地址层**只委托不重写**。
  任何新增 root 必须委托其归属后端的既有检查，不得自行实现鉴权。
- **范围轴封闭**：`Memory.scope` 只能是 `personal|workspace|org` 三值，
  `Memory.__post_init__` 拒绝其他值。
- **升级需授权（FR-4）**：`promote_to_org` 仅 `full_access_admin` 角色可调用，
  否则抛 `MemoryAccessError`。
- **分层只降不升（FR-14）**：`_select_tier` 在高层缺失时向下退
  （`L1 → l0_summary → content`），**绝不返回空串**给上层。
- **FR-16 硬限制**：`tierable=False` 且内容超 `MEMORY_L2_HARD_MAX_BYTES`
  时**拒绝写入**（抛 `MemoryTooLargeError`），不静默截断。
- **写入必须 await（motor）**：`MemoryStore.save` 是 `async`，
  `replace_one` 必须 await，否则写入从未执行。这是本契约最易违反的一条。
- **地址可逆**：`MemoryAddress.uri()` → `parse_memory_uri()` 往返一致；
  `safe=""` 保证 id 内的 `/` 被百分号编码，路径不会被错误切分。
- **不可见即不泄露**：跨租户 / 越权地址在批量解析中以
  `reason="visibility_denied"` 逐项报告，**不返回任何内容字段**。
- **溯源必备（FR-19）**：会话沉淀的记忆带 `source_session_id` +
  `source_type="session"`，可回溯到 002 会话。
- **生命周期唯一（FR-20）**：一次会话**至多沉淀一次**（`_SEDIMENTED` 账本），
  `end → delete` 不产生重复记忆。

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
   `summary_generated_at` → 首次读取零 LLM 成本。
2. **读时懒兜底**：摘要缺失或 `is_summary_stale()` 为真时，调用注入的
   `Summarizer` 现场生成。

> ⚠️ 写时摘要**必须**同时打新鲜时间戳，否则会被懒刷新路径覆盖。

## 统一地址空间（021）

### 语法

```
mogo://memory/<scope>/<owner>/<id>/[L0|L1|L2]        017
mogo://resource/doc/<tenantId>/<documentId>/<chunkId>  005
mogo://resource/biz/<tenantId>/<system>/<type>/<recordId>  014
mogo://resource/kg/<tenantId>/<nodeId>              015
mogo://skill/<orgId>/<skillId>[/<version>]          004
mogo://skill/asset/<assetKey>                       018
mogo://session/<tenantId>/<sessionId>/[L0|L1|L2]    002
```

- tier 段**可省略**，省略时回落 `L0`。
- 每个 resource 子根的**第一段恒为 owning tenant**（租户隔离锚点）。

### 解析与分发

`parse_context_uri(uri)` 按 root 分发到对应 Address 对象；未知 root 或
非 `mogo://` scheme 抛 `ValueError`（客户端错误，非服务端错误）。

`resolve_memory(uri, *, tenant_id, viewer_id, ...)` 是**唯一**运行时入口：
路由到归属适配器 → 委托可见性 → 返回 `{"resolved": {...}, "trace": {...}}`。

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

| root | 委托给 | 粗守卫 |
| --- | --- | --- |
| `memory` | 017 `visible_to` | scope 规则 |
| `resource` | 005/014/015 租户隔离 | `addr.tenant_id == ctx.tenant_id` |
| `skill` | 004/018 org scope | `addr.identifiers[0] == ctx.tenant_id`；asset 交后端治理 |
| `session` | 002 参与者集合 | `addr.tenant_id == ctx.tenant_id` |

`ctx.tenant_id` 为空时视为「以归属租户为准」，放行（best-effort，非提权）。

## HTTP 契约（生产入口）

`POST /api/context/resolve` — 解析单个或批量地址。

请求：

```json
{
  "uri": "mogo://memory/org/u1/m1/L0",
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
- 未知 root / 非 `mogo://` → `400`；地址不存在 / 不可见 → `200` + 逐项标记。
- 轨迹进内存环形缓冲（200 条，可回看），属可观测通道，**不进 001 审计流**。

## 会话沉淀接线（FR-20）

```
POST /api/sessions/{id}/end
  → SessionPersistenceService.end_session()      置 ended_at / end_reason（幂等）
  → dispatch_session_end()                       009 事件派发
  → _on_session_end_event()                      017 订阅者
  → sediment_session_end() → MemoryStore.save() 分层记忆落库
```

`DELETE /api/sessions/{id}` 仅对**从未结束过**的会话做兜底沉淀（经账本去重）。

## 存储

`memories` 集合，按 `(memory_id, tenant_id)` upsert。分数字段与内容同文档存储，
无独立向量库 —— 检索依赖 scope 过滤 + 权重排序，非向量召回。
