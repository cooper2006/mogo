# himovo/movo 与本地 mogo 代码比对与合并可行性分析

> 生成时间：2026-10-31
> 比对对象：本地 `cooper2006/mogo`（`main`）↔ 远端 `https://github.com/himovo/movo`（`main`）
> 本文只做分析，**未执行任何合并**。

---

## 1. 结论摘要

- 两个仓库**同源**：共同祖先为 `b30fa607`（2026-09-21 09:43，"ci: match manual promotion to candidate image tags"），此后**双向大幅分叉**。
- 分叉规模：
  - 本地 `main` 领先 **792 个提交**（内部/企业特性线）
  - `himovo/main` 领先 **173 个提交**（社区/产品化线）
  - 两棵树实际有差异的文件约 **3137 个**（含重命名），其中双方共有文件 **2108 个**、himovo 独有 **748 个**、本地独有 **1452 个**。
- **不建议整体 `git merge himovo/main`**：双方在同一批核心服务（chat-api / user-web / admin-web / admin-api / document-parser）上各自演进了数百个文件，机械合并会产生海量语义冲突。
- **建议按功能域选择性移植（cherry-pick / 定向搬运）**，优先级见第 6 节。真正低风险的是 himovo 的**独立新增模块**（sandbox-manager、sandbox-egress、qa 等）；高价值但高耦合的是 session-sharing、desktop、sandbox 全套。
- 一个重要判断：从 himovo 的提交（`Merge remote-tracking branch 'internal/main'`、`chore: keep internal release QA materials local`、`docs: remove internal notes from community repository`）看，**himovo/movo 更像是对外的社区/开源发行版，本地 mogo 是内部/企业开发主线**。两者定位不同，合并时要按"能力"而非"提交"来取舍。

---

## 2. 仓库关系与分叉基线

| 项目 | 值 |
|---|---|
| 本地 HEAD | `c9d185dd` docs(spec): 035/042 口径收敛 |
| himovo HEAD | `305bd927` feat(product): support enterprise member policy and deployment errors |
| 共同祖先 | `b30fa607`（2026-09-21 09:43） |
| 本地领先提交数 | 792 |
| himovo 领先提交数 | 173 |
| 共有文件 | 2108 |
| himovo 独有文件 | 748 |
| 本地独有文件 | 1452 |
| 两树差异文件（约） | 3137 |

> 说明：`himovo/main` 最初是浅克隆（depth=1），已加深到约 1000 层历史后才定位到共同祖先；更早的历史未拉取，不影响本次差异分析。

---

## 3. himovo/movo 自 fork 起的改动分布（173 提交）

### 3.1 改动文件按目录（自 fork 起）

| 目录 | 改动文件数 | 说明 |
|---|---:|---|
| `services/chat-api` | 542 | 最大改动源，含 session-sharing 端点、sandbox 脚本执行、DSH runtime |
| `apps/user-web` | 339 | 桌面端 UI、会话共享前端、i18n |
| `apps/admin-web` | 181 | sandbox 设置、暗色主题、i18n |
| `services/admin-api` | 104 | 企业成员策略、sandbox 设置路由、i18n |
| `services/document-parser` | 41 | OCR / vision / 证据检索增强 |
| `services/sandbox-manager` | 22 | **全新服务**（容器隔离） |
| `deploy/cli`、`deploy/docker` | 8 / 5 | 部署与 CLI |
| `.github/workflows` | 5 | 国内镜像、双架构发布 |
| `services/sandbox-egress` | 3 | **全新服务**（出口代理） |
| `qa/*` | 10 | **全新** Playwright 端到端测试套件 |
| `docs/*`、`scripts/*` | 若干 | 安装/发布文档、检查脚本 |
| `movo`、`assets/*`、`SANDBOX_CONTAINERS.md` | 各 1/3/1 | 启动脚本改名、素材、容器说明 |

### 3.2 功能主题分组（按提交聚类）

1. **会话共享 session-sharing（最大的一整块，约 40 个提交）**
   共享对话、参与者身份、share token 生命周期、实时 SSE、按会话隔离读写、发起者权限（取消/工具审批）、owner 重命名/删除级联、实时投影与去重。
2. **Sandbox 容器隔离执行（skills / plugins）**
   `sandbox-manager`（容器复用、租约、依赖源、Docker engine）、`sandbox-egress`（出口代理）、`chat-api/sandbox_script`（脚本准备）、租户级 sandbox 执行审计、默认开启 sandbox。
3. **DSH runtime 集成**
   DSH 升级、托管插件、Windows 支持、旧版兼容、CLI 环境预加载。
4. **桌面端应用 UI**
   主导航栏、Windows 标题栏、桌面暗色主题、代码面板、会话共享操作、更新提示。
5. **i18n 英文化**
   以英文 key 为基准，chat/admin/user/document 响应本地化，新增本地化检查脚本。
6. **企业成员策略与访问契约**
   `feat(product): enterprise member policy`、企业访问契约扩展。
7. **文档解析增强**
   内嵌 Office 图片 OCR、vision-capable 模型输入、证据式检索与知识落地、PDF 页恢复。
8. **搜索**
   DeepSeek Search 集成、按已启用 provider 路由。
9. **CI / 发布**
   国内 ACR 镜像、双架构镜像、Flow Buildx、漏洞非阻断上报、开源卫生检查。

---

## 4. 本地 mogo 独有方向（792 提交，对比参照）

- 大量 **spec 驱动的内部特性**：035/042/045 等口径收敛、资产中心、RBAC 角色白名单、系统审计一级菜单。
- **admin-web 深度打磨**：列表滚动条、筛选栏、页面边距、模型中心多选等大量 UI 修复。
- **离线 bundle 构建/加速**、Mongo → PanWeiDB 迁移、pg 差分校验。
- **治理/韧性/仪表盘/会话/钩子/DAG/语义索引/KG/技能/记忆/资产/配置** 等内部能力落地。
- QA 审计（R12）、跨午夜测试修复、部署缺陷修复。

> 结论：本地是"内部功能 + 治理 + 迁移 + UI 打磨"的深水区；himovo 是"产品化 + 开源化 + 桌面端 + sandbox + 会话共享"的对外能力线。

---

## 5. 可合并内容分层评估

### Tier A｜独立新增模块（增量、低冲突，**优先考虑**）

这些目录/文件在本地**完全不存在**，属于纯新增：

| 模块 | 路径 | 规模 | 说明 / 注意 |
|---|---|---|---|
| sandbox 容器管理 | `services/sandbox-manager/` | 22 文件 | 独立服务，含 Docker engine、租约、依赖源、jobs。需评估其调用方（chat-api）接口 |
| sandbox 出口代理 | `services/sandbox-egress/` | 3 文件 | 独立代理服务，耦合度低 |
| sandbox 脚本准备 | `services/chat-api/sandbox_script/` + `Dockerfile.sandbox-script` | 少量 | 依附 chat-api，需连带 chat-api 改动 |
| sandbox 审计端点 | `services/chat-api/app/api/endpoints/sandbox_audit_internal.py` | 1 文件 | 依附 chat-api |
| 端到端测试 | `qa/`（playwright、release-smoke、session-sharing spec） | 10 文件 | 可独立引入，但依赖各服务接口 |
| 文档/素材 | `SANDBOX_CONTAINERS.md`、`assets/*` | 4 文件 | 纯文档/图片，零风险 |
| 启动脚本 | `movo` | 1 文件 | 是本地 `mogo` 的改名版（均为 bash 启动脚本），**不要直接覆盖 `mogo`** |

⚠️ **关键提醒**：Tier A 虽是新增目录，但 sandbox 系列会 import/依赖 chat-api、user-web、admin-web 中**已被 himovo 修改的共享文件**。单独 copy 目录无法独立编译/运行，必须连带对应的共享文件改动一起移植。

### Tier B｜本地缺失或仅部分具备、但依附共享核心的功能（**中高价值、高耦合**）

| 功能 | 本地现状 | himovo 情况 | 合并难度 |
|---|---|---|---|
| 会话共享 session-sharing | 仅有 `services/chat-api/app/services/session_versioning/share.py` 等**局部**能力 | 完整特性：share token、参与者、实时 SSE、权限、级联删除 | 高（跨 chat-api + user-web + admin-web + 测试） |
| 桌面端 desktop | 无 `apps/user-web/src/components/desktop/*` | 完整桌面 UI + composables + Windows 标题栏 | 中高（若本地 user-web 结构差异大则接口对不上） |
| sandbox 设置 UI | 无 | admin-web `sandbox-settings.ts` + admin-api 路由 | 中（依附 sandbox 全套） |
| 企业成员策略 | 部分（enterprise_capabilities 等） | `enterprise member policy`、企业访问契约扩展 | 中高（与本地 RBAC 体系可能冲突） |
| DeepSeek Search | 已有 DeepSeek **模型**支持（llm/capabilities、pricing、metering） | 额外有 **Search** 集成与 provider 路由 | 中（可作为独立增强评估） |
| 文档解析 OCR/vision/证据检索 | document-parser 已有部分 ocr/vision 代码 | OCR 内嵌 Office 图片、vision 输入、证据式检索、PDF 页恢复 | 中（同文件双向改动，需逐文件比对） |

### Tier C｜双方都大改的共享核心（**冲突极高，不建议整体合并**）

| 服务/应用 | himovo 改动 | 冲突风险 |
|---|---|---|
| `services/chat-api` | 542 文件 | ★★★★★ 最大冲突源，本地同样深改 |
| `apps/user-web` | 339 文件 | ★★★★★ |
| `apps/admin-web` | 181 文件 | ★★★★☆ |
| `services/admin-api` | 104 文件 | ★★★★☆ |
| `services/document-parser` | 41 文件 | ★★★☆☆ |

> 这些是"双方各自演进同一文件"的重灾区。任何整体合并都会在这里产生大量需要人工语义裁决的冲突。

---

## 6. 合并策略建议（优先级）

**不建议** `git merge himovo/main`（3137 文件差异 + 双方独立演进核心服务，冲突不可机械解决）。

推荐按以下优先级**定向移植**：

1. **P0｜零风险文档/素材**：先吸收 `SANDBOX_CONTAINERS.md`、`assets/*`、`docs/windows-installation*`、`docs/release-process.md` 等纯文档（按需改写措辞，避免与本地 `.specify`/`docs` 口径冲突）。
2. **P1｜独立服务**：评估引入 `services/sandbox-manager`、`services/sandbox-egress`。这两个是独立新服务，冲突面小；但要先确认与本地 chat-api 的接口契约（本地是否已有 `egress_guard`、`enterprise_capabilities/data/script*`，是否会被新 sandbox 取代或并存）。
3. **P2｜高价值独立增强**：`services/document-parser` 的 OCR/vision/证据检索增强、DeepSeek Search 集成。相对独立、价值明确，建议**逐文件 diff 后挑选**，而非整块覆盖。
4. **P3｜大型特性（工作量大）**：session-sharing、desktop、sandbox 全套。建议作为**独立特性分支**评估，先做接口对齐与最小可用子集，不要一次性全量移植。
5. **P4｜暂缓**：i18n 英文化、CI 国内镜像等，本地已有自己的体系与 spec 口径，**借鉴思路即可，不建议直接搬提交**。

### 具体操作方法（若后续执行）

- 用 `git cherry-pick` 只挑**单一功能闭环**的提交，而不是 merge。
- 对 Tier C 的共享文件，先用 `git diff b30fa607 himovo/main -- <file>` 与本地同文件对比，评估是"himovo 独有增强"还是"与本地分叉"。
- 命名统一：himovo 把 `mogo` 改名 `movo`，合并时**保持本地 `mogo` 命名**，不要引入 `movo` 造成双启动脚本并存。
- 镜像/部署名、CI 变量、文档品牌词需统一改写。

---

## 7. 风险与注意事项

1. **命名分叉**：`mogo` vs `movo`（启动脚本、镜像名、文档品牌）。合并时以本地 `mogo` 为准。
2. **架构假设不同**：本地已做 **Mongo → PanWeiDB 迁移**、离线 bundle；himovo 的会话共享测试仍依赖 MongoDB（`ci: provide MongoDB for session sharing contract tests`、`validate personal knowledge access before db init`）。移植 session-sharing 时要适配本地存储层。
3. **spec 体系不同**：本地是 `035/042/045` 等 spec 驱动；himovo 是 `docs/open-source-productization` 开源产品化体系。文档合并会有口径冲突，**不要覆盖本地 spec**。
4. **依赖/锁文件**：本地有 `lockfix/admin-web-lockfile` 分支、`admin-web` 锁文件修复；himovo 用另一套 dependabot 版本。合并前端前先对齐依赖版本，避免锁文件冲突。
5. **Tier A 的"伪独立"陷阱**：sandbox 新服务看似独立，实为 chat-api 生态的一部分，**不能只 copy 目录**，否则编译/运行断裂。
6. **测试体系**：himovo 的 `qa/` 是 Playwright 端到端，本地测试是 pytest + esbuild+node 的 `test:*` 脚本，移植测试需改造运行方式。

---

## 8. 建议的下一步（需你确认后再动）

- [ ] 确认合并目标：只吸收**独立模块**（P0/P1），还是也要**会话共享/桌面端**这类大特性（P3）？
- [ ] 若同意，我可以先对 P1（sandbox-manager / sandbox-egress）做**逐文件 diff 与接口耦合评估**，产出一份"可移植清单 + 改动点"。
- [ ] 对 P2（document-parser / DeepSeek Search）做**同文件双向 diff**，标出 himovo 独有增强行。
- [ ] 所有操作前先建独立分支（如 `feat/port-movo-sandbox`），不污染 `main`。

---

## 9. P1 详细移植评估：sandbox-manager / sandbox-egress

### 9.1 服务定位与接口

- **sandbox-manager**：FastAPI 服务，监听 **:8300**，Bearer token 鉴权（`MOVO_SANDBOX_MANAGER_TOKEN`）。属 **DinD 型服务**：挂载 `/var/run/docker.sock`，负责拉起/回收 `sandbox-script` 与 `dsh-runtime-host` 容器，管理 workspace 卷、租约、依赖源。
- **sandbox-egress**：HTTP 出口代理，sandbox-manager 的 `depends_on` 健康依赖。
- 对外 API 面：

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/health` | 健康检查（compose healthcheck 用） |
| POST | `/v1/script-jobs` | 执行脚本任务 |
| POST | `/v1/script-task-calls` | 执行 task call |
| DELETE | `/v1/script-tasks/{task_id}` | 释放任务容器 |
| POST | `/v1/script-tasks/{task_id}/freeze` | 冻结任务容器 |
| POST | `/v1/skill-environments` (202) | 准备技能环境 |
| GET | `/v1/skill-environments/{digest}` | 查询环境状态 |
| PUT | `/v1/settings` | 更新设置 |
| POST | `/v1/plugin-runtimes` | 创建插件运行时 |
| DELETE | `/v1/plugin-runtimes/{lease_id}` | 释放插件运行时 |

### 9.2 chat-api 侧耦合层

| 部分 | 本地现状 | 移植动作 | 冲突 |
|---|---|---|---|
| `app/execution_isolation/`（12 文件） | **不存在** | 新增整包 | 低（新增）；依赖 `app.core.db`、`app.services.skill_packages.validator`、`app.utils.oss_uploader` —— **本地均存在 ✓** |
| `app/services/skill_packages/{dependency_status,prewarm,readiness}.py` | **不存在**（本地 skill_packages 只有 dispatcher/validator/installer/upgrade 等） | 新增 3 文件 | 低（新增） |
| `dsh/runtime-host/src/runtime-http-server.mjs` | 存在，但已分叉 | 手工合并 | **高**：+110/-261，需逐块取 sandbox relay 增量，勿整文件覆盖 |
| `docker-compose.yml` | 无任何 sandbox 服务 | 手工加 3 个服务 + profile + token + 卷 | 中 |
| `deploy/cli/sandbox.sh`、`deploy/cli/i18n.sh` | 无 | 新增/合并 | 低-中（品牌词 movo→mogo） |

### 9.3 结论

- **可低风险新增**：`services/sandbox-manager/`(22)、`services/sandbox-egress/`(3)、`app/execution_isolation/`(12)、skill_packages 3 个新文件。
- **必须手工合并**：`runtime-http-server.mjs`（本地区已深度分叉，直接覆盖会破坏本地 DSH 功能）。
- **运行前提**：Docker socket 挂载、`sandbox-script`/`dsh-runtime-host` 镜像需构建发布、`MOVO_SANDBOX_MANAGER_TOKEN` 密钥注入。
- **风险**：DinD 带来宿主机 Docker 权限暴露；与本地已有的 `egress_guard`、`enterprise_capabilities/data/script*` 存在职责重叠，需先决定"并存还是替代"。

### 9.4 `runtime-http-server.mjs` 逐块分析（三方 diff 结论）

三方规模（同一文件）：

| 版本 | 行数 |
|---|---:|
| fork 点 `b30fa607` | 191 |
| 本地 `main` | **433**（本地 +251/-9，大幅自研） |
| `himovo/main` | 282（himovo +108/-17） |

**关键结论**：`git diff main himovo/main` 的 +110/-261 **主要反映本地多出的 251 行**，不是 himovo 的 sandbox 增量。**直接覆盖 himovo 版本会删掉本地 261 行工作，绝不可取。**

himovo 相对 fork 点的真实增量（应移植的部分）按块拆解：

| 块 | 内容 | 依赖 |
|---|---|---|
| imports | 新增 `IsolatedPluginRuntimePool`、`ContainerPluginRuntimePool`、`admitSessionBody`、`PluginArchiveMaterializer`；移除 `resolveSessionSeed` | 4 个新模块，本地**全缺** |
| constructor | 依 `MOVO_SANDBOX_MANAGER_URL` 选 `ContainerPluginRuntimePool`（sandbox）或 `IsolatedPluginRuntimePool`；初始化 `#pluginArchives` | 同上 |
| 请求入口 | 新增 `/v1/sandbox-relay/` 路由（转发到 isolated pool）；错误处理加 `headersSent/destroyed` 保护 | — |
| health | 合并 `#manager.inventory()` + `#isolated.inventory()` | — |
| plugin-archives | 新增 `POST /v1/plugin-archives/materialize` | `#pluginArchives` |
| runtimes 创建 | `prepareProfile` 后按 `plugins.length` 路由到 isolated 或 manager | `plugin-archive-materializer` |
| isolated 路由 | 按 runtimeId 先查 isolated，支持 dispose / createSession / forward | `container/isolated-plugin-runtime` |
| plugin-child 分支 | `MOVO_DSH_PLUGIN_CHILD=1` 下的 `seed-export`、`trusted-session` | `admitSessionBody` |
| sessions 创建 | 用 `admitSessionBody` 替换本地内联的 cwd/seed/permission 校验 | `session-admission.mjs` |
| send | 由同步改 `await runtime.send(...)` | runtime 方法 |
| events | 新增 `head_only`/`headOnly` 探针（`runtime.headCursor`） | `headCursor`（本地缺） |
| questions | 新增 `pendingQuestions` / `answerQuestion` | 本地缺 |
| managed-plugins | 新增 list/inspect/install/enable/remove | `managedPlugin*`（本地缺） |
| `#seedSource()` | 统一 isolated/manager 的 seed 导出 | `exportCompletedSeed`（本地有） |

**因此 `runtime-http-server.mjs` 不能单独手合并**：它 import 的 4 个新模块本地全缺，调用的 `headCursor / pendingQuestions / answerQuestion / managedPluginList / managedPluginInstall` 本地 `runtime-manager.mjs` 也全缺。它只是 **DSH runtime-host 子系统升级的 HTTP 门面**。

### 9.5 P1 应拆成两条独立线

| 子线 | 范围 | 规模 | 可移植性 |
|---|---|---|---|
| **P1a｜Python 脚本执行侧** | `services/sandbox-manager/`、`services/sandbox-egress/`、`chat-api/app/execution_isolation/`、`skill_packages/{dependency_status,prewarm,readiness}.py`、compose、deploy/cli | ~40 文件 | **较可行**：Python 侧依赖（`core.db`/`validator`/`oss_uploader`）本地齐全；sandbox-manager 为独立服务 |
| **P1b｜DSH runtime-host 插件侧** | `services/chat-api/dsh/runtime-host/`（**40 新增 + 38 修改**，含 `runtime-http-server.mjs`、`container/isolated-plugin-runtime`、`managed-plugin-bridge`、`official-host/*`、Windows 兼容等） | **78 文件** | **大工程**：本地 runtime-host 已自研分叉（如 `runtime-manager.mjs` 本地 113 行 vs himovo 82 行），需整体评估，不能按文件硬合并 |

> 建议：先做 **P1a**（脚本侧，收益明确、耦合可控），把 **P1b** 作为独立大特性单独排期；`runtime-http-server.mjs` 留到 P1b 一并处理。

---

## 10. P2 文件级差异清单

### 10.1 document-parser（41 改动 = 25 新增 + 16 共享修改）

**新增模块（可直接搬，低冲突）：**
`office_image_ocr.py`、`office_image_sources.py`、`pdf_ocr_policy.py`、`pdf_page_ocr.py`、`pdf_text_recovery.py`、`rag_text_windows.py`、`retrieval_selection.py`、`retrieval_trace.py`、`spreadsheet_ingest.py`、`exact_identifier_retrieval.py`、`chunk_identifiers.py`、`error_locale.py`、`request_body_limit.py`、`rapidocr_assets.py`，及对应测试（`test_office_embedded_image_ocr.py`、`test_pdf_ocr_policy.py`、`test_pdf_text_recovery.py`、`test_retrieval_selection.py`、`test_exact_identifier_retrieval.py`、`test_short_content_preservation.py` 等）。

**共享文件（需逐文件 diff 后挑选）：**

| 文件 | 增删 | 说明 |
|---|---|---|
| `app/services/document_parsing_service.py` | +41/-116 | 解析主流程，改动大 |
| `app/services/vector_store.py` | +25/-76 | 向量库，改动大 |
| `app/services/retrieval_service.py` | +27/-35 | 检索主流程 |
| `app/main.py` | +17/-104 | 入口精简 |
| `app/services/model_center_runtime.py` | +23/-10 | 模型运行时 |
| `app/services/reranker_provider.py` | +18/-5 | rerank |
| `app/services/rag_chunk_optimizer.py` | +14/-4 | 分块 |
| `app/services/retrieval_access_policy.py` | +7/-8 | 访问策略 |
| `requirements-docling.txt` | +9/-30 | 依赖 |

> 注意：本地 document-parser 已有部分 ocr/vision 代码（`document_parsing_service.py` 有命中），需先判断是"himovo 更完整"还是"实现路线不同"，避免重复/冲突。

### 10.2 DeepSeek Search（本地已有搜索骨架）

- **本地已有**：`services/admin-api/app/api/routes/external_search.py`、`services/chat-api/app/services/search_provider_config.py`（共享，+41/-15）、`app/enterprise_capabilities/research/`、`app/api/endpoints/research.py`。
- **himovo 新增**：
  - 后端：`services/admin-api/app/services/external_search_provider.py`、`services/chat-api/app/dsh_runtime/profile/search_availability.py`、`app/enterprise_capabilities/research/progressive/{deepseek_provider,provider_router,evidence,summary_messages}.py`、`dsh/runtime-host/src/web-search-availability.mjs`。
  - 前端：`ExternalSearchSettingsPage.vue`、`SetupSearchStep.vue`、`SearchProviderGuide.vue`、`providerGuides.ts`、`locales/modules/deepseekSearch.ts`、`SessionSearchOverlay.vue`、`useSessionSearch.ts`。
- **结论**：属"在本地已有搜索骨架上叠加 DeepSeek provider + progressive research + 前端引导"，**不是从零引入**。必须先 diff `search_provider_config.py` 与本地 `research/` 现有实现，避免覆盖本地已有 provider。

---

## 11. 可执行移植清单（分阶段，建议逐段开独立分支）

### P0｜文档素材（零风险）— 已执行
- [x] 并入 `SANDBOX_CONTAINERS.md`（品牌词 `MOVO→MOGO`、`movo→mogo`、`MOVO_*→MOGO_*`；顶部加"随 P1 移植生效"状态说明）
- [x] 并入 `assets/`（`dsh-movo-responsibilities-en.png`、`dsh-movo-responsibilities-zh-cn.png`、`wecom-support-group-qr.png`，均为有效 PNG）
- [x] 更正：`docs/windows-installation*.md`、`docs/release-process.md`、`docs/docker-deployment.md` 在 himovo 中**已被删除**（社区化时移除内部文档），本地保留即可，无需吸收
- [x] 不并入：`apps/*/README.md`、`services/*/AGENTS.md`——属 himovo 开发约定（英文标识符/代码禁中文/DSH 边界），与本地约定冲突，非零风险

### P1a｜sandbox 脚本执行侧（分支 `feat/port-movo-sandbox`）— 已执行（预检通过）
- [x] 搬目录：`services/sandbox-manager/`(22)、`services/sandbox-egress/`(3)、`services/chat-api/app/execution_isolation/`(12)、`skill_packages/` 7 个新文件（archive_store / dependency_status / nested_archive / pending_upgrade / prewarm / readiness / retry_cache）
- [x] 品牌改写：`MOVO_→MOGO_`、`MOVO→MOGO`、`movo→mogo`、`ghcr.io/himovo/movo→ghcr.io/mogoai`（全量清零，`himovo` 未误伤）
- [x] `docker-compose.yml`：新增 `sandbox-egress` / `sandbox-script`(profile `sandbox-image`) / `sandbox-manager`(profile `sandbox`)，`sandbox-workspaces` 卷，bootstrap 生成 `MOGO_SANDBOX_MANAGER_TOKEN`，chat-api/admin-api 注入 `MOGO_SANDBOX_MANAGER_URL`（默认空=不启用）
- [x] `deploy/cli/sandbox.sh`（改写为 `mogo_sandbox_*`）+ `deploy/cli/i18n.sh` 3 条消息 + `mogo` source 该脚本（**不自动挂 up/update，默认行为不变**）
- [x] 验证：40 个 py 文件 `ast.parse` 0 失败；所有 `app.*` 内部 import 可解析；`docker compose config` 退出码 0，启用 profile 后 `sandbox-egress`/`sandbox-manager` 正确解析；`bash -n` 三个 shell 文件通过

**关键状态：`execution_isolation` 目前是"惰性"的**——本地 `enterprise_capabilities/data/script.py`、`script_engine/executor.py` 等**尚未**改为调用它（这些是 himovo 改过的共享文件）。也就是说脚本执行仍走旧路径，sandbox 不会自动生效。**激活需要下一步改这些共享文件**（见 §10/§9.2），这是 P1a 剩余的"接线"工作。

**未做/待确认**：
- sandbox-manager 单测未跑（本机无 venv，系统 python 缺 fastapi/httpx/pytest）。
- `mogo` 的 `up`/`update` 流程未自动调用 `mogo_sandbox_start`（避免改变默认启动行为，需你决定是否挂钩）。
- 与本地既有 `egress_guard`、`enterprise_capabilities/data/script*` 的"并存 or 替代"关系未决。

### P1b｜DSH runtime-host 插件侧（**已按方案 A 移植完成，待提交**）
- [x] 三方盘点：himovo 自 fork 起 **40 新增 + 38 修改**；本地自 fork 起 **6 新增 + 46 修改**
- [x] 分类：**仅 himovo 改过 54** / **双方都改过 24** / 仅本地改过 28
- [x] 冲突试算（`git merge-file`）：24 个冲突文件中 **12 个可自动干净合并**，其余多为 1–5 处冲突（`runtime-http-server.mjs` 5、`runtime-turn-context.mjs` 3、`official-host/installation.mjs` 3…），仅 `pnpm-lock.yaml` 需重新生成（93 处）
- [x] **方案 A 落地**：保持本地 `@deepseek-ai/dsh 0.2.1-rc.3`，把 himovo 改动适配到 rc.3（详见 §9.7）
- [x] 移植 54 个仅 himovo 文件 + 三方合并 24 个冲突文件（`runtime-http-server.mjs` 保留本地 261 行）
- [x] 回归：非 e2e 契约测试 A/B 对照，**共享用例零回归**（详见 §9.7）
- [x] 补齐 `managed-profile.mjs` 所需的 `pnpm` 运行时依赖（package.json + allowBuilds + 锁文件，纯增量 +144/−0）

#### §9.7 方案 A 执行结果与验证

**改动规模**：`git diff --stat main -- services/chat-api/dsh/runtime-host` = **72 文件，+2792 / −145**（其中 40 个新增文件、15 个 himovo 新测试文件）。

**冲突解决**：24 个冲突文件 → 12 个自动干净合并、11 个手工解冲突、1 个（`pnpm-lock.yaml`）不合并。
关键取舍：
- `package.json` / `pnpm-lock.yaml` / `pnpm-workspace.yaml` / `Dockerfile` **合并时逐字节保持 main 版本**（后续为补齐 pnpm 运行时依赖，按用户确认又做了三处显式改动，见本节末尾「新增缺口（已补齐）」）。合并时 himovo 把 `pnpm-workspace.yaml` 的 overrides 改成了 `undici 8.10.2` / `@modelcontextprotocol/sdk 1.31.0` / `fast-uri 3.1.7` / `sharp 0.35.5`，而锁文件仍是 main 的（`undici 8.11.2` / `sdk 1.30.0`）——**overrides 与 lockfile 不一致会让 Docker 里 `pnpm install --frozen-lockfile` 直接失败**，已回退。这些包新代码并未直接引用（`grep undici|modelcontextprotocol src/ tests/` 零命中），属传递依赖的安全版本提升，与本次移植无关。
- `runtime-http-server.mjs` 5 处冲突全解：imports 取并集、错误处理取 himovo、`/health` 保留本地签名 `runtimeHealth([...manager.inventory(), ...isolated.inventory()], this.instanceId, this.#state)` + drain 逻辑 + plugin-archives + isolated 路由（且 isolated 路由必须排在 holds 探针之前）、session 创建保留本地 `resolveSessionSeed(..., {authToken})`。
- `runtime-turn-context.mjs` 3 处：保留本地语言策略 + 采纳 himovo 文件交付策略；保留本地 MOGO Knowledge QA 措辞；采纳 himovo `visionEnabled` 分支。
- `kernel-runtime.mjs` 自动合并成功（474 行 = main 392 + himovo 443 的并集），含全部 `pendingQuestions` / `answerQuestion` / `headCursor` / `managedPlugin*`。

**静态校验**：`node --check` 覆盖 `src/**/*.mjs` 全部通过（0 失败）；冲突标记 0 处；品牌词 `himovo|movo|MOVO` 在 `src/` `tests/` **0 处**。

**动态验证（A/B 对照）**：并发跑 `node --test` 时失败集合会漂移（同一份代码首轮 24 失败、二轮 18 失败），**必须串行才有可比性**，故统一用 `--test-concurrency=1`。

| 指标 | main 基线 | P1b 合并后 |
|---|---|---|
| 非 e2e 测试文件 | 27 | 42（+15 个 himovo 新增） |
| 非 e2e 用例数 | 103 | 140 |
| 通过 / 失败 | 96 / 7 | **136 / 4** |
| 全量含 e2e（并发，仅参考） | 112，92 通过 / 20 失败 | 151，133 通过 / 18 失败 |

非 e2e 失败集合逐个比对：
- **两边共有 3 个**（预存问题，非合并引入）：`Runtime Host delegates workspace lifecycle…`、`runtime delegates to a DSH subagent…`、`runtime discovers and loads a Skill installed in the MOGO workspace`
- **仅 P1b 失败 1 个**：`managed plugin activates only for its Runtime…`（himovo 新测试，缺 pnpm 依赖，见下）
- **仅 main 失败 4 个**（P1b 顺带修好）：`a persisted code session resumes…`、`official Code composition coexists…`、`ordinary and code sessions use isolated official preset capability surfaces`、`runtime forks a completed conversation…`

HTTP 层单独串行对照（`runtime-drain` + `runtime-http-server` + `runtime-manager-isolation`）：main 与 P1b **均为 8 通过 / 1 失败，且失败的是同一条**（workspace registry），说明手工解冲突的 `runtime-http-server.mjs` 行为与 main 等价。

**⚠️ 预存失败根因（本次最重要的发现）**：本地 `node_modules/@deepseek-ai/` 下 **43 个包中完全没有 `workspaceRegistry` 这个 API**（`grep -rl workspaceRegistry node_modules/@deepseek-ai/` 零命中），而 `src/workspace-service.mjs:25` 与 `kernel-runtime.mjs:138` 依赖它——**这两处在 `main` 上就已存在**。也就是说本地 main 在 rc.3 基线下的 DSH kernel/workspace 用例**本来就是红的**，与 P1b 无关，也无法靠合并修好。e2e 用例的两种报错 `DSH Workspace Registry is unavailable` 与 `timed out waiting for Code/Skill E2E` 是同一根因（后者为级联超时）。

**新增缺口（已补齐）**：`src/official-host/managed-profile.mjs:4` 硬编码 `../../node_modules/pnpm/bin/pnpm.mjs`，himovo 在 `package.json` 里声明 `"pnpm": "11.28.5"`；本地 `package.json` 原本没有这个依赖（`node_modules/pnpm` 不存在）→ `managed-plugin-runtime` 用例报 `Cannot find module .../node_modules/pnpm/bin/pnpm.mjs`。

补齐方式与验证：
- `package.json` 加 `"pnpm": "12.14.0"`（对齐本地 Dockerfile 的 `npm install --global pnpm@12.14.0`）
- `pnpm-workspace.yaml` 的 `allowBuilds` 加 `pnpm: false`——pnpm 包带 `preinstall`/`postinstall`（`node install.js`），被 `ERR_PNPM_IGNORED_BUILDS` 拦下；该脚本只把 JS shim 换成原生二进制，其自身注释也说明「阻止生命周期脚本的安装会保留占位 shim，通过 Node 调用照样可用」，而 `managed-profile.mjs` 正是用 `process.execPath` + `bin/pnpm.mjs` 调用（实测 `node node_modules/pnpm/bin/pnpm.mjs --version` → `12.14.0`）。**这一条不加，Docker 里的 `pnpm install --frozen-lockfile` 会以同样错误失败。**
- 锁文件重生成：`pnpm install --registry=https://registry.npmmirror.com`（npmjs 源在本机解析 22 分钟无进展，npmmirror 45 秒完成）。结果 **+144 / −0 行**，全部是 pnpm 自身及其 `@pnpm/exe.*` 平台包，**已有依赖版本一个都没动**。

补齐后 `managed-plugin-runtime` 用例越过 pnpm 报错，再往下 3 个断言（plugin-archives 缓存修复、隔离可见性、跨 Runtime session 交接）都通过，只在最后一步「session 从 managed 交回 plain」失败，报 `runtime not found: <managedRuntimeId>`（`#seedSource()` 里 `this.#isolated.get(runtimeId)` 取不到）。这是该新用例的独立问题，与 pnpm 依赖无关，**待单独排查**。

#### §9.6 关键阻塞：DSH 依赖版本分叉

| 版本 | `@deepseek-ai/dsh` |
|---|---|
| fork 点 `b30fa607` | `0.1.6-alpha.1` |
| 本地 `main` | **`0.2.1-rc.3`**（本地独立升级到 rc 通道，依赖列表更长） |
| `himovo/main` | **`0.2.1-alpha.1`**（himovo 升级到 alpha 通道） |

双方从同一基线升级到了**不同的 0.2.1 预发布通道**（semver 上 `alpha.1 < rc.3`，本地更新）。himovo 的 runtime-host 新代码按 `0.2.1-alpha.1` 的 API 编写，直接并入本地 `0.2.1-rc.3` 存在 API 不兼容风险，**不是文本冲突能解决的**。

**可选方案（需你决策）**：
- **方案 A（推荐）**：保持本地 `rc.3`，将 himovo 的 runtime-host 改动**适配**到 rc.3——先跑通 54 个新增/修改文件的 `node --check` 与单测，逐文件修 API 差异。工作量中等偏大，但不降级本地。
- **方案 B**：整体对齐到 himovo 的 `alpha.1`——需把本地 DSH 相关 46 个文件的改动重新适配，风险大，**不建议**。
- **方案 C**：暂缓 P1b，先交付 P1a（脚本侧），DSH 插件侧等版本策略明确后再做。

> 首次尝试直接三方合并时，因上述版本分叉已回滚全部 P1b 工作区改动。**随后按方案 A 重做并完成**，结果见 §9.7。

### P2｜document-parser + DeepSeek Search（分支 `feat/port-movo-rag`）
- [ ] document-parser：25 个新增模块直接搬；16 个共享文件逐个 `git diff` 后挑选
- [ ] DeepSeek：先 diff `search_provider_config.py` / `research/`，再叠加 `deepseek_provider`/`provider_router`/`external_search_provider` 与前端
- [ ] 验证：本地 pytest 覆盖

### P3｜session-sharing / desktop（分支 `feat/port-movo-sharing`，先最小子集）
- [ ] 先做接口对齐 + 最小可用（share token + 只读共享 + 基础 SSE），不要全量
- [ ] desktop UI 需先确认本地 user-web 结构与 himovo 的 `components/desktop/*` 接口是否兼容

---

## 附录：本次比对所用命令（可复现）

```bash
# 添加并抓取 himovo（浅层 + 加深）
git remote add himovo https://github.com/himovo/movo.git
git fetch --depth 1 himovo main
git fetch --deepen=1000 himovo main

# 关系
git merge-base main himovo/main
git rev-list --count himovo/main..main      # 792
git rev-list --count main..himovo/main      # 173

# 文件集
git ls-tree -r --name-only himovo/main | sort > /tmp/himovo_files.txt
git ls-tree -r --name-only main | sort > /tmp/local_files.txt
comm -23 /tmp/himovo_files.txt /tmp/local_files.txt | wc -l   # 748
comm -13 /tmp/himovo_files.txt /tmp/local_files.txt | wc -l   # 1452
comm -12 /tmp/himovo_files.txt /tmp/local_files.txt | wc -l   # 2108

# 改动分布
git diff --name-only b30fa607 himovo/main | cut -d/ -f1-2 | sort | uniq -c | sort -rn
```
