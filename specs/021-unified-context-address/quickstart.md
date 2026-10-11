# Quickstart: Unified Context Address Space (021)

**Feature**: [spec.md](./spec.md) | [plan.md](./plan.md) | [tasks.md](./tasks.md)

本文件说明如何**启用并验证**统一上下文地址空间 `mogo://`，包括四类寻址、逐层加载、委托式可见性与检索轨迹回看。

---

## 1. 前置

- 特性 017（three-scope-memory）已落地（首期 tenant 样板，暴露 `mogo://memory/...` 根）
- 特性 005（knowledge-rag）已落地（`mogo://resource/doc/...` 根，citation 锚点）
- 特性 004（skillhub-lifecycle）已落地（`mogo://skill/...` 根，版本快照 digest）
- 特性 002（session-versioning）已落地（`mogo://session/...` 根，会话快照）
- 特性 009（hooks-interception）已落地（SessionStart/SessionEnd 钩子触发）
- 特性 001（gatekeeper）已落地（委托式可见性复用各后端权限码）

---

## 2. 四类统一寻址

```python
from app.context_address.address_space import ContextAddressSpace

addr = ContextAddressSpace()

# 解析任一 mogo:// URI
result = await addr.resolve("mogo://memory/workspace/u1/mem-123/L1")
# result.backend → "017-three-scope-memory"
# result.payload → (l0, l1, l2, tierable, provenance)

# 各类型根
uris = [
    "mogo://memory/<scope>/<owner_id>/<memory_id>/[L0|L1|L2]",      # 017
    "mogo://resource/doc/<tenant_id>/<document_id>/<chunk_id>",     # 005
    "mogo://resource/biz/<system>/<entity_type>/<record_id>",       # 014
    "mogo://resource/kg/<node_id>",                                  # 015
    "mogo://skill/<org_id>/<skill_id>/<version>",                    # 004
    "mogo://skill/asset/<asset_id>",                                 # 018
    "mogo://session/<tenant_id>/<session_id>/[L0|L1|L2]",           # 002
]

# 未知 type 根 → 明确报错
try:
    await addr.resolve("mogo://unknown/type")
except AddressError:
    pass
```

**验证**：给定 URI→路由到对应后端并解析；未知根→报错不静默；解析不触发数据复制（虚拟路由）。

---

## 3. 逐层加载（L0/L1/L2 按需）

```python
# 默认只注入 L0+L1，L2 不进上下文
candidates = await addr.retrieve(
    query="相关记忆",
    tenant_id="t1",
)
# candidates[0].l0 → 摘要（粗筛）
# candidates[0].l1 → 方向（定方向）
# candidates[0].l2 → None（默认不加载）

# 显式请求 L2
detail = await addr.detail(
    uri="mogo://memory/workspace/u1/mem-123/L2",
    layer="L2",
)
# detail.content → L2 详细内容
```

**验证**：检索返回→默认只含 L0+L1；显式请求 L2→返回 L2；非记忆类 L0/L1 由后端既有字段提供，不调 LLM。

---

## 4. 委托式可见性

```python
# 地址层不新建统一权限模型，委托各后端既有检查
results = await addr.retrieve(
    query="...",
    user_id="u1",
)

# 各后端可见性：
# memory → 017 visible_to（personal/workspace/org）
# doc → 005 retrieval_access_policy（租户/组织隔离）
# biz → 014 bizdata:read（001 权限码）
# kg → 015 kg:read（001 权限码）
# skill → 004 角色授权（006）+ 018 a2a_exposed
# session → 002 会话参与者集合 + share 可见范围

# 不可见项在候选中被静默剔除（不报错）
```

**验证**：跨范围/无权限 URI→候选中静默剔除；地址层无独立权限码，不新增 001 之外的授权面。

---

## 5. 检索轨迹可回看

```python
# 每次检索产出统一 retrieval_trace
trace = await addr.retrieve_with_trace(
    query="...",
    tenant_id="t1",
    session_id="session-1",
    turn_id=3,
)

# trace.hits → 命中项（uri/type/tier_used/命中原因）
# trace.skipped → 被跳过项及原因（不可见/相关性不足/未请求 L2）

# 按 trace_id 回看
history = await addr.get_trace(trace.trace_id)
# history.reasons → "为何命中/漏掉"

# 高价值命中抽样进 001 审计
```

**验证**：一次检索→1 条 trace 含全部命中与跳过；按 trace_id 回看→还原原因；轨迹含元数据→已脱敏。

---

## 6. 会话结合（消费 + 生产 + 归档）

```python
# 活跃会话消费（同一检索+轨迹机制）
results = await addr.retrieve(
    query="...",
    session_id="session-1",
    turn_id=5,
)

# 009 SessionEnd hook → 触发 017 分层记忆沉淀
# 002 SessionStart hook → 触发上下文解析预热

# 历史会话浏览
history = await addr.resolve(
    "mogo://session/t1/session-1/L1"
)
```

**验证**：活跃会话 turn→经 021 统一检索，轨迹绑定 session/turn；SessionEnd→触发 017 沉淀；历史会话→可浏览 L0/L1/L2。

---

## 7. 验证清单

| # | 验证项 | 期望 |
|---|---|---|
| 1 | 四类 URI 解析 | 路由到对应后端并解析 (l0,l1,l2,tierable) |
| 2 | 未知 type 根 | 明确报错，不静默 |
| 3 | 解析不复制数据 | 虚拟路由，不触发后端数据复制 |
| 4 | 默认加载 | 只含 L0+L1，L2 不进上下文 |
| 5 | 显式请求 L2 | 返回 L2 详细内容 |
| 6 | 非记忆类 L0/L1 | 由后端既有字段提供，不调 LLM |
| 7 | 跨范围 URI | 候选中静默剔除，不报错 |
| 8 | 地址层权限 | 无独立权限码，不新增授权面 |
| 9 | 检索轨迹 | 1 条 trace 含全部命中与跳过及原因 |
| 10 | 轨迹回看 | 按 trace_id 还原命中/漏掉原因 |
| 11 | 轨迹脱敏 | 含元数据但已脱敏（001 PII 策略联动） |
| 12 | 会话消费 | 活跃会话经统一检索，轨迹绑定 session/turn |
| 13 | SessionEnd 沉淀 | 触发 017 分层记忆沉淀 |
| 14 | 历史会话浏览 | 可经 mogo://session/... 浏览 L0/L1/L2 |

---

## 8. 单元测试

```bash
cd services/chat-api
PYTHONPATH=. python -m pytest \
  tests/test_context_address_space.py \
  tests/test_context_address_adapters.py \
  tests/test_retrieval_trace.py \
  -o asyncio_mode=auto -q
```

---

## 9. 说明

- 首期 tenant = memory（017），作为样板验证"目录树可浏览 + 检索轨迹"范式
- resource/skill/session 地址约定现在定、各 spec 反向声明，按节奏接入（不阻塞 017）
- 地址层是虚拟路由 + 适配器 + 轨迹，复用各后端库（与 017/005/004 "不重复建库"哲学一致）
- 不新建统一权限/能力模型，委托各后端既有鉴权
- 不训练摘要/embedding 模型，仅 memory 由上游 LLM 生成，其余复用既有字段
