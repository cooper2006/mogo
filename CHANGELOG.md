# Changelog

All notable MOGO Community Edition changes are recorded here. Releases use
semantic version tags and the same tag is applied to every published container
image.

## Unreleased

### Added

- **023 可观测性与韧性 Phase 1 基座落地（2026-10-24，T001–T013）**：
  - 公共基座 `services/common/` 三模块：`observability_base.py`（structlog 结构化日志 / OpenTelemetry 追踪 / Prometheus 指标 / contextvars trace_id 上下文 / status_class 工具）、`dependency_guard.py`（pybreaker 熔断 5 连失败·30s 半开 / TimeoutHierarchy 30s→10s→5s / 重试 1.5s 基数·30s 上限·±10% 抖动·3 次 / PoolRegistry + PoolSpec 连接池隔离）、`slo.py`（SLOSpec / ErrorBudget / BurnRate 双窗口 1h/6h + 6h/3d / DEFAULT_SLOS 99.9%·P99<3s·LLM 错误率<1%）；三服务 vendored 副本（`services/{admin-api,chat-api,document-parser}/app/common/`）+ `scripts/check_common_sync.py` 字节一致性 CI 门禁（3 模块 × 3 服务）。
  - 依赖钉扎：`admin-api` / `chat-api` / `document-parser` 三个 `requirements.in` 各追加 `structlog>=24.1` / `opentelemetry-{api,sdk,exporter-otlp}>=1.25` / `prometheus-client>=0.20` / `pybreaker>=1.2`，锁文件（`--generate-hashes`）纯增量新增，零版本漂移（msgpack 历史漂移 1.2.2→1.1.2 已按 `requirements.in` 钉扎修正）。
  - 可观测性栈：`docker-compose.yml` 追加 6 服务（`prometheus` / `grafana` / `alertmanager` / `otel-collector` / `tempo` / `loki`），由 `--profile observability` 门控（沿用 pool/panweidb profile 先例，默认部署形态不变）；`grafana` 挂 public + backend（宿主 3001，回环 127.0.0.1 默认绑定）；其余 5 服务挂 backend（internal 网络，仅容器内可达）；持久化卷 5 个（`prometheus-data` / `grafana-data` / `alertmanager-data` / `tempo-data` / `loki-data`，MOGO_VOLUME_PREFIX 前缀）。
  - 部署配置：`deploy/prometheus/prometheus.yml`（3 业务服务 + 栈自身抓取）、`deploy/otel-collector/config.yaml`（OTLP gRPC 4317 / HTTP 4318 接收，路由到 Tempo + Loki）、`deploy/grafana/provisioning/datasources/datasources.yml`（Prometheus/Loki/Tempo 三数据源）、`deploy/alertmanager/alertmanager.yml`（P0/P1/P2 分级 + IM webhook + 邮件兜底 + 静默/抑制规则）、`deploy/tempo/tempo.yaml`、`deploy/loki/loki.yaml`。
  - 验证：`docker compose config --quiet` 通过；三服务全量回归绿；`check_common_sync.py` 3 模块 × 3 服务字节一致。

- **025 API 契约加固 Phase 1 落地（2026-10-24，T001–T007）**：三服务统一错误契约——
  各新增 `app/core/errors.py`（稳定字符串错误码枚举 + `ErrorResponse`，RFC 9457 扩展
  `type`/`title`/`status`/`instance`，兼容键 `detail`/`message` 并存）、
  `app/core/error_handler.py`（接管 422/500；路由级 `HTTPException` 形状不变，留待
  T011 逐路由整改）、`app/middleware/trace_id.py`（`X-Trace-ID` 沿用/生成 + 响应头
  回写，chat-api 侧打通 observability `request_context`）、`app/core/errors_codes.md`
  （code/http_status/trigger/remedy 四字段字典）；新增
  `tools/api_check/error_codes_uniqueness.py` 跨服务错误码唯一性 + 状态漂移 +
  字典登记完整性检查，接入 `.github/workflows/quality-gate.yml`（backend-quality）。
  验证：admin-api 新增 `tests/test_error_contract_phase1.py` 14 项，admin-api /
  chat-api / document-parser 三服务全量 pytest 通过，`check_python_static.py` 门禁通过。
- **023–026 治理口径修正与 clarify 消解（2026-10-24 QA R11 后续）**：README（中/英）
  撤回 022–026「按波交付已实施」宣称；`specs/INDEX.md` 表行逐特性区分阻塞原因。
  023 的 OQ-1~OQ-8 经需求方确认全部消解（Loki / Tempo / pybreaker / 本地磁盘 +
  S3 兼容对象存储异地 / IM webhook + 邮件 / SLO 99.9%·P99<3s·LLM 错误率<1% /
  RTO≤30min·RPO≤15min / 单宿主机演练如实声明）；026 性能预算阈值定值（默认可配，
  见其 spec「Clarify 记录」）。四特性规约层阻塞全部解除。

- **AgentOS 整合批次 032–044 落地（13 个特性）**，2026-10-23 立项、2026-10-24 全部落地
  （spec/plan/tasks 三件套齐备，详见 `specs/INDEX.md`「四（补 6）」）：
  - **032 评测门禁 eval-gate**：技能发布前强制跑 golden 用例集
    （`skill_eval_cases` / `skill_eval_policies` / `skill_eval_runs`），未达
    `EVAL_PASS_RATE_THRESHOLD` / `MIN_EVAL_RUNS` 阻断发布；审计写 `gate_events`，
    写失败 fail-closed（503）；模型网关走 HMAC 令牌而非静态服务令牌。
  - **033 Canary 灰度**：按租户比例投放 skill 新版本，`skill_shadow_runs` 影子观测。
  - **034 工具凭证加密**：工具凭证 KMS 加密存储 + 一键轮换
    （`scripts/migrate_tool_credentials_encryption.py` / `rotate_tool_credentials_key.py`）。
  - **035 成本归因三维**：token 用量按 `(tenant_id, project_id, skill_id)` 归因。
  - **036 信任评级 L1–L4**：`trust_ratings` / `trust_rating_settings` + 降级扫描器
    （默认 21 天窗口 / 6h 间隔），L1 技能对用户不可见；管理端新增
    `TrustRatingPage.vue` 与 skills 页 L1–L4 徽标。
  - **037 统一门户**：资产发布 / 申领 / 审批 / 开通回收全链路
    （`portal_listings` / `portal_requests` / `portal_settings`），admin-api 与
    chat-api 双写侧共用字段契约。
  - **038 出口沙箱 egress**：域名 / 工具 / 路径前缀白名单 + 企业工具调用审计
    （`egress_allowlist` / `enterprise_tool_audit`）。
  - **039 可视化编排**：Vue Flow 画布（`OrchestrationCanvasPage.vue`）。
  - **040 模型档位路由**：`app/llm/complexity.py` + `app/config/model_routing.yaml`，
    按任务复杂度选档位，`aget_llm_client` 为真实生效路径。
  - **041 连接器市场**：模板安装计数按 `(tenant_id, template_id)`（`connector_installs`）。
  - **042 三级配额**：组织 / 项目 / 用户三级（`quota_projects` / `quota_alert_events`）。
  - **043 会话回放 Stage 1（纯前端）**：执行轨迹时间轴 + 步骤下钻面板；成本字段
    严格只认有限数值，无数据不渲染。
  - **044 多 Agent 模式**：010 编排引擎新增 `round_robin` / `debate` 两模式，
    补 `contracts/orchestration.md` 六模式契约。
- **租户清除覆盖补齐**：`TENANT_SCOPED_COLLECTIONS` /
  `TENANT_GOVERNANCE_COLLECTIONS` 收进上述新集合（`skill_eval_cases` /
  `skill_eval_policies` / `skill_eval_runs` / `connector_installs` /
  `portal_listings` / `portal_requests` / `portal_settings` / `egress_allowlist` /
  `enterprise_tool_audit` / `quota_projects` / `quota_alert_events`）。此前 032–044
  的新集合全部漏在租户清除清单外，删除租户会留下跨集合数据残留（GDPR 硬伤），
  本轮补全；`test_every_tenant_id_keyed_collection_in_the_tree_is_covered`
  自动扫描全仓 `*_COLLECTION` 常量防再次漂移。

### Changed

- **chat-api 未处理异常（500）响应体契约变更（025 FR-11，属预期破坏性收敛）**：
  `{"code": -1, "message": ...}` → 统一 `ErrorResponse` 结构（`code` 为稳定字符串
  `api.internal_error`，`message`/`detail` 兼容键保留）。HTTP 层消费方注意；
  SSE 流内帧 `code: 0/-1` envelope 不受影响。

- **审计写失败不再静默**：037 统一门户双写侧（chat-api `services/portal/requests.py`、
  admin-api `api/routes/portal_admin.py`）的 `gate_events` 审计写入原本
  `except Exception: pass`，证据链断口无法被发现，现改为写 warning 日志。
  admin-api 三个后台扫描器的 shutdown 停止同样补上 warning。
- **`scripts/check_python_static.py` 静默异常门重新收敛**：修复后 chat-api
  42 → 41、admin-api 16 → 12，全部回到上限内，未抬高任何上限。

## v0.2.5 - 2026-10-23

### Removed

- **彻底下线 movo 过渡回退机制**：`docker-compose.yml` 的卷名前缀回退链
  （`${MOGO_VOLUME_PREFIX:-${MOVO_VOLUME_PREFIX:-movo}}`）简化为只写
  `MOGO_VOLUME_PREFIX`，默认值由 `movo` 改为 `mogo`，卷名示例
  `movo-mongo-data` → `mogo-mongo-data`；secrets 双写（同时写 `movo_` 与
  `mogo_` 两份）取消，只保留 `MOGO_*` 权威键；`./mogo` CLI 内部 `movo_*`
  辅助函数命名与 `MOVO_*_IMAGE` 环境覆盖键一并退役；文档与镜像 registry 示例
  统一为 `ghcr.io/mogoai`，`MOVO_*` / `himovo` 字样从用户可见文档、
  NOTICE、LICENSE 与测试断言中清除。`MOGO_` 是唯一权威拼写，`.env` / CI 中
  残留的 `MOVO_*` 键需改名为 `MOGO_*`。

### Added

- **MongoDB 升级到 8.3.13**：按 6.0 → 7.0 → 8.0 → 8.3 逐级过 FCV 门升级（不能
  一步到位），FCV 停在 `8.0` 便于回退 8.0 二进制；升级前自动做逻辑 + 冷卷双备份，
  升级后 `mogo_dev` 56 个非空集合与升级前一致。
- **数据库连接信息全部下沉 `.env`**：新增 `MOGO_MONGODB_URI` / `MOGO_MONGODB_DB` /
  `MOGO_REDIS_URL`（业务缓存，DB/0）/ `MOGO_KERNEL_REDIS_URL`（DSH 锁与归属缓存，
  DB/1），默认值仍指向栈内服务名；`MOGO_MONGO_IMAGE` / `MOGO_REDIS_IMAGE` /
  `MOGO_WEAVIATE_IMAGE` / `MOGO_PANWEIDB_IMAGE` 可覆盖镜像（含 Portainer 离线模板）。
- **纯外部数据库部署模式**：设 `MOGO_USE_EXTERNAL_DB=1` 时 `./mogo up` 自动加载
  `docker-compose.external.yml`，把 `mongo` / `redis` / `panweidb` 三个容器排除出
  拓扑，应用只连 `.env` 里给的外部实例。起栈前会体检连接信息（缺失或仍指向栈内
  服务名直接拦下）并探测外部 MongoDB 版本（低于 7.0 提醒需逐级升级）；不启动栈
  单独体检用 `./mogo check`。
- **离线 bundle 漂移加固**：`scripts/apt_packages_bundle.sh` 现在会刷新离线
  Packages 索引（原先生成时索引长期滞后，叠加构建期 `apt-get update` 就是
  `E: Unable to fetch some archives` 的放大器）；chat-api / document-parser 补齐
  `libexpat1 2.5.0-1+deb12u5` 与 krb5 依赖，dsh-runtime-host 补齐
  `ca-certificates 20250419~deb12u2`；`apt` / `pip` bundle 下载失败不再被
  `|| true` 静默吞掉（失败即报错）。

## v0.2.4 - 2026-10-20

### Fixed

- **会话删除不生效**（P0）：`DELETE /api/sessions/{id}` 在会话没有活跃 DSH
  conversation 时 `dispose_conversation()` 抛 `LookupError`，导致整个请求
  返回 500、MongoDB 删除未执行；前端仅 console.warn，5 秒后
  `refreshSessionSummaries` 又拉回已删会话。修复：将
  `dispose_conversation` 包入 try/except（与已有 sedimentation 块一致），降级
  为 warn 日志后继续执行 MongoDB 删除；前端补 catch 块并显示错误 toast。同时
  修正 `refreshSessionSummaries` 中 `mergeSessionPages` 参数顺序反了的问题
  （原调用把服务器列表当基础集，已删会话被重新加回）。

## v0.2.3 - 2026-10-18

### Added

- **027 数据后端迁移：PanWeiDB（MongoDB → openGauss 系）R1/R2/R3 全量落地**。
  三服务新增可选后端 `MOGO_DATA_BACKEND=panweidb`（默认仍为 `mongo`，回滚只改
  环境变量）。核心是 `app/core/pg_compat.py` Motor/PyMongo 兼容门面：集合映射
  `(id, tenant_id, doc JSONB, created_at, updated_at)` 单表；R2 补齐聚合管道编译
  器与 `bulk_write`（25 处 `aggregate()` 零修改可用）；R3 对 44 张表做「列 + doc」
  双写扁平化，读路径列优先、筛选/ORDER BY/distinct 路由真实列可用 btree；T083
  七处 TTL 应用层清理（openGauss 无 TTL 索引）；T085 主键调用点后端解耦。
  新增宿主机一键拉起脚本 `scripts/pg/`。完整回归报告见 `specs/027-*`。
- **030 本体数据权限层**：chat-api 终端用户侧本体授权自查端点、admin-api 按用户
  汇总授权接口、admin-web「本体清单」+「用户本体授权」双视图、user-web「我的本体」
  页；撤销路由支持 `ontology://` 形态 URI；演示数据补种脚本。菜单/侧边栏文案
  国际化（本体授权 → 我的本体）。
- **031 模型供应商发现与多协议接入**：admin-web「获取模型列表」支持
  Anthropic/Gemini/Ollama（后端代理探测 provider 真实可用模型，点选免手填）；
  编辑已保存配置时复用已存 API Key。
- **部署：容器经 `host.docker.internal` 访问宿主机模型网关**，loopback 地址报错
  提示，方便本机 Ollama/网关直连。

### Fixed

- PanWeiDB 兼容层恢复 MongoDB 数组元素匹配语义（9f824bb）；补聚合 `$in`/`$toLower`
  并修占位符顺序，修复 dashboard overview 500（0f607a4）。
- 访问链路：localhost:3000 访问 + chat-api settings 导入（ceb47e5）、HTTP 补
  `/dsh-web/` 路由（1e7f4f0）、HSTS max-age=0 清除浏览器缓存（6005cbe）。
- panweidb 客户端 boncuser 连接 28P01 修复（7c30db1）。
- admin-web `src/api/models.ts` 括号错乱导致 `vite build` 失败（6ea16f3 引入，
  b5c3bfb 修复）。

### Changed

- TLS 开关抽取到 `.env`，默认关闭（b3bf111）。
- dsh-runtime-host 升级 dsh 至 `0.2.1-rc.3`（dsh-invariants 按 peer 例外保留
  `0.2.0-rc.2`，SBOM 单列车）。

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
