# Code Review — 2026-10-06

**范围**：`services/chat-api` 未提交工作树（60 修改 + 11 新增路径），主线为 017 三段式记忆（density tier）与 021 统一上下文地址空间（`mogo://`）。
**基线**：`7d95ade`（main）。**Review 方式**：静态阅读 + 逻辑反证；本机无法跑 pytest（见文末环境限制）。
**性质**：目标代码为**未提交**的新增/改动，因此所有发现目前仅存在于工作树。

---

## 结论摘要

| 级 | 数量 | 说明 |
|---|---|---|
| **High** | 1 | 记忆可见性判定完全采信 URI，可跨用户读他人记忆（潜在，尚未接线） |
| **Medium** | 3 | 字节上限按字符数计量；死配置项；`org` 写权限未校验 |
| **Low** | 3 | 重复常量、`split()` 吞掉多余段、时间戳精度 |

**最重要的三件事**：
1. `check_memory_visibility` 判定身份时用的是**调用方 URI 里的** `scope`/`owner_id`，不是库里那条记录的真实 `owner_id` —— 同一租户内任意用户可读任意用户的 personal 记忆。
2. `MEMORY_L2_HARD_MAX_BYTES` 用 `len(content)`（字符数）校验，中文/日文内容实际字节数可达设定的 3 倍。
3. `MEMORY_SUMMARY_REFRESH_DAYS` 是死配置：改了 env 无任何效果，代码里散落三个硬编码 `30`。

---

## F1 · High（潜在）— 记忆可见性采信 URI，非库内记录

**位置**：`services/chat-api/app/context_space/visibility.py:48-58`
**触发链**：`router.py:38-48` → `visibility.py:52-58` → `scope.py:105-108`

```python
def check_memory_visibility(*, addr: MemoryAddress, ctx: ViewerContext) -> bool:
    from app.memory.scope import Memory, visible_to
    memory = Memory(scope=addr.scope, owner_id=addr.owner_id)   # ← 用 URI 的身份
    return visible_to(memory, viewer_id=ctx.viewer_id, ...)
```

**机制**（已反证）：
- `router.py:43` 只按 `memory_id` + `tenant_id` 取记录：`store.get(tenant_id=..., memory_id=addr.memory_id)`。库里的真实 `scope`/`owner_id` **从未参与比对**。
- `visibility.py:52` 用 URI 声明的 `scope`/`owner_id` **重新构造**一个 `Memory` 做可见性判定，丢弃真实记录。
- `scope.py:107-108`：`scope == "personal"` 时判定为 `viewer_id == memory.owner_id` —— 而 `owner_id` 是**调用方自己填的**。

**利用场景**：`tenant_id = t1` 内，用户 `u2` 请求
```
mogo://memory/personal/u1/<u1的真实memory_id>/L2
```
`scope=personal` + `owner_id=u1` 由 URI 提供 → `visible_to` 比对 `viewer_id("u2") == owner_id("u1")`？——若请求改为 `mogo://memory/org/u1/<u1的memory_id>`，`scope=org` 走 `scope.py:111-112` 的 `return viewer_id != ""`，**恒真**，`u2` 直接拿到 `u1` 的 L2 原文。甚至 `personal/<任意值>/<u1的memory_id>` 同样绕过（owner 与本人不符时被拒，但 org scope 恒通过）。

**爆炸半径**：限单租户（`store.get` 带 `tenant_id` 过滤），但**租户内横向**任意读。

**当前可达性**：`resolve_memory` 全仓仅被测试调用，**尚未接入任何 HTTP 端点**（`grep` 确认 `app/**` 下无生产调用方）。故定级 **High 而非 Blocker** —— 是埋好待接的雷。

**修复**（一行）：
```python
def check_memory_visibility(*, addr, memory: Memory, ctx: ViewerContext) -> bool:
    return visible_to(memory, viewer_id=ctx.viewer_id, ...)   # 用取回的真实记录
```
`router.py` 的 `check_visibility(addr=addr, ctx=viewer)` 改为同时传 `memory=memory`。

**顺带确认安全**：`store.get` / `delete` 均带 `tenant_id` + `resolve_main_id` 过滤（`store.py:179, 188-192`），租户隔离本身成立；`tenant_id` 取自 `_resolve_session_user` 的 `main_id` 而非 URI（`memory.py:11`），正确。

---

## F2 · Medium — `HARD_MAX_BYTES` 按字符数而非字节计量

**位置**：`services/chat-api/app/memory/store.py:84`

```python
hard_max = int(get_settings().MEMORY_L2_HARD_MAX_BYTES)
if not tierable and len(content) > hard_max:   # ← 字符数
```

`MEMORY_L2_HARD_MAX_BYTES = 1_000_000`（`config.py:159`）语义是字节，但 `len()` 返回字符数。中文/日文 1 字 = 3 字节，非分层的 CJK 内容可写入实际 **≈3 MB** 而非 1 MB；且写入后 `l2_raw` 原样落库（`store.py` `l2_raw=tier.l2_raw`），无下游兜底。

**修复**：`len(content.encode("utf-8")) > hard_max`。若 `content` 允许含 surrogate，需 `errors="replace"` 或先校验可编码性。

---

## F3 · Medium — `MEMORY_SUMMARY_REFRESH_DAYS` 死配置

**位置**：`services/chat-api/app/core/config.py:158`

该设置项定义后**无任何代码读取**（`grep` 全仓 0 次使用）。真实生效的是三处独立硬编码：
- `memory/tiering.py:27` `SUMMARY_REFRESH_DAYS_DEFAULT = 30`
- `memory/sediment.py:32` `SUMMARY_REFRESH_DAYS_DEFAULT = 30`（重复定义）
- `memory/store.py` `_row_to_memory` 里 `int(row.get("summary_refresh_days") or 30)`（第四处隐式 `30`）

部署方设 `MEMORY_SUMMARY_REFRESH_DAYS=7` 后毫无效果，还会以为已生效 —— 运维陷阱。`tiering.py` 与 `sediment.py` 各自定义同名常量属漂移隐患（一处改一处不改）。

**修复**：三处常量统一引用 `get_settings().MEMORY_SUMMARY_REFRESH_DAYS`；`store.py` 的 `or 30` 改为回退到该配置。

---

## F4 · Medium — `scope=org` 写入未校验角色

**位置**：`services/chat-api/app/api/endpoints/memory.py:19-21`

`create_memory` 校验了 `scope` 取值合法性，但**未校验调用方是否有权限写 `org`**。spec 与 docstring 明确 `org` 需 `full_access_admin`（FR-4，`scope.py:21-22` `ORG_PROMOTION_ROLES`），提升走 `promote_to_org`（有校验，`scope.py:127`）；但**直接创建**为 `org` 的路径跳过了这一步。任意用户可写一条 `org` scope 记忆，进而对全租户可见。

**修复**：`if scope == "org" and role not in ORG_PROMOTION_ROLES: raise HTTPException(403)`。

> 注：本文件当前处于另一会话的写入过程中（见 F7），以上按 `git diff` 内容评审。

---

## F5 · Low — `parse_memory_uri` 吞掉多余路径段

**位置**：`services/chat-api/app/memory/address.py:57-63`

```python
parts = uri[len(prefix):].split("/")
if len(parts) < 3: raise ValueError(...)
tier = unquote(parts[3]) if len(parts) >= 4 and parts[3] else "L0"
```

`len(parts) >= 4` 只读 `parts[3]`，`parts[4:]` 静默丢弃。`mogo://memory/personal/u1/m/L2/extra` 被当作 `tier=L2` 接受，不报错。不泄密，但会让地址解析对拼写错误宽容，掩盖调用方 bug。对照 `ResourceAddress.parse` 对段数做了精确断言（`!= 3` / `!= 4`），此处不对称。

**修复**：`if len(parts) > 4: raise ValueError(...)`。

---

## F6 · Low — 可见性测试验证的是构造器而非授权逻辑

**位置**：`services/chat-api/tests/context_space/test_address_visibility.py:99-103`

```python
addr = MemoryAddress(scope="personal", owner_id="u1", memory_id="m", tier="L0")
assert check_visibility(addr=addr, ctx=ViewerContext(viewer_id="u1")) is True
```

测试只用 URI 构造的地址断言可见性，**从不加载真实记录** —— 因此 F1 的越权在该用例中"通过"（`u1` 请求自己的地址确实应可见）。集成测试的 `_FakeMemoryStore.get`（`test_adapters_integration.py:126-137`）忠实返回了带真实 `owner_id="u1"` 的 `Memory`，但适配层没用它。**无一条用例尝试"以他人身份解析他人 memory_id"**，即缺越权回归测试。

**修复**：新增用例 —— 种子记录 `m-1`（owner `u1`），以 `viewer_id="u2"` 解析 `mogo://memory/org/u1/m-1/L2`，断言 `ContextVisibilityError`。F1 修复后该用例应绿，当前应红。

---

## F7 · 环境/流程观察（非缺陷）

- **`memory.py` 当前是截断的语法错误文件**（27 行 / 1,233 B / mtime 08:17:24，`ast.parse` 报 `IndentationError: unexpected indent`）。系另一会话写入中途被读取，**非本 review 的提交缺陷**，但确认工作树不稳定 —— 评审结论以 `git diff` 与新增文件为准。
- 提交前需确认该文件已写完并通过语法检查。

---

## 环境限制（影响结论强度）

以下检查**未能实际执行**，结论以静态阅读 + 逻辑反证为主：
- pytest 无法运行：DSH 自带 Python 3.12.14 的 `pydantic_core` 触发 macOS code-signing `different Team IDs`；系统 Python 3.9.6 低于项目要求的 3.10+；ServBay pip 不可用；Docker Python 3.13 不可达。**所有 finding 均未通过测试用例验证**。
- QualityForge 工具套件 9 个中 7 个因输出 schema 未声明字段而报错（`qf_plan`/`qf_exec`/`qf_record`/`qf_list`/`qf_update`/`qf_fixplan`/`qf_probe`），仅 `qf_scan`/`qf_report` 可用，故本次 review 未依赖该套件。

## 已确认安全（曾疑，实查无虞）

- **无硬编码密钥**：`config.py` 全部密钥默认空串，docker-compose 由 bootstrap 服务 `random_hex()` 运行时生成；`scripts/dev/internal_service_auth.sh` 用 `openssl rand`/`secrets.token_hex`。`qf_scan` 报的 20 处"疑似凭据"经核对均为测试脚本中的 test-only JWT secret。
- **密码学强度充足**：PBKDF2-HMAC-SHA256 ×120,000 迭代 + 16 字节随机盐；会话令牌 HMAC-SHA256 且用 `hmac.compare_digest` 防时序侧信道。
- **租户隔离成立**：`MemoryStore.get/delete`、`resolve_main_id`、端点侧 `tenant_id` 均取自已认证 session 的 `main_id`，非 URI。
- **无 Mongo 注入**：所有查询用参数字典，未见字符串拼接；`tenant.py` 的 `$or` 仅限 default 主租户匹配。

---

## 建议处置顺序

| 序 | 项 | 说明 |
|---|---|---|
| 1 | **F1** | 接线前必修。改动小（adapter 传 `memory`），收益大（堵住横向越权） |
| 2 | **F6** | 与 F1 同批：先写越权回归用例（当前应红），再修 F1 使其变绿 |
| 3 | **F4** | 一行角色校验，堵住 org 直写 |
| 4 | **F2** | 一行改为按 UTF-8 字节计量 |
| 5 | **F3** | 收敛三处 `30` 到配置项 |
| 6 | F5 | 收尾，收紧解析 |

F1+F6 应在任何调用 `resolve_memory` 的端点合入**之前**完成 —— 这是本轮唯一的时序硬约束。
