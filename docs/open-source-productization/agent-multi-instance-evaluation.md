# 智能体多实例运行改造评估

> 状态：评估稿（未实现）
> 范围：`services/chat-api` 与其依赖的 `dsh-runtime-host`，不含桌面端 `local-browser-agent` 与 `admin-api` 独立扩缩
> 前提：私有化部署阶段（`docker-compose.yml`），后续可上 K8s

## 1. 目标

支持**同一套 movo 部署**通过多个 `chat-api` 实例（进程/容器）横向扩展，从而：

- 提高并发用户会话承载能力（当前单实例 CPU/RAM 受限于 DSH kernel 与工具执行）
- 允许滚动升级 chat-api（灰度、快速回滚）
- 为多租户分片（后续）留出入口

**不做**：同一会话在多个 chat-api 实例之间**同时**处理（会造成 kernel session 双写、事件顺序错乱）。

## 2. 现状盘点

### 2.1 相关组件

| 组件 | 位置 | 状态 | 有状态/无状态 |
|---|---|---|---|
| `chat-api` | `services/chat-api/app/main.py` | FastAPI，单实例 | **有内存状态**（见 2.2） |
| `dsh-runtime-host` | `services/chat-api/dsh/runtime-host/` | Node.js HTTP 服务 | HTTP 调用，天然可多实例 |
| `redis` | `docker-compose.yml:redis` | 已部署 | 已被 `admin-api`/`document-parser` 使用 |
| `mongo` | `docker-compose.yml:mongo` | 已部署 | 存 `agent_kernel_bindings` |
| Celery | 未部署 | 部署文档提到"后续承载多实例 Agent 路由" | — |

### 2.2 chat-api 进程内状态（关键障碍）

`services/chat-api/app/dsh_runtime/gateway.py`：

- `DshAgentKernelGateway._sessions: dict[str, _SessionBinding]` — 内存中的 session→runtime 绑定
- `DshAgentKernelGateway._runtimes: dict[str, _RuntimeBinding]` — 内存中的 runtime 索引
- `DshAgentKernelGateway._credential_refresh_locks: KeyedAsyncLock` — 凭据刷新锁

**多实例 chat-api 直接跑起来的效果**：同一 conversation 的两次请求若被负载均衡到不同实例，B 实例的 `_sessions` 里找不到 A 创建的 session，`attach_session` 会失败或产生不一致。

### 2.3 已具备的基础

- **`agent_kernel_bindings` 存储在 MongoDB**（`services/chat-api/app/dsh_runtime/bindings/repository.py`），已定义：
  - `binding_id` unique
  - `kernel_session_id` unique
  - `(tenant_id, conversation_id, current=True)` 唯一
  - `claim_turn` 使用 `find_one_and_update` 做乐观锁（`active_turn.status in [completed, failed, cancelled]`）
- **`kernel_session_id` 由 `dsh-runtime-host` 生成并返回**，是持久化的会话标识
- **Redis 已部署**并接入其他服务，可直接承载分布式锁/路由表
- **`DSH_RUNTIME_HOST_URL` 是环境变量**（`docker-compose.yml`），天然支持指向多个 host

## 3. 三个层次的改造目标

按耦合度递增拆成三层，可以独立交付：

### 层 A：`dsh-runtime-host` 水平扩展（最轻，无侵入）

**目标**：多个 `dsh-runtime-host` 实例共享同一份 runtime 命名空间。

**现状可行性**：`chat-api` 通过 HTTP 单点调用（`DSH_RUNTIME_HOST_URL` 一个 URL），要变多实例需要引入 LB 或客户端 round-robin。但**核心问题是 session 亲和性**——`resume_session` 必须命中同一个持有该 session 内存态的 host。

**改造选项**：
- **A1（推荐）**：把 `dsh-runtime-host` 前面挂一个 **sticky LB**（Nginx/Envoy 按 `X-Session-Id` header 做一致性哈希），host 端保持有状态。改造量：Compose 加 LB 服务 + 网关透传 header。
- A2：把 `dsh-runtime-host` 改为无状态（session 快照落 Mongo/Redis）——**不建议**，改动面太大，且 DSH 上游在演进，不宜自己造轮子。

**风险**：LB 一致性哈希需要 `hash_key = kernel_session_id`，网关（`DshAgentKernelGateway._transport`）需要在每次请求带该 header。改造点集中在 `services/chat-api/dsh/runtime-host/` 与 `docker-compose.yml`。

### 层 B：`chat-api` 无状态化 + 分布式会话路由（核心）

**目标**：chat-api 自身可水平扩展，任意实例都能处理任意会话请求。

#### B.1 把内存态外置到 Redis

对 `DshAgentKernelGateway` 引入可选的**分布式后端**：

| 内存字段 | Redis 化方案 | Key 结构 | TTL |
|---|---|---|---|
| `_sessions[session_id]` | Hash | `kernel:session:{session_id}` | 会话最后活跃 +2h |
| `_runtimes[runtime_id]` | Hash | `kernel:runtime:{tenant}:{profile}` | 24h |
| `_credential_refresh_locks` | 分布式锁（Redlock 或 SETNX） | `kernel:lock:cred:{runtime_id}` | 30s |

**改造范围**：
- `services/chat-api/app/dsh_runtime/gateway.py`：抽出 `SessionStore` / `RuntimeStore` 接口，提供 `InMemory*`（默认，测试用）与 `Redis*`（生产用）两个实现
- `services/chat-api/app/config.py`：新增 `KERNEL_STORE_BACKEND`（`memory` | `redis`），`KERNEL_REDIS_URL`
- `services/chat-api/requirements.txt`：如需 Redlock 引入 `redis-pylock`（可选，也可以直接用 Redis SET NX PX）

#### B.2 会话路由一致性（同一会话固定到某实例）

即便无状态化，同一个 `kernel_session` 的请求也**最好**落到同一个 chat-api 实例，好处：
- `credential_lease` 的短命 token 缓存命中率更高
- 避免同一会话在两个实例同时 `claim_turn` 造成乐观锁重试

**方案**：Nginx/Envoy 按 `conversation_id` 一致性哈希到 chat-api 实例池。

```
nginx.conf（伪）
upstream chat_api_pool {
  hash $conversation_id consistent;
  server chat-api-1:8000;
  server chat-api-2:8000;
  server chat-api-3:8000;
}
```

`conversation_id` 需要从 URL path / header 提取；当前 `sessions.router` 挂在 `/api/sessions/{session_id}` 附近，需确认字段命名一致（见 `services/chat-api/app/main.py`）。

#### B.3 `agent_kernel_bindings` 已就绪

`KernelBindingRepository.claim_turn` 的乐观锁就是为多实例设计的，`find_one_and_update` 天然原子。唯一需要确认的是**跨实例的 `turn_runner` 幂等性**——若 A 实例抢占了 turn 崩溃，B 实例是否能接管？看 `services/chat-api/app/dsh_runtime/turn_recovery.py`（当前应该已有崩溃恢复逻辑）。

### 层 C：`Browser Agent WebSocket` 集群路由

**目标**：桌面端 `/api/agent/connect` 在 chat-api 多实例后仍能让 agent 消息正确路由。

**现状**：Nginx 目前应该直接把 WS 转到单点 chat-api（`docker-compose.yml` 的 nginx 段），要引入 **Nginx `sticky` / `ip_hash`** 或 `mod_upstream_sticky` 让同一客户端始终连同一后端。

**注意**：WS 长连接 + 滚动升级时会有连接闪断，客户端需要重连重试逻辑（应已在 `apps/local-browser-agent` 中实现，需核实）。

## 4. 推荐落地顺序

按"最小可交付 → 逐步深化"：

| 阶段 | 内容 | 复杂度 | 阻塞依赖 |
|---|---|---|---|
| **P1** | 层 A：LB + sticky 让 `dsh-runtime-host` 可 2 实例 | 低 | 无 |
| **P2** | 层 B.1：`SessionStore`/`RuntimeStore` 抽象 + Redis 实现 | 中 | P1 完成后开始验证 |
| **P3** | 层 B.2：chat-api 前面挂一致性哈希 LB | 低 | P2 |
| **P4** | 层 C：WS sticky 路由 | 低 | P3 |
| **P5** | Compose `deploy.replicas` + K8s Deployment 模板 | 中 | P1–P4 |

P1 + P3 + P4 是**架构正确性**的必要条件；P2 是**性能与稳定性**的锦上添花（不做的话，跨实例请求会重新 `discover_runtime` + `attach_session`，能跑但慢）。

## 5. 关键设计决策与开放问题

### 5.1 一致性 vs 可用性

- **强一致**：所有跨实例操作走 Mongo `claim_turn` 乐观锁（当前设计已支持）
- **弱一致**：Redis 存 session 元数据允许短暂脏读（例如 200ms 内两实例都看到 session 存在）——**推荐**，避免每次 attach 都读 Mongo

### 5.2 是否需要 Celery

文档提到"Redis 后续承载多实例 Agent 路由"。经评估，**celery 不是必需的**：
- 如果只做 sticky LB（层 A/C）+ Redis session store（层 B.1），路由是**同步 HTTP**，无需队列
- Celery 只在需要**异步任务解耦**时引入（例如"用户点了取消，异步去通知远端 kernel"）

**建议**：本轮不引入 Celery，避免多一套运维负担；等到有具体异步需求再评估。

### 5.3 多租户分片

本次不涉及。`RuntimeCoordinator.isolation_key = f"tenant:{tenant_id}:profile:{profile_version}"` 已经预留了租户维度，未来按 `tenant_id` 做 chat-api 实例分片是自然的下一步。

## 6. 风险清单

| 风险 | 等级 | 缓解 |
|---|---|---|
| `KernelHostTransport` 假设单个 `dsh-runtime-host`，加 LB 后可能出错（例如长连接复用） | 中 | P1 阶段做契约测试：并发 50 请求 + 3 个 host，验证 session 亲和性 |
| Redis 分布式锁实现错误导致 `_credential_refresh_locks` 死锁 | 中 | 优先使用 `redis-pylock`（已成熟），或退化为 SETNX + 超时；单点失败降级为无锁（凭据可能重复刷新，可接受） |
| Nginx 一致性哈希与 URL 字段不一致 | 低 | 先在 `deploy/docker/nginx.conf` 加注释和 `log_format` 输出 hash key 验证 |
| WS sticky 在滚动升级时客户端闪断 | 中 | 客户端已有重连；服务端可加 `X-Session-Resumed` 提示 |
| `agent_kernel_bindings` 唯一索引冲突处理 | 低 | 已有 `BindingReplacementConflict` 异常 |

## 7. 验收标准

- [ ] `docker compose up -d --scale chat-api=3 --scale dsh-runtime-host=3` 无报错
- [ ] 压测：200 并发用户 × 每人 1 会话，P99 latency 与单实例相当（±20%）
- [ ] 滚动升级 chat-api（kill 一个实例）后，进行中的会话无丢失（`claim_turn` 恢复）
- [ ] 单会话在两个实例间切换后，第 2 实例能 `attach_session` 成功并继续对话
- [ ] 审计日志中 `kernel_session_id` 与 `binding_id` 关联正确

## 8. 参考

- `specs/010-dag-orchestration-engine/spec.md` — 明确"不实现跨实例编排协调"
- `docs/open-source-productization/self-hosted-deployment-implementation-plan.md` — 提到 "Redis 后续承载多实例 Agent 路由"
- `services/chat-api/app/dsh_runtime/gateway.py` — `_sessions`/`_runtimes` 内存态
- `services/chat-api/app/dsh_runtime/bindings/repository.py` — `agent_kernel_bindings` MongoDB 结构 + `claim_turn` 乐观锁
- `docker-compose.yml` — `dsh-runtime-host` 与 `redis` 已就绪

## 9. 后续动作建议

1. 与核心团队确认本次目标是**多 chat-api 实例**还是**多 dsh-runtime-host 实例**（层 A 足够？还是需要层 B？）
2. 确认 Nginx 网关的 `conversation_id` 提取方式（URL 段 vs Header）
3. 确认 `apps/local-browser-agent` 的 WebSocket 重连逻辑是否支持多次重试
4. 若以上确认无异议，先做 P1（层 A）作为可交付里程碑
