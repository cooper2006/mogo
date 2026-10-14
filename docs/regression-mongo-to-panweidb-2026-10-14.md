# Mongo → PanWeiDB 切换回归测试报告

**日期**：2026-10-14
**范围**：027-mongo-to-panweidb-migration（R1 基础设施 + R2 落地）
**方法**：QualityForge（证据优先 / 穷尽优先于抽样 / 区分未通过·阻塞·待测）
**执行环境**：本机（OrbStack），MongoDB 6.0.20 + PanWeiDB（openGauss）均在线

> **2026-10-14 更新**：QF-DB-001 已修复并复测通过（在有残留数据的初始状态下重跑，19/19 全过）。详见第 4 节该条的「修复与复测」小节。

---

## 0. 使用说明

- 第 4 节是**可勾选清单**：已修复请改为 `- [x]`；接受风险写 `WONTFIX`；延后写 `DEFER`；不适用写 `NA`。
- 每条问题都带期望、实测、证据与复现步骤，可独立复核。
- 第 5 节是覆盖度证明：每条被执行的检查与其结论。
- 第 6 节是被裁剪或未覆盖的检查，透明列出，不伪装成通过。

---

## 1. 结论摘要

### 交付判定：**可交付**（无 P0；原 P1 已修复并复测通过）

本轮回归测试验证了数据库从 MongoDB 切换到 PanWeiDB 后的行为一致性。**未发现任何产品代码层面的语义回归**：

- admin-api 全量 **919/919 通过**
- chat-api 全量 **2588/2591 通过**（3 项失败均为测试环境 Mongo 端口配置问题，指定正确端口后全部通过）
- MongoDB ↔ PanWeiDB 差分测试 **19/19 通过**（聚合管道 10 条 + `$percentile` + `bulk_write` 8 项）
- 兼容层三副本不漂移守卫通过
- 4 个运行实例实测均在 `MOGO_DATA_BACKEND=panweidb` 且健康

### 关键发现

| 编号 | 优先级 | 结论 |
|---|---|---|
| QF-DB-001 | **P1** | 差分测试脚本的 `DROP TABLE` 缺 schema 限定，在 `search_path` 不含目标 schema 时**静默失效**，残留数据导致 `bulk_write` 计数误报 3 项失败。这是**测试工具缺陷而非兼容层缺陷**——它会让 R2 验收得出错误结论。**已修复并复测通过（19/19）。** |
| QF-DB-002 | P2 | chat-api 测试默认连 `127.0.0.1:27017`，与本机转发端口 `27018` 不一致，3 个依赖 Mongo 的测试失败。 |
| QF-DB-003 | P2 | document-parser 本地缺 5 个包导致文档解析测试无法执行（环境阻塞，非缺陷）。**已补齐依赖并解除阻塞，22/22 全过。** |
| QF-DB-012 | P2 | document-parser 的 `pymongo` 版本声明（`<4.0.0`）、锁定文件（`3.13.0`）与实际运行（`4.18.3`）三处不一致。**已修复：放宽上界至 `>=4.5` 并重编译锁定文件，22/22 回归通过。** |

### 特别值得注意的一点

差分测试最初报出的 `bulk_write` 计数不符（`matched=6/期望4`、`modified=6/期望4`、`upserted=0/期望1`）经插桩排查后证明是**假阳性**。对 `pg_compat.bulk_write` 逐步插桩显示计数逐条与 MongoDB 完全对应（`1+2+1+0=4`），修复脚本的 schema 限定后 **19/19 全过**。

这个发现本身有工程价值：**差分测试是 R2 最可靠的验收方式，但它这次的验收能力被自己的 DDL 缺陷掩盖了**。同类问题（测试工具本身有 bug 导致验收结论错误）在生产代码中更难被发现，建议在 CI 中增加差分测试的自检。

补充：本轮在同步版 `pg_compat` 的端到端验证中又遇到一次同一类问题——我的验证脚本报「`$elemMatch` 未拒绝」，实为脚本 bug（`aggregate()` 返回懒执行游标，未调 `.to_list()` 就不编译 SQL）。一次是工具产生假阳性，一次是工具产生假阴性，**两次都指向同一件事：验证代码自身缺少测试**。

---

## 2. 优先级与严重度分布

| 优先级 | 严重度 | 数量 | 说明 |
|---|---|---|---|
| P0 | critical | **0** | 无阻断级问题 |
| P1 | high | 1 | QF-DB-001（测试工具，非产品代码）—— **已修复** |
| P2 | medium | 2 | QF-DB-002（测试基建）、QF-DB-012（依赖约束不一致）—— **QF-DB-012 已修复** |
| P2 | low | 1 | QF-DB-003（环境阻塞）—— **已解除** |
| — | info | 10 | 通过项，作为基线证据保留 |

---

## 3. 修复波次

### Wave 1（阻断级清零）—— 无需处理
无 P0 问题。

### Wave 2（建议本轮处理，均为小改动）

1. **QF-DB-001**（S）：~~`scripts/pg/verify_mongo_pg_diff.py` 两处 `DROP TABLE IF EXISTS` 加 schema 限定。~~ **✅ 已修复并复测通过（2026-10-14）**
2. **QF-DB-002**（S）：chat-api 测试 conftest 固定 `MONGODB_URI`。

### Wave 3（排期或接受风险）

3. **QF-DB-003**（S）：~~为 document-parser 补齐本地 venv。~~ **✅ 已补齐并复测 22/22（2026-10-14）**
4. **QF-DB-012**（S）：~~放宽 `requirements.in` 的 `pymongo` 上界并重编译 `requirements.txt`。~~ **✅ 已修复并复测（2026-10-14）**
5. QF-DB-007 的附带建议（S）：为 FR-025 增加「源码禁用符号扫描」守卫测试。

---

## 4. 问题清单（可勾选）

### QF-DB-001 · P1 / high · **已修复并复测通过**

**差分测试脚本 `DROP TABLE` 未带 schema 限定，在 `search_path` 不含目标 schema 时静默失效**

- [x] 已修复（2026-10-14）

**期望**：差分测试在 PanWeiDB 上能干净隔离每轮 `bulk_write` 用例，聚合管道与 `bulk_write` 计数全部与 MongoDB 基线一致。

**实测**：脚本对 pg 侧使用 `DROP TABLE IF EXISTS "{coll}"`（无 schema 限定）。实测连接 `search_path = '"$user",public'`，不含 `mogo_dev`，因此 DROP 解析到不存在的 `boncuser2`/`public` 下同名表，`IF EXISTS` 静默成功，真实表 `mogo_dev.bulk_write_probe` 的上一轮数据残留（实测 DROP 后仍存在且已有 2 行）。残留数据使 `UpdateMany`/`ReplaceOne` 多匹配 2 行、upsert 变成匹配命中，导致 `matched_count=6/期望4`、`modified_count=6/期望4`、`upserted_count=0/期望1` 三项误报失败。

把两处 DROP 改为 `mogo_dev."{coll}"` 后 **19/19 全部通过**，确认 `pg_compat` 的 `bulk_write` 计数语义与 MongoDB 完全一致。

**涉及文件**：
- `scripts/pg/verify_mongo_pg_diff.py:187`
- `scripts/pg/verify_mongo_pg_diff.py:219`

**复现步骤**：
```bash
cd mogo
PW=$(grep '^PANWEIDB_PASSWORD=' .env | cut -d= -f2-)
python3 scripts/pg/verify_mongo_pg_diff.py \
  --mongo-uri mongodb://127.0.0.1:27018 --mongo-db mogo_dev \
  --dsn "host=127.0.0.1 port=5432 user=boncuser2 password=$PW dbname=bonc" \
  --schema mogo_dev
# → [bulk_write 差分] 段 matched/modified/upserted 三项失败
# → 而「落库文档集合一致」「文档条数」通过

# 库内验证根因：
SHOW search_path;                          -- ("$user",public)  ← 不含 mogo_dev
SELECT count(*) FROM mogo_dev."bulk_write_probe";  -- 2（DROP 后仍残留）
```

**证据**：
- `SHOW search_path` → `('"$user",public',)`
- 原样运行差分测试：通过 16 / 失败 3
- 仅把两处 DROP 加 `mogo_dev.` 前缀后重跑：通过 19 / 失败 0
- 对 `PgCollection.bulk_write` 插桩逐步计数：`update_one matched=1`、`update_many matched=2`、`replace_one matched=1`、upsert 分支 `matched=0/upserted_id=r-9`，合计 `matched=4/modified=4/upserted=1`，与 MongoDB 逐项对应

**修复建议**：
把 `scripts/pg/verify_mongo_pg_diff.py` 里两处 `DROP TABLE IF EXISTS "{coll}"` 改为带 schema 的 `DROP TABLE IF EXISTS "{schema}"."{coll}"`（schema 取自 `--schema` 参数，双引号包裹以与 `pg_compat` 内部 `_qualified` 的写法保持一致）。

这是**测试工具的隔离缺陷**而非兼容层缺陷，但会造成 R2 验收误判：任何按此脚本报告的「bulk_write 计数不符」都是假阳性。

**工作量**：S（约 10 分钟）

### 修复与复测（2026-10-14）

**改动**：`scripts/pg/verify_mongo_pg_diff.py`，4 处（8 insertions / 4 deletions）：

1. `_check_bulk_write(mongo, pg, pool)` → `_check_bulk_write(mongo, pg, pool, schema)`
2. 两处 `DROP TABLE IF EXISTS "{coll}"` → `DROP TABLE IF EXISTS "{schema}"."{coll}"`（schema 带引号，与 `pg_compat._qualified` 一致）
3. 调用处传入 `args.schema`
4. 在首处 DROP 前加注释说明「为何必须带 schema 限定」，防止未来回退：

```python
    # DROP 必须带 schema 限定：连接的 search_path 是 '"$user",public'（不含目标
    # schema），裸标识符会解析到不存在的同名表，IF EXISTS 静默 no-op，上一轮残留
    # 数据就会污染本轮计数——2026-10-14 回归时 bulk_write 的 matched/modified/
    # upserted 因此误报失败（实际计数与 MongoDB 一致）。见
    # docs/regression-mongo-to-panweidb-2026-10-14.md §4 QF-DB-001。
    # schema 也须用双引号包裹（与 pg_compat._qualified 一致）：不带引号的标识符会
    # 被折叠为小写，遇到 pg_compat 带引号创建的含大写 schema 名会报
    # "schema does not exist"。实测 2026-10-14。
```

**复测方法（关键：在故障场景下验证，而非干净状态下验证）**：

若表已被前次跑动清掉，直接在干净状态下重跑无法证明修复有效。因此先**人为造出原故障的初始状态**——按 `mogo_dev.bulk_write_probe` 的结构建表并插入残留的 2 行（`p-2`、`p-9`），确认残留行数 = 2，然后跑修复后的脚本：

```bash
# 1. 造出残留数据（复现原故障场景）
残留行数 = [(2,)]          残留 id = [('p-2',), ('p-9',)]

# 2. 跑修复后的差分测试
python3 scripts/pg/verify_mongo_pg_diff.py \
  --mongo-uri mongodb://127.0.0.1:27018 --mongo-db mogo_dev \
  --dsn "host=127.0.0.1 port=5432 user=boncuser2 password=*** dbname=bonc" \
  --schema mogo_dev
# → 通过 19 / 失败 0，exit 0

# 3. 确认测试结束后的清理也正确
SELECT count(*) FROM information_schema.tables
  WHERE table_schema='mogo_dev' AND table_name='bulk_write_probe';
# → (0,)  表已被正确 DROP
```

**复测结果**：**19 / 19 全过，exit 0**。与修复前同一初始状态下的 `16 / 19`（3 项误报失败）对比，三项计数偏差全部消除。

| 指标 | 修复前（有残留） | 修复后（有残留） | MongoDB 基线 |
|---|---|---|---|
| inserted_count | ✅ 2 | ✅ 2 | 2 |
| matched_count | ❌ 6 | ✅ **4** | 4 |
| modified_count | ❌ 6 | ✅ **4** | 4 |
| upserted_count | ❌ 0 | ✅ **1** | 1 |
| 落库文档集合一致 | ✅ | ✅ | ✅ |
| 文档条数 | ✅ 2 | ✅ 2 | 2 |
| 汇总 | 16 / 19 | **19 / 19** | — |

**Code review 中发现的第二个问题（2026-10-14 追加修复）**：

上面的修复写成 `f'DROP TABLE IF EXISTS {schema}."{coll}"'`，但 `pg_compat.py:1162` 的 `_qualified` 是 `f'"{schema}"."{name}"'`——**带引号**。不带引号的 schema 标识符会被折叠为小写，而 `pg_compat` 带引号建 schema 会保留大小写。用含大写的 schema 实测：

```
建 schema "Review_Mixed_Case" + 表（pg_compat 带引号写法）
  ❌ 无引号  {schema}     → ProgrammingError: schema "review_mixed_case" does not exist
  ✅ 带引号  "{schema}"   → 已删除
```

当前环境 `PANWEIDB_SCHEMA=mogo_dev` 全小写，所以不触发；但 `--schema` 是可配置参数，任何含大写的配置都会让差分测试直接崩。已把两处改成 `"{schema}"` 与 `pg_compat` 一致，并把注释里的悬空引用（"见 WORK_LOG 2026-10-14"，当时 `WORK_LOG.md` 未提交、HEAD 不可达）改为指向本报告 §4 QF-DB-001。

**复测过程的一个附带发现**：造残留数据时发现 openGauss 与标准 PostgreSQL 的一处行为差异，值得记入 FR-024「目标库实测事实」：

1. **`INSERT ... ON CONFLICT DO NOTHING` 不支持**（已实测确认）：`FeatureNotSupported: Conflict without target is not yet supported within INSERT ON CONFLICT KEY DO UPDATE statement.`。注意**带 target 也不行**：无唯一约束时 `ON CONFLICT (id) DO NOTHING` 报 `InFailedSqlTransaction`；有主键时同样不通过。pg_compat 未使用该语法（写路径用 `INSERT ... ON CONFLICT ... DO UPDATE` 带明确 target，或先查后写），因此不影响兼容层；但写差分测试/搬迁工具的 SQL 时需注意——**去重必须靠先查后写，不能靠 `ON CONFLICT`**。

**一条需要澄清的误报**：本报告初稿曾把「`SELECT count(*), id FROM ... ORDER BY id` 报 `GroupingError`」记为 openGauss 的特有差异，称"标准 PostgreSQL 允许隐式分组"。**这是错的**——标准 PostgreSQL 对同样语句报完全相同的错误（`column must appear in the GROUP BY clause or be used in an aggregate function`），这是 SQL 标准行为，不是方言差异。

顺带一条**部分反证**：`SELECT count(*), id::text FROM _t GROUP BY id` 实测**通过**。这与 `docs/mongo-to-panweidb-migration-plan.md` §2.6 记录的「`GROUP BY <expr>` 与 `SELECT <同一 expr 但套了 ::text>` 被判定为不同表达式」看似矛盾。该记录的原始场景是 jsonb 表达式，与这里的简单 `text` 列不同，因此不一定构成反证，但**该约束的边界比 §2.6 的字面描述更窄**，值得复核。

**工作量**：已投入约 20 分钟（含造残留场景与三段验证）。

---

### QF-DB-002 · P2 / medium · fail

**chat-api 单测默认 Mongo 端口 27017 与本机转发端口 27018 不一致，3 个依赖 Mongo 的测试失败**

- [ ] 待处理

**期望**：chat-api 全量单测在本机回归环境下一致通过；连接不可达时应返回业务层 reason（`unresolved`/`visibility_denied`），而非泄漏驱动异常。

**实测**：3 个测试失败，同根：pymongo 连 `127.0.0.1:27017` 被拒（Errno 61），`ServerSelectionTimeoutError` 沿调用栈泄漏到断言层。设置 `MONGODB_URI=mongodb://127.0.0.1:27018` 后 3 个测试**全部通过**，确认属环境配置而非代码回归。

失败项：
1. `test_resolve_missing_address_reports_per_item` —— 断言收到 `'ServerSelectionTimeoutError'` 而非 `{'unresolved','visibility_denied'}`
2. `test_create_memory_allows_org_scope_for_admin` —— 直接抛 `ServerSelectionTimeoutError`
3. `test_save_tierable_huge_accepted` —— 直接抛 `ServerSelectionTimeoutError`

**涉及文件**：
- `services/chat-api/app/core/config.py:85`（`MONGODB_URI: str = ""`）
- `services/chat-api/tests/memory/test_store_tier.py:21`
- `services/chat-api/tests/context_space/test_context_endpoints.py:66`

**复现步骤**：
```bash
cd services/chat-api
# 原样失败：
venv/bin/python -m pytest tests/memory/test_store_tier.py::test_save_tierable_huge_accepted -q
# → ServerSelectionTimeoutError: 127.0.0.1:27017 [Errno 61] Connection refused

# 指定正确端口后通过：
MONGODB_URI=mongodb://127.0.0.1:27018 venv/bin/python -m pytest \
  tests/context_space/test_context_endpoints.py::test_resolve_missing_address_reports_per_item \
  tests/memory/test_memory_endpoints.py::test_create_memory_allows_org_scope_for_admin \
  tests/memory/test_store_tier.py::test_save_tierable_huge_accepted -q
# → 3 passed
```

**证据**：
- `docker ps` 显示 `mongo-fwd` 容器（python:3.13-slim）承担 27018→栈内 mongo 的 TCP 转发；`lsof` 显示 27017 无监听、27018 LISTEN
- 原样运行：`AssertionError: assert 'ServerSelectionTimeoutError' in {'unresolved', 'visibility_denied'}`
- 指定 `MONGODB_URI=27018` 重跑：3 passed

**修复建议**：在 chat-api 测试的 `conftest.py` 里用 `os.environ.setdefault` 固定 `MONGODB_URI`（或统一走 mongo-fwd 的 27018），避免本机回归依赖隐式 27017。这属于测试基建问题。

**附带观察（建议单独跟进）**：`test_resolve_missing_address_reports_per_item` 暴露出「下游存储不可达时驱动异常会泄漏进 API 响应字段」的边界行为，与 **FR-031**（存储抖动不得导致请求被无限阻塞或错误被裸抛）相关——本次在未切 panweidb 后端时已可复现，建议在 panweidb 路径上单独补一个「池耗尽/不可达→业务错误」的用例。

**工作量**：S（约 15 分钟）

---

### QF-DB-003 · P2 / low · **已解除阻塞（2026-10-14）**

**document-parser 本地无可用 Python 环境，7–8 个文档解析测试无法执行（环境阻塞）**

- [x] 已解除（2026-10-14，补齐依赖后 22/22 全过）

**期望**：document-parser 的全量单测可在本地独立执行，与另两个服务的回归结果口径一致。

**实测**：`services/document-parser` 下没有 venv（仅一个空的 `.venv` 目录），系统 python3 缺少 `pydantic_settings`，跨用 `services/admin-api` 的 venv 可完成 28 个用例的收集但运行期缺 `python-pptx` / `openpyxl`，导致 `test_document_parsing_fallback.py` 的 7–8 个用例失败。

这是**环境依赖缺失，不是代码缺陷**：失败均发生在被测对象之前的 import/造数据阶段（`ModuleNotFoundError: No module named 'pptx'`），与被测的 `pg_compat` 改动无关。

**涉及文件**：
- `services/document-parser/.venv`
- `services/document-parser/tests/test_document_parsing_fallback.py:40`（`from pptx import Presentation`）

**复现步骤**：
```bash
ls -d services/document-parser/venv
# → 不存在，仅 .venv

python3 -m pytest services/document-parser/tests/ --collect-only
# → ModuleNotFoundError: No module named 'pydantic_settings'

../admin-api/venv/bin/python -m pytest tests/ -q   # 在 document-parser 目录内
# → 收集 28 项成功；test_document_parsing_fallback.py 的 7–8 项因缺 pptx 失败
```

**证据**：
- `document-parser/tests` 下 7 个测试文件，含 `test_vector_store_anchor.py`（本轮有改动，4 个用例）
- admin-api venv 下收集结果：`test_document_parsing_fallback.py:8`、`test_markdown_parse_service.py:2`、`test_model_providers.py:4`、`test_retrieval_authorized_candidates.py:1`、`test_retrieval_scope.py:3`、`test_vector_store_anchor.py:4`

**修复建议**：为 document-parser 补齐本地 venv（或明确其单测只在容器内执行并在文档中标注），使回归口径与 admin-api/chat-api 对齐。本次回归中 document-parser 的 `pg_compat` 副本已通过 `sync_pg_compat --check` 的同步变换一致性校验，**代码层面的等价性有据**；缺的是端到端执行证据。

**工作量**：S（约 30 分钟）

### 解除阻塞与复测（2026-10-14）

用 ServBay 下的 Python 3.13 补齐 `.venv` 缺失依赖后重测。

**环境实况（比原报告描述的更乐观）**：`.venv` 并非空目录，里面已有 Python 3.13.12 与大部分依赖（`pydantic_settings` 2.15.0、`python-pptx` 1.0.2、`openpyxl` 3.1.5、`python-docx` 1.2.0、`pypdf` 6.19.0、`celery` 5.6.3、`oss2` 2.19.1、`pytest` 9.1.1、`fastapi` 0.142.2、`uvicorn` 0.29.0 均已安装）。原报告"仅一个空的 `.venv` 目录"的描述**不准确**——实际是缺 5 个包，其中 `psycopg` / `psycopg_pool` 正是本轮迁移的新依赖。

缺的 5 个：`motor`、`psycopg`、`psycopg_pool`、`pytest-asyncio`、`httpx`。

**安装**（按 AGENTS.md「国内源」条款，先配置 pip 源）：

```ini
# ~/Library/Application Support/pip/pip.conf
[global]
index-url = https://mirrors.aliyun.com/pypi/simple/
trusted-host = mirrors.aliyun.com
```

```bash
.venv/bin/python -m pip install "psycopg[binary]>=3.2.0" "psycopg-pool>=3.2.0" \
    "motor>=3.3.0" pytest-asyncio httpx
```

**复测结果**：

```
.venv/bin/python -m pytest tests/ -q --tb=line -p no:randomly
→ 22 个用例，进度条至 [100%]，F/E 计数 0，exit 0
```

| 测试文件 | 用例数 | 结果 |
|---|---|---|
| `test_document_parsing_fallback.py` | 8 | 全过 |
| `test_markdown_parse_service.py` | 2 | 全过 |
| `test_model_providers.py` | 4 | 全过 |
| `test_retrieval_authorized_candidates.py` | 1 | 全过 |
| `test_retrieval_scope.py` | 3 | 全过 |
| `test_vector_store_anchor.py` | 4 | 全过 |
| 合计 | **22** | **22/22** |

**额外验证：同步版 `pg_compat` 在 PanWeiDB 上的端到端能力**

document-parser 是唯一用**同步驱动**（`pymongo` + `psycopg_pool.ConnectionPool`）的服务，其余两个用 `motor` + `AsyncConnectionPool`。其 `pg_compat` 是异步版的机械变换副本，且**没有自己的单测**（单测都在 admin-api 的 `test_pg_compat.py`），只靠 `sync_pg_compat --check` 保证文本一致。因此补了一次端到端实跑：

| 能力 | document-parser 同步版 | admin-api 异步版（对照） |
|---|---|---|
| 隐式建表 + 写入 | ✅ | ✅ |
| 中文/重音字符往返（`中文标题 café`） | ✅ | ✅ |
| 嵌套路径 `$set` 深合并（`meta.deep.y`，保留同级 `x`） | ✅ `{'n':1,'deep':{'x':2,'y':3}}` | ✅ |
| `$regex` 词边界方言翻译（`\badmin\b`） | ✅ 命中 2（`administrator` 不命中） | ✅ 命中 2 |
| `$type` 过滤 | ✅ 命中 1 | — |
| 聚合 `$group` | ✅ | ✅ |
| `bulk_write` | ✅ `inserted=1 matched=1 modified=1 upserted=0` | ✅ |
| 未覆盖阶段显式失败（`$elemMatch` / `$geoNear` / `$bad`） | ✅ 全部 `PgCompatUnsupported` | ✅ 全部 `PgCompatUnsupported` |
| 空 `bulk_write` | ✅ `(0, 0)` | ✅ `(0, 0)` |

结论：三副本中唯一缺少单测覆盖的同步副本，在本轮新增能力上**与异步副本行为一致**，端到端可用。

> **一个方法论备注**：过程中验证脚本一度报「`$elemMatch` 未拒绝」，实际是脚本 bug——`aggregate()` 返回的是**懒执行游标**，不调 `.to_list()` 就不会编译 SQL。补上 `.to_list()` 后正确拒绝。这类「测试脚本自身的假阴性」与 QF-DB-001 的「测试工具的假阳性」是同一类问题：**回归结论的可信度取决于验证代码本身，而它通常没有自己的测试**。

**工作量**：已投入约 40 分钟（含配置国内源、补依赖、同步版端到端验证）。

---

### QF-DB-012 · P2 / medium · **已修复（2026-10-14）**

**document-parser 的 `pymongo` 版本声明与锁定文件、实际运行版本三处不一致**

- [x] 已修复（放宽上界 + 重编译锁定文件，22/22 回归通过）

**期望**：同一仓库内各服务对同一驱动的约束、锁定与实际安装版本应一致；尤其是 `pg_compat` 的 `bulk_write` 直接依赖驱动私有属性（`InsertOne._doc`、`UpdateOne._filter`/`_doc`/`_upsert`），驱动大版本差异可能改变其行为。

**实测**：三处不一致——

| 位置 | 声明/版本 |
|---|---|
| `services/document-parser/requirements.in:6` | `pymongo>=3.12.0,<4.0.0` |
| `services/document-parser/requirements.txt:1045`（pip-tools 锁定） | `pymongo==3.13.0` |
| `.venv` 实际安装（补依赖后） | `pymongo==4.18.3` |
| `services/admin-api` / `chat-api` 实际使用 | `pymongo==4.18.2` |

补齐 `.venv` 依赖时 `pip` 将 `pymongo` 从 3.13.0 自动升级到 4.18.3（`motor>=3.3.0` 的解析链拉高了 pymongo——motor 3.4+ 声明 `pymongo>=4.x`），此时 `requirements.in` 的 `<4.0.0` 已被违反。

同时 `requirements.txt` 里**已包含** `psycopg==3.3.6`、`psycopg-binary==3.3.6`、`psycopg-pool==3.3.3`（第 785/789/858 行）——说明该锁定文件已在迁移时被重新编译过一次，但 `pymongo` 的版本上限没跟着放宽，两个事实自相矛盾。

**为何不是 P0**：实测 document-parser 在 `pymongo 4.18.3` 下 22/22 全过，同步版 `pg_compat` 端到端能力全部正常（见上一节对照表）。所以**当时是「声明滞后于实际」而非「实际版本有缺陷」**。风险在于：新环境按 `requirements.in`/`requirements.txt` 干净安装时会得到 pymongo 3.13.0，与共享的 `pg_compat` 在 4.x 下验证过的行为不一致，且无法被单测发现（document-parser 没有 pg_compat 单测）。

**涉及文件**：
- `services/document-parser/requirements.in:6`
- `services/document-parser/requirements.txt:1045`

**复现步骤**：
```bash
cd services/document-parser
grep -nE '^(pymongo|motor|psycopg)' requirements.in
grep -nE '^(pymongo|motor|psycopg)' requirements.txt | head
.venv/bin/python -m pip list 2>/dev/null | grep -iE '^(pymongo|motor|psycopg)'
```

---

**修复（2026-10-14）**：

1. `requirements.in:6`：`pymongo>=3.12.0,<4.0.0` → **`pymongo>=4.5`**，与 admin-api / chat-api 的声明完全对齐（原先两个服务是 `>=4.5`，document-parser 单独落后）。
2. 用原文件头部记录的同一条命令重编译：
   ```bash
   pip-compile --generate-hashes \
     --index-url=https://pypi.tuna.tsinghua.edu.cn/simple \
     --output-file=requirements.txt --strip-extras requirements.in
   ```

**编译产物**（+80 / −129 行，1562 → 1513 行）：

| 变化 | 内容 |
|---|---|
| pymongo | `3.13.0` → **`4.18.3`**（与另两个服务的 4.18.2 同代） |
| 新增 | `dnspython==2.9.0`（pymongo 4.x 引入的 SRV 解析依赖） |
| 移除 | `async-timeout`、`exceptiongroup`（均为 Python <3.11 的兼容垫片，3.13 由标准库提供） |
| 编译解释器 | `Python 3.10` → **`Python 3.13`**，与 admin-api / chat-api 的锁定文件一致 |

**为何用 3.13 编译是安全的**：锁定文件里的 `--hash` 是 pip-compile 的 universal 集合（**无任何平台/版本标记**，实测 `grep python_version` 为空），不绑定单一解释器；且 admin-api / chat-api 的锁定文件本就用 3.13 编译、在 CI 上正常运行。改完 document-parser 反而消除了一致性偏差。

**验证**：
```bash
.venv/bin/python -m pip show pymongo      # 4.18.3，与锁定文件一致
.venv/bin/python -m pytest -q -p no:randomly
# ......................  [100%]   22/22，exit 0
```

**一个附带澄清**：原「修复建议」提到要"明确 `motor` 的版本约束"。这条建议**不成立**——document-parser 是**同步服务**，`requirements.in` 里本来就没有 `motor`（异步的 motor 只在 admin-api / chat-api 声明）。补依赖时我临时装的 motor 3.7.1 只用于交叉验证同步/异步一致性，**不该进入依赖声明**；重编译后的锁定文件里也确实没有 motor，符合预期。


---

## 5. 全部测试项核对表

> **编号说明**：本节沿用 `QF-DB-` 前缀但含义与 §4 不同——§4 的编号是**问题**，本节的编号是**通过的测试项**，两者共用一个编号空间且交错排列（问题项 001/002/003/012，通过项 004–011/013/014）。引用时请以章节为准，不要只凭编号判断性质。

### 5.1 执行结果汇总

| # | 检查项 | 类别 | 结果 | 证据 |
|---|---|---|---|---|
| QF-DB-004 | admin-api 全量回归 | regression | **PASS** | 919/919，0 失败，exit 0 |
| QF-DB-011 | chat-api 全量回归 | regression | **PASS** | 2591 项，3 失败均归因 QF-DB-002，其余全绿 |
| QF-DB-013 | document-parser 全量回归 | regression | **PASS** | 22/22（补齐依赖后），exit 0 |
| QF-DB-006 | MongoDB ↔ PanWeiDB 差分测试 | integration | **PASS** | 19/19（修复 schema 限定后） |
| QF-DB-005 | 兼容层三副本不漂移守卫（FR-026） | regression | **PASS** | `sync_pg_compat --check`：chat-api ✅ document-parser ✅ |
| QF-DB-007 | FR-025 禁用函数零命中 | contract | **PASS** | 禁用符号全文扫描无命中 |
| QF-DB-008 | FR-016 未覆盖能力显式失败 | contract | **PASS** | 五类拒绝路径 + 三类正则拒绝 |
| QF-DB-009 | FR-030 审计/业务 schema 分离与回退 | integration | **PASS** | 四层回退链，schema 永不为空 |
| QF-DB-010 | FR-001 后端开关实测 | integration | **PASS** | 4 实例 `MOGO_DATA_BACKEND=panweidb` 且 healthy |
| QF-DB-014 | 同步版 `pg_compat` 端到端（PanWeiDB 实跑） | integration | **PASS** | 9 项能力与异步版行为一致 |

### 5.2 关键通过项明细

**admin-api 全量回归（QF-DB-004）**：`venv/bin/python -m pytest tests/`，进度条 13 段至 100%，共 919 个用例，无 F/E 标记，退出码 0。覆盖含 `test_pg_compat.py`（56 项，含本轮新增的 regex 方言翻译、`$type`、`create_index` unique/sparse/partial）、`test_tenant_purge.py`（28 项，FR-029）、`test_security_audit_events.py`、`test_setup_*` 系列。

**差分测试（QF-DB-006）**：
- `$percentile`：返回 `[p50=11712.0, p95=84268.2]`，`p50<=p95` 且非负
- `bulk_write` 8/8：`inserted=2`、`matched=4`、`modified=4`、`deleted=1`、`upserted=1`、落库文档集合一致、文档条数 2、空请求列表全 0

**FR-025 映射规则（QF-DB-007）**：对 `pg_compat.py` 全文扫描 `REGEXP_MATCHES` / `REGEXP_REPLACE` / `REGEXP_SUBSTR` / `JSONB_PATH_QUERY` / `JSONB_PATH_EXISTS` / `STRING_AGG` / `ARRAY_AGG` / `ROW_NUMBER` / `NTH_VALUE` / `PERCENTILE_CONT` / `DISTINCT ON`，禁用集合**零命中**。正则统一用 `~` / `~*` 操作符；百分位用 ordered-set 聚合；聚合键表达式只构建一次。

**FR-016 显式失败（QF-DB-008）**：五条拒绝路径均覆盖——`test_unsupported_filter_operators_fail_loudly`、`test_unsupported_update_operators_fail_loudly`、`test_aggregation_unsupported_stage_fails_loudly`、`test_aggregation_unsupported_accumulator_and_expression_fail_loudly`、以及三类正则拒绝（`\p{L}`、`(?P<name>...)`、`[[:word:]]`）。异常类型统一为 `PgCompatUnsupported`（继承 `NotImplementedError`）。

**FR-030 审计隔离（QF-DB-009）**：回退链为 `panweidb_audit_schema` → 环境变量 `PANWEIDB_AUDIT_SCHEMA` → `.env` 文件 → `effective_panweidb_schema`（业务 schema）→ `'public'`，四层全非空兜底，因此 `PgCollection` 的 schema 永不为空字符串（避免 `""."table"` 空标识符 SQL）。`db.get_audit_db` 在 panweidb 后端下用独立 `PgDatabase(pool, effective_panweidb_audit_schema)` 构造审计门面，与业务门面分离但共用连接池。

**FR-001 后端开关（QF-DB-010）**：4 个实例（admin-api、chat-api、document-api、document-worker）`MOGO_DATA_BACKEND` 均为 `panweidb`，镜像 tag 均为 `v0.2.5-panweidb`，docker 报告 healthy。

### 5.3 本轮新增能力的守卫覆盖

| 新增能力 | 对应测试 | 结果 |
|---|---|---|
| `$regex` PCRE → openGauss ARE 方言翻译（`\b`→`\y`、`\w`→`[A-Za-z0-9_]`） | `test_regex_word_boundary_translated_to_are`、`test_regex_non_boundary_translated_to_are`、`test_regex_word_class_translated_to_ascii`、`test_regex_common_constructs_passthrough` | PASS |
| `$regex` 不支持构造拒绝 | `test_regex_rejects_unicode_property`、`test_regex_rejects_named_group`、`test_regex_rejects_posix_word_class` | PASS |
| `$type` 过滤算子 | `test_unsupported_filter_operators_fail_loudly` 对照 | PASS |
| `create_index` unique / sparse / partial | `test_create_index_plain_no_where`、`test_create_index_unique_adds_unique_keyword`、`test_create_index_sparse_adds_not_null_where`、`test_create_index_partial_inlines_filter_as_literal`、`test_create_index_partial_and_sparse_conjunction` | PASS |
| DDL 占位符内联（`partialFilterExpression`） | `test_create_index_partial_inlines_filter_as_literal` | PASS |

---

## 6. 未展开项（透明列出）

| 项 | 原因 |
|---|---|
| **反向回滚演练**（FR-001 验收场景 4） | 本次只验证了「默认→切换」方向。把某实例临时切回 mongo 并确认行为一致未执行。 |
| **FR-004 显式失败可操作信息** | 连接参数缺失/不可达时的错误信息内容未逐一验证（仅从 QF-DB-002 的附带观察间接触达）。 |
| **FR-005 连接池最小/最大/超时配置** | 未做压测或连接耗尽场景验证。 |
| **FR-006 异步探测不建同步池** | 未做连接数级别的探针验证。 |
| **FR-013 字段缺失的不等值语义** | 单测 `test_ne_matches_missing_field_semantics` 覆盖，但未在真实 PanWeiDB 上做端到端验证。 |
| **FR-015 隐式建表幂等与并发** | `_ensure_table` 有 `_table_ready` 置位，但未做并发压测验证。 |
| **FR-017/018 建表生成器与巡检** | `scripts/pg/generate_ddl.py` 未执行（需额外准备空 schema）。 |
| **FR-019–023 数据搬迁工具** | `migrate_mongo_to_panweidb.py` 未执行（属破坏性操作，需单独批准窗口）。 |
| **FR-027 占位符不变量** | 单测已固化断言（`test_add_to_set_dedupes_and_counts_placeholders_twice` 等），未额外做穷举扫描。 |
| **FR-028 三服务锁定文件完整性** | 未执行带哈希的安装校验。 |
| **FR-029 租户批量删除端到端** | `test_tenant_purge.py` 28 项通过，但未在 panweidb 后端上做端到端演练。 |
| **FR-031 连接池耗尽/不可达可用性** | 未压测。QF-DB-002 的附带观察已指出一个相关边界行为。 |
| **FR-032 保留期清理** | 未验证审计日志保留期与租户墓碑回收在 panweidb 上的行为。 |
| **SC-005 建表 10 秒内完成** | 103 张表的建表耗时未实测。 |
| **SC-009 无全表扫描** | 未抽样验证执行计划。 |
| **SC-010 租户销毁与保留期零退化** | 未做端到端对比。 |
| ~~**document-parser 端到端执行**~~ | ~~见 QF-DB-003，环境阻塞。~~ **已于 2026-10-14 解除：22/22 全过，同步版 `pg_compat` 端到端另见 QF-DB-014。** |
| **前端回归**（admin-web / user-web） | 本次范围限定在数据后端切换；前端未涉及。 |

---

## 7. 执行证据

### 7.1 命令与结果

| 命令 | 退出码 | 结论 |
|---|---|---|
| `cd services/admin-api && venv/bin/python -m pytest tests/ -q -p no:randomly` | 0 | 919 项全过（进度条 13 段，F/E 计数 0） |
| `cd services/admin-api && venv/bin/python -m pytest tests/test_pg_compat.py -q` | 0 | 56 项全过 |
| `cd services/chat-api && venv/bin/python -m pytest tests/ -q -p no:randomly` | 1 | 2591 项，3 失败（进度条 36 段，F 计数 3） |
| `cd services/chat-api && MONGODB_URI=mongodb://127.0.0.1:27018 venv/bin/python -m pytest <3 个失败用例> -q` | 0 | 3 项全过 |
| `python3 scripts/pg/sync_pg_compat.py --check` | 0 | chat-api ✅ document-parser ✅ |
| `python3 scripts/pg/verify_mongo_pg_diff.py ...`（原样） | 1 | 通过 16 / 失败 3 |
| 同上（DROP 加 schema 限定后） | 0 | 通过 19 / 失败 0 |
| `cd services/document-parser && ../admin-api/venv/bin/python -m pytest tests/ -q` | 1 | 收集 28 项，7–8 项因缺 `pptx` 失败 |
| `SHOW search_path` | 0 | `('"$user",public',)` —— 不含 `mogo_dev` |
| `SELECT count(*) FROM mogo_dev."bulk_write_probe"` | 0 | `2` —— DROP TABLE 后仍残留 |
| `docker exec <4 个实例> sh -c 'echo $MOGO_DATA_BACKEND'` | 0 | 四个均为 `panweidb` |
| 禁用函数扫描 `grep -onE 'REGEXP_MATCHES\|REGEXP_REPLACE\|...' pg_compat.py` | 1 | 零命中 |

### 7.2 环境快照

```
运行中容器：mogo-admin-api-1 (healthy)、mogo-chat-api-1 (healthy)、
            mogo-document-api-1 (healthy)、mogo-document-worker-1
            镜像均为 v0.2.5-panweidb
            mongo-fwd (27018→栈内 mongo 转发)、mogo-mongo-1 (mongo:6.0.20, healthy)
            panweidb (c2988ce00a05)、mogo-gateway-1 (healthy)
监听端口：127.0.0.1:5432 (PanWeiDB)、127.0.0.1:27018 (Mongo 转发)
          127.0.0.1:27017 无监听
PanWeiDB 连接：user=boncuser2, db=bonc, schema=mogo_dev
PanWeiDB search_path: "$user",public  ← 不含 mogo_dev（QF-DB-001 根因）
```

### 7.3 差分测试逐步插桩证据（QF-DB-001 的关键判据）

绕过脚本、直接对 `pg_compat.PgCollection` 的方法插桩，逐个操作执行：

```
[probe] update_one  a=({'_id':'r-1'}, {'$set':{'v':10}, '$push':{'tags':'b'}})  → matched=1 modified=1
[probe] update_many a=({'v':{'$gte':2}}, {'$inc':{'v':1}})                       → matched=2 modified=2
[probe] replace_one a=({'_id':'r-2'}, {'_id':'r-2','v':99,'replaced':True})      → matched=1 modified=1
[probe] update_one  a=({'_id':'r-9'}, {'$set':{'v':9}}) k={'upsert':True}        → matched=0 modified=0 upserted_id=r-9
BULK: inserted=2 matched=4 modified=4 deleted=1 upserted=1 ids={7: 'r-9'}
DOCS: [{'v':99,'_id':'r-2','replaced':True}, {'v':9,'_id':'r-9'}]
```

与 MongoDB 侧 `bulk_write` 返回值逐项一致。这证明 `pg_compat` 的 `bulk_write` 聚合层实现正确，差分脚本的失败来自残留数据而非兼容层。

---

## 8. 项目画像

| 维度 | 值 |
|---|---|
| 项目 | mogo |
| 文件数 | 6900（源码 2113，测试 455） |
| 语言 | Python 1625、Vue 162、TypeScript 206、JavaScript 86、Shell 33 |
| 服务 | admin-api、chat-api、document-parser（均独立构建，兼容层各有副本） |
| CI | GitHub Actions |
| 容器 | Dockerfile + compose |
| 本轮改动 | 67 文件，1407 插入 / 275 删除（HEAD 基线，含其他会话在途工作） |
| 本轮核心改动 | 三份 `pg_compat.py` 各 +248/-17 行：`$regex` 方言翻译、`$type`、`create_index` unique/sparse/partial、DDL 占位符内联 |

### 规模盘点（来自 027 规格）

- 3 个服务、149 个文件、**612 处数据访问入口**、**103 个数据集合**
- 路线决策：兼容层先行 / 开关式回滚 / 分阶段推进
- 本次回归覆盖 R1 基础设施 + R2 落地（聚合管道、`bulk_write`、审计库分离）

---

## 9. 签署栏

| 角色 | 事项 | 签署 |
|---|---|---|
| 开发者 | 已处理 QF-DB-001（P1，已修复并复测 19/19）、QF-DB-003（已补齐依赖，复测 22/22）、QF-DB-012（已修复，复测 22/22） | |
| 开发者 | 已确认 QF-DB-002 的处置方式（测试基建问题，不在本轮范围） | |
| 测试 | 已复测并确认修复生效 | |
| 发布 | 已批准发布（无 P0，原 P1 已修复；剩余 2 项 P2 均为测试基建/依赖约束，非产品代码缺陷） | |

---

## 附：本报告的方法论说明

本报告按 QualityForge 方法论执行：**证据优先**（每条结论都有命令输出、行号或配置片段）、**穷尽优先于抽样**（三服务全量测试 + 差分测试而非抽样）、**区分三件事**（QF-DB-003 标记为 `blocked` 而非 `fail`，因为工具未装不是项目缺陷）。

`qualityforge` 的 `qf_record` / `qf_report` 工具在本次执行中因返回值 schema 校验缺陷（`additionalProperties: false` 与实际返回字段不匹配）无法写入，故本报告为手工产出，结构与工具输出等价。审计数据目录 `.qualityforge/` 保留的是上一轮审计的历史数据（1211 项），与本轮记录相互独立。
