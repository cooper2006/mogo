# RTO / RPO：定义、目标与实测记录

> 023 observability-resilience · US6 恢复与灾备（T108）
>
> 场景处置步骤见 [docs/runbooks/disaster-recovery.md](../runbooks/disaster-recovery.md)；
> 本文只回答两个问题：**我们的目标是多少**、**实际做到了多少**。

## 1. 定义（先对齐口径，否则数字没有意义）

| 指标 | 定义 | 计时起点 | 计时终点 |
|---|---|---|---|
| **RTO**（Recovery Time Objective） | 服务恢复到**可接受程度**所需时间 | 故障发生时刻（不是有人发现、更不是有人到场） | 关键路径恢复可用：`/ready` 通过 + 一次真实业务请求成功 |
| **RPO**（Recovery Point Objective） | 最多可以丢多少数据 | — | 恢复点时刻与故障时刻之差 = **数据丢失窗口** |

三个容易搞混的点：

1. **RTO 从故障开始算，不从事后开始算。** 演练脚本记录的墙钟时间也是从演练开始
   算起；真实故障里还要加上「从故障发生到开始处置」的发现与响应延迟——
   这就是为什么告警要快（见 `docs/observability/alerting.md` 的 `for:` 设置）。
2. **"可接受程度"要事先定义。** 本文按「登录 + 会话读写 + 对话可用」为关键路径；
   异步任务（文档解析、批处理）允许延后恢复，不计入 RTO。
3. **RPO 不是"备份多久跑一次"。** 备份每 15 分钟跑一次，不代表 RPO 就是 15 分钟：
   还必须满足「这份备份能解开、内容校验通过、恢复得比 15 分钟快」。任一条不成立，
   有效 RPO 就等于上一份**验证过可用**的备份的时间差。

## 2. 目标

| 场景 | RTO 目标 | RPO 目标 | 依据 |
|---|---|---|---|
| 单 AZ / 宿主机失联 | **≤ 30 min** | **≤ 15 min** | 跨 AZ 部署下副本在另一 AZ，切换是秒级；30 min 留给发现、判定与人工兜底 |
| MongoDB 数据丢失 | ≤ 60 min | **≤ 15 min** | 备份每 15 分钟一次（`*/15` oplog + 每日全量）；60 min 含恢复到演练库验证的时间 |
| LLM 全面故障 | ≤ 30 min（降级可用） | 不适用（无数据写入） | 降级开关 + 备 provider 切换 |
| 密钥泄露 | ≤ 15 min（吊销完成） | 不适用 | 吊销是新 key 生效前的唯一止血手段 |
| TLS 证书过期 | ≤ 30 min | 不适用 | 换证 + 网关重建 |
| Redis 全丢 | ≤ 10 min | 不适用（缓存可重建） | 删卷重建 + 冷启动预热 |
| 备份全部不可用 | ≤ 120 min | 取决于最后一份好备份 | 只剩宿主机数据卷可救 |

**为什么是 30 / 15 这两个数**：可用性 SLO 目标是 **99.9%**
（`deploy/prometheus/rules/slo_recording.yml` 的 `mogo:slo:availability:target`），
30 天窗口的错误预算只有 **约 43.2 分钟**。也就是说：

- RTO **30 min 是"最坏容忍"，不是常态目标**——一次灾难恢复就用掉月预算的约 70%；
  所以真正的防线是「让故障不用恢复」（跨 AZ 秒级切换、熔断降级），恢复演练只是兜底。
- RTO **超过 30 min 即当月 SLO 必然破约**，这也是演练预算取 1800s 的原因。
- RPO **15 min** 对应「最坏丢 15 分钟对话内容」，是产品侧确认可接受的量级；同时
  留出「备份任务本身要跑完」的余量（备份耗时逼近 10 分钟就该告警，见 §6）。

改这两个数必须同时改 SLO、告警预算（`MogoAvailabilityBurnRate*`）与本文档，
否则「目标」和「监控」会各说各话。

## 3. 目标如何被执行（不只是写在文档里）

| 目标 | 落地手段 | 代码/配置 |
|---|---|---|
| RPO ≤ 15 min | 每 15 分钟 oplog 增量 + 每日 02:30 全量 | `scripts/backup/crontab.example`、`scripts/backup/schedule.sh` |
| 备份可用 | 每次备份算明文摘要、每次恢复做校验和 + 明文摘要 + 逐集合文档数比对 | `scripts/backup/lib.sh`、`scripts/backup/restore_mongo.sh` |
| RTO ≤ 30 min | 恢复流程脚本化（不靠人记忆）+ 每周异地演练 | `scripts/drill/drill_recovery.sh`、cron `0 5 * * 1` |
| 跨 AZ 秒级切换 | 关键服务 `replicas: 2` + `max_replicas_per_node: 1` + `start-first` 滚动 | `deploy/docker-compose.prod.yml` |
| 自动切换可验证 | drain 节点演练并记录 RTO | `scripts/drill/drill_az_failover.sh` |
| 预算可配置 | `MOGO_RTO_BUDGET_SECONDS`（默认 1800）、`MOGO_RPO_BUDGET_SECONDS`（默认 900） | `scripts/drill/drill_recovery.sh` |

演练脚本超过预算时**只标记 `达标：no`，不判定失败**——预算用于暴露退化趋势，
不是用来让 CI 变红的（网络慢一点不等于灾备能力坏了）。

## 4. 怎么测（可复现的测量方法）

### 4.1 备份恢复演练（测 RTO 的恢复段 + RPO）

```bash
# 1) 记录演练起点，跑演练（内部会调真实恢复路径 restore_mongo.sh）
MOGO_RTO_BUDGET_SECONDS=1800 MOGO_RPO_BUDGET_SECONDS=900 \
  bash scripts/drill/drill_recovery.sh --from-offsite --sample 20
# 2) 脚本输出报告路径，报告内含：RTO 实测 / RPO 实测 / 数据丢失窗口 / 时间线
```

报告的 RTO 是**脚本墙钟总耗时**（解密 + 恢复 + 抽样比对），不含人工发现时间；
真实 RTO = 告警延迟 + 人工判定 + 这个数字。

### 4.2 跨 AZ 切换演练（测切换段）

```bash
bash scripts/drill/drill_az_failover.sh \
  --node az-a-node-1 --service mogo_chat-api,mogo_admin-api --restore \
  --report-dir /var/log/mogo/drills
```

RTO = 从 `docker node update --availability drain` 到 `docker service ls`
全部 `N/N` 的墙钟时间。**单机 / 非 Swarm 环境下脚本返回 2 并提示环境不具备**，
此时不能把「没有数据」当成「达标」。

### 4.3 记录规范

每次演练填一行下表，并把报告文件路径一起记下来（数字要能追溯到原始报告）：

- 日期用 UTC；
- RTO/RPO 单位统一为分钟（保留一位小数）；
- 「数据量」列写源库文档总数，否则不同规模的 RTO 不可比；
- 未达标必须写一行原因，不许留空。

## 5. 实测记录（T113）

| 日期（UTC） | 场景 | 数据量 | RTO 实测 | RPO 实测 | 目标 | 是否达标 | 报告 |
|---|---|---|---|---|---|---|---|
| — | 备份恢复到演练库（`drill_recovery.sh`） | — | 待首次生产演练 | — | 30 / 15 | **未演练** | — |
| — | 跨 AZ drain 切换（`drill_az_failover.sh`） | — | 待首次生产演练 | 不适用 | 30 | **未演练** | — |

### 5.1 当前状态说明（必须如实记录）

截至 2026-10-25，**还没有一次真实环境的端到端演练记录**，原因如下（不是"忘了"）：

1. 开发机没有 `mongodump` / `mongorestore` / `mongosh`，也没有可用的 Swarm 集群，
   真实演练无法在此执行；
2. 备份/恢复/演练脚本的逻辑已由脚本级测试覆盖（用假 mongo 工具注入故障）：
   `scripts/test_mongo_backup.sh`、`scripts/test_mongo_restore.sh`、
   `scripts/test_rotate_backups.sh`、`scripts/test_drill_recovery.sh`、
   `scripts/test_backup_schedule.sh`、`deploy/tests/test_prod_az_failover.py`；
3. **脚本测试通过 ≠ RTO 达标**：它只证明流程正确、故障能被发现、报告字段齐全，
   不证明在真实数据量下 30 分钟内恢复得完。

因此本节的两行标记为 **未演练**，而不是「通过」。首次上线后的第一件事就是按
§4.1 / §4.2 各跑一次，用真实数字填表；在此之前，任何人引用「RTO ≤ 30 min」
都应当同时说明「尚未实测」。

### 5.2 首次演练的检查清单

- [ ] 备份口令取自 secret（不是 `.env` 里的明文）
- [ ] 异地副本可用（`MOGO_BACKUP_OFFSITE_DIR` 或 rclone remote 配好且可读）
- [ ] 演练库名与源库不同（脚本会拒绝同名）
- [ ] 记录源库文档总数作为「数据量」
- [ ] 报告落盘路径纳入留存（默认 `<backup_dir>/../artifacts/drills/`）
- [ ] 演练后确认源库未被改动（文档数与演练前一致）

## 6. 退化信号（怎么知道 RTO 在变差）

| 信号 | 含义 | 阈值建议 |
|---|---|---|
| 演练 RTO 连续两次上升 | 数据量增长或链路变慢 | 上升 > 20% 即排查 |
| `mongo-backup` 容器 unhealthy | 备份已停摆，RPO 实际在扩大 | 立即 P1 |
| 备份 `duration_seconds` 持续上升 | 接近 15 分钟窗口，RPO 即将破约 | 逼近 600s 时告警 |
| 归档 `encrypted_bytes` 与 `dump_bytes` 比例突变 | 可能是空库或异常压缩 | 人工确认 |
| 演练报告 `达标：no` | 本次超预算 | 记入复盘，不算 CI 失败 |
