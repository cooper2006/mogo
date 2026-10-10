# DSH 多实例落地方案（审批稿）

> **文档类型**：落地实施方案（待审批）
> **日期**：2026-10-08
> **前置调研**：`deliverables/gstack/dsh-multi-instance-2026-10-08.md`（现状调研 + 改造项清单 M1-M4 / R1-R4 / L1-L7 / Phase 1-4 路线）
> **现状基线已核对**：调研文档所述 4 个阻断点当前代码**仍为真实状态**（已读 `docker-compose.yml` / `transport.py` / `gateway.py` 确认）。
> **本方案不改动任何代码**——仅给出范围、分 Phase、待拍板决策与验收标准，供审批。

---

## 1. 现状：什么已经能用，什么还卡住

### 1.1 已经具备（层 A 路由，无需再建）
- ✅ `HttpKernelHostTransport` 多 host 一致性哈希路由（`transport.py:194-235`）
- ✅ `DSH_RUNTIME_HOSTS_URL` 配置项 + `configured_runtime_hosts()` 装配（`config.py:125` / `application.py:61-66`）
- ✅ 三副本 + nginx sticky LB 的 compose profile（`docker-compose.yml:152-190`，`runtime-pool`）
- ✅ nginx `hash $dsh_sticky_key consistent`（`deploy/docker/dsh-runtime-lb.conf:50-58`）
- ✅ 29 项多 host 契约测试（`tests/dsh_runtime/test_multi_host_transport.py`）

**结论**："路由层"已支持多实例。真正卡住生产多副本的是**存储层**与**健康检查单点**。

### 1.2 真正卡住生产多副本的问题（按严重度）

| 编号 | 问题 | 严重度 | 性质 | 对应改造项 |
|---|---|---|---|---|
| **R-02** | `_isolation_key` 从进程内 `_runtimes` 取，chat-api 重启后返回 `None` → sticky 降级为 `runtime_id` → **全部既有会话路由失败** | 🔴 致命 | 每次 chat-api 重启**必然发生** | M4 |
| **R-03** | `/health` / `/ready` 只探测 `base_urls[0]` → 副本级故障被假绿/假红 | 🔴 高 | 多副本下**必然发生** | M3 |
| **R-01** | 三副本共享 `dsh-runtime-data` 卷 → session JSONL / workspace registry 跨副本踩踏 | 🔴 致命 | 触发条件：sticky 降级或 LB 重排 | M1 |
| **R-05** | 同 `(tenant, profileVersion)` 在多副本各建一份 runtime，租户状态分裂 | 🟠 高 | 无跨副本唯一性 | M2 |

> 注：R-01 当前因"共享卷"而**暂时能 resume**（JSONL 读得到），但代价是踩踏风险；一旦做 M1（卷隔离），resume 会**显式失败**（§12.4 核心开放问题）。这是落地顺序的核心矛盾。

---

## 2. 推荐落地范围与顺序

### 2.1 关键判断：先削"每次重启必然炸"的致命项，再做"破坏性"的存储隔离

把改造拆成两段，**先做纯增量、零破坏、单实例行为不变的一段**，把生产多副本的门槛降到最低，再做需要破坏性/外部依赖的一段：

#### Phase 1（强烈建议先做，纯增量、可 `git revert`、单实例行为不变）
| 改造项 | 类型 | 解决的问题 | 向后兼容 |
|---|---|---|---|
| **M4** `_isolation_key` 持久化回退（绑定记录带 `isolation_key`，永不降级 runtime_id） | 🔴 | R-02（致命） | ✅ 方案一无需 schema 变更 |
| **M3** 健康检查探测全部副本并聚合；`/ready` 改为"任一健康即 200" | 🔴 | R-03（高） | ✅ 单 host 行为等价 |
| **R4** 宿主日志带 `instanceId`（新增 `DSH_INSTANCE_ID`，出现在 `/health` 与错误体） | 🟡 | R-09 排障 | ✅ |
| **R3** 亲和性失败错误分类（`DshAffinityError` 区分 `runtime not found` / `session is not live` / 网络错） | 🟡 | R-07 排障 | ✅ |

**Phase 1 收益**：即使**不启用多副本**，也消除 chat-api 重启后全量路由失败的致命隐患；启用多副本后健康检查正确。**无数据迁移、可整段回退。**

#### Phase 2（需单独审批——因 M1 破坏性）
| 改造项 | 类型 | 解决的问题 | 风险 |
|---|---|---|---|
| **M2** runtime 唯一性：Redis `SET dsh:runtime:{isolationKey} NX PX` 锁（`DSH_KERNEL_REDIS_URL`，复用现有 redis DB/1） | 🔴 | R-05 | 中（Redis 不可用时降级当前行为，R-12） |
| **M1** 存储卷按副本隔离（三卷 → `dsh-runtime-data-1/2/3`） | 🔴 | R-01 | **高（破坏性）**：既有 session resume 失效，需 §12.4 兜底 |

**Phase 2 的 M1 是核心开放问题**（§12.4）：卷隔离后跨副本 resume 失败。文档推荐 A+B 组合（session→host 缓存 + `exportCompletedSeed` 重建兜底）。**此迁移能力建议与 M1 同批落地或先落地，不可先裸做 M1。**

#### Phase 3 / Phase 4（延后）
- 压测与契约测试扩充、R1 优雅上下线（drain）、§12.4 session 跨副本迁移、跨版本灰度演练、L3 背压。
- 这些不阻塞"多副本安全可用"，按资源排期。

---

## 3. 待用户拍板的关键决策

> 以下决策决定 Phase 2 是否启动以及 M1 的兜底方式，请在审批 Phase 1 时一并答复。

### 决策 D1：是否启用 `runtime-pool` 多副本作为默认？
- **建议**：保持**单实例默认**（不改变现有部署行为），但合并 Phase 1（单实例也受益）。多副本仍作为 `docker compose --profile runtime-pool up` 的 opt-in。
- 备选：默认三副本。→ 会改变所有部署形态，不建议。

### 决策 D2：M1 存储卷隔离的兜底策略（Phase 2 核心矛盾）
选项：
- **(a) 接受重建会话**：每副本独立卷，既有 session 在新拓扑下重新创建（对话历史靠 `exportCompletedSeed` 部分保留）。最简单，但用户体验有损。
- **(b) 先做 §12.4 的 session→host 缓存 + 归属查询，再隔离卷**：用户无感，但工作量最大（Phase 4 级别）。
- **(c) 暂不做 M1，仅做 M2（Redis 锁）+ Phase 1**：维持当前"共享卷能 resume"的现状，靠 M2 消除同 isolationKey 多 runtime、靠 M4/M3 消除路由与健康检查致命项。**多副本可安全启用，但不解决极端情况下的 JSONL 踩踏**（踩踏仅在 sticky 降级/LB 重排时触发，而 M4 已大幅降低降级概率）。
- **建议**：**先走 (c)，把"多副本安全可用"的门槛降到最低**；M1 隔离卷 + 迁移能力作为后续独立 Phase，单独评估破坏性。

### 决策 D3：Redis 复用
- **建议**：M2 复用现有 `redis` 服务，使用独立 DB（`redis://redis:6379/1`），与 admin-api/doc-processing 的 DB/0 隔离。新增配置 `DSH_KERNEL_REDIS_URL`。

### 决策 D4：Phase 1 是否包含 R3/R4
- **建议**：包含（低成本、纯增量，显著提升多副本排障能力）。若想最小范围，可只做 M4+M3。

---

## 4. Phase 1 具体改动清单（落地时实施）

| 文件 | 改动 |
|---|---|
| `services/chat-api/app/dsh_runtime/gateway.py` | `_SessionBinding` 增加 `isolation_key` 字段；`attach_session` / `discover_runtime` 填充；`_isolation_key()` 从绑定取，不再因重启返回 None（M4） |
| `services/chat-api/app/dsh_runtime/application.py` | `probe_host()` → 新增 `probe_all_hosts()` 并发探测 `_base_urls` 全部 `/health`（M3） |
| `services/chat-api/app/dsh_runtime/transport.py` | 新增 `probe_all_hosts()` 方法（对 `_base_urls` 并发 GET `/health`）（M3） |
| `services/chat-api/app/main.py` | `/health` 返回逐副本明细；`/ready` 判定改为"任一健康即 200"（M3） |
| `services/chat-api/app/dsh_runtime/transport.py` + `gateway.py` + `errors.py` | 区分 `runtime not found` / `session is not live` / 网络错，新增 `DshAffinityError`（R3） |
| `services/chat-api/dsh/runtime-host/src/host.mjs` + `runtime-http-server.mjs` + `host-protocol.mjs` | 引入 `DSH_INSTANCE_ID`（compose 服务名），出现在启动日志、`/health`、`runtimeHealth`、错误响应体（R4） |
| `docker-compose.yml` | `dsh-runtime-host-1/2/3` 增加 `DSH_INSTANCE_ID` 环境变量（R4）；不改动卷定义 |

**Phase 1 验收标准**（引用调研文档 §13 Phase 1）：
- 单 host 下 `/health` `/ready` 行为逐字节不变
- 多 host 下 `/health` 返回逐副本明细（含 instanceId、runtimes 数）
- 仅副本 1 挂掉时 `/ready` 仍 200；全部挂掉时 503
- chat-api 重启后既有 session 继续 `send` 成功（M4）
- 亲和性错误被分类为 `DshAffinityError`（R3）
- 每条宿主日志含 `instanceId`（R4）
- `pytest tests/dsh_runtime/ -q` 与 `node --test runtime-host/tests/` 全绿

---

## 5. Phase 2 具体改动清单（待 D2 决策后实施）

| 文件 | 改动 |
|---|---|
| `services/chat-api/app/dsh_runtime/runtime_coordinator.py` | `create_runtime` 前获取 Redis 锁 `dsh:runtime:{isolationKey}`；失败则走既有 discover 兜底；dispose 时释放（M2） |
| 新增 `services/chat-api/app/dsh_runtime/runtime_lock.py` | Redis 分布式锁封装，Redis 不可用时降级（M2） |
| `docker-compose.yml` | 卷按副本隔离 `dsh-runtime-data-1/2/3`（M1，若 D2 选 a/b） |
| `services/chat-api/app/core/config.py` | 新增 `DSH_KERNEL_REDIS_URL`、`DSH_RUNTIME_DISTRIBUTED_LOCK`、`DSH_RUNTIME_LOCK_TTL_SECONDS`（M2） |

**Phase 2 验收标准**（引用调研文档 §13 Phase 2）：
- 三个副本 `/data/dsh-runtime` 物理隔离（M1）
- 同一 `(tenant, profileVersion)` 全局只一个 runtime（M2）
- 跨副本 resume 行为符合 D2 选定兜底（显式失败 / 迁移）
- Redis 挂掉时降级为当前语义不报错（M2）

---

## 6. 验证方式（本地 mogo 部署）

```bash
# Phase 1 验证（单实例默认即受益）：
MOGO_VERSION=<v> ./mogo build && ./mogo up --build
# 1) 重启 chat-api 后既有会话继续对话 → 断言 turn.completed（验证 M4）
# 2) curl localhost:8000/ready → 单实例 200（行为不变）

# 多副本验证（opt-in）：
DSH_RUNTIME_HOSTS_URL=http://dsh-runtime-host-1:8101,http://dsh-runtime-host-2:8101,http://dsh-runtime-host-3:8101 \
  ./mogo up --build --profile runtime-pool
# 3) curl localhost:8000/health | jq → 逐副本明细（验证 M3）
# 4) docker compose stop dsh-runtime-host-1 → curl localhost:8000/ready → 仍 200（验证 M3）
# 5) docker compose logs dsh-runtime-host-2 | grep instanceId（验证 R4）
```

---

## 7. 回滚方案
- Phase 1：纯增量，向后兼容。**`git revert` 即可**，无数据迁移。
- Phase 2：M2 用 `DSH_RUNTIME_DISTRIBUTED_LOCK=false` 关闭；M1 卷定义改回一行（保留旧卷不删）。

---

## 8. 建议审批内容
1. 确认 **Phase 1（M4 + M3 + R3 + R4）** 先行落地。
2. 确认 **D1**：单实例默认不变，多副本保持 opt-in。
3. 确认 **D2**：建议先做 (c)——M2 + Phase 1，暂不裸做 M1 卷隔离；M1 + 迁移能力作为后续独立 Phase。
4. 确认 **D3**：复用现有 redis DB/1。
5. Phase 3/4 暂不排期。
