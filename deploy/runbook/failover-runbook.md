# 单区故障切换 Runbook（024 T075/T076/T077 / FR-039/FR-040）

> 适用：自托管单机部署（首期 FR-038 以「备份 + 新主机重建」达成）。
> 目标：单区/单主机故障后在 RTO 内从备份在新主机重建并恢复服务。
> RTO 目标 60 分钟（重建 + 恢复备份 + 流量切换），RPO 目标 ≤ 最近一次自动备份时刻
> （`deploy/cli/backup-schedule.sh` 默认每日 02:00，窗口 02:00-05:00）。

---

## 0. 角色与权限（T077 / FR-040）

**"谁可以切"** —— 明确角色与审批，技术侧有对应限制手段。

| 角色 | 是否可执行切换 | 审批要求 | 限制手段 |
|---|---|---|---|
| SRE 值班（on-call） | 可执行 `failover.sh prepare/execute` | 触发 P0 后 10 分钟内自行决策 | 独立操作账号 `mogo-failover`，专用 SSH 密钥；无 sudo 到生产主机 |
| SRE 负责人 | 可执行全部动作（含 `back` 回切） | 需知会值班经理 | 同上 |
| 平台负责人 | 可执行 `back` 回切 | 需 P0 事故单 + 双人复核 | 双人审批（`MOGO_FAILOVER_REQUIRE_APPROVAL=1` 时需第二签名） |
| 应用研发（R&D） | 只读 `failover.sh status` | — | 只读密钥；无执行权 |
| 外部/第三方 | 禁止 | — | 独立账号无任何执行权限 |

- **独立操作账号**：`mogo-failover`（SSH 公钥仅安装在目标主机，密码登录禁用）。
- **专用密钥**：切换操作走 `MOGO_FAILOVER_KEY`（`deploy/secrets/` 或 SSH agent），
  与日常运维账号隔离；密钥权限 0600，不提交仓库。
- **审计**：所有切换动作记录到 `deploy/runbook/rollbacks/<date>-failover.md`
  （操作人、账号、时间、动作、结果），随事故单归档。
- **双人复核**：回切（`back`）默认需 `MOGO_FAILOVER_REQUIRE_APPROVAL=1` +
  第二位操作者的 SSH 签名文件（`--approver-key`）。

---

## 1. Redis 持久化与 RPO 声明（T075 / FR-039）

**如实声明**（不自欺）：

- 现状：`docker-compose.yml` 的 `redis` 服务 `command: ["redis-server", "--appendonly", "yes"]`
  —— **AOF 开启，但未配置 `appendfsync`**（默认 `everysec`，最多丢 1 秒写入）。
- **切换中的丢失范围**：
  - 若故障发生在两次自动备份之间，Redis 数据**最多丢失**自最近一次备份以来
    的全部写入（备份不含 redis 实时数据，仅 redis-data 卷快照）。
  - 即便 AOF 每 1 秒 fsync，新主机重建时 AOF 文件来自 redis-data 卷备份，
    因此实际丢失范围 = 备份时刻 → 故障时刻之间所有 Redis 写入。
- **对业务的影响**：Redis 用于缓存与短期会话；丢失后表现为缓存 miss 与登录态失效，
  应用层**必须能**容忍（缓存重建、重新登录），不得依赖 Redis 作持久事实源。
- **验证点**：切换后 `redis-cli DBSIZE` 与关键 key 存在性符合"备份时刻状态"预期；
  若发现依赖 Redis 持久化的业务逻辑（如未落 Mongo 的订单状态），视为**设计缺陷**，
  须在切换演练中记录并修复（写入 DR 预案整改闭环）。

---

## 2. 切换步骤（T076 / FR-040）

### 2.1 前置条件

- 已配置 `deploy/cli/backup-schedule.sh`（每日备份 + 保留策略）。
- 已生成密钥 `deploy/secrets/mongo-keyfile`（可选，HA 副本集启用时）与 `MOGO_BACKUP_KEY_FILE`。
- `deploy/cli/failover.sh` 就绪，`mogo failover status` 可读。

### 2.2 prepare（准备新主机）

```bash
# 决策人：SRE 值班；执行者：SRE 值班；预计 10 分钟
./mogo failover prepare --new-host <IP> --backup backups/mogo-backup-<ts>
```

- 校验新主机可达（SSH）、磁盘足够、时间同步（NTP）。
- 从远端/对象存储取回最近一次备份（含解密密钥，密钥**异机**，见 backup-key-management.md）。
- 解密并校验 `SHA256SUMS`。
- **验证点**：`mogo failover status` 显示 `prepare: done`。

### 2.3 execute（重建 + 切换流量）

```bash
# 决策人：SRE 负责人；执行者：SRE 值班；预计 30 分钟
./mogo failover execute --new-host <IP>
```

- 在新主机拉起 compose（`mongo-ha` 若启用），从解密备份恢复所有卷。
- 切换流量：DNS / 网关 upstream 指向新主机（`deploy/cli/canary.sh` 或反向代理配置）。
- 旧主机降级为只读/下线。
- **验证点**：`./mogo status` 全部服务 healthy；`redis-cli DBSIZE` 符合声明范围。

### 2.4 verify（一致性校验）

```bash
./mogo failover verify --new-host <IP>
./mogo failover status
```

- 调用 `scripts/verify_data_consistency.py`（Mongo 关键集合行数 + 抽样校验和 + 应用层读写探针）。
- 调用 `scripts/verify_restore_business.py`（业务冒烟）。
- 全部 PASS 才算切换成功。

### 2.5 back（回切）

```bash
# 决策人：平台负责人；执行者：SRE 负责人；需双人复核
./mogo failover back --orig-host <IP> --yes --approver-key <signature>
```

- 原主机修复后回切：反向同步数据（增量备份）→ 切流量 → 验证。
- **未完成收缩禁止回滚**（见 expand-contract.md）：数据层若在过渡版本做了破坏性变更，
  须先执行 `.down.py` 回到兼容态。

---

## 3. 验证点清单（切换演练必打勾）

| # | 验证点 | 命令 | 结论 |
|---|---|---|---|
| F1 | 新主机 SSH 可达、NTP 同步 | `./mogo failover status` | |
| F2 | 备份解密 + SHA256SUMS 通过 | `sha256sum -c` | |
| F3 | 所有卷恢复成功 | `docker volume ls` | |
| F4 | 服务全部 healthy | `./mogo status` | |
| F5 | 数据一致性 PASS | `verify_data_consistency.py` | |
| F6 | 业务冒烟 PASS | `verify_restore_business.py` | |
| F7 | Redis 丢失范围符合声明 | `redis-cli DBSIZE` | |
| F8 | 操作人/账号/时间/动作已记录 | `deploy/runbook/rollbacks/<date>-failover.md` | |

---

## 4. 通信方式与外部联系人（T082 关联）

- 内部：P0 事故群（IM webhook，见 `deploy/alertmanager/alertmanager.yml`）。
- 外部：云服务商 / 机房运维 7×24 电话（写入 `deploy/runbook/dr-plan.md` 的联系人表）。
- 通知模板：事故单编号 + 影响范围 + 当前阶段（prepare/execute/verify/back）。

---

## 5. 版本与更新

- 版本：v1（2026-10-26 随 024 T075/T076/T077 建立）。
- 更新规则：拓扑变更 / 角色变更 / 演练发现新问题 → 更新并递增版本号，随 DR 预案
  `deploy/runbook/dr-plan.md` 一起评审。