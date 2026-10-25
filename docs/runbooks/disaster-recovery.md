# 灾难恢复预案（Disaster Recovery）

> 023 observability-resilience · US6 恢复与灾备（T107）
>
> 本文和 `docs/runbooks/` 下其它文档的分工：那些是**单点故障**的处置手册
> （一个依赖抖了，改配置就好）；本文是 **灾难**——数据丢了、整个 AZ 没了、
> 密钥泄了。灾难处置的共同点是：**先止血、再评估、再动手，绝不凭记忆操作**。
>
> 每个场景都按同一套骨架写：症状 → 影响 → 判定（是不是真的灾难）→ 恢复步骤
> → 验证 → 复盘。RTO/RPO 的定义与实测记录在
> [docs/observability/rto-rpo.md](../observability/rto-rpo.md)。

## 0. 通用原则（先读这一节）

1. **恢复动作必须可回滚或有备份兜底。** 拿不准时，先备份现状（哪怕是坏的），
   再动手——`mongodump` 一份坏的也比没有强，它保留了「当时到底坏成什么样」。
2. **不要在故障窗口里升级组件。** 换版本会引入第二个变量，让根因不可辨。
3. **恢复演练不等于恢复。** 只有走过一遍 `restore_mongo.sh` + 一致性校验，
   才算确认备份可用；「备份任务显示成功」只证明文件写下来了。
4. **RTO 是从故障开始算到服务可用，不是从你到场算。** 所以演练要记录墙钟时间
   （脚本已经这么做），而不是「处理了多久」。

### 0.1 备份与恢复工具速查

| 动作 | 命令 |
|---|---|
| 立即全量备份 | `bash scripts/backup/backup_mongo.sh --mode full` |
| 每小时增量（含 oplog） | `bash scripts/backup/backup_mongo.sh --mode oplog` |
| 恢复到演练库并校验 | `bash scripts/backup/restore_mongo.sh --archive <归档> --target-db mogo_drill --drop --yes` |
| 只校验不写库 | `bash scripts/backup/restore_mongo.sh --archive <归档> --consistency-only` |
| 完整演练（含 RTO/RPO 记录） | `bash scripts/drill/drill_recovery.sh --archive <归档>` |
| 保留策略（30 天本地 / 90 天异地） | `bash scripts/backup/rotate_backups.sh` |
| 跨 AZ 切换演练 | `bash scripts/drill/drill_az_failover.sh --node <节点> --service <服务> --restore` |

备份口令来自 `MOGO_BACKUP_PASSPHRASE`（临时）或 `MOGO_BACKUP_PASSPHRASE_FILE`
（推荐，docker secret 或宿主机 0600 文件）。**两者都没有时脚本直接失败**，
不会回退到内置口令——这是有意的。

---

## 1. MongoDB 数据丢失（误删 / 损坏 / 归档丢失）

> 告警：`MogoServiceNotReady`（P0）、`MogoAvailabilityBurnRateFast`（P0），
> 或值班同学直接收到业务投诉

### 1.1 症状

- 集合「突然空了」或文档数远小于预期；登录失败（用户库没了）；
- `mongosh` 能连上，但 `db.stats()` 的 `dataSize` 明显偏小；
- 或者反过来：Mongo 起不来，日志出现
  `WiredTiger ... unrecoverable error` / `File exists` / `Invalid database`。

### 1.2 影响

| 数据 | 影响 |
|---|---|
| 用户与会话 | 用户无法登录，会话列表空白 |
| 消息与任务状态 | 在途任务全部丢失，需客户重发 |
| 计费与审计 | **不可重建**，只能按备份恢复到最近时间点 |

### 1.3 判定：是真的灾难吗

先确认**是不是只是连错了库**（最常见的假警报）：

```bash
# 应用实际连的库名和连接串
docker compose exec chat-api printenv | grep -E 'MONGODB_(URI|DB)'
docker compose exec mongo mongosh --quiet --eval 'db.adminCommand({listDatabases:1}).databases.map(d=>d.name+"="+d.sizeOnDisk)'
```

库名对但数据不对 → 真灾难，进入恢复。

### 1.4 恢复步骤

1. **立刻停止写入**，避免新数据覆盖「可恢复点」之后的空间：

   ```bash
   docker compose stop chat-api admin-api document-api document-worker
   ```

2. **先备份当前（坏的）状态**，留下证据：

   ```bash
   MOGO_BACKUP_PASSPHRASE_FILE=/run/secrets/mongo_backup_passphrase \
     bash scripts/backup/backup_mongo.sh --mode full --db mogo
   # 记下归档名，报告中标注"故障现场"
   ```

3. **确认要恢复到的时间点**。按 RPO ≤ 15 分钟的目标，选故障发生前最近的一份：

   ```bash
   ls -lt backups/ | head -20
   # 看清单里的 finished_at / collections 文档数
   python3 -m json.tool backups/mongo-mogo-full-<stamp>.archive.gz.json | head -40
   ```

4. **先恢复到演练库验证**，不要直接覆盖生产：

   ```bash
   bash scripts/backup/restore_mongo.sh \
     --archive backups/mongo-mogo-full-<stamp>.archive.gz.enc \
     --target-db mogo_verify --drop --yes
   ```

   一致性校验通过（逐集合文档数一致）再继续。**校验失败就换下一份备份**，
   不要"先恢复到生产试试"。

5. **覆盖生产库**（此步不可逆）：

   ```bash
   bash scripts/backup/restore_mongo.sh \
     --archive backups/mongo-mogo-full-<stamp>.archive.gz.enc \
     --target-db mogo --drop --yes
   ```

   脚本在目标库非空时会拒绝，必须显式 `--drop --yes`——防止误把备份
   合并进生产库造成二次污染。

6. 起服务，跑健康检查：

   ```bash
   docker compose start chat-api admin-api document-api document-worker
   curl -sf http://127.0.0.1:8000/ready | head -c 300
   ```

### 1.5 验证

- `/ready` 返回 200，`dependencies.mongodb.status == "ok"`；
- 抽查 3 个集合的文档数与清单 `collections[]` 一致；
- 用真实账号登录一次，列表能出数据；
- 记录**数据丢失窗口** = 故障发生时间 − 恢复点时间（写进复盘）。

### 1.6 复盘要点

- 丢失窗口为什么这么大？RPO 是否真的 ≤ 15 分钟（看最后一份备份的
  `finished_at`）？
- 备份为什么没更频繁（cron 没装？容器没起？`profile: backup` 没开？）
- oplog 切片是否可用：有 oplog 备份时可以做时间点恢复（见 §1.7）。

### 1.7 补充：用 oplog 缩小丢失窗口

`--mode oplog` 的归档里带 oplog 切片，可以回放到指定时间点。当前
`restore_mongo.sh` 支持恢复到**归档对应时刻**；更细的时间点恢复需要手工：

```bash
# 解出归档（含 local.oplog.rs），再对目标库回放
mongodump --uri "$MOGO_MONGODB_URI" --oplog --gzip --archive=/tmp/full.archive.gz
mongorestore --uri "$MOGO_MONGODB_URI" --gzip --archive=/tmp/full.archive.gz \
  --oplogReplay --oplogLimit "<epoch>:1"
```

> 这条路径尚未脚本化（T113 之后按需补）。没有把握时优先用「全量备份 +
> 接受丢失窗口」，别在故障中现学 oplog 回放。

---

## 2. LLM 全面故障（所有 provider 同时不可用）

> 告警：`MogoLlmErrorRateHigh`（P1）、`MogoLatencyP99High`（P1）

### 2.1 症状

- 对话请求大面积为 5xx 或超时；
- 日志里 `CircuitOpenError`、`llm:azure-openai` / `llm:default-openai`
  熔断器反复 OPEN；
- 各 provider 的 `p99` 全部劣化（不是单个 provider 的问题）。

### 2.2 影响

| 能力 | 影响 |
|---|---|
| 对话 / 生成 | 不可用 |
| 文档解析 | 若依赖 LLM 抽取，解析暂停（任务留在队列，不丢） |
| 登录、会话列表、非生成类功能 | **不受影响**（务必在故障中向用户说明这一点） |

### 2.3 判定

区分「单 provider 故障」和「全面故障」：

```bash
curl -s http://127.0.0.1:8000/internal/health/dependencies | python3 -m json.tool
# 看 llm 各 provider 的熔断状态与最近错误
docker compose logs --tail=200 chat-api | grep -iE 'circuit|provider|timeout' | tail -40
```

单 provider 挂了 → 切到备用 provider（`.env` 里换 `MOGO_LLM_*` 配置，重启
chat-api），不需要走本文。全部挂了才进入下面。

### 2.4 恢复步骤

1. **确认不是自己的问题**：额度耗尽、key 被吊销、网络出口被封，都会表现为
   「全部 provider 都挂」。

   ```bash
   # key 是否还有效（用最小请求探活，别用业务请求）
   curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $OPENAI_API_KEY" \
     https://api.openai.com/v1/models
   ```

2. **开启降级**：把生成类能力标为不可用，返回明确的「稍后重试」文案，而不是
   让请求堆积到超时（超时会连锁占满连接池，把非生成功能也拖垮）。

3. **降低重试与并发**：`MOGO_LLM_POOL_*_MAX_CONNECTIONS` 调小、
   熔断 `MOGO_BREAKER_FAIL_MAX` 调小，让失败快速返回。

4. **切换或新增 provider**：只要能恢复一条通路，就先恢复一条（哪怕慢），
   再谈全量。

5. 恢复后**逐步放开**并发，不要一次性全部打开——下游可能还在限流。

### 2.5 验证

- `MogoLlmErrorRateHigh` 消失，p99 回落；
- 一次端到端对话成功（含工具调用）；
- 熔断器状态从 OPEN → HALF_OPEN → CLOSED 走过一遍。

### 2.6 复盘要点

- 为什么是**同时**全挂？是否有单点共性（同一个出口 IP、同一份 key、
  同一个网关）？
- 降级开关是否真的生效（用户拿到的是"稍后重试"而不是 30s 后超时）？
- 备 provider 的切换是否演练过？没演练过的切换等于没有。

---

## 3. 宿主机宕机 / 单个 AZ 失联

> 告警：`MogoServiceScrapeDown`（P0）成片出现，或云厂商可用区事件通知

### 3.1 症状

- 一个节点上所有容器同时失联；Prometheus 的 `up` 指标成批归零；
- 用户侧：部分请求成功、部分 502/超时（取决于 LB 是否已摘除坏后端）。

### 3.2 影响

单机 compose 部署下：**全站不可用**，直到节点恢复。跨 AZ 部署下：容量减半，
自动切换后可用。

### 3.3 判定：机器还活着吗

```bash
# 云控制台/带外管理口先确认节点状态；能 SSH 进去说明只是容器层问题
ssh <node> 'uptime; df -h /; docker ps --format "{{.Names}}\t{{.Status}}" | head'
```

节点起不来 → 需要重建节点（云厂商换机），按 §3.4 走。
节点能进但不健康 → 可能是磁盘/内存故障，先 `docker node update --availability drain`
把它摘出，保住数据卷。

### 3.4 恢复步骤

**A. 有跨 AZ 拓扑（`deploy/docker-compose.prod.yml`）**

1. 确认剩余节点上的副本数已经恢复（Swarm 会自动重建被 drain 的任务）：

   ```bash
   docker service ls           # REPLICAS 列应为 N/N
   docker node ls              # 坏节点 Drain / Down
   ```

2. 如果任务没有自动重建，手动 drain 坏节点强制驱逐：

   ```bash
   docker node update --availability drain <坏节点>
   ```

3. 确认入口还在：VIP 或云 LB 只把流量发给存活节点的 gateway。

4. 记录 RTO（从故障开始到 `docker service ls` 全部 N/N）。

**B. 单机部署**

1. 在新主机上装 Docker + compose，克隆同一版本（**用镜像 tag，不要 latest**）：

   ```bash
   git checkout <发布 commit>
   docker compose pull
   ```

2. 恢复数据卷。有备份就用备份（§1.4）；宿主机磁盘还在就把 `mongo-data` 卷
   整个搬过来（卷级复制比 dump 快，但要求 MongoDB 已停）：

   ```bash
   # 在旧机（若还能访问）或备份宿主上
   docker run --rm -v mogo_mongo-data:/data -v "$PWD":/backup alpine \
     tar czf /backup/mongo-data.tgz -C /data .
   # 新机
   docker volume create mogo_mongo-data
   docker run --rm -v mogo_mongo-data:/data -v "$PWD":/backup alpine \
     tar xzf /backup/mongo-data.tgz -C /data
   ```

3. 用**同一个** `MOGO_BACKUP_PASSPHRASE_FILE` 与 `MOGO_VOLUME_PREFIX`（否则卷名
   对不上，compose 会新建空卷，看起来「数据又丢了」）。

4. `docker compose up -d`，验证 `/ready`，再逐个确认业务。

### 3.5 验证

- `docker service ls` 全部 N/N，`docker node ls` 只剩健康节点；
- 入口 VIP/域名可达，做一次真实登录 + 一次对话；
- 检查 Mongo 副本集 `rs.status()` 有 PRIMARY，且不会因为少了旧节点而卡住选主。

### 3.6 复盘要点

- 自动切换用了多久？和 `drill_az_failover.sh` 演练出来的数字差多少？
- 为什么坏节点没被自动摘除（LB 健康检查没配？`max_fails` 太小？）
- 有状态服务是否被错误地跨节点迁移（数据卷不跨节点，迁移只会得到空库）。

---

## 4. 密钥泄露（LLM key / 数据库口令 / 备份口令）

> 告警：无（**这是当前监控盲区**，靠外部报告或代码扫描发现）

### 4.1 症状

- GitHub secret scanning / 供应商通知某个 key 异常调用；
- 账单异常（LLM 额度被刷）；
- 日志里出现不属于自己的调用来源。

### 4.2 影响

| 泄露对象 | 最坏情况 |
|---|---|
| LLM provider key | 额度被刷、账单失控；**不涉及用户数据** |
| MongoDB 口令 | 库被拖走、被删（如果有公网暴露） |
| **备份口令** | 所有历史备份可被解开 → 等同于**全部历史数据泄露**，最严重 |

### 4.3 恢复步骤（处置顺序不能变，先吊销再排查）

1. **先吊销，再排查。** 泄露的 key 每多活一分钟都是风险：

   ```bash
   # LLM：在供应商控制台 revoke，然后发新 key
   # MongoDB：改口令（先加新用户，切应用，再删旧用户，避免中断）
   ```

2. **轮换备份口令**，并且**重新加密历史备份**。仅换新口令不会让旧备份变安全：

   ```bash
   # 用旧口令解开、新口令重新加密，逐个归档处理
   for f in backups/mongo-*.archive.gz.enc; do
     MOGO_BACKUP_PASSPHRASE_FILE=<旧口令> bash scripts/backup/restore_mongo.sh \
       --archive "$f" --target-db mogo_rotate --drop --yes
     MOGO_BACKUP_PASSPHRASE_FILE=<新口令> bash scripts/backup/backup_mongo.sh --db mogo_rotate
   done
   ```

   时间紧时：**先销毁仍可被解开的旧备份**（在确认新备份可用之后），
   而不是留着"以防万一"。

3. **检查备份的去向**：异地副本（`MOGO_BACKUP_OFFSITE_DIR` / rclone remote）
   上是否有更早的口令保护的归档，一并按上面处理。

4. **审计访问**：谁在泄露窗口内读过这些材料（对象存储访问日志、CI 日志、
   IM 历史）。若历史数据真被读取，按合规流程上报。

5. **消除复发点**：把口令从代码/CI/镜像里彻底移出，改走 secret 或密钥管理
   系统；加 pre-commit / secret scanning 守卫（仓库已有 pre-commit 密钥检查）。

### 4.4 验证

- 旧 key 调用返回 401；
- 新备份用新口令可解开，旧口令解不开；
- `git log -S` 确认没有残留口令字面量；CI 里没有 `PASSPHRASE=` 赋值。

### 4.5 复盘要点

- 泄露是怎么发生的（写进 `.env` 被提交？CI 变量明文？日志打印了口令？）
- 为什么没更早发现（secret scanning 是否覆盖该文件类型/CI 配置）
- 备份口令和备份文件是否放在同一处（**必须分开**：备份在对象存储，
  口令在密钥管理系统；放一起等于没加密）

---

## 5. TLS 证书过期 / 证书被吊销

> 告警：无专属规则（**监控盲区**，见 `docs/runbooks/certificate_expired.md` §改进项）

### 5.1 症状

- 浏览器报 `NET::ERR_CERT_DATE_INVALID`；API 客户端报证书错误；
- 内网 `/ready` 正常、外部访问失败——这是 TLS 层问题的典型特征。

### 5.2 影响

| 入口 | 影响 |
|---|---|
| 外部 HTTPS（用户端、开放 API） | **全部失败**，浏览器直接拦截，请求到不了网关 |
| 内网 HTTP / 容器间调用 | 不受影响（这也是为什么监控可能一片绿而用户全挂） |
| 已有长连接 | 换证要重建网关，连接会断，客户端需重连 |

判定口径：内网 `/ready` 正常、外部访问失败 ⇒ 先怀疑 TLS，别去翻业务日志。

### 5.3 恢复步骤

1. 确认到期时间与证书链：

   ```bash
   openssl x509 -in deploy/tls/fullchain.pem -noout -dates -subject
   openssl s_client -connect <域名>:443 -servername <域名> </dev/null 2>/dev/null | openssl x509 -noout -dates
   ```

2. 换证书：新 `fullchain.pem` + `privkey.pem` 落到 `MOGO_TLS_CERTS_DIR`，
   **私钥权限必须是 0644**（网关以非 root 运行，0600 会导致
   `cannot load certificate key ... Permission denied`，直接 crash-loop）。

3. 重建网关（配置是挂载的，不用重建镜像）：

   ```bash
   docker compose up -d --no-deps gateway
   ```

4. 生效验证：浏览器/`curl` 不再报错，`openssl s_client` 显示新到期时间。

### 5.4 验证与复盘

**验证**：浏览器/`curl` 不再报证书错误，`openssl s_client` 显示新到期时间，
换证后 5 分钟内无新的 `NET::ERR_CERT_*` 报错。



- 到期提醒为什么没触发？补一条外部拨测（证书剩余天数）而不是靠人记。
- 证书续签是否自动化（ACM / certbot / 供应商托管）？手工换证迟早会漏。

---

## 6. 备份卷损坏 / 备份全部不可用

> 告警：`mongo-backup` 容器 unhealthy（健康检查基于 `.last-success`）

### 6.1 症状

- `docker compose ps mongo-backup` 显示 `unhealthy`；
- `/backups` 里文件在但解不开（解密报 `bad decrypt` 或明文摘要不匹配）；
- 恢复时校验和不匹配。

### 6.2 影响

| 情况 | 影响 |
|---|---|
| 最新一份坏、旧的可读 | 有效 RPO 退回到旧备份的时间点（丢失窗口变大，但数据还在） |
| 异地副本可用 | 影响可控：从异地取回即可，RTO 取决于取回带宽 |
| 备份全坏且无异地 | **灾难**：只能靠宿主机数据卷或更上游的存储快照，通常已丢数据 |

### 6.3 恢复步骤

1. **先判断是"这一份坏"还是"全坏"**：逐个跑只校验模式，不要只看最新一份。

   ```bash
   for f in backups/mongo-*.archive.gz.enc; do
     echo "== $f"
     bash scripts/backup/restore_mongo.sh --archive "$f" --consistency-only || echo "  损坏"
   done
   ```

2. 有异地副本就立刻取回（异地存在的意义就是这一刻）：

   ```bash
   bash scripts/backup/restore_mongo.sh --from-offsite \
     --archive <归档名> --target-db mogo_verify --drop --yes
   ```

3. 局部损坏（某几份坏）→ 删掉坏归档、补一份新的全量，并查原因：
   磁盘满了写半截？加密过程被 kill（容器重启）？

4. 全部损坏 → 只剩宿主机卷可救：把 `mongo-data` 卷按 §3.4-B 搬出来，
   从**数据目录**直接起一个 mongod 导出。这是最后手段，且要求磁盘物理完好。

### 6.4 验证

- `bash scripts/backup/restore_mongo.sh --archive <新归档> --consistency-only` 通过；
- `mongo-backup` 容器重新变 healthy（`.last-success` 在 2 小时内）；
- 保留策略已把坏归档清掉（`bash scripts/backup/rotate_backups.sh`），避免下次恢复又踩到它。

### 6.5 复盘要点

- 备份成功的判定是否只看退出码？应同时校验「解密 + 明文摘要 + 文档数」
  三件事——`restore_mongo.sh --consistency-only` 就是干这个的。
- 为什么坏了没人知道？备份容器 healthcheck（`.last-success` 超过 2 小时即
  unhealthy）是否被接到告警上。

---

## 7. Redis 全丢（缓存 / 会话锁 / 限流状态）

> 告警：`MogoServiceNotReady`（P0，`/ready` 的 redis 依赖）

### 7.1 影响

Redis 是**可重建**的缓存，不是账本。数据全丢的影响是：

| 数据 | 全丢后果 |
|---|---|
| 会话归属缓存 | DSH 运行时锁/归属信息丢失 → 进行中的长任务可能拿不到锁，需用户重试 |
| 限流计数 | 计数清零 → 短时间内容量突增，需盯住宿主资源 |
| 业务缓存 | 回源变多，DB 压力上升（可能连锁触发慢查询） |

### 7.2 恢复步骤

1. Redis 起得来就 `FLUSHALL`（确认它确实是缓存库，且没有把业务数据塞进去）：

   ```bash
   docker compose exec redis redis-cli -n 0 FLUSHALL
   docker compose exec redis redis-cli -n 1 FLUSHALL   # DSH 内核库 DB/1
   ```

2. Redis 起不来就删卷重建（这就是「缓存可以丢」的兑现时刻）：

   ```bash
   docker compose stop redis
   docker volume rm mogo_redis-data
   docker compose up -d redis
   ```

3. **紧接着盯 DB 与 CPU**：缓存冷启动会让回源放大，观察 15 分钟。

### 7.3 复盘要点

- 是否有本不该放 Redis 的数据放进了 Redis（丢了就找不回来的那种）？
- 限流重置导致的突增是否有保护（DB 侧最大连接数、网关侧并发限流）？

---

## 8. 跨 AZ 拓扑（T103–T106 的部署前提）

这也是 §3 自动切换**能不能成立**的前提，单独写清楚。

### 8.1 节点要求

| 节点 | 标签 | 角色 |
|---|---|---|
| `az-a-node-1` | `mogo.role=app`、`mogo.az=az-a` | 应用副本 |
| `az-b-node-1` | `mogo.role=app`、`mogo.az=az-b` | 应用副本 |
| 数据节点（其一） | `mogo.data=true`、`mogo.az=az-a` | mongo / redis / mongo-backup |

```bash
docker node update --label-add mogo.role=app --label-add mogo.az=az-a az-a-node-1
docker node update --label-add mogo.role=app --label-add mogo.az=az-b az-b-node-1
docker node update --label-add mogo.data=true --label-add mogo.az=az-a <数据节点>
```

### 8.2 部署

```bash
docker stack deploy -c docker-compose.yml -c deploy/docker-compose.prod.yml mogo
# 或
docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml --profile prod up -d
```

关键配置（`deploy/docker-compose.prod.yml`）：

- 关键服务 `replicas: 2` + `placement.max_replicas_per_node: 1` → 一主一备
  **必然**分在两个节点（Compose 没有反亲和语法，用「每节点最多一个」逼近）；
- `update_config.order: start-first` + `failure_action: rollback` → 发版期间
  始终有实例接流量，坏镜像自动回滚；
- `restart_policy.max_attempts: 0` → 永不放弃重启；
- healthcheck 跑 `deploy/probes/readiness.sh`（依赖不可用则不接流量，
  但**不重启**）；进程卡死/崩溃由 `restart_policy` 负责——两件事不能混。

### 8.3 入口层

- **推荐**：云厂商 LB（跨 AZ、自带健康检查），后端指向两个节点的 gateway 端口；
- **自建**：宿主机 Keepalived 提供 VIP，两台机器 `MASTER/BACKUP`，
  健康检查脚本见 `deploy/keepalived/check_gateway.sh`（VIP 必须在宿主机网络，
  放进容器需要 `host network` + `NET_ADMIN`，风险大于收益）。

### 8.4 演练

```bash
bash scripts/drill/drill_az_failover.sh \
  --node az-a-node-1 --service mogo_chat-api,mogo_admin-api \
  --restore --report-dir /var/log/mogo/drills
```

脚本会 drain 节点、等副本恢复、记录 RTO 并落报告。**单机环境没有可切换的
节点，脚本会明确返回「环境不具备」**——不要把它当成通过。

---

## 9. 场景与目标对照

| 场景 | 目标 RTO | 目标 RPO | 关键依赖 |
|---|---|---|---|
| §1 数据丢失 | 60 min（含验证） | ≤ 15 min | 备份可用 + 演练过 |
| §2 LLM 全故障 | 30 min（降级可用） | 不适用 | 降级开关 + 备 provider |
| §3 宿主机/AZ 宕机 | ≤ 30 min | ≤ 15 min | 跨 AZ + 自动切换 |
| §4 密钥泄露 | 15 min（吊销） | 不适用 | 吊销流程 + 重加密 |
| §5 证书过期 | 30 min | 不适用 | 证书备份 + 换证 SOP |
| §6 备份不可用 | 120 min | 取决于最后一份好备份 | 异地副本 |
| §7 Redis 全丢 | 10 min | 不适用（可重建） | 冷启动保护 |

实测记录模板与当前值见
[docs/observability/rto-rpo.md](../observability/rto-rpo.md)。

---

## 10. 复盘模板

每个场景处置完都填一份，落在 `docs/postmortems/YYYY-MM-DD-<标题>.md`：

```markdown
# <标题>

- 时间线（UTC）：发现 / 响应 / 止血 / 恢复 / 复盘
- 影响面：哪些用户、多少请求、多久
- RTO 实测：__ min（目标 __ min）
- RPO 实测：__ min（目标 __ min），数据丢失窗口 __
- 根因（一句话，能说清"为什么"而不是"发生了什么"）
- 做对的事 / 做错的事
- 行动项（每条带 owner 与截止日期，禁止写"加强监控"这种不可验收的项）
```
