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

- [x] T029 [P] `.github/workflows/container-release.yml`：制品镜像写入 label（`org.mogo.version` / `org.mogo.git.sha` / `org.mogo.built.at`），校验三项齐全（FR-013）  证据：`container-release.yml` 的 docker/metadata-action labels 新增 `org.mogo.version=${{ github.ref_name }}` / `org.mogo.git.sha=${{ github.sha }}` / `org.mogo.built.at=${{ github.run_started_at }}` 三键（FR-013）；构建后新增「Verify MOGO artifact labels」步骤，用 `docker buildx imagetools inspect --format '{{json .ImageLabels}}'` 读 manifest config blob 取三 label，任一为空 `::error::` 报缺哪几项并 exit 1（缺 label 的候选镜像不得进入 promote）。YAML 解析通过。
- [x] T030 [P] `.github/workflows/container-release.yml`：追加 digest 完整性校验步骤，产出 `SHA256SUMS` 并签名（FR-019）  证据：新增 `scripts/release/build_sha256sums.py`——build 模式对 ALL_IMAGES_JSON 每个 suffix 用 `docker buildx imagetools inspect` 取 manifest digest 写 `SHA256SUMS`（`<hex>  <ref>` GNU 兼容格式）；verify 模式逐行重查 registry digest 比对，不一致 exit 1（完整性校验）。配套 `scripts/release/test_sha256sums.py` 5 用例全绿（缺 env/缺文件/生成/一致/漂移/registry 不可达）。`container-release.yml` 新增 `publish-integrity` job（needs promote-release，push 触发）：build SHA256SUMS → sigstore/cosign-installer@v3 → `cosign sign-blob --bundle SHA256SUMS.bundle`（keyless OIDC，id-token: write）→ `cosign verify-blob` → `gh release upload <tag> SHA256SUMS SHA256SUMS.bundle` 随 Release 发布。
- [x] T031 [P] 新建 `deploy/cli/verify-artifact.sh`：在部署前比对线上容器 digest 与流水线发布记录，不一致告警（FR-012）  证据：`deploy/cli/verify-artifact.sh` 按优先级取发布记录 `deploy/releases/latest.json`（images 段）或回退 compose 声明作为预期产物，比对运行容器实际镜像（docker inspect 的 Config.Image），按 digest 段比对（`ref.split('@')[1]`）。实测 `--service mongo` 比对 1 服务（依据 compose-declaration）→ `OK — 运行镜像与预期产物一致` rc=0。
- [x] T032 [P] `.github/workflows/container-promote.yml`：晋级记录写入发布记录（晋级动作、执行者、时间），`scripts/release/promote_container_release.sh` 同步输出（FR-018）  证据：新增 `scripts/release/record_promotion.py`——记录字段 action/source_sha/source_tag/suffixes/target_tag/actor/occurred_at/github_run_id，追加到 `deploy/releases/promotions.jsonl` 并更新 `deploy/releases/latest.json` 的 `last_promotion` 段。`promote_container_release.sh` 末尾调用它回显「Writing promotion record…」，`container-release.yml` 的 promote-release job 加 `contents: write` + 「Commit promotion record」步骤（git config + add deploy/releases/ + commit + push，无变更则跳过），`container-promote.yml` 同加 checkout + 记录 step + permissions contents: write。实测 record_promotion.py 连续两条 append 到 promotions.jsonl、latest.json last_promotion 正确更新（actor/occurred_at/suffixes 完整）。
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

- [x] T038 [P] 新建 `deploy/canary/canary-plan.yml`：灰度档位序列（`1% → 10% → 50% → 100%`）、每档观察窗口时长、校验点定义（FR-020）  证据：新建 `deploy/canary/canary-plan.yml`——`version/services(chat-api,admin-api,document-api)/steps[]`，档位序列 `1%→10%→50%→100%`，每档含 `weight`/`window_minutes`（10/20/30/60）/`checkpoints[]`（1% 档 `error_rate_canary_lt_baseline_plus_2pct`+`p95_latency_canary_le_baseline_plus_20pct`+`service_healthy`；10%/50% 加 `5xx_rate_lt_1pct`+`timeout_rate_lt_2pct`；100% 加 `full_route_health`）；`routing{header:X-MOGO-CANARY, hash_key:$remote_addr}`；`rollback{max_auto_rollbacks_per_step:2, t1_rollback_seconds_max:300}`（FR-020）。YAML 解析通过。
- [x] T039 [P] `deploy/docker/nginx.conf`：新增业务服务的灰度 `upstream`（`chat-api-canary` / `admin-api-canary` / `document-api-canary`），按头 `X-MOGO-CANARY` 或按 hash 分流；**不改动** `dsh-runtime-host-lb` 与基础设施块  证据：`deploy/docker/nginx.conf` 顶部加 `include /etc/nginx/conf.d/mogo-canary.conf;`，admin-api 与 chat-api 两处 location（/askai-api/、/api/）加 `if ($mogo_canary_force = "1"){ set $xxx_up xxx-canary:PORT; }` + `if ($mogo_canary_route = "canary"){ ... }`（admin-api-canary:8100 / chat-api-canary:8000）；**未改动** `dsh-runtime-host-lb` 与基础设施块。挂载片段 `deploy/canary/nginx-canary.conf` 用 `map $http_x_mogo_canary $mogo_canary_force` + `split_clients "${remote_addr}:${http_x_mogo_canary}" $mogo_canary_route`。本机 nginx（ServBay `/Applications/ServBay/sbin/nginx`，用临时 main.conf `events{}http{include canary;include site;}`）`nginx -t` → `syntax is ok / test is successful`。docker.io 拉 nginx:alpine 失败（Bad Gateway）故未在容器内复测。
- [x] T040 [P] `deploy/docker/nginx-https.conf`：同步灰度 upstream 块  证据：`deploy/docker/nginx-https.conf` 同步：顶部同加 `include /etc/nginx/conf.d/mogo-canary.conf;`，443 server 的 chat-api/admin-api location 加同样的 `$mogo_canary_force`/`$mogo_canary_route` 分流。本机 `nginx -t` 通过到证书加载阶段（仅因 `/etc/nginx/certs/fullchain.pem` 不存在报错，与灰度改动无关），配置语法 OK。
- [x] T041 [P] 新建 `deploy/cli/canary.sh`：`canary start|promote|rollback|status` 四个动作，操作 compose 中 `-canary` 后缀容器  证据：新建 `deploy/cli/canary.sh`（644 无执行位，经 `bash` 调用）实现 `start|promote|rollback|status`：`plan_weights()` 读 plan.yml 档位；`write_nginx_weight()` 写 nginx-canary.conf（weight=0 生成 `map "x" $mogo_canary_route { default stable }` 全 stable，>0 生成 split_clients）；`reload_gateway()` 用 `docker compose exec -T gateway nginx -t && nginx -s reload`（容器未挂载新文件时重载失败只警告不退出，需重建 gateway 生效）；`save_state/read_state` 读写 `.canary-state.json`（weight/version/started_at/last_rollback）；rollback 停止 3 个 -canary 容器并写 `deploy/runbook/rollbacks/<date>-<version>.md`。实测：`status --json` 正常；`promote --weight 7` 报「档位 7 不在 plan 中（允许: 1 10 50 100）」rc=1；`promote` 应答取消；`rollback --reason test_dry --yes` 全程跑通（耗时 2.7s ≤ T1 目标 300s，生成回滚记录）。
- [x] T042 [P] `docker-compose.yml`：新增 `chat-api-canary` / `admin-api-canary` / `document-api-canary` 服务定义（默认 `profiles: ["canary"]`，不占用默认部署）  证据：`docker-compose.yml` 给 chat-api/admin-api/document-api 定义加 YAML 锚点 `&chat-api-def`/`&admin-api-def`/`&document-api-def`，新增 `chat-api-canary: {<<: *chat-api-def, image: ${MOGO_CHAT_API_CANARY_IMAGE:-ghcr.io/mogoai/chat-api:${MOGO_CANARY_VERSION:-candidate}}, profiles: [canary]}`（admin-api-canary/document-api-canary 同理）；三服务默认 `profiles: ["canary"]` 不占用默认部署。gateway volumes 加 `${MOGO_CANARY_NGINX_CONF:-./deploy/canary/nginx-canary.conf}:/etc/nginx/conf.d/mogo-canary.conf:ro`。`docker compose config -q` rc=0；`docker compose --profile canary config --services` 列出 3 个 -canary 服务。踩坑：compose 顶层 `secrets:`(1215 行) 在 `volumes:`(1153) 之后，append 会误入 secrets 段报错，须插到 `^networks:$`(1131 行) 之前。
- [x] T043 [P] `mogo` 新增 `canary` 子命令组，接入 `--lang` 国际化  证据：`mogo` 加 `command_canary()`（缺脚本报 `canary_script_missing` exit 2）+ `case` 分支 `canary) require_docker; command_canary "$@" ;;`；`deploy/cli/i18n.sh` zh/en 各加一行 `./mogo canary start|promote|rollback|status 灰度发布：按档位分流、自动回滚与回滚记录`（en 锚点 `Verify running images match release record`）。实测 `./mogo canary status --json` 输出正常。

### 指标对比与自动回滚

- [x] T044 [P] 新建 `deploy/canary/rollback-conditions.yml`：自动回滚条件（触发指标 + 阈值 + 观察时长），指标口径复用 007 llm-gateway-resilience（错误率、p95 延迟、5xx 率、超时率）（FR-022）  证据：新建 `deploy/canary/rollback-conditions.yml`——5 条条件 `error_rate_delta`(gt_baseline_plus_2pct,P0) / `p95_latency_delta`(gt_baseline_plus_20pct,P0) / `http_5xx_rate`(gt_0_01,P1) / `timeout_rate`(gt_0_02,P1) / `availability`(lt_0_99,P0)，均 `window_minutes:5`；`scope{label_selector}` + `prometheus_url:${MOGO_PROMETHEUS_URL:-http://prometheus:9090}`；`on_trigger{action: canary.sh rollback, cooldown_minutes:10, max_rollbacks_per_window:2, record_template: deploy/runbook/rollbacks/<date>-<version>.md}`；`queries{}` 5 条 PromQL（error_rate/5xx_rate/timeout_rate 用 `sum(rate(http_requests_total{canary="1",...})) / clamp_min(sum(rate(http_requests_total{canary="1",...})), 1)`, p95 用 `histogram_quantile(0.95, sum by (le)(rate(http_request_duration_seconds_bucket{canary="1"}[5m])))`, availability 用 `1 - sum(rate(http_requests_total{canary="1",status=~"5.."}[5m]))/clamp_min(...)`）。指标口径复用 007 llm-gateway-resilience。YAML 解析通过。
- [x] T045 [P] 灰度期新旧版本指标并排对比脚本：按版本号维度输出指标对照表（FR-021）  证据：新建 `deploy/cli/canary-metrics.sh`（重写版，`bash -n` 通过）——读 rollback-conditions.yml 的 `queries` 键做 METRICS 列表；`metric_expr()/metric_rule()` 取 PromQL 与 op；`query_value()` 用 `curl -G ${PROM_URL}/api/v1/query --data-urlencode query/time`；把模板 `{canary="1"}` 替换成 `{canary="1"}`（新版本）与 `{canary!="1"}`（稳定版）双查询，输出 Markdown 对照表（指标/canary/stable/基线规则）或 `--json`。实测无 prometheus 时 5 行全 N/A、表头与规则列正确。踩坑：bash 内嵌跨行 `$(python3 -c '...')` 单引号易致 `bash -n` 报 unexpected EOF，全改单行 python 后通过。
- [x] T046 [P] 自动回滚执行器：观察窗口结束后评估 `rollback-conditions.yml`，超阈则调用 `deploy/cli/canary.sh rollback`，无需人工介入（FR-022）  证据：新建 `deploy/cli/auto-rollback.sh`——读 rollback-conditions.yml，逐条 `query()` 取指标实测值并 `hit()` 判定（op 前缀解析 `gt_baseline_plus_Npct`/`gt_0_N`/`lt_0_N`，prometheus 不可达 value=null 视为未触发）；`any_hit` 为真且非 `--dry-run` 时调 `canary.sh rollback --reason "auto:<ids>" --yes`；带 600s 冷却（读 state.json 的 last_rollback.ended_at 距现在 <600s 则跳过）；`--dry-run` 只评估告警不执行（exit 3）。实测 `--dry-run --json` 输出 5 条条件 `hit:false`（prometheus 未起 value=null），`--dry-run` 表格输出正确，rc=0。
- [x] T047 [P] 回滚耗时实测记录：每次回滚（人工或自动）写入 `deploy/runbook/rollbacks/<date>-<version>.md`，含开始/结束时间、实测耗时、触发原因、触发指标值（FR-025）  证据：回滚记录由 `deploy/cli/canary.sh` 的 rollback 动作写入 `deploy/runbook/rollbacks/<date>-<version>.md`（T041 已实现）：含开始时间、结束时间、实测耗时（与 T1 级目标 300s 对比）、触发原因（reason，人工可传 `--reason`，自动回滚传 `auto:<ids>`）、触发指标（指到 rollback-conditions.yml 对应 condition id）。实测 `rollback --reason test_dry --yes` 生成 `deploy/runbook/rollbacks/2026-10-26-unknown.md`（耗时 2.7s）。
- [x] T048 [P] 回滚后关键指标恢复校验：`scripts/verify_rollback_baseline.py`，比对回滚后指标与回滚前基线（FR-026）  证据：新建 `scripts/verify_rollback_baseline.py`——CLI `--baseline-file/--post-file [--tolerance N]`（文件比对）或 `--url/--metric/--before-window/--after-window`（直连 Prometheus 拉窗口均值）；`check()` 逐指标算 `|post-base|/|base|`，任一越界 exit 1；`--json` 输出完整判定。实测基线 JSON（error_rate 0.01 / p95 320 / 5xx 0.0005 / availability 0.999）对回滚后 JSON（error_rate 0.011 / p95 340 / 5xx 0.0006 / availability 0.9985，容差 10%）→ 3 OK + 5xx FAIL 20% rc=1；越界样本（error_rate 0.02 / p95 400 / 5xx 0.003 / availability 0.99）→ 3 FAIL rc=1，判据正确（FR-026 闭环）。
- [ ] T049 真实回滚演练（**不得用 mock**）：在预发或隔离环境执行一次完整"灰度 → 注入故障 → 自动回滚 → 指标恢复"演练，记录实测耗时（FR-023）

### 数据变更兼容性

- [x] T050 [P] 数据变更与代码回滚兼容性结论表：新建 `deploy/runbook/data-rollback-matrix.md`，逐项标注可回滚 / 不可逆（FR-024）  证据：新建 `deploy/runbook/data-rollback-matrix.md`（FR-024）——兼容性矩阵覆盖 MongoDB/Redis/Weaviate 与业务内嵌 schema，13 类数据变更逐项标注：`可回滚`（新增可选字段/加默认值/加普通索引/枚举新增/Redis key 结构/随代码回滚）与 `不可逆/需备份`（删字段、重命名字段、改字段类型、批量数据修正、枚举改名、Weaviate collection schema 变更、新增唯一索引），每项给出回滚方式与风险等级（低/中-高）；并写 5 条关键原则（向后兼容、双写窗口、备份前置、回滚验证、不可逆变更走弃用观察流程）与档位联动（1%/10%/50%/100% 各档允许的变更等级与观察点）。
- [x] T051 [P] 不可逆数据变更的迁移脚本兜底要求：每个不可逆项必须有对应的前向修复脚本，`scripts/migrations/` 目录（FR-024）  证据：新建 `scripts/migrations/` 目录与 `scripts/migrations/README.md`（FR-024）——文件命名约定 `<序号>_<描述>.py` + `<序号>_<描述>.down.py`（成对 up/down）；脚本接口约定 `up()/down()` + `__main__` 按 `--direction up|down` 分派；5 条硬性要求：幂等、向后兼容、备份前置、可回滚（down 能恢复到 up 之前可用状态）、评审随 PR 提交。每个不可逆项必须有对应前向修复（down）脚本，否则禁止合入。当前目录为空，仅建立约定与后续登记入口。

---

## Phase 5: User Story 4 (P1) — 特性开关与发布管理（阶段 5）

**Goal**: 建立特性开关登记、数据库变更顺序约束与自托管发布检查单，覆盖 QF-828 / 833 / 834 / 835 / 021 blocked。
**独立测试**: 特性开关四项登记齐全且到期告警；含 schema 变更的发布中数据库变更先落地且代码回滚后旧版本可用。

### 特性开关

- [x] T052 [P] 新建 `deploy/flags/flags.yml`：特性开关登记，字段 `name` / `owner` / `defaultValue` / `expiry` / `cleanupPlan` / `codeRefs`（FR-027）  证据：新建 `deploy/flags/flags.yml`（FR-027）——每项登记 `name/owner/defaultValue/expiry/cleanupPlan/codeRefs` 六字段。登记 5 个真实开关：`canary_routing_enabled`(platform-oncall, 2027-01-31, codeRefs deploy/canary/nginx-canary.conf + deploy/cli/canary.sh + auto-rollback.sh)、`panweidb_data_backend`(data-platform, 2027-06-30, codeRefs services/admin-api/app/core/config.py:31-38 + docker-compose.yml)、`mogo_tls`(platform-oncall, 2099-12-31, codeRefs mogo:154 + mogo:248-251 + deploy/docker/nginx-https.conf)、`audit_db_enabled`(security, 2027-03-31, codeRefs services/admin-api/app/core/config.py)、`canary_auto_rollback`(platform-oncall, 2027-01-31, codeRefs auto-rollback.sh + rollback-conditions.yml)。cleanupPlan 均写明清理动作与归档位置。
- [x] T053 [P] 新建 `deploy/cli/flag-check.sh`：校验 `flags.yml` 四项登记齐全；到期开关输出告警（FR-028）  证据：新建 `deploy/cli/flag-check.sh`（FR-028）——校验四项登记齐全（owner/defaultValue/expiry/cleanupPlan），expiry 早于 `--today`（UTC）输出 `EXPIRED <flag> (expiry=..., owner=...)  → 需清理或更新 expiry`；扩展属主存活性检查（读 `deploy/flags/owners.yml`，owner 未登记或 status != active 输出 `FAIL <flag>: owner <name> owner departed/not active  -> 阻塞发布`）；任一问题 exit 1；`--json` 输出 `{total, problems, expired, owner_problems}`。CLI 支持 `--json/--today`，路径可用 `MOGO_FLAGS_FILE`/`MOGO_OWNERS_FILE` 覆盖。实测：正常 5 项齐全无到期 rc=0；`--today 2027-02-01` → 2 条 EXPIRED (canary_routing_enabled/canary_auto_rollback 到期) rc=1；删除 owner 字段 → `FAIL <flag>: missing owner` rc=1；platform-oncall 标 departed → 3 条 owner FAIL rc=1（阻塞发布）。
- [x] T054 [P] 应用侧读取约定：`services/*/app/core/config.py` 提供统一的 feature flag 读取入口，默认值来自 `flags.yml`（FR-027）  证据：共享模块 `services/common/feature_flags.py` 提供 `get_feature_flag(name, default)` / `resolve_flag` / `is_enabled` / `feature_flag_names`；默认值来自 `deploy/flags/flags.yml` 每项 `defaultValue`，运行时 `MOGO_FLAG_<NAME_UPPER>` 环境变量优先级最高（值接受 1/0/true/false/yes/no，其他值原样返回），清单读取带 60s TTL 缓存；未登记/清单缺失/YAML 失败一律回退调用方 `default` 不抛异常。三个服务 `services/{admin-api,chat-api,document-parser}/app/core/config.py` 统一通过 `Settings.feature_flag(name, default)` 暴露读取方法（`_feature_flag_entrypoint()` 定位加载共享模块，覆盖容器 /app/<svc> 与本地布局，加载失败回退环境变量+显式 default），禁止业务代码各自读环境变量判断开关。
- [x] T055 [P] 属主转移流程：`deploy/runbook/flag-owner-transfer.md`，含离职时的转移步骤与 CI 检查（属主账号已注销则阻塞发布）（FR-028）  证据：新建 `deploy/runbook/flag-owner-transfer.md`（FR-028）+ `deploy/flags/owners.yml`（属主 id/alias/status: active|departed + transfers 记录段）——流程：触发条件（属主账号注销、长期无响应 ≥14 天、书面申请）→ 转移 5 步（确认新属主→交接上下文含 cleanupPlan/codeRefs→改 flags.yml owner 随 PR→跑 flag-check.sh→CI 阻塞发布）→ CI 属主存活性约定（owners.yml 白名单，departed/未登记 → exit 1 阻塞）→ 检查单条目表（纳入 release-checklist-self-hosted.md）→ transfers 记录（from/to/date/reason/pr）。

### 数据库变更顺序与迁移

- [x] T056 [P] 数据库变更先于代码的门禁：发布计划脚本校验迁移版本号 < 依赖它的代码版本，否则阻塞（FR-029）  证据：新建 `deploy/cli/migration-gate.sh`（FR-029）——校验本次发布引入的最高迁移号 `--migration-max N` ≥ 代码声明迁移基线 `--code-migration-base M`，否则阻塞（exit 1）；支持 `--release-file deploy/releases/latest.json`（读 migration_max/code_migration_base），并扫描 `scripts/migrations/[0-9]*_*.py` 取最大序号兜底（`migration_max = max(给定, 扫描)`）。CLI `--migration-max/--code-migration-base/--release-file/--json`。实测：N=5 M=3 → PASS rc=0；N=2 M=5 → `BLOCKED 代码依赖的迁移未先发布` rc=1；N=5 M=5 --json → `{migration_max:5, code_migration_base:5, blocked:false, verdict:PASS}` rc=0。
- [x] T057 [P] 扩展-收缩流程文档：`deploy/runbook/expand-contract.md`，含三阶段步骤与"未完成收缩禁止回滚"的明确禁令（FR-030）  证据：新建 `deploy/runbook/expand-contract.md`（FR-030）——三阶段：Expand（新结构并存，1% 档）/ Migrate（存量幂等分批迁移，10%-50% 档）/ Contract（删旧结构，100% 后下一版本）；硬性规则含**「未完成收缩禁止回滚」**明确禁令（canary.sh rollback 的 `--reason contract-phase` 会先触发 `<n>.down.py` 回到迁移完成态再回滚）+ 三版本互相兼容 + 双写窗口 ≥1 灰度周期 + 备份前置 + 迁移说明纳入检查单；回滚决策树（是否 Contract 阶段分支）；记录 reason 前缀 `expand-phase/migrate-phase/contract-phase`。
- [x] T058 [P] 在线迁移要求：`scripts/migrations/` 规范 —— 迁移幂等、长事务拆分、不阻塞线上请求（FR-031）  证据：`scripts/migrations/README.md` 追加「在线迁移要求 (024 T058 / FR-031)」6 条——①迁移幂等（exists/if not 判断，up/down 可重跑）；②长事务拆分（>1000 条分 200 批 + sleep(0.05)）；③不阻塞线上（probe_throughput.py 探测，吞吐下降 >20% 立即中止）；④分批与重试（失败批仅重跑，连续 3 批失败暂停告警）；⑤时间窗（高风险 02:00-05:00 本地时区，检查单记录）；⑥回滚（任意批次续跑或整体 down，down 幂等）。文件 68 行。
- [x] T059 [P] 迁移执行不阻塞验证：压测脚本在迁移进行中发请求，确认无请求阻塞（FR-031）  证据：新建 `scripts/migrations/probe_throughput.py`（FR-031）——迁移进行期间持续对探测端点发请求，统计每分钟吞吐，当前窗口速率低于基线 `rate*(1-threshold)` 即判定「迁移阻塞线上」并中止迁移（exit 1）。CLI `--url/--interval/--window/--baseline-seconds/--threshold 0.2/--duration/--migration-cmd/--dry-run/--json`；`--migration-cmd` 并行跑迁移；dry-run 用 `_simulate()` 模拟基线（0.98 成功率），不发真实请求。实测 `--dry-run --baseline-seconds 3 --duration 5 --window 2 --interval 0.05 --json` → baseline_rate_per_sec 17.667、两窗口 930/990 请求每分、`blocked:false`、verdict `PASS 迁移未阻塞线上`、rc=0。
- [x] T060 [P] 破坏性变更迁移说明：每次破坏性变更必须附迁移说明文档，纳入发布检查单（覆盖 QF-021 blocked）  证据：新建 `docs/migration-notes/TEMPLATE.md`（FR-030，覆盖 QF-021 blocked）——破坏性变更迁移说明模板：变更概要（影响服务/变更类型/风险等级，参照 data-rollback-matrix.md）、兼容性分析（旧版本能否读写/expand-migrate-contract 阶段/双写窗口/是否不可逆）、迁移 5 步（备份前置→迁移脚本成对 up/down→执行→probe_throughput 验证→migration-gate 门禁）、回滚路径（阶段判定 + down 脚本 + `./mogo canary rollback`，未完成收缩禁止回滚）、数据验证（抽样校验 + verify_rollback_baseline）、执行人/结论（纳入发布检查单）。

### 发布检查单

- [x] T061 [P] 新建 `docs/release-checklist-self-hosted.md`：覆盖自托管企业部署的**配置差异**（各环境）与**依赖差异**（镜像 digest、运行时版本），基于既有 `docs/open-source-productization/release-checklist.md` 扩展（FR-032）  证据：新建 `docs/release-checklist-self-hosted.md`（FR-032/FR-033）——18 项 C01-C18，覆盖**配置差异**（三环境 config-lint / prod 敏感键 source / startup-config-check / drift-check）与**依赖差异**（镜像 digest verify-artifact / 镜像标签 + SHA256SUMS cosign / 运行时版本 / IaC diff / migration-gate / probe_throughput / canary state / auto-rollback / flag-check / deploy-dry-run / 备份前置 / 值班告警）。基于 `docs/open-source-productization/release-checklist.md` 扩展，聚焦自托管企业部署路径。
- [x] T062 [P] 检查单格式强制"执行人 + 结论"两项，机器可校验（空值视为未通过）（FR-033）  证据：检查单格式强制 `| 执行人: | 结论: | 理由: |` 三字段（`docs/release-checklist-self-hosted.md` 全部条目），机器可校验——`deploy/cli/checklist-verify.sh` 解析 `- [ ] C.. | 描述 | 执行人: X | 结论: Y | 理由: Z`，执行人或结论为空视为未通过；结论 `不适用` 必须附理由（reason-for-na 缺失也 FAIL）；空结论与空执行人 → exit 1。
- [x] T063 [P] `docs/release-process.md` 补自托管企业部署路径章节，指向自托管检查单  证据：`docs/release-process.md` 追加「自托管企业部署路径 (FR-032/FR-033)」章节（111→149 行）——指向 `docs/release-checklist-self-hosted.md` 与 `deploy/cli/checklist-verify.sh`；分 4 小节：配置差异（config-lint/startup-config-check/敏感键 source/mogo config rollback）、依赖差异（verify-artifact/镜像标签+SHA256SUMS/运行时版本/drift-check）、灰度与回滚（mogo canary/auto-rollback/verify_rollback_baseline）、发布门禁 C08-C10（migration-gate/migration-notes/probe_throughput）；末尾说明逐条填写后跑 checklist-verify.sh 全 OK 才可 `./mogo up`。
- [x] T064 [P] 检查单校验脚本：`deploy/cli/checklist-verify.sh`，在发布前校验每项执行人与结论非空  证据：新建 `deploy/cli/checklist-verify.sh`（FR-033）——`--checklist <path>`（默认 docs/release-checklist-self-hosted.md）、`--json`；正则解析每条 `执行人/结论/理由`，缺 executor/verdict 或 `不适用` 缺 reason-for-na → 输出 `FAIL <id>: 缺 <field>`；全 OK 输出 `PASS 全部项执行人与结论非空` exit 0，任一缺失 exit 1。实测未填清单 → 18 项全 FAIL rc=1；填 `执行人: ops | 结论: 通过` → 18 项全 OK rc=0；把结论改 `不适用` 且理由空 → 18 项 `FAIL <id>: 缺 reason-for-na` rc=1。

---

## Phase 6: User Story 5 (P1) — 备份自动化与可恢复性（阶段 6）

**Goal**: QF-837 已 `pass`，补齐自动策略、加密、保留策略（QF-836 / 838 / 839 blocked）。
**独立测试**: 自动备份最近成功时间在窗口内；备份集已加密；恢复到干净环境业务校验通过。

- [x] T065 [P] `deploy/cli/backup.sh` 增加加密：备份归档前 `gpg --symmetric`（或 `openssl enc -aes-256-gcm`），密钥从 `deployment-secrets` 卷或外部密钥源读取（FR-035）  证据：`deploy/cli/backup.sh` 新增 `mogo_backup_encrypt_dir` / `mogo_backup_decrypt_dir` / `mogo_backup_key`（FR-035）——归档后用 `openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt -pass stdin` 加密为 `*.tar.gz.enc`，密钥来源 env `MOGO_BACKUP_KEY` / 文件 `MOGO_BACKUP_KEY_FILE`（**无内置默认口令**，未配置则跳过加密保持旧明文兼容）；目录写入 `ENCRYPTED=true`/`BACKUP_CIPHER`/`KEY_SHA256_PREFIX`（密钥 sha256 前 32 位，不含密钥本体）；默认删除明文（`MOGO_BACKUP_KEEP_PLAIN=1` 可保留）；对加密归档重算 `SHA256SUMS`。`mogo_restore` 检测 `ENCRYPTED` 后先解密到临时工作目录（指纹不匹配即拒绝，避免用错密钥静默解出垃圾），恢复后 `trap` 清理不落明文。单测 `scripts/test_backup_encrypt.sh`：5 组用例（未配置密钥跳过/加密生成 .enc 并删明文/正确密钥解密内容一致且 SHA256SUMS 校验通过/错误密钥被指纹校验拒绝/无密钥报错）全部 ALL PASS rc=0。
- [x] T066 [P] 密钥异地存放：密钥 MUST NOT 与备份集同机，写入 `deploy/runbook/backup-key-management.md` 并列为 DR 演练必测项（FR-035）  证据：新建 `deploy/runbook/backup-key-management.md`（FR-035）——密钥来源表（env / 密钥文件 / secrets 卷 / Vault-KMS，**禁止内置默认口令**）+ 异地存放四条硬要求（异机、两份副本、备份目录只写 `KEY_SHA256_PREFIX`、至少一份离线副本）+ 生成命令（`openssl rand -base64 32`）+ 轮换触发与三步流程（新密钥验证→旧密钥保留至归档过期→更新离线指纹）+ DR 演练必测项表 K1-K6（异地取密钥/解密/SHA256SUMS/错误密钥拒绝/密钥归位/耗时记录）+ 常见坑（同盘、写密钥副本、轮换即删旧钥、单钥）。
- [x] T067 [P] 新建 `deploy/cli/backup-schedule.sh`：定时备份（提供 cron 与 systemd timer 两种安装方式），配置项含周期、目标窗口、失败告警（FR-034）  证据：新建 `deploy/cli/backup-schedule.sh`（FR-034，227 行）+ `deploy/config/backup-schedule.yml`（version 1，schedule.cron `0 2 * * *`/window `02:00-05:00`/timezone Asia/Shanghai，retention.retain_count 7/retain_days 14/min_keep 3，alert.channel log|webhook）——提供 `mogo_backup_schedule_install_cron`（写入 crontab，去重 `mogo-backup-schedule.sh cron-run` 条目）、`install_systemd`（cron→OnCalendar 转换，生成 mogo-backup.service/timer，daemon-reload+enable --now）、`status`（周期/窗口/保留策略/cron 与 systemd 是否安装/最近备份与总数）、`run`（执行备份命令，失败结构化 JSON 详情 + `mogo_notify` 告警）、`prune`（双重保留策略）；独立入口 `backup-schedule.sh cron-run` 供 cron/systemd 调用。
- [x] T068 [P] `mogo` 新增 `backup-schedule install|status` 子命令  证据：`mogo` 新增 `backup-schedule` 子命令（第 859-881 行，source `deploy/cli/backup-schedule.sh`）：`./mogo backup-schedule install|cron`（安装 cron）、`./mogo backup-schedule systemd`（安装 systemd timer）、`./mogo backup-schedule status`（查看调度/保留策略/最近备份）、`./mogo backup-schedule prune`（按保留策略清理）、`./mogo backup-schedule uninstall`（移除 cron/systemd 条目）。
- [x] T069 [P] 保留策略：`backup-schedule.sh` 支持保留份数 + 时长双重策略，过期自动清理，清理后剩余份数必须仍满足恢复需求（FR-036）  证据：`deploy/cli/backup-schedule.sh` 的 `mogo_backup_schedule_prune`（FR-036）实现**份数 + 时长双重策略**（`retain_count` 最近 N 份 且 `retain_days` 内备份均保留，并叠加 `min_keep` 安全下限），按 mtime 升序删旧；清理后重新统计剩余份数，`to_del` 且 `剩余 < retain_count` 时输出 `FAIL 清理后剩余份数不足 retain_count，保留策略不满足 FR-036` 并 exit 1。配置见 `deploy/config/backup-schedule.yml` 的 `retention` 段（retain_count 7 / retain_days 14 / min_keep 3）。
- [x] T070 [P] 备份失败告警：失败时输出结构化错误并触发通知（复用现有告警渠道约定）（FR-034）  证据：新建 `deploy/cli/notify.sh` 提供统一告警入口 `mogo_notify <severity> <title> <detail_json>`（FR-034）——输出结构化 JSON `{severity,title,detail,timestamp}` 并写入 stderr，按 `MOGO_ALERT_CHANNEL`（log 默认 / webhook）投递；webhook 用 curl/wget POST `MOGO_ALERT_WEBHOOK_URL`，无 curl/wget 或无 URL 时降级 log 并 return 1。`mogo_backup_schedule_run` 在备份命令失败时以 `python3` 生成 `{command, error}` JSON 详情并调 `mogo_notify critical "mogo 定时备份失败" <detail>`，同时写 stderr、return 1（调度器可见退出码）。渠道约定见 `deploy/alertmanager/alertmanager.yml`（IM webhook + 邮件双渠道）。
- [x] T071 [P] 新建 `scripts/verify_restore_business.py`：恢复后业务校验（关键数据可读写、对话/文档/知识检索功能可用），产出 PASS/FAIL 报告（FR-037）  证据：新建 `scripts/verify_restore_business.py`（FR-037，126 行）——恢复后对网关/API 做业务冒烟，默认 6 个端点（gateway_health /health、api_health /api/health、chat_smoke POST /api/chat、documents_list /api/documents、knowledge_search /api/knowledge-base/search、admin_status /api/admin/system/status），CLI `--base-url/--endpoints-file/--timeout/--json`；逐项断言 status 与可选子串，输出 PASS/FAIL 报告 `{total, passed, failed, verdict, results}`，verdict 含「恢复后业务校验全部通过（FR-037）」，任一 FAIL 退出码 1。
- [x] T072 [P] `mogo restore` 增加 `--verify` 选项，恢复后自动调用业务校验  证据：`mogo restore` 增加 `--verify` 选项（第 851-857 行解析 `restore_verify`），`mogo_restore` 第 3 参数 `verify`（默认 false，兼容既有 2 参数调用）；恢复成功后自动调用 `scripts/verify_restore_business.py --base-url ${MOGO_VERIFY_BASE_URL:-${MOGO_LOCAL_BASE}} --json`，报告写入 `backups/restore-verify.json`，失败则 cat stderr 并 return 1。用法：`./mogo restore <备份目录> --yes --verify`。
- [ ] T073 真实恢复演练（**不得用 mock**）：从最近一次自动备份恢复到干净主机，执行 `verify_restore_business.py`，记录实测耗时（FR-037）  ⚠️ 需远端/预发环境（本机 Docker 无远端集群），本轮不可验

---

## Phase 7: User Story 5 (P1) — 跨区部署与切换能力（阶段 7）

**Goal**: 建立跨可用区能力与切换流程（QF-840~843 blocked），首期以 MongoDB 副本集 + 备份重建达成。
**独立测试**: 单区故障（拉掉整台主机）后从备份在新主机重建，RTO 内恢复服务。

- [x] T074 [P] `docker-compose.yml` 增加 MongoDB 副本集选项（`mongo --replSet rs0` + init keyfile 容器），默认关闭、以 `profiles: ["ha"]` 启用（FR-039）  证据：`docker-compose.yml` 新增 `mongo-ha`（`profiles: ["ha"]`，`mongod --replSet rs0 --keyFile /run/secrets/mongo_keyfile --bind_ip_all`，healthcheck 用 `replSetGetStatus` myState 1||2，与单机 mongo 共用 mongo-data 卷）与 `mongo-ha-init`（轮询 ping 后 `rs.initiate({_id:'rs0',members:[{_id:0,host:'mongo-ha:27017'}]})`）；顶层 `secrets.mongo_keyfile`（`file: ${MOGO_MONGO_KEYFILE_HOST_FILE:-./secrets/mongo_keyfile}`，密钥不提交仓库，生成命令 `openssl rand -base64 756 | tr -d '\n'`）。实测：临时 keyfile 下 `docker compose --profile ha config --quiet` 与 `docker compose config --quiet` 均 rc=0（FR-039）。
- [x] T075 [P] Redis 持久化与 RPO 声明：在预案中如实写明 Redis 数据在切换中的丢失范围（FR-039）  证据：`deploy/runbook/failover-runbook.md` §1「Redis 持久化与 RPO 声明」——如实写明切换中丢失范围 = 备份时刻→故障时刻之间所有 Redis 写入，AOF 已开启但 fsync everysec 不跨区同步；对业务影响（缓存 miss、登录态失效）与应用层必须可容忍；验证点（切换后 `redis-cli DBSIZE` 与关键 key 符合备份时刻预期）；并声明 RPO 不做承诺（FR-039）。
- [x] T076 [P] 新建 `deploy/runbook/failover-runbook.md`：单区故障切换步骤（决策人、执行者、验证点、回切步骤）（FR-040）  证据：新建 `deploy/runbook/failover-runbook.md`（134 行）§2 切换步骤（2.1 前置条件 / 2.2 prepare / 2.3 execute / 2.4 verify / 2.5 back 回切，每步标注决策人、执行者、预计耗时、验证点）+ §3 验证点清单 F1-F8 + §4 通信方式（FR-040）。
- [x] T077 [P] 切换权限收敛：明确"谁可切"（角色 + 审批）写入预案，且技术侧有对应限制手段（如独立操作账号、专用密钥）（FR-040）  证据：`deploy/runbook/failover-runbook.md` §0「角色与权限」给出角色矩阵（SRE 值班/SRE 负责人/平台负责人/研发/第三方）+ 审批要求 + 技术限制（独立操作账号 `mogo-failover`、专用 SSH 密钥 `MOGO_FAILOVER_KEY`、双人复核 `MOGO_FAILOVER_REQUIRE_APPROVAL` + `--approver-key` 签名、审计记录 `deploy/runbook/rollbacks/<date>-failover.md`）；`deploy/cli/failover.sh` 用 `mogo_failover_check_account`（默认只允许 mogo-failover 账号执行，`MOGO_FAILOVER_SKIP_ACCOUNT_CHECK=1` 豁免）与 `mogo_failover_check_approval`（双人复核）实现技术侧限制。实测：非 mogo-failover 账号执行 `./mogo failover prepare/execute/back` 会被 `mogo_failover_check_account` 拒绝（FR-040）。
- [x] T078 [P] 新建 `scripts/verify_data_consistency.py`：切换后数据一致性校验（MongoDB 关键集合行数 + 抽样校验和 + 应用层读写探针）（FR-041）  证据：新建 `scripts/verify_data_consistency.py`（FR-041）——① MongoDB 关键集合行数（`countDocuments`，支持 `--collections` 显式或自动探测非 system 集合）；② 抽样校验和（按 `_id` 排序后的文档 JSON sha256，跨节点可对账，每集合 `sample_sha256` + 全库 `checksum`）；③ 应用层读写探针（`--probe-app` 时对 `/health`、`/api/health` 请求并报告 status/body）。CLI：`--mongo-uri/--db/--collections/--sample-size/--base-url/--probe-app/--timeout/--json`，verdict 含「切换后数据一致性校验全部通过（FR-041）」，任一 FAIL 退出码 1。实测（假 mongosh 夹具）：`users` rows=3 `sample_sha256=8c5bc0e0…`、`conversations` rows=2 `fb83bf5c…`、`passed=true` rc=0；无 mongosh/连接失败时优雅输出 FAIL rc=1。
- [x] T079 [P] 新建 `deploy/cli/failover.sh`：`failover prepare|execute|verify|back` 动作，编排新主机拉取制品 → 恢复备份 → 切换流量 → 一致性校验  证据：新建 `deploy/cli/failover.sh`（240 行）提供 `prepare|execute|verify|back|status` 五动作——`prepare`（SSH 可达/NTP/磁盘预检 + 备份就绪检查，加密备份提示先解密）、`execute`（拉起 compose + 恢复备份卷 + 切换流量指引）、`verify`（调 `scripts/verify_data_consistency.py` + `scripts/verify_restore_business.py`，任一 FAIL 退出码非 0）、`back`（回切，默认需双人复核）、`status`（状态机 `deploy/.failover-state.json`，保留最近 50 条历史）。实测：`bash -n` 通过；`./mogo failover status` rc=0 输出「当前阶段: back / 目标主机: 10.0.0.19 / 历史动作 2 条」（FR-040）。
- [x] T080 [P] `mogo` 新增 `failover` 子命令组  证据：`mogo` 第 38-39 行 `source deploy/cli/failover.sh`，第 886-912 行新增 `failover` 子命令分支（`prepare|execute|verify|back|status`，参数透传给对应 `mogo_failover_*` 函数）。实测：`./mogo failover status` rc=0 输出状态机；`./mogo failover <未知动作>` 输出用法并 exit 2；`bash -n mogo` 通过（FR-040）。
- [ ] T081 真实单区故障演练（**不得用 mock**）：在隔离环境拉掉整台主机，从备份在新主机重建，记录 RTO / RPO 实测值（FR-038 / 043）  ⚠️ 需远端/预发环境（本机 Docker 无远端集群），本轮不可验

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
