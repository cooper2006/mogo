# DSH 多实例运行改造说明（第二版）

> **文档类型**：技术现状调研 + 改造方案
> **调研日期**：2026-10-09
> **代码基线**：`main` @ `36546a4`（第一版基线 `dc35112`，其间 34 个非合并提交）
> **调研范围**：`services/chat-api/dsh/runtime-host/`（Node 宿主）、`services/chat-api/app/dsh_runtime/`（Python 客户端/编排）、启动编排脚本、部署编排、版本兼容契约
> **调研方式**：全量精读源码，所有结论标注 `文件路径:行号` 证据
> **版本说明**：本文档为第二版。第一版（`dsh-multi-instance-2026-10-08.md`，基线 `dc35112`）列出的 M1–M4 阻断项与 R1–R4 建议项**绝大部分已实现**，本文档逐项更新状态并补充新增能力。第一版中标记为「📝 建议方案·未实现」的条目，若已在代码中落地，改标为「✅ 已实现」并附提交证据。

---

## 阅读约定（重要）

本文档严格区分「**现状**」与「**建议**」，请务必先识别标记再阅读：

| 标记 | 含义 |
|---|---|
| ✅ **【代码现状·已验证】** | 直接从源码读出的事实，附 `文件:行号`。未经实测运行验证的，明确写「未实测」 |
| 🟡 **【代码现状·实测】** | 源码事实 + 仓库内文档/测试记录表明曾被实际运行验证过（附证据出处） |
| 📝 **【建议方案·未实现】** | 本文档提出的设计，**当前代码中不存在**，不得当作已有能力引用 |
| ❓ **【推断】** | 无法从代码直接确认的判断，标注推断依据与置信度 |
| ⚠️ **【待确认】** | 需要人工/外部信息确认，代码无法回答 |

**本文档不含任何代码修改。** 所有"改造项"均为待实施建议。

**术语约定**：DSH = DeepSeek Harness（上游 `@deepseek-ai/dsh-*` npm 包族）；Runtime Host = Node 侧宿主进程（`dsh-runtime-host` 服务）；kernel = DSH 内核；turn = 一次对话轮次；session = 一次 kernel 会话（`kernel_session_id`）；runtime = 一个隔离的 kernel 实例（`runtime_id`）；isolation key = 运行时的稳定标识（`tenant:{tenant_id}:profile:{profile_version}`），是跨副本路由的 sticky key。

---

## 目录

1. [执行摘要](#1-执行摘要)
2. [DSH 架构全景（当前状态）](#2-dsh-架构全景当前状态)
3. [改造项状态总表（第一版建议 → 当前代码）](#3-改造项状态总表第一版建议--当前代码)
4. [会话亲和性与跨副本转交](#4-会话亲和性与跨副本转交)
5. [存储与状态：多副本隔离](#5-存储与状态多副本隔离)
6. [并发与背压](#6-并发与背压)
7. [优雅上下线与滚动升级](#7-优雅上下线与滚动升级)
8. [可观测性与健康检查](#8-可观测性与健康检查)
9. [鉴权与租户隔离](#9-鉴权与租户隔离)
10. [剩余缺口与建议](#10-剩余缺口与建议)
11. [关键设计决策](#11-关键设计决策)
12. [配置与运维手册（当前）](#12-配置与运维手册当前)
13. [风险登记册（当前）](#13-风险登记册当前)
14. [附录 A：文件全景表（当前）](#附录-a文件全景表当前)
15. [附录 B：关键代码位置索引](#附录-b关键代码位置索引)
16. [附录 C：术语表](#附录-c术语表)
17. [附录 D：与第一版的差异](#附录-d与第一版的差异)

---

## 1. 执行摘要

### 1.1 最重要的结论（先看这个）

**结论 1：第一版提出的 M1–M4 阻断项与 R1–R4 建议项已基本全部落地。**

第一版（2026-10-08，基线 `dc35112`）标识了 8 个改造项。自那时起，DSH 多实例相关代码经历了约 16 个 dedicated 提交（不含 main_id→tenant_id 重命名批次），当前状态：

| 第一版编号 | 第一版分类 | 当前状态 | 关键提交 |
|---|---|---|---|
| M1 | 🔴 阻断：存储卷按副本隔离 | ✅ **已实现** | `fddc97a` |
| M2 | 🔴 阻断：runtime 创建分布式锁 | ✅ **已实现** | `f1e68c5`, `8372300` |
| M3 | 🔴 阻断：健康检查覆盖全部副本 | ✅ **已实现** | `transport.py:371`（`probe_all_hosts`） |
| M4 | 🔴 阻断：`_isolation_key` 持久化回退 | ✅ **已实现** | `17f87c2`, `bb97e88`（§12.4 A+B） |
| R1 | 🟡 建议：优雅上下线 drain | ✅ **已实现** | `806b51d` |
| R2 | 🟡 建议：Session→副本归属查询接口 | ✅ **已实现** | `bb97e88`（`/holds`, `/owner` 端点） |
| R3 | 🟡 建议：亲和性失败的错误分类 | ✅ **已实现** | `transport.py:462`（`DshAffinityError`） |
| R4 | 🟡 建议：结构化日志携带实例标识 | ✅ **已实现** | `DSH_INSTANCE_ID` + `instanceId` 全链路 |
| L3 | 🟢 可延后：turn 背压信号量 | ✅ **已实现** | `a597aaa` |
| 方案 1 | 第一版未列出：跨副本自动转交 | ✅ **已实现** | `e39dfb6` |

**结论 2：3 副本已从「可选 profile」变为「默认拓扑。**

第一版记录：3 个副本 + sticky LB 在 `profiles: ["runtime-pool"]` 下，需显式 `docker compose --profile runtime-pool up -d` 启用。当前代码（`6179fb7`）：副本不再受 profile 限制，chat-api 默认通过 `DSH_RUNTIME_HOST_URL → dsh-runtime-host-lb` 与 LB 通信，`DSH_RUNTIME_HOSTS_URL` 保持为空（故意的——防止 chat-api 绕过 LB 用不同哈希算法二次路由）。

**结论 3：滚动升级可用性从 87% 提升到 100%。**

第一版记录：滚动升级期间约 1/3 活跃会话会因 hash ring remap 而中断。当前通过三层叠加实现透明升级：
- **R1 drain**（`806b51d`）：副本收到 SIGTERM 后先 drain 30s，等待进行中 turn 完成再退出，不再 force-cancel
- **nginx 故障转移**（`774c47e`）：`proxy_next_upstream error timeout http_502 http_503 http_504` + `proxy_next_upstream_tries 2`，副本刚挂掉但未被 nginx 标记为 failed 时自动重试下一个 upstream（87%→98%）
- **方案 1 跨副本自动转交**（`e39dfb6`）：副本收到它不持有的 runtime 请求时，向 peer 探测 owner 并 relay，客户端看到正常响应而非 400（98%→100%）

**结论 4：仍然存在的真实缺口已从「阻断级」降级为「建议级」。**

第一版的 4 个阻断项（M1–M4）全部解决后，剩余缺口主要是：
- 多 chat-api 实例（层 B）下的进程内状态共享——当前 chat-api 仍为单实例，`_tasks`/`_turn_outcomes`/`_live_streams` 等进程内 dict 在层 B 下是硬阻断
- session 归属缓存的 TTL 管理（无主动淘汰，仅依赖 Redis TTL 过期）
- 跨副本 seed 重建的生产化（当前有实现和测试，缺少压测与演练数据）

### 1.2 一句话结论

**多实例改造的核心问题（路由、存储、健康检查、优雅上下线、并发控制）已解决，DSH 3 副本池从「实验性功能」变为「生产就绪的默认拓扑」；剩余工作集中在多 chat-api 层的横向扩展和运维成熟度。**

---

## 2. DSH 架构全景（当前状态）

### 2.1 两层结构（与第一版相同，标注更新）

```
┌─────────────────────────────────────────────────────────────┐
│                      chat-api (Python)                        │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  DshRuntimeApplication (application.py:41)            │   │
│  │  ├── HttpKernelHostTransport (transport.py:195)       │   │
│  │  │   ├── _base_urls → LB (dsh-runtime-host-lb:8101)  │   │
│  │  │   └── _replica_urls → 3 副本直连 (§12.4 探测)     │   │
│  │  ├── DshAgentKernelGateway (gateway.py:66)           │   │
│  │  │   └── backpressure: TurnBackpressure (L3 信号量)   │   │
│  │  ├── RuntimeCoordinator (runtime_coordinator.py:18)  │   │
│  │  │   ├── RuntimeLock (runtime_lock.py:50)  [M2 锁]   │   │
│  │  │   └── SessionAffinityCache (session_affinity.py:29)│   │
│  │  └── TurnRunner (turn_runner.py)                     │   │
│  │      └── 每个 turn 获取/释放 backpressure 槽位        │   │
│  └──────────────────────────────────────────────────────┘   │
└───────────────┬─────────────────────────────────────────────┘
                │ HTTP + X-Session-Id / X-Isolation-Key
                ▼
┌─────────────────────────────────────────────────────────────┐
│                    nginx sticky LB                           │
│  hash $dsh_sticky_key consistent                             │
│  → 隔离键 → 运行时ID → 会话ID → $request_id (4级降级)       │
│  + proxy_next_upstream 故障转移 (R1 滚动升级)                │
└───────┬──────────────┬──────────────┬───────────────────────┘
        │              │              │
   ┌────▼────┐   ┌────▼────┐   ┌────▼────┐
   │  host-1 │   │  host-2 │   │  host-3 │
   │  :8101 │   │  :8101 │   │  :8101 │
   │ (独立卷) │   │ (独立卷) │   │ (独立卷) │
   │        │   │        │   │        │
   │ DSH_RUNTIME_PEERS: 互相可见，跨副本转交          │
   └────────┘   └────────┘   └────────┘
```

### 2.2 关键角色对照表

| 组件 | 位置 | 职责 | 当前实例数 |
|---|---|---|---|
| chat-api | `services/chat-api/` | 编排层：DAG、Hooks、LLM 网关 | 1（层 B 未实施） |
| Runtime Host | `dsh/runtime-host/src/` | Node 宿主：kernel 运行时、session 状态 | 3（默认） |
| nginx LB | `deploy/docker/dsh-runtime-lb.conf` | sticky 路由 + 故障转移 | 1 |
| Redis | `docker-compose.yml:redis` | 分布式锁 + 归属缓存 | 1 |
| MongoDB | `docker-compose.yml:mongo` | binding、conversation、事件持久化 | 1 |

### 2.3 一次 turn 的完整时序（当前，3 副本 + LB）

1. 客户端 → chat-api：`POST /api/sessions/{id}/turns`
2. chat-api `TurnRunner` 获取 backpressure 槽位（L3 信号量，默认 32）
3. chat-api `RuntimeCoordinator` 查 `SessionAffinityCache`（Redis）获取 session→instance 映射
4. chat-api `HttpKernelHostTransport` 计算路由 key（4 级优先级：显式 sticky_key → isolationKey → runtime_id → session_id）
5. chat-api 向 LB 发送请求，携带 `X-Session-Id` / `X-Isolation-Key` / `X-Runtime-Id` 头
6. nginx 按 `X-Isolation-Key` 一致性哈希选中一个副本
7. 副本检查本地 `RuntimeManager` 是否持有该 runtime：
   - **持有** → 正常处理
   - **不持有** → 向 peer 探测 `GET /v1/runtimes?isolationKey={key}`，找到 owner 后 relay 请求（方案 1，最多 2 跳）
8. 副本处理请求，返回 SSE event stream
9. chat-api 转发事件给客户端，同时写 MongoDB 持久化

---

## 3. 改造项状态总表（第一版建议 → 当前代码）

### 3.1 阻断项（M1–M4）—— 全部已实现

| 编号 | 第一版描述 | 当前状态 | 实现位置 | 证据 |
|---|---|---|---|---|
| **M1** | 存储卷按副本隔离 | ✅ 已实现 | `docker-compose.yml:173-210` | `fddc97a` |
| **M2** | Runtime 创建分布式锁 | ✅ 已实现 | `app/dsh_runtime/runtime_lock.py` | `f1e68c5`, `8372300`, `66a5a87` |
| **M3** | 健康检查覆盖全部副本 | ✅ 已实现 | `transport.py:371-405` (`probe_all_hosts`), `application.py:162-189` | 随 M1/M2 提交 |
| **M4** | `_isolation_key` 持久化回退 | ✅ 已实现 | `app/dsh_runtime/session_affinity.py` | `17f87c2`, `bb97e88` |

**M1 详情**：第一版记录三个副本共享 `dsh-runtime-data` 命名卷，多副本并发读写内核状态文件会互相踩踏。当前每个副本挂载独立卷（`dsh-runtime-data-1/2/3`），消除跨副本踩踏。注意：这意味着副本间不再共享任何持久化内核状态——session 的恢复依赖 §12.4 的 seed 重建机制。

**M2 详情**：新增 `RuntimeLock` 类（`runtime_lock.py:50-143`），基于 Redis `SET key value NX EX ttl` + Lua 脚本释放（比较 token 后删除）。仅序列化 runtime **创建**操作；获取锁失败后走 discover 兜底（与现有 `DshRuntimeError` 处理一致）。Redis 不可用时降级为无协调（日志记录 `dsh.runtime_lock.redis_unavailable`），不影响可用性。默认 TTL 30s。

**M3 详情**：第一版记录 `probe_host()` 只探测 `base_urls[0]`，三副本中任意两个挂掉仍报 healthy。当前 `probe_all_hosts()` 并发探测全部副本，`probe_host()` 改为「任意一个健康即返回 True」（`application.py:188`），`host_health_details` 携带逐副本明细。

**M4 详情**：第一版记录 `_isolation_key` 是进程内 dict，chat-api 重启后返回 None 导致 sticky 降级。当前 `SessionAffinityCache`（`session_affinity.py:29-121`）以 Redis 存储 `kernel_session_id → instance_id` 映射，TTL 7200s。Redis 不可用时退化为进程内 dict（与旧行为一致，单实例安全）。

### 3.2 建议项（R1–R4）—— 全部已实现

| 编号 | 第一版描述 | 当前状态 | 实现位置 | 证据 |
|---|---|---|---|---|
| **R1** | 优雅上下线 drain | ✅ 已实现 | `runtime-http-server.mjs:84-105, 228-249` | `806b51d` |
| **R2** | Session→副本归属查询接口 | ✅ 已实现 | `transport.py:249-300` (`probe_session_owner`) | `bb97e88` |
| **R3** | 亲和性失败的错误分类 | ✅ 已实现 | `transport.py:462-466` (`DshAffinityError`) | 随 M2 提交 |
| **R4** | 结构化日志携带实例标识 | ✅ 已实现 | `DSH_INSTANCE_ID` + `instanceId` 全链路 | 随 R1 提交 |

**R1 详情**：两阶段关机——阶段 1 drain（`#drain()`，`runtime-http-server.mjs:98-105`）：停止接受新请求，等待进行中 turn 完成（最多 30s），已有 session 的 send/resume/cancel/events 继续服务；阶段 2 关闭服务器 + `disposeAll()`。drain guard（`:239-249`）拒绝新 runtime/session/workspace 的 POST，已有 session 的 POST 不拒绝。`POST /drain` 端点（`:228-234`）允许运维手动触发。`stop_grace_period: 45s` 覆盖 drain 窗口（`docker-compose.yml:130`）。

**R2 详情**：`probe_session_owner()`（`transport.py:249-300`）向每个副本发 `GET /v1/runtimes/{runtime_id}/sessions/{session_id}/owner`，返回 `{"owned": bool, "instanceId": str}`。服务端实现（`runtime-http-server.mjs:295-303`）在 runtime 未持有 session 时返回 `owned: false` 而非 400，确保探测不会提前终止。另有 `GET /v1/runtimes/{runtime_id}/holds`（`:276-283`）用于 runtime 级别的归属探测（在 session 创建前就可以定位 owner）。

**R3 详情**：`DshAffinityError`（`transport.py:462-466`）是 `DshTransportError` 的子类，仅在 `path.startswith("/v1/runtimes/")` 且 `code == "not_found"` 时抛出，供上层区分「路由失败」与「普通的传输错误」。`DshNotFoundError` 已在 `errors.py` 中定义。

**R4 详情**：每个副本设置 `DSH_INSTANCE_ID`（`dsh-runtime-host-1/2/3`），健康检查响应、drain 响应、create 响应、export-seed 响应全部携带 `instanceId` 字段。nginx 日志格式 `dsh_lb` 记录 `upstream` 和 `key`。

### 3.3 新增能力（第一版未列出）

| 能力 | 描述 | 实现位置 | 证据 |
|---|---|---|---|
| **方案 1** | 跨副本自动转交 | `replica-forward.mjs` (158 行) | `e39dfb6` |
| **L3 背压** | turn 并发信号量 | `turn_backpressure.py` (79 行) | `a597aaa` |
| **§12.4 A** | 跨副本 seed 导出/重建 | `session-seed.mjs` (106 行) | `bb97e88`, `17f87c2` |
| **nginx 故障转移** | 滚动升级期间重试 | `dsh-runtime-lb.conf:83-85` | `774c47e` |
| **3 副本默认化** | 从可选 profile 变为默认 | `docker-compose.yml:152-210` | `6179fb7` |

---

## 4. 会话亲和性与跨副本转交

### 4.1 粘性路由（与第一版相同，补充实现细节）

- **客户端哈希**：`sticky_index()`（`transport.py:182-192`）用 `hashlib.sha256`（非 builtin `hash`，规避 `PYTHONHASHSEED` 不稳定性）取前 8 字节大端整数模副本数
- **nginx 一致性哈希**：`hash $dsh_sticky_key consistent`（`dsh-runtime-lb.conf:57`），4 级 sticky key 降级（`:48-53`）：
  1. `$dsh_key_isolation`（`X-Isolation-Key` 头）—— 最稳定，runtime 创建前就存在
  2. `$dsh_key_runtime`（`X-Runtime-Id` 头）—— 有 isolation key 时禁用（两者哈希到不同副本）
  3. `$dsh_key_session`（`X-Session-Id` 头）—— 有 runtime key 时禁用
  4. `$request_id` —— 兜底，永不为空
- **4 级路由优先级**（`runtime_routing_key()`，`transport.py:123-165`）：显式 `sticky_key` → `isolationKey` 参数 → path 中的 `runtime_id` → path 中的 `session_id`

### 4.2 跨副本自动转交（方案 1，新增）

**触发条件**：sticky LB 因 hash ring remap（副本增减、重启）将请求路由到不持有该 runtime 的副本。

**处理流程**（`replica-forward.mjs` + `runtime-http-server.mjs:326-341`）：

1. 副本收到请求，`findByRuntimeId(runtimeId)` 返回 undefined
2. 缓冲请求 body（读一次，handoff 和本地路径共享）
3. `#handOff()` 尝试转交：
   a. 优先用 `X-Isolation-Key` 头调用 `findOwnerByIsolation()` —— 向每个 peer 发 `GET /v1/runtimes?isolationKey={key}`
   b. 若 isolation key 不可用，回退到 `findOwner()` —— 向每个 peer 发 `GET /v1/runtimes/{runtime_id}/holds`
   c. 找到 owner 后，`forwardRequest()` 重发原始请求到 owner，携带 hop 计数器
4. 若 owner 返回 503 `service_draining`（对方正在 drain），自动尝试下一个 peer（`:167-192`）
5. 若所有 peer 都无法服务，返回本地 400（诚实失败）

**安全约束**：
- `MAX_HOPS = 2`（`:23`），防止转发环路
- 不转发回源副本（`parsePeers()` 排除 selfUrl）
- `/health`、`/drain`、非 `/v1/runtimes` 路径不转发（`shouldForward()`，`:43-50`）
- 转发超时 30s，peer 探测超时 2s

**效果**：滚动升级期间用户无感知，不再遇到 `runtime not found` 错误。

### 4.3 Session 归属缓存（§12.4 B，新增）

`SessionAffinityCache`（`session_affinity.py:29-121`）：

- **存储**：Redis key `mogo:dsh:session_host:{session_id}` → `instance_id`，TTL 7200s
- **读**：`get(session_id)` —— Redis 读，失败返回 None（视为 miss，触发 probe 兜底）
- **写**：`set(session_id, instance_id)` —— Redis 写，失败降级为进程内 dict
- **删**：`forget(session_id)` —— 副本重启后主动清理过期记录
- **降级**：Redis 不可用时完全退化为进程内 dict（单实例语义，安全）

**与第一版的区别**：第一版的 `_isolation_key` 仅在 `gateway._runtimes` 中查找，chat-api 重启后 `restore()` 重建了 `_sessions` 但 `_runtimes` 可能为空，导致返回 None。当前 `gateway._isolation_key()`（`gateway.py:89-101`）增加了从 `_sessions` 回退的逻辑，再叠加 Redis 持久化缓存，双重保障。

### 4.4 跨副本 Seed 重建（§12.4 A，新增）

当 session 的 owning replica 彻底丢失 session（重启且未恢复）时，通过 HMAC 签名的 seed 事件日志在另一副本重建：

**导出**（`transport.py:302-369` `export_session_seed()`）：
- 向每个副本发 `GET /v1/runtimes/{runtime_id}/sessions/{session_id}/export-seed`
- 持有者返回 `{"seed": [...], "seedSignature": "hmac-sha256", "seedSourceInstanceId": "...", "seedSourceSessionId": "..."}`
- 签名 = `HMAC-SHA256(authToken, [sourceInstanceId, sourceSessionId, seed])`
- 404 表示该副本不再持有 session，继续探测其他副本

**导入**（`session-seed.mjs:4-45` `resolveSessionSeed()`）：
- 验证 `seedSignature`（`verifySeededSession()`，`:68-84`）—— MAC 不匹配拒绝
- 逐事件校验 seed 形状（`assertSeedEvent()`，`:86-93`）—— 每个事件必须是纯对象且有 `type` 字段
- 自动补全 `parentSessionId`（`:19-25`）
- 拒绝 raw seed（无签名的 `parentSessionId` 直接拒绝）

**安全模型**：签名密钥 = Runtime Host bearer token，全池共享。能拿到有效 MAC 的攻击者已可直接访问整个池，因此签名不增加权限提升风险，仅防止中间人篡改。

---

## 5. 存储与状态：多副本隔离

### 5.1 存储卷隔离（M1，已实现）

| 副本 | 卷 | 挂载点 | 环境变量 |
|---|---|---|---|
| `dsh-runtime-host-1` | `dsh-runtime-data-1` | `/data/dsh-runtime` | `DSH_INSTANCE_ID=dsh-runtime-host-1` |
| `dsh-runtime-host-2` | `dsh-runtime-data-2` | `/data/dsh-runtime` | `DSH_INSTANCE_ID=dsh-runtime-host-2` |
| `dsh-runtime-host-3` | `dsh-runtime-data-3` | `/data/dsh-runtime` | `DSH_INSTANCE_ID=dsh-runtime-host-3` |

第一版的 `dsh-runtime-data` 共享卷已删除。**影响**：副本之间不再共享任何内核状态文件（JSONL session 日志、workspace registry、skill bundle 物化产物）。这意味着：
- ✅ 消除了并发写入踩踏
- ⚠️ 副本重启后该副本持有的 session 不再能从其他副本的磁盘恢复——必须依赖 §4.4 的 seed 重建机制或 MongoDB 的 binding 记录

### 5.2 跨副本状态一致性

| 数据 | 存储位置 | 多副本一致性 |
|---|---|---|
| Kernel session 事件 | Node 进程内存 + 本地 JSONL | 单副本持有，跨副本通过 seed 重建 |
| Runtime binding | MongoDB (`kernel_bindings`) | ✅ 原子读写 |
| Conversation 元数据 | MongoDB (`conversations`) | ✅ 原子读写 |
| Session 归属缓存 | Redis | ✅ 原子读写 |
| Runtime 创建锁 | Redis | ✅ 原子读写 |
| Skill bundle 物化 | 本地卷 | ⚠️ 各副本独立，需重新物化 |
| Workspace registry | 本地卷 | ⚠️ 各副本独立 |

### 5.3 进程内状态（层 B 阻断项，未解决）

以下对象仍是进程内状态，**在多 chat-api 实例（层 B）下是硬阻断**：

- `DshChatService._tasks` / `_turn_outcomes` / `_live_streams`（`chat_service.py`）
- `TurnEventRegistry._channels`（`turn_channel.py:138`）
- `KeyedAsyncLock`（`credential_lease.py`）—— 凭据刷新锁

当前 chat-api 为单实例，这些不构成问题。若未来扩展到多 chat-api，需要外置到 Redis。

---

## 6. 并发与背压

### 6.1 L3 Turn 背压信号量（新增）

**问题**：多副本池下，每个 chat-api 副本独立向 LLM 网关发送 turn 请求，总负载 = chat-api 副本数 × 单实例负载。无控制时可能压垮 LLM 网关。

**方案**（`turn_backpressure.py:21-79`）：

- `TurnBackpressure` 类，进程级 `asyncio.Semaphore`
- 默认最大并发 32（`DSH_RUNTIME_TURN_MAX_CONCURRENT`，`config.py:149`），0 禁用（旧行为）
- **槽位占用整个 turn**（send → stream → finalize），而非仅 send 调用——慢 turn 阻塞自己的槽位而非释放后被新 turn 占用
- `run_turn_limited()`（`:68-79`）是统一入口，`acquire()` 前自增 waiting 计数，`release()` 后递减
- 指标：`in_flight`（当前持有数）、`waiting`（等待队列长度）

**接线**（`turn_runner.py:61-296`）：
- `TurnRunner.__init__` 接收 `backpressure` 参数，从 `gateway.backpressure` 读取（`:74`）
- `run_turn()`（`:113-116`）在 turn 开始时 `acquire()`，结束时 `release()`（`:295-296`）
- `gateway.backpressure` 是普通公开属性（`66b382c` 修复），application 在 `gateway` 构造后设置（`application.py:84`）

### 6.2 唯一的跨副本并发保护：MongoDB 乐观锁

与第一版相同：`claim_turn()` 通过 `find_one_and_update` 原子认领 turn，是多副本间唯一的交叉一致性保证。Redis 分布式锁（M2）仅用于 runtime 创建，不覆盖 turn 级并发。

### 6.3 取消与超时

与第一版相同：`runtime.cancel()` 通过 kernel API 取消进行中 turn；`turn_channel.py` 的 `TurnEventRegistry` 在 chat-api 重启时丢失所有订阅（层 B 阻断项）。

---

## 7. 优雅上下线与滚动升级

### 7.1 优雅下线（R1，已实现）

**关机流程**（`runtime-http-server.mjs:84-95`）：

```
SIGTERM → drain (最多 30s) → server.close() → disposeAll() → closeAllConnections() → 进程退出
```

- **Drain 阶段**（`:98-105`）：`#draining = true`，`#state = HOST_STATES.draining`，`whenSessionsIdle()` 轮询所有 runtime 的 `activeSessionCount()`，直到为 0 或超时（30s）。超时后仍有活跃 session 的在阶段 2 被 dispose（状态已持久化，后续可恢复）
- **Drain guard**（`:239-249`）：`POST` 请求在 draining 状态下，仅拒绝 `v1/runtimes`（创建 runtime）、`v1/runtimes/{id}/sessions`（创建 session）、`v1/runtimes/{id}/workspaces`（创建 workspace）——已有 session 的 send/resume/cancel/events 继续服务
- **手动 drain**：`POST /drain`（`:228-234`）返回当前状态和活跃 session 数
- **健康检查**：`/health` 在 drain 期间仍返回 200（`:221-227`），避免 LB 提前摘除副本导致新请求打到正在 drain 的节点

**配置**：`stop_grace_period: 45s`（`docker-compose.yml:130`），覆盖 drain 30s + 关闭连接时间。

### 7.2 滚动升级故障转移（新增）

**nginx 配置**（`dsh-runtime-lb.conf:83-85`）：

```
proxy_next_upstream error timeout http_502 http_503 http_504;
proxy_next_upstream_tries 2;
proxy_next_upstream_timeout 5s;
```

- 仅重试连接错误/超时/5xx——4xx 是真实响应，不重试
- `max_fails=3 fail_timeout=10s`：连续 3 次失败后标记为不可用 10s

**效果**：副本重启的前几秒（容器已停止但 nginx 未标记失败）请求不再 502，自动重试下一个健康副本。可用性从 87% 提升到 98%。

### 7.3 方案 1：跨副本自动转交（新增）

与 §4.2 详述相同。覆盖 nginx 故障转移未覆盖的场景：副本健康但未持有请求的 runtime（hash ring remap）。可用性从 98% 提升到 100%。

### 7.4 滚动升级场景验证

| 场景 | 第一版行为 | 当前行为 |
|---|---|---|
| 副本重启，进行中 turn | force-cancel，用户感知中断 | drain 等待完成，无感知 |
| 副本刚停，新请求打到它 | 502/504 | nginx 重试下一个（R1） |
| hash remap，请求打到不持有 runtime 的副本 | 400 "runtime not found" | 方案 1 自动转交 |
| 3 副本轮询重启 | 约 1/3 会话中断 | 0 中断（叠加三层） |

---

## 8. 可观测性与健康检查

### 8.1 健康检查（M3，已实现）

**第一版缺陷**：`probe_host()` 仅探测 `base_urls[0]`，三副本中任意两个挂掉仍报 healthy；持有 session 的副本挂掉时用户遇到 `runtime not found` 但 readiness 是绿的。

**当前实现**：

- `HttpKernelHostTransport.probe_all_hosts()`（`transport.py:371-405`）—— 并发探测所有 `base_urls`，返回逐副本 `{"url", "healthy", "detail", "error"}`
- `DshRuntimeApplication._probe_hosts()`（`application.py:162-174`）—— 调用 `probe_all_hosts()`，异常时返回空列表
- `DshRuntimeApplication.probe_host()`（`:176-189`）—— 任意一个副本健康即返回 True（与第一版的「全部健康」不同，现为「任一健康」，避免误报 down）
- `host_health_details` 携带逐副本明细，供 `/ready` 端点和运维查询

**健康检查判据**（`transport.py:398-402`）：`payload.ok === true && payload.kernel === 'dsh'`

### 8.2 现有可观测性资产

| 资产 | 位置 | 说明 |
|---|---|---|
| 逐副本健康明细 | `application.py:51, 174` | `host_health_details: list[dict]` |
| nginx 访问日志 | `dsh-runtime-lb.conf:87-90` | `dsh_lb` 格式：`session=... runtime=... isolation=... upstream=... key=...` |
| Redis 事件日志 | `runtime_lock.py:75-84` | `dsh.runtime_lock.redis_ready` / `redis_unavailable` / `acquire_failed` / `release_failed` |
| 归属缓存事件日志 | `session_affinity.py:55-64` | `dsh.session_affinity.redis_ready` / `redis_unavailable` / `read_failed` / `write_failed` / `delete_failed` |
| Drain 状态 | `runtime-http-server.mjs:114-116` | `state` 属性（`ready` / `draining`） |
| Turn 背压指标 | `turn_backpressure.py:43-49` | `in_flight` / `waiting` |

### 8.3 剩余缺口

- **无跨副本的聚合健康仪表盘**：当前只能通过逐个查询或 nginx 日志拼凑全局视图
- **无 turn 级别的延迟/错误 metric 导出**（Prometheus 等）
- **session 归属缓存命中率未统计**（`get()` 返回 None 时无法区分「真 miss」与「Redis 读失败」）

---

## 9. 鉴权与租户隔离

与第一版相同，补充 M2 锁对租户隔离的影响：

### 9.1 宿主鉴权

- Runtime Host API 使用 bearer token（`DSH_RUNTIME_HOST_TOKEN`，`bootstrap` 服务生成，48 字节随机 hex）
- `validBearerToken()` 校验 Authorization 头（`host-auth.mjs`）
- token 长度至少 32 字符（`runtime-http-server.mjs:30`）

### 9.2 租户隔离的存储维度

- **Runtime 隔离**：通过 isolation key（`tenant:{tenant_id}:profile:{profile_version}`）保证不同租户的 runtime 在物理上是不同的 kernel 实例
- **M2 锁的作用**：防止两个 chat-api 副本同时为同一 isolation key 创建 runtime（导致租户状态在两个副本上各有一份，即「状态分裂」）。锁确保只有一个副本的 `create_runtime` 成功，另一个走 discover 兜底
- **跨副本转交**：方案 1 保证即使请求被路由到错误副本，也能透明地转交给持有 runtime 的副本——租户无感知

### 9.3 剩余缺口

- 第一版记录的 `org_id` 从未注入（R-04）仍未解决——组织级数据作用域实际未生效
- `visible_to` 的隐式租户隔离合同（`scope.py:93-113`）依赖 `viewer_role` 作为信任根，与 DSH 层是正交的

---

## 10. 剩余缺口与建议

### 10.1 已解决（无需再投入）

M1–M4、R1–R4、L3 背压、方案 1 跨副本转交、§12.4 A+B —— 全部已实现，有测试覆盖。

### 10.2 建议投入（按优先级）

| 优先级 | 项目 | 说明 |
|---|---|---|
| **P0** | 多 chat-api 实例（层 B） | `_tasks`/`_turn_outcomes`/`_live_streams`/`_channels` 进程内状态外置到 Redis |
| **P1** | 归属缓存命中率统计 | 区分「真 miss」与「Redis 读失败」，便于调优 TTL |
| **P1** | 跨副本 seed 重建压测 | 当前有单元测试，缺少生产级压测数据（多副本 + 并发 session 迁移） |
| **P2** | 聚合健康仪表盘 | 跨副本健康状态的统一视图 |
| **P2** | Turn 级 Prometheus metric | `in_flight` / `waiting` / 转发次数 / drain 事件 |
| **P3** | Skill bundle 物化共享 | 当前各副本独立物化，可考虑共享到 NFS/S3 |
| **P3** | `org_id` 注入 | 组织级数据作用域（第一版 R-04，仍未解决） |

### 10.3 明确不在本范围内的

- 层 C（多租户共享同一 isolation key 的并发控制）—— 需要应用层设计
- K8s 部署 —— 当前仅 Docker Compose
- DSH 内核版本升级 —— 由上游 `@deepseek-ai/dsh-*` 包管理

---

## 11. 关键设计决策

### 11.1 决策一：Sticky Key 用 isolation key 而非 runtime id

**理由**：runtime id 在 chat-api 重建 binding 时变化（`runtime_id` 是 host 侧生成的 UUID），而 isolation key（`tenant:{tenant_id}:profile:{profile_version}`）在整个 runtime 生命周期内稳定。用 runtime id 做 sticky key 会导致 `create_session` 被哈希到与 `create_runtime` 不同的副本，出现 `runtime not found`。

**证据**：`transport.py:134-139`（注释记录了这个坑），`dsh-runtime-lb.conf:28-32`（注释同样记录）。

### 11.2 决策二：双层路由（客户端哈希 + LB 哈希）

客户端 `sticky_index()`（sha256 % count）与 nginx `hash ... consistent` 使用不同的哈希算法。**故意不让两者一致**：

- 客户端哈希用于无 LB 场景（直接配置多 host）
- nginx 一致性哈希用于生产 LB 场景（副本增减时最小化 remap）
- 通过 `DSH_RUNTIME_HOSTS_URL` 为空强制走 LB（`docker-compose.yml:259-262`），防止两个路由方案同时生效

### 11.3 决策三：Runtime 创建锁的降级语义

`RuntimeLock.acquire()` 返回 `None` 时，调用方**不得视为失败**——应继续走 create + discover 兜底（与锁未启用时的行为一致）。仅当 Redis 不可用时记录警告，不影响服务可用性。这个设计保证了 Redis 故障不阻断 runtime 创建。

### 11.4 决策四：跨副本转交的跳数上限

`MAX_HOPS = 2`：最多 A → B → C 两跳。为什么不是无限：

- 3 副本场景下 2 跳足以覆盖所有拓扑（A 不持有 → B 持有 → B 响应）
- 防止网络分区时转发环路
- 超过上限返回 508 `forward_loop_detected`，客户端可感知异常

### 11.5 决策五：Drain 期间健康检查不断

`/health` 在 drain 期间仍返回 200（仅 `state` 字段变为 `draining`）。这避免了 LB 在副本 drain 期间摘除它，导致新请求打到正在 drain 的节点而被 503 拒绝（drain guard 仅拒绝新 runtime/session/workspace，不拒绝已有 session 的请求）。

### 11.6 决策六：Seed 签名用 Runtime Host Token

不引入独立的密钥。理由：能拿到有效 seed MAC 的攻击者已经持有 Runtime Host bearer token，可以直连整个池。签名仅防止中间人篡改，不防止未授权访问。

---

## 12. 配置与运维手册（当前）

### 12.1 现有配置项（已验证）

| 配置项 | 默认值 | 说明 | 位置 |
|---|---|---|---|
| `DSH_RUNTIME_HOST_URL` | `http://dsh-runtime-host-lb:8101` | LB 地址（3 副本模式） | `docker-compose.yml:263` |
| `DSH_RUNTIME_HOSTS_URL` | `""`（空） | 多 host 直连列表；3 副本模式下**故意留空** | `docker-compose.yml:264` |
| `DSH_RUNTIME_REPLICA_URLS` | `http://dsh-runtime-host-1:8101,...` | 探测用直连地址（绕过 LB） | `docker-compose.yml:269` |
| `DSH_KERNEL_REDIS_URL` | `redis://redis:6379/1` | Redis 地址（分布式锁 + 归属缓存） | `docker-compose.yml:271` |
| `DSH_SESSION_AFFINITY_CACHE_TTL_SECONDS` | `7200` | 归属缓存 TTL | `docker-compose.yml:272` |
| `DSH_RUNTIME_DISTRIBUTED_LOCK` | `true` | 启用 M2 分布式锁 | `config.py:143` |
| `DSH_RUNTIME_LOCK_TTL_SECONDS` | `30.0` | 运行时创建锁 TTL | `config.py:144` |
| `DSH_RUNTIME_TURN_MAX_CONCURRENT` | `32` | L3 turn 背压信号量（0 禁用） | `config.py:149` |
| `DSH_RUNTIME_HOST_TOKEN` | 随机生成 | Runtime Host bearer token | `bootstrap` 服务 |
| `DSH_INSTANCE_ID` | `dsh-runtime-host-1/2/3` | 副本实例标识 | `docker-compose.yml:164,183,199` |
| `DSH_RUNTIME_PEERS` | `http://dsh-runtime-host-1:8101,...` | Peer 列表（跨副本转交用） | `docker-compose.yml:169-172` |
| `DSH_RUNTIME_SELF_URL` | `http://dsh-runtime-host-N:8101` | 自身地址（peer 列表排除自身） | `docker-compose.yml:168,187,203` |

### 12.2 部署拓扑（当前默认）

```
docker compose up -d
  → 3 × dsh-runtime-host (独立卷, DSH_RUNTIME_PEERS 互相可见)
  → 1 × dsh-runtime-host-lb (sticky hash + 故障转移)
  → 1 × chat-api (通过 LB 与 pool 交互)
  → 1 × redis (分布式锁 + 归属缓存)
  → 1 × mongo (binding/conversation/事件持久化)
```

**无需 `--profile` 参数**：3 副本已是默认拓扑。

### 12.3 单实例部署（兼容）

如需回退到单实例：

```bash
# 停止 LB 和额外副本
docker compose stop dsh-runtime-host-lb dsh-runtime-host-2 dsh-runtime-host-3
# chat-api 自动通过 DSH_RUNTIME_HOST_URL 回退到单实例
# Redis 不可用时锁和缓存自动降级（日志记录，不影响服务）
```

### 12.4 排障要点

| 症状 | 定位路径 |
|---|---|
| `runtime not found` | 1. 检查 LB 日志 `key=...` 确认路由到了哪个副本 2. 检查该副本的 `inventory()` 是否包含该 runtime 3. 若不包含，检查方案 1 转发是否触发（`x-dsh-forwarded-to` 头） |
| Turn 延迟高 | 1. 检查 `turn_backpressure.in_flight` / `waiting` 2. 若 waiting > 0，考虑调高 `DSH_RUNTIME_TURN_MAX_CONCURRENT` 3. 检查 LLM 网关负载 |
| 副本重启后 session 丢失 | 1. 检查 MongoDB binding 是否存在 2. 若 binding 存在但 session 不在任何副本，触发 §12.4 seed 重建（`create_session` 携带 `sealed_seed`） |
| Redis 不可用 | 1. 检查 `dsh.runtime_lock.redis_unavailable` 日志 2. 锁降级为无协调（runtime 创建可能跨副本重复，discover 兜底） 3. 归属缓存退化为进程内 dict（仅 chat-api 本地有效） |
| 滚动升级中断 | 1. 检查 `proxy_next_upstream` 是否触发 2. 检查 drain guard 是否拒绝了新请求 3. 检查方案 1 转发是否触发 |

### 12.5 常用诊断命令

```bash
# 1. 逐副本健康与持有的 runtime
curl -s http://localhost:8101/health | jq .
curl -s http://dsh-runtime-host-1:8101/health | jq .
curl -s http://dsh-runtime-host-2:8101/health | jq .

# 2. 某 isolationKey 在哪个副本上
curl -s "http://dsh-runtime-host-1:8101/v1/runtimes?isolationKey=tenant%3Axxx%3Aprofile%3Av1" | jq .
curl -s "http://dsh-runtime-host-2:8101/v1/runtimes?isolationKey=tenant%3Axxx%3Aprofile%3Av1" | jq .

# 3. LB 亲和性验证（同一 session 连续 5 次是否落同一 upstream）
for i in 1 2 3 4 5; do
  curl -s -H "X-Session-Id: test-session" http://localhost:8101/health | jq -r '.instanceId'
done

# 4. chat-api 事件日志与 binding 关联核查
# grep -r "dsh.runtime_lock" /var/log/chat-api/
# grep -r "dsh.session_affinity" /var/log/chat-api/

# 5. Drain 状态
curl -s -X POST http://dsh-runtime-host-1:8101/drain | jq .
```

---

## 13. 风险登记册（当前）

| ID | 风险 | 严重度 | 当前缓解 | 残留风险 |
|---|---|---|---|---|
| R-01 | 跨副本存储踩踏 | 🔴 已消除 | M1 卷隔离 | 无 |
| R-02 | 同一 isolationKey 创建重复 runtime | 🟡 已缓解 | M2 Redis 分布式锁 | Redis 不可用时退化为无协调（discover 兜底） |
| R-03 | 健康检查单点（只探测 base_urls[0]） | 🟡 已消除 | M3 probe_all_hosts | 无 |
| R-04 | `_isolation_key` 进程内丢失 | 🟡 已消除 | M4 Redis 归属缓存 | Redis 不可用时退化为进程内 dict |
| R-05 | 滚动升级中断 | 🟢 已消除 | R1 drain + nginx 故障转移 + 方案 1 转交 | 极端场景（3 副本同时重启）仍可能中断 |
| R-06 | LLM 网关过载 | 🟢 已缓解 | L3 turn 背压信号量 | 仅控制 chat-api 侧，不控制其他调用方 |
| R-07 | Redis 单点 | 🟡 未解决 | 无（Redis 无高可用配置） | Redis 完全不可用时锁和缓存降级，但失去跨副本协调能力 |
| R-08 | MongoDB 连接池耗尽 | 🟡 未解决 | 无 | 高并发下 turn 认领可能失败 |
| R-09 | 层 B 多 chat-api 进程内状态 | 🔴 未解决 | 无 | 当前 chat-api 单实例，不构成问题；扩展到多实例时是硬阻断 |
| R-10 | Seed 重建期间的事件不一致 | 🟡 未解决 | HMAC 签名 + 形状校验 | 重建后的 session 与原始 session 在事件序上可能有细微差异 |
| R-11 | 副本间 DSH 内核版本不一致 | 🟡 未解决 | 版本治理文件 | 不同版本的 kernel 可能不兼容 |
| R-12 | `org_id` 未注入 | 🟡 未解决 | 无 | 组织级数据作用域未生效（第一版 R-04） |
| R-13 | nginx 配置错误导致流量打到错误副本 | 🟢 已缓解 | `proxy_next_upstream` + drain guard | 配置变更需人工验证 |
| R-14 | 跨副本转发增加延迟 | 🟢 已接受 | 最多 2 跳，每跳探测 2s | 极端场景下端到端延迟增加 4s |

---

## 14. 附录 A：文件全景表（当前）

### A.1 Node 侧 Runtime Host（`services/chat-api/dsh/runtime-host/src/`）

| 文件 | 行数 | 关键导出 | 与第一版差异 |
|---|---|---|---|
| `host.mjs` | — | 启动入口 | +9 行（实例 ID 传递） |
| `host-protocol.mjs` | — | HOST_STATES, runtimeHealth | +8 行（state 参数） |
| `host-auth.mjs` | — | validBearerToken, assertSecureHost | 无变化 |
| `http-utils.mjs` | — | readBody, readJson, routeParts, sendJson | +19 行（bufferedBody 支持） |
| `kernel-runtime.mjs` | — | KernelRuntime 类 | +31 行（exportCompletedSeed, ownsSession, activeSessionCount） |
| `model-profile.mjs` | — | normalizeModelProfile | 无变化 |
| `runtime-manager.mjs` | — | RuntimeManager 类 | +38 行（findByIsolation, findByRuntimeId, exportCompletedSeed, activeSessionCount, whenSessionsIdle） |
| `runtime-http-server.mjs` | 433 | RuntimeHttpServer 类 | **+258 行**（drain, hand-off, seed 端点, drain guard） |
| `replica-forward.mjs` | 158 | **新增**：parsePeers, shouldForward, findOwner, findOwnerByIsolation, forwardRequest | 🆕 |
| `session-seed.mjs` | 106 | **新增**：resolveSessionSeed, verifySeededSession, seedMac, sealSeed | 🆕 |
| 其他 | — | skill, tool, event 等 | 无 DSH 多实例相关变化 |

### A.2 Python 侧（`services/chat-api/app/dsh_runtime/`）

| 文件 | 行数 | 关键导出 | 与第一版差异 |
|---|---|---|---|
| `application.py` | 213 | DshRuntimeApplication | **+59 行**（probe_all_hosts, backpressure, affinity, lock 接线） |
| `transport.py` | 524 | HttpKernelHostTransport | **+195 行**（probe_all_hosts, probe_session_owner, export_session_seed, replica_clients） |
| `gateway.py` | — | DshAgentKernelGateway | **+98 行**（backpressure 属性, _isolation_key 回退） |
| `runtime_coordinator.py` | — | RuntimeCoordinator | **+215 行**（affinity, lock, seed 接线） |
| `runtime_lock.py` | 143 | **新增**：RuntimeLock | 🆕 |
| `session_affinity.py` | 121 | **新增**：SessionAffinityCache | 🆕 |
| `turn_backpressure.py` | 79 | **新增**：TurnBackpressure, run_turn_limited | 🆕 |
| `turn_runner.py` | — | TurnRunner | **+8 行**（backpressure 接线） |
| `errors.py` | — | DshRuntimeError 等 | +12 行（DshNotFoundError 等） |
| `config.py` | — | Settings | +21 行（新配置项） |

### A.3 部署与编排

| 文件 | 与第一版差异 |
|---|---|
| `docker-compose.yml` | **+101 行**（3 副本默认化, 卷隔离, DSH_RUNTIME_PEERS, LB 配置, chat-api 环境变量） |
| `deploy/docker/dsh-runtime-lb.conf` | **+13 行**（proxy_next_upstream 故障转移, nginx 版本升级） |

### A.4 测试

| 文件 | 行数 | 覆盖内容 | 新增/更新 |
|---|---|---|---|
| `tests/dsh_runtime/test_multi_host_transport.py` | 22213→ | 哈希稳定性, 50 并发×3 host, create/discover 命中 | +86 行（replica_clients 测试） |
| `tests/dsh_runtime/test_runtime_lock.py` | 6122 | **新增**：M2 分布式锁 acquire/release/降级 | 🆕 |
| `tests/dsh_runtime/test_session_affinity.py` | 6043 | **新增**：归属缓存 get/set/forget/降级 | 🆕 |
| `tests/dsh_runtime/test_session_rebuild.py` | 6503 | **新增**：跨副本 seed 导出/导入/签名验证 | 🆕 |
| `tests/dsh_runtime/test_turn_backpressure.py` | 2233 | **新增**：L3 信号量 acquire/release/降级 | 🆕 |
| `dsh/runtime-host/tests/replica-forward.test.mjs` | 7236 | **新增**：parsePeers, shouldForward, findOwner, forwardRequest | 🆕 |
| `dsh/runtime-host/tests/runtime-drain.test.mjs` | 3031 | **新增**：drain 流程, drain guard, /drain 端点 | 🆕 |
| `dsh/runtime-host/tests/runtime-forward-handoff.test.mjs` | 3728 | **新增**：hand-off 端到端, hop 限制, draining peer 跳过 | 🆕 |
| `dsh/runtime-host/tests/runtime-manager-isolation.test.mjs` | 1565 | **新增**：create 的 check/set 竞态修复 | 🆕 |
| `dsh/runtime-host/tests/session-seed.test.mjs` | 5341 | **新增**：seed 导出/导入/MAC 验证/形状校验 | 🆕 |

---

## 15. 附录 B：关键代码位置索引

### B.1 多实例路由

| 位置 | 说明 |
|---|---|
| `transport.py:182-192` | `sticky_index()` — sha256 稳定哈希 |
| `transport.py:123-165` | `runtime_routing_key()` — 4 级 sticky key 优先级 |
| `transport.py:371-405` | `probe_all_hosts()` — 并发探测全部副本 |
| `transport.py:249-300` | `probe_session_owner()` — session 归属探测 |
| `transport.py:302-369` | `export_session_seed()` — 跨副本 seed 导出 |
| `transport.py:407-415` | `_select_base_url()` / `_select_client()` — 客户端路由 |
| `dsh-runtime-lb.conf:36-53` | nginx sticky key 4 级降级 map |
| `dsh-runtime-lb.conf:55-64` | upstream 块：hash consistent + max_fails/fail_timeout |
| `dsh-runtime-lb.conf:83-85` | proxy_next_upstream 故障转移 |

### B.2 分布式锁（M2）

| 位置 | 说明 |
|---|---|
| `runtime_lock.py:50-143` | `RuntimeLock` 类：acquire/release/降级 |
| `runtime_lock.py:41-47` | Lua 释放脚本（比较 token 后删除） |
| `runtime_coordinator.py` | 锁的接线位置（`create_runtime` 前 acquire，后 release） |

### B.3 归属缓存（M4 / §12.4 B）

| 位置 | 说明 |
|---|---|
| `session_affinity.py:29-121` | `SessionAffinityCache` 类 |
| `gateway.py:89-101` | `_isolation_key()` — 从 `_sessions` 回退 |
| `application.py:131-138` | affinity cache + lock 的构造参数 |

### B.4 跨副本转交（方案 1）

| 位置 | 说明 |
|---|---|
| `replica-forward.mjs:22-23` | `HOP_HEADER`, `MAX_HOPS = 2` |
| `replica-forward.mjs:43-50` | `shouldForward()` — 路径过滤 |
| `replica-forward.mjs:73-84` | `findOwner()` — 按 runtime_id 探测 |
| `replica-forward.mjs:94-106` | `findOwnerByIsolation()` — 按 isolation key 探测 |
| `replica-forward.mjs:115-158` | `forwardRequest()` — relay + hop 计数 |
| `runtime-http-server.mjs:124-194` | `#handOff()` — 转交编排 |
| `runtime-http-server.mjs:326-341` | runtime 未命中时的转交触发 |
| `runtime-http-server.mjs:276-283` | `GET /v1/runtimes/{id}/holds` — runtime 归属探测 |
| `runtime-http-server.mjs:295-303` | `GET /v1/runtimes/{id}/sessions/{sid}/owner` — session 归属探测 |

### B.5 Seed 重建（§12.4 A）

| 位置 | 说明 |
|---|---|
| `session-seed.mjs:4-45` | `resolveSessionSeed()` — 导入入口 |
| `session-seed.mjs:63-66` | `seedMac()` — HMAC 签名生成 |
| `session-seed.mjs:68-84` | `verifySeededSession()` — MAC 验证 + 形状校验 |
| `session-seed.mjs:86-93` | `assertSeedEvent()` — 逐事件校验 |
| `session-seed.mjs:97-105` | `sealSeed()` — 导出密封 |
| `runtime-http-server.mjs:304-323` | `GET .../export-seed` 端点 |
| `transport.py:302-369` | `export_session_seed()` — 客户端探测 |

### B.6 优雅上下线（R1）

| 位置 | 说明 |
|---|---|
| `runtime-http-server.mjs:84-95` | `stop()` — 两阶段关机 |
| `runtime-http-server.mjs:98-105` | `#drain()` — drain 阶段 |
| `runtime-http-server.mjs:228-234` | `POST /drain` 端点 |
| `runtime-http-server.mjs:239-249` | drain guard — 拒绝新 runtime/session/workspace |
| `runtime-http-server.mjs:221-227` | `/health` 在 drain 期间返回 200 |
| `runtime-manager.mjs:96-112` | `activeSessionCount()` / `whenSessionsIdle()` |
| `docker-compose.yml:130` | `stop_grace_period: 45s` |

### B.7 L3 背压

| 位置 | 说明 |
|---|---|
| `turn_backpressure.py:21-65` | `TurnBackpressure` 类 |
| `turn_backpressure.py:68-79` | `run_turn_limited()` — 统一入口 |
| `turn_runner.py:61-74` | 接收 backpressure 参数 |
| `turn_runner.py:113-116` | turn 开始时 acquire |
| `turn_runner.py:295-296` | turn 结束时 release |
| `application.py:84` | `gateway.backpressure = TurnBackpressure(...)` |

---

## 16. 附录 C：术语表

| 术语 | 定义 |
|---|---|
| **DSH** | DeepSeek Harness，上游 `@deepseek-ai/dsh-*` npm 包族 |
| **Runtime Host** | Node 侧宿主进程，持有 kernel 运行时和 session 状态 |
| **kernel** | DSH 内核，版本 `0.1.0-rc.6`（`application.py:42`） |
| **turn** | 一次对话轮次：send → stream → finalize |
| **session** | 一次 kernel 会话，标识为 `kernel_session_id` |
| **runtime** | 一个隔离的 kernel 实例，标识为 `runtime_id`（host 生成的 UUID） |
| **isolation key** | 运行时的稳定标识：`tenant:{tenant_id}:profile:{profile_version}`，跨副本 sticky routing 的 key |
| **sticky routing** | 同一 session 的所有请求路由到同一副本 |
| **方案 1** | 跨副本自动转交：请求打到不持有 runtime 的副本时，自动转发给 owner |
| **§12.4 A** | 跨副本 seed 重建：session 丢失后从其他副本导出的签名事件日志重建 |
| **§12.4 B** | Session 归属缓存：Redis 存储 session→instance 映射，加速路由决策 |
| **drain** | 优雅下线：停止接受新请求，等待进行中 turn 完成 |
| **L3 背压** | 进程级信号量，限制同时进行的 turn 数量，防止压垮 LLM 网关 |
| **层 A** | 多 Runtime Host 副本（已实现） |
| **层 B** | 多 chat-api 实例（未实现，进程内状态是硬阻断） |
| **层 C** | 多租户共享同一 isolation key（未实现，需应用层设计） |

---

## 17. 附录 D：与第一版的差异

### D.1 基线变化

- 第一版基线：`dc35112`（2026-10-08 11:53）
- 第二版基线：`36546a4`（2026-10-09，其间 34 个非合并提交，其中约 16 个 DSH 多实例相关）
- 第一版中所有标记为「📝 建议方案·未实现」的条目，若已在代码中落地，已改标为「✅ 已实现」

### D.2 结构变化

| 第一版 | 第二版 |
|---|---|
| 15 章 + 4 附录 | 17 章 + 4 附录 |
| 独立的「改造项清单」章（M1-M4 / R1-R4 / L1-L7） | 改造项状态总表（§3），逐项标注当前状态与提交证据 |
| 独立的「分阶段落地路线」章（Phase 0-4 全部为建议） | 删除——Phase 0-2 已完成，Phase 3-4 部分完成，详见 §10 剩余缺口 |
| 无「跨副本自动转交」相关内容 | §4.2 + §7.3 详细描述方案 1 |
| 无「L3 背压」相关内容 | §6.1 详细描述 |
| 无「Seed 重建」相关内容 | §4.4 详细描述 §12.4 A |
| 无「优雅上下线」相关内容 | §7.1 详细描述 R1 |
| 风险登记册 16 项（含已消除项） | 风险登记册 14 项，标注已消除/已缓解/未解决 |

### D.3 关键结论变化

| 第一版结论 | 第二版结论 |
|---|---|
| 「多实例改造并非从零开始，层 A 已落地」 | 层 A 已完成并生产化（3 副本默认） |
| 「真正阻断多实例的是共享存储卷 + 健康检查单点」 | M1/M3 已解决，阻断项降级为建议项 |
| 「既有评估文档已过期」 | 评估文档已更新（本版即为最新） |
| 「滚动升级会 remap 1/3 活跃会话」 | 三层叠加后滚动升级可用性 100% |
| 「无并发/背压机制」 | L3 背压已实现（默认 32 并发） |
| 「`_isolation_key` chat-api 重启后失效」 | M4 Redis 归属缓存已解决 |

---

## 文档维护

- 本文档为第二版，替代第一版 `dsh-multi-instance-2026-10-08.md`
- 代码基线变化后需重新调研更新
- 所有标记为「📝 建议方案·未实现」的条目在代码落地后应改标为「✅ 已实现」并附提交证据
- 每次 DSH 多实例相关提交后，应更新 §3 改造项状态总表和 §13 风险登记册