# Tasks: MongoDB → PanWeiDB 数据后端迁移

**Input**: Design documents from `/specs/027-mongo-to-panweidb-migration/`

**Prerequisites**: plan.md (required), spec.md (required)

**Status**: **R1（Phase 1–8）全部完成并实测通过**；R2（Phase 9）未开始。

**Organization**: 任务按用户故事分组，每组可独立实现与测试；`[P]` 标记可并行任务。
**US1 是其余故事的前置条件**（没有可切换的后端，搬迁与读写都无处落地）。

**Implementation Order**: US1 → US2 → US3 → US4 → US5 → Polish → R2

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行（不同文件、无依赖）
- **[Story]**: 所属用户故事
- 描述中含确切文件路径

## Path Conventions

- 服务代码：`services/<svc>/app/`
- 服务测试：`services/admin-api/tests/`
- 仓库级守卫测试：`deploy/tests/`
- 运维脚本：`scripts/pg/`
- 生成物：`deploy/pg/`

---

## Phase 1: Setup

**Goal**: 确认目标库能力边界与驱动可行性——所有后续设计都建立在实测之上，而非假设。

- [x] T001 实测目标库版本、兼容模式、认证方式与远程账号权限（PanWeiDB 3.2.0 / `sql_compatibility=A` / `internal` 不可改 / MD5 / `omm` 远程被拒 / `boncuser` 可用）
- [x] T002 验证驱动可行性：psycopg3 同步连接、异步连接、`AsyncConnectionPool`、`Jsonb` 适配器、参数绑定、事务、UTF-8 中文往返
- [x] T003 [P] 探测 A 模式下的 JSON 函数子集（可用 15 项 / 不可用 8 项），确认 GIN 只能用 `jsonb_ops`
- [x] T004 [P] 盘点迁移规模：`get_db()` 调用点 612 / 文件 149 / 集合 103；统计集合 API 与算子使用频次

**Checkpoint**: 能力边界与规模明确，可进入设计

---

## Phase 2: Foundational (Blocking Prerequisites)

**Goal**: 建立后端分派骨架与配置开关——**这是 US1–US5 的共同前置**。

**⚠️ CRITICAL**: 本 Phase 完成前，任何用户故事都无法落地。

- [x] T005 三个服务 `app/core/config.py` 新增 `MOGO_DATA_BACKEND` 开关与 `PANWEIDB_*` 连接参数（含环境变量回退与默认值）
- [x] T006 三个服务 `app/core/config.py` 新增 `effective_data_backend` / `effective_panweidb_*` 属性，规范变量不带服务前缀便于统一切换
- [x] T007 新建 `services/{admin-api,chat-api}/app/core/pg.py`：psycopg3 同步 + 异步连接池、DSN 组装（含 UTF-8 与 `search_path`）、健康探测、优雅关闭
- [x] T008 新建 `services/document-parser/app/core/pg.py`：同步连接池（该服务历史上只用同步驱动，无需异步池）
- [x] T009 改造三个服务 `app/core/db.py`：按 `MOGO_DATA_BACKEND` 分派；新增 `init_backend()` / `close_backend()` 统一入口
- [x] T010 改造三个服务 `app/main.py`：启动/关闭钩子改调 `init_backend()` / `close_backend()`（异步服务必须走异步入口，psycopg 的异步连接绑定事件循环）
- [x] T011 [P] 三个服务 `/health` 上报后端快照（`backend` / `target` 脱敏 / `reachable`）；异步服务用异步探测避免额外建同步池

**Checkpoint**: 后端可分派、可切换、可探活，US1 达成

---

## Phase 3: User Story 1 (P1) — 数据后端可开关切换 🎯 MVP

**Goal**: 默认行为与迁移前完全一致；切换后连接可用；参数缺失时显式失败不回退。

**独立测试**: 不启动新库，仅切换环境变量，观察启动日志、健康检查输出与连接目标。

- [x] T012 [US1] `init_db()` 在新后端模式下**显式拒绝**（异步池必须在事件循环内建立，不允许半初始化）
- [x] T013 [US1] `get_db()` 在池未就绪时给出可操作的错误信息（指明应在启动时调用 `init_backend()`）
- [x] T014 [US1] 验证默认分支：用桩驱动确认 `MOGO_DATA_BACKEND` 未设置时返回原后端句柄，`close_db()` 正常
- [x] T015 [US1] 验证切换分支：真实建池 + `ping` + 列出 103 张表；`health_payload()` 返回 `reachable: True`

**Checkpoint**: 可开关、可回滚、默认零影响

---

## Phase 4: User Story 2 (P1) — 既有业务代码无需改写

**Goal**: 门面形状与现有驱动一致，既有调用点零修改即可读写新库。

**独立测试**: 同一组用例对门面执行，断言结果集与更新后的文档结构。

- [x] T016 [US2] 新建 `services/admin-api/app/core/pg_compat.py`：结果对象（`InsertOneResult` / `UpdateResult` / `DeleteResult`）、`PgCursor`、`PgCollection`、`PgDatabase`
- [x] T017 [P] [US2] 实现过滤条件编译 `_FilterCompiler`：等值 / `$ne` / 范围 / `$in` / `$nin` / `$exists` / `$regex`(含 `$options`) / `$or` / `$and` / `$nor` / `$not` / `$size` / `$all` / 点号路径
- [x] T018 [US2] 实现更新算子编译 `_UpdateCompiler`：编译为 `WITH s0/s1/...` **步骤链**（规避占位符重复）
- [x] T019 [US2] 实现 `_jsonb_set_path()` 逐层回卷，修复「`jsonb_set` 不建中间层导致的静默丢更新」
- [x] T020 [US2] 实现 `_unset_expression()`，用「取父节点 → `-` 删键 → 写回」替代不可用的 `#-`
- [x] T021 [P] [US2] `$push` 改用数组字面量替代不可用的 `jsonb_build_array`；`$addToSet` 占位符入参两次（判重 + 追加各一次）
- [x] T022 [US2] 实现 `apply_update_to_document()`（Python 侧算子，用于 upsert 插入路径）
- [x] T023 [US2] 实现隐式建表 `_ensure_table()`：幂等、可并发、首次操作时执行，对齐文档数据库语义
- [x] T024 [US2] `create_index` 支持单字段与复合字段；忽略方向；先建表再建索引
- [x] T025 [US2] 复制门面到 `services/chat-api/app/core/pg_compat.py`（异步，逐字节一致）
- [x] T026 [US2] 由异步版机械变换生成 `services/document-parser/app/core/pg_compat.py`（同步游标：`for` 迭代 + `len()` + `to_list()`）
- [x] T027 [US2] 真实 PanWeiDB 端到端验证：异步 **64/64**、同步 **26/26** 通过

**Checkpoint**: 门面在真实库上可用，业务调用点零修改

---

## Phase 5: User Story 3 (P1) — 存量数据可搬迁、可校验、可重跑

**Goal**: 搬迁幂等、可续跑、可校验，且只读源库。

**独立测试**: 可控小数据集完成「演练 → 搬迁 → 重跑 → 校验 → 门面回读」全链路。

- [x] T028 [US3] 新建 `scripts/pg/migrate_mongo_to_panweidb.py`：按批读取源库文档、`ON CONFLICT DO UPDATE` 幂等写入
- [x] T029 [P] [US3] 实现演练模式 `--dry-run`（只统计不写库）
- [x] T030 [P] [US3] 实现校验模式 `--verify`（逐集合比对文档数并列出不一致项）
- [x] T031 [US3] 实现进度表 `<schema>._migration_progress` 与 `--resume` 续跑
- [x] T032 [US3] 主键归一为字符串（JSON 列存不下对象类型），并在文档中登记为已知差异
- [x] T033 [US3] 真实链路验证：临时源库灌入 3 个集合 → 演练 → 搬迁 → **幂等重跑（计数不变）** → 校验一致 → 门面回读 + 更新 10/10 通过

**Checkpoint**: 数据可搬迁、可验证、可重跑

---

## Phase 6: User Story 4 (P2) — 建表可自动生成、可巡检

**Goal**: 从代码推导集合清单并生成幂等 DDL；连库巡检缺失表。

- [x] T034 [US4] 新建 `scripts/pg/generate_ddl.py`：三来源扫描集合名（`*_COLLECTION` 常量 / 字面量下标 / `*_COLLECTIONS` 清单），取并集
- [x] T035 [P] [US4] 生成幂等 DDL（`CREATE SCHEMA/TABLE/INDEX IF NOT EXISTS`）+ 租户索引 + GIN(`jsonb_ops`) 索引
- [x] T036 [P] [US4] 实现 `--list`（列出集合与来源文件）与 `--check`（连库巡检缺失表）
- [x] T037 [US4] 生成 `deploy/pg/schema.sql`：**103 张表 / 309 个索引**，实测 **1.6s** 建完；巡检报「全部表已就位」

**Checkpoint**: 建表可自动化、可巡检

---

## Phase 7: User Story 5 (P2) — 未覆盖能力显式失败

**Goal**: 把未知缺口转化为可枚举清单，不静默出错。

- [x] T038 [US5] 定义 `PgCompatUnsupported` 异常，消息包含「未实现的内容 + 应查阅的方案文档 + R2 处理位置」
- [x] T039 [P] [US5] 未覆盖的集合 API（聚合管道、`bulk_write`）与算子（`$elemMatch` / `$pull` / `$text` 等）逐个显式抛出
- [x] T040 [US5] 验证：对未覆盖能力调用断言异常类型与信息；对已覆盖调用确认无误报

**Checkpoint**: 缺口可枚举，R2 工作量估算可信

---

## Phase 8: Polish & Cross-Cutting Concerns

- [x] T041 [P] 三个服务 `requirements.in` 声明 `psycopg[binary]` + `psycopg-pool`
- [x] T042 重生成带哈希的 `requirements.txt`：admin-api（仅新增 psycopg 三件套）、chat-api（**77 行纯新增、零删除**）
- [x] T043 document-parser 锁定文件：镜像源不可达时手工合并，并记录依据（哈希覆盖该版本全部发行文件，与 Python 版本无关）；登记网络恢复后的补跑命令
- [x] T044 [P] 三个服务锁定文件通过 `pip install --require-hashes` **实测安装**
- [x] T045 [P] 三个服务 `.env.example` 新增开关与连接参数示例
- [x] T046 [P] `docker-compose.yml` 为 4 个服务条目注入 `MOGO_DATA_BACKEND` 与 `PANWEIDB_*`；YAML 合法性校验通过
- [x] T047 新建 `services/admin-api/tests/test_pg_compat.py`：**29 项**纯逻辑单测，含「占位符数量 = 参数数量」不变量与深合并回归
- [x] T048 新建 `deploy/tests/test_pg_compat_parity.py`：**11 项**守卫（异步副本逐字节一致 / 同步副本等于机械变换结果 / 禁止引入 A 模式禁用函数 / 异步服务健康检查必须用异步探测）
- [x] T049 编写权威方案文档 `docs/mongo-to-panweidb-migration-plan.md`（实测事实 / 规模盘点 / 映射规则 / 覆盖范围与缺口 / 分阶段计划 / 风险 / 验收）
- [x] T050 更新 `docs/WORK_LOG.md` 与项目记忆

**Checkpoint**: R1 全部完成，可交付评审

---

## Phase 9: R2 — 兼容层接线（未开始）

**Goal**: 在 PanWeiDB 后端上跑通三服务测试套件，并补齐未覆盖能力。

- [ ] T051 [US1] 把 `MOGO_DATA_BACKEND` 细化为域级开关（如 `MOGO_DATA_BACKEND_<DOMAIN>`），使不同域可先后切换
- [ ] T052 [US2] 重写 25 处聚合管道调用（`$group` / `$match` / `$sort` / `$unwind` / `$lookup` / `$facet` 等）为 SQL
- [ ] T053 [P] [US2] 重写 6 处 `bulk_write` 调用
- [ ] T054 [P] [US2] 重写 `$elemMatch` 与 `$pull` 各 1 处
- [ ] T055 [US2] 逐点核对 202 处 `create_index` 的 unique / sparse / partial 语义，补齐缺失的索引语义或显式登记为可接受差异
- [ ] T056 [US2] 核对按对象类型比较主键的调用点，改为字符串比较
- [ ] T057 [US2] 核对正则使用点，改写 PCRE 专有断言
- [ ] T058 [US2] 投影下推为 SQL（消除 Python 侧裁剪的开销）
- [ ] T059 [US1] 三服务测试套件在 `MOGO_DATA_BACKEND=panweidb` 下全绿
- [ ] T060 [US1] 审计库分离：`get_audit_db()` 指向独立 schema，对齐 FR-17 保留期策略
- [ ] T061 补跑 `bash scripts/generate-hashes.sh document-parser --docker 3.10`，恢复锁定文件的单一生成来源
- [ ] T062 补齐 `/speckit-checklist` 与 `/speckit-analyze` 质量门禁，进入 implement → converge

---

## Clarify Decisions

| 问题 | 结论 | 记录位置 |
|---|---|---|
| 目标库是否支持 Mongo 线协议？ | 否（实测） | plan.md「目标库实测事实」 |
| 能否切到 PG 兼容模式？ | 否（`internal` 不可改 + 建库无 `DBCOMPATIBILITY`） | plan.md「Open Questions」 |
| 驱动选型 | psycopg3（同步 + 异步一套依赖） | plan.md「Technical Context」 |
| 兼容层是否抽共享包？ | 否，沿用每服务自包含 + 守卫防漂移 | plan.md「Structure Decision」 |
| 是否双写保证一致性？ | 否，用「先搬迁、后切换、可回滚」 | spec.md「Non-Goals」 |
| 主键对象类型如何处理？ | 归一为字符串并登记为已知差异 | plan.md「已知语义差异」 |
| document-parser 锁定文件？ | 手工合并 + 记录依据 + 登记补跑命令 | plan.md「Open Questions」/ T043 |

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1（Setup）**：无依赖，最先执行
- **Phase 2（Foundational）**：依赖 Phase 1，**阻塞全部用户故事**
- **Phase 3–7（US1–US5）**：依赖 Phase 2；US2/US3 可并行，US4/US5 可并行
- **Phase 8（Polish）**：依赖 Phase 3–7
- **Phase 9（R2）**：依赖 Phase 8

### User Story Dependencies

- **US1（后端可切换）**：无故事依赖 —— **是 US2–US5 的前置**
- **US2（调用点零修改）**：依赖 US1
- **US3（数据搬迁）**：依赖 US1；与 US2 并行开发（搬迁用原生 SQL 写入，回读验证时才依赖 US2）
- **US4（建表自动化）**：依赖 US1；与 US2/US3 并行
- **US5（显式失败）**：依赖 US2（门面存在才有「未覆盖」的概念）

### Within Each User Story

- 编译核心（过滤 / 更新）先于集合方法
- 集合方法先于真实库端到端验证
- 异步版先于同步版（同步版由异步版机械变换生成）

### Parallel Opportunities

- T003 / T004（能力探测与规模盘点）可并行
- T007 / T008（异步池与同步池）可并行
- T017 / T021（过滤与更新算子）可并行
- T029 / T030（演练与校验模式）可并行
- T035 / T036（DDL 生成与巡检）可并行
- T041 / T044 / T045 / T046（依赖与配置落位）可并行
- T047 / T048（单测与守卫）可并行

---

## Implementation Strategy

### MVP First（US1）

Phase 1 → Phase 2 → Phase 3。**此时即可交付**：后端可切换、默认零影响、可即时回滚，
风险已被隔离在开关之后。

### Incremental Delivery

1. US1 完成 → 可开关（安全阀就位）
2. US2 完成 → 调用点零修改可读写（路线可行性得证）
3. US3 完成 → 数据可搬迁可校验
4. US4 + US5 完成 → 运维可自动化、缺口可枚举
5. Polish 完成 → R1 可评审

### 验证基线（R1 实测结果）

| 项 | 结果 |
|---|---|
| 兼容门面（异步） | **64 / 64** |
| 兼容门面（同步） | **26 / 26** |
| 搬迁全链路 | 演练 / 搬迁 / 幂等重跑 / 校验 / 门面回读 **全部通过** |
| DDL | 103 表 / 309 索引，**1.6s** |
| 纯逻辑单测 | **29 / 29** |
| 一致性守卫 | **11 / 11** |
| 依赖锁完整性安装 | 三个服务**全部通过** |
| `db.py` 双分支 | 默认不变 / 切换可用 / 参数缺失显式失败 |

---

## Notes

- R1 任务全部勾选并附实测证据；R2 任务为规划项，进入前应先跑 `/speckit-analyze`。
- 本特性属「既有工作回溯补规格」：R1 代码先于 spec 落地（与本仓库 003–006 的处理方式
  一致），R2 起严格按 spec → plan → tasks → implement 推进。
- 未覆盖能力按 FR-016 显式失败，因此 R2 的实际工作量可在切换后由异常日志**精确枚举**，
  无需靠人工通读 612 处调用点。
