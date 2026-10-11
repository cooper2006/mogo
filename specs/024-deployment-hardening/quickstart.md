# Quickstart: Deployment & Release Hardening（024）

**Feature**: [spec.md](./spec.md) | [plan.md](./plan.md) | [tasks.md](./tasks.md)

本文件说明如何**启用并验证**部署与发布加固。全部命令基于自托管 Docker Compose 部署（`docker-compose.yml` + `mogo` CLI）。

> ⚠️ **前置认知**：QualityForge 审计的 42 个 P0/P1 缺陷中 **41 项为 `blocked`**，含义是"基础设施尚未建立"。因此本 Quickstart 的每个子域都对应**先建立基础设施、再执行验证**两步，不是"跑一条命令就通过"。

---

## 1. 前置条件

### 环境

- Linux x86_64 或 arm64 主机，Docker Engine 24+ 与 Docker Compose v2
- `git`、`bash` 5+、`yamllint`、`jq`、`sha256sum`（或 `shasum -a 256`）
- 已安装 `mogo` CLI（仓库根目录 `./mogo`），可执行 `./mogo --help`
- 若启用灰度：`nginx` 已在 `docker-compose.yml` 中作为 `gateway` 服务运行
- 若启用自动续期（可选）：主机可访问 ACME 服务器（Let's Encrypt），且持有域名控制权

### 隔离环境（演练必需）

- 至少一台**隔离主机**用于灰度回滚演练、恢复演练、单区故障演练。
- 隔离环境必须与生产环境隔离网络，但使用**相同的 compose 配置与镜像来源**。

### 现有可用能力（无需重建）

- `./mogo backup` / `./mogo restore`：归档 8 个命名卷 + `SHA256SUMS` + 版本/commit 标记（`deploy/cli/backup.sh`，QF-837 已 `pass`）
- `.github/workflows/container-release.yml` / `container-promote.yml`：制品发布与晋级
- `scripts/test_backup_restore_rollback.sh`：函数级演练（**Docker 调用全部 mock，结果不计入 RTO/RPO 实测值**）

---

## 2. 子域 A：部署安全基线（US1）

### 2.1 启用

```bash
# 1) 非 root 化：Dockerfile 追加 USER 后重新构建
./mogo build

# 2) 只读 + 最小能力：docker-compose.yml 已含 read_only / cap_drop / no-new-privileges
./mogo up -d

# 3) 安装基线扫描（T016/T019）
./mogo baseline
```

### 2.2 验证

```bash
# 容器安全基线四项（SC-001）
for c in chat-api admin-api document-api user-web admin-web gateway; do
  docker inspect "$c" --format \
    "$c User={{.Config.User}} RO={{.HostConfig.ReadonlyRootfs}} CapDrop={{.HostConfig.CapDrop}} NNP={{.HostConfig.SecurityOpt}}"
done
```

预期：`User` 非 `0`、`RO=true`、`CapDrop=["ALL"]`、`SecurityOpt` 含 `no-new-privileges:true`。

```bash
# 基线扫描（含镜像体积基线与运行层清理）
./mogo baseline --json > /tmp/baseline.json
jq -e '.items | all(.status == "pass")' /tmp/baseline.json

# 配置清单一致性（T022）
bash deploy/cli/config-lint.sh --env prod

# 漂移检测（T025）
bash deploy/cli/drift-check.sh
```

---

## 3. 子域 B：制品与可追溯性（US2）

### 3.1 启用

```bash
# 制品门禁在流水线侧生效：.github/workflows/container-release.yml 追加 label 与 digest 校验
# 部署侧校验：
./mogo verify --against ghcr.io/himovo/chat-api:${MOGO_VERSION}

# 部署 dry-run 预审
./mogo deploy --dry-run
```

### 3.2 验证

```bash
# 线上 digest 与流水线记录一致（FR-012）
docker inspect $(docker service ls -q 2>/dev/null || echo chat-api) \
  --format '{{.Image}}'
# 与 .github/workflows 产出的 SHA256SUMS 比对

# 缺失必填配置键 → 启动失败并指出键名（FR-015）
# 在 .env 中删除一个必填键后：
./mogo up -d 2>&1 | tee /tmp/boot.log
grep -E 'Missing required config: [A-Z_]+' /tmp/boot.log
# 预期：非零退出 + 明确键名
```

---

## 4. 子域 C：灰度与回滚（US3）

### 4.1 启用

```bash
# 灰度配置与回滚条件
cat deploy/canary/canary-plan.yml        # 档位与观察窗口
cat deploy/canary/rollback-conditions.yml # 触发指标 + 阈值

# 启动灰度（新版本仅承载 1% 流量）
./mogo canary start --version ${MOGO_VERSION}
./mogo canary status
```

### 4.2 验证

```bash
# 灰度档位推进（1% → 10% → 50% → 100%）
./mogo canary promote   # 每档需等待观察窗口结束
./mogo canary status    # 输出当前档位、观察窗口剩余、新旧版本指标对照

# 新旧版本指标并排对比（FR-021）
./mogo canary metrics --compare chat-api

# 注入超阈后自动回滚（FR-022，预发环境验证）
# 人为调高新版本错误率 → 观察窗口结束 → 自动回滚触发
./mogo canary status   # 应显示 auto-rollback triggered + 实测耗时
```

---

## 5. 子域 D：特性开关与发布管理（US4）

### 5.1 启用

```bash
# 特性开关登记（FR-027）
cat deploy/flags/flags.yml
# 每项必须含 owner / defaultValue / expiry / cleanupPlan 四项

# 开关校验与到期告警
bash deploy/cli/flag-check.sh
```

### 5.2 验证

```bash
# 开关四项登记齐全（FR-027）
bash deploy/cli/flag-check.sh --strict   # 缺任一登记项即非零退出

# 发布检查单执行人与结论（FR-033）
bash deploy/cli/checklist-verify.sh docs/release-checklist-self-hosted.md

# 数据库变更先于代码（FR-029）
# 发布计划校验：迁移版本号 < 依赖它的代码版本，否则阻塞
```

---

## 6. 子域 E：备份自动化（US5.1）

### 6.1 启用

```bash
# 备份加密（FR-035）：密钥从 deployment-secrets 卷或外部密钥源读取
export MOGO_BACKUP_KEY_FILE=/var/lib/mogo/secrets/backup.key   # MUST 与备份集不同主机

# 安装定时备份（FR-034）
./mogo backup-schedule install --cron "0 2 * * *"
./mogo backup-schedule status

# 保留策略（FR-036）
./mogo backup-schedule install --keep 14 --keep-days 30
```

### 6.2 验证

```bash
# 手动触发一次
./mogo backup
ls -l /var/backups/mogo/latest/*.tar.gz.gpg   # 应为加密文件

# 最近一次成功时间（FR-034）
./mogo backup-schedule status --json | jq -r '.lastSuccess'

# 恢复到干净环境 + 业务校验（FR-037）
./mogo restore --from /var/backups/mogo/latest --verify
# 预期：恢复完成后自动运行 scripts/verify_restore_business.py 并输出 PASS
```

---

## 7. 子域 F：跨区与切换（US5.2）

```bash
# 启用 MongoDB 副本集（可选，FR-039）
docker compose --profile ha up -d mongo mongo-init

# 单区故障切换（FR-038/040）
./mogo failover prepare    # 新主机拉制品、准备环境
./mogo failover execute    # 切流量到新主机
./mogo failover verify     # 数据一致性校验（FR-041）
```

预期：`./mogo failover verify` 输出 `scripts/verify_data_consistency.py` 的校验报告。

---

## 8. 子域 G：DR 预案与演练（US5.3）

```bash
# 预案与记录目录
ls deploy/runbook/
# dr-plan.md / rollback-runbook.md / failover-runbook.md /
# data-rollback-matrix.md / expand-contract.md / drills/

# 演练记录模板
cat deploy/runbook/drills/TEMPLATE.md
```

预期：`dr-plan.md` 含场景清单、决策人、切换与恢复步骤、通信方式、外部联系人、责任人、RTO/RPO 目标、版本号与更新日期。

---

## 9. 子域 H：证书、值班与告警（US5.4）

```bash
# 证书清单与检查（FR-046/047/048）
cat deploy/certs/inventory.yml
./mogo cert check          # 到期 ≤ 30 天告警 + 证书链校验
./mogo cert list           # 含责任人、用途、到期时间

# 值班表（FR-051）
cat deploy/runbook/oncall-roster.yml
bash deploy/cli/oncall-check.sh    # 校验零空档 + 联系方式可达

# 告警升级路径（FR-052）
cat deploy/runbook/alert-escalation.md

# 水位与容量（FR-049/050）
./mogo monitor check
cat deploy/monitoring/watermarks.yml
cat docs/capacity-model.md
```

---

## 10. 验证清单

### 部署安全基线

- [ ] `docker inspect` 全部业务容器：`User` 非 `0`
- [ ] `docker inspect` 全部业务容器：`ReadonlyRootfs=true`
- [ ] `docker inspect` 全部业务容器：`CapDrop=["ALL"]`
- [ ] `docker inspect` 全部业务容器：`SecurityOpt` 含 `no-new-privileges:true`
- [ ] 运行镜像不含 `gcc` / `g++` / pip 缓存 / `*.test.py`
- [ ] 镜像分层与体积在 `deploy/config/image-baseline.yml` 基线内
- [ ] 配置清单键与代码读取点双向一致，无未登记必填键
- [ ] 配置变更可在审计中查到操作者、时间、旧值 → 新值、受影响服务
- [ ] 配置可按 commit 回滚（`./mogo config rollback --to <ref>`）
- [ ] 人工注入变更后 `drift-check.sh` 100% 检出

### 制品与可追溯性

- [ ] 线上容器 digest 可反查流水线发布记录与 git commit
- [ ] 制品带版本号 + commit SHA + 构建时间三项元数据
- [ ] 各环境镜像 digest 一致，差异仅限配置层
- [ ] 删除必填配置键后启动非零退出并指明键名
- [ ] dry-run 计划 diff 与实际执行一致，偏离被报告
- [ ] 按发布说明在干净机器可一键安装并通过最小验证
- [ ] 制品晋级有执行者与时间记录

### 灰度与回滚

- [ ] 灰度 1% → 10% → 50% → 100% 四档可执行，每档有观察窗口
- [ ] 灰度期新旧版本指标可并排对比
- [ ] 自动回滚条件在**预发环境**实际触发过并留存记录
- [ ] 真实环境回滚演练实测耗时 ≤ 约定目标（**非 mock**）
- [ ] 回滚后关键指标恢复基线并有校验记录
- [ ] 数据变更兼容性结论表覆盖全部变更项，不可逆项有兜底脚本

### 特性开关与发布管理

- [ ] 特性开关四项（属主/默认值/到期/清理计划）登记齐全
- [ ] 到期开关告警可触发；属主离职有转移流程
- [ ] 含 schema 变更的发布中，数据库变更先于代码落地
- [ ] 破坏性变更走扩展-收缩流程，未完成收缩时禁止回滚
- [ ] 迁移不阻塞线上服务，迁移幂等
- [ ] 发布检查单覆盖配置差异与依赖差异
- [ ] 检查单每项均有执行人与结论，无空值项

### 备份与灾备

- [ ] 自动备份最近一次成功时间在约定窗口内
- [ ] 备份集已加密，密钥与备份集**不在同一主机**
- [ ] 保留策略生效，清理后剩余份数仍满足恢复需求
- [ ] 备份失败触发告警
- [ ] 恢复到干净环境后业务校验 PASS（**非 mock**）
- [ ] 单区故障后在 RTO 内恢复服务，数据丢失 ≤ RPO（**非 mock**）
- [ ] 切换后数据一致性校验通过
- [ ] DR 预案含场景、决策人、步骤、通信、外部联系人、责任人、RTO/RPO、版本与更新日期
- [ ] DR 演练记录含 RTO / RPO **实测值**，覆盖数据丢失与区域不可用两类场景
- [ ] 演练发现的问题有整改闭环

### 证书、值班与监控

- [ ] 证书剩余 ≤ 30 天告警或自动续期触发
- [ ] 域名与证书清单 100% 含责任人、用途、到期时间
- [ ] 证书链与协议被**外部拨测**校验（非仅本机检查）
- [ ] 值班表零空档，联系方式经演练验证可达
- [ ] 告警升级路径与各层级响应时限明确
- [ ] 值班交接与在办事项有记录
- [ ] 关键资源水位有分级告警
- [ ] 容量模型可换算业务量 → 资源需求与扩容触发点

---

## 11. 部署回滚演练步骤

> 本步骤用于验证 US3（灰度与回滚）与 US5（灾备）的端到端能力。**必须在隔离环境执行，且结果须为真实环境实测值，mock 结果不得计入 RTO/RPO。**

### 11.1 演练前准备

```bash
# 1) 确认当前版本与备份就绪
export MOGO_VERSION=$(./mogo status --json | jq -r '.version')
./mogo backup
./mogo backup-schedule status   # 确认最近一次成功在窗口内

# 2) 记录回滚前基线（关键指标）
./mogo canary metrics --compare chat-api > /tmp/baseline-before.csv

# 3) 确认回滚条件已配置
cat deploy/canary/rollback-conditions.yml
cat deploy/runbook/data-rollback-matrix.md   # 确认本次发布的数据变更可逆性
```

### 11.2 场景 A：灰度失败自动回滚

```bash
# 4) 启动灰度
./mogo canary start --version ${NEW_VERSION}
./mogo canary promote   # 推到 10%

# 5) 注入故障（在隔离环境内人为调高新版本错误率）
#    例如：把 canary 容器的一个关键依赖指向不可用地址

# 6) 等待观察窗口结束，观察自动回滚
./mogo canary status --watch
# 预期输出：auto-rollback triggered, trigger=<metric>, threshold=<value>, observed=<value>

# 7) 记录实测耗时
cat deploy/runbook/rollbacks/*.md   # 每次回滚自动写一条记录

# 8) 校验指标恢复基线
./mogo canary metrics --compare chat-api > /tmp/baseline-after.csv
diff /tmp/baseline-before.csv /tmp/baseline-after.csv
# 预期：错误率、延迟、吞吐恢复至回滚前基线
```

### 11.3 场景 B：整版本回退 + 数据恢复

```bash
# 9) 全量升级到新版本（模拟一次正式发布的失败）
export MOGO_VERSION=${NEW_VERSION}
./mogo update

# 10) 判定需要回退：执行备份恢复
./mogo restore --from /var/backups/mogo/<previous-timestamp> --verify
# 预期：恢复完成 + scripts/verify_restore_business.py 输出 PASS

# 11) 数据一致性校验
./mogo failover verify
# 预期：scripts/verify_data_consistency.py 输出 PASS

# 12) 如本次发布包含数据变更，按兼容性结论处理
cat deploy/runbook/data-rollback-matrix.md
# 不可逆项：执行对应的前向修复脚本 scripts/migrations/<version>_forward_fix.py
# 可逆项：直接回滚代码即可
```

### 11.4 场景 C：单区故障（主机不可用）

```bash
# 13) 在隔离环境拉掉整台主机（模拟区域不可用）
docker stop $(docker ps -q)   # 或整机断电

# 14) 在新主机上重建
#     准备阶段：拉制品 + 恢复备份
./mogo failover prepare --from-host <old-host> --backup /var/backups/mogo/<latest>
./mogo failover execute
./mogo failover verify

# 15) 记录 RTO / RPO 实测值到演练记录
#     部署前时间戳 vs 业务校验 PASS 时间戳 = RTO 实测
#     最后一次成功备份时间戳 vs 故障发生时间戳 = RPO 实测
cat deploy/runbook/drills/TEMPLATE.md   # 按模板填写
```

### 11.5 演练收尾

- [ ] 演练记录已写入 `deploy/runbook/drills/<YYYY-MM-DD>-<scenario>.md`，含 RTO / RPO **实测值**
- [ ] 发现的问题已登记责任人 + 修复方案 + 验证状态
- [ ] RTO / RPO 实测值达标后已固化到 `deploy/runbook/dr-plan.md` 的正式承诺值
- [ ] 演练结论已同步到 001 gatekeeper-governance 的审计体系
- [ ] 本次演练的隔离环境已清理，生产环境未受影响

---

## 12. 与既有特性的接口

| 特性 | 接口 | 说明 |
|---|---|---|
| 001 gatekeeper-governance | `system_audit` | 配置变更审计、发布检查单结论、演练记录均写入既有审计体系 |
| 007 llm-gateway-resilience | 指标口径 | 自动回滚触发条件与灰度对比复用 007 的错误率、超时率、5xx 率口径 |
| 022 security-hardening | 密钥约定 | 密钥不入库遵循 022 的 `.env.example` 约定；备份密钥另立异地管理 |
| 008 ops-dashboard | 数据源 | 水位与证书状态可作为驾驶舱数据源，但本特性不依赖 008 |
