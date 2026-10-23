# Implementation Plan: MongoDB → PanWeiDB 数据后端迁移

**Branch**: `feat/migrate-mongo-to-panweidb` | **Date**: 2026-10-13 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/027-mongo-to-panweidb-migration/spec.md`

## Summary

在三个后端服务的数据访问入口（`app/core/db.py`）之下引入 **PanWeiDB 后端**与
**兼容门面**，使既有 612 处业务调用点无需改写即可读写新库；用一个环境变量
（`MOGO_DATA_BACKEND`）在后端间切换，默认保持 MongoDB 且行为不变。

技术路线：**集合 → 单表 + JSON 文档列**（`id` / `tenant_id` / `doc JSONB` /
时间戳），字段一律走 JSON 路径表达式访问，因此**新增业务字段不需要 DDL 变更**。
驱动选 **psycopg3**（同时提供同步与异步 API，一个依赖替代 pymongo 与 motor）。

权威方案文档：`docs/mongo-to-panweidb-migration-plan.md`（含完整映射规则表与风险清单）。

## Technical Context

**Language/Version**: Python 3.13（admin-api / chat-api）、Python 3.10（document-parser）

**Primary Dependencies**:
- 新增：`psycopg[binary]`（同步 + 异步连接）、`psycopg-pool`（连接池）
- 保留：`motor` / `pymongo`（默认后端路径完全不变）

**Storage**: PanWeiDB 3.2.0（openGauss 内核）作为新增后端；MongoDB 6.0.20 保留为默认

**Testing**: pytest；新增纯逻辑单测（不依赖数据库）+ 守卫测试（防漂移、防禁用函数）
+ 真实 PanWeiDB 端到端验证脚本

**Target Platform**: Linux 容器（docker compose）；本地 OrbStack 验证

**Project Type**: web-service（三服务单仓库，各自独立镜像）

**Performance Goals**: 建表 114 张 ≤ 10s（实测 1.6s）；查询走主键/租户/JSON 表达式索引；
兼容门面无额外往返（隐式建表仅在首次操作时发生）

**Constraints**: 目标库 `sql_compatibility=A` 固定不可改（见下）；兼容层不得使用
该模式下被禁用的 JSON 函数/运算符；默认后端路径不得引入任何额外连接

**Scale/Scope**: 3 服务 / 149 文件 / 612 处数据访问入口 / 103 个集合 / 8 个 compose 服务条目

### 目标库实测事实（2026-10-13，改代码前必读）

| 项 | 实测值 |
|---|---|
| 镜像 | `registry.cn-shenzhen.aliyuncs.com/shine_fei/panweidb:3.2.0`（arm64） |
| 内核 | openGauss 系；`version()` 报 `PostgreSQL 9.2.4 on aarch64` |
| 兼容模式 | `sql_compatibility = A`（Oracle 模式）；`pg_settings.context = internal` → **不可改** |
| 建库选项 | PanWeiDB 3.2 的 `CREATE DATABASE` **不支持** `DBCOMPATIBILITY` |
| 端口 / 认证 | 5432；`password_encryption_type = 1`（**MD5**） |
| 远程账号 | `boncuser` 可远程连；`omm` 远程被拒（openGauss initial user 保护） |
| `pg_hba` | local / 127.0.0.1 = `trust`；`0.0.0.0/0` = `md5` |
| 线协议兼容 | **无 MongoDB 兼容**（那是金仓 KingbaseES 的能力） |

**A 模式下的 JSON 能力子集**（实测）：

- **可用**：`jsonb_set`、`jsonb_typeof`、`jsonb_array_length`、`to_jsonb`、`||`、
  `@>`、`?`、`jsonb_agg`、`jsonb_array_elements`、`jsonb_extract_path(_text)`、
  `jsonb_insert`、`jsonb_path_query`、`jsonb - text`、`jsonb - int`、`jsonb_delete`、
  GIN 算子类 `jsonb_ops`（可建，但见下）
- **不可用**（报 `FeatureNotSupported: ... is only supported in PG-format database`）：
  `jsonb_build_array`、`jsonb_build_object`、`#-`、`jsonb_strip_nulls`、
  `jsonb_pretty`、`jsonb_to_record`、`jsonb_object_agg`、`jsonb_path_ops`（GIN 算子类）

### GIN 索引不可用（openGauss 缺陷，真实数据入库时踩到）

`USING GIN (doc jsonb_ops)` **遇到任何空字符串值就报错**：
`jsonb_gin.cpp : 519 : The parameter destMax is equal to zero or larger than the macro`。
顶层与嵌套值都触发；空数组 / 空对象 / `null` 正常。**表里只要已有一行含空串，
连 `CREATE INDEX` 本身都会失败**，因此不能靠「先建索引再灌数据」绕开。

实测对照（同一张含空串的表）：无索引 ✅ / `btree (tenant_id)` ✅ /
`btree ((doc #> '{f}'))` ✅ / `GIN (doc jsonb_ops)` ❌。

**结论：建表 DDL 只建 `tenant_id` btree 索引，不建 GIN。** 代价可控——GIN 只服务于
`@>` / `?`，而兼容层里只有 `$all` 用到 `@>`（全代码库 1 处）。已固化为守卫测试。

### 三个必须规避的语义差异（R1 已全部修复并加回归）

1. **`jsonb_set` 不创建中间层对象**（PostgreSQL 会）。openGauss 下
   `jsonb_set('{"x":1}', '{a,b}', v, true)` 原样返回 → `{"$set": {"a.b": 1}}`
   在 `a` 不存在时**静默丢更新**。
   **对策**：`_jsonb_set_path()` 逐层回卷（内层 → 父层 → 收口），既补中间层又保留
   同级字段，实现真正的深合并。
2. **`#-` 删路径运算符不可用**。**对策**：`_unset_expression()` 改用
   「取出父节点 → `-` 删键 → `jsonb_set` 写回」，并用 `create_if_missing=false`
   保证父节点缺失时是 no-op。
3. **嵌套表达式会让占位符重复**，psycopg 报 `query has N placeholders but M parameters`。
   **对策**：更新算子编译成 `WITH s0/s1/...` **步骤链**，每步只引用上一步的列名
   `doc`，占位符恰好出现一次。

### 表结构与访问约定

```sql
CREATE TABLE IF NOT EXISTS "<schema>"."<collection>" (
    id         TEXT PRIMARY KEY,        -- str(_id)
    tenant_id  TEXT,                    -- 从文档提升，用于租户隔离与批量清理
    doc        JSONB NOT NULL,          -- 完整文档（含 _id）
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX "<collection>_tenant_idx" ON ... (tenant_id);
-- 刻意不建 GIN：openGauss 的 jsonb GIN 索引遇空字符串即报错（见「GIN 索引不可用」节）
```

- **只建 `tenant_id` btree 索引，不建 GIN**（见「GIN 索引不可用」节）。按字段过滤的
  表达式索引由各服务启动时的 `ensure_indexes()` 通过门面的 `create_index` 建立。
- **隐式建表**：门面首次操作某集合时执行 `CREATE TABLE IF NOT EXISTS`，对齐文档
  数据库「首次写入隐式建集合」的语义。
- 审计库：MongoDB 侧用独立 database，PanWeiDB 侧用独立 **schema**
  （`PANWEIDB_AUDIT_SCHEMA`）作为等价隔离手段。

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 原则 | 合规性 | 说明 |
|---|---|---|
| I. Specification-First (NON-NEGOTIABLE) | ✅ | 本特性已补 spec.md（027）；R1 代码先于 spec 落地，属「既有工作回溯补规格」，与本仓库 003–006 的处理方式一致；R2 起严格按 spec → plan → tasks → implement 推进 |
| II. Enterprise Production Readiness | ✅ | 开关式回滚（FR-001/FR-004）；健康检查暴露后端与可达性（FR-006）；未覆盖能力显式失败，不引入不可观测的失败路径（FR-016） |
| III. Security and Data Protection | ✅ | 连接口令只经环境变量/`.env`，不落仓库；搬迁工具**只读源库**（FR-022）；连接目标在日志与健康检查中脱敏（不含口令） |
| IV. Cross-Platform and i18n | ✅ | 连接显式声明 UTF-8，保证中文往返一致；不涉及界面文案变更 |
| V. Observability and Simplicity | ✅ | 结构化日志；**默认后端零额外开销**（惰性初始化，FR-002）；按 YAGNI 不引入双写/双读 |

**结论**：无违反项，无需 Complexity Tracking 例外。

## Project Structure

### Documentation (this feature)

```text
specs/027-mongo-to-panweidb-migration/
├── spec.md              # 需求规格（本特性的"做什么/为什么"）
├── plan.md              # 本文件（技术方案）
├── tasks.md             # 任务清单（R1 已勾选）
├── quickstart.md        # 可执行的验证清单
└── checklists/
    └── requirements.md  # 需求质量评审清单
```

### Source Code (repository root)

```text
services/<svc>/app/core/
├── pg.py           # 新增：psycopg3 连接池（同步 / 异步）、DSN 组装、健康探测
├── pg_compat.py    # 新增：Mongo 兼容门面（Motor / PyMongo 子集）
├── db.py           # 改造：按 MOGO_DATA_BACKEND 分派后端
└── config.py       # 改造：新增 MOGO_DATA_BACKEND + PANWEIDB_* 配置项

services/<svc>/app/main.py            # 改造：init_db/close_db → init_backend/close_backend
services/document-parser/app/api/routes/health.py   # 改造：/health 与 /ready 上报后端

services/admin-api/tests/test_pg_compat.py          # 新增：纯逻辑单测（29 项）
deploy/tests/test_pg_compat_parity.py               # 新增：一致性守卫（11 项）

scripts/pg/
├── generate_ddl.py                   # 新增：集合扫描 → 幂等 DDL + 连库巡检
└── migrate_mongo_to_panweidb.py      # 新增：幂等搬迁 + 计数校验 + 续跑

deploy/pg/schema.sql                  # 新增：103 集合建表 DDL（生成物）
docs/mongo-to-panweidb-migration-plan.md            # 新增：权威方案文档

services/<svc>/requirements.in        # 改造：新增 psycopg 依赖声明
services/<svc>/requirements.txt       # 改造：重生成（带哈希）
services/<svc>/.env.example           # 改造：新增开关与连接参数示例
docker-compose.yml                    # 改造：4 个服务条目注入开关与连接参数
```

**Structure Decision**: 沿用仓库既有的**每服务自包含**结构（构建上下文为
`./services/<svc>`，`COPY app /app/app`）。兼容层因此在三处存在副本，
与既有的 `db.py` / `config.py` 处理方式一致；副本漂移由
`deploy/tests/test_pg_compat_parity.py` 守卫（异步两份逐字节一致，同步那份必须是
异步版的机械变换结果）。不为此引入新的构建上下文或共享包，避免影响发布流水线。

## 映射规则

### 过滤条件

| 文档数据库 | 目标库实现 |
|---|---|
| `{f: v}` / `{"$eq": v}` | `(doc #> '{f}') = %s::jsonb` |
| `{"$ne": v}` | `(doc #> '{f}' IS NULL OR doc #> '{f}' <> %s::jsonb)`（含字段缺失语义） |
| `{"$gt/$gte/$lt/$lte": v}` | 数值：`(CASE WHEN jsonb_typeof(...)='number' THEN (doc#>>'{f}')::numeric END) > v`；否则文本比较 |
| `{"$in": [...]}` / `{"$nin": [...]}` | `(doc #> '{f}') IN (%s::jsonb, ...)` / `IS NULL OR NOT IN (...)` |
| `{"$exists": true}` | `(doc #> '{f}') IS NOT NULL` |
| `{"$regex": p, "$options": "i"}` | `(doc #>> '{f}') ~* %s`（无 `i` 则 `~`） |
| `{"$size": n}` | `jsonb_array_length(...) = n`（先判 `jsonb_typeof='array'`） |
| `{"$all": [...]}` | 逐项 `doc #> '{f}' @> %s::jsonb` |
| `$or` / `$and` / `$nor` / `$not` | `OR` / `AND` / `NOT (OR)` / `NOT (...)` |
| 点号路径 `a.b` | `doc #> '{a,b}'` |

### 更新算子

更新编译为 **步骤链**（每步只引用上一步的 `doc` 列）：

```sql
WITH s0 AS (SELECT id, doc FROM t WHERE <filter> LIMIT 1),
     s1 AS (SELECT id, jsonb_set(doc, '{age}', %s::jsonb, true) AS doc FROM s0),
     s2 AS (SELECT id, <step2> AS doc FROM s1)
UPDATE t AS tgt SET doc = s2.doc, updated_at = now() FROM s2 WHERE tgt.id = s2.id
```

| 文档数据库 | 目标库实现 |
|---|---|
| `$set` | `_jsonb_set_path()`（逐层回卷，真深合并） |
| `$setOnInsert` | 仅 upsert 插入路径生效（Python 侧合成文档） |
| `$unset` | 顶层 `doc - 'k'`；嵌套 `jsonb_set(doc,'{a}', COALESCE(doc#>'{a,b}','{}') - 'c', false)` |
| `$inc` | `jsonb_set(doc,'{f}', to_jsonb(COALESCE((doc#>>'{f}')::numeric,0)+n), true)` |
| `$max` / `$min` | `GREATEST` / `LEAST` |
| `$push`（含 `$each`） | `COALESCE(doc#>'{f}','[]') \|\| %s::jsonb`（不用 `jsonb_build_array`） |
| `$addToSet`（含 `$each`） | `CASE WHEN arr @> item THEN arr ELSE arr \|\| item END` |
| `$currentDate` | `to_jsonb(now())` |

### 覆盖范围与缺口

**R1+R2 已覆盖**：

- 过滤算子：等值 / `$ne` / 范围（数值与文本）/ `$in` / `$nin` / `$exists` / `$regex`(含 `$options`) /
  `$size` / `$all` / `$elemMatch` / `$or` / `$and` / `$nor` / `$not` / 点号嵌套路径
- 更新算子：`$set` / `$setOnInsert` / `$unset` / `$inc` / `$max` / `$min` / `$push`(含 `$each`) /
  `$addToSet`(含 `$each`) / `$pull` / `$currentDate`
- 集合 API：`find_one` / `find` / `insert_one` / `insert_many` / `replace_one` / `update_one` /
  `update_many` / `find_one_and_update` / `delete_one` / `delete_many` / `count_documents` /
  `distinct` / `create_index` / `create_indexes` / `list_collection_names` / `command` /
  **`aggregate`** / **`bulk_write`**
- 聚合：阶段 `$match` / `$group` / `$sort` / `$limit` / `$skip` / `$count` / `$project`；
  累加器 `$sum` / `$avg` / `$min` / `$max` / `$push` / `$addToSet` / `$first` / `$last` / `$count`；
  表达式 `$ifNull` / `$cond` / 比较 / `$and` / `$or` / `$not` / `$add` / `$subtract` /
  `$multiply` / `$divide` / `$max` / `$min` / `$literal` / `$percentile`

**R2 精确盘点后修正的范围**（R1 阶段曾高估）：

| 未覆盖项 | 实际出现次数 | 说明 |
|---|---|---|
| `$lookup` / `$facet` / `$unwind` / `$unionWith` / `$out` / `$merge` | **0** | 只出现在 `app/core/nosql_guard.py` 的**白名单常量**里，无实际调用。R1 的估算把白名单当成了使用 |
| `$elemMatch` / `$pull` | 0 | 同上（白名单常量） |

**仍未覆盖**（调用即抛 `PgCompatUnsupported`）：`$text` / geo / 稀疏/部分索引 /
`$setWindowFields` / `$geoNear`。

### 已知语义差异（R2 需逐点核对）

| 差异 | 影响 |
|---|---|
| `_id` 由对象类型变字符串 | 按字符串比较仍命中；按对象比较的调用点会失效 |
| 正则方言（PCRE vs ARE） | 复杂断言（lookahead 等）需改写 |
| 投影在 Python 侧裁剪 | 大文档投影有额外开销，R2 可下推 SQL |
| 唯一索引的稀疏/部分语义 | 无直接对应物，需逐点核对 202 处索引声明 |
| 索引方向 `-1` 被忽略 | btree 可双向扫描，不影响可用性 |

## 分阶段计划

### R1 — 基础设施（**已完成**）

连接池、兼容门面、后端分派、配置开关、健康检查、DDL 生成器、搬迁工具、
依赖接入、方案文档、单测与守卫。详见 `tasks.md` Phase 1–5。

### R2 — 兼容层接线（**已完成**，T069–T087）

实际交付：域级开关 `effective_data_backend_for`、聚合编译器（`$match`/`$group`/`$sort`/
`$limit`/`$skip`/`$count`/`$project` + 累加器/表达式）、`bulk_write`、索引对齐（202 处，
含 sparse/partial 与 7 处 TTL 应用层清理）、主键字符串化解耦（115 处）、同步副本生成器
`sync_pg_compat.py`、审计库分离。原计划 5 项：

1. **域级开关**：把 `MOGO_DATA_BACKEND` 细化到域级，使不同域可以先后切换。
2. **补齐缺口**：25 处聚合管道、6 处 `bulk_write`、`$lookup`/`$facet`/`$unwind`。
3. **索引对齐**：核对 202 处索引声明的 unique / sparse / partial 语义。
4. **全量回归**：三服务测试套件在 PanWeiDB 后端下全绿，逐条修复不兼容点。
5. **审计分库**：把 `get_audit_db()` 指向独立 schema，对齐 FR-17 保留期策略。

### R3 — 逐域关系化（**已完成**，2026-10-16）

已把 44 张表（✅ 全平铺 21 + 🔶 部分平铺 23）从「单表 + JSON」扁平化为真实列 + 索引
（455 列 + 44 索引，真库 0 错误）；兼容层经 `column_map.py` 双写，并在读路径 / 筛选 /
排序 / 去重 / 聚合首阶段路由到真实列。热点集合（`chat_sessions` / `chat_messages` /
`token_usage_logs` / `admin_accounts` / `end_users`）均已包含在内。详见
`docs/027-r3-relational-four-tables-plan.md` 与 `r3-flatten/`。

## Open Questions（已消解）

| 问题 | 结论 | 依据 |
|---|---|---|
| 目标库是否支持 Mongo 线协议？ | **否** | 实测；线协议兼容是金仓 KingbaseES 的能力 |
| 能否把目标库切到 PG 兼容模式以解除函数限制？ | **否** | `sql_compatibility` 是 `internal` 上下文不可改；3.2 的 `CREATE DATABASE` 不支持 `DBCOMPATIBILITY` |
| 驱动选 psycopg3 还是 asyncpg？ | **psycopg3** | 同时提供同步与异步 API，一个依赖替代 pymongo 与 motor；asyncpg 在目标库上报的 9.2.4 版本串下有特性门控风险 |
| 兼容层放共享包还是每服务一份？ | **每服务一份** | 与仓库既有架构一致（构建上下文为服务目录）；漂移由守卫测试防 |
| 是否双写以保证迁移期一致性？ | **否** | 改用「先搬迁、后切换、可回滚」；双写引入难以验证的一致性问题（见 spec Non-Goals） |
| `_id` 的对象类型如何落库？ | **归一为字符串** | JSON 列存不下对象类型；已在方案文档中登记为已知差异 |
| document-parser 的锁定文件如何生成？ | **手工合并 + 记录依据** | Docker Hub 与 DaoCloud 镜像均不可达，无法用 `--docker 3.10`；已验证哈希覆盖该版本全部发行文件（含全部 cp310 wheel），与 Python 版本无关。网络恢复后应补跑 `bash scripts/generate-hashes.sh document-parser --docker 3.10` |

## Complexity Tracking

> 无 Constitution Check 违反项，本节留空。

## 风险与缓解

| # | 风险 | 等级 | 缓解 |
|---|---|---|---|
| 1 | 兼容模式固定导致 JSON 函数受限 | 高 | 已实测出可用子集并内联规避；守卫测试禁止引入禁用函数（FR-025） |
| 2 | `jsonb_set` 不建中间层导致静默丢更新 | 高 | 已用逐层回卷修复 + 专项回归用例 |
| 3 | 612 处调用点仍可能用到未覆盖算子 | 中 | 未覆盖即抛显式异常（FR-016） |
| 4 | `min()`/`max()` 聚合对 jsonb 按**文本**比较 | 高 | `$min`/`$max` 改用 `(array_agg(x ORDER BY x))[1]`；差分测试已覆盖 |
| 5 | 兼容层三份副本漂移 | 中 | `scripts/pg/sync_pg_compat.py` 为唯一变换来源 + `deploy/tests/test_pg_compat_parity.py` 守卫 |
| 6 | 唯一索引的稀疏/部分语义差异 | 中 | `unique` 已支持；稀疏/部分索引无直接对应物，R3 按需核对 |
| 7 | 投影在 Python 侧裁剪 | 低 | R3 下推 SQL |
| 8 | 本地镜像源不可达影响锁定文件生成 | 低 | 已记录补跑命令；哈希与 Python 版本无关已验证 |
| 9 | `$percentile` 口径差异（Mongo 近似 vs PanWeiDB 精确） | 低 | 代码已有 `try/except` 兜底到 `_duration_percentiles_fallback()`，两条路径均可用 |

## R4 — 收尾补充（compose 一体化 + 真库 bug 修复，2026-10-22）

R1/R2/R3 全部落地后，027 还补齐了两块收尾工作，使 PanWeiDB 从「手工 `docker run` 的独立容器」升级为「compose 一体化生命周期」，并消除真实库下的一个查询型缺陷。两者不改变既有 FR/Non-Goals（默认后端仍为 mongo、开关式回滚不变）。

### R4.1 PanWeiDB 纳入 compose 一体化管理（commit `78205d6`）

**背景**：原先 PanWeiDB 是手工 `docker run` 的独立容器——PID 1 是 `tail -f /dev/null`、数据库不随容器启动（要人肉 `gs_ctl start`）、数据在容器可写层（`docker rm` 即全丢）、容器不在 compose 项目内（`./mogo up/down` 看不到它）。

**改造**：

- `docker-compose.yml` 新增 `panweidb` 服务，挂 `panweidb` profile（默认不启动，镜像只本地 arm64 交付、默认后端仍是 mongo）；数据落命名卷 `panweidb-storage`；同时挂 `public` + `backend`（backend 是 internal 网络，其上发布端口宿主不可达，宿主工具按 `127.0.0.1:5432` 连库）。
- 新增 `deploy/panweidb/entrypoint.sh` 作为 PID 1 supervisor：首次解包二进制、`gs_initdb`、写 `pg_hba`/`license`/`version`，`gs_ctl start` + 守活，`SIGTERM` 时 `gs_ctl stop -m fast` 并等 `postmaster.pid` 消失才退出。
- 四个应用服务加 `depends_on: panweidb {condition: service_healthy, required: false}`（指向未启用 profile 的服务会让 compose 直接解析失败）；`PANWEIDB_HOST` 默认改服务名。
- `deploy/cli/images.sh`：后端切到 panweidb 时 `mogo_compose` 自动带 `--profile panweidb`，一个开关管住两件事。
- `mogo` CLI：启动前检查 panweidb 镜像，缺失时提前失败而不是让应用卡在连库超时。

**收益**：`MOGO_DATA_BACKEND=panweidb docker compose --profile panweidb up -d` 即可把目标库与三应用一并拉起/停止/回收，数据持久化到命名卷，生命周期与栈一致。

### R4.2 修复 dashboard /overview 500（commit `db5370f`）

PanWeiDB 的 `timestamptz` 经兼容层返回 **ISO 字符串**而非 `datetime`，导致 admin-api dashboard 汇总查询在真实 PanWeiDB 后端下 500；已在读取路径统一序列化口径修复。属于 R3 关系扁平化后真实列读取路径的收尾缺陷修复（FR-002/FR-015 的"字段形状一致"承诺在 dashboard 场景的兑现）。

### R4 涉及的新增/改动文件

```text
docker-compose.yml                  # 新增 panweidb 服务（panweidb profile）+ 四应用 depends_on
deploy/panweidb/entrypoint.sh       # 新增：PID 1 supervisor（解包/gs_initdb/gs_ctl start/守活/优雅停）
deploy/cli/images.sh               # 改造：切 panweidb 时自动带 --profile panweidb
mogo（CLI）                          # 改造：启动前检查 panweidb 镜像，缺失提前失败
services/admin-api/app/...          # 修复 timestamptz 读取路径序列化（dashboard 500）
```
