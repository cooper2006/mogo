# MongoDB → PanWeiDB 迁移方案

| 项 | 值 |
|---|---|
| 分支 | `feat/migrate-mongo-to-panweidb`（基于 `main` @ `1d0b1fc` / v0.2.1） |
| 状态 | **R1（基础设施）已落地并实测通过**；R2（兼容层接线）未开始 |
| 回滚方式 | 环境变量开关 `MOGO_DATA_BACKEND=mongo`（默认），**不需要回滚代码** |
| 目标库 | PanWeiDB 3.2.0（openGauss 内核），OrbStack 容器 `panweidb`，端口 5432 |

---

## 1. 结论摘要

1. **这是一次「文档模型 → 关系模型」的范式迁移，不是换连接串。** 涉及 3 个服务、
   149 个文件、612 处 `get_db()`、103 个集合。
2. **PanWeiDB 不提供 MongoDB 线协议兼容**（那是金仓 KingbaseES 的能力）。
   因此只有两条路：自建兼容层，或把 612 处调用点改写成 SQL。
3. **既定路线（用户 2026-10-13 确认）：兼容层先行**——把集合映射成
   `(id, tenant_id, doc JSONB)` 单表，在 `app/core/db.py` 后面实现一个形状与
   motor/pymongo 一致的门面，使业务调用点几乎不用改。
4. **R1 已完成且实测通过**：连接池、配置开关、后端分派、兼容门面、DDL 生成器、
   数据搬迁工具、健康检查接入。兼容门面在真实 PanWeiDB 上 **64/64（异步）+
   26/26（同步）** 通过；搬迁工具在真实 MongoDB → PanWeiDB 上完成
   「演练 / 搬迁 / 幂等重跑 / 校验 / 门面回读」全链路验证。
5. **关键约束（务必先读第 5 节）**：PanWeiDB 的 `sql_compatibility` 固定为 `A`
   （Oracle 模式）且**不可修改**，该模式下多个标准 JSONB 函数/运算符被禁用，
   兼容层必须在其子集内实现。

---

## 2. 目标库实测事实

2026-10-13 在用户本机 OrbStack 的 `panweidb` 容器上实测。

### 2.1 实例信息

| 项 | 实测值 |
|---|---|
| 镜像 | `registry.cn-shenzhen.aliyuncs.com/shine_fei/panweidb:3.2.0` |
| 内核 | openGauss 系；`version()` 报 `PostgreSQL 9.2.4 on aarch64` |
| 兼容模式 | `sql_compatibility = A`（Oracle 模式），`pg_settings.context = internal` → **不可改** |
| 端口 / 认证 | 5432；`password_encryption_type = 1`（**MD5**） |
| 建库选项 | `CREATE DATABASE` **不支持** `DBCOMPATIBILITY`（PanWeiDB 3.2 已移除） |
| 已有库 | `bonc`（owner `boncuser`）、`panweidb`、`postgres`、`testdb` |
| 远程账号 | `boncuser` 可远程连；`omm` 远程被拒（openGauss 的 initial user 保护） |
| `pg_hba` | local/127.0.0.1 = `trust`；`0.0.0.0/0` = `md5` |

### 2.2 驱动选型：psycopg3

已实测通过：**同步连接、异步连接（`AsyncConnection`）、`AsyncConnectionPool`、
`Jsonb` 适配器、参数绑定、事务上下文、`client_encoding=UTF8` 中文往返**。

选择 psycopg3 的理由：它同时提供同步与异步 API，可以**一个依赖同时替代
pymongo 与 motor**，避免引入第二套驱动。

> 未选 asyncpg：openGauss 的 `server_version` 报 9.2.4，asyncpg 的协议/特性门控
> 在该版本串下有已知风险，且社区实践普遍使用 psycopg2/psycopg3 对接 openGauss。

### 2.3 A 模式下的 JSONB 能力（**关键约束**）

| 可用 ✅ | 不可用 ❌ |
|---|---|
| `jsonb_set` | `jsonb_build_array` |
| `jsonb_typeof` | `jsonb_build_object` |
| `jsonb_array_length` | `#-`（删路径运算符） |
| `to_jsonb` | `jsonb_strip_nulls` |
| `\|\|`（合并） | `jsonb_pretty` |
| `@>` / `?` | `jsonb_to_record` |
| `jsonb_agg` | `jsonb_object_agg` |
| `jsonb_array_elements` | `jsonb_path_ops`（GIN 算子类） |
| `jsonb_extract_path(_text)` | |
| `jsonb_insert` / `jsonb_path_query` | |
| `jsonb - text` / `jsonb - int` / `jsonb_delete` | |
| GIN 算子类 `jsonb_ops`（可建，但见 2.5 —— **实际不可用**） | |

不可用函数在调用时报
`FeatureNotSupported: ... is supported only in PG-format database`。

**规避手法已内联在 `pg_compat.py`**（`_unset_expression`、`$push` 分支），
修改该模块时不要引入上表右侧的函数。

### 2.5 GIN 索引不可用（**openGauss 缺陷，R1 实测踩到**）

`USING GIN (doc jsonb_ops)` **遇到任何空字符串值就报错**：

```
jsonb_gin.cpp : 519 : The parameter destMax is equal to zero or larger
than the macro : SECUREC_STRING_MAX_LEN
```

- **触发条件**：文档里存在空字符串值（顶层与嵌套值都触发）。
  空数组、空对象、`null`、非空字符串均正常。
- **更麻烦的是**：表里只要**已有一行**含空串，**连 `CREATE INDEX` 本身都会失败**，
  所以不能靠「先建索引再灌数据」绕开。
- **实测对照**（同一张含空串的表，逐项验证）：

  | 索引类型 | 结果 |
  |---|---|
  | 无索引 | ✅ 可写 |
  | `btree (tenant_id)` | ✅ 可写 |
  | `btree ((doc #> '{f}'))`（兼容层 `create_index` 的形态） | ✅ 可写 |
  | `GIN (doc jsonb_ops)` | ❌ 报错 |

- **结论：建表 DDL 只建 `tenant_id` btree 索引，不建 GIN。**
- **代价可控**：GIN 只服务于 JSONB 包含/键存在性查询（`@>` / `?`），而兼容层里
  只有 `$all` 用到 `@>`（全代码库 **1 处**）。按字段过滤走
  `doc #> '{f}'` 表达式索引（各服务启动时的 `ensure_indexes()` 建立），
  租户过滤走 `tenant_id`，主键查询走主键索引。
- 该约束已固化为守卫测试
  （`deploy/tests/test_pg_compat_parity.py::test_ddl_generator_does_not_emit_gin_index`），
  防止后续修改重新引入 GIN。

### 2.6 聚合与排序相关的偏差（**R2 实测踩到**）

| 偏差 | 影响 | 规避 |
|---|---|---|
| `min()` / `max()` **聚合**作用在 jsonb 上按**文本**比较（PostgreSQL 按 jsonb 类型序） | `$max` 在 `999` 与 `4343` 之间会取到 `"999"`（字典序） | `$min`/`$max` 改用 `(array_agg(x ORDER BY x))[1]` —— jsonb 的**排序运算符本身是正确的** |
| `min(jsonb)` / `max(jsonb)` 的**返回类型是 `text`**，不是 jsonb | 外层 `jsonb_set` 报 `function jsonb_set(jsonb, unknown, text, boolean) does not exist` | 同上（不再用 min/max 聚合） |
| 不支持 `FILTER (WHERE ...)` 聚合子句（PG 9.4+） | 报 syntax error | 改子查询或 `sum(case when ... then 1 else 0 end)` |
| `GROUP BY <expr>` 与 `SELECT <同一 expr 但套了 ::text>` 被判定为不同表达式 | 报 `column "..." must appear in the GROUP BY clause` | 用 `GROUP BY 1`（按输出列序号），并把文档组装拆到第二个 CTE |
| `jsonb_build_object` / `jsonb_build_array` 不可用 | 无法直接构造对象/数组 | 对象用 `jsonb_set` 链；数组用 `'[]'::jsonb \|\| elem` |

**可用的能力**（实测）：`array_agg(x ORDER BY y)`、`jsonb_agg(DISTINCT x)`、
`percentile_cont` / `percentile_disc`（有序集聚合）、`jsonb` 的排序运算符、
`jsonb_set` 的参数化路径、`(jsonb #>> '{}')::numeric`、`GROUP BY jsonb`。

### 2.7 `$percentile` 与 MongoDB 版本

`$percentile` 是 **MongoDB 7.0+** 才有的表达式；当前栈的 MongoDB 6.0.20 **不支持**，
会报 `Unknown expression $percentile`。`dashboard.py` 已经用 `try/except` 兜底到
`_duration_percentiles_fallback()`（`find()` + Python 侧算分位数），因此：

- 在 MongoDB 6.0 上：走兜底路径；
- 在 PanWeiDB 上：兼容层用 `percentile_cont` 直接算（精确值，而非 Mongo 7.0 的
  近似 t-digest），兜底路径保留。

两者结果口径略有差异（精确 vs 近似），但都在合理范围内，且代码路径一致。

### 2.4 另一处与 PostgreSQL 的语义差异（踩过）

**openGauss 的 `jsonb_set` 不会创建中间层对象**，而 PostgreSQL 会：

```sql
-- PG:      {"x":1,"a":{"b":2}}
-- PanWeiDB: {"x":1}          ← 原样返回，静默失效
jsonb_set('{"x":1}'::jsonb, '{a,b}', '2'::jsonb, true);
```

因此 `{"$set": {"profile.city": "上海"}}` 在 `profile` 不存在时会**静默丢更新**。
`_jsonb_set_path()` 用「逐层回卷」实现真正的深合并（内层 → 父层 → 收口），
既补中间层又保留同级字段。这是 R1 修掉的一个真实缺陷，已加回归用例。

### 2.8 `INSERT ... ON CONFLICT` 不可用（**2026-10-14 回归实测**）

openGauss 不支持 `ON CONFLICT DO NOTHING` 的无 target 形式，**带 target 也不行**：

```sql
-- 无 target
INSERT INTO t VALUES ('a',99) ON CONFLICT DO NOTHING
  -- FeatureNotSupported: Conflict without target is not yet supported within
  --   INSERT ON CONFLICT KEY DO UPDATE statement.

-- 带 target（无唯一约束）
INSERT INTO t VALUES ('a',99) ON CONFLICT (id) DO NOTHING
  -- InFailedSqlTransaction（首条事务已中止）

-- 带 target（有 PRIMARY KEY）
INSERT INTO t VALUES ('a',1) ON CONFLICT (id,n) DO NOTHING
  -- 同样不通过
```

**结论：幂等/去重写入必须靠"先查后写"，不能用 `ON CONFLICT`。** pg_compat 的写路径
本就采用先查后写（`find_one` 判定存在性后再 `insert` / `update`），因此不触发；但
数据搬迁工具、差分测试脚本、以及任何手写幂等 upsert 的 SQL 都必须遵守此约束。

> 附：同一轮实测还确认了一处**误记**——`SELECT count(*), id FROM t`（无 `GROUP BY`）
> 报 `GroupingError` 并非 openGauss 的特有差异，标准 PostgreSQL 报完全相同的错。
> 另 `SELECT count(*), id::text FROM t GROUP BY id` 实测通过，提示 §2.6 中
> 「`GROUP BY <expr>` 与 `SELECT <同一 expr 但套了 ::text>` 判定为不同表达式」的
> 边界比字面描述更窄（§2.6 的原始场景是 jsonb 表达式），值得复核。

### 2.9 主键 `_id` 类型归一化的调用点改造（T085，2026-10-14）

§4 已约定 `_id` 统一落成 hex **字符串**（`str(ObjectId)`，24 位十六进制）。本节为切流前的调用点核对结论。

**规模（仅 `app/` 应用代码）**：共 **115 处** 与 `_id`/`ObjectId` 强耦合——
71 处 `ObjectId(...)` 构造 + 44 处 `ObjectId.is_valid(...)`/`isinstance(_, ObjectId)` 守卫。
分布：admin-api 41（29 构造 / 12 守卫）、chat-api 65（43 构造 / 22 守卫）、document-parser 1。
重灾区：`chat-api` 的 `api/endpoints/{sessions(6), auth(6 构造/5 守卫)}`、`dsh_runtime/conversation/repository.py(7/5)`、`scheduled_tasks/{repository(3), runner(2), dsh_execution(3/1)}`；`admin-api` 的 `repositories/{model_repository(9), org_user_repository(8)}`、`api/routes/{traffic_allocations, analytics, position_roles, dashboard, directory, knowledge_documents}(共 22)`。

**三类失效模式**：

1. `ObjectId(x)` 构造查询 `_id`：迁移后 `_id` 为 24-hex 字符串，`ObjectId(x)` 仅当 `x` 合法 24-hex 才成功；若上层把任意用户输入直接 `ObjectId(...)` 会抛 `InvalidId`（Mongo 下同样抛，非新差异），但穿透到字符串后端时**应改为直接用字符串 `x`**，去掉多余转换与额外异常面。
2. `ObjectId.is_valid(s)` 守卫：`_id` 恒为 24-hex，结果与原一致，不影响；但若把 `is_valid` 当资源存在性之外的业务校验，需复核语义。
3. `isinstance(v, ObjectId)`：**必失效**——迁移后 `doc["_id"]` 与入参均为 `str`，判断恒为 `False`，会改变分支走向（如 `if isinstance(id, ObjectId): … else: str 规范化` 的 else 分支）。

**改造方向（R3 / 灰度切流前置）**：将 115 处与后端类型解耦——查询用 `str(x)`、校验改为字符串长度/hex 判断、`isinstance(_, ObjectId)` 改为字符串判断或删除。**未完成前不得把对应域切到 PanWeiDB**，否则第 3 类会静默改变分支、第 1 类会扩大异常面。

**现状**：已完成三服务（admin-api / chat-api / document-parser）解耦——新增 `app/core/ids.py`
提供 `to_backend_id`（归一化）、`to_backend_id_strict`（非法即抛错，替代原 `ObjectId(...)` 的
抛错语义）、`is_valid_backend_id`（合法性判定）。mongo 模式行为**不变**，panwei 模式一律字符串。
三服务 panwei 全量回归全绿。

---

## 3. 现状盘点

### 3.1 规模

| 指标 | 数量 |
|---|---|
| 涉及服务 | 3（admin-api / chat-api / document-parser） |
| `get_db()` / `get_audit_db()` 调用点 | **612** |
| 涉及文件（app 层） | **149** |
| 集合数（DDL 生成器扫描所得） | **103** |

服务分布：admin-api **303**、chat-api **302**、document-parser **7**。

### 3.2 驱动分裂

| 服务 | 驱动 | 特性 |
|---|---|---|
| admin-api | motor（异步） | 另有 `get_audit_db()`：审计与业务分库（FR-17/T044） |
| chat-api | motor（异步） | `get_db()` 在无事件循环时返回 `None` |
| document-parser | pymongo（同步） | 只用同步路径 |

迁移后统一为 psycopg3 的同步 / 异步连接。

### 3.3 API 与算子使用面

集合 API 调用次数（app 层）：

| API | 次数 | API | 次数 |
|---|---|---|---|
| `find_one` | 373 | `delete_many` | 31 |
| `update_one` | 269 | `delete_one` | 28 |
| `find` | 248 | `aggregate` | 25 |
| `create_index` | 202 | `find_one_and_update` | 17 |
| `insert_one` | 96 | `insert_many` | 12 |
| `count_documents` | 59 | `replace_one` | 11 |
| `update_many` | 33 | `distinct` | 8 |
| | | `bulk_write` | 6 |

聚合管道阶段：`$group` 26、`$match` 25、`$sort` 6、`$project` 2、`$unwind` 2、
`$limit` 2、`$count` 2、`$lookup` 1、`$facet` 1、`$skip` 1、`$addFields` 1、
`$replaceRoot` 1、`$unionWith` 1、`$sample` 1、`$out` 1、`$merge` 1。

**结论：聚合用得很少**（`aggregate()` 仅 25 处，且以 `$group`/`$match` 为主），
这是兼容层路线的最大利好——真正难翻译的 `$lookup`/`$facet`/`$graphLookup`
各只有 1 处（或 0 处），可以单独重写。

查询/更新算子：`$set` 305、`$in` 106、`$or` 56、`$ifNull` 50、`$setOnInsert` 48、
`$ne` 47、`$regex` 37、`$exists` 33、`$lt/$gt/$gte` 72、`$and` 14、`$unset` 12、
`$inc` 11、`$cond` 10、`$lte` 8、`$nin` 7、`$push` 4、`$addToSet` 3、`$each` 3、
`$slice` 2、`$all`/`$elemMatch`/`$size`/`$pull`/`$rename`/`$currentDate`/`$mul`/`$pop`/`$bit` 各 1。

---

## 4. 表结构与访问约定

**每个集合一张表，表名 = 集合名**：

```sql
CREATE TABLE "<schema>"."<collection>" (
    id         TEXT PRIMARY KEY,        -- str(_id)
    tenant_id  TEXT,                    -- 从文档提升，用于租户隔离与批量清理
    doc        JSONB NOT NULL,          -- 完整文档（含 _id）
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX "<collection>_tenant_idx" ON ... (tenant_id);
-- 刻意不建 GIN：见 2.5（openGauss 的 jsonb GIN 索引遇空字符串即报错）
```

设计要点：

- **字段一律走 JSONB 路径表达式**（`doc #> '{a,b}'`），**不预建列** →
  新增业务字段**不需要 DDL 变更**，这是兼容层能低成本落地的根本原因。
- `id` / `tenant_id` 提升为真实列，用于主键、租户过滤与 `tenant_purge` 的批量删除。
- **只建 `tenant_id` btree 索引**，不建 GIN（见 2.5）。按字段过滤的表达式索引由各服务
  启动时的 `ensure_indexes()` 通过兼容层的 `create_index` 建立。
- **隐式建表**：兼容层首次操作某集合时执行 `CREATE TABLE IF NOT EXISTS`，
  等价于 Mongo 的「首次写入隐式建集合」，避免启动期因表缺失而崩。

> 审计库：MongoDB 用独立 **database**（`ASKAI_ADMIN_AUDIT_DB`），PanWeiDB 侧
> 用独立 **schema**（`PANWEIDB_AUDIT_SCHEMA`）作为等价隔离手段。

---

## 5. 兼容层设计

### 5.1 位置与形态

```
services/<svc>/app/core/pg.py         # psycopg3 同步/异步连接池、DSN、健康探测
services/<svc>/app/core/pg_compat.py  # Mongo 兼容门面（Motor/PyMongo 子集）
services/<svc>/app/core/db.py         # 按 MOGO_DATA_BACKEND 分派
```

`get_db()` 在 PanWeiDB 模式下返回 `PgDatabase`，其形状对齐 motor 的 `Database`：

- `db["collection"]` / `db.collection` → `PgCollection`
- `db.command("ping")` / `db.list_collection_names()` 可用

`PgCollection` 提供 `find_one` / `find` / `insert_one` / `insert_many` /
`replace_one` / `update_one` / `update_many` / `find_one_and_update` /
`delete_one` / `delete_many` / `count_documents` / `distinct` / `create_index` /
`create_indexes`；`find()` 返回的游标支持 `sort/limit/skip`、
`await cursor.to_list(n)`、`async for`（同步版为 `for` 与 `len()`）。

### 5.2 过滤条件映射规则

| Mongo | SQL / JSONB |
|---|---|
| `{f: v}` | `(doc #> '{f}') = %s::jsonb` |
| `{f: {"$eq": v}}` | 同上 |
| `{f: {"$ne": v}}` | `(doc #> '{f}' IS NULL OR doc #> '{f}' <> %s::jsonb)`（含字段缺失语义） |
| `{f: {"$gt/$gte/$lt/$lte": v}}` | 数值：`(CASE WHEN jsonb_typeof(doc#>'{f}')='number' THEN (doc#>>'{f}')::numeric END) > v`；否则文本比较 |
| `{f: {"$in": [...]}}` | `(doc #> '{f}') IN (%s::jsonb, ...)` |
| `{f: {"$nin": [...]}}` | `IS NULL OR NOT IN (...)` |
| `{f: {"$exists": true}}` | `(doc #> '{f}') IS NOT NULL` |
| `{f: {"$regex": p, "$options": "i"}}` | `(doc #>> '{f}') ~* %s`（无 `i` 则 `~`） |
| `{f: {"$size": n}}` | `jsonb_array_length(...) = n`（先判 `jsonb_typeof='array'`） |
| `{f: {"$all": [...]}}` | 逐项 `doc #> '{f}' @> %s::jsonb` |
| `$or` / `$and` / `$nor` / `$not` | `OR` / `AND` / `NOT (OR)` / `NOT (...)` |
| 点号路径 `a.b` | `doc #> '{a,b}'` |

### 5.3 更新算子映射规则

**关键实现约束**：`UPDATE ... SET` 不允许对同一列多次赋值，且嵌套表达式会让
**占位符重复出现**（psycopg 报 placeholder/parameter 数量不符）。因此更新编译成
**步骤链**：

```sql
WITH s0 AS (SELECT id, doc FROM t WHERE <filter> LIMIT 1),
     s1 AS (SELECT id, jsonb_set(doc, '{age}', %s::jsonb, true) AS doc FROM s0),
     s2 AS (SELECT id, <step2> AS doc FROM s1)
UPDATE t AS tgt SET doc = s2.doc, updated_at = now() FROM s2 WHERE tgt.id = s2.id
```

每一步只引用上一步的列名 `doc`，占位符恰好出现一次。

| Mongo | 实现 |
|---|---|
| `$set` | `_jsonb_set_path()`（逐层回卷，真深合并） |
| `$setOnInsert` | 仅 upsert 插入路径生效（Python 侧合成文档） |
| `$unset` | 顶层 `doc - 'k'`；嵌套 `jsonb_set(doc,'{a}',COALESCE(doc#>'{a,b}','{}') - 'c',false)` |
| `$inc` | `jsonb_set(doc,'{f}',to_jsonb(COALESCE((doc#>>'{f}')::numeric,0)+n),true)` |
| `$max` / `$min` | `GREATEST` / `LEAST` |
| `$push`（含 `$each`） | `COALESCE(doc#>'{f}','[]') \|\| %s::jsonb` |
| `$addToSet`（含 `$each`） | `CASE WHEN arr @> item THEN arr ELSE arr \|\| item END` |
| `$currentDate` | `to_jsonb(now())` |

### 5.4 覆盖范围与缺口

**R1 已覆盖**：上表全部算子 + 全部列出的集合 API。

**R1 明确未覆盖**（调用即抛 `PgCompatUnsupported`，异常消息指向本文档）：

| 未覆盖项 | 代码中出现次数 | R2 处理方式 |
|---|---|---|
| `aggregate()` 管道 | 25 | 逐点重写为 SQL（`$group`/`$match` 为主，难度低） |
| `bulk_write` | 6 | 逐条展开为多次 `insert/update` 或单条 SQL |
| `$lookup` / `$facet` / `$unwind` / `$unionWith` | 各 1 | 单独重写为 JOIN / UNION |
| `$elemMatch` / `$pull` | 各 1 | 单独重写 |
| `$text` / `$near` / geo | 0 | 不需要 |

### 5.5 已知语义差异（消费侧需注意）

| 差异 | 说明 | 影响 |
|---|---|---|
| `_id` 类型 | JSONB 存不下 `ObjectId`，统一落成 hex **字符串**（T085 核对：115 处调用点受字符串化影响，见 §2.9） | `str(doc["_id"])` 无影响；`doc["_id"] == ObjectId(...)` 会不等 |
| `$regex` 方言 | Mongo 用 PCRE，PG 用 ARE | 复杂断言（lookahead 等）需改写 |
| 投影 | 在 Python 侧裁剪（R1 简化） | 大文档投影有额外内存/传输开销，R2 可下推 SQL |
| `$inc` / `$max` / `$min` | 走 `::numeric` 转换 | 仅支持数值字段 |
| 唯一索引 | 建在 `(doc #> '{f}')` 表达式上 | 与 Mongo 的 sparse/partial 索引语义不同，需逐点确认 |
| 索引方向 | 忽略 `-1` | PG btree 可双向扫描，不影响可用性 |
| TTL 索引（`expireAfterSeconds`） | openGauss **无原生 TTL 索引**等价物 | ✅ 7 处已由应用层清理实现：兼容层登记声明 + `purge_expired_ttl()` + 各服务 `ttl_purge_loop` 定期执行 |

**TTL 7 处清单与清理方案（已实现）**：openGauss 无 Mongo 的 TTL 索引机制。7 处 —— admin-api 3：`directory_repository`（`user_invite_expires_ttl`，`expires_at`,0）、`security/mfa_policy`（`mfa_used_steps_ttl`，`expires_at`,0）、`security/audit_events`（retention_days×86400）；chat-api 4：`security/mfa_policy`（`mfa_used_steps_ttl`）、`main`（`end_user_sessions`/`end_user_login_challenges`，`expires_at`,0）、`enterprise_capabilities/browser/engine/recording/store`（24h）。**实现**：兼容层 `create_index` 登记 `(collection, field, N)` 到 `_TTL_REGISTRY`；`purge_expired_ttl(pool, schema)` 执行 `DELETE FROM <schema>.<collection> WHERE (doc->>'<field>')::timestamptz <= now() - N 秒`；各服务 `app/core/ttl_purge.py` 的 `TtlPurgeLoop` 在 startup 起、shutdown 停（默认每小时，`MOGO_TTL_PURGE_INTERVAL_SECONDS` 可调；mongo 模式 no-op）。审计（admin `audit_events.purge_expired`）本就有应用层兜底。

---

## 6. 开关与回滚

```bash
# 默认：完全保持迁移前行为
MOGO_DATA_BACKEND=mongo        # 或不设

# 切到 PanWeiDB
MOGO_DATA_BACKEND=panweidb
PANWEIDB_HOST=127.0.0.1
PANWEIDB_PORT=5432
PANWEIDB_USER=boncuser
PANWEIDB_PASSWORD=...
PANWEIDB_DB=bonc
PANWEIDB_SCHEMA=mogo_dev
PANWEIDB_AUDIT_SCHEMA=mogo_audit   # 可选；缺省与业务同 schema
PANWEIDB_POOL_MIN_SIZE=1
PANWEIDB_POOL_MAX_SIZE=10
```

**回滚 = 把 `MOGO_DATA_BACKEND` 改回 `mongo` 并重启**，不需要回滚代码、不需要
数据回迁（MongoDB 侧数据保持原样、只读）。这是选择「开关切换」而非「硬切」的核心收益。

各服务还有带服务前缀的等价变量（`ASKAI_ADMIN_*` / `MOVO_DOC_PROCESSING_*`）；
规范变量 `MOGO_DATA_BACKEND` / `PANWEIDB_*` 不带前缀，便于三服务统一切换。

**健康检查**：三服务的 `/health`（document-parser 另有 `/ready`）会输出
`backend` 字段；PanWeiDB 模式下附带 `target` 与 `reachable`（真实探测）。

---

## 7. 分阶段计划

### R1 — 基础设施（**本分支已交付**）

| 交付物 | 状态 |
|---|---|
| `app/core/pg.py` × 3：同步/异步连接池、DSN 组装、健康探测、优雅关闭 | ✅ |
| `app/core/pg_compat.py` × 3：Mongo 兼容门面（异步 × 2 + 同步 × 1） | ✅ |
| `app/core/db.py` × 3：`MOGO_DATA_BACKEND` 分派，mongo 分支行为不变 | ✅ |
| `app/core/config.py` × 3：开关 + `PANWEIDB_*` 配置项与回退 | ✅ |
| 健康检查接入（`backend` / `target` / `reachable`） | ✅ |
| `scripts/pg/generate_ddl.py`：集合扫描（静态 + `--from-mongo` 权威来源）→ 幂等 DDL + 连库巡检 | ✅ |
| `scripts/pg/migrate_mongo_to_panweidb.py`：幂等搬迁 + `--prune` 对账 + 计数校验 | ✅ |
| `deploy/pg/schema.sql`：114 集合建表 DDL（**不含 GIN**，见 2.5） | ✅ |
| `requirements.in` × 3：psycopg 依赖声明 | ✅ |
| 真实 PanWeiDB 端到端验证（异步 64/64、同步 26/26、搬迁全链路） | ✅ |
| **GIN 索引缺陷发现与规避**（2.5）+ 守卫测试固化 | ✅ |
| **真实数据入库验证**（下节） | ✅ |

#### R1 真实数据入库实测（2026-10-13）

把本机运行中的 `mogo` 开发栈数据搬进了 PanWeiDB：

| 项 | 结果 |
|---|---|
| 源库 | 运行中的 `mogo-mongo-1`（MongoDB 6.0.20，`mogo_dev`，88 集合） |
| 目标 | PanWeiDB `bonc` 库的 `mogo_dev` schema，**115 张表 / 229 个 btree 索引 / 0 GIN** |
| 搬迁量 | **17,785 篇文档**，耗时 5.5s |
| 计数校验 | **88 个集合全部一致，不一致项 0** |
| 门面回读 | 13/13 通过（含中文字段、空字符串字段、布尔字段、`_id` 归一、深合并更新、未覆盖能力显式失败） |

> 网络备注：`mogo_backend` 是 `Internal=true` 的网络，容器既无外网也无法发布端口，
> 因此实测时用一个纯 stdlib 的 TCP 转发容器（双网络：默认 bridge 发布端口 +
> 接入 `mogo_backend` 连 mongo）把源库端口映射到宿主机，再在宿主机上跑工具。

### R2 — 兼容层接线（**本分支已交付**）

**先修正一处早先的估算失实**：R1 阶段曾按「25 处聚合管道 + 6 处 `bulk_write` +
`$lookup`/`$facet`/`$unwind` 各 1 处」估算 R2 范围。R2 精确盘点后发现
**`$lookup`/`$facet`/`$unwind`/`$unionWith`/`$out`/`$merge` 全部为 0 处** ——
它们只出现在 `app/core/nosql_guard.py` 的**白名单常量**里，没有任何实际调用。
同样 `$elemMatch` / `$pull` 也是 0 处。实际用到的阶段只有
`$match`(25) / `$group`(26) / `$sort`(5) / `$project`(1) / `$limit`(1) / `$count`(1)。

| 项 | 状态 |
|---|---|
| **聚合管道编译器**（`$match`/`$group`/`$sort`/`$limit`/`$skip`/`$count`/`$project`；累加器 `$sum`/`$avg`/`$min`/`$max`/`$push`/`$addToSet`/`$first`/`$last`；表达式 `$ifNull`/`$cond`/`$eq` 等比较/`$and`/`$or`/`$not`/`$add`/`$subtract`/`$multiply`/`$divide`/`$max`/`$min`/`$literal`/`$percentile`） | ✅ |
| **`bulk_write`**（`InsertOne`/`UpdateOne`/`UpdateMany`/`ReplaceOne`/`DeleteOne`/`DeleteMany`，结果对象对齐 pymongo） | ✅ |
| **审计库分离**（独立 schema + 未配置时回退 + schema 自举） | ✅ |
| **差分测试**：同一管道/同一批操作在 MongoDB 与 PanWeiDB 上跑并比对结果 | ✅ 聚合 11/11、`bulk_write` 8/8 |
| **纯逻辑单测**（聚合编译器，含占位符不变量与 openGauss 偏差回归） | ✅ +15 项（共 44 项） |
| **三服务全量回归** | 见下 |
| 逐域开关（`MOGO_DATA_BACKEND_<DOMAIN>`） | ✅ `effective_data_backend_for`（域级覆盖回退全局；逐域路由双池属 R3） |
| 202 处 `create_index` 的 unique/sparse/partial 语义逐点核对 | ✅ sparse/partial 已支持；实测 unique 34 处、sparse 3 处、partial 0 处；TTL（`expireAfterSeconds`）7 处**已实现**为应用层清理（§5.5） |
| 正则方言核对（PCRE→ARE `translate_regex_pattern`） | ✅ 差分 32/32，实际调用点无拒绝分支命中 |
| 主键 `_id` 类型归一化调用点改造 | ✅ 三服务 115 处已解耦（`to_backend_id`/`to_backend_id_strict`/`is_valid_backend_id`，§2.9）；mongo 行为不变、panwei 用字符串 |
| document-parser 锁定文件单一来源 | ✅ `--docker 3.13` 重生成，1342 hashes，正文不变仅清头部噪声 |
| 三服务 panwei 后端全量回归（连真实 PanWeiDB，独立回归 schema `regress_*`） | ✅ **admin-api rc=0；document-parser rc=0；chat-api rc=0（全量全绿）**。chat-api 原 12 失败=单测直接调 `get_db()` 未 `init_backend()`（panwei 不懒建池的接入契约），已在 `tests/conftest.py` 加 panwei 适配 fixture（惰性池替身透传真池 + async 真池 init）修复；**非 pg_compat 数据层缺陷** |

**R2 的关键设计决策**：把「补齐缺口」实现为**兼容层能力**而不是改写 25 处业务调用点 ——
这样调用点仍然零修改，符合 R1 定下的路线。代价是兼容层多了一个聚合编译器，
但它有差分测试兜底（同一管道两边跑、比结果），可靠性高于逐点手改 SQL。

### R3 — 逐域关系化（未开始，可选）

按访问频次把热点集合（`chat_sessions` / `chat_messages` / `token_usage_logs` /
`admin_accounts` / `end_users`）从「单表 + JSONB」改成真实列 + 索引，提升查询性能。
这一步是可选的，只有当 JSONB 路径查询成为瓶颈时才需要。

---

## 8. 数据搬迁与校验

```bash
# 0) 建表（幂等）。迁移场景务必加 --from-mongo：静态扫描有已知漏扫（见下）
python scripts/pg/generate_ddl.py --schema mogo_dev \
  --from-mongo "mongodb://127.0.0.1:27017" --mongo-db mogo_dev \
  --out deploy/pg/schema.sql
psql "$PANWEIDB_DSN" -f deploy/pg/schema.sql

# 1) 演练：只统计不写库
python scripts/pg/migrate_mongo_to_panweidb.py \
  --mongo-uri "mongodb://127.0.0.1:27017" --mongo-db mogo_dev \
  --dsn "$PANWEIDB_DSN" --schema mogo_dev --dry-run

# 2) 正式搬迁（幂等；中断后直接重跑）
python scripts/pg/migrate_mongo_to_panweidb.py ... --schema mogo_dev

# 3) 对账收敛（源库在搬迁期间仍被写入时必需，见下）
python scripts/pg/migrate_mongo_to_panweidb.py ... --schema mogo_dev --prune

# 4) 校验计数
python scripts/pg/migrate_mongo_to_panweidb.py ... --schema mogo_dev --verify
```

### 集合清单的来源（DDL 生成器）

**权威来源是源 MongoDB 的实际集合**（`--from-mongo`），静态扫描只作补充。
实测静态扫描漏了 **11 个集合**，原因是集合名的四种写法它覆盖不到：

| 漏扫的写法 | 例子 |
|---|---|
| 大写常量（无 `_COLLECTION` 后缀） | `INBOX = "kernel_event_inbox"` |
| 实例属性赋值 | `self._collection = "runtime_action_receipts"` |
| 带前缀的下标 | `self._db["presence_heartbeats"]` |
| 属性访问 | `db.scheduled_jobs.find(...)` |
| 配置项驱动 | `settings.jobs_collection`（document-parser） |

漏掉的表不会导致失败（兼容层首次写入时隐式建表），但**巡检与容量规划会失真**，
因此迁移场景必须加 `--from-mongo`。

### 搬迁的三条语义（**务必先读**）

1. **幂等**：`ON CONFLICT (id) DO UPDATE`，重跑即自愈，中断后直接重跑。
2. **不传播删除**：upsert 只能保证「源库有的目标库也有」，**不能**保证
   「目标库没有源库已删的」。对**活跃的**源库（有会话 GC / TTL 清理）会留残留，
   此时 `--verify` 报「目标多于源」属预期。实测踩到过：搬迁期间运行中的 chat-api
   清理了一个过期会话，导致 `end_user_sessions` 目标比源多 1 行。
   需要收敛时加 `--prune`（删除目标库中源库已不存在的行）。
3. **可续跑**：`--resume` 跳过已完成集合，进度记在 `<schema>._migration_progress`。

工具**只读 MongoDB**，只写 PanWeiDB 目标表。

---

## 9. 性能与索引

- **主键**：`id` 上天然有唯一索引 → `find_one({"_id": ...})` 走索引。
- **租户过滤**：`tenant_id` 有独立 btree 索引 → 绝大多数查询的公共前缀。
- **JSONB 包含查询**：**没有 GIN 可用**（见 2.5），`@>` / `?` 会退化为顺序扫描。
  兼容层里只有 `$all` 用到 `@>`（全代码库 1 处），影响可忽略。
- **等值查询走 `doc #> '{f}' = %s::jsonb`**：表达式索引需要按需建。
  R1 的 `create_index` 会把 Mongo 的索引声明翻译成 PG 表达式索引
  （单字段与复合都支持），因此**既有 `ensure_indexes()` 在启动时会自动补齐**。
- **已知性能风险**：`find()` 的 `skip` 是 `OFFSET`，大偏移为 O(n)；
  R2 建议改成基于 `id` 的游标分页。

---

## 10. 风险清单

| # | 风险 | 等级 | 缓解 |
|---|---|---|---|
| 1 | `sql_compatibility=A` 不可改，JSONB 函数受限 | **高** | 已实测出可用子集并内联规避；新增代码不得引入禁用函数 |
| 2 | `jsonb_set` 不建中间层 → 点号 `$set` 静默丢更新 | **高** | 已用 `_jsonb_set_path()` 逐层回卷修复 + 回归用例 |
| 3 | 612 处调用点里仍可能用到未覆盖算子 | 中 | 未覆盖即抛 `PgCompatUnsupported`（**不静默降级**），R2 逐条清 |
| 4 | 25 处 `aggregate()` 需重写 | 中 | 以 `$group`/`$match` 为主，工作量可控 |
| 5 | 兼容层代码在 3 个服务间重复 | 中 | 与仓库既有架构一致（`db.py`/`config.py` 本就每服务一份）；R3 可抽成共享包 |
| 6 | 投影在 Python 侧裁剪 | 低 | R2 下推为 SQL |
| 7 | 唯一索引语义（sparse/partial）差异 | 中 | R2 逐点核对 202 处索引声明 |
| 8 | `_id` 由 ObjectId 变字符串 | 中 | ✅ 已解决：**115 处调用点**（71 `ObjectId(` 构造 + 44 `is_valid`/`isinstance`）已用 `to_backend_id`/`to_backend_id_strict` 与后端类型解耦（§2.9），mongo 行为不变 |

---

## 11. 验收标准

**R1（已达成）**

- [x] `MOGO_DATA_BACKEND` 未设置时，三服务行为与迁移前**完全一致**（mongo 分支代码路径未改语义）
- [x] 兼容门面在真实 PanWeiDB 上通过 64/64（异步）+ 26/26（同步）用例
- [x] 搬迁工具完成「演练 → 搬迁 → 幂等重跑 → 计数校验 → 门面回读」全链路
- [x] DDL 生成器产出 103 张表 / 309 个索引，实测 1.6s 建完
- [x] 未覆盖算子显式失败并给出可操作的错误信息

**R2（待达成）**

- [ ] 三服务测试套件在 `MOGO_DATA_BACKEND=panweidb` 下全绿
- [ ] 25 处 `aggregate()` 与 6 处 `bulk_write` 全部改写完成
- [ ] 索引语义逐点核对完成
- [ ] 生产数据搬迁 + 计数校验通过，且能在一个发布周期内回滚

---

## 12. R1 改动文件清单

**新增**

```
services/{admin-api,chat-api}/app/core/pg.py          # 异步连接池
services/{admin-api,chat-api}/app/core/pg_compat.py   # 异步兼容门面
services/{admin-api,chat-api}/app/core/db.py          # 后端分派（重写）
services/document-parser/app/core/pg.py               # 同步连接池
services/document-parser/app/core/pg_compat.py        # 同步兼容门面
services/document-parser/app/core/db.py               # 后端分派（重写）
scripts/pg/generate_ddl.py                            # DDL 生成器
scripts/pg/migrate_mongo_to_panweidb.py               # 数据搬迁工具
deploy/pg/schema.sql                                  # 103 集合建表 DDL（生成物）
docs/mongo-to-panweidb-migration-plan.md              # 本文档
```

**修改**

```
services/*/app/core/config.py         # 加 MOGO_DATA_BACKEND + PANWEIDB_* 配置
services/*/app/main.py                # init_db/close_db → init_backend/close_backend
services/*/app/main.py, document-parser/app/api/routes/health.py   # /health 加 backend
services/*/requirements.in            # 加 psycopg[binary] / psycopg-pool
services/*/requirements.txt           # 重新生成（带哈希）
```
