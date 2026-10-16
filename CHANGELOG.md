# Changelog

All notable MOVO Community Edition changes are recorded here. Releases use
semantic version tags and the same tag is applied to every published container
image.

## v0.2.2 - 2026-10-16

### Changed

- **离线包增量下载（base-images 五类全部增量）**：按 `pip_wheels_bundle.sh`
  的同款思路，把剩余离线包改为增量下载，重跑不再全量重下。
  - `apt_packages_bundle.sh`：`fetch_one` 去掉 per-arch `rm -rf`（改 `mkdir -p`），
    容器内 `apt-get install` 前把缓存 `.deb` 回灌进 `/var/cache/apt/archives`，
    让 apt 跳过已下载的 `.deb`（apt 版 `--find-links`）。真实 docker 验证：
    重跑需要 **0 B / 2204 kB**，下载 0 字节。
  - `docling_models_bundle.sh`：新增 `base-images/docling-models/` 持久缓存与
    `fetch` 命令，`docling_version` + `inventory` 版本门禁，`save`/`pack` 按
    缓存是否 current 跳过。沙箱 10 场景验证通过。
  - 审计结论：pip-wheels / playwright / images / docling-models / apt 五类
    均为增量下载（playwright 于 v0.2.1 的 d63da04 已改造，本轮确认）。

### Added

- **027 数据后端迁移 R3（关系扁平化 + 兼容层 §5 改造）**：在 R1/R2 兼容门面之上，
  对 44 张表做「列 + doc」双形态落库，并让扁平化**真正生效**：
  - 实体库落地：455 列加列、同名列 + 24 条语义映射回填、44 条索引（含
    `WHERE deleted_at IS NULL` 部分唯一索引），openGauss 实测 0 错误；
    产物与审查清单归档于 `specs/027-mongo-to-panweidb-migration/r3-flatten/`。
  - 兼容层改造：新增 `app/core/column_map.py`（44 表 `{doc_key: column}` 1:1 映射，
    三服务副本逐字节相同）作为单一数据源；`pg_compat.py` 据此实现**双写**
    （INSERT/UPDATE/replace_one 同语句写列，CTE 保证原子性）、**读路径列优先**
    （SELECT 带列，非空覆盖 doc，datetime 序列化回 ISO 保形）、**筛选/索引路由**
    （命中键走真实列可用 btree）。非平铺表 map 为空，生成 SQL 与改造前一致。
  - 真库端到端冒烟（`r3-flatten/e2e_smoke.py`）：捕获兼容层真实 SQL 至 openGauss
    执行，验证 `UPDATE 1` 且列值正确同步（含语义别名 `user_id→owner_user_id`）。
  - 后续优化（同日落地）：`ORDER BY`（find_one / cursor sort）与 `distinct` 对命中
    COLUMN_MAP 的顶层键路由到真实列（可用 btree 索引；列值归一化保持 doc 形状：
    timestamptz→ISO 字符串、Decimal→int/float）；`aggregate` 的 `$match` / `$sort`
    仅在直接读基表的首阶段路由（CTE 阶段只有 `(id, doc)`，维持 doc 路径）；
    `$group` 的 `_id` 与累加器仍走 doc 路径。
- **027 数据后端迁移 R2（兼容层接线）**：在 R1 的门面上补齐**聚合管道**与
  **`bulk_write`**，使 25 处 `aggregate()` 调用点**仍然零修改**即可在 PanWeiDB 上工作。
  - 聚合管道编译器 `app/core/pg_compat.py::_AggregationCompiler`：阶段
    `$match`/`$group`/`$sort`/`$limit`/`$skip`/`$count`/`$project`；累加器
    `$sum`/`$avg`/`$min`/`$max`/`$push`/`$addToSet`/`$first`/`$last`；表达式
    `$ifNull`/`$cond`/比较/`$and`/`$or`/`$not`/算术/`$max`/`$min`/`$literal`/`$percentile`。
    未覆盖的阶段/算子显式抛 `PgCompatUnsupported`。
  - `bulk_write`：`InsertOne`/`UpdateOne`/`UpdateMany`/`ReplaceOne`/`DeleteOne`/
    `DeleteMany`，`BulkWriteResult` 字段对齐 pymongo。
  - 审计库分离：`get_audit_db()` 在 PanWeiDB 下指向独立 **schema**
    （未配置时回退业务 schema），schema 不存在时由 `CREATE SCHEMA IF NOT EXISTS` 自举。
  - 新增 `scripts/pg/sync_pg_compat.py`：把「同步三份兼容层副本」固化为脚本
    （`--check` 可作 CI 漂移检查），守卫测试改为复用它的变换，消除变换规则的第二份来源。
- 027 数据后端迁移 R1（MongoDB → PanWeiDB）—— 基础设施与兼容层：
  三个服务新增可选数据后端 **PanWeiDB 3.2.0**（openGauss 内核 / PostgreSQL 兼容线协议），
  由 `MOGO_DATA_BACKEND` 开关选择，**默认仍为 `mongo` 且行为不变**；回滚只需改环境变量
  并重启，**不需要回滚代码**。
  核心是 `app/core/pg_compat.py` 提供的 Motor/PyMongo 形状**兼容门面**：集合映射为单表
  `(id, tenant_id, doc JSONB, created_at, updated_at)`，字段一律走 JSON 路径表达式，
  **新增业务字段不需要 DDL 变更**，因此既有 612 处数据访问入口**无需改写**。
  驱动用 psycopg3（同步 + 异步一套依赖，同时替代 pymongo 与 motor）。
  新增 `scripts/pg/generate_ddl.py`（集合扫描，支持以源 MongoDB 为权威来源的
  `--from-mongo` → 幂等 DDL + 连库巡检）与 `scripts/pg/migrate_mongo_to_panweidb.py`
  （幂等搬迁 + `--prune` 对账 + 计数校验 + 续跑，**只读源库**）。
  方案与目标库实测事实见 `docs/mongo-to-panweidb-migration-plan.md`；
  SDD 规约见 `specs/027-mongo-to-panweidb-migration/`。
  实测：兼容门面在真实 PanWeiDB 上**异步 64/64、同步 26/26** 通过；三服务带哈希锁定
  文件均通过完整性安装；**真实数据入库**——本机运行中的 `mogo_dev` 库
  （88 集合 / **17,785 篇文档**）在 5.5s 内搬完，计数校验 **88 个集合全部一致、
  不一致项 0**，兼容门面回读 **13/13** 通过（含中文字段、空字符串字段、布尔字段、
  `_id` 归一、深合并更新、未覆盖能力显式失败）。

### Known limitations

- **本库没有 `jsonb ->> text[]` 运算符**：`->` / `->>` 右遇 `'{a,b}'` 字面量只匹配
  **text 重载**，键名变成字面字符串 `"{a,b}"` → 恒为 NULL（常量即可复现；显式
  `doc ->> ('{k}'::text[])` 直接报 `operator does not exist`）。**jsonb 路径表达式
  一律用 `#>` / `#>>`**（只接受 text[]、无歧义）；若误用 `->>'{k}'` 写列同步，
  真库上列被**静默写 NULL**（doc 完好、`UPDATE 1` 照常返回），测试已固化
  `"->'" not in sql` 回归断言。
- **`min()` / `max()` 聚合在 openGauss 上按文本比较 jsonb**（PostgreSQL 按类型序），
  实测 `$max` 在 `999` 与 `4343` 之间会取到 `"999"`；且其返回类型是 `text` 而非 jsonb。
  兼容层已改用 `(array_agg(x ORDER BY x))[1]`（jsonb 的**排序运算符本身是正确的**），
  并有差分测试覆盖。
- **GIN 索引不可用（openGauss 缺陷）**：`USING GIN (doc jsonb_ops)` 遇到**任何空字符串值**
  即报 `jsonb_gin.cpp : 519 : The parameter destMax is equal to zero ...`（顶层与嵌套值
  都触发；空数组 / 空对象 / `null` 正常）。且表里只要已有一行含空串，**连 `CREATE INDEX`
  本身都会失败**。空串在真实数据里极常见（`email: ""` / `phone: ""`），因此建表 DDL
  **只建 `tenant_id` btree 索引、不建 GIN**。实测对照：无索引 / `btree (tenant_id)` /
  `btree ((doc #> '{f}'))` 三者遇空串均可写，只有 GIN 失败。代价可控——GIN 只服务于
  `@>` / `?`，而兼容层里只有 `$all` 用到 `@>`（全代码库 1 处）。已加守卫测试防止重新引入。
- PanWeiDB 的 `sql_compatibility` 固定为 `A`（Oracle 模式）且为 `internal` 上下文不可修改，
  该模式下 `jsonb_build_array` / `jsonb_build_object` / `#-` / `jsonb_strip_nulls` /
  `jsonb_pretty` / `jsonb_to_record` / `jsonb_object_agg` / `jsonb_path_ops` 不可用。
  兼容层已在该子集内实现（嵌套删除改用「取父节点 → `-` 删键 → 写回」，
  `$push` 改用数组字面量），并有守卫测试禁止引入禁用函数。
- openGauss 的 `jsonb_set` **不创建中间层对象**（PostgreSQL 会），点号路径更新已用逐层
  回卷实现真深合并，避免静默丢更新。
- **搬迁不传播删除**：upsert 只保证「源库有的目标库也有」。源库在搬迁期间仍被写入
  （会话 GC / TTL 清理）时目标库会留残留，`--verify` 会报「目标多于源」。
  需要收敛时用 `--prune`。
- **DDL 生成器的静态扫描有漏扫**（实测漏 11 个集合）：集合名若来自大写常量、实例属性、
  带前缀下标、属性访问或配置项（如 `settings.jobs_collection`），扫描不到。
  迁移场景**必须加 `--from-mongo`**（以源库实际集合为权威来源）。
- 聚合与批量写**已在 R2 落地**（见上）。仍未覆盖：`$text` / geo 查询、
  稀疏/部分索引、`$setWindowFields` / `$geoNear`；调用即抛显式异常（不静默降级）。
  `$lookup` / `$facet` / `$unwind` / `$unionWith` / `$elemMatch` / `$pull` 在代码中
  **没有任何实际调用**（只出现在 `nosql_guard.py` 的白名单常量里），因此无需实现。
- 迁移后主键由对象类型归一为字符串；按对象比较主键的调用点需在 R3 逐点核对。

## v0.2.1 - 2026-10-12

### Added

- **021 unified context address space — production entry**：
  `POST /api/context/resolve` 与 `GET /api/context/trace/{id}` 暴露 `mogo://`
  地址空间（memory / resource / skill / session 四根）。此前 router 与四个
  tenant 适配器仅被测试引用，生产不可达。
- **009 hook 事件派发**（`app/dsh_runtime/hooks/dispatcher.py`）：`subscribe` /
  `dispatch` / `dispatch_session_end` 等，闭合 `emit_*` 产出却无人消费的断链；
  订阅者异常隔离，不影响调用方。
- **002 会话结束语义**：`SessionPersistenceService.end_session()` +
  `POST /api/sessions/{id}/end` + `chat_sessions.ended_at` / `end_reason` 字段。
  会话结束时触发 009 `SessionEnd` → 017 分层记忆沉淀（幂等，账本去重）。
- **017 契约文档** `contracts/memory-context-contract.md`：两条正交轴、地址语法、
  可见性委托矩阵、HTTP 契约与沉淀接线图。
- **Python 3.13 运行时升级 + 依赖哈希锁定（供应链完整性）**：`chat-api` 与
  `admin-api` 的基础镜像升级到 `python:3.13-slim-bookworm`；两者的
  `requirements.txt` 全量锁定 sha256（chat-api **2773** 条 / admin-api **1063** 条），
  安装改为 `pip install --require-hashes` —— 依赖树任何一环被替换都会构建失败。
  新增 `scripts/generate-hashes.sh` 生成与刷新哈希（走清华源，实测 >5min → ~3min）。
  **`document-parser` 保持 `python:3.10-slim-bookworm`**：Docling 钉死
  `numpy==1.26.4`，无 3.13 轮子，故不随迁；该服务的 `requirements.txt` 亦不做
  哈希锁定（同样受 Docling 约束）。
- **生产离线发布链路** `deploy/production/`：面向无外网 / 内网 Portainer 的交付。
  `prepare-release.sh` 九步流水线 —— 确定版本号（默认取 `git rev-parse --short HEAD`）
  → 前置检查 → 固定 compose 变量 → 收集镜像清单 → 交叉构建 amd64 应用镜像 →
  校验应用镜像 → 生成基础镜像 amd64 变体 → 打包 → 渲染清单 / 校验 / 出部署单。
  产出 `01-base.tar`、`02-app-small.tar`、`03-chat-api.tar`、`04-document-parser.tar`
  （大镜像单独成包，网页上传可单独重传），外加已渲染的
  `docker-compose.portainer.yml`、自包含的 `DEPLOY.md`（含实测体积与 sha256）与
  `bundle.json`。配套 `verify_bundle.py` 校验三条硬约束：每条 manifest 条目的
  `RepoTags` 与预期完全一致、config 的 `architecture/os` 为 `amd64/linux`、
  `len(Layers) == len(rootfs.diff_ids)`（经典 `docker load` 的硬性前提）；
  `render_deploy_doc.py` 生成部署单。
- **跨架构基础镜像导出** `scripts/export_base_images.sh`：`save --platform linux/amd64`
  借助 Docker 28+ 的 `docker save --platform`，可在 Apple Silicon 上产出 amd64
  归档。**load 侧默认拒绝跨平台归档**，须显式加 `--allow-platform-mismatch` ——
  单平台归档会**替换**同 tag 的多平台清单，误 load 会把本机镜像降级为单架构。
  另有 `--mirror`（解析 Docker Hub 走镜像站）与 `--manifest-only`（只出清单不导出）。
- **备份 / 恢复 / 回滚演练脚本** `scripts/test_backup_restore_rollback.sh`：
  把"备份 → 恢复 → 回滚"作为可重复执行的验证，而不是一次性手工步骤。

### Fixed

- **CI 测试门禁必红（P0）**：`pytest-asyncio` 在 strict 模式下拒绝执行裸
  `async def` 测试，而 `services/chat-api/pyproject.toml` 与 Quality Gate
  都没有设置 `asyncio_mode`。此前"本机全绿"依赖临时传入 `-o asyncio_mode=auto`；
  还原为仓库真实配置后全量 **43 failed / exit=1**。现已在 `pyproject.toml`
  写入 `asyncio_mode = "auto"`，并把 `pytest-asyncio` / `pytest-timeout`
  显式声明进 dev 依赖。
- **021 地址层越权：URI 被当成凭证（P0）**：`check_memory_visibility` 从 URI
  的 `scope` / `owner_id` 段**构造**判定对象，导致 `u2` 可用
  `mogo://memory/org/u1/m-1/L2` 读到 `u1` 的私密内容。现改为接收**真实存储
  记录**，缺失即 fail closed；`session` 适配器同步补 `user_id` 查询条件
  （此前同租户任一成员可读他人会话，含 L2 逐字稿）。
- **`707c8ea` 机械 sweep 引入的系统性回归（P1）**：该提交为 165 个文件批量
  改写 `except` 块，引入四类缺陷，已全部恢复并归零：
  - **8 处 try 体真实语句被删**（`yield _sse(...)`、`return {"healthy": ...}`、
    `return EffectContract(...)`、`parser.close()`、`raw = resp.json()`、
    `package = validate_skill_package(archive)` 等）；
  - **23 处 except 回退值被删** —— 16 处导致 `UnboundLocalError`
    （含安全函数 `utils/ssrf_guard.py`）、6 处破坏 `-> bool/int/str/List`
    返回契约、1 处 `ping_loop` 失去早退；
  - **6 处重复 `except` 子句**（后者不可达，新加的日志永不执行；其中
    `content/evaluation/streaming.py` 使 SSE 流异常时永久挂起）；
  - **18 个文件调用未导入的 `log_print`** —— 异常分支自身抛 `NameError`。
- **021 检索轨迹无租户隔离（P1）**：`_TRACE_RING` 现按 `tenant_id` 分键，
  跨租户读取返回 404。
- **`POST /memory` 允许任意角色写 org 作用域（P1，017 FR-4）**：非
  `ORG_PROMOTION_ROLES` 角色写入 org 作用域现返回 403。
- **记忆 `HARD_MAX` 按字符而非字节计量（P1，017 FR-16）**：中文内容实际占用
  3 倍字节，上限可被穿透；改为按 UTF-8 字节计算。
- **`MEMORY_SUMMARY_REFRESH_DAYS` 为死配置（P1）**：该环境变量从不被读取，
  刷新周期硬编码 30 天；现由 `_configured_refresh_days()` 统一解析。
- **`orchestration/store.py` 落库主键为空 + 未导入 `load_orchestration_document`（P1）**：
  `_document_shape` 读的是 `loaded.definition.id`（真实字段为 `orchestration_id`）。
- **`revoke_share` 引用未定义变量（P1）**：`tenant_id, _ = await _authorize(...)`
  丢弃 `user_id` 后仍引用它，端点必 500。
- **`memory/address.py` 未拒绝超长 URI（P2）**：段数 > 4 现抛 `ValueError`。
- **017 记忆永不落库（P0）**：`MemoryStore.save` 对 motor 的 `replace_one` 未
  `await`，协程创建即丢弃，API 返回成功但记录不存在。`save` 改为 `async`，
  调用链（memory 端点 ×2、sediment ×2、sessions ×1）同步补 `await`。
- **009→017 闭环语义**（P1）：会话沉淀此前只挂在 `delete_session`，导致会话
  正常结束不沉淀。现由 `end_session` 驱动，`delete_session` 降级为去重兜底。
- **021 KG 单节点读取**（P1）：`resource/kg` 适配器此前调用私有
  `_ensure_loaded()`，为读一个节点拉取租户全图（最多 2000 节点 + 5000 边）。
  新增公开 `TenantKgStore.get_node_direct()`。
- **版本一致性**：manifest 版本此前与 CHANGELOG 声明不一致
  （chat-api/admin-api/admin-web 为 0.1.0、user-web 为 0.0.0，CHANGELOG 为
  0.2.0）。已统一为 0.2.0，并在 Quality Gate 新增 `version-consistency` job
  阻断此类漂移。
- **全仓非静默宽泛 `except Exception` 补日志（R4）**：改用 AST 安全改写器
  （只增不删 / 不遮蔽变量 / 保留尾注释 / 排除异常已传播 / 绝不碰 `log_print`
  定义模块），落盘 **95 文件 · 209 条 `log_print` · 66 个 import · 147 行
  `except` 补 `as exc` 绑定**，**非-except 删除行 = 0**。显式排除 73 处异常已
  传播（`raise` / re-raise helper）与 38 处有意 `pass`（吞取消异常的关停惯用法、
  链式尝试的预期失败、以及日志基础设施自身 `emit()` / `_log_stage()`）。
  与 `707c8ea` 的 165 文件正则 sweep 形成对照：后者一次引入 4 类缺陷。
- **chat-api 全部上传链路在生产不可用（P0）**：`utils/oss_uploader.py` 的
  `generate_object_path()` 写成 `datetime.datetime.now(timezone)` —— `timezone`
  是 `datetime.timezone` **类**而非 tzinfo 实例，必然抛
  `TypeError: tzinfo argument must be None or of a tzinfo subclass, not type 'type'`。
  该函数经 `upload_bytes_with_path()` 被约 15 处生产调用点使用（头像、聊天附件、
  文档解析结果、生成图片、PPTX/PDF/表格导出、技能包、脚本产物、写作引擎产物），
  即**任何落盘并回传文件的功能都会 500**。由 `3f82068`（QF-445 机械替换
  `datetime.utcnow()`）引入：同提交另 4 处均正确写作 `now(timezone.utc)`，仅此
  一处漏了 `.utc`。全仓库检索同类误用（`now(timezone)` / `astimezone(timezone)` /
  `replace(tzinfo=timezone)`）仅此 1 处。
- **供应链密钥门禁首跑即红**：`scripts/check-secrets.sh` 与 CI 的
  `supply-chain-gate` 由 `1634e9b` 引入后**从未通过**——11 处高置信命中 + 12 条
  低置信提示，逐条核对全部是误报（`token = <函数调用>` 这类变量名、开发/测试
  固件里的假密钥、锁定文件的 `sha512` 校验和、40+ 字符长变量名）。现补齐两条
  **不放宽 pattern**（检出能力零损失）的豁免通道：**行级标记**
  （行尾 `pragma: allowlist secret`，detect-secrets 惯例）与**路径白名单**
  （新增 `specs/`、`scripts/dev/`、`pnpm-lock.yaml`、`versions.lock`，并把
  `is_allowlisted()` 由纯前缀匹配改为任意层级匹配，使 `services/*/tests/` 可被
  豁免）；低置信模式加**值位置**约束以排除 40+ 字符的长变量名。`--all`
  （2821 文件）现 exit 0、输出仅 `✓ 未发现疑似密钥`。
- **`dsh-runtime-host` 未纳入 022 US3 容器加固**：compose 模板此前没有
  `cap_drop: [ALL]` / `no-new-privileges` / 只读根，仅靠 entrypoint 的 gosu 降权。
  现镜像改以 `USER node` 直接非 root 启动（因此不需要 gosu 的
  `CAP_SETUID`/`CAP_SETGID`，`cap_drop: ALL` 才成立），entrypoint 的
  chown/gosu 改为 `id -u` = 0 条件分支，`HOME` 指向数据卷内的
  `/data/dsh-runtime/home`（DSH anonymous-user-id 落盘），cordis host profile
  走 tmpfs。七个服务现加固一致。

### Changed

- **对外暴露的 API 版本统一到 `0.2.0`**：chat-api / admin-api / document-parser
  三个服务的 `FastAPI(version=...)` 从 `0.1.0` 对齐到 `0.2.0`，与
  `pyproject.toml`、两个前端 `package.json` 及本文件已发布版本一致。
- **构建文档补充 DSH Runtime Host 的构建方式**：`./mogo build` 默认**不**构建
  `dsh-runtime-host`（其 Compose 服务带 `profiles: [single-host]`），而池模式的
  3 个副本复用同一镜像名，裸 `build` 后 `up` 会回退去拉 GHCR 镜像。已在
  `docs/docker-deployment.md` 新增专节，`README.md` 与 `docs/installation-guide.md`
  各加指引（含 `--profile` 为全局 flag、须置于子命令之前）。
  该字段是 `/openapi.json` 的 `info.version`，属**对外可见契约**，下游若按版本
  做兼容性判断会受影响；此前长期滞后会让排障时出现「代码是 0.2.0 但文档说 0.1.0」
  的口径冲突。  三处均已加注释说明需与 CHANGELOG 保持同步。
- **`version-consistency` 门禁覆盖范围扩大**（`.github/workflows/quality-gate.yml`）：
  原先只校验 4 个清单文件（两个 `pyproject.toml` + 两个前端 `package.json`），
  **恰不含三个 `main.py`** —— 这正是上一条版本滞后能长期存活的根因（该字段根本不在门禁视野里）。
  现新增 `check_fastapi`，对三个服务的 `FastAPI(version=...)` 一并校验，共 **7 条**。
  提取用 `sed -n '/FastAPI(/,/)/p'` 锚定 `FastAPI(...)` 调用块，避免误抓同文件里其他
  `"version"` 字面量（`/health` 响应体的硬编码 `0.1.0`、MCP `clientInfo`、DSH kernel 版本等）。
  提取失败（找不到 `FastAPI(` 或抓不到版本号）也会判失败，不会静默放过。
- **CI 质量门禁扩为五 job**（`.github/workflows/quality-gate.yml`）：
  `version-consistency`（manifest 版本与 CHANGELOG 声明一致）、`frontend-quality`、
  `backend-quality`、`dsh-host-e2e`、`security-quality`。
- **`backend-quality` 内置两道针对"单测全绿但生产零引用"的特殊门禁**：
  - `services/chat-api/scripts/check_production_wiring.py` —— 校验新增子系统的
    生产接线（router / 消费方）确实存在，拦住"只有测试在引用"的假落地；
  - `services/chat-api/scripts/check_module_coverage.py` —— 对新增子系统设
    **模块级覆盖率下限**：021 `context_space` 85%、017 `memory` 80%、
    009 `dsh_runtime/hooks` 75%。仓级 `fail_under = 55` 对大型遗留代码是合理的
    粗门禁，但对新子系统要么形同虚设、要么被遗留代码拖累，故单独设限。
- 017 文档补齐密度轴用法与地址契约：`specs/017-three-scope-memory/quickstart.md`。

## v0.2.0 - 2026-10-03

### Added

- Platform multi-tenancy (spec 020): a platform super-admin console for tenant
  lifecycle management (create / list / rename / enable / disable / reset
  password / archive / restore / purge), a `tenants` registry collection, tenant
  isolation guards, soft-archive semantics, and staged purge of MongoDB records,
  vectors and files with a one-month tombstone.
- Quota "unlimited" now propagates as a flag (`unlimited` / `points_unlimited`),
  with `remainingPoints: -1` meaning "no limit"; clients must not do arithmetic
  on `-1`.

### Upgrade notes (required reading)

- **Published container images were renamed: the `movo-` prefix is gone.**
  `ghcr.io/himovo/movo-chat-api` is now `ghcr.io/himovo/chat-api`, and likewise
  for `movo-admin-api`, `movo-admin-web`, `movo-user-web`, `movo-gateway` and
  `movo-dsh-runtime-host` (all 7 images, including `movo-document-parser`). The
  images are named `<registry>/<service>`; a local source build still uses the
  bare `service:tag` form (`chat-api:latest`) so local images never collide with
  the published ones. If your deployment pins the old names in a compose file,
  a Kubernetes manifest or a pull script, **update it to the new names before
  upgrading** — otherwise the pull fails, or an unchanged image reference keeps
  you on the old release while everything else moves ahead.
  The related `MOVO_IMAGE_PREFIX` environment variable is **no longer
  supported**: its old meaning was a name prefix (`${MOVO_IMAGE_PREFIX}-chat-api`
  → `ghcr.io/himovo/movo-chat-api`), which the new `<registry>/<service>` naming
  cannot express. It is ignored with a warning and the default registry is used,
  rather than building a non-existent path such as
  `ghcr.io/himovo/movo/chat-api`. Replace it with `MOVO_IMAGE_REGISTRY`
  (e.g. `ghcr.io/himovo`), or set the per-service `MOVO_*_IMAGE` variables
  directly.
- **Set `ASKAI_ADMIN_PLATFORM_ADMIN_PASSWORD` before the first start after
  upgrading.** A deployment that already completed the setup wizard will not see
  the wizard again, so this environment variable is the only way to provision the
  platform super-admin — without it the platform console is unreachable.
  `ASKAI_ADMIN_PLATFORM_ADMIN_USERNAME` and
  `ASKAI_ADMIN_PLATFORM_ADMIN_DISPLAY_NAME` are optional (defaults: `admin` /
  `平台超级管理员`).
- Existing tenants are backfilled into the new `tenants` collection on startup
  (idempotent, reserved identifiers skipped); no data migration is needed.
- **MongoDB database name changed from `gragentic` to `mogo_dev`.** This is a
  rename, not a copy: an existing deployment that keeps the old database name
  will appear to have lost all data, because the services connect to a fresh,
  empty `mogo_dev`. There is **no automatic migration**. Choose one:
  - keep existing data — set `ASKAI_ADMIN_MONGODB_DB` (admin-api), `MONGODB_DB`
    (chat-api) and `MOVO_DOC_PROCESSING_MONGODB_DB` (document-parser) back to
    `gragentic`; or
  - adopt the new name — before starting the upgraded stack, migrate the data,
    e.g. `mongodump --db gragentic` then `mongorestore --nsFrom 'gragentic.*'
    --nsTo 'mogo_dev.*'`, or rename each collection with
    `db.adminCommand({renameCollection: "gragentic.<c>", to: "mogo_dev.<c>"})`.
  Both `docker-compose.yml` and `prod-images-caf21d4/docker-compose.portainer.yml`
  already default to `mogo_dev`.
- `ASKAI_ADMIN_BOOTSTRAP_ADMIN_*` was renamed to
  `ASKAI_ADMIN_TENANT_BOOTSTRAP_ADMIN_*` — update your environment files.

## v0.1.15 - 2026-09-16

### Added

- Add configurable image-generation request and response mappings for OpenAI-compatible
  and custom image model endpoints.

### Changed

- Upgrade the embedded DeepSeek Harness runtime to `0.1.6-alpha.1` and refresh its
  compatibility adapters, supply-chain evidence, and regression coverage.
- Improve desktop and Web Code-session recovery, workspace selection, and execution
  activity presentation.

### Fixed

- Implement the MCP Streamable HTTP initialization and session lifecycle while
  retaining compatibility with legacy MCP HTTP endpoints.
- Send image-model options only when explicitly configured and parse configurable
  JSON response paths without assuming one provider-specific payload shape.
- Refresh Skill feedback state when new feedback notifications arrive without
  interrupting the current page with a loading state.
- Copy Skill sharing links in desktop WebViews that expose the Clipboard API
  but deny direct clipboard writes.

## v0.1.14 - 2026-09-15

### Fixed

- Avoid rebuilding unchanged container images when only the release workflow or
  release planner changes; full rebuilds now require an explicit operator request.
- Apply available Debian security updates to runtime images before publishing.
- Build and scan immutable candidate images before promoting a release to its
  version and `latest` tags, and use the last successful container release as
  the incremental-build baseline.

## v0.1.13 - 2026-09-15

### Added

- Complete the Skill distribution lifecycle with publishing, direct sharing,
  update discovery, feedback, and organization-level management.
- Support installing external Skills from ZIP packages and show their source,
  version, update status, and local modifications in the Web workspace.
- Add clearer Windows installation guidance for Docker Desktop, WSL 2, Ubuntu,
  and common WSL environment mistakes.

### Changed

- Use the official GHCR images by default so both `./mogo up` and native
  `docker compose up -d` work without an `.env` file.
- Pull container images sequentially and keep retrying interrupted downloads
  until they succeed or the user stops the launcher.
- Improve the English and Chinese README onboarding, quick start, capability
  boundaries, and community feedback entry points.

### Fixed

- Allow users to switch models between turns in the same conversation while
  preserving the selected model when conversation history is reopened.
- Correct packaged Skill editing actions and labels so imported Skills are not
  presented as unpublished authoring drafts.
- Improve Skill list and detail UI state handling, including safe rendering of
  optional feedback data and clearer local-change indicators.

## v0.1.5 - 2026-09-05

### Security

- Upgrade the Community Web runtime base image to the current minimal
  Nginx/Alpine release to remove fixable high-severity OS vulnerabilities.

## v0.1.4 - 2026-09-05

### Added

- Add durable DSH turn recovery and idempotent terminal-state finalization.
- Preserve evidence from manually recorded browser events to improve workflow
  portability and target matching.

### Changed

- Make chat cancellation wait for authoritative backend acknowledgement before
  releasing the active UI state.
- Improve stream startup, interrupted-turn handling and browser recording review.

## v0.1.1 - 2026-09-04

### Added

- Add configurable Python package, PyTorch and Hugging Face mirrors for source builds.
- Support externally provisioned Docling models and preserve reusable document-build caches.
- Add MOVO Desktop service-address and update controls to the Community Web workspace.
- Add selective promotion of validated container candidates.

### Changed

- Improve document-model download reliability and timeout handling.
- Expand the English and Chinese product documentation, including MOVO positioning,
  Desktop capability boundaries and official website links.

### Security

- Upgrade vulnerable DSH Runtime Host dependencies and republish the affected images.

## v0.1.0 - 2026-09-02

- Prepare the independent Community Edition repository.
- Remove Community Edition member limits and cloud billing behavior.
- Add isolated `movo_*` Docker volumes and first-run setup.
- Add resumable presentation generation.
- Add source-build and prebuilt-container deployment modes.
