# Implementation Plan: Deployment & Release Hardening（部署与发布加固）

**Branch**: `024-deployment-hardening` | **Date**: 2026-10-11 | **Spec**: [spec.md](./spec.md)

**Input**: QualityForge 审计 42 个 P0/P1 缺陷（1 fail + 41 blocked），覆盖部署安全、制品与可追溯性、灰度与回滚、特性开关与发布管理、持续运行与灾备。**41 项 blocked 的含义是"基础设施尚未建立"，本特性主体工作是建基础设施而非改业务代码。**

## Summary

当前部署链路的事实基线（`.qualityforge/audit.json` 与仓库实读）：

1. **唯一实证缺陷**：`services/*/Dockerfile` 与 `deploy/docker/gateway.Dockerfile` 无 `USER` 指令，全部容器以 root 运行（QF-818 fail）。
2. **加固参数全缺**：`docker-compose.yml` 中 `user:` / `read_only:` / `cap_drop:` / `no-new-privileges:` 出现次数为 **0**。
3. **配置无治理**：无环境配置清单、无配置变更审计、无漂移检测（QF-816 / 817 / 824 blocked）。
4. **制品层大部分已达标**：QF-811~815 已 `pass`（同制品、带版本与提交标识、配置与代码分离、缺失配置启动失败），仅需固化为强制门禁。
5. **灰度与回滚零基础**：单机 Compose 一次替换全部实例，无灰度通道、无自动回滚条件（QF-825~832 全 blocked）。
6. **备份已可用但未自动化**：`deploy/cli/` 的 `backup.sh` 已归档 8 个命名卷 + SHA256SUMS + 版本/commit 标记，QF-837 已 `pass`；缺自动策略、加密、保留策略（QF-836 / 838 / 839 blocked）。
7. **演练只是 mock**：`scripts/test_backup_restore_rollback.sh` 把 Docker 调用全部 mock，其结果不能计入 RTO/RPO 实测值。
8. **DR / 证书 / 值班全空白**：无书面预案、无证书续期告警（`deploy/tls/README.md` 为手工放置）、无值班表与告警升级路径。

本方案：

1. 以 **docker-compose.yml + mogo CLI + GitHub Actions** 为唯一承载，不引入 Kubernetes；
2. 按 **US1（安全基线）→ US2（制品）→ US3（灰度回滚）→ US4（开关与发布）→ US5（持续运行与灾备）** 顺序实施，前者是后者的前置；
3. 每个子域产出"**可执行的脚本 / 配置模板 / 流水线步骤 + 可复现的验证命令 + 可追溯的记录文件**"三件套，把 blocked 项从"未建立"推进到"已建立且可验证"；
4. 与 001 gatekeeper-governance 复用审计存储，与 007 llm-gateway-resilience 复用指标口径，不新建平行机制。

## Technical Context

**Language/Version**: Bash 5（CLI 与部署脚本）、Python 3.13（校验脚本）、YAML（compose / 流水线 / 配置清单）

**Primary Dependencies**: Docker Compose v2、nginx 1.31（灰度分流）、MongoDB 6.0.20、Redis 7.4.2-alpine、Weaviate 1.25.7、GitHub Actions、HashiCorp Vault（可选，非强制依赖）

**Storage**: MongoDB（主存储）、Redis（缓存）、Weaviate（向量）、命名卷 10 个（卷前缀 `movo_`：`deployment-secrets` / `mongo-data` / `redis-data` / `weaviate-data` / `dsh-runtime-data` / `askai-storage` / `knowledge-storage` / `admin-static` 等）、备份归档 `tar.gz` + `SHA256SUMS`

**Testing**: `scripts/test_backup_restore_rollback.sh`（既有 mock 演练）、`scripts/release/test_plan_container_release.py`、新增校验脚本以 Bash + Python 断言形式落地

**Target Platform**: 自托管 Docker Compose（Linux x86_64 / arm64），Linux 主机单机部署

**Project Type**: brownfield —— 在既有部署链路上叠加加固层

**Performance Goals**: 灰度分流引入的 nginx 开销 < 1%；配置校验在部署前完成，不增加运行时开销；漂移检测周期 ≥ 5 分钟；T1 级回滚 ≤ 约定分钟数（首期目标 15 分钟，实测后固化）

**Constraints**: 不引入 Kubernetes；不做多区域 active-active；不做自动扩缩容；不重写 QF-811~815 已 `pass` 的机制；不新增顶层服务模块

**Scale/Scope**: 单机部署，13 个服务、10 个命名卷；5 个子域、52 个 FR、约 60 个实施任务

## 现有实现事实（contract 依据）

**部署入口**

- `docker-compose.yml`：13 个服务（`mongo` / `redis` / `weaviate` / `chat-api` / `admin-api` / `document-api` / `document-worker` / `user-web` / `admin-web` / `gateway` / `dsh-runtime-host`×3 / `dsh-runtime-host-lb` / `bootstrap`）、10 个命名卷（前缀 `${MOVO_VOLUME_PREFIX:-movo}`）、两张网络（`public` / `backend`）
- `mogo` CLI（Bash 脚本）：`up` / `build` / `update` / `backup` / `restore` / `status` / `logs` / `restart` / `down`，`--lang` 国际化；`deploy/cli/` 下拆分 `backup.sh` / `images.sh` / `pull.sh` / `base-images.sh` / `dsh-version.sh` / `i18n.sh`
- `docker-compose.build.yml`：本地构建变体

**镜像构建**

- `services/{admin-api,chat-api,document-parser}/Dockerfile`：`ARG BASE_IMAGE=python:3.13-slim-bookworm` + `FROM ${BASE_IMAGE}`，**无 `USER` 指令**
- `deploy/docker/gateway.Dockerfile`、`apps/{admin-web,user-web}/Dockerfile`：同问题
- `base-images/apt/{chat-api,document-parser,dsh-runtime-host}`：既有 apt 依赖打包目录，非 root 化时需同步
- `scripts/export_base_images.sh` / `apt_packages_bundle.sh` / `pip_wheels_bundle.sh`：基础镜像离线导出链路

**备份与回滚（唯一已可用环节）**

- `deploy/cli/backup.sh`：`MOVO_VOLUME_SUFFIXES` 8 项、`movo_sha256_create` / `movo_sha256_verify`、`movo_volume_prefix`（校验前缀合法性）、`movo_write_backup`（归档 + SHA256SUMS + 版本/commit 标记）
- `scripts/test_backup_restore_rollback.sh`：backup → upgrade → rollback 全链路，**Docker 调用全部 mock**

**流水线**

- `.github/workflows/`：`container-release.yml`（发布 candidate，校验 amd64/arm64）、`container-promote.yml`（晋级）、`quality-gate.yml`、`runtime-guard.yml`、`dsh-upgrade-candidate.yml`、`dsh-migration-step1.yml`
- `scripts/release/plan_container_release.py` + `promote_container_release.sh`：发布计划与晋级脚本

**发布与部署文档**

- `docs/release-process.md`：开源社区发布流程（不可变 commit/tag/GHCR）
- `docs/open-source-productization/release-checklist.md`：既有发布检查单（**不覆盖自托管企业部署的配置与依赖差异**）
- `docs/docker-deployment.md`、`docs/windows-installation.md`、`deploy/production/`（`prepare-release.sh` / `merge_images.py` / `render_deploy_doc.py` / `verify_bundle.py` / `docker-compose.portainer.yml.tpl`）

**TLS**

- `deploy/tls/README.md`：手工放置 `fullchain.pem` / `privkey.pem`，`cp deploy/docker/nginx-https.conf deploy/docker/nginx.conf` + 解开 443 端口注释。**无自动续期、无到期告警。**

**MongoDB**

- `docker-compose.yml` 中无 `--replSet` 参数，即**当前为单节点无副本集**。跨区切换能力需先引入副本集（FR-039）。

## Constitution Check

*GATE: 必须通过后方可进入设计。*

| 原则 | 结果 | 说明 |
|---|---|---|
| I. Specification-First | ✅ | 本文件为 `/speckit-plan` 产出；spec.md 已先行完成 |
| II. Enterprise Production Readiness | ✅ | 每个子域产出脚本/配置模板/流水线三件套；灰度与回滚必须有真实环境演练，mock 结果不计入实测值 |
| III. Security and Data Protection | ✅ | 非 root / 只读 / 最小能力是 US1 核心目标；密钥不入库（`.env.example` 约定不变）；备份加密且密钥异地 |
| IV. Cross-Platform and i18n | ✅ | 新增 CLI 输出沿用 `deploy/cli/i18n.sh` 的 `--lang` 机制；新增文档中英对照或简体中文 |
| V. Observability and Simplicity | ✅ | 遵循 YAGNI：不引入 Kubernetes、不做多区域 active-active、不做自动扩缩容；Vault 为可选路径 |
| Agent Operating Rules | ✅ | 不删除文件；每轮更新 `docs/WORK_LOG.md`；只改必要文件；不用 `git add -A` |

**结论**：无违规项，无需填写 Complexity Tracking。

## Architecture

### 部署与发布流水线（目标态）

```text
git push (main / tag)
   │
   ▼
[1] container-release.yml  ── 构建多架构镜像 ──► candidate 制品（版本 + commit SHA + digest）
   │                                              │
   │                                              ▼
   │                                     [2] 制品门禁（新增）
   │                                          · 镜像 digest 可追溯（FR-012/013/019）
   │                                          · 非 root + 只读 + 最小能力基线扫描（FR-001/004/005）
   │                                          · 镜像体积/分层基线比对（FR-003）
   │                                          · 运行层不含构建工具与测试（FR-002）
   │                                              │
   │                                              ▼
   │                                     [3] container-promote.yml
   │                                          · 晋级记录（执行者 + 时间，FR-018）
   │                                              │
   ▼                                              ▼
[4] 部署前置校验（新增 mogo 子命令）
    · 配置清单 vs 代码读取点一致性（FR-007/011）
    · 部署 dry-run 产出计划 diff（FR-016）
    · 漂移检测（FR-010）
        │
        ▼
[5] 灰度发布（新增）
    · nginx 分流：1% → 10% → 50% → 100%（FR-020）
    · 每档观察窗口 + 校验点
    · 新旧版本指标并排对比（FR-021）
        │
        ├──► 指标健康 ──► 放量 ──► 全量 ──► 收尾
        │
        └──► 指标超阈 ──► 自动回滚（FR-022/023/025/026）
                              · 回滚耗时实测记录
                              · 关键指标恢复基线校验
                              · 数据变更兼容性按结论处理（FR-024）

[6] 持续运行（新增）
    · 自动备份（周期 + 加密 + 保留策略，FR-034/035/036）
    · 水位监控与分级告警（FR-049）
    · 证书阈值告警 / 自动续期（FR-046/047/048）
    · 值班表与告警升级路径（FR-051/052）
        │
        ▼
[7] DR（新增）
    · 书面预案 + 责任人（FR-042）
    · 演练：数据丢失 + 区域不可用两类场景（FR-043/044）
    · RTO/RPO 实测值 + 整改闭环（FR-045）
```

### 目录结构（新增 / 变更）

```text
deploy/
├── docker/
│   ├── nginx.conf                          # [改] 增加灰度 upstream 与按头/按 hash 分流
│   └── nginx-https.conf                    # [改] 同步灰度块
├── cli/
│   ├── backup.sh                           # [改] 加密 + 保留策略 + 失败告警（FR-034~036）
│   ├── backup-schedule.sh                  # [新] 定时备份（cron/systemd timer 两种落地）
│   ├── drift-check.sh                      # [新] 漂移检测：运行态 vs compose 声明（FR-010）
│   ├── config-lint.sh                      # [新] 配置清单 vs 代码读取点一致性（FR-007/011）
│   ├── baseline-check.sh                   # [新] 镜像安全基线扫描（非 root/只读/能力，FR-001/004/005）
│   └── cert-check.sh                       # [新] 证书到期与链校验 + 外部拨测（FR-046~048）
├── certs/                                  # [新] 域名与证书清单（FR-047）
│   └── inventory.yml
├── config/                                 # [新] 各环境配置清单（FR-007）
│   ├── dev.yml
│   ├── staging.yml
│   └── prod.yml
└── runbook/                                # [新] DR 预案与演练记录（FR-042~045）
    ├── dr-plan.md
    ├── rollback-runbook.md
    ├── drills/                             # [新] 演练记录（每次演练一个文件）
    ├── oncall-roster.yml                   # [新] 值班表（FR-051）
    └── alert-escalation.md                 # [新] 告警升级路径（FR-052）

docker-compose.yml                          # [改] read_only / cap_drop / no-new-privileges / user
services/*/Dockerfile                       # [改] 非 root 用户（QF-818 fail 修复）
deploy/docker/gateway.Dockerfile            # [改] 同上
apps/*/Dockerfile                           # [改] 同上
base-images/apt/*                           # [改] 同步非 root 依赖
.github/workflows/
├── container-release.yml                   # [改] 追加制品门禁步骤
├── container-promote.yml                   # [改] 晋级记录（执行者 + 时间）
└── nightly-drift.yml                       # [新] 每日漂移检测 + 证书检查
mogo                                        # [改] 新增子命令：baseline / drift / canary / rollback / cert / backup-schedule
deploy/canary/                              # [新] 灰度配置与脚本
│   ├── canary-plan.yml                     # [新] 灰度档位与观察窗口定义（FR-020）
│   └── rollback-conditions.yml             # [新] 自动回滚条件（FR-022）
deploy/flags/                               # [新] 特性开关登记（FR-027/028）
│   └── flags.yml
docs/
├── release-process.md                      # [改] 补自托管企业部署路径
├── release-checklist-self-hosted.md        # [新] 覆盖配置与依赖差异的检查单（FR-032/033）
├── capacity-model.md                       # [新] 容量模型（FR-050）
└── work-log.md                             # [改] 每轮更新

scripts/
├── test_backup_restore_rollback.sh         # [改] 增加真实环境模式（非 mock）
├── verify_restore_business.py              # [新] 恢复后业务校验（FR-037）
└── verify_data_consistency.py              # [新] 切换后数据一致性校验（FR-041）
```

**Structure Decision**: 全部加固逻辑落在 `deploy/` 与 `mogo` CLI 下，业务代码（`services/*`、`apps/*`）只改 Dockerfile 与必要的配置校验入口，不新增业务模块。特性开关走"配置文件登记 + 应用侧读取"的轻量方案，不引入独立的开关服务。

## 与现有特性的关系

| 特性 | 关系 | 说明 |
|---|---|---|
| **001 gatekeeper-governance**（六层门禁） | 审计联动 | 配置变更审计（FR-009）、发布检查单结论（FR-033）、演练记录（FR-043）均写入既有审计体系（`system_audit`），不新建平行审计存储。001 的门禁能力可作为配置变更与部署前置校验的调用方。 |
| **007 llm-gateway-resilience**（网关韧性） | 指标联动 | 自动回滚触发条件（FR-022）中的大模型调用指标（重试率、超时率、5xx 率）复用 007 已定义口径，不重复定义指标；灰度期新旧版本对比（FR-021）同样沿用该口径。 |
| **022 security-hardening** | 边界协同 | 022 覆盖应用层安全（认证、授权、输入、数据）；本特性覆盖部署层安全（容器、镜像、基础设施）。二者在"密钥不入库"与"审计"上交界，以 022 的密钥约定为准。 |
| **008 ops-dashboard**（驾驶舱） | 数据源 | 水位监控与分级告警（FR-049）、证书状态（FR-046）可作为 008 驾驶舱的数据源，但本特性不依赖 008 落地。 |

## 实施阶段映射

| 阶段 | 子域 | 内容 | 覆盖 FR / QF |
|---|---|---|---|
| 1 | US1 安全基线 | 非 root 化（QF-818 fail 修复）+ `read_only` / `cap_drop` / `no-new-privileges` + 镜像体积基线 + `baseline-check.sh` | FR-001~005、003 |
| 2 | US1 配置治理 | 配置清单 `deploy/config/` + `config-lint.sh` + 配置变更审计与回滚 + `drift-check.sh` | FR-006~011 |
| 3 | US2 制品门禁 | 流水线追加 digest 追溯与完整性校验、dry-run 计划 diff、发布说明一键安装、晋级记录 | FR-012~019、QF-024 |
| 4 | US3 灰度与回滚 | nginx 灰度分流 + `canary-plan.yml` + 新旧版本指标对比 + 自动回滚条件 + 真实回滚演练 | FR-020~026 |
| 5 | US4 开关与发布 | `deploy/flags/flags.yml` + 属主/默认值/清理计划 + 数据库变更顺序 + 扩展-收缩 + 自托管检查单 | FR-027~033、QF-021 |
| 6 | US5 备份自动化 | `backup-schedule.sh` + 加密 + 保留策略 + 恢复业务校验 | FR-034~037 |
| 7 | US5 跨区与切换 | MongoDB 副本集 + 切换手段与权限 + 一致性校验脚本 | FR-038~041 |
| 8 | US5 DR 与演练 | `dr-runbook/` 预案 + 真实演练（数据丢失 + 区域不可用）+ RTO/RPO 实测 + 整改闭环 | FR-042~045 |
| 9 | US5 证书与值班 | `cert-check.sh` + 证书清单 + 外部拨测 + 值班表 + 告警升级路径 | FR-046~048、051、052 |
| 10 | US5 监控与容量 | 水位监控与分级告警 + 容量模型 | FR-049~050 |
| 11 | 收尾 | 全量验证 + 文档双语核对 + `docs/WORK_LOG.md` + QualityForge 复测 | 全部 |

**顺序约束**：阶段 1 是阶段 3~10 的前置（基线不成立，灰度/回滚都跑在不可信环境上）；阶段 2 是阶段 3 的前置（制品门禁需要配置清单作为校验输入）；阶段 4 依赖阶段 6（回滚演练需要可验证的备份恢复）；阶段 8 依赖阶段 7。阶段 3 / 5 / 9 / 10 之间可并行。

## 关键风险与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| 非 root 化后既有命名卷权限为 root-owned，容器写不进去 | 服务启动即失败，属阻断性 | 每个需要写卷的服务增加一次性 `init` 容器 `chown`（复用 `bootstrap` 服务模式），不放开 root 运行；先在 `docker-compose.build.yml` 本地验证再改生产 compose |
| `distroless` 缺少 CA 证书与 shell，运维无法进入容器排查 | 排障能力下降 | 首期保留 `slim-bookworm` 并显式安装 `ca-certificates`，不追求极致精简（见 spec Edge Cases） |
| nginx 同时是入口反代与 dsh-runtime 反代，灰度分流改 nginx 可能影响 dsh-runtime | 灰度改动波及基础设施 | 灰度只作用于业务服务（`chat-api` / `admin-api` / `document-api`），dsh-runtime 与 mongo/redis/weaviate 不参与灰度；nginx 改动分两次合并并各自灰度验证 |
| 现有 `test_backup_restore_rollback.sh` 全部 mock，容易让人误以为已演练过 | RTO/RPO 实测值为空 | 明确写入 Assumptions 与 spec Edge Cases：mock 结果不计入实测值；阶段 8 必须有一次真实环境演练并留存记录 |
| 首期无 MongoDB 副本集，"跨可用区切换"只能是备份重建 | RTO 取决于备份恢复时长，可能被误读为秒级切换 | 预案中如实写明 RTO = 备份恢复时长；阶段 7 引入副本集后缩短到故障转移时间；两个数字分别记录，不混淆 |
| 备份加密密钥与备份集同机存放 → 加密等于没加密 | 密钥泄露即数据泄露 | 密钥 MUST 与备份集异地（FR-035）；密钥可用性列为 DR 演练必测项 |
| 客户使用自有证书，无域名控制权，无法 ACME | FR-046 无法达成自动续期 | 退化为阈值告警（剩余 ≤ 30 天）+ 手工更换 runbook；在检查单中如实标注"自动续期：不适用（客户自有证书）" |
| 41 项 blocked 的工作量集中在"新建基础设施"，容易被实现成"只写文档不写脚本" | 特性变成空洞文档 | 每个 FR 的任务必须产出**可执行脚本或流水线步骤 + 可复现验证命令**；纯文档类任务必须绑定一个验证命令（如 `bash -n`、`yamllint`、`mogo cert check`） |
| 特性开关到期无人清理，属主离职后成为孤儿 | 代码分支永久残留 | FR-028 到期告警 + 属主转移流程；`flags.yml` 校验任务在 CI 中检查到期项 |
| 检查单被"全套勾选不写执行人"糊弄 | 检查单形同虚设 | FR-033 格式强制执行人字段，`release-checklist-self-hosted.md` 用机器可校验的表格格式，空值视为未通过 |
| 回滚代码但数据库已收缩 | 数据损坏，不可逆 | FR-024 要求每项数据变更给出可逆性结论；扩展-收缩流程禁止在未完成收缩前回滚；迁移脚本必须幂等 |
