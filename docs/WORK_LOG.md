# Work Log

## 2026-09-24 修复 chat-api 启动失败 + 恢复单实例默认拓扑（真实容器启动暴露）

接上一轮改动，在**重建并重启真实容器**时暴露两个单测未覆盖的问题：

1. **`application.py` 缺 import**：调用 `configured_runtime_hosts` 但未导入，容器启动即
   `NameError: name 'configured_runtime_hosts' is not defined` → `Application startup failed`。
   该路径位于 `start()` 生命周期内，此前无任何测试覆盖。
   - 修复：补 `from app.dsh_runtime.transport import HttpKernelHostTransport, configured_runtime_hosts`。
   - **补测试**：新增 wiring 回归用例（断言 composition root 用到的名字在其模块命名空间可解析 +
     用 `configured_runtime_hosts` 的输出构造 transport），测试数 27 → **29**。

2. **compose 默认拓扑被改坏**：上一轮把 chat-api 的 `DSH_RUNTIME_HOST_URL` 默认值指向
   `dsh-runtime-host-lb` 与三副本，但默认部署并不会启动这些服务 → `/ready` 持续
   503（DSH host 探测失败），**chat-api 无法就绪**。
   - 修复：默认回到单实例 `dsh-runtime-host`；三副本与 LB 移入
     `profiles: ["runtime-pool"]`，用 `docker compose --profile runtime-pool up -d`
     显式启用，并通过 `DSH_RUNTIME_HOST_URL` / `DSH_RUNTIME_HOSTS_URL` 覆盖指向 LB。
   - chat-api 的两个 host 变量改为可被环境覆盖（`${DSH_RUNTIME_HOST_URL:-...}`），
     保留单实例默认值。

**验证**：两类配置（默认 / `--profile runtime-pool`）均 `docker compose config` 通过；
chat-api 恢复 healthy 且 `/ready` 返回 `{"status":"ready","dsh_host":"healthy"}`；
管理后台 dashboard / analytics / tools / skills 接口均 200；路由修复在容器内生效
（`runtime_routing_key` 返回 isolation key 并同时携带三个 header）。

**其他连带处理**：
- `user-web` 与 `admin-web` 均已用新镜像（裸名）重启并就绪，界面改动已生效。
- 期间修正了我误用 `apps/user-web/Dockerfile`（开发服务器）的问题，生产镜像为 `Dockerfile.prod`。

## 2026-09-24 补齐全部 7 个镜像的新命名本地构建

用户指出「movo 打头的 7 个镜像没有改名」。核查确认：上一轮只让**构建流程**产出新名，
并重建了 4 个（admin-web / chat-api / gateway / user-web），**其余 3 个从未用新名构建**：
admin-api、document-parser、dsh-runtime-host。

- **补齐构建**：
  - `admin-api:latest` ✅（`./movo build admin-api`）
  - `dsh-runtime-host:latest` ✅（`./movo build dsh-runtime-host`）
  - `document-parser:latest` —— 直接构建失败：构建期需从 HuggingFace 下载 Docling 模型，
    当前网络不可达（`LocalEntryNotFoundError: ConnectError: [Errno 101] Network is unreachable`）。
    采用既定方案：给已完整构建的 `movo-document-parser:latest` 打新标签
    （`docker tag movo-document-parser:latest document-parser:latest`，同一镜像 ID `b1e3743e237f`），
    内容完全一致、无需重新下载模型。
  - 注：`document-parser` 对应的 compose **服务名是 `document-api`**（`./movo build document-parser`
    会报 `no such service`），已按正确服务名操作。
- **结果**：**7/7 镜像均有裸名版本**。`./movo build` 的自动清理在本轮生效
  （构建 dsh-runtime-host 后输出 "Pruned untagged build leftovers, reclaimed about 851 MB"）。
- **运行的服务全部切换到裸名镜像**（逐个切换 + 立即验证，避免整批中断）：
  admin-api、admin-web、chat-api、document-api、document-worker、dsh-runtime-host、gateway、user-web。
- **验证**：`docker compose ps` 显示 7 个 MOVO 服务镜像名均无 `movo-` 前缀；全部 healthy；
  `/`、`/admin/` 返回 200；dashboard / analytics / tools 接口 200；
  chat-api `/ready` → `{"status":"ready","dsh_host":"healthy"}`。
- **发布渠道**：用户明确**不走 GHCR**、不推送镜像。既有 `container-release.yml` /
  `runtime-guard.yml` 中 `MOVO_IMAGE_PREFIX` → `MOVO_IMAGE_REGISTRY` 的改名保留
  （该变量已从代码移除，不改会导致 CI 变量未定义），本地校验
  （`check_compose_image_modes.sh`、`test_plan_container_release.py`）均通过。

## 2026-09-24 镜像命名去前缀（movo-* → 裸服务名）+ 移除「社区版」界面文案

### 一、7 个镜像名称调整（用户要求）

- **目标**：本地 `movo-admin-web:latest` → `admin-web:latest`；远端 `ghcr.io/himovo/movo-admin-web` → `ghcr.io/himovo/admin-web`。用户确认本地与远端都去前缀。
- **核心难点**：原镜像名由 `${MOVO_IMAGE_PREFIX}-{service}` 拼接，直接把前缀置空会得到 `-admin-web:latest`（多一个连字符）；而 `${VAR-default}` 在空值时会产出 `/admin-web:latest`（多一个斜杠）。**空前缀方案不可行**。
- **方案**：改为**每服务一个完整镜像引用变量**，默认值即最终镜像名：
  ```yaml
  image: ${MOVO_ADMIN_WEB_IMAGE:-ghcr.io/himovo/admin-web:${MOVO_VERSION:-latest}}
  ```
  本地构建时由 CLI 把这些变量覆盖为裸名（`admin-web:latest`），预构建路径保持带 registry。
- **改动文件**：
  - `docker-compose.yml`：7 处镜像定义（`MOVO_DSH_RUNTIME_HOST_IMAGE` / `MOVO_CHAT_API_IMAGE` / `MOVO_ADMIN_API_IMAGE` / `MOVO_USER_WEB_IMAGE` / `MOVO_ADMIN_WEB_IMAGE` / `MOVO_GATEWAY_IMAGE` + 既有 `MOVO_DOCUMENT_API_IMAGE`/`MOVO_DOCUMENT_WORKER_IMAGE`）
  - `deploy/cli/images.sh`：新增 `MOVO_IMAGE_SERVICES` 映射与 `movo_export_service_images()`，按 `MOVO_EXPORTED_IMAGE_PREFIX`（预构建=`ghcr.io/himovo/`，源码构建=空）导出全部镜像引用；`MOVO_DEFAULT_IMAGE_REGISTRY` 取代 `MOVO_DEFAULT_IMAGE_PREFIX`
  - `.github/workflows/container-release.yml`：镜像名由 `ghcr.io/${repository}-${suffix}` 改为 `ghcr.io/${owner}/${suffix}`（**仓库名不再进入镜像名**，避免改名后镜像失联）
  - `.github/workflows/runtime-guard.yml`、`scripts/check_compose_image_modes.sh`、`.env.example`、`README.md`、`README.zh-CN.md`、`deploy/cli/i18n.sh`、`services/document-parser/build_document_processing_bigpack.sh`（base 镜像名去前缀）
- **校验脚本加固**：`check_compose_image_modes.sh` 改为断言新命名，并**新增一条"不得再出现 movo- 前缀"的硬校验**；同时修掉它自身对运行中容器的环境依赖（`compose config --images` 会报出运行容器的镜像名，导致结果依赖本机状态）。
- **实测验证**：
  - 默认路径解析为 `ghcr.io/himovo/{dsh-runtime-host,chat-api,admin-api,document-parser,user-web,admin-web,gateway}`（7/7）
  - 源码构建路径解析为裸名 `admin-web:latest` 等
  - **真实构建**：`docker build` 输出 `Successfully tagged admin-web:latest`、`user-web:latest`、`admin-web:latest`（不再是 `movo-*`）
  - `bash scripts/check_compose_image_modes.sh` → `Compose image modes are valid.`

### 二、移除界面「社区版」文案（用户截图指出两处）

- **位置**：user-web 的 `accountTierLabel` computed 被 3 处复用（个人资料卡副标题、底部账户切换器、弹层手机号旁），社区版分支返回 `t('ui.community_edition')` = "社区版"。用户截图圈出其中两处。
- **修复**：`apps/user-web/src/App.vue` 的 community 分支改为返回空串；同时给两处模板加 `v-if="accountTierLabel"` 守卫（避免渲染空 div），弹层的分隔点改为 `maskedPhone() && accountTierLabel` 双条件。
- **保留**：真实版本身份（企业管理员/成员、Plus、专业团队版、企业定制版、免费版）不受影响。
- **admin-web 同步**（用户确认）：`DashboardPage.vue` 的 `tierLabel` community 分支同样返回空串，`n-tag` 加 `v-if="tierLabel"`。
- **实测验证**：
  - user-web 编译产物对比：旧镜像 `edition==="community"||... return A("ui.community_edition")` → 新镜像 **`return ""`**
  - admin-web 编译产物对比：旧镜像 DashboardPage 有 `if(Z.value)return s("社区版")` → 新镜像该返回已消失
  - 容器内全量扫描：新 user-web 产物中「社区版」仅剩 **i18n 字典定义**（`ui.community_edition`，已无任何代码引用），不渲染到界面
  - `vue-tsc --noEmit` 两份均通过（admin-web 在 node:20-slim 容器内验证，本地 esbuild 二进制平台不匹配）

### 三、附带处理的环境问题（重要）

- **磁盘告急导致构建失败**：排查中发现 chat-api 重建以 `exit code 137`（OOM/磁盘满被杀）失败，根因是宿主机可用空间仅剩 **3.2 GiB**。清理 dangling 镜像回收 **4.67 GB**、清理 e2e 验证环境（3 副本 + LB + 独立卷）后恢复到 **20 GiB**。构建随即恢复正常。
- **user-web 502 的连带原因**：磁盘紧张期间重建 user-web 容器，nginx 启动脚本 `10-listen-on-ipv6-by-default.sh` 在计算 `default.conf` checksum 时 IO 阻塞，容器长时间停在 `health: starting`；磁盘恢复后启动约需 1 分钟即转为 `healthy`。
- **误用 Dockerfile 的更正**：首次重建 user-web 时误用 `apps/user-web/Dockerfile`（该文件是**开发服务器** `npm run dev`），导致容器内无 nginx/无静态产物。生产镜像是 `Dockerfile.prod`（`docker-compose.build.yml` 指定）。已用正确文件重建并验证。
- **镜像标签与 dangling**：排查用户看到的"只有 ID 没有名字"的镜像，确认是**多阶段构建的中间层**与**反复重建留下的悬空镜像**（`<none>`），并非命名错误——目标镜像 `user-web:latest`、`admin-web:latest` 均有正确标签。
- `scripts/check_open_source_hygiene.py`：清理了 `docs/pending-review/README.md` 中我自己上一轮写入的密钥样本字面量（改为脱敏描述），该文件不再触发告警；剩余 3 处为既有测试夹具（已登记、非本轮引入）。
- chat-api 全量测试 **1877 passed / 8 failed**（8 项为预存 e2e 环境依赖，无回归）。

## 2026-09-24 复查遗留项：真实容器端到端验证 + 修复多实例路由根本缺陷 + 两项口径拍板

对上一轮主动标注的三个遗留项做复查，其中**第一项复查出一个真实缺陷并已修复**。

### 一、多实例端到端验证（原标注"未做"）—— 发现并修复真实缺陷

- **搭起真实验证环境**：`MOVO_VOLUME_PREFIX=movo-e2e docker compose -p movo-e2e up -d dsh-runtime-host-{1,2,3} dsh-runtime-host-lb`（独立 project + 独立卷前缀，不影响运行中的实例）。三个**真实 Node DSH runtime 副本**（kernel `dsh 0.1.6-alpha.1`）全部 healthy。
- **验证手段**：`backend` 网络是 `internal: true`，LB 无对外端口，故从同网络内的副本容器用 Node `fetch` 发起请求，并以 **LB 访问日志的 `key=` / `upstream=` 字段**为证据。
- **第一轮验证（通过）**：`sess-AAA` 连续 6 次全部命中同一副本；12 个不同 session 散落到 3 个副本（6/3/3）；两轮请求映射完全一致（哈希稳定）。
- **❗发现真实缺陷（端到端才暴露）**：
  - `POST /v1/runtimes`（创建 runtime）无 session 语义 → 用随机 `$request_id` 兜底 → 落在副本 A
  - `POST /v1/runtimes/{id}/sessions`（建会话）按新 session id 哈希 → 落在副本 B → **`runtime not found`**
  - 实测日志：create 在 `.2`、create_session 在 `.4`；`GET /v1/runtimes` 落到 `.3` 返回 0 个（`.2` 上明明有 1 个）
  - **根因**：sticky key 只覆盖 session 维度，且**创建期用 isolationKey、后续用 runtimeId，两个 key 哈希到不同副本**——这是设计层面的矛盾，单元测试（假 host）无法发现。
- **修复（三层）**：
  1. `transport.py`：sticky key 优先级改为 **显式 sticky_key（isolation key）> isolationKey 查询参数 > runtime_id > session_id**；新增 `runtime_id_from_path`，三个标识都转发到 header 供日志关联。
  2. `gateway.py`：`_RuntimeBinding` 新增 `isolation_key` 字段（创建/发现两处都填），新增 `_isolation_key(runtime_id)` 辅助方法，**12 处调用点**统一传入 `sticky_key=isolation_key`。
  3. `dsh-runtime-lb.conf`：nginx 用三层 `map` 实现同样优先级（isolation > runtime > session > `$request_id` 兜底），并新增 `X-Runtime-Id` / `X-Isolation-Key` 转发与日志字段。
- **修复后真实端到端复验（通过）**：
  - 全链路 `create_runtime → create_session → describe_session`：**201 / 201 / 200**，三次请求 LB 日志 `key=tenant:t5:profile:p5`、`upstream=192.168.148.4` **完全一致**（修复前为 400 `runtime not found`）。
  - **8 个不同 tenant 并发跑完整生命周期：8/8 成功**，散落到 3 个副本（10/2/4）。
- **测试**：`test_multi_host_transport.py` 由 17 项扩到 **27 项**，新增 runtime 级路由、`create_and_use_runtime_stay_on_one_replica` 回归、隔离键优先级等用例；既有 session 级用例改用无 runtime 段的路径以隔离被测维度。
- **兼容处理**：`tests/dsh_runtime/test_gateway_step2.py` 的 fake transport（`request` / `stream`）补 `session_id` / `sticky_key` / `**kwargs`，避免 Protocol 扩展导致既有测试崩。

### 二、案例二 timeout 口径（已拍板并修正）

- 原状：案例 §8 要求"总耗时 ≤ 15 分钟"，但编排 YAML 写 `timeout: 1800`（30 分钟）——**文档内部矛盾**。
- **用户决定**：改为与验收标准对齐 → `timeout: 900`，并同步更新 `docs/cases/multi-agent-competitor-deep-dive.md` §3 的 YAML 片段（原注释"30 分钟总超时"一并改）。
- **测试补充**：断言 `loaded.timeout == 900`，且**并行节点的单个上限必须落在总预算内**（`max(node_timeouts) <= 900` 而 `sum(node_timeouts) = 3300 > 900`，正好编码了"并行而非串行"的语义）。

### 三、Skill 命名约束（已拍板：维持双命名）

- 现状：`skill_packages/validator.py` 的 `SKILL_NAME` 强制 kebab-case（不允许下划线），而仓库 9 个内置 Skill 全用 snake_case。
- **用户决定**：维持双命名，但把规则写清楚 → 在 `docs/cases/README.md` 新增「Skill 的两种命名（不要混用）」小节，用表格明确：**Skill id（snake_case）**用于内置目录与编排 `skill:` 字段；**安装包名 `packageName`（kebab-case）**用于 SkillHub 安装；`SKILL.md` 必须同时声明两者，测试分别断言。

### 验证与回归

- chat-api 全量：**1877 passed, 8 failed**（基线 1877/8 中的 8 项为预存 e2e 环境依赖失败，**无回归**；总数从 1867 增至 1877 为新增路由测试）。
- nginx 配置语法校验通过；`docker compose config` 通过。
- 验证环境 `movo-e2e` 保留在运行状态以便复查；LB 日志证据留存 `/tmp/lb-e2e-evidence.log`（19 行 runtime/session 请求记录）。
- 改动文件：`services/chat-api/app/dsh_runtime/{transport,gateway}.py`、`deploy/docker/dsh-runtime-lb.conf`、`services/chat-api/app/enterprise_capabilities/research/orchestrations/competitor_deep_dive.yaml`、`services/chat-api/tests/dsh_runtime/{test_multi_host_transport,test_gateway_step2}.py`、`services/chat-api/tests/orchestration/test_competitor_deep_dive.py`、`docs/cases/{README.md,multi-agent-competitor-deep-dive.md}`。

## 2026-09-24 远端地址迁移：cooper2006/mogong → cooper2006/mogo

- **需求**：远端推送地址调整为 `https://github.com/cooper2006/mogo.git`（用户确认该仓库是原 `mogong` 改名而来，非新建独立仓库）。
- **执行**：
  - `git remote set-url mogong https://github.com/cooper2006/mogo.git` 后 `git remote rename mogong mogo`（用户确认 remote 名同步改为 `mogo`，保持名字与地址一致）。
  - 验证：`git remote -v` 显示 `mogo` → 新地址；`git fetch mogo` 成功；`mogo/main` 与本地 `main` 同为 `d226bbc`。
  - **迁移前核对**：`git ls-remote` 两个地址均返回同一 HEAD `d226bbc`，确认是改名重定向而非不同仓库。
- **同步更新规则文件**（这是活跃规则，必须与实际 remote 一致，否则后续代理会推错地址）：
  - `AGENTS.md`「远端仓库边界」：推送目标改为 `cooper2006/mogo`（`mogo` remote），并注明由 `mogong` 改名而来、旧地址会重定向。
  - `.specify/memory/constitution.md` 同段：按该文件 Governance 条款完成修订——**记录理由 + 版本号 1.1.0 → 1.1.1 + Last Amended 2026-07-08 → 2026-09-24**，并新增 Amendment Log 条目。
- **未改动**：
  - `origin`（himovo/movo）保持 `no-push` 锁定，未触碰。
  - `docs/WORK_LOG.md` 中历史条目里的 `cooper2006/mogong` 字样**保持原样**——那是当时推送事实的记录，不应回溯改写；新条目起使用 `mogo`。
  - README 中的 `git clone` 地址仍指向 `himovo/movo`（上游社区版仓库），与本次推送远端无关，未改动。

## 2026-09-24 README 重写为「墨攻 MOGO」企业级智能体平台（中英双语）

- **需求**：按用户给定的六点思路重写 README——① 产品名改为**墨攻（MOGO）**，定位为"基于 DSH 的企业级智能体平台，在开源 MOVO 平台基础上构建"；② 引入 spec-kit SDD 开发规范；③ 增强企业级功能（P2 九项）；④ 智能体多实例运行改造；⑤ 客户反馈智能分诊案例；⑥ 竞品深度调研案例。
- **澄清（用户确认）**：产品名以指令为准写作 **MOGO**（V3 PPT 里原文为 "MOGONG"，未采用）；"9 项"指补强清单 **P2 的第 7–15 项共 9 项生态能力**（非 slide3 的"九大能力域"）；中英双语两份都重写。
- **素材来源**：`docs/movo-intro-v3.pptx`（12 页，用 zipfile 直接解析 `ppt/slides/*.xml` 的 `<a:t>` 提取全文）+ `docs/MOVO企业级智能体功能补强规划.md` §三/§六 + `specs/` 19 个特性。
- **新结构**（两份各 345 行，章节一一对应）：
  1. **与开源 MOVO 的关系**——五块已领先能力（容器化自托管 / Docling 解析 / 内容生成 / 多形态 Agent / SkillHub）作为"不重复造轮子"边界，说明墨攻只做加法
  2. **主线一：spec-kit SDD**——`.specify/` + `specs/` 结构说明，19 个特性各自含 spec/plan/tasks/checklist/contracts
  3. **主线二：企业级功能补强**——P0 六项（Gatekeeper 六层门禁、风险分级与自主矩阵、RBAC 权限码、PII 脱敏、网关韧性、运营驾驶舱）、P1 三项、**P2 九项**（逐项附 spec 编号链接）
  4. **主线三：多实例运行改造**——按 `kernel_session_id` 一致性哈希 + `X-Session-Id` + `hashlib.sha256` 稳定性说明 + 向后兼容 + 50 并发 × 3 副本契约测试
  5. **落地案例**——两个案例（单智能体 vs 多智能体）并说明选型判断，各自概述场景与能力组合
  6. 保留并更新运维章节：快速启动 / 社区版 / 桌面端 / 系统架构（架构图加入 sticky LB）/ 部署运维（新增"多实例横向扩展"小节）/ 配置 / 从源码构建 / 仓库结构（加入 `specs/`、`.specify/`）/ 贡献 / 许可证
- **准确性核对**（逐条实测，非估计）：
  - 两份 README 的 **25 个本地引用零缺失**（脚本校验 markdown 链接与 html src/href）
  - P2 表格引用的 9 个 spec 目录全部存在；`specs/` 确为 19 个特性
  - **270 / 270 个 tasks 全部勾选完成**，支持"tasks 已全部完成"的表述
  - 修正一处表述不一致：P0 表格实际列出 6 行子能力（治理层被拆分展示），与规划文档的"15 个清单项"口径不同，已改写为"规划中的 15 个清单项（其中治理与风控层含…子能力）已全部实现"，避免读者把表格行数当作清单项数
- **未改动**：`LICENSE` 仍引用 MOVO 社区许可证（法律文本，未获授权不改）；环境变量名 `MOVO_*` 与镜像前缀保持原样（部署兼容性）；`docs/` 中的其他文档未动。

## 2026-09-24 SDD 三部分落地：多实例运行改造 + 两个案例实例（全部可运行代码 + 逐条验收测试）

依据用户指定的三份 SDD 文档，把"实现"落成可运行代码与可执行测试（非仅文档）。

### 一、智能体多实例运行改造（`docs/open-source-productization/agent-multi-instance-evaluation.md` P1 层 A + P2）

- **`services/chat-api/app/dsh_runtime/transport.py`**：`HttpKernelHostTransport` 支持多 host（新增 `base_urls`，保留 `base_url` 向后兼容）；按 `kernel_session_id` 做**一致性哈希**路由，每次请求注入 `X-Session-Id`；新增 `normalize_base_urls` / `configured_runtime_hosts` / `session_id_from_path` / `sticky_index`。
  - 哈希用 `hashlib.sha256` 而非内置 `hash`——后者受 `PYTHONHASHSEED` 影响，重启后会漂移，导致 session 找不到所属 host。
  - sticky key 从 path（`/v1/runtimes/{rid}/sessions/{sid}/...`）自动提取，**无需改动网关全部调用点**；同时支持显式 `session_id` 参数覆盖。
- **`core/config.py`**：新增 `DSH_RUNTIME_HOSTS_URL`（逗号分隔），空值回退 `DSH_RUNTIME_HOST_URL`。
- **`dsh_runtime/application.py`、`__init__.py`**：按新配置装配并导出新符号。
- **`docker-compose.yml`**：`dsh-runtime-host-1/2/3` 三个副本（YAML 锚点复用，因 `deploy.replicas` 仅 Swarm 生效）+ `dsh-runtime-host-lb`（nginx sticky）；`chat-api` 指向 LB，并注入 host 列表。
- **`deploy/docker/dsh-runtime-lb.conf`**：`hash $http_x_session_id consistent`，无 header 时回退 `$request_id` 避免空 key；SSE 不缓冲、超时 3600s；`log_format` 输出 session/upstream 便于排障。
- **`deploy/cli/dsh-version.sh`**：跟随服务改名读取 `dsh-runtime-host-1`。
- **P2 契约测试** `tests/dsh_runtime/test_multi_host_transport.py`：**17 项**——哈希稳定性（含与独立 sha256 计算对照）、分布非退化、单 URL 向后兼容、header 注入与缺失、显式 session_id 覆盖、**50 并发 × 3 host 的 session 亲和性**、request 与 stream 选中同一 host。
- **实测 sticky 生效**（非仅语法检查）：临时起 3 个假 host + 该 LB 配置，同一 `sess-A` 连续 5 次全部命中 `HOST-3`；8 个不同 session 分布到全部 3 个 host。

### 二、案例一：客户反馈智能分诊（`docs/cases/single-agent-customer-feedback-triage.md`）

- **Skill 全套** `app/skills_specs/customer_feedback_triage/`：`SKILL.md`（含 `---` 包裹的 frontmatter，符合 `skill_packages/validator.py` 契约）、`templates/triage_report.md`、`templates/action_items.csv`、`scripts/severity_heuristics.py`、`validation.yaml`。
  - **发现并处理命名约束**：`validator.py` 的 `SKILL_NAME` 强制 kebab-case（不允许下划线），而仓库内置 Skill 全用 snake_case。故 SKILL.md 同时声明 `name: customer_feedback_triage`（内置 id，与案例文档一致）与 `packageName: customer-feedback-triage`（可安装包名），测试对两者分别断言。
- **可运行运行时** `app/cases/customer_feedback_triage.py`：8 个 step 全部落成可调用实现（load/normalize/classify/categorize/redact/rank/compose/approval），LLM 与审批/审计/成本边界均为可注入 Protocol + 默认实现；内置 `DefaultPiiRedactor`（mask/remove/hash/abstract，与 admin-api `governance/pii.py` 策略表对齐，**不跨服务 import**）。
- **验收测试** `tests/cases/test_customer_feedback_triage.py`：**15 项**，覆盖案例 §6 的 8 条标准（AC-1 批量 500 条 ≤180s、AC-2 P0 召回率、AC-3 PII 零泄漏「正则 + Shannon 熵双判定」、AC-4 P0≥3 触发审批、AC-5 成本入 token_usage、AC-6 审计八步完整、AC-7 commit 后可 resume、AC-8 Skill 包通过校验），另有负例（P0<3 不触发审批、去重、CSV 上限、模板节齐全）。
  - 实测 **P0 召回率 100%（20/20）**，阈值 95%。
  - 测试修正了采样缺陷：召回率改在**全量批次**上统计（而非被 `ACTION_ITEM_LIMIT` 截断的 action items），避免 P0 多于 20 条时被误判为漏检。

### 三、案例二：竞品深度调研（`docs/cases/multi-agent-competitor-deep-dive.md`）

- **新增 YAML 编排加载器** `app/orchestration/loader.py`（此前只有 Python dict 入口，案例 YAML 无法生效）：`load_orchestration_file/text/directory`，支持 `depends_on` 自动推导边、`data_contract`/`failure_propagation`/`audit` 段落解析。
  - **关键语义修正**：案例用 `skip_condition: {expr: "..."}`（**表达式为真时跳过**），而引擎的 `condition` 是**为真时运行**——极性相反。加载器把 `expr` 编译为结构化条件并包一层 `not`，使文档保持自然读法。
  - 新增 `compile_expr`：把 `"completed_children_count < 3"` 编译为引擎的 `{"op": "<", "left": {"var": ...}, "right": 3}`；无法表达的语法在**加载期**报错（而非运行期静默为常量）。
- **编排定义** `app/enterprise_capabilities/research/orchestrations/competitor_deep_dive.yaml`：graph 模式、并发 4、总超时 1800s、指数退避重试、5 节点（4 并行分析 + 1 汇总）、两处 skip_condition、data_contract、failure_propagation、audit。
- **5 个子 Skill** `app/skills_specs/{market_intelligence_v1,product_analysis_v1,financial_analysis_v1,sentiment_monitor_v1,report_synthesis_v1}/`：各含 SKILL.md（`role: subagent` / `parent_skill` / `output_key`）、templates、scripts（entity_resolution / feature_normalize / ratio_math / topic_cluster / evidence_index）、validation.yaml。
- **编排运行时** `app/enterprise_capabilities/research/competitor_deep_dive.py`：data_contract 发布、指数退避重试（`RetryPolicy`，实测 5s→10s）、失败传播、降级报告、节点级观测（attempts/并发峰值/耗时）。
  - **失败传播按案例 §6.2 实现**：单个分析节点永久失败**不阻塞**汇总节点（引擎默认会阻塞），而是软化为"无数据"并计入 `completed_children_count`；≥3 → 正常合成，<3 → 汇总节点跳过 + 降级报告。实测四场景全部符合预期（4 成功→合成；3 成功→合成；2 成功→跳过+降级；0 成功→跳过+降级）。
- **验收测试** `tests/orchestration/test_competitor_deep_dive.py`：**25 项**，覆盖案例 §8 的 10 条标准（并行度 ≥3 + 时间窗重叠、耗时预算、环检测拒绝执行、条件跳过含 skip_reason、节点重试与退避、失败传播、Evidence 可反查、风格契约、成本按节点聚合、commit/share/resume），另有加载器与子 Skill 契约检查。

### 验证与回归

- **chat-api 全量**：`./venv/bin/python -m pytest tests/ -q --ignore=tests/llm/test_decision_turn.py` → **1867 passed, 8 failed**。
  - 基线（改动前实测）为 **1810 passed, 8 failed**；8 个失败全部是 e2e 环境依赖（`DSH Runtime Host exited during startup with code 1`），与本次改动无关，**无回归**，新增 57 项测试全部通过。
- **环境要点**（供后续复用）：chat-api venv 是 `services/chat-api/venv`（非 `.venv`）；排除坏例必须用 `--ignore=tests/llm/test_decision_turn.py`（该文件是 collection error，`--deselect` 无效会直接中断）。
- 文件：新增 `app/orchestration/loader.py`、`app/cases/customer_feedback_triage.py`、`app/enterprise_capabilities/research/competitor_deep_dive.py`、`app/enterprise_capabilities/research/orchestrations/competitor_deep_dive.yaml`、`app/skills_specs/customer_feedback_triage/*`、5 个子 Skill 目录、`deploy/docker/dsh-runtime-lb.conf`、两个测试文件；改动 `dsh_runtime/{transport,application,__init__}.py`、`core/config.py`、`docker-compose.yml`、`deploy/cli/dsh-version.sh`。

## 2026-09-24 README 补入 P0/P1 已落地能力（依据《MOVO企业级智能体功能补强规划》）

- **需求**：依据 `docs/MOVO企业级智能体功能补强规划.md` 的内容修改 README，**重点体现 P0/P1 已落地的新能力**；经用户确认目标为根目录 `README.md` + `README.zh-CN.md` 双语同步。
- **改动**：在两个 README 的「MOVO 提供什么 / What MOVO provides」表格之后，新增一节 `## 企业治理与可靠性 / Enterprise governance and reliability`，含两张表：
  - **P0 —— 合规入场券与生产可用性**：Gatekeeper 六层串行门禁（R4 红线不可覆盖）、R0–R4 风险分级 + L1–L5 × R0–R4 自主矩阵（25 格）、细粒度 RBAC 权限码 `<resource>:<action>[:<target>]`（三级隔离 + fail-closed）、PII 脱敏（mask/remove/hash/abstract，运行时 + 会话保存/分享双保险、可逆占位符、clone 只读）、LLM 网关韧性（failover + 降级链 + 指数退避 + 用量成本计量）、运营驾驶舱（成本/使用/质量/趋势四维）。
  - **P1 —— 可扩展性与会话级协作**：Hooks 五事件（含 PreToolUse tool > session > tenant 优先级 + ≤5s 延迟预算 + fail-closed + 声明式规则）、DAG 编排四模式（拓扑/环检测、三态 fail-closed 条件跳过、节点级指数退避）、会话与工作流双版本化（commit 线性时间线 / 一次性 share 300s TTL / 共在线多人协作）。
  - 末尾一段列出 P2 长线工作（Dream 自进化、A2A、多 IM、业务索引、知识图谱、Skill 市场强化、三范围记忆、能力资产化、Harness 弹性），并链到 `docs/MOVO企业级智能体功能补强规划.md` 与 `docs/SDD界面呈现对照表.md`。
- **措辞**：明确写为 "implemented, tested and available in this release / 均已实现、通过测试，并在本版本中可用"，与规划文档 §6「落地进展」的 ✅ 状态一致，不把 P2 混入已交付能力。
- **验证**：两处新增小节标题确认存在；两个链接目标文件均存在（含中文文件名路径）；行数 README.md 260→285、README.zh-CN.md 269→294。
- **未改动**：README 的定位、Quick Start、部署运维、许可证等既有章节保持不变（用户未要求）。

## 2026-09-24 驾驶舱"5 个 tab 只剩总览"真正根因：n-tab-pane 相互嵌套（前两轮修复不彻底）

- **用户反馈**：切到成本/使用/质量/趋势任一 tab，显示的仍是"总览"的 6 个 metric cards。
- **根因**：前两轮的脚本改造只把 5 个 `<n-tab-pane>` 改成**开口**却仍连续排在一起，5 个 tab-body div 排在后面——Vue 编译后形成**层层嵌套**：`overview pane` 的 default slot 里套着 `cost pane`（其 slot 里又套 `usage`…）。Naive UI 渲染激活 pane 时，最外层 overview 的 slot 已含全部内容，于是切任何 tab 都渲染 overview。
  - dist 证据（修复前 `DashboardPage-60d16d3c.js`）：`_(B,{name:"trend"...,{default:c(()=>[ ...metric-card（overview 的内容）... ])` —— trend pane 的 slot 里竟然是 overview 内容。
- **修复**：用 Python 从源码提取「5 个 pane 开头 + 5 个 tab 注释 + 5 个 tab-body div 块」，重新组装为**兄弟结构**：
  ```
  <n-tab-pane name="overview" :tab="t('总览')"> <div class="tab-body">…overview…</div> </n-tab-pane>
  <n-tab-pane name="cost"     :tab="t('成本')"> <div class="tab-body">…cost…</div>     </n-tab-pane>
  … 5 个平级 …
  ```
  同时统一缩进。改动前备份 `apps/admin-web/src/views/dashboard/DashboardPage.vue` → `/tmp/DashboardPage.vue.bak`。
- **验证**：`docker build`（内含 `vue-tsc --noEmit && vite build`）通过；新 chunk `DashboardPage-a432b63b.js`；dist 反查确认 3 个 pane 的 slot 内容各自独立：
  - `overview` → metric-cards；`cost` → 「成本维度」卡片；`trend` → 「环比 / 同比」卡片。**不再嵌套**。
- 镜像 `a5847843`，`--force-recreate` 重启 admin-web healthy。请硬刷新验证 5 个 tab。

## 2026-09-24 驾驶舱 5 tab 修复补遗：去掉冗余 v-show，让 n-tab-pane 单独控制可见

- **用户反馈**："原来的 5 个功能点怎么变成一个了"——总览 tab 渲染了 6 个 metric cards 出数（近 24h 调用 51 / Token 消耗 16.5 万 / 活跃用户 1 / 成功率 94.12% / 近 24h 成本 ¥10.26 / 平均耗时 4.96s），但其他 4 个 tab（成本/使用/质量/趋势）切过去空白。
- **根因**：上一轮把 `<div>` 移进 `<n-tab-pane>` slot 时**保留了 `v-show="activeTab === 'X'"`**——Naive UI 的 `n-tab-pane` 非激活时设置 `display:none`，但内部 `v-show` 再次设置 `display:none`（或与 Naive UI 的隐藏机制冲突），导致非激活 tab 内容彻底不可见。
- **修复**：`apps/admin-web/src/views/dashboard/DashboardPage.vue` 5 个 tab-body div 去掉 `v-show`，让 `<n-tab-pane>` 单独管理 panel 可见性。
- **构建**：admin-web 镜像 `ac887c4e`（DashboardPage chunk `60d16d3c`），`--force-recreate` 重启 healthy。
- **请用户硬刷新**（Cmd+Shift+R）后验证 5 个 tab 全部有内容。

## 2026-09-24 驾驶舱 5 个 tab panel 全空白根因：n-tab-pane 自闭合 + div 兄弟节点

- **用户截图**（vision 看图）：导航 MOVO logo + 工作台高亮 + 五个 tab label（总览/成本/使用/质量/趋势）渲染正常，当前高亮"趋势"，**但 panel 内容区完全空白**（不是整页白屏）。控制台无任何消息。
- **根因**（源码层）：`apps/admin-web/src/views/dashboard/DashboardPage.vue` 的 5 个 `<n-tab-pane name="X" :tab="..."></n-tab-pane>` 全是**自闭合**（无 default slot），而真正的 panel 内容（`<div v-show="activeTab === 'X'" class="tab-body">...</div>`）是这些 n-tab-pane 的**兄弟节点**，不是 slot 子节点。Naive UI 的 `<n-tab-pane>` 没有 slot 时不渲染 panel 内容 → 5 个 tab 全部 panel 空，5 个兄弟 div 被 Vue 当作 n-tabs 的额外 children 渲染（因 v-show 同一时刻只显示一个，看起来"什么都没渲染"）。
  - 同一文件 1437 行 5 个 pane 全部同型问题（之前从未工作过；用户一直看到的"驾驶舱空白"就是这个 bug，与 P50/P95/演示数据/analytics 500 都无关——这些是别的维度）。
- **修复**：用 Python 脚本两步入 `apps/admin-web/src/views/dashboard/DashboardPage.vue`：
  1. 5 个 `<n-tab-pane ...></n-tab-pane>` 自闭合 → 开口 `<n-tab-pane ...>`；
  2. 在每个 tab-body div 的结束 `</div>` 后插入 `</n-tab-pane>`（按括号配对定位）。
  - 保留 `v-show` 冗余显示控制（n-tab-pane 自身已管理可见性，多一层无害），最小风险。
- **构建**：经典 builder 重建 admin-web 镜像 `3221c6bf`（chunk hash 从 `DashboardPage-30658e94`/`index-adbb82cc` 变为 `DashboardPage-0b1e948f`/`index-5ba7f9c3`），`--force-recreate` 重启 admin-web healthy。
- **请用户硬刷新**（Cmd+Shift+R）后验证 5 个 tab panel 都能正常渲染（数据已在 dashboard/overview 出数：calls24h=59、quality p50/p95、usage/quality 各段齐备）。

## 2026-09-24 驾驶舱白屏定位：`/api/analytics/token-usage` 500（BSON datetime 同型 bug）

- **现象**：用户截图反馈"驾驶舱页面全白（无导航无布局）"，控制台报 `Failed to load resource: 500`，出错栈在 `AnalyticsPage-9e186a6b.js`。
- **定位**：管理后台 `/admin/dashboard` 路由实际渲染的是 **AnalyticsPage**（非 DashboardPage），它请求 `/api/analytics/token-usage` 返回 500 → 前端 catch 后整个页面挂掉。
  - 根因（容器内日志）：`app/api/routes/analytics.py:273` `start_time = int(row.get("start_time") or 0)` 对 **BSON datetime** 抛 `TypeError: int() argument must be a string... not 'datetime.datetime'`——与本轮早先修的 `dashboard.py _duration_ms` **完全同型**。我造的演示数据（`start_time`/`end_time` 为 datetime）触发了这个隐藏 bug。
- **修复**：`analytics.py` 新增 `_to_ms()` 归一化（兼容 epoch int 与 datetime），第 273-275 行改用它；全仓 grep 确认无其它 `int(...get("start_time"/"end_time"))` 残留。
- **验证**：admin-api 236 项测试全过；重建镜像 `53712d3b` + `--force-recreate` 重启 healthy；`analytics/token-usage` 由 500 → **200**（items 20 条，durationMs 正常出数），`dashboard/overview` 仍 200。
- **全量体检**：管理后台 12 个页面接口（analytics ×2 / dashboard / tools / skills / system-audit ×2 / hooks / governance ×3 / auth/me）全部 200。
- 说明：浏览器 provider 仍未注册，无法通过自动化点击验证；本次由用户提供的浏览器控制台 500 报错直接定位。

## 2026-09-24 §6 界面实操核验 + 4 处 motor 异步 bug 修复 + 演示数据造数

- **浏览器 provider 未注册**（`browser_open` 报 "no usable browser provider is registered"），改用用户给定凭据做 API 级界面端点核验：admin（`admin`/`1qaz2wsx#EDC`）登录 admin-api、朱军峰（`zhujunfeng@bonc.com.cn`/同密码）登录 chat-api。
- **路由双前缀发现**：admin-api `api_router` 以 `/api` 挂载，而 hooks/governance router 自身又带 `/api` prefix，实际路径为 `/admin-api/api/api/hooks/...`、`/admin-api/api/api/governance/...`；单前缀 404。
- **§6 八步 + P0/P1/P2 各条目逐条核验**（端点 + 数据 + 服务层运行时）全部通过：
  1. 驾驶舱 `GET /admin-api/api/dashboard/overview`（已登录）200，顶层 billing/health/metrics/assets/quality/trend/usage/todos/recentActivity 九段齐备；
  2. 风险格 `GET /admin-api/api/api/governance/autonomy-matrix` 200，L1–L5×R0–R4 矩阵 + canonical；
  3. 钩子规则全链路：`POST /rules` 201（deny_tool）→ `GET /rules` 200 → `GET /rules/{id}` 200 → `GET /scope?tool=dangerous_tool` 命中 → `DELETE` 204；
  4. 会话版本化（002）容器内 DB 模式：`ShareStore.create_share` token + `is_active()`、`CoPresence` 双用户心跳→`online()={u1,u2}`、`merge_messages` 线性时间线 [1,2,3,4,5,6]；
  5. DAG（010）：`evaluate_skip` 三态（true→skip / false→run / 语法错→fail-closed）+ `run_node_with_retry`（RetryPolicy 指数退避）；
  6. Dream（011）：`detect_low_adoption` 命中/不命中正确、`mark_deprecated`/`restore`；
  7. 能力资产（018）DB 模式：`register`→`governance_view`（3 条）→`governance_detail`（契约下钻）→`set_status(offline, approver)` 审批→`mark_a2a_exposed`；
  8. 审计落点：`/admin-api/api/system-audit/logs` 200，hooks/skills/tools 管理事件落 001 落点。
- **发现并修复 4 处 motor 异步 bug**（同步方法直接调用 motor 异步 db，返回 Future 不 await → 500/写入丢失）：
  - admin-api `app/services/hooks_store.py`：6 个 CRUD 方法改 `async` + `routes/hooks.py` 6 处调用加 `await`（此前 `GET /api/api/hooks/rules` 500，`'_asyncio.Future' object has no attribute 'get'`）；
  - chat-api `app/dsh_runtime/hooks/store.py`：同型 7 个方法改 async；`tests/test_hooks_009.py` 3 项测试改 `@pytest.mark.asyncio`；
  - chat-api `app/services/capability_assets.py`：`CapabilityAssetRegistry` 9 个方法改 async + DB 模式下 `governance_view` 从库回灌 in-memory；`tests/services/test_capability_asset_us2.py` 7 项测试改 async；
  - chat-api `app/services/session_versioning/share.py` + `co_presence.py`：`ShareStore` 4 个方法 + `CoPresence` 5 个方法改 async，修正 `ShareStore.to_document(share)` 传参错误（原 `TypeError: missing 1 required positional argument`）；`tests/services/test_session_us5_and_polish.py` 同步更新 fake + async。
  - 另修 admin-api `app/api/routes/dashboard.py` `_duration_ms`/`_duration_percentiles_fallback` 的 `int(row.get("start_time"))` 对 BSON datetime 报错（500）→ 新增 `_to_ms()` 归一化。
- **测试基线**：admin-api 236 项全过；chat-api 非 e2e 1808 项全过（排除预存坏例 `test_decision_turn` 与 4 个 dsh_runtime e2e 文件——stash 对照确认 e2e 失败为预存环境依赖，与本次改动无关）。
- **重建镜像**（经典 builder `DOCKER_BUILDKIT=0`）：admin-api `babb202a`、chat-api `0877b010`，均 `--force-recreate` 重启 healthy，修复已确认带进容器。
- **造演示数据**（均带 `demo_seed: true` 标记，可一键清理）：tools ×3、skills ×3、`token_usage_logs` 24h 窗口 ×60、`capability_assets` ×3（对齐 registry schema）、`session_shares` ×1。造数后驾驶舱各段（metrics/quality/usage/trend）均出数（calls24h=59、p50Ms/p95Ms 正常、trend 环比/瓶颈 top-N 齐备）。
- 遗留：浏览器实操（UI 点击触发）仍需 provider 注册后补做；端点/数据/服务层/演示数据全部通过。

## 2026-09-24 智能体案例设计（单智能体 + 多智能体协同）

- 新增 `docs/cases/` 目录，含 3 个文件：
  - `README.md` — 案例索引 + 单/多智能体决策指南 + 设计原则
  - `single-agent-customer-feedback-triage.md` — 客户反馈智能分诊（单 Skill · 单会话）
  - `multi-agent-competitor-deep-dive.md` — 竞品深度调研（5 子智能体 · DAG graph 编排）
- 案例设计贴合项目实际能力：Skill YAML 参照 `skills_specs/stock_analysis/SKILL.md` 内置范式；DAG 编排引用 `specs/010-dag-orchestration-engine`；治理能力（PII/RBAC/审批/审计）映射到 `admin-api/app/governance/`；成本聚合映射到 `llm/resilience/metering.py`。
- 单智能体案例（客户反馈分诊）：8 个 step 顺序执行、无需并行；核心展示单 Skill 完整生命周期 + P0 触发审批（R1）+ 全链路审计 + 会话 commit。
- 多智能体案例（竞品深度调研）：5 个子智能体（市场/产品/财务/舆情/合成），采用 DAG graph 模式，4 个分析节点并行 + 1 个汇总节点依赖；含条件跳过（私有公司跳财务）、指数退避重试、失败传播（<3 子节点完成则合成节点跳过）、Evidence 追溯、成本分项聚合。
- 明确设计边界：不引入新工具依赖、不新增编排模式、不覆盖未实现的场景（如实时数据流），所有能力调用点均对应现有代码。
- 决策指南明确：能用单智能体就别上多智能体；判断核心问题是"子任务是否有独立数据源或分析模式"；DAG 四模式（graph/hybrid/sequential/supervisor）按依赖是否静态、是否需动态分派区分。

## 2026-09-24 工作台为空排查 + P50/P95 真实 bug 修复（Mongo 6.0 无 $percentile）

- **现象**：用 admin 账号登录（密码 1qaz2wsx#EDC）后，工作台五标签内容全空。
- **排查**：`GET /api/dashboard/overview` 返回 200（非报错），`assets` 有内容（用户 1/模型 1/部门 1），但 `metrics`/`usage`/`trend` 全 0。根因是**租户隔离 + 该租户无调用数据**：dashboard 按 `main_id` 过滤（`tenant_match`），库里仅 2 条 `token_usage_logs` 且属于 `setup-test-*` 测试租户；BONC 租户（`bonc-8edc43f4957660c85fd050c9`）下 0 条。`created_at` 经查是 BSON Date（用 Date 查询命中 2 条、字符串比较为 0），**非类型 bug**。
- **修复 P50/P95 真实 bug**：`_quality_metrics` 用 Mongo `$percentile` 算 P50/P95，但该操作符仅 Mongo ≥7.0 支持，项目固定 `mongo:6.0.20`（实测 `Unknown expression $percentile`），异常被 `except` 静默吞掉 → **生产环境 P50/P95 恒为 None**。
  - 新增 `_duration_percentiles_fallback()`（`app/api/routes/dashboard.py`）：从 `end_time - start_time` 取时长后在内存按最近秩（nearest-rank）算 P50/P95；不升级 Mongo、不改基础镜像，6.0/7.0 均正确出数。
  - 验证：修复前 P50/P95 = None；修复后 P50=4852ms、P95=7827ms、avg=4705ms。admin-api 236 项测试通过。
- **造演示数据**（仅本机界面验证用）：向 `token_usage_logs` 写入 495 条 BONC 租户记录（60 天跨度、4 模型、4 用户、含 failed/timeout 异常态），均带 `demo_seed: true` 标记，可一键清理：
  `db.token_usage_logs.deleteMany({main_id:"bonc-8edc43f4957660c85fd050c9", demo_seed:true})`
- 重建 admin-api 镜像并 `--force-recreate` 重启，验证接口出数正常。

## 2026-09-24 §6 验证清单 8 步核验（chat-api 强制重建 + 服务层运行时验证）

- **发现并修正 chat-api 镜像缓存问题**：此前"重建"的 chat-api 镜像（8fb9a）实际命中 buildx 缓存，`/app/app/services/dag`、`/app/app/llm/resilience` 等 SDD 模块缺失。用 `DOCKER_BUILDKIT=0 docker build --no-cache` 强制重建（`ccb26ffc`，2026-09-24 13:39），`--force-recreate` 重启 chat-api 容器，确认容器内全部 SDD 模块在位（dag/dream_cycle/session_versioning/llm.resilience/orchestration/a2a/im_gateway/capability_assets/feature_audit）。
- **§6 八步核验结果**（端点 + 数据 + 服务层运行时）：
  1. 驾驶舱端点挂载（未登录 401）+ DashboardPage 五标签在 admin-web 镜像 dist；
  2. `autonomy_matrix` 25 行（L1–L5×R0–R4）+ governance 端点；
  3. `/api/hooks/rules|rules/{id}|scope` openapi 就绪；
  4. 容器内 `build_share`（token + active）/ `CoPresence`（双用户心跳→在线）/ `merge_messages`（线性时间线）通过；
  5. `evaluate_skip` 三态（true→skip / false→run / 语法错→fail-closed skip）+ `run_node_with_retry`（成功 1 次 / 失败后 3 次 / 退避 [1.0,2.0] 递增 / 耗尽 succeeded=False）通过；
  6. `detect_low_adoption`（≥20 曝光 & <10% & 14d）命中/不命中 + `mark_deprecated`/`restore` 通过；
  7. `CapabilityAssetRegistry` 注册→治理视图→详情下钻→状态审批→`a2a_exposed` 标记 + 非法状态 ValueError 通过；
  8. `record_feature_event`（012/014/015/016/017/018 事件族）+ `im.deliver` 审计 + 未知事件拒绝通过。
- 结果已写入 `docs/SDD界面呈现对照表.md` §6.1（核验表格 + 遗留说明）。
- 遗留：浏览器实操（UI 点击触发）当前会话浏览器 provider 未注册，用服务层运行时等价验证代替；端点/数据/服务层全部通过。

## 2026-09-24 document-parser 镜像重建（经典 builder + HF 镜像源）

- 补上 8 个镜像中最后一个未重建的 `document-parser`：此前 Docling 模型下载步骤因 Docker 内网络无法直连 huggingface.co 而失败。
- 本次以 `DOCKER_BUILDKIT=0 docker build ... --build-arg MOVO_HF_ENDPOINT=https://hf-mirror.com` 逐镜像构建成功（b1e3743e），Docling 模型经 hf-mirror.com 下载 + 离线校验通过。
- `--force-recreate` 拉起 document-api / document-worker 新容器，document-api healthy；探活 `localhost:3000`、`/admin` 均 200。
- 至此 8 个 `ghcr.io/himovo/movo-*` 运行时镜像全部为本地源码构建（chat-api/admin-api/dsh-runtime-host/admin-web/user-web/gateway/document-parser），容器镜像 ID 逐一验证匹配。

## 2026-09-24 镜像重建 + admin-api 导入 bug 修复 + P0/P1/P2 落地对照文档

- **经典 builder 重建**：OrbStack buildx 受 macOS provenance 锁死（`~/.docker/buildx/` 不可写，SIP 下 `sudo xattr -d` 也失败），改用 `DOCKER_BUILDKIT=0 docker build` 逐镜像构建并打 `ghcr.io/himovo/movo-*` 标签，绕过 buildx activity 写入。
- **admin-api 两处导入 bug 修复**（容器启动 `ModuleNotFoundError`）：
  - `routes/governance.py`：`from ..governance import ...` → `from ...governance import ...`（`..governance` 误指 `app.api.governance`，实际包在 `app.governance`）；函数内惰性导入同修。
  - `routes/hooks.py`：原先直接 import chat-api 的 `app.dsh_runtime.hooks.store`（admin-api 容器无此模块）→ 新增 admin-api 侧独立实现 `app/services/hooks_store.py`（同集合 `hook_rules`，无跨服务依赖，含 fail-closed 形状校验 + tool>session>tenant 作用域查询），路由改引用之。
- 修复后 admin-api 全量 236 项复跑通过；重建镜像 `--force-recreate` 重启，6 个容器镜像 ID 全部匹配本地新构建，`http://localhost:3000` 及 `/admin`、`/admin/setup` 探活 200。
- **文档增强**：
  - `docs/SDD界面呈现对照表.md` 重写为 P0/P1/P2 全量落地对照（速查总表 15 特性 × 代码位置/测试/界面触点 + 分节功能表 + 经典 builder 构建说明 + 8 步验证清单）。
  - `docs/MOVO企业级智能体功能补强规划.md` 新增「§六 落地进展」：清单 1–15 → specs/001–019 对应关系 + 各特性关键交付 + 测试基线（chat-api 313 / admin-api 236）+ 部署提示。
- 提交并推送 cooper2006/mogong（origin 未触碰）。

## 2026-09-24 智能体多实例运行改造评估（v2：目标收敛 + WS 重连检查）

- 用户确认三个决策：①目标是多 `dsh-runtime-host` 实例（chat-api 单实例保持）；②`conversation_id` 从 Header 提取（为后续 chat-api 多实例预留）；③要求检查 `local-browser-agent` WS 重连能力。
- **WS 检查结论**：`apps/local-browser-agent` 闭源，仓库中不存在（本地 `apps/` 只有 `admin-web`/`user-web`）；无法确认客户端重连逻辑。但**服务端证据充分**：`ws_endpoint.py:57-63` 20s 心跳、`registry.py:58-73` `attach` 主动取消旧连接的挂起调用（幂等设计）、`close(code=1008)` 明确错误握手。
- **新发现**：`services/chat-api/app/browser/registry.py:48` 类注释直接写"In-process singleton. Replace with Redis pub/sub for multi-worker"——开发者已明确识别出 `AgentRegistry` 是多实例化障碍。与 `DshAgentKernelGateway` 内存态同类问题，但**性质不同**：WS `send` 回调是本地 Python 对象，跨实例无法传递（`_sessions` 可通过 `attach_session` 跨实例恢复）。
- **本轮不做 WS 集群路由**：chat-api 单实例时 registry 完全够用，不涉及 WS 集群路由。未来做多 chat-api 实例才需 Redis pub/sub。
- **文档更新**：`agent-multi-instance-evaluation.md` 加入 2.2.2 新障碍、层 A hash key 决策（改为 `kernel_session_id` 而非 `conversation_id`）、层 C.1 WS 检查结论、P1/P2 收敛为本轮主交付、P3 列为待调研项。

## 2026-09-24 智能体多实例运行改造评估（v1）

- 新增 `docs/open-source-productization/agent-multi-instance-evaluation.md`：评估 `chat-api` 与 `dsh-runtime-host` 多实例化路径。
- 结论：现有架构下同一会话**不支持**在多个 chat-api 实例间并行处理；`DshAgentKernelGateway` 的 `_sessions`/`_runtimes`/`_credential_refresh_locks` 内存态是主要障碍。
- 分三层可交付：P1 层 A（LB sticky 让 dsh-runtime-host 可 2 实例，低复杂度）→ P2 层 B.1（SessionStore/RuntimeStore 抽象 + Redis 实现）→ P3 层 B.2（chat-api 一致性哈希 LB）→ P4 层 C（WS sticky）→ P5 Compose/K8s。
- 明确不引入 Celery：本场景路由是同步 HTTP，无队列必要；等具体异步需求出现再评估。
- `agent_kernel_bindings` 的 `claim_turn` 乐观锁已就绪，`kernel_session_id` 已由 dsh-runtime-host 生成，为跨实例接管奠定基础。
- 关键开放问题已列出：LB hash_key 提取方式、WS 滚动升级时客户端重连逻辑、Redis 分布式锁选型。

## 2026-09-22 收尾：admin-api 测试依赖 httpx2 入 requirements

- `services/admin-api/requirements.txt` 增补 `httpx2>=0.1.0`（test-only：新版 starlette 的 TestClient 需要 httpx2；admin-api `.venv-test` py3.14 全量 236 项复跑通过）。此前该依赖仅存在于本地虚拟环境，未入库，测试环境不可复现。
- 复核 001–019 各 `tasks.md` 未勾项 = 0；chat-api 313 项 / admin-api 236 项 / admin-web build 全绿；HEAD 已推送 cooper2006/mogong。

## 2026-09-22 落地 001–019 剩余任务（SDD 补全：代码 + 测试 + 文档 + 审计）

本轮把 `specs/001–019` 各特性 tasks.md 中未勾选项全部落地（实现 + 测试 + quickstart/contracts + T999 审计接入），并在勾选前核对实现已存在。

### 001 gatekeeper（admin-api）
- `app/governance/risk.py`（风险分级 + 25 格矩阵）、`pii.py`（5 类 PII + 策略引擎）、重写 `layers/redaction.py`/`quota.py`/`approval.py`、`permission_grants.py`、`layers/rbac.py` 并集显式授权、`app/api/routes/governance.py` 管理端点、`config.py` 配置变更留审计。
- 测试：`tests/test_governance_matrix.py`/`test_governance_pii.py`/`test_governance_us4_us5.py`/`test_governance_polish.py`（T015–T032 全勾选）。
- 全量 236 项通过。

### 007 llm-gateway-resilience（chat-api）
- `app/llm/resilience/pricing.py`（008 同源 MODEL_PRICES）+ `metering.py`（聚合 T020）；`instrumented_client.py` 成本估算 + 韧性事件；`token_usage/models.py` 新增 cost/resilience 字段。
- 测试：`tests/llm/test_resilience_metering.py` 14 项；`specs/007` T015–T025 全勾选。

### 008 ops-dashboard
- `app/api/dashboard_usage.py`（T014/T015 调用时序 + 去重 + Skill/检索频次）；`routes/dashboard.py` 新增 `_usage_tab` + overview 返回 `usage`；`dashboard_metrics.py` 新增 `empty_quality_section`/`empty_trend_section`（T025 兜底）。
- 前端 `apps/admin-web/src/views/dashboard/DashboardPage.vue` 四维标签页（总览/成本/使用/质量/趋势）；`dashboardText.ts` 翻译补全。
- 测试：`tests/test_dashboard_selfcheck.py`（T024 租户隔离 / T025 空态 / T026 成本对账）10 项；admin-web `pnpm build` 通过。

### 002 session-versioning（P1）
- `co_presence.py`（US5 在线态 + 线性合并）、`share.py`（US4 短时效 token + 可见范围 + 失效空态）、`audit.py`（T021 会话事件进 001 落点）。
- 测试：`tests/services/test_session_us5_and_polish.py` 8 项；quickstart + `contracts/session-versioning-contract.md`。

### 009 hooks-interception
- `integration.py`（T009 挂 PreToolUse + T011 钩子审计）、`lifecycle.py`（T013 四事件）、`store.py`（T015-T016 CRUD + 三级作用域）、`guard.py`（T017 fail_closed + T018 延迟预算 ≤5s）。
- admin-api `app/api/routes/hooks.py`（hook_rules CRUD + 作用域查询，挂 `/api/hooks`）。
- 测试：`tests/test_hooks_009.py` 17 项；更新 quickstart。

### 010 dag-orchestration-engine
- `app/services/dag/skip.py`（T013-T015 条件跳过 + T014 跳过追溯，基于 `app/orchestration` 的 Node/Graph + conditions）、`retry.py`（T016-T017 指数退避 + 分层不重复）、`builder_migrate.py`（T018 双轨迁移 + T019 等价回归）。
- 测试：`tests/services/test_dag_skip_retry.py` 14 项 + `test_dag_migrate_polish.py` 11 项；quickstart + `contracts/orchestration.md`。

### 011 dream-cycle-self-evolution
- `dream_cycle/runner.py`（T001-T008）、`friction.py`（T005-T006）、`mr.py`（T011-T012）、`deprecation.py`（T014-T015 与 016 共用 `marked_low_quality`）、`evolution_audit.py`（T017 全链路审计 + T018 可配置）。
- 测试：`test_dream_cycle.py` 12 + `test_dream_evolution.py` 13 + `test_dream_audit_config.py` 7；quickstart + `contracts/self-evolution.md`。

### 012 a2a-agent-gateway
- `app/a2a/client.py`（T009 出站客户端：30s 超时 + failover + 复用 007 退避；治理拒绝 `-32000` 不重试不 failover，立即透出错误码）。
- 测试：`tests/test_a2a_client_012.py` 7 项（US2 出站调用 + 错误码映射 + failover + 拒绝短路）；`quickstart.md` + `contracts/a2a-gateway.md`（JSON-RPC 方法/错误码映射/超时与 failover 契约）。

### 013/014/015/016/017/018/019
- 014 `business_semantic_index.py`（T007 复用 005 检索客户端 + 引用锚点）。
- 017 `memory/retrieval.py`（T010-T011 记忆进 RAG 按 scope 过滤 + 升级/衰减/检索）。
- 018 `capability_assets.py`（T012 视图 + 状态 + a2a_exposed 标记）。
- T999 审计：`im_gateway/audit.py` + `services/feature_audit.py`（014/015/016/017/018 事件进 001 落点）。
- T998 文档：013/014/015/016/017/018 quickstart + `contracts/harness-config.md`。
- 测试：`test_014_017_semantic_memory.py` 12 + `test_capability_asset_us2.py` 7 + `test_t999_audit_t998_docs.py` 7。

### 验证
- chat-api：`tests/services/ + tests/test_hooks_009.py + tests/test_a2a_client_012.py + tests/llm/` **313 项通过**（仅 `tests/llm/test_decision_turn.py` 收集错误为预存问题——`_DecisionSchema` 不在 planner 中，与本轮改动无关，已 `--ignore` 跳过）。
- admin-api：全量 **236 项通过**。
- admin-web：`pnpm build` 通过（含四维标签页）。
- 勾选 `specs/001/002/007/008/009/010/011/012/013/014/015/016/017/018/019` tasks.md 全部未勾项（各特性 remaining=[]）。

## 2026-07-08 深化 007 降级链 + 015 一致性约束 + 014 跨系统对齐

- **007 `resilience/degradation.py`**（T011–T014）：模型降级链——`build_chain`（**高性能→中档→轻量**，可配 models，FR-8）+ `run_with_degradation`（可重试失败逐档降级并**发降级事件**，401/403 立即中止，**链耗尽抛 `DegradationError` 明确报错不静默**，FR-2）+ 降级原因枚举（429/5xx/timeout）
- **015 `knowledge_graph/consistency.py`**（T008–T010）：一致性约束三类——
  - **互斥**（同实体属性冲突值）+ **传递**（A→B→C 缺 A→C 报告 gap）+ **基数**（关系端点数量上下界）
  - `ConstraintBundle` + `check_all` + `mark_conflicts`（**标记但仍可查询，不阻断**，FR-14）
- **014 `business_index/alignment.py`**（T009–T011）：跨系统对齐——`align_entities`（按 实体类型+业务键 分组，同键跨系统成组，**无键标记 unaligned**，FR-6）+ `missing_systems`（缺口系统）+ `join_cross_system`（**跨系统联查带 missingSystems 标注，不拒绝**，FR-5）
- **测试**：resilience 新增 7 项（18→25）、knowledge_graph 新增 8 项（17→25）、business_index 新增 5 项（17→22），全部通过。
- 勾选 `specs/007/tasks.md` T011–T014、`specs/015/tasks.md` T008–T010、`specs/014/tasks.md` T009–T011。
- 提交并推送 cooper2006/mogong（origin push 仍锁 no-push，未触碰 himovo）。

## 2026-07-08 深化 019 门禁链对接 + 013 渠道路由

- **019 `harness_config/gate_adapter.py`**（T014）：厚度 profile → 001 门禁链映射——`GatePlan`（模式/层集合/后端/审计粒度/跳过层）+ `build_gate_plan`（**底线守护拒绝违规薄化**）+ `backend_for`（**过渡期挂 transition（approval_runtime/audit），001 就绪后切 gatekeeper**，clarify OQ-3）+ `describe_plan`（审计可序列化）
- **013 `im_gateway/router.py`**（T010）：统一渠道路由——`ChannelRouter`（注册/惰性构建 adapter + 路由解析）+ **渠道停用拒绝新消息且已有绑定置只读**（FR-9）+ 未知/未实现渠道明确报错 + 启用后恢复
- **测试**：`tests/harness_config/test_harness_config.py` 新增 7 项 + `tests/im_gateway/test_im_gateway.py` 新增 6 项，全部通过。
- 勾选 `specs/019/tasks.md` T014、`specs/013/tasks.md` T010。
- 提交并推送 cooper2006/mogong（origin push 仍锁 no-push，未触碰 himovo）。

## 2026-07-08 深化 010 supervisor/hybrid + registry，011 draft_gen

- **010 `orchestration/supervisor.py`**（T011/T012）：`Supervisor` 监督模式——分派子节点（并发上限）+ 聚合结果 + **失败传播**（监督自身失败→整体失败；子节点失败率 ≥ 阈值（默认 100%=全失败）→ 监督失败；可配阈值）+ `run_hybrid`（顺序前缀 + 并行阶段，前缀输出传并行）
- **010 `orchestration/registry.py`**（T003）：编排定义声明式管理——`OrchestrationDefinition`（声明式节点/边/条件/重试 + **版本字段**）+ `to_graph()` 物化 + `validate()`（**定义期 fail-closed**：悬空边/非法条件拒绝，变量条件放行）+ `update()`（**版本递增 + 归档旧版**）+ `OrchestrationRegistry`（注册/查询/版本历史）
- **011 `self_evolution/draft_gen.py`**（T008/T010）：Skill 草稿生成——`SkillDraft`（**draft 中间态，永不直接发布**）+ `build_test_samples`（从片段派生可执行样例）+ **生成侧质量门槛**（需测试样例 + 预览运行通过，否则不产草稿，FR-13）+ `generate_draft`
- **测试**：`tests/orchestration/test_supervisor.py`（17 项）+ `tests/self_evolution/test_self_evolution.py` 新增 6 项，全部通过。
- 勾选 `specs/010/tasks.md` T003/T011/T012、`specs/011/tasks.md` T008/T010。
- 提交并推送 cooper2006/mogong（origin push 仍锁 no-push，未触碰 himovo）。

## 2026-07-08 深化 009 钩子注册表 + 011 周期扫描

- **009 `hooks/registry.py`**（T003）：五事件注册表——`HookRegistry`（**首期仅 PreToolUse 启用**，其余注册为目标态，clarify OQ-3）+ `enable`/`disable`（**PreToolUse 不可禁用**，合规拦截点）+ 会话生命周期事件（SessionStart/End/MemoryCommit）与 002 桥接 + 未知事件拒绝
- **011 `self_evolution/scanner.py`**（T007/T009）：周期扫描——
  - `scan_fragments`：按场景相似度聚类 + **平均 pairwise Jaccard 打分** + 高置信判定（Jaccard≥0.7 且样本≥5）
  - `ScanConfig`（扫描频率 once/daily/weekly 复用 scheduled_tasks、阈值、**草稿堆积上限 100**，FR-8/FR-12）
  - `should_generate_draft`（**所有模式都产草稿，仅 MR 受置信门控**）+ `dedupe_drafts`（**同片段保留最高置信**）+ `scan_summary`（审计摘要）
- **测试**：`tests/dsh_runtime/test_hooks.py` 新增 6 项 + `tests/self_evolution/test_self_evolution.py` 新增 6 项，全部通过。
- 勾选 `specs/009/tasks.md` T003、`specs/011/tasks.md` T007/T009。
- 提交并推送 cooper2006/mogong（origin push 仍锁 no-push，未触碰 himovo）。

## 2026-07-08 深化 008 成本看板聚合（US2 / T010–T012）

- **`dashboard_metrics.py` 新增成本维度**：
  - `build_cost_section`：Token 总量（输入/输出分离）+ 各模型成本 + 成本占比（按成本降序）+ 合计
  - `reconciles`：**对账校验（模型成本合计 = 总量，容差 0.01，FR-6）**，空租户也对账通过
  - `attribute_cost`：**按任意维度分摊**（部门/智能体，FR-2），无值归"未分配"
  - `forecast_cost`：**近 N 期移动平均预测**（默认 4 期，clarify OQ-5），空历史返回 None
- **测试**：`tests/test_dashboard_metrics.py` 新增 6 项（合计/对账 0 差异/空租户对账/维度分摊/预测/空历史），全部通过。
- 勾选 `specs/008-ops-dashboard/tasks.md` T010–T012。
- 提交并推送 cooper2006/mogong（origin push 仍锁 no-push，未触碰 himovo）。

## 2026-07-08 深化 010 DAG 执行器 + 002 快照存储

- **010 `orchestration/engine.py`**（T006–T010）：`DagEngine` graph 模式执行器——
  - **拓扑调度 + 并发度上限**（默认 4，超限排队不拒绝，FR-2）
  - **节点失败阻塞全传递下游闭包**并标记 `blocked`（区别于 `failed`，FR-6）
  - 条件跳过（含**语法错误 fail_closed 跳过 + 原因记录**，FR-4）
  - **执行事件审计**（started/completed/failed/skipped/blocked，FR-7）
  - `run_sequential`（顺序模式）+ 上游输出写共享上下文供下游读取
- **002 `session_versioning/snapshot.py` + `store.py`**（T002/T007–T012）：
  - `SessionSnapshot`（seq/trigger/actor/summary/changed_refs/**附件指针**，clarify OQ-1）+ `CommitPolicy`（**idle 超时/关键工具/分享自动提交**，可配）+ `build_snapshot`（摘要派生）
  - `SnapshotStore`：commit（自动分配 id）/ `log`（按 seq 时间线，FR-2）/ `latest` / `preview`（摘要预览）/ **`resume_point`（从目标快照后续编，永不重置为 1，FR-3）**
- **测试**：`tests/orchestration/test_engine.py`（12 项）+ `tests/services/test_session_snapshots.py`（22 项），全部通过。含并发度上界、阻塞闭包、条件 fail-closed、resume 不重置、附件指针等关键断言。
- 勾选 `specs/010/tasks.md` T006–T010、`specs/002/tasks.md` T002/T007–T012。
- 提交并推送 cooper2006/mogong（origin push 仍锁 no-push，未触碰 himovo）。

## 2026-07-08 实现 P2 特性 016（Skill 市场强化）核心 —— P2 全覆盖

- **016 Skill 市场强化** → `services/admin-api/app/services/skill_market/`：
  - `scoring.py`：**效果分 = 成功率 0.5 + 采纳率 0.3 + 纠正率反向 0.2**（权重可配，clarify OQ-1）+ 空样本 0 分不报错 + **低质量判定（<0.4 且持续 ≥7 天，clarify OQ-4）** + 共用标记位常量 `marked_low_quality`（与 011 一致）
  - `canary.py`：灰度 rollout（**首期按租户**，clarify OQ-2）+ **异常率 >20% 自动回滚**（可配，clarify OQ-3）+ **最小样本门槛 20**（小样本不判定，FR-10）+ 回滚目标 = 上一稳定版本 + `apply_rollback` 审计记录
- **测试**：`tests/test_skill_market.py`（17 项）：权重常量、满分/零分/混合打分、空样本、权重可配、低质量双条件、canary 阈值常量、计入调用、非法计数、阈值内不回滚、超阈值回滚、样本不足不判定、回滚目标与审计、无需回滚 noop。全部通过。
- 勾选 `specs/016-skill-market-hardening/tasks.md` T001–T011。
- **P2（012–019）全部特性核心实现完成**；更新 `specs/INDEX.md` 实现进度行。
- 提交并推送 cooper2006/mogong（origin push 仍锁 no-push，未触碰 himovo）。

## 2026-07-08 实现 P2 特性 013（多 IM 入口）+ 018（能力资产化）核心

- **013 多 IM 入口** → `services/chat-api/app/im_gateway/`：
  - `adapter_base.py`：渠道适配基类 + **飞书 adapter**（首期渠道，clarify OQ-1；解析 `content` JSON 文本、群/单聊）+ `chunk_text`（**长响应纯文本分段**，非流式，FR-2）+ `build_adapter`（未实现渠道明确报错）
  - `bindings.py`：`ImSessionBinding` **1:1 映射**（IM 会话 ↔ MOVO 会话，FR-2）+ `SessionBindingRegistry`（**1 MOVO 会话仅可绑 1 IM 渠道**，先绑者为准，FR-14；**停用渠道 → 已有绑定置只读**，FR-9）+ `resolve_group_sender`（群内 @bot 发起者 → MOVO 用户，未绑定拒绝，FR-10）
  - `webhook.py`：**HMAC-SHA256 签名**（nonce.timestamp.body，常数时间比较）+ **nonce 去重 5 分钟防重放** + 时间戳窗口校验（FR-13）
- **018 能力资产化** → `services/admin-api/app/services/capability_assets/`：
  - `contract.py`：**契约四段 schema**（input/output/errors/sla，JSON 声明式，clarify OQ-1）+ `normalize_contract`（缺失段补空）+ `contract_diff`（变更审计用）
  - `registry.py`：`CapabilityAsset`（版本/owner/状态/`a2a_exposed`）+ **契约变更版本递增并归档旧版**（FR-5）+ 状态管理（active/deprecated/**offline 需全能力管理员审批**，FR-6）+ owner 转移（FR-11）+ `discover_assets`（**自动扫描 REST/MCP**，非标准标 `manual_required`，**按 端点+方法 去重**，FR-2/FR-10）
- **测试**：`tests/im_gateway/test_im_gateway.py`（26 项）+ `tests/test_capability_assets.py`（20 项），全部通过。
- **修复一个缺陷**：`CapabilityAsset.name` 无默认值与构造用法不符（`TypeError: missing 'name'`）→ 给默认空串。
- 勾选 `specs/013/tasks.md` T001–T009、`specs/018/tasks.md` T001–T011。
- **P2 除 016 外全部有核心实现**（012/013/014/015/017/018/019）。
- 提交并推送 cooper2006/mogong（origin push 仍锁 no-push，未触碰 himovo）。

## 2026-07-08 实现 P2 特性 014（业务语义索引）核心

- **014 业务语义索引** → `services/chat-api/app/business_index/`：
  - `entities.py`：业务实体（客户/订单/供应商/账目，4 类，clarify OQ-2）+ **三级来源定位**（系统/类型/记录 ID，FR-3）+ 对齐键（各类型业务主键）+ `align_pair`（**对齐失败标记 unaligned 而非拒绝联查**，FR-6）
  - `sources.py`：数据源规格（**强制只读**——不写业务库）+ 定时拉取（once/daily/weekly，**不做 CDC**，clarify OQ-3）+ `is_source_unavailable`/`build_unavailable_notice`（**数据源不可用明确标注，不用陈旧数据冒充**，FR-11）+ `mask_pii_fields`（mask/hash/remove，**索引前脱敏**，FR-10）
- **测试**：`tests/business_index/test_business_index.py`（17 项）：实体类型/对齐键/来源三级/对齐（匹配/不匹配/异类型）、源只读约束/间隔校验/默认日拉、不可用标注、PII mask/hash 确定性/remove。全部通过。
- 勾选 `specs/014-business-semantic-index/tasks.md` T001–T006/T008。
- **P2 已实现核心：012 / 014 / 015 / 017 / 019**（013/016/018 待后续）。
- 提交并推送 cooper2006/mogong（origin push 仍锁 no-push，未触碰 himovo）。

## 2026-07-08 实现 P2 特性 017（三范围记忆）核心

- **017 三范围记忆** → `services/chat-api/app/memory/`：
  - `scope.py`：三级范围（personal/workspace/org）+ 可见性（owner/members/organization）+ `resolve_default_scope`（**单人会话→personal，多人→workspace**，clarify OQ-1）+ `visible_to`（按 scope 隔离，全能力管理员可读全部，**无越权**）+ `promote_to_org`（**仅全能力管理员可授权提升**，否则 `MemoryAccessError`，FR-4）
  - `lifecycle.py`：衰减策略（**默认 30 天**，`touch` 访问重置计时，clarify OQ-2）+ `is_expired`/`seconds_until_expiry`（剩余存活时间）+ 清理方式（archive 默认，可配 delete）
- **测试**：`tests/memory/test_memory.py`（16 项）：默认范围（单/多人）、未知 scope 拒绝、三级可见性隔离、全能力管理员越权可见、提升授权门槛、衰减窗口边界、访问重置、清理默认。全部通过。
- 勾选 `specs/017-three-scope-memory/tasks.md` T001–T009。
- **P2 已实现核心：012 / 015 / 017 / 019**（013/014/016/018 待后续）。
- 提交并推送 cooper2006/mogong（origin push 仍锁 no-push，未触碰 himovo）。

## 2026-07-08 实现 P2 特性 012（A2A 网关）+ 015（知识图谱）核心

- **012 A2A 网关** → `services/chat-api/app/a2a/`：
  - `agent_card.py`：AgentCard 模型（A2A 标准字段 + `skills[]`，必含校验）+ `build_agent_card`（**仅 `a2a_exposed` 才生成**，FR-12）+ `parse_agent_card`（Dify 字段映射 + 容错未知 auth scheme）+ URL 结构 `/a2a/{tenant}/{agent_id}`
  - `protocol.py`：JSON-RPC 方法（`message/send`/`tasks/get`/`tasks/result`）+ 请求校验（jsonrpc 版本/未知方法/params）+ `TaskLifecycle`（**task id 幂等**，重复提交不重跑）+ 错误码（含 `movo_denied` -32000）+ `rpc_error_from_denial`（001 拒绝 → JSON-RPC error，FR-7）
- **015 知识图谱** → `services/chat-api/app/knowledge_graph/`：
  - `schema.py`：节点/边模型（实体 人/组织/产品/事件，关系 隶属/负责/引用/关联）+ 校验（空 id、自关系、未知类型）+ 置信门槛
  - `store.py`：邻接存储 + **合并策略**（同实体属性合并不覆盖，冲突保留多值并标 `conflicted`，FR-3）+ 低置信不入图（FR-12）
  - `query.py`：多跳遍历（**跳数上限默认 3**）+ `CycleGuard` 防环（环记录不延伸，FR-11）+ 断裂在第几跳标注（FR-5）+ 关系过滤
- **测试**：`tests/a2a/test_a2a.py`（24 项）+ `tests/knowledge_graph/test_knowledge_graph.py`（17 项），全部通过。
- 勾选 `specs/012/tasks.md` T001–T008、`specs/015/tasks.md` T001–T007。
- 提交并推送 cooper2006/mogong（origin push 仍锁 no-push，未触碰 himovo）。

## 2026-07-08 补齐 P2 tasks（012–019）+ 实现 019 厚薄配置核心（13/15）

- **生成 P2 八份 `tasks.md`**（012–019）：补齐 012/013/014/015/016/017/018 缺失的 tasks（019 单独精写）。至此 **tasks 层 19/19 全覆盖**。每份含 clarify 决策、checklist 门禁、Phase 结构、MVP 范围。
- **实现 `services/chat-api/app/harness_config/`（019）**（依赖轻，可脱离 DB 单测）：
  - `layer_switch.py`：六层规范序 + 可省层（approval/quota）+ 必需层（identity/rbac/redaction/audit）；`resolve_layers` 厚=全六层、薄=省审批+配额、显式列表按规范序
  - `floor.py`：底线守护——禁用必需层/关审计 → `FloorViolation`；R4 任意模式 deny；薄模式最小审计四元组 + `audit_covers_floor` 校验（FR-5/6/8）
  - `profile.py`：厚度 profile（scope+mode+启用层+审计粒度+超时）+ `ProfileResolver` **维度优先级 场景>租户>工具**、未配置回退**默认厚模式**（FR-3/FR-8 + clarify OQ-1/OQ-5）
- **测试**：新增 `services/chat-api/tests/harness_config/test_harness_config.py`，**18 项全部通过**：厚/薄层集合、可省层集合、显式列表排序、底线守护（必需层/审计）、R4 全模式 deny、最小审计四元组与校验、默认厚、三维优先级、逐调用切换、非法薄化拒绝、审计粒度。
- 勾选 `specs/019-harness-elastic-config/tasks.md` 的 T001–T013（13/15）。
- 更新 `specs/INDEX.md`：tasks 行 → 19/19；新增"实现进度"行。
- 提交并推送 cooper2006/mogong（origin push 仍锁 no-push，未触碰 himovo）。

## 2026-07-08 实现 011 Dream Cycle 自进化核心（tasks T001–T004）

- **新增 `services/chat-api/app/self_evolution/`**（依赖轻，可脱离 DB/运行时单测）：
  - `fragment.py`：经验片段模型（场景特征/动作序列/结果/时间戳/来源会话 ID/用户反馈，FR-2）+ 内存 `FragmentStore`（按租户隔离）
  - `friction.py`：friction 检测——**默认自动捕获**"失败后成功（重试≥1）"与"人工纠正"，"用户显式标记"**仅主动触发**；优先级 显式标记 > 人工纠正 > 失败后成功（clarify OQ-1）
  - `similarity.py`：**Jaccard**（场景 token 集合，归一化大小写/空白）+ **Levenshtein 编辑距离**（动作序列）+ `is_high_confidence`（Jaccard ≥0.7 且样本 ≥5，clarify OQ-3）+ 贪心 `cluster_by_similarity`（首期不引入向量库）
- **测试**：新增 `services/chat-api/tests/self_evolution/test_self_evolution.py`，**22 项全部通过**：三类 friction 捕获与优先级、自动捕获集合、批量检测、Jaccard（相同/部分/归一化/空）、编辑距离（相同/替换/增删）、归一化相似度边界、高置信阈值、默认常量、聚类分组、片段 store（id/租户隔离/document 字段）。
- 勾选 `specs/011-dream-cycle-self-evolution/tasks.md` 的 T001–T004；T005+（捕获接入/扫描/草稿/MR/淘汰）待后续。
- **P1 全部特性（002/009/010/011）核心已落地**。
- 提交并推送 cooper2006/mogong（origin push 仍锁 no-push，未触碰 himovo）。

## 2026-07-08 实现 010 通用 DAG 引擎核心（tasks T001/T002/T004/T005）

- **新增 `services/chat-api/app/orchestration/`**（依赖轻，可脱离 DB/运行时单测）：
  - `graph.py`：DAG 节点/边模型——节点含 mode/条件/重试配置；校验（空 id、重复节点、边引用不存在、自环）；`downstream_closure`（**传递下游闭包**，用于失败阻塞 FR-6）；`roots`
  - `topo.py`：Kahn 拓扑排序（确定性 tie-break）+ DFS 环检测，**环以节点 ID 序列报出**（`A -> B -> C -> A`，FR-3）
  - `conditions.py`：受限 JSON 条件对象求值——算子 `== != > >= < <= in has` + `and/or/not`，支持 `{"var": "path"}` 引用**嵌套上下文**；**禁用任意代码**（未知算子直接 fail-closed）；语法/取值错误抛 `ConditionError`（FR-4 + clarify OQ-1/OQ-5）
- **发现并修复一个缺陷**：`_resolve` 把无 `op` 的**字面量字典**（如 `{"k": 1}`）误判为非法 operand 而抛错；改为无 `var`/`op` 的字典按字面量返回。
- **测试**：新增 `services/chat-api/tests/orchestration/test_orchestration.py`，**23 项全部通过**：图校验/闭包/roots、拓扑顺序/确定性、二节点与三节点环检测（含环路径）、条件等值/序关系/in/has/嵌套 var/逻辑运算/未知算子/缺操作数/非列表 operands/禁代码注入。
- 勾选 `specs/010-dag-orchestration-engine/tasks.md` 的 T001/T002/T004/T005；T003（registry）/T006（执行器）/T007-T022 待后续。
- 提交并推送 cooper2006/mogong（origin push 仍锁 no-push，未触碰 himovo）。

## 2026-07-08 实现 009 五事件钩子 PreToolUse 核心（tasks T001/T002/T004–T008）

- **新增 `services/chat-api/app/dsh_runtime/hooks/`**（依赖轻，可脱离 DB 单测）：
  - `rules.py`：声明式规则 schema（`hook_rules{scope∈tool/session/tenant, rule_type∈deny_tool/require_field/observe, rule_config, enabled}`）+ 解析；**解析失败 fail-closed**（未知 scope/rule_type、缺字段、非对象均抛 `RuleParseError`）；作用域优先级 tool>session>tenant
  - `timeout.py`：超时保护（默认 5s，`hook_timeout_seconds` 可配）+ `HookTimeout`；**fail_closed 不可配放行**；共享延迟预算（FR-13）
  - `engine.py`：PreToolUse 规则求值——先按作用域再按类型排序，**deny 短路优先于 require**，require_field 缺字段拒绝，observe 仅记录；malformed 规则 fail_closed；拒绝返回 403（与门禁拒绝区分）
- **测试**：新增 `services/chat-api/tests/dsh_runtime/test_hooks.py`，**20 项全部通过**：规则解析（合法/未知 scope/未知类型/缺字段/非对象/禁用跳过）、排序、deny 拦截/仅匹配目标工具、require_field 缺/有字段、observe 不拦截、deny 短路优先、malformed fail-closed、超时（默认 5s/正常/超时抛出/预算）。
- **测试基建**：新增 `services/chat-api/tests/conftest.py`——**仅当 motor 不可用时**注入 stub（正常环境 no-op）；另在 DSH runtime 包 init 无法导入时将其降级为命名空间包（保留 `__path__`），使 hooks 纯逻辑测试可独立运行。
- 勾选 `specs/009-hooks-interception/tasks.md` 的 T001/T002/T004–T008；T003（registry）/T009（integration 挂载 turn_admission）/T010+ 待后续。
- 提交并推送 cooper2006/mogong（origin push 仍锁 no-push，未触碰 himovo）。

## 2026-07-08 实现 002 会话版本化核心纯逻辑（tasks T001/T004/T005/T006）

- **新增 `services/chat-api/app/services/session_versioning/`**（依赖轻，可脱离 DB 单测）：
  - `secrets.py`：低熵秘密识别——Shannon 熵 ≥3.5 bits/char **且** 长度 ≥16，叠加凭证前缀（`sk-`/`ghp_`/`AKIA`/`Bearer `）双判定；白名单 + 手动标记抑制误报（FR-7/FR-10）
  - `placeholder.py`：可逆占位符 `{{secret:<id>}}`——替换/还原，**仅 owner / full_access_admin 可解引用**，解引用落审计（FR-7/FR-8）
  - `timeline.py`：线性时间线约束（seq 单调、append 拒绝分叉、resume 从快照后续编不重置）+ **MongoDB 乐观锁冲突检测**（`check_and_advance`，重试耗尽 fail-closed）+ 线性合并去重（FR-3/FR-4/FR-6）
- **发现并修复一个缺陷**：`detect_secrets` 的 prefix 匹配与 generic 高熵候选**不共享去重**（span 不一致），同一 token 被重复上报且标签错乱（`low_entropy` 覆盖 `openai_key`）。改为**重叠检测**（generic 候选与已匹配凭证区域重叠则跳过）。
- **测试**：新增 `services/chat-api/tests/services/test_session_versioning.py`，**23 项全部通过**：熵计算/长度门槛/三类前缀/低熵文档 ID 不误报/白名单/手动标记/占位符可逆/解引用权限/审计/时间线单调/resume 不分叉/乐观锁冲突与 fail-closed/线性合并。
- 勾选 `specs/002-session-versioning/tasks.md` 的 T001/T004/T005/T006（核心纯逻辑）；T002/T003/T007-T022（快照存储、端点接入、share/co-presence）待后续。
- 提交并推送 cooper2006/mogong（origin push 仍锁 no-push，未触碰 himovo）。

## 2026-07-08 实现 008 运营驾驶舱后端 MVP（tasks T001/T002/T004–T007/T009）

- **新增 `services/admin-api/app/api/dashboard_metrics.py`**：四维看板共享聚合辅助（纯逻辑，可脱离 DB 单测）——
  - 租户隔离 `tenant_match`（FR-7）+ UTC 时间窗口 `window_start`/`previous_window`（FR-3）
  - 质量维度 `build_quality_section`（成功率/异常率/人工介入率/P50/P95，空租户返回 None 不报错，FR-9）
  - 趋势维度 `build_trend_section`（环比/同比 delta）+ `bottleneck_top_n`（成本/时长排序 top-5，标注维度）
  - `percentile_stage`/`extract_percentiles`：**从 `start_time`/`end_time`（epoch ms）内联计算 duration** 再取 $percentile（`token_usage_logs` 无 duration_ms 字段）
- **扩展 `services/admin-api/app/api/routes/dashboard.py`**：
  - 新增 `_quality_metrics`（US4/FR-4）：成功率 + 异常率（failed+timeout+error 合并）+ P50/P95 + 平均时长；`$percentile` 不可用时降级为仅平均
  - 新增 `_approval_pending_count`：审批挂起数（无持久审批集合时优雅降级为 0）
  - 新增 `_trend_metrics`（US5/FR-5）：环比/同比 + 瓶颈 top-5（按模型聚合，成本/时长排序）
  - `/overview` 接入 `quality` + `trend` 两节（原有 billing/metrics/assets/todos/recentActivity 保留）
- **测试**：
  - `tests/test_dashboard_metrics.py`（18 项）：租户隔离/UTC 窗口/rate 空值/质量节/趋势 delta/瓶颈排序/百分位提取
  - `tests/test_dashboard_routes.py`（6 项）：质量聚合（空租户/计算/租户作用域）、趋势聚合（空值/瓶颈排序）、审批降级
  - `tests/conftest.py`：**仅当 motor 不可用时**注入 stub（正常环境 no-op），使纯逻辑测试可在不支持 motor 的解释器上运行
- **验证**：admin-api 52 项 + chat-api 18 项 = **70 项测试全部通过**。
- 勾选 `specs/008-ops-dashboard/tasks.md` 的 T001/T002/T004–T007/T009（后端 MVP）；T003/T008（前端 Vue）与 T010–T027 待后续。
- 提交并推送 cooper2006/mogong（origin push 仍锁 no-push，未触碰 himovo）。

## 2026-07-08 实现 007 LLM 网关韧性 failover MVP（tasks T001–T010）

- **新增 `services/chat-api/app/llm/resilience/` 模块**（007 US1 failover + 退避）：
  - `errors.py`：错误分类——可重试（429/5xx/408/timeout/连接错误）vs 不可重试（401/403 立即失败）；`AllProvidersFailedError` 携带各供应商失败原因（FR-10）
  - `events.py`：韧性事件落 `token_usage_logs` **附加字段**（`failover_from`/`failover_to`/`degradation_step`/`degradation_reason`），不新增 collection；降级原因枚举（429/5xx/timeout/manual）
  - `retry.py`：tenacity 指数退避 + 抖动原语（默认基数 1.5s/上限 30s/±10%/3 次，**沿用既有 `azure_gpt_image` 值**）；401/403 不重试
  - `failover.py`：`ResilientLLMClient`（实现 `BaseLLMClient`）主/备供应商调度——可重试错误切备、不可重试立即抛、全失败聚合错误；**单供应商严格 no-op**（FR-9 向兼容）；流式 failover 仅在首块失败时切换（避免重复输出）
  - `providers.py`：从声明式 `app/config/resilience.yaml` 构建 provider 列表；**配置缺失/无 providers 时回退单供应商 = 现状行为**（FR-8/FR-9）
- **新增配置模板** `services/chat-api/app/config/resilience.yaml`（provider 顺序注释示例 + retry 默认值），默认不启用多供应商。
- **测试**：新增 `services/chat-api/tests/llm/test_resilience.py`，**18 项全部通过**：错误分类（可/不可重试）、事件字段、降级原因枚举、failover 切备、单供应商 no-op、全失败聚合、**401 不 failover**、退避重试成功/不重试 auth/耗尽重抛、provider 配置解析与回退。
  - 运行：`PYTHONPATH=. <venv>/bin/python -m pytest tests/llm/test_resilience.py -o asyncio_mode=auto`
- **可测试性设计**：resilience 模块不顶层依赖 `llm.factory`/motor（延迟 import），使其可独立单测。
- 勾选 `specs/007-llm-gateway-resilience/tasks.md` 的 T001–T010（MVP 范围）。
- 提交并推送 cooper2006/mogong（origin push 仍锁 no-push，未触碰 himovo）。

## 2026-07-08 实现 001 gatekeeper MVP（tasks T001–T014，六层链骨架跑通）

- **新增 `services/admin-api/app/governance/` 模块**（001 六层门禁的依赖底座）：
  - `gatekeeper.py`：`GateContext` / `GateVerdict` 数据类 + `Gatekeeper.evaluate` 六层串行编排 + 短路 + 审计落点；`GateLayer` 协议
  - `config.py`：声明式配置（层增删/顺序/审计开关，默认厚模式 + 显式降级）+ 必需层守护（禁用 identity/rbac/redaction/audit 或关审计 → 报错）
  - `rbac_model.py`：权限码 `<resource>:<action>[:<target>]` 解析 + 岗位角色预设组 `expand_role_to_codes`（对接 006 `system_key`/`capabilities`）+ `has_permission`（wildcard/资源通配/目标匹配，未知码 fail-closed）
  - `schema.py`：6 个集合建索引 + 种子（gate_config / 25 格矩阵 / 默认 PII 策略）
  - `layers/`：identity（层1，主体解析）/ rbac（层2，权限码判定）/ redaction·approval·quota（US3/2/5 的 pass-through 占位）/ audit（层6，落 `gate_events`）
- **接入工具调用入口** `app/api/routes/tools.py`：新增 `_enforce_gate`，在 `/{tool_id}/test` 与 `/test-draft` 执行前过门禁；被拒按层映射 HTTP 码（403/409/429）；`ensure_indexes` 挂接 governance 建表。
- **发现并修复一个真实缺陷**：`Gatekeeper.evaluate` 原先把 audit 层放在链尾并 `continue`，导致**中途拒绝（如 RBAC 拒绝）时 `audit_layer` 仍为 None，拒绝事件不落审计** —— 违反 FR-9。已改为**先把 audit 层从链中分离**再跑其余层，确保通过/拒绝事件都落库。
- **可测试性设计**：governance 纯逻辑模块（config/rbac_model/gatekeeper）**不顶层依赖 motor**（DB 访问一律延迟 import），使单测无需 DB 驱动。
- **测试**：新增 3 个测试文件共 **28 项全部通过**（rbac_model 12、config 9、gatekeeper 5 + 参数化）：
  - `tests/test_governance_rbac_model.py`、`tests/test_governance_config.py`、`tests/test_governance_gatekeeper.py`
  - 运行方式（本机无 Python 3.10，用临时 venv）：`PYTHONPATH=. <venv>/bin/python -m pytest tests/test_governance_*.py -o asyncio_mode=auto`
- 勾选 `specs/001-gatekeeper-governance/tasks.md` 的 T001–T014（MVP 范围）。
- **环境说明**：本机仅有 Python 3.14，而仓库 `motor==2.5.1` 与 3.14 不兼容（`from asyncio import coroutine` 已移除）——既有测试在本机亦无法收集，属**环境限制**非本次改动引入；governance 新测试因不依赖 motor 故可正常跑。
- 提交并推送 cooper2006/mogong（origin push 仍锁 no-push，未触碰 himovo）。

## 2026-07-08 生成 P1 缺口特性 002/009/010/011 的 tasks.md（P0+P1 tasks 层齐备）

- 按 `/speckit-tasks` 语义生成 4 份 tasks.md，落点经**实际代码结构核实**（非 plan 假设）：
  - **002 session-versioning**（22 任务）：落 `chat-api/app/services/session_versioning/` + `api/endpoints/sessions.py`。Phase1 骨架 → Phase2 时间线/秘密/占位符/存储 → US1 commit/log → US2 resume → US3 乐观锁并发 → US4 share → US5 co-presence → Polish。含 clarify（独立 `session_snapshots`、熵≥3.5+前缀、不引入 Redis、share 短时效 token）。
  - **009 hooks-interception**（19 任务）：落 `chat-api/app/dsh_runtime/hooks/`，挂载 `turn_admission.admit_skill_selection`。Phase1 骨架/规则 schema → Phase2 超时+fail_closed+求值核心 → US1 PreToolUse 三规则 → US2 审计 → US3 会话事件 → US4 规则管理 → Polish。含 clarify（超时 5s、fail_closed 不可配、首期仅 PreToolUse、hook_rules schema）。
  - **010 dag-orchestration**（22 任务）：落 `chat-api/app/orchestration/`。Phase1 骨架/图模型 → Phase2 拓扑+条件 → US1 graph 并行 → US2 四模式 → US3 条件跳过 → US4 节点重试 → US5 内容规划迁移 → Polish。含 clarify（JSON 条件对象、并发度 4、重试分层、双轨迁移、语法错误 fail_closed）。
  - **011 dream-cycle**（19 任务）：落 `chat-api/app/self_evolution/`。Phase1 骨架/片段模型 → Phase2 friction/相似度 → US1 捕获 → US2 扫描+草稿 → US3 自动建 MR → US4 低采纳淘汰 → Polish。含 clarify（friction 三类、Jaccard≥0.7+样本≥5、共用 016 标记位、14 天淘汰、生成侧门槛）。
- **P0+P1 tasks 层齐备**（7 份：001/007/008/002/009/010/011）。
- 更新 `specs/INDEX.md`：tasks 行改为 7 份完成；P1 SDD 路径标注 tasks 已补齐。
- 全部提交并推送 cooper2006/mogong（origin push 仍锁 no-push，未触碰 himovo）。仅新增 `specs/**/tasks.md` + `INDEX.md`，未改 services/apps 源码。

## 2026-07-08 跨特性双向声明轮：清空 15 份 checklist 全部剩余未勾项

- 目标：消解 001/002/007–019 共 15 份 checklist 的剩余未勾项（跨特性两两关系 + 特性自身缺口），让 spec 契约无冲突、进入 implement 就绪。
- **A 类：跨特性双向声明**（在各 spec 新增"跨特性关系（被依赖方视角）"节，两边同声明）：
  - 001 补：↔006 权限码预设组、↔009 钩子扩展点+审计落点、↔012/013/018 受管入口、↔019 层概念、↔014/015 权限码 resource 扩展
  - 002 补：↔009 会话事件载体、↔011 经验源、↔013 IM 会话承载、↔017 记忆沉淀、↔005 会话 vs 知识边界
  - 004 补：↔011 草稿上游、↔016 市场强化基础、↔018 资产引用；005 补：↔014 业务实体项、↔015 图谱融合、↔017 存储/检索
  - 006 补：↔017 记忆提升权、↔019 厚度配置权；007 补：↔010 重试分层、↔001 配额维度、↔008 韧性字段
  - 009 补：↔001 扩展点/审计、↔002 载体、↔010 节点触发、↔019 非红线可跳+fail_closed 保留
  - 011 补：↔016 共用标记位、↔004 草稿、↔010 纯调度；012 补：↔018 a2a_exposed、↔001 受管入口；014 补：↔015 指针引用、↔005 检索、↔001 权限码
- **B 类：特性自身缺口回填 FR**：001 补 25 格 AUTONOMY_MATRIX 完整取值表；007 补降级原因枚举/重试响应取消/failover 计量归属（FR-11~13）；009 补五事件可携带数据/钩子延迟预算（FR-12~13）；010 补跨层并发预算（FR-12）；008 澄清"新标签页=新端点"契约边界。
- **结果**：15 份 checklist **全部 100% 勾选达标**（001 18/18、002 16/16、007–019 各满额）；各 checklist"评审结论"节更新为"全部达标"；003–006 既有回溯未动。
- 更新 `specs/INDEX.md`：checklist 统计行 + "五（补2）"表头与共性结论更新为"已全部消解"。
- 全部提交并推送 cooper2006/mogong（origin push 仍锁 no-push，未触碰 himovo）。改 `specs/**/spec.md`（跨特性关系 + FR 回填）+ `checklists/requirements.md`（勾选+结论）+ `INDEX.md`，未改 services/apps 源码。

## 2026-07-08 回填 + 评审勾选 P2 特性 012–019 的 checklist（agent 代审，19/19 全覆盖）

- 对 P2 八个特性走与 P0/P1 相同流程：逐条判定 checklist，回填 clarify 已定值 + 可消解边界进 FR 正文，再勾真正达标项：
  - **012 a2a-agent-gateway**（13/15）：AgentCard 字段+skills[]、JSON-RPC 方法名、agent 路由、客户端超时/failover、Dify 优先、刷新触发、同租户边界、双向审计、错误码映射、幂等、鉴权枚举、外部注册。
  - **013 multi-im-entry**（13/15）：映射粒度 1:1、长响应分段、能力=Web 全量、租户级开关、首期飞书、纯文本+基础卡片、会话映射、@bot 主体、撤回不回改、离线降级、凭据注入、1会话1IM。
  - **014 business-semantic-index**（12/15）：4 类实体+schema、定时拉取、联查键、来源三级、首期 CRM、PII 走 001、数据源不可用、全量首刷、对齐失败、副本延迟。
  - **015 knowledge-graph-layer**（12/15）：实体/关系类型、跳语义+3 跳、三类约束、查询入口、迁移阈值、断裂判定、合并策略、防环、低置信门槛、矛盾不阻断、融合裁决。
  - **016 skill-market-hardening**（13/15）：异常口径、打分权重、租户灰度、降权行为、20% 回滚、0.4/7天、数据源、最小样本、稳定版本、恢复路径、多版本归集（CHK006 矛盾上轮已修）。
  - **017 three-scope-memory**（12/15）：Workspace 粒度、默认策略、授权角色、衰减口径、三级可见性、001 治理点、离职处置、超限拒绝、多范围各存、检索过滤（CHK002 矛盾上轮已修）。
  - **018 capability-asset-registration**（12/15）：契约四段、扫描目标、3 态、owner 粒度、自动/人工分工、多对多 skill_refs、下线审批、旧版可查、去重键、视图下钻、owner 转移、a2a_exposed。
  - **019 harness-elastic-config**（13/15）：厚/薄层集合、三维 profile、审计粒度+超时、默认厚、优先级、可省/不可省、最小审计四元组、工具调用级生效、配置权、过渡挂载、中途切换。
- **19 份 checklist 现已全部 agent 代审并勾选**，P0/P1/P2 质量层完全一致。剩余未勾项**高度集中于跨特性双向声明**（012↔001/018、013↔001/002、014↔005/015/001、015↔005/014/001、016↔004/011、017↔005/002/006、018↔004/012/001、019↔001/009），需相关 spec 互相确认。
- 更新 `specs/INDEX.md`：checklist 行改为 19/19 全代审；"五（补2）"表补齐 P2 八行 + 更新共性结论；SDD 路径 P2 行标注已评审勾选。
- 全部提交并推送 cooper2006/mogong（origin push 仍锁 no-push，未触碰 himovo）。改 `specs/**/spec.md`（FR 回填）+ `checklists/requirements.md`（勾选+评审结论）+ `INDEX.md`，未改 services/apps 源码。

## 2026-07-08 回填 + 评审勾选 P1 特性 002/009/010/011 的 checklist（agent 代审）

- 对 P1 四个特性走与 P0 相同流程：先逐条判定 checklist，把"clarify 已定未回填 FR"+"可消解边界缺口"回填进 spec，再勾真正达标项：
  - **002 session-versioning**（12/16）：回填触发条件 / resume seq 续编 / share 权限转移+失效空态 / co-presence 冲突乐观锁 / 秘密判定 熵≥3.5+前缀 / 独立 `session_snapshots`+附件引用 / 审计字段 / 解引用定义 / 离线贡献保留。余 4 项跨特性（002↔001/009/011/005）。
  - **009 hooks-interception**（11/16）：回填三规则语义 / 作用域叠加合并 / fail_closed 不可配+observe 例外 / 首期仅 PreToolUse / 超时 5s / 解析失败三类 / deny 返回 403 区分 / 生效时机 / 求值顺序。余 5 项（五事件数据、跨特性 001/002/019、延迟预算）。
  - **010 dag-orchestration**（13/16）：回填节点数据传递 / 并发度 4+排队 / 跳过追溯 / 阻塞下游闭包+blocked 态 / JSON 条件对象 / 版本字段 / 环路径格式 / 双轨迁移 / 语法错误 fail_closed / 节点原子语义 / supervisor 失败传播。余 3 项跨特性（007/009/002）+ 跨层并发预算。
  - **011 dream-cycle**（12/16）：回填片段字段 / Jaccard+编辑距离 / 测试定义 / 采纳率口径 / friction 默认捕获 / MR 目标 004 草稿目录 / 草稿vsMR 边界 / 淘汰恢复 / 草稿堆积上限 / 同片段去重 / 淘汰生效范围 / 生成侧质量门槛。余 4 项跨特性（004/002/016/010）。
- 累计 P0+P1 七份 checklist 已 agent 代审：001 15/18、007 10/15、008 13/15、002 12/16、009 11/16、010 13/16、011 12/16。**剩余未勾项高度集中于跨特性双向声明**，需相关 spec 互相确认。
- 更新 `specs/INDEX.md`：checklist 行标注 P0/P1 已评审勾选；新增"五（补2）P0/P1 评审 + FR 回填记录"表。
- 全部提交并推送 cooper2006/mogong（origin push 仍锁 no-push，未触碰 himovo）。改 `specs/**/spec.md`（FR 回填）+ `checklists/requirements.md`（勾选+评审结论）+ `INDEX.md`，未改 services/apps 源码。

## 2026-07-08 审阅并勾选 P0 特性 001/007/008 的 checklist（agent 代审）

- 按 `/speckit-checklist` 语义逐条判定 001/007/008 的 18+15+15 项需求质量，**只勾真正达标的，未达标如实保留 `[ ]`**（不滥勾）：
  - **001**：勾 4/18（CHK003 PII 5 类、CHK008 脱敏仅存指纹、CHK011 编号已订正、CHK015 并发竞态属实现细节）；14 项未勾 = 真实缺口（含 clarify 已定但 FR 正文未回填的 CHK009/010 + 未定义的级联/时区/矩阵表/预设组/超时动作 + 跨特性 006/019 对齐）
  - **007**：勾 3/15（CHK005 单供应商 no-op 可验证、CHK010 凭据口径、CHK015 抖动属实现细节）；12 项未勾 = 真实缺口（主/备判定、降级维度、成本单价表、clarify 已定退避/仅文本未回填 FR、跨特性 008 字段对齐）
  - **008**：勾 1/15（CHK013 N=4 上轮已补）；14 项未勾 = 真实缺口（去重键/时区/容差/异常枚举、clarify 已定人工介入率/P50P95/top-N 未回填 FR、跨特性 007/006 对齐）
- 诚实结论：**P0 三份 checklist 均未 100% 达标**，暴露出大量"spec 还没写到可 implement"的需求缺口，主要集中在 ①clarify 已定但 FR 正文未回填（高频）②跨特性字段/角色口径未双向对齐 ③矩阵取值表/级联/时区等边界未定义。
- 勾选态即 `/speckit-implement` 的拦截门禁；未勾项须先回填 spec 才能放行。各 checklist 已加"评审结论"节登记达标/缺口明细。
- 全部提交并推送 cooper2006/mogong（origin push 仍锁 no-push，未触碰 himovo）。仅改 `checklists/requirements.md`，未改 spec/services/apps 源码。

## 2026-07-08 生成 P0 缺口特性 001/007/008 的 tasks.md（为 implement 铺路）

- 按 `/speckit-tasks` 语义把 spec 用户故事 + plan 模块结构 + 已消解 OQ + checklist 门禁拆成可执行任务，P0 先走：
  - **001 gatekeeper**（32 任务）：Phase1 骨架/配置/协议/编排 → Phase2 基础表/审计/权限码模型 → US1 六层链 → US2 25 格矩阵 → US3 PII 脱敏 → US4 权限码管理 → US5 配额 → Polish。含 clarify 决策（审批复用 approval_runtime 不建表、MongoDB 配额、PII 全局默认+租户覆盖）+ checklist 门禁说明。
  - **007 llm-gateway-resilience**（25 任务）：Phase1 resilience 子模块骨架 → Phase2 provider 抽象/退避原语 → US1 failover → US2 降级链 → US3 退避 → US4 计量 → Polish。含 clarify 决策（tenacity 复用、1.5s/30s/±10%/3 次、仅文本模型、事件落 token_usage_logs）。
  - **008 ops-dashboard**（27 任务）：Phase1 数据源对齐 → Phase2 质量/趋势聚合补齐 → US1 总览 → US2 成本 → US3 使用 → US4 质量 → US5 趋势 → Polish。含 clarify 决策（人工介入率口径、P50/P95 数据源、瓶颈 top-N、N=4、DashboardPage 标签页）。
- 每份含：故事分阶段 + 依赖图 + 并行点 + MVP 范围 + 实现策略 + checklist 门禁提示；故事间按 P1→P2→P3 排序，MVP 取最核心故事。
- 更新 `specs/INDEX.md`：完成度统计新增 tasks 行（P0 三份完成），SDD 路径细化 P0/P1/P2 各自 tasks 状态。
- 全部提交并推送 cooper2006/mogong（origin push 仍锁 no-push，未触碰 himovo）。纯 spec 规划文件，未改 services/apps 源码。

## 2026-07-08 修正 checklist 暴露的 5 处 spec 缺陷（规约自洽化）

- 按"先修缺陷再进 tasks"，逐个研读对应 spec 段落并修正：
  - **001 编号订正**：Non-Goals 4 条特性引用订正（LLM 韧性 002→007、DAG 003→010、自进化 004→011、会话版本化 005→002）。确认 003/005 的交叉引用编号本就正确，错配仅在 001 自身。
  - **016 FR-4 对齐 clarify**：FR-4 + US3 由"按比例/用户"改为"首期按租户，按比例/用户为后续扩展"，消除与 clarify OQ-2 的矛盾。
  - **017 FR-3/FR-5 默认策略统一**：按 clarify OQ-1"单/多人会话"改写 FR-3（单人默认 personal、多人默认 workspace）与 FR-5（沉淀随会话类型），消除两条默认冲突。
  - **008 补 N 值**：US2 成本预测"N = 4 期（可配置 forecast_periods）"，新增 clarify OQ-5。
  - **010 补语法错误策略**：US3 + FR-4 定为"默认 fail_closed（跳过 + 审计），可配置报错中断"，新增 clarify OQ-5，与 009 钩子 fail_closed 底线一致。
- 更新 `specs/INDEX.md`"五（补）"节：缺陷表由"待修正"改为"✅ 已修"修正记录。
- 全部提交并推送 cooper2006/mogong（origin push 仍锁 no-push，未触碰 himovo）。纯 spec 文本订正，未改 services/apps 源码。

## 2026-07-08 为 001–019 补齐需求质量门禁 checklist（19/19 规约质量层一致）

- 按 `/speckit-checklist` 语义（"需求的单元测试"，校验 spec 质量而非实现）为尚无 checklist 的 15 个特性生成 `checklists/requirements.md`（001/002/007/008/009/010/011 + P2 012–019），每份含完整性/清晰度/一致性/边界与歧义四类条目（CHKxxx 编号，全未勾选，reviewer-owned）。与既有 003/004/005/006 保持同口径，**19/19 规约质量层一致**。
- 门禁作用：`/speckit-implement` 读勾选态作为拦截门禁；未勾选项须先消解。
- checklist 逐份研读 spec+plan+clarify 记录后生成，暴露 5 个需在 reviewer 审阅前修正的缺陷（登记进 INDEX "五（补）"节）：
  - **001 CHK011 一致性缺陷**：spec Non-Goals 特性编号引用错配（写"LLM 韧性属 002/DAG 属 003"，实际 007/010），连带 012/013/014 的"001 是否含本特性"需按正确编号核实
  - **016 CHK006 矛盾**：FR-4"灰度按比例/用户" vs clarify"首期按租户"，需按 clarify 修正 FR-4
  - **017 CHK002 矛盾**：FR-3"默认个人级" vs FR-5"会话沉淀默认 Workspace"，需按 clarify OQ-1 统一
  - 008 CHK013 / 010 CHK013：成本预测 N 值、表达式语法错误策略 两处完整性缺口
- 更新 `specs/INDEX.md`：完成度统计 checklist 改为 19/19；新增"五（补）缺陷登记表"；SDD 路径三行同步。
- 全部提交并推送 cooper2006/mogong（origin push 仍锁 no-push，未触碰 himovo）。未改 services/apps 源码。

## 2026-07-08 按 P0→P1→P2 顺序完成 001–019 全部 clarify（OQ 消解）

- 按 `/speckit-clarify` 语义（消解 spec 歧义 + 把答案编码回 spec/plan）逐个消解 19 个特性的 OQ，每个 spec 新增 "Clarify 记录" 节，对应 plan "Open Questions" 改为 "Open Questions（已 clarify 消解）"。OQ 答案基于代码事实，未臆造：
  - **P0（001/007/008）**：001 审批复用 `approval_runtime`（poll + 5min 超时）、配额用 MongoDB（不引入 Redis）、PII 全局默认 + 租户可覆盖；007 用既有 `tenacity`（requirements 已含，azure_gpt_image 已用）、退避 1.5s/30s/±10%/3 次、事件落 `token_usage_logs`；008 人工介入率=审批挂起数、P50/P95 取 `duration_ms`、瓶颈 top-N、DashboardPage 加标签页。
  - **P1（002/009/010/011）**：002 独立 `session_snapshots`、熵 ≥3.5 + 前缀双判定、不引入 Redis、share 联动 006；009 超时 5s、fail_closed 不可放行、首期仅 PreToolUse；010 JSON 条件对象（禁代码 AST）、并行度 4、节点/模型重试分层、双轨迁移；011 Jaccard ≥0.7 + 样本 ≥5 建 MR、14 天低采纳淘汰、与 016 共用标记位。
  - **P2（012–019）**：各自口径/阈值/依赖顺序已定（019 薄模式保留身份/RBAC/脱敏/审计/红线，可省审批/配额）。
- 关键依据（grep 核实）：`approval_events.py::EnterpriseApproval`（审批状态机 + risk_level）、`azure_gpt_image.py` 的 tenacity 退避参数、`requirements.txt::tenacity>=8.3.0`、`dashboard.py::_duration_ms`、`scheduled_tasks/schedule.py` 的 once/daily/weekly 调度。
- 更新 `specs/INDEX.md`：完成度统计加入 clarify 19/19 + 关键消解摘要，去掉旧"待 clarify OQ"行。
- 全部提交并推送 cooper2006/mogong（origin push 仍锁 no-push，未触碰 himovo）。未改 services/apps 源码。

## 2026-07-08 补 012–019 的 plan.md（完成全部 19 份技术契约）

- 为 8 个 P2 后置缺口特性补 plan.md（基于已研读代码事实的挂载点设计，均标注 P2 后置 + 各自 OQ）：
  - 012 a2a-agent-gateway：新增 `a2a/`（AgentCard + JSON-RPC + 客户端），复用 `enterprise_capabilities/tools` 执行后端 + `governance` 鉴权审计
  - 013 multi-im-entry：新增 `im_gateway/`（渠道 adapter + 会话映射 + 路由），首期 1 渠道，复用 Workspace/Sandbox/001 治理
  - 014 business-semantic-index：新增 `business_index/`（连接器 + 实体抽取 + 增量 + 对齐），复用 005 `knowledge/retrieval` 检索与引用锚点
  - 015 knowledge-graph-layer：新增 `knowledge_graph/`（抽取 + 存储 + 多跳 + 一致性），首期 MongoDB 邻接模拟图，与 005 RAG 并行融合
  - 016 skill-market-hardening：新增 `admin-api/services/skill_market/`（监控 + 打分 + 灰度 + 标记），在 004 `skill_lifecycle` 之上叠加，复用审计 + token_usage + scheduled_tasks
  - 017 three-scope-memory：新增 `memory/`（三级范围 + 可见性 + 升级授权 + 沉淀），复用 005 个人知识 + 002 会话 + governance 授权
  - 018 capability-asset-registration：新增 `capability_assets/`（发现 + 注册 + 版本 + 治理视图），复用 `enterprise_capabilities/tools` 契约 + 审计 + position_roles
  - 019 harness-elastic-config：新增 `harness_config/`（厚度 schema + 层开关 + 底线守护），是 001 六层门禁的"启用哪几层"开关层，红线 + 审计不可降档
- 每个 P2 plan 均登记 4–5 个 OQ（阈值/口径/依赖顺序），供后续 clarify 消解。
- 更新 `specs/INDEX.md`：012–019 plan 列由 ⏳ 改 ✅，完成度统计改为 spec 19/19 + plan 19/19（全部技术契约齐全），SDD 路径同步。
- 全部提交并推送 cooper2006/mogong（origin push 仍锁 no-push，未触碰 himovo）。未改 services/apps 源码。

## 2026-07-08 为既有回溯特性 003/004/005/006 生成需求质量门禁 checklist

- 按 `/speckit-checklist` 语义（"需求的单元测试"，校验 spec 质量而非实现）为 003/004/005/006 各生成 `checklists/requirements.md`（4 份），每份含完整性/清晰度/一致性/边界与歧义四类条目（CHKxxx 编号，全未勾选）。
- 门禁作用：`/speckit-implement` 读取勾选态作为拦截门禁；未勾选项须先消解（多为跨特性口径对齐 + 各 plan 的 OQ）才能放行。
- 条目聚焦暴露 spec 的质量缺口，关键跨特性对齐项已标注：
  - 003↔001（审计联动依赖）、003↔005（候选片段来源）
  - 004↔006（"角色授权"口径）、004↔001（权限码过渡）、004↔016（市场强化边界）、CHK002 签名是否真实存在（须 clarify 定论）
  - 005↔002（知识分享 vs 会话交接）、005↔003（候选片段来源）、005↔001（检索授权）
  - 006↔001（岗位角色→权限码预设组）、006↔004（角色概念一致）、006↔019（厚度叠加）
- 更新 `specs/INDEX.md`：完成度统计加入 checklist（4 份），SDD 路径既有回溯链改为 spec→plan→checklist→tasks→analyze，并登记跨特性口径对齐待消解项。
- 全部提交并推送 cooper2006/mogong（origin push 仍锁 no-push，未触碰 himovo）。未改 services/apps 源码。

## 2026-07-08 补 007–011 的 plan.md + P2 后置清单建 spec（012–019）

- 补 5 份缺口特性 plan.md（基于已研读代码事实）：
  - 007 llm-gateway-resilience：`llm/resilience/` 子模块（failover/降级链/退避），计量复用既有 token_usage 管线
  - 008 ops-dashboard：在既有 dashboard.py/analytics.py 上补"质量/趋势"两维度，前端扩四维看板
  - 009 hooks-interception：`dsh_runtime/hooks/` 五事件注册 + fail_closed，挂载复用 turn_admission/gateway/approval_runtime
  - 010 dag-orchestration-engine：新增 `orchestration/` 通用引擎，content/planning 作为迁移参照
  - 011 dream-cycle-self-evolution：新增 `self_evolution/`，复用 scheduled_tasks/skills_specs/004 skill_lifecycle
- 新建 8 份 P2 后置清单 spec（规划文档 §清单 8–15，对应 12 的沉淀闭环已并入 011）：
  - 012 a2a-agent-gateway / 013 multi-im-entry / 014 business-semantic-index / 015 knowledge-graph-layer / 016 skill-market-hardening / 017 three-scope-memory / 018 capability-asset-registration / 019 harness-elastic-config
- 更新 `specs/INDEX.md`：新增"P2 后置清单"分组（012–019），修正完成度统计（spec 001–019 全 19 份；plan 001–011 共 11 份，012–019 待补）与 OQ 汇总
- 全部提交并推送 cooper2006/mogong（origin push 仍锁 no-push，未触碰 himovo）。未改 services/apps 源码。

## 2026-07-08 补全全部特性规约（spec 007–011 + plan 002/005/006 + INDEX）

- 新建 5 份缺口特性 spec（规划文档 §2/§3 补强清单）：
  - 007 llm-gateway-resilience（清单 2，P0）：failover/降级链/指数退避/计量
  - 008 ops-dashboard（清单 3，P0）：成本/使用/质量/趋势四维驾驶舱
  - 009 hooks-interception（清单 4，P1）：五事件 Hooks + fail_closed + 声明式规则
  - 010 dag-orchestration-engine（清单 5，P1）：四模式/拓扑/环检测/条件跳过/节点重试
  - 011 dream-cycle-self-evolution（清单 7，P2）：friction 沉淀/模式扫描/草稿建 MR/低采纳淘汰
- 补 plan.md 至已有 spec：002 session-versioning、005 knowledge-rag-research、006 position-rbac-admin（均基于既有代码事实：sessions.py versions/seq、knowledge/ citation 复合键、position_roles 集合）
- 新建 `specs/INDEX.md` 总览：既有回溯（003/004/005/006）与缺口新特性（001/002/007–011）分组，标注 spec/plan 完成度、对应规划条目、代码位置、待 clarify 的 OQ 汇总
- 规约完成度：spec.md 001–011 全完成（11 份）；plan.md 001/002/003/004/005/006 完成（6 份），007–011 待补
- 全部提交并推送 cooper2006/mogong（origin push 仍锁 no-push，未触碰 himovo）。未改 services/apps 源码。

## 2026-07-08 创建待确认清单目录 docs/pending-review/

- 按 AGENTS.md 代理操作规约中"无法判断的文件放入待确认清单"的约定，创建 `docs/pending-review/README.md`：定义收录规则（用途不明/疑似临时/与任务冲突/疑似废弃）、条目登记格式（路径/日期/发现者/疑点/建议/状态）、处置流程（用户拍板→代理执行→改 resolved）。
- 当前无待确认条目，台账为空。未改动 services/apps 源码。

## 2026-07-08 引入 Spec Kit SDD 规约 + 合并代理操作规约

- 初始化 specify-cli 1.0.8（claude skills 集成），生成 `.specify/`（模板/脚本/workflow）与 `.claude/skills/`（10 个 /speckit-* 技能；`.claude/` 按 .gitignore 不入库）。
- 写入项目 constitution `.specify/memory/constitution.md` v1.0.0（5 条核心原则 + 技术约束 + 工作流 + 治理）。
- 本次在 Development Workflow 后新增 **Agent Operating Rules（代理操作规约）** 一节，合并用户提供的 13 条代理行为约定（中文回复/思考、仅操作工作区、禁删文件、需确认先问、待确认清单、改后更新 WORK_LOG、只读最新 AGENTS.md/WORK_LOG.md、最小改动、不顺手重构、必要范围测试、出错先定位、远端写入边界只推 cooper2006/mogong）。constitution 版本升至 v1.1.0。
- 改动文件：`.specify/memory/constitution.md`（新增 Agent Operating Rules 节 + 版本号 1.0.0→1.1.0）。未改 services/apps 源码。
- 验证：constitution 为规约文档，无运行代码；`git diff` 仅该文件变更。

## 2026-07-08 回溯 SDD 规约：spec/plan 001–006

- 按 existing-projects 回溯方法为既有能力域补齐 SDD 规约，均提交并推送 cooper2006/mogong（origin/himovo push 已锁 no-push，未触碰）：
  - 001 gatekeeper-governance（缺口新特性）：spec.md + plan.md（含 3 个 OQ 待 clarify）。
  - 002 session-versioning（缺口新特性）：spec.md。
  - 003 document-ingestion-delivery（既有能力回溯）：spec.md + plan.md。
  - 004 skillhub-lifecycle（既有能力回溯）：spec.md + plan.md。
  - 005 knowledge-rag-research（既有能力回溯）：spec.md。
  - 006 position-rbac-admin（既有能力回溯）：spec.md。
- 远端：`git remote set-url --push origin no-push`，锁定不向 himovo 写入；推送走 mogong remote。

## 2026-09-22 将 movo-intro-v2 配色切为「极简单色」（黑白灰 + 单一电光青）

- 用户对「科技深空」仍不满意，指定方向「极简单色监听」：白底黑字 + 纯黑深底（封面/结束/挂载条/P2 band），**唯一电光青 `#12C2B0`** 作一律强调（标题竖条 / 证据 / ✓ / P0 / 最高优先级），其余全部灰阶。
- 优先级用「青实底 / 中灰 / 纯黑」分层：P0=电光青实底、P1=中灰 `#7B8491`、P2=纯黑；删去除青以外的所有彩色。
- 改动集中在 `/tmp/movo-ppt-build/gen-deck.mjs`：T tokens 收敛为黑/灰阶+单青（teal/amber/blue 同指电光青）；P4 GAP 与 P9 路线图 P1 由 teal→gray；P7 三卡顶条改「首卡青、余灰」；P8 Dream 步骤序号首步青、余灰。
- 结构校验仍通过（10 页、404 形状 0 越界、无畸形占位符）；LibreOffice→PDF→PyMuPDF 全页重渲染 + 蒙太奇总览确认整体协调。

## 2026-09-22 调整 movo-intro-v2 配色为「科技深空」+ 切微软雅黑字体

- 按用户指定方向「科技深空」重配色：深靛蓝 `#141B38`（封面/结束/挂载条）→ 品牌蓝 `#3D7BFF`（标题竖条）→ 电光青 `#11A8CC`（证据/强调/filled）→ 品红紫 `#A93DDF`（P0/最高优先级），内容页白底、浅蓝灰卡 `#F0F4FC`；头部 label/文本微调为深靛蓝系。
- 字体已由上版切为微软雅黑（`FONT_CN = "Microsoft YaHei"`），跨 Windows/WPS 通用。
- 仅改 `/tmp/movo-ppt-build/gen-deck.mjs` 的 design tokens（T 对象）+ header tick 锚点色，其余布局未动；重生成后结构校验通过（10 页、404 形状 0 越界、无畸形占位符），LibreOffice→PDF→PyMuPDF 全页重渲染 + 蒙太奇总览确认协调。
- 产物原位更新：`outputs/movo-intro-v2/movo-intro-v2.pptx`（含 PDF 预览与各页 PNG）；未改动源码与旧版产物。

## 2026-09-22 重做 MOVO 介绍 + 补强规划整合版 PPT（movo-intro-v2）

- 用户对 `outputs/movo-intro/movo-intro.pptx`（15 页）不满意（视觉不够高级 / 结构混乱 / 信息过载 / 篇幅长），要求**整合「社区版介绍 + 功能补强规划」两块、精简到 8–10 页重做**。
- 采用 jingmei-ppt 视觉总监流程 + **咨询研报配方**（analytical / compressed / calm）：白底 + 藏青墨色 + 细灰线 + 结论先行 + 单页单一 claim；深藏青封面/结束遥呼，P0 用克制的琥珀（占位 ≤6%）。
- 产出 10 页决策稿 `outputs/movo-intro-v2/movo-intro-v2.pptx`：01 封面 → 02 定位与核心判断 → 03 差异化底座 → 04 六大缺口（P0/P1/P2）→ 05 P0·治理风控层 → 06 P0·网关韧性+驾驶舱 → 07 P1·Hooks/DAG/双版本化 → 08 P2·自进化与生态 → 09 三阶段路线图 → 10 结束页。
- 技术路线：PptxGenJS（`/tmp/movo-ppt-build`，全局无 perl-library 依赖），结构化为 design tokens + 组件（header/token 单行保护/panel/pill）+ 每页组合；短 token 走 `token()` 单行保护（wrap:false + fit:shrink）。
- 结构校验：10/10 页、404 个形状 0 越界、无畸形占位符；LibreOffice headless 转 PDF + PyMuPDF 渲染 10 页 PNG，蒙太奇总览 + 封面/最密页（P0 治理、P0 生产）全尺寸检查通过。
- 审查副产品（仅供查看，未引用）：`movo-intro-v2.pdf`、`montage.png`、`preview/sNN.png`。
- 未改动源码、services、apps 目录；`assets/`/`slides/` 等旧产物保留未动。

## 2026-09-22 补充「功能补强规划」4 页到介绍 PPT（完成）

- 依据 `docs/MOVO企业级智能体功能补强规划.md` 扩展 PPT：11 页 → 15 页，新增第 4 章节「04 · 功能补强」。
- 新增 4 页（本地 `slides/` 源文件已完成并通过 slidep lint）：
  - P11 现状与六大缺口（横向条列，P0 琥珀 / P1 主蓝 / P2 青三色标注）
  - P12 P0 三大最高优先级（深色 hero，左大卡"治理与风控层"跨行 + 右上"LLM 网关韧性" + 右下"数据驾驶舱"）
  - P13 三阶段实施路线图（三列阶段卡 + 贯穿原则横条）
  - P14 P1 能力深读 + P2 生态清单（上三卡 Hooks/DAG/双版本化，下深色横条列 P2 十项）
- 已同步更新：`slides/02.slide` 目录页新增第 4 章、全部 15 页页码统一为 `NN / 15`、`slides/15.slide` 结束页副标增加呼应语。
- 中途阻塞：写入前 7 页成功、随后 08-15 全部 `HttpTransportError: openFile network error`；约 3.5 小时后重试，等 30 秒后 `slidep upsert-dsl movo-intro-v1.pptx --page-index 10` 首次成功（返回 `presentation is not open` 后自动恢复），说明云端 openFile 服务瞬时故障已解除。
- 最终产物：`outputs/movo-intro/movo-intro.pptx` 15 页完整版本，逐页 lint 全部通过（15/15 `"ok":true`）；未修改的 15 份 `.slide` 源文件保留在 `slides/`；空的中间产物 `movo-intro-empty-backup.pptx`（13 KB）作为归档保留。


## 2026-09-22 同步主文档 §2.1/§2.5 grep 措辞至规划1 修正版

- 对 `docs/MOVO企业级智能体功能补强规划.md`（主文档，含 AgentGit 会话级维度）的 §2.1 与 §2.5 两处 grep 措辞，同步为 `docs/MOVO企业级智能体功能补强规划 (1).md` 上一轮已修正的版本：
  - §2.1 R0–R4 矩阵行：「grep 无 `risk_level`/`rbac`/`autonomy` 命中」→「无分级矩阵（grep 无 `risk_level` 矩阵 / `risk_level × autonomy` 联合命中；`risk_level` 仅散落于 `enterprise_capabilities/tools`、`events/tool_presentation` 等业务模块）」。
  - §2.5 Dream Cycle 行：「grep 无 `learnings`/`dream`/`jaccard` 命中」→「无通用记忆自进化（grep 无 `learnings`/`dream`/`jaccard` 命中；`learning` 命中集中在 `browser/engine/workflow_cache`，属浏览器工作流缓存，非框架层）」。
- 复核主文档内其它 grep 表述（`circuit_break`/`degradation_chain`、`dag`/`topological`/`cyclic`、`hooks`）与 `services/` 验证结果一致，无需再改。
- 两份文档 grep 措辞现已完全一致；实质差异仅为主文档多含 AgentGit 会话级维度（§2.6、P1 第 6 项、P2 第 12 项、路线图、落地建议）。
- 未改动源码、services、apps 目录。



- 对 `docs/MOVO企业级智能体功能补强规划 (1).md` 的 §2.1 与 §2.5 两处表格描述做了最小修正，其余正文/结构未动：
  - §2.1 R0–R4 矩阵行：「grep 无 `risk_level`/`rbac`/`autonomy` 命中」→「无分级矩阵（grep 无 `risk_level` 矩阵 / `risk_level × autonomy` 联合命中；`risk_level` 仅散落于 `enterprise_capabilities/tools`、`events/tool_presentation` 等业务模块）」——避免与上一轮 grep 验证事实冲突。
  - §2.5 Dream Cycle 行：「无记忆自进化/经验沉淀（grep 无 `learnings`/`dream`/`jaccard` 命中）」→「无通用记忆自进化（grep 无 `learnings`/`dream`/`jaccard` 命中；`learning` 命中集中在 `browser/engine/workflow_cache`，属浏览器工作流缓存，非框架层）」——补上 `learning` 命中的实际位置。
- 复核规划1全文其它 grep 相关表述（`failover`/`circuit_break`/`degradation_chain`/`dag`/`topological`/`cyclic`/`hooks`），与 `services/` grep 结果一致，无需再改。
- 未改动源码、services、apps 目录。



- 在 `docs/MOVO企业级智能体功能补强规划.md` 末尾新增「§六、对标 EntAgent 可补充进 Movo 的功能（按价值排序）」，含 6.1 治理风控层、6.2 LLM 网关韧性、6.3 可扩展 Hooks、6.4 通用 DAG 编排、6.5 Dream 自进化、6.6 反向确认、6.7 落地优先级；原 §一–§五 结构与正文未动。
- grep 核实（`services/` 内）：`failover`/`circuit_break`/`degradation_chain` 0 命中、`topological`/`DAG` 0 命中、`rbac` 字样 0 命中；`risk_level` 仅散落 `enterprise_capabilities/tools`，`autonomy` 无业务命中；`hook` 命中全在业务代码（浏览器 rules、图像生成），非框架层；`learning` 命中集中在 `browser/engine/workflow_cache`，`dream`/`jaccard` 0 命中。文档结论据此表述为「无统一 X，已有 X 作挂载点」。
- 同步更新两处：顶部 `> 依据` 追加 EntAgent 对标来源；§四 实施路线图 P0/P1/P2 行追加 EntAgent 对标章节映射；「附：知识库核心参考来源」追加 EntAgent 安全闭环等参考。
- 未改动源码、services、apps 目录。

## 2026-09-22 制作 MOVO 社区版介绍 PPT

- 基于 `README.md` / `README.zh-CN.md` 内容，用 tencent-pptx 技能产出 11 页去代码化介绍 PPT，面向同行技术人员（企业自用智能体平台使用者）。
- 产出位置：`outputs/movo-intro/`（`movo-intro.pptx`、`STORY.md`、`DESIGN.md`、`slides/*.slide`、`assets/`）。未改动项目源码与 services 目录。
- 设计：科技蓝白配色（主 `#3B82F6` / 辅 `#06B6D4` / 强调 `#F59E0B` / 深底 `#0F172A`），11 页含 3 个 hero 页（封面、能力总览、结束页）。
- 复用项目自带素材：`movo-logo.png`（页脚 L3 角标）、`docs/assets/dsh-movo-responsibilities-zh-cn.png`（第 4 页 DSH/MOVO 分工主视觉）。封面与结束页背景图 ImageGen 两次均带"AI生成"水印，按规则改用 SVG 兜底。
- 全部 11 页 `slidep lint` 通过、已写入 pptx；第 7 页（七大能力）初版 6 卡横排触发 child-containment 溢出，改为 3 列 × 2 行 + 缩短文案后通过。
- 内容边界：保留"社区许可证非 OSI 开源、不可白标/OEM"的准确表述，未夸大开源程度。


## 2026-09-22 切换 OrbStack Docker 环境并启动全部服务

- 停止本地源码开发方式（dev.sh 及 8000/8100/8101/8200/3000/3100 端口服务），切换到 Docker 环境。
- 确认 OrbStack daemon 运行正常，`/usr/local/bin/docker`（OrbStack 注入）与 Compose v5.1.2 可用；DSH 沙箱 PATH 缺 docker，统一在命令中显式 `export PATH=/usr/local/bin:$PATH` 或 `DOCKER_BIN=/usr/local/bin/docker`。
- `~/.orbstack/config/docker.json` 已有国内 registry-mirrors（腾讯云/USTC/dockerproxy/1ms.run），daemon 已生效；拉取期间出现腾讯云源 Bad Gateway 与 short read，重试后 alpine:3.21、mongo:6.0.20、weaviate、ghcr 镜像全部就绪。
- `./movo --lang zh-CN up` 完成：bootstrap/mongo/redis/weaviate/dsh-runtime-host/chat-api/admin-api/document-api/document-worker/admin-web/user-web/gateway 全部 running（多数 healthy），入口 http://localhost:3000 与 /admin/setup 均返回 200。
- 此前本地开发阶段修改保留：三个 services 下的 `.env`（MONGODB_URI 指向本机 27017）、chat-api venv 的 motor 3.7.1/pymongo 4.18.1、admin-api 五处 `db is not None` 真值判断修复、user-web 与 admin-web 的 `pnpm-workspace.yaml` allowBuilds 开启（均为 dev.sh 源码模式需要；不影响 Docker 部署）。
- 下一步：访问 http://localhost:3000/admin/setup 完成首次初始化（企业管理员凭据由 setup 向导创建，无预置账号）。

## 2026-09-22 熟悉文档并尝试启动应用

- 已阅读 `README.md`、`README.zh-CN.md`、`dev.sh`、`dev_dsh.sh`、`CONTRIBUTING.md`、`docker-compose.yml` 与 `docs/docker-deployment.md`，确认官方启动入口为 `./movo up`，本地源码开发入口为 `./dev.sh` 或 `./dev_dsh.sh`。
- 已在本机执行 `./movo --lang zh-CN up`，启动器因“未找到 Docker”失败。
- 检查发现本机缺少 Docker、Docker Desktop、Docker Compose、Redis 与 Homebrew，因此当前环境不满足推荐启动条件；未继续执行 `./dev.sh` 以免缺少依赖后产生不完整启动。
- 下一步：安装并启动 Docker Desktop（或 Docker Engine + Docker Compose v2），确保至少 8 GB 可用内存和 20 GB 可用磁盘，然后执行 `./movo up` 后访问 `http://localhost:3000/admin/setup`；若选择本地源码开发，需要先安装并启动 Redis，再执行 `./dev.sh`。
