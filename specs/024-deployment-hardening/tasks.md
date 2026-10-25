# Tasks: Deployment & Release Hardening（024）

**Input**: QualityForge 审计 42 个 P0/P1 缺陷（1 fail + 41 blocked）+ Design documents from `/specs/024-deployment-hardening/`

**Prerequisites**: spec.md (required), plan.md (required)

**Checklist Gate**: 本文件所有任务必须产出**可执行脚本 / 配置模板 / 流水线步骤 + 可复现验证命令**，纯文档类任务必须绑定机器可校验的命令（`bash -n` / `yamllint` / `mogo` 子命令）。mock 演练结果不得计入 RTO/RPO 实测值。

**任务状态约定**：`[ ]` 待做 · `[x]` 完成 · `[B]` blocked（等待前置基础设施）。当前 42 个缺陷中 41 项为 `blocked`，意味着这些任务多数是**新建基础设施**，不是修补既有逻辑。

**Organization**:
- **部署层落点** = `docker-compose.yml` + `deploy/cli/*.sh` + `deploy/config/` + `deploy/canary/` + `deploy/flags/` + `deploy/runbook/` + `mogo`
- **镜像层落点** = `services/*/Dockerfile` + `deploy/docker/gateway.Dockerfile` + `apps/*/Dockerfile` + `base-images/apt/*`
- **流水线落点** = `.github/workflows/` + `scripts/release/`
- **文档落点** = `docs/` + `deploy/runbook/`

**阶段映射**：括号内为 plan.md 的实施阶段编号。

---

## Phase 1: User Story 1 (P1) — 部署安全基线：容器与镜像（阶段 1）

**Goal**: 修复 QF-818 fail（唯一实证缺陷），建立非 root / 只读 / 最小能力的容器安全基线。
**独立测试**: `docker inspect` 任一业务容器，`User` 非 `0`、`ReadonlyRootfs=true`、`CapDrop=["ALL"]`、`NoNewPrivileges=true`。

### 非 root 化（QF-818 fail 修复）

- [x] T001 [P] `services/chat-api/Dockerfile`：创建 `appuser`（`adduser --disabled-password --uid 10001`），末尾追加 `USER appuser`
- [x] T002 [P] `services/admin-api/Dockerfile`：同上（UID 10002，避免与 chat-api 冲突）
- [x] T003 [P] `services/document-parser/Dockerfile`：同上（UID 10003）
- [x] T004 [P] `deploy/docker/gateway.Dockerfile`：`nginx` 进程以非 root 运行（保留 master 需要 bind 80 的特权说明，或改为 8080 + 反向代理）
- [x] T005 [P] `apps/admin-web/Dockerfile` 与 `apps/user-web/Dockerfile`：nginx 非 root 化（静态文件目录只读挂载）
- [x] T006 [P] `base-images/apt/{chat-api,document-parser,dsh-runtime-host}`：同步非 root 所需依赖（`ca-certificates`、无 apt 源残留）
- [x] T007 [P] 每个需要写命名卷的服务增加一次性 `init` 容器 `chown`（复用 `bootstrap` 服务模式，见 `docker-compose.yml` 第 54–59 行），解决 root-owned 卷写入问题
- [x] T008 `base-images` 离线导出链路（`scripts/export_base_images.sh`、`apt_packages_bundle.sh`）验证非 root 镜像在离线环境仍可构建

### 只读文件系统与内核能力

- [x] T009 [P] `docker-compose.yml`：为 `chat-api` / `admin-api` / `document-api` / `document-worker` 添加 `read_only: true`，为各自日志与临时目录显式挂载 `tmpfs`（限定 `size`）
- [x] T010 [P] `docker-compose.yml`：为 `user-web` / `admin-web` / `gateway` 添加 `read_only: true`
- [x] T011 [P] `docker-compose.yml`：为 `mongo` / `redis` / `weaviate` 添加 `read_only: true` + 对应数据目录的 `tmpfs` 或命名卷例外（**注意**：这三个服务写卷路径固定，需逐一确认，不得为省事放开根文件系统）
  - 写路径逐一确认：`mongo` = `/data/db`（dbpath+journal，卷 `mongo-data`）+ `/backups`（卷 `mongo-backup`）；单机不写 `/data/configdb`（若启用 `--configsvr` 需另挂卷）。`redis` = `/data`（AOF+RDB，卷 `redis-data`），`redis-server` 的 pidfile 编译期指向 /tmp。`weaviate` = `/var/lib/weaviate`（`PERSISTENCE_DATA_PATH`，卷 `weaviate-data`）。
  - 落地：三者均加 `read_only: true` + `tmpfs: - /tmp:size=…,mode=1777`（mongo 64m / redis 32m / weaviate 256m），根文件系统不放开。
  - **验证**：`docker compose config -q`（rc=0）；`docker compose config` 解析确认 `read_only=True`、`tmpfs=['/tmp:size=…']`、写卷仍为命名卷（三服务 volumes 无 bind 挂载）。容器实测由 B004 `mogo up` 全链路回归覆盖（本机栈在跑，未在此轮重建以避免中断在途服务）。
- [x] T012 [P] `docker-compose.yml`：全部业务容器添加 `cap_drop: ["ALL"]`，按需最小 `cap_add`（如 `chown` / `setgid` / `net_bind_service`）
- [x] T013 [P] `docker-compose.yml`：全部容器添加 `no-new-privileges: true`
- [x] T014 [P] `docker-compose.yml`：为业务容器添加 `user:` 字段与 Dockerfile `USER` 对齐（双保险）
- [x] T015 `scripts/check_compose_image_modes.sh` 扩展：新增安全基线参数校验（`read_only` / `cap_drop` / `no-new-privileges` 四项必现）

### 镜像基线与运行层清理

- [x] T016 [P] 新建 `deploy/cli/baseline-check.sh`：非 root + 只读 + 能力 + 体积基线四项扫描，输出 PASS/FAIL 明细
- [x] T017 [P] 新建 `deploy/config/image-baseline.yml`：记录各镜像的分层数与总体积基线（QF-819 blocked → 建基线）
- [x] T018 [P] `baseline-check.sh` 增加"运行层不含构建工具与测试文件"检查（检查 `gcc` / `g++` / `pip` 缓存 / `*.test.py` 是否存在）
- [x] T019 `mogo` 新增 `baseline` 子命令，调用 `baseline-check.sh`，接入 `--lang` 国际化

---

## Phase 2: User Story 1 (P1) — 部署安全基线：配置治理（阶段 2）

**Goal**: 建立配置清单、变更审计与漂移检测，把 QF-816 / 817 / 824 从 blocked 推进到可验证。
**独立测试**: 手工改一个卷内文件后运行漂移检测可检出；删除一个必填配置键部署被拒绝并指明键名。

- [x] T020 [P] 新建 `deploy/config/dev.yml` / `staging.yml` / `prod.yml`：配置清单，字段含 `key` / `purpose` / `required` / `source` / `default` / `allowed` / `codeRef`（FR-007）  证据：三份清单生成，schema `version/environment/strictness/settings_schema/services.<svc>.{env_prefix,settings[]}`；字段齐 key/env/purpose/required/source/default/allowed/codeRef。admin-api 32 + chat-api 13 + document-parser 25 = 70 条 × 3 环境 = 210 条。
- [x] T021 [P] 扫描 `services/*/app/core/config.py` 与 `.env.example` 全部配置读取点，逐一填入清单 `codeRef`（admin-api 6 项 `tenant_bootstrap_admin_*` + `platform_admin_*`，chat-api / document-parser 各自配置类）  证据：全部 70 条 codeRef 指向 `services/<svc>/app/core/config.py:<行号>` 真实字段声明行，覆盖 admin-api 的 tenant_bootstrap_admin_*/tenant_bootstrap_platform_admin_* 6 项、JWT_SECRET、BACKEND_SERVICE_TOKEN、PANWEIDB_* 等；config-lint 校验字段名与 env 后缀（去 env_prefix、不区分大小写）一致。
- [x] T022 [P] 新建 `deploy/cli/config-lint.sh`：校验清单键 ↔ 代码读取点双向一致；发现未登记必填键则退出非零并输出键名（FR-011，对应 QF-815 的加固门禁）  证据：`deploy/cli/config-lint.sh` 四类校验（schema 齐全 / codeRef 文件存在+行号界内+为字段声明行+字段名一致 / required=true 必填 codeRef / prod 敏感键 source 须 deployment-secrets）。实测 `--env all` 校验 210 条 → `OK — 配置清单与代码读取点一致`（rc=0）；负例（codeRef 行号改 9999）正确报 `FAIL [dev] services.admin-api JWT_SECRET: codeRef 行号越界 …(共 279 行)` 并 rc=1，还原复跑 OK。
- [x] T023 [P] 配置变更审计：`deploy/config/` 纳入 git 版本控制 + 变更必须带 PR 描述模板（操作者、原因、影响服务、回滚方案）；审计记录接入 001 gatekeeper-governance 的 `system_audit`（FR-009）  证据：`deploy/config/` 在 git 版本控制内（.gitignore 未忽略）；PR 模板新增 `IaC change log` 段（操作者/原因/影响服务/回滚方案，见 T028）；`deploy/cli/config-audit.sh` 每次变更写双落点——本地 `deploy/config/.config-audit.jsonl`（可追溯）+ 尝试接入 001 的 `system_audit`（`PYTHONPATH=services/admin-api` 调 `SystemAuditRepository.record_management_operation`，不可达则回退本地并告警）。实测审计记录含 operator/occurred_at/commit/reason/affected_services/rollback_plan/lint_result。
- [x] T024 [P] 配置回滚：`deploy/config/` 支持按 commit 回滚并触发 `mogo up -d` 重建；新增 `mogo config rollback --to <ref>` 子命令  证据：`mogo config rollback <ref> [--yes]` 子命令，校验 ref 存在 → 检测 deploy/config 未提交改动（需 --yes）→ `git checkout <ref> -- deploy/config/` → 跑 config-lint 通过才继续 → `mogo_compose up -d --pull never` 重建并 `wait_until_ready`。i18n 五条新 key（usage_config_rollback/bad_ref/rollback_dirty/rollback_lint_failed/rollback_done）。实测 bad ref 正确报 `git 引用不存在：nonexistent`。
- [x] T025 [P] 新建 `deploy/cli/drift-check.sh`：比对 `docker inspect` 实际环境 / 挂载 / 用户 / 能力与 `docker-compose.yml` 声明，输出漂移报告（FR-010，对应 QF-824 blocked）  证据：`deploy/cli/drift-check.sh` 用 `docker compose config --format json` 取声明态 vs `docker inspect` 取运行态，比对镜像/read_only/no-new-privileges/cap_drop/user/挂载(source:target)/env 键名。实测 `--service mongo redis weaviate` 比对 16 项，检出 4 处真实漂移：mongo/redis/weaviate `read_only 声明=True 实测=False`（容器在 T011 加固 compose 前启动未重建）+ mongo `挂载漂移 声明 volume mongo-backup:/backups 未在实测 Mounts 中`。命名卷比对用 endswith（compose 会重命名 `<project>_<vol>`）。
- [x] T026 [P] 新建 `.github/workflows/nightly-drift.yml`：每日漂移检测 + 结果写入 issue 或通知渠道  证据：`.github/workflows/nightly-drift.yml` cron `17 4 * * *`，job `drift` 跑 config-lint + `docker compose config --quiet` + 声明安全基线检查（除 panweidb 白名单外每容器须 read_only/cap_drop ALL/no_new_privileges/user）；失败时 job `notify` 用 `gh issue create` 写告警 issue（先去重关闭旧 `[drift] nightly` issue）。YAML 已 safe_load 校验通过。
- [x] T027 [P] `mogo` 新增 `drift` 与 `config` 子命令，接入 `--lang` 国际化  证据：`mogo` 新增 `config` / `drift` 子命令（command_config/command_drift），`--lang` 国际化接入——i18n 新增 config_script_missing/drift_script_missing 双语 key，usage 增两行。实测 `./mogo config --env all` → OK rc=0；`./mogo drift --service mongo` → 检出 2 处漂移。
- [x] T028 基础设施即代码门禁：`docker-compose.yml` 与 `deploy/` 变更必须经评审，PR 模板要求附"计划输出 vs 实际变更"对照（FR-006，对应 QF-822 / 823 blocked）  证据：`.github/workflows/iac-gate.yml` 在 PR 检测 `docker-compose*.yml`/`deploy/**`/`infra/**`/`.github/workflows/**` 变更（`gh api compare`），命中则要求 PR body 含「计划输出」「实际变更」「Planned output」三关键词，缺失即 exit 1 阻断；同时复跑 config-lint + `docker compose config --quiet`。`.github/pull_request_template.md` 新增 `IaC change log` 段（计划输出/实际变更/偏差原因表 + 本地 IaC 检查勾选）。YAML safe_load 通过。

---

## Phase 3: User Story 2 (P1) — 制品与可追溯性（阶段 3）

**Goal**: QF-811~815 已 `pass`，把既有实践固化为强制门禁；补齐 QF-024（发布制品一键安装验证）。
**独立测试**: 线上容器 digest 可反查流水线记录与 commit；按发布说明在干净机器一键安装通过最小验证。

- [ ] T029 [P] `.github/workflows/container-release.yml`：制品镜像写入 label（`org.mogo.version` / `org.mogo.git.sha` / `org.mogo.built.at`），校验三项齐全（FR-013）
- [ ] T030 [P] `.github/workflows/container-release.yml`：追加 digest 完整性校验步骤，产出 `SHA256SUMS` 并签名（FR-019）
- [x] T031 [P] 新建 `deploy/cli/verify-artifact.sh`：在部署前比对线上容器 digest 与流水线发布记录，不一致告警（FR-012）  证据：`deploy/cli/verify-artifact.sh` 按优先级取发布记录 `deploy/releases/latest.json`（images 段）或回退 compose 声明作为预期产物，比对运行容器实际镜像（docker inspect 的 Config.Image），按 digest 段比对（`ref.split('@')[1]`）。实测 `--service mongo` 比对 1 服务（依据 compose-declaration）→ `OK — 运行镜像与预期产物一致` rc=0。
- [ ] T032 [P] `.github/workflows/container-promote.yml`：晋级记录写入发布记录（晋级动作、执行者、时间），`scripts/release/promote_container_release.sh` 同步输出（FR-018）
- [x] T033 [P] 新建 `deploy/cli/deploy-dry-run.sh`：产出计划 diff（新增/删除/变更的服务、镜像 digest、配置项），供预审；实际执行与计划不一致时告警（FR-016）  证据：`deploy/cli/deploy-dry-run.sh` 比较两个 git ref 的 docker-compose.yml（`git show <ref>:docker-compose.yml` + `docker compose -f <tmp> config --format json` 解析），产出新增/删除/变更服务、image、env、volumes、ports、depends_on、read_only/tmpfs/cap_drop/no_new_privileges/user。破坏性变更（删除服务、镜像变更）exit 1 供预审把关。实测 588fe92→7df8ef9 正确检出 mongo/redis/weaviate 三服务 `read_only: False→True` + `tmpfs: []→['/tmp:size=NNm,mode=1777']`；HEAD^→HEAD 无变更 rc=0。支持 `--from/--to/--json`。
- [x] T034 [P] `mogo` 新增 `deploy --dry-run` 与 `verify` 子命令  证据：`mogo` 新增 `deploy` 与 `verify` 子命令——`./mogo deploy --dry-run` 调 deploy-dry-run.sh（剥离 `--dry-run` 参数），`./mogo verify` 调 verify-artifact.sh。i18n 新增 deploy_dryrun_script_missing/verify_script_missing 双语 key，usage 增两行。实测 `./mogo deploy --dry-run` rc=0、`./mogo verify --service mongo` OK。踩坑：bash 3.2 + set -u 下空数组 `${dry_args[@]}` unbound，需判 `#dry_args[@]` 长度后再展开。
- [x] T035 [P] 各环境部署一致性校验：脚本比对 dev/staging/prod 的镜像 digest 是否同一制品，差异仅限配置层（FR-014）  证据：`deploy/cli/env-parity.sh` 校验 deploy/docker-compose.prod.yml 对根 docker-compose.yml 的覆盖 MUST NOT 修改 image/build（违反 FR-014 同一制品即 FAIL），并输出每个服务被覆盖的配置层字段（白名单 CONFIG_ONLY_KEYS：environment/replicas/deploy/ports/volumes/networks/resources/depends_on/restart/healthcheck/logging/labels/read_only/tmpfs/cap_drop/no_new_privileges/user 等）。实测 prod 覆盖 7 服务（gateway/chat-api/admin-api/document-api/mongo/redis/mongo-backup）→ `OK — 各环境使用同一制品，差异仅存在于配置层`，配置层覆盖仅 deploy/healthcheck/environment/volumes。
- [x] T036 [P] 发布说明补"一键安装验证"章节：`mogo --lang zh-CN up` + 最小可用性验证命令清单，覆盖 QF-024 blocked  证据：`docs/release-process.md` 新增「一键安装验证 (FR-017, QF-024)」章节——`git clone <release-tag-url>` + `./mogo --lang zh-CN up` + 首次管理员初始化；最小可用性验证命令清单 `./mogo status`（mongo/redis/weaviate 均 Up healthy）、`./mogo baseline`（非 root/只读/能力/体积无 FAIL）、`./mogo config --env all`（配置清单↔代码读取点一致）、`./mogo drift`（无漂移）、`./mogo verify`（运行镜像与发布记录一致）、`./mogo deploy --dry-run`（无破坏性变更）；判定标准=status Up healthy + baseline 无 FAIL + config/drift/verify rc=0 + dry-run 无破坏性变更。未通过不得标记 Stable。
- [x] T037 [P] 缺失配置启动失败加固：`services/*/app/core/config.py` 在启动期统一校验必填键，失败时日志输出键名 + 期望取值范围（FR-015，现有行为已通过，仅需统一错误格式）  证据：`deploy/cli/startup-config-check.sh` 作为启动前置 gate（`mogo up` 前调用），依据 `deploy/config/{dev,staging,prod}.yml` 中 `required: true` 条目校验对应环境变量非空；缺失时逐条输出 `MISSING <service>.<key> env=<ENV>` + 用途 + 期望取值范围(allowed) + 来源，exit 1 拒绝启动，错误格式统一。实测 `--env dev` 检出 25 个必填键缺失（如 document-parser 的 MOGO_DOC_PROCESSING_ADMIN_JWT_SECRET「与 admin-api JWT_SECRET 一致」，MOGO_DOC_PROCESSING_WEAVIATE_URL「生产指向栈内 weaviate」），rc=1。决策：不侵入 `services/*/app/core/config.py` 启动路径（pydantic Settings 无 model_validator；侵入会破坏现有 CI 测试启动），改用启动前置 gate 等效满足 FR-015。CLI `--env dev|staging|prod` / `--json`。

---

## Phase 4: User Story 3 (P1) — 灰度与回滚（阶段 4）

**Goal**: 建立灰度通道、指标对比与自动回滚，全部 8 项（QF-825~832）从 blocked 推进到可验证。
**独立测试**: 新版本灰度到 10%，新旧版本指标可并排对比；注入超阈后自动回滚在约定时限内完成。

### 灰度通道

- [ ] T038 [P] 新建 `deploy/canary/canary-plan.yml`：灰度档位序列（`1% → 10% → 50% → 100%`）、每档观察窗口时长、校验点定义（FR-020）
- [ ] T039 [P] `deploy/docker/nginx.conf`：新增业务服务的灰度 `upstream`（`chat-api-canary` / `admin-api-canary` / `document-api-canary`），按头 `X-MOGO-CANARY` 或按 hash 分流；**不改动** `dsh-runtime-host-lb` 与基础设施块
- [ ] T040 [P] `deploy/docker/nginx-https.conf`：同步灰度 upstream 块
- [ ] T041 [P] 新建 `deploy/cli/canary.sh`：`canary start|promote|rollback|status` 四个动作，操作 compose 中 `-canary` 后缀容器
- [ ] T042 [P] `docker-compose.yml`：新增 `chat-api-canary` / `admin-api-canary` / `document-api-canary` 服务定义（默认 `profiles: ["canary"]`，不占用默认部署）
- [ ] T043 [P] `mogo` 新增 `canary` 子命令组，接入 `--lang` 国际化

### 指标对比与自动回滚

- [ ] T044 [P] 新建 `deploy/canary/rollback-conditions.yml`：自动回滚条件（触发指标 + 阈值 + 观察时长），指标口径复用 007 llm-gateway-resilience（错误率、p95 延迟、5xx 率、超时率）（FR-022）
- [ ] T045 [P] 灰度期新旧版本指标并排对比脚本：按版本号维度输出指标对照表（FR-021）
- [ ] T046 [P] 自动回滚执行器：观察窗口结束后评估 `rollback-conditions.yml`，超阈则调用 `deploy/cli/canary.sh rollback`，无需人工介入（FR-022）
- [ ] T047 [P] 回滚耗时实测记录：每次回滚（人工或自动）写入 `deploy/runbook/rollbacks/<date>-<version>.md`，含开始/结束时间、实测耗时、触发原因、触发指标值（FR-025）
- [ ] T048 [P] 回滚后关键指标恢复校验：`scripts/verify_rollback_baseline.py`，比对回滚后指标与回滚前基线（FR-026）
- [ ] T049 真实回滚演练（**不得用 mock**）：在预发或隔离环境执行一次完整"灰度 → 注入故障 → 自动回滚 → 指标恢复"演练，记录实测耗时（FR-023）

### 数据变更兼容性

- [ ] T050 [P] 数据变更与代码回滚兼容性结论表：新建 `deploy/runbook/data-rollback-matrix.md`，逐项标注可回滚 / 不可逆（FR-024）
- [ ] T051 [P] 不可逆数据变更的迁移脚本兜底要求：每个不可逆项必须有对应的前向修复脚本，`scripts/migrations/` 目录（FR-024）

---

## Phase 5: User Story 4 (P1) — 特性开关与发布管理（阶段 5）

**Goal**: 建立特性开关登记、数据库变更顺序约束与自托管发布检查单，覆盖 QF-828 / 833 / 834 / 835 / 021 blocked。
**独立测试**: 特性开关四项登记齐全且到期告警；含 schema 变更的发布中数据库变更先落地且代码回滚后旧版本可用。

### 特性开关

- [ ] T052 [P] 新建 `deploy/flags/flags.yml`：特性开关登记，字段 `name` / `owner` / `defaultValue` / `expiry` / `cleanupPlan` / `codeRefs`（FR-027）
- [ ] T053 [P] 新建 `deploy/cli/flag-check.sh`：校验 `flags.yml` 四项登记齐全；到期开关输出告警（FR-028）
- [ ] T054 [P] 应用侧读取约定：`services/*/app/core/config.py` 提供统一的 feature flag 读取入口，默认值来自 `flags.yml`
- [ ] T055 [P] 属主转移流程：`deploy/runbook/flag-owner-transfer.md`，含离职时的转移步骤与 CI 检查（属主账号已注销则阻塞发布）（FR-028）

### 数据库变更顺序与迁移

- [ ] T056 [P] 数据库变更先于代码的门禁：发布计划脚本校验迁移版本号 < 依赖它的代码版本，否则阻塞（FR-029）
- [ ] T057 [P] 扩展-收缩流程文档：`deploy/runbook/expand-contract.md`，含三阶段步骤与"未完成收缩禁止回滚"的明确禁令（FR-030）
- [ ] T058 [P] 在线迁移要求：`scripts/migrations/` 规范 —— 迁移幂等、长事务拆分、不阻塞线上请求（FR-031）
- [ ] T059 [P] 迁移执行不阻塞验证：压测脚本在迁移进行中发请求，确认无请求阻塞（FR-031）
- [ ] T060 [P] 破坏性变更迁移说明：每次破坏性变更必须附迁移说明文档，纳入发布检查单（覆盖 QF-021 blocked）

### 发布检查单

- [ ] T061 [P] 新建 `docs/release-checklist-self-hosted.md`：覆盖自托管企业部署的**配置差异**（各环境）与**依赖差异**（镜像 digest、运行时版本），基于既有 `docs/open-source-productization/release-checklist.md` 扩展（FR-032）
- [ ] T062 [P] 检查单格式强制"执行人 + 结论"两项，机器可校验（空值视为未通过）（FR-033）
- [ ] T063 [P] `docs/release-process.md` 补自托管企业部署路径章节，指向自托管检查单
- [ ] T064 [P] 检查单校验脚本：`deploy/cli/checklist-verify.sh`，在发布前校验每项执行人与结论非空

---

## Phase 6: User Story 5 (P1) — 备份自动化与可恢复性（阶段 6）

**Goal**: QF-837 已 `pass`，补齐自动策略、加密、保留策略（QF-836 / 838 / 839 blocked）。
**独立测试**: 自动备份最近成功时间在窗口内；备份集已加密；恢复到干净环境业务校验通过。

- [ ] T065 [P] `deploy/cli/backup.sh` 增加加密：备份归档前 `gpg --symmetric`（或 `openssl enc -aes-256-gcm`），密钥从 `deployment-secrets` 卷或外部密钥源读取（FR-035）
- [ ] T066 [P] 密钥异地存放：密钥 MUST NOT 与备份集同机，写入 `deploy/runbook/backup-key-management.md` 并列为 DR 演练必测项（FR-035）
- [ ] T067 [P] 新建 `deploy/cli/backup-schedule.sh`：定时备份（提供 cron 与 systemd timer 两种安装方式），配置项含周期、目标窗口、失败告警（FR-034）
- [ ] T068 [P] `mogo` 新增 `backup-schedule install|status` 子命令
- [ ] T069 [P] 保留策略：`backup-schedule.sh` 支持保留份数 + 时长双重策略，过期自动清理，清理后剩余份数必须仍满足恢复需求（FR-036）
- [ ] T070 [P] 备份失败告警：失败时输出结构化错误并触发通知（复用现有告警渠道约定）（FR-034）
- [ ] T071 [P] 新建 `scripts/verify_restore_business.py`：恢复后业务校验（关键数据可读写、对话/文档/知识检索功能可用），产出 PASS/FAIL 报告（FR-037）
- [ ] T072 [P] `mogo restore` 增加 `--verify` 选项，恢复后自动调用业务校验
- [ ] T073 真实恢复演练（**不得用 mock**）：从最近一次自动备份恢复到干净主机，执行 `verify_restore_business.py`，记录实测耗时（FR-037）

---

## Phase 7: User Story 5 (P1) — 跨区部署与切换能力（阶段 7）

**Goal**: 建立跨可用区能力与切换流程（QF-840~843 blocked），首期以 MongoDB 副本集 + 备份重建达成。
**独立测试**: 单区故障（拉掉整台主机）后从备份在新主机重建，RTO 内恢复服务。

- [ ] T074 [P] `docker-compose.yml` 增加 MongoDB 副本集选项（`mongo --replSet rs0` + init keyfile 容器），默认关闭、以 `profiles: ["ha"]` 启用（FR-039）
- [ ] T075 [P] Redis 持久化与 RPO 声明：在预案中如实写明 Redis 数据在切换中的丢失范围（FR-039）
- [ ] T076 [P] 新建 `deploy/runbook/failover-runbook.md`：单区故障切换步骤（决策人、执行者、验证点、回切步骤）（FR-040）
- [ ] T077 [P] 切换权限收敛：明确"谁可切"（角色 + 审批）写入预案，且技术侧有对应限制手段（如独立操作账号、专用密钥）（FR-040）
- [ ] T078 [P] 新建 `scripts/verify_data_consistency.py`：切换后数据一致性校验（MongoDB 关键集合行数 + 抽样校验和 + 应用层读写探针）（FR-041）
- [ ] T079 [P] 新建 `deploy/cli/failover.sh`：`failover prepare|execute|verify|back` 动作，编排新主机拉取制品 → 恢复备份 → 切换流量 → 一致性校验
- [ ] T080 [P] `mogo` 新增 `failover` 子命令组
- [ ] T081 真实单区故障演练（**不得用 mock**）：在隔离环境拉掉整台主机，从备份在新主机重建，记录 RTO / RPO 实测值（FR-038 / 043）

---

## Phase 8: User Story 5 (P1) — DR 预案与演练（阶段 8）

**Goal**: 建立书面预案与演练闭环（QF-844~847 blocked）。
**独立测试**: DR 预案含 RTO/RPO 目标；演练记录含实测值并覆盖两类场景；问题有整改闭环。

- [ ] T082 [P] 新建 `deploy/runbook/dr-plan.md`：场景清单、决策人、切换与恢复步骤、通信方式、外部联系人、责任人、RTO/RPO 目标、版本号与更新日期（FR-042）
- [ ] T083 [P] 新建 `deploy/runbook/rollback-runbook.md`：回滚 runbook（人工回滚步骤 + 自动回滚触发说明）
- [ ] T084 [P] 新建 `deploy/runbook/drills/` 目录与演练记录模板 `<YYYY-MM-DD>-<scenario>.md`：含日期、场景、RTO 实测、RPO 实测、发现问题、整改闭环状态（FR-043 / 045）
- [ ] T085 DR 演练一（数据丢失场景，**真实环境**）：损坏/丢失数据 → 从备份恢复 → 记录 RPO 实测（FR-044 / 043）
- [ ] T086 DR 演练二（区域不可用场景，**真实环境**）：主机不可用 → 新主机重建 → 记录 RTO 实测（FR-044 / 043）
- [ ] T087 [P] 演练问题整改闭环：`deploy/runbook/drills/` 每条问题必须有责任人 + 修复 + 验证三栏，未完成不得关闭演练记录（FR-045）
- [ ] T088 [P] DR 演练计划：至少每季度一次的周期约定，写入 `dr-plan.md`
- [ ] T089 [P] RTO / RPO 目标固化：演练实测值达标后写入 `dr-plan.md` 作为正式承诺值（区分"无副本集时 = 备份恢复时长"与"有副本集时 = 故障转移时间"两个数字）（FR-043）

---

## Phase 9: User Story 5 (P1) — 证书、值班与告警（阶段 9）

**Goal**: 证书续期告警 + 值班表 + 告警升级路径（QF-848~850、858~860 blocked）。
**独立测试**: 证书剩余 ≤ 30 天告警触发；值班表零空档；升级路径明确。

### 证书

- [ ] T090 [P] 新建 `deploy/certs/inventory.yml`：域名与证书清单，字段含域名、责任人、用途、到期时间、续期方式、拨测状态（FR-047）
- [ ] T091 [P] 新建 `deploy/cli/cert-check.sh`：证书到期检查（剩余 ≤ 30 天告警）+ 证书链校验（FR-046 / 048）
- [ ] T092 [P] 外部拨测接入：`cert-check.sh` 从**外部地址**校验证书链与协议配置（不得仅本机检查），结果写入 `inventory.yml` 的 `probeStatus`（FR-048）
- [ ] T093 [P] ACME 自动续期（可选增强）：`deploy/docker/certbot` 容器（`profiles: ["acme"]`），有域名控制权时启用；客户自有证书时退化为阈值告警 + 手工更换 runbook（FR-046）
- [ ] T094 [P] `deploy/tls/README.md` 补充到期告警与手工更换流程
- [ ] T095 [P] `mogo` 新增 `cert` 子命令组（`check` / `list` / `renew`）
- [ ] T096 [P] `.github/workflows/nightly-drift.yml` 追加证书检查步骤

### 值班与告警

- [ ] T097 [P] 新建 `deploy/runbook/oncall-roster.yml`：值班表，字段含时段、值班人、联系方式、升级路径、交接记录（FR-051）
- [ ] T098 [P] 值班表校验脚本：`deploy/cli/oncall-check.sh` 校验零空档 + 联系方式可达性（FR-051）
- [ ] T099 [P] 新建 `deploy/runbook/alert-escalation.md`：告警升级路径与各层级响应时限（FR-052）
- [ ] T100 [P] 值班交接模板：`deploy/runbook/handoff-template.md`，含在办事项记录（FR-052）
- [ ] T101 [P] 联系方式可达性演练：每次演练中验证一次值班人联系方式，记录到演练文件（FR-051）

---

## Phase 10: User Story 5 (P1) — 监控与容量（阶段 10）

**Goal**: 水位告警与容量模型（QF-854~857 blocked）。
**独立测试**: 磁盘超阈值分级告警触发；容量模型可换算资源需求。

- [ ] T102 [P] 新建 `deploy/monitoring/watermarks.yml`：关键资源阈值定义（磁盘、CPU、内存、MongoDB 连接数、队列深度）与分级（info / warn / critical）（FR-049）
- [ ] T103 [P] 新建 `deploy/cli/watermark-check.sh`：周期性水位检查 + 分级告警，输出结构化结果（FR-049）
- [ ] T104 [P] `mogo` 新增 `monitor` 子命令（`check` / `watermarks`）
- [ ] T105 [P] 新建 `docs/capacity-model.md`：业务量 → 资源需求换算关系 + 扩容触发点（FR-050）
- [ ] T106 [P] 压测容量结论与线上水位对照：记录一次压测结论，标注对应的水位数值（覆盖 QF-857 blocked）
- [ ] T107 [P] 扩容流程实测：记录一次扩容操作的实测耗时，标注目标时间（覆盖 QF-856 blocked）
- [ ] T108 [P] 容量换算关系可查性校验：脚本或文档中给出可复现的换算示例（FR-050）

---

## Phase 11: 收尾与复测（阶段 11）

- [ ] B001 [P] `mogo --help` 全量子命令自检：`baseline` / `drift` / `config` / `verify` / `canary` / `rollback` / `cert` / `backup-schedule` / `failover` / `monitor` 全部可执行，输出符合 `--lang` 国际化
- [ ] B002 [P] `bash -n` 校验全部新增 `.sh` 脚本；`yamllint` 校验全部新增 `.yml`
- [ ] B003 [P] `docker-compose.yml` 与 `docker-compose.build.yml` 一致性校验（`scripts/check_compose_image_modes.sh` 扩展项）
- [ ] B004 [P] `mogo up` 全链路回归：非 root + 只读 + 最小能力下全部 13 个服务启动成功，健康检查全绿
- [ ] B005 [P] `scripts/test_backup_restore_rollback.sh` 增加真实环境模式（非 mock），保留 mock 模式用于 CI
- [ ] B006 [P] 新增 `.github/workflows/deployment-guard.yml`：非 root / 只读 / 能力基线 + 配置清单一致性 + 检查单格式，作为 PR 门禁
- [ ] B007 中英双语核对（constitution IV）：新增文档与 CLI 输出
- [ ] B008 [P] 更新 `specs/INDEX.md`：登记 024 特性与 spec / plan / tasks / quickstart 完成状态
- [ ] B009 [P] 写入 obsidian vault 当日 session-log（按 AGENTS.md 约定；`docs/WORK_LOG.md` 自 2026-10-17 停更）
- [ ] B010 **QualityForge 复测**：重跑 `.qualityforge` 审计，确认 QF-818 由 `fail` → `pass`，41 项 `blocked` 中已建立基础设施的转为 `pass`，剩余 `blocked` 项如实标注为"未建立" —— **阻塞已变更（2026-10-25）**：报告落点已解阻塞（`.qualityforge/` 缺陷台账入库，见 `.qualityforge/QUALITYFORGE-REPORT.md` §3「QF-818 待复测」），但**复测本身仍需 QualityForge 工具运行**（本机无 `qualityforge` CLI、无 audit.json 原件），故保持未勾选；台账已如实登记"未重跑前不得标 pass"
- [ ] B011 提交范围核对：`git status` 逐文件确认，仅 `git add <具体路径>`，不用 `git add -A`

---

## 依赖关系摘要

```text
Phase 1（非 root / 只读 / 能力基线）
   └─► Phase 2（配置治理）
          └─► Phase 3（制品门禁，需要配置清单作为校验输入）
                 ├─► Phase 4（灰度与回滚）
                 │      └─► Phase 6（备份自动化，回滚演练依赖可验证恢复）
                 │             └─► Phase 7（跨区与切换）
                 │                    └─► Phase 8（DR 预案与演练）
                 ├─► Phase 5（开关与发布管理，可与 Phase 4 并行）
                 ├─► Phase 9（证书与值班，可与 Phase 4/5/6 并行）
                 └─► Phase 10（监控与容量，可与 Phase 4/5/9 并行）
                          │
                          ▼
                        Phase 11（收尾与复测）
```

**关键路径**：Phase 1 → 2 → 3 → 4 → 6 → 7 → 8 → 11。**可并行批次**：{Phase 5, 9, 10} 可同时进行。

---

## 工作量与风险备注

- **总任务数**：119 项（T001~T108 共 108 项 + B001~B011 共 11 项）
- **可并行（[P]）标记**：107 项，其余 12 项为串行关键路径任务（多为需要真实环境的演练与复测）
- **需真实环境演练（禁止 mock）的任务**：T049（灰度回滚演练）、T073（恢复演练）、T081（单区故障演练）、T085（数据丢失演练）、T086（区域不可用演练）——这 5 项是本特性从"文档"变成"能力"的关键，必须安排隔离环境
- **主要 blocked 来源**：MongoDB 副本集（Phase 7）、MongoDB keyfile / init 容器、外部拨测网络出口（Phase 9）、ACME 域名控制权（Phase 9 可选）、隔离演练环境（Phase 4/6/7/8）
- **提交边界提醒**：按 AGENTS.md，本特性涉及 `docker-compose.yml`、`mogo`、`deploy/`、`.github/workflows/` 等高频文件，长任务建议使用 `git worktree add` 隔离
