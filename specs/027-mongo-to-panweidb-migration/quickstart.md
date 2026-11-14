# Quickstart: MongoDB → PanWeiDB 数据后端迁移

**Feature**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Tasks**: [tasks.md](./tasks.md)

**用途**: 本文件是**可执行的验收清单**。每条命令都可直接复制运行，并给出预期结果。
R1 的每条命令均已在真实 PanWeiDB 3.2.0 上实测通过。

> **凭据约定**: 本文件不硬编码任何口令（遵循 constitution 原则 III）。
> 请自行导出环境变量：
>
> ```bash
> export PW_HOST=127.0.0.1 PW_PORT=5432 PW_USER=boncuser PW_DB=bonc PW_SCHEMA=mogo_dev
> export PW_PASSWORD='<你的口令>'
> export PW_DSN="host=$PW_HOST port=$PW_PORT user=$PW_USER password=$PW_PASSWORD dbname=$PW_DB"
> ```

---

## 0. 前置条件

| 项 | 要求 |
|---|---|
| 目标库 | PanWeiDB 3.2.0 可达；账号具备在目标库创建 schema 的权限 |
| 驱动 | `psycopg[binary]` + `psycopg-pool`（已在三个服务的锁定文件中） |
| 源库 | MongoDB 可达（仅搬迁与端到端验证需要） |
| Python | 3.13（admin-api / chat-api）/ 3.10（document-parser） |

**环境提示**（本机已踩过的坑）：

- 本机 `pip-compile` 需 `env -u PYTHONPATH`，否则被沙箱的 `sitecustomize` 拦成
  `PermissionError`。
- Docker Hub 与 `docker.m.daocloud.io` 可能返回 502；`--docker` 模式的锁定文件
  生成会因此失败（见步骤 7）。

---

## 1. 默认后端：确认行为与迁移前一致（FR-002 / SC-001）

```bash
cd services/admin-api
unset MOGO_DATA_BACKEND
env -u PYTHONPATH python -c "
import app.core.db as db
from app.core.config import settings
assert settings.effective_data_backend == 'mongo'
assert db.is_panweidb_backend() is False
print('✅ 默认后端 =', settings.effective_data_backend)
"
```

**预期**: 输出 `✅ 默认后端 = mongo`，且**不产生任何到 PanWeiDB 的连接**。

---

## 2. 切换后端：参数缺失时显式失败（FR-004）

```bash
cd services/admin-api
env -u PYTHONPATH MOGO_DATA_BACKEND=panweidb python -c "
import app.core.db as db
for label, fn in (('init_db()', db.init_db), ('get_db()', db.get_db)):
    try:
        fn(); print(f'❌ {label} 本应抛错')
    except RuntimeError as e:
        print(f'✅ {label} 显式拒绝：{str(e)[:60]}...')
"
```

**预期**: 两个入口各输出一行 `✅ ... 显式拒绝`，**不回退到 MongoDB**。

---

## 3. 真实连通与健康快照（FR-005 / FR-006 / SC-002）

```bash
cd services/admin-api
env -u PYTHONPATH \
  MOGO_DATA_BACKEND=panweidb \
  PANWEIDB_HOST=$PW_HOST PANWEIDB_PORT=$PW_PORT \
  PANWEIDB_USER=$PW_USER PANWEIDB_PASSWORD=$PW_PASSWORD \
  PANWEIDB_DB=$PW_DB PANWEIDB_SCHEMA=$PW_SCHEMA \
  python -c "
import asyncio
from app.core import pg, db
async def go():
    await db.init_backend()
    print('health =', await pg.health_payload())
    handle = db.get_db()
    print('ping   =', await handle.command('ping'))
    print('tables =', len(await handle.list_collection_names()))
    await db.close_backend()
asyncio.run(go())
"
```

**预期**:

```
health = {'backend': 'panweidb', 'target': 'panweidb://<user>@<host>:<port>/<db>', 'reachable': True}
ping   = {'ok': 1}
tables = 103
```

> `target` 字段**不含口令**。

---

## 4. 建表：生成 + 巡检（FR-017 / FR-018 / SC-005）

> **迁移场景务必加 `--from-mongo`**：静态扫描有已知漏扫（大写常量 / 实例属性 /
> 带前缀下标 / 属性访问 / 配置项驱动的集合名），实测漏了 11 个集合。
> 源 MongoDB 的**实际集合**才是权威来源。

```bash
# 4a. 列出扫描到的集合与来源（静态）
python scripts/pg/generate_ddl.py --list | tail -3
# 预期: 共 103 个集合（静态扫描 103 个）

# 4b. 权威来源：并上源 MongoDB 的实际集合
python scripts/pg/generate_ddl.py --from-mongo "mongodb://127.0.0.1:27017" \
  --mongo-db mogo_dev --list 2>/dev/null | tail -1
# 预期: 共 114 个集合（静态扫描 103 个）

# 4c. 生成 DDL
python scripts/pg/generate_ddl.py --schema "$PW_SCHEMA" \
  --from-mongo "mongodb://127.0.0.1:27017" --mongo-db mogo_dev \
  --out deploy/pg/schema.sql
# 预期: ✅ 已写入 deploy/pg/schema.sql（114 个集合）

# 4d. 建表（幂等，可重复执行）
time psql "$PW_DSN" -f deploy/pg/schema.sql
# 预期: 114 张表 / 229 个 btree 索引，耗时 < 10s（实测 1.6s）
#       DDL 里不应出现 USING GIN（见步骤 4e）

# 4e. 确认没有 GIN 索引（openGauss 的 jsonb GIN 遇空字符串即报错）
grep -c "USING GIN" deploy/pg/schema.sql
# 预期: 0

# 4f. 巡检
python scripts/pg/generate_ddl.py --schema "$PW_SCHEMA" \
  --from-mongo "mongodb://127.0.0.1:27017" --mongo-db mogo_dev \
  --check --dsn "$PW_DSN" 2>/dev/null | tail -2
# 预期: ✅ 全部表已就位
```

**验证隐式建表（FR-015）**: 对一个未预建表的集合直接写入。

```bash
cd services/admin-api && env -u PYTHONPATH \
  MOGO_DATA_BACKEND=panweidb PANWEIDB_HOST=$PW_HOST PANWEIDB_PORT=$PW_PORT \
  PANWEIDB_USER=$PW_USER PANWEIDB_PASSWORD=$PW_PASSWORD \
  PANWEIDB_DB=$PW_DB PANWEIDB_SCHEMA=$PW_SCHEMA \
  python -c "
import asyncio
from app.core import db
async def go():
    await db.init_backend()
    coll = db.get_db()['auto_created_probe']
    await coll.insert_one({'_id': 'x1', 'v': 1})
    print('✅ 隐式建表 + 写入成功:', (await coll.find_one({'_id': 'x1'}))['v'])
    await coll.delete_many({})
    await db.close_backend()
asyncio.run(go())
"
```

---

## 5. 兼容门面：真实库端到端（FR-007–FR-016 / SC-002）

### 5a. 纯逻辑单测（不需要数据库）

```bash
cd services/admin-api
env -u PYTHONPATH python -m pytest tests/test_pg_compat.py -q
# 预期: 29 passed
```

覆盖：过滤/更新算子映射、**「占位符数量 = 参数数量」不变量**、深合并回归、
未覆盖算子显式失败。

### 5b. 一致性守卫

```bash
cd /Users/cooper/Github/mogo
env -u PYTHONPATH python -m pytest deploy/tests/test_pg_compat_parity.py -q
# 预期: 11 passed
```

覆盖：异步两份副本**逐字节一致**、同步副本等于异步副本的机械变换结果、
**禁止引入 A 模式禁用函数/运算符**、异步服务健康检查必须用异步探测。

### 5c. 真实 PanWeiDB 端到端

```bash
# 门面在真实库上的完整用例（写入/查询/算子/更新/upsert/游标/索引/删除/未覆盖）
# 异步门面 ≥ 60 项、同步门面 ≥ 25 项，通过率必须 100%
```

**预期**: 异步 **64/64**、同步 **26/26**。

**重点回归项**（这三条是 R1 期间真实踩到的坑）：

| 用例 | 断言 |
|---|---|
| 父对象缺失时的点号 `$set` | `{"$set": {"a.b.c": 1}}` 在 `a` 不存在时**创建中间层**且同级字段保留 |
| `$unset` 嵌套路径 | 不使用 `#-` 运算符也能正确删键；父节点缺失时是 no-op |
| `$addToSet` 去重 | 数组内容与文档数据库一致；SQL 占位符数量等于参数数量 |

---

## 6. 数据搬迁：演练 → 搬迁 → 重跑 → 校验（FR-019–FR-023 / SC-003 / SC-004）

```bash
# 6a. 演练：只统计不写库
python scripts/pg/migrate_mongo_to_panweidb.py \
  --mongo-uri "mongodb://127.0.0.1:27017" --mongo-db mogo_dev \
  --dsn "$PW_DSN" --schema "$PW_SCHEMA" --dry-run
# 预期: 逐集合输出 "[dry-run] <coll>: N 篇文档"，不写入任何行

# 6b. 正式搬迁（幂等；中断后直接重跑）
python scripts/pg/migrate_mongo_to_panweidb.py \
  --mongo-uri "mongodb://127.0.0.1:27017" --mongo-db mogo_dev \
  --dsn "$PW_DSN" --schema "$PW_SCHEMA"
# 预期: 逐集合输出 "N 篇文档已写入"

# 6c. 幂等验证：重跑后计数不增加（SC-004）
python scripts/pg/migrate_mongo_to_panweidb.py ... --schema "$PW_SCHEMA"
# 预期: 再次输出同样的写入数，但目标库文档数不变（ON CONFLICT DO UPDATE）

# 6d. 对账收敛（源库在搬迁期间仍被写入时必需）
python scripts/pg/migrate_mongo_to_panweidb.py ... --schema "$PW_SCHEMA" --prune
# 预期: 若源库在搬迁期间删过行，输出 "对账清理 N 行（源库已不存在的行）"
#       否则输出 "对账清理 0 行"

# 6e. 计数校验（SC-003）
python scripts/pg/migrate_mongo_to_panweidb.py ... --schema "$PW_SCHEMA" --verify
# 预期: 逐集合 "✅ <coll> mongo=N panweidb=N"，最后 "✅ 计数全部一致"

# 6f. 续跑
python scripts/pg/migrate_mongo_to_panweidb.py ... --schema "$PW_SCHEMA" --resume
# 预期: "--resume：跳过 K 个已完成集合"
```

> **为什么需要 6d**：搬迁只做 upsert，**不传播删除**。upsert 能保证「源库有的目标库
> 也有」，但保证不了「目标库没有源库已删的」。对**活跃的**源库（有会话 GC / TTL 清理），
> 两次搬迁之间源库删掉的行会残留在目标库，导致 `--verify` 报「目标多于源」。
> 实测踩到过：`end_user_sessions` 目标 20 行 vs 源 19 行，多出的是一行已过期会话。

**只读保证（FR-022）**: 搬迁工具只对源库执行 `find`，不对源库做任何写操作；
目标库写入一律 `ON CONFLICT DO UPDATE`，`--prune` 的删除只作用于**目标库**。

---

## 7. 依赖锁完整性（FR-028 / SC-007）

```bash
# 重新生成（改动依赖后必须执行）
bash scripts/generate-hashes.sh admin-api
bash scripts/generate-hashes.sh chat-api
bash scripts/generate-hashes.sh document-parser --docker 3.10   # 必须 3.10

# 完整性安装验证（Dockerfile 的实际验收条件）
pip install --require-hashes -r services/admin-api/requirements.txt
pip install --require-hashes -r services/chat-api/requirements.txt
pip install --require-hashes -r services/document-parser/requirements.txt
```

**预期**: 三个服务的锁定文件均可通过完整性校验安装。

> **已知限制**: 若 Docker Hub 与 `docker.m.daocloud.io` 不可达，
> `--docker 3.10` 会失败（镜像拉不到）。此时 document-parser 的锁定文件需手工合并，
> 并记录依据。**网络恢复后必须补跑**上面第三条命令，以恢复单一生成来源。

---

## 8. 回滚（FR-001 / SC-008）

```bash
# 回滚 = 改一个环境变量并重启，不需要改动任何代码
export MOGO_DATA_BACKEND=mongo
docker compose up -d --no-deps admin-api chat-api document-api document-worker
```

**预期**: 服务恢复原行为；源库数据在搬迁期间保持原样（搬迁只读），无需回迁。

---

## 9. 验收清单汇总

| # | 项 | 命令 | 预期 | 状态 |
|---|---|---|---|---|
| 1 | 默认后端不变 | 步骤 1 | `mongo`，零额外连接 | ✅ |
| 2 | 参数缺失显式失败 | 步骤 2 | 两处显式拒绝，不回退 | ✅ |
| 3 | 真实连通与健康 | 步骤 3 | `reachable: True`，表数正确 | ✅ |
| 4 | 建表与巡检 | 步骤 4 | 114 表 / 229 btree 索引 / **0 GIN** / 1.6s | ✅ |
| 5 | 隐式建表 | 步骤 4 末 | 未预建表也能写入 | ✅ |
| 6 | 纯逻辑单测 | 步骤 5a | 29 passed | ✅ |
| 7 | 一致性守卫 | 步骤 5b | 14 passed | ✅ |
| 8 | 门面端到端 | 步骤 5c | 异步 64/64、同步 26/26 | ✅ |
| 9 | 搬迁全链路 | 步骤 6 | 演练/搬迁/对账/校验全通过 | ✅ |
| 10 | 门面回读搬迁数据 | 步骤 6 + 5c | 字段与嵌套结构一致，可继续更新 | ✅ |
| 11 | 依赖锁完整性 | 步骤 7 | 三个服务全部通过 | ✅ |
| 12 | 回滚 | 步骤 8 | 仅改环境变量 | ✅ |
| 13 | **真实数据入库** | 步骤 4–6 全跑 | 17,785 篇 / 5.5s；88 集合计数全一致 | ✅ |
| 14 | **聚合管道差分** | 步骤 9 | 11 组管道在 Mongo 与 PanWeiDB 上结果一致 | ✅ |
| 15 | **bulk_write 差分** | 步骤 10 | 5 个计数 + 落库文档集合一致，8/8 | ✅ |
| 16 | **审计库分离** | 步骤 11 | 独立 schema、业务不可见、未配置时回退 | ✅ |

---

## 9. 差分测试（R2，最主要的验收方式）

差分测试是 R2 的主要验收手段——**同一批操作在 MongoDB 与 PanWeiDB 上跑并比对结果**，
比静态分析可靠得多。脚本已固化在仓库里：

```bash
# 前置：mogo_backend 是 internal 网络，容器无外网且发布不了端口，需先起一个
# TCP 转发容器把栈内 MongoDB 映射到宿主机（详见 docs/mongo-to-panweidb-migration-plan.md 第 8 节）
python scripts/pg/verify_mongo_pg_diff.py \
  --mongo-uri "mongodb://127.0.0.1:27018" --mongo-db mogo_dev \
  --dsn "host=127.0.0.1 port=5432 user=boncuser password=... dbname=bonc" \
  --schema mogo_dev
```

**预期**：`通过 19 / 失败 0`（聚合 10 组管道 + `$percentile` 1 项 + `bulk_write` 8 项）。

脚本覆盖的管道：`$match`+`$group` 计数 / 全局 `_id: None` 聚合 / `$min`/`$max`/`$avg` /
`$sort`+`$group`+`$first`/`$last` / `$group`+`$sort`+`$limit` / `$count` 阶段 /
`$push`/`$addToSet` / `$cond` 在 `_id` 与 `$sum` 里 / 复合 `_id` / 大数据集（8,706 行）。
`$percentile` 因 MongoDB 6.0 不支持而单独验证。
bulk_write 覆盖六种请求与 upsert，比对 `inserted`/`matched`/`modified`/`deleted`/`upserted`
五个计数与落库文档集合，外加空请求列表。

## 10. bulk_write 差分测试

已并入步骤 9 的脚本。

## 11. 审计库分离（R2）

```bash
MOGO_DATA_BACKEND=panweidb PANWEIDB_AUDIT_SCHEMA=mogo_audit ... python -c "
import asyncio
from app.core import db

async def go():
    await db.init_backend()
    audit, biz = db.get_audit_db(), db.get_db()
    print('隔离生效:', audit._schema != biz._schema)
    coll = audit['system_audit_logs']
    await coll.insert_one({'_id': 'probe'})
    print('独立 schema 写入:', await coll.find_one({'_id': 'probe'}) is not None)
    print('业务 schema 不可见:', await biz['system_audit_logs'].find_one({'_id': 'probe'}) is None)
    await coll.delete_many({'_id': 'probe'})
    await db.close_backend()

asyncio.run(go())
"
```

**预期**：`隔离生效: True`、`独立 schema 写入: True`（schema 不存在时由
`CREATE SCHEMA IF NOT EXISTS` 自举）、`业务 schema 不可见: True`。
不配置 `PANWEIDB_AUDIT_SCHEMA` 时回退业务 schema。

---

**R2 已交付**（见 [tasks.md](./tasks.md) T082–T087，均已勾选）：

- 域级开关（`effective_data_backend_for`）、202 处索引的 unique/sparse/partial 语义逐点核对（T082–T083）
- 正则方言与按对象比较主键的调用点核对（T084–T085）
- document-parser 锁定文件生成、`/speckit-checklist` 与 `/speckit-analyze` 门禁登记（T086–T087）
