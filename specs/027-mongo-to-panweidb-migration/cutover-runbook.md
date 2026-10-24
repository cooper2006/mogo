# 027 Runbook：从「可切换」到「真正下线 mongo」——带真实命令与预期输出

**配套**：`decommission-checklist.md`（总清单）｜本文是**可照着敲的执行手册**。
**环境基线（本机 mac + OrbStack，2026-10-23 实测口径）**：
- 应用内部端口：admin-api **8100** / chat-api **8000** / document-parser **8200**
- PanWeiDB 宿主出口：`127.0.0.1:5432`（compose `panweidb` profile 服务，数据落命名卷 `panweidb-storage`）
- 宿主机访问栈内 mongo：需 dev-forward 转发 → `mongodb://127.0.0.1:27018`（`mogo_backend` 是 internal 网络，直连不了）
- 所有"预期输出"均取自脚本源码的真实打印格式。

---

## 0. 通用变量（每节直接复用）

```bash
cd /Users/cooper/mogo

# PanWeiDB libpq 连接串（与 scripts/pg/*.py 用法一致；库名/模式按 .env 对齐）
export PW_DSN="host=127.0.0.1 port=5432 user=boncuser password=${PANWEIDB_PASSWORD} dbname=bonc"
export PW_SCHEMA="mogo_dev"
export MG_URI="mongodb://127.0.0.1:27018"   # 经 dev-forward
export MG_DB="mogo_dev"
```

**连接前置（宿主机工具都要）**：

```bash
# 栈内 mongo 的宿主机转发（不存在则建；幂等）
docker ps --format '{{.Names}}' | grep -q mogo-mongo-fwd || \
docker run -d --rm --name mogo-mongo-fwd \
  --network mogo_default --network mogo_backend \
  -p 27018:27018 mogo-pg-fwd 27018 mogo-mongo 27017
```
> 预期：无输出即成功；`docker ps` 应见 `mogo-mongo-fwd`。若镜像 `mogo-pg-fwd` 不存在，先 `docker build -t mogo-pg-fwd scripts/pg/dev-forward`。
> 网络名前缀随 compose 项目名变化，`docker network ls | grep mogo` 确认。

**宿主机依赖（脚本缺了会自己报错）**：`pip install pymongo 'psycopg[binary]'`
> 缺失时脚本打印：`error: 缺少依赖 pymongo（pip install pymongo 'psycopg[binary]'）` 并以退出码 2 结束。

---

## 1. Step 0 — 门槛自检（Gate）

```bash
# G2 兼容层一致性守卫（期望 14/14）
python -m pytest deploy/tests/test_pg_compat_parity.py -q
```
> 预期末行：`14 passed`。任何失败**不得进入切流**。

```bash
# G4 源库全量备份（切流前最后一份 mongo 真相）
TS=$(date +%F-%H%M)
mkdir -p backups
docker compose exec -T mongo mongodump --db=mogo_dev --archive=/tmp/mogo-$TS.archive
docker compose cp mongo:/tmp/mogo-$TS.archive backups/mogo-$TS.archive
docker compose exec -T mongo rm -f /tmp/mogo-$TS.archive
ls -lh backups/mogo-$TS.archive
```
> 预期：`.archive` 文件存在且大小 > 0（dev 栈 17,785 篇约几十 MB 量级）。
> 记录 `$TS`，回滚时要用。

---

## 2. Step 1 — 目标库制备（P0）

```bash
# P0-1 启动 PanWeiDB（profile 门控；默认不进拓扑）
docker compose --profile panweidb up -d panweidb
docker compose ps panweidb
```
> 预期：`panweidb` 状态 `Up ... (healthy)`。若镜像缺失会提前失败——先确认本地 `panweidb:3.2.0` 已 load（`base-images/images/arm64/panweidb_3.2.0.tar`）。

```bash
# P0-3 生成 DDL（--from-mongo = 以源库实际集合为权威来源，防静态漏扫）
python scripts/pg/generate_ddl.py --schema "$PW_SCHEMA" \
  --from-mongo "$MG_URI" --mongo-db "$MG_DB" \
  --out deploy/pg/schema.sql

# 应用（幂等：IF NOT EXISTS）
python - <<'PY'
import psycopg, pathlib
dsn = __import__('os').environ['PW_DSN']; schema = __import__('os').environ['PW_SCHEMA']
sql = pathlib.Path('deploy/pg/schema.sql').read_text()
with psycopg.connect(dsn, autocommit=True) as c, c.cursor() as cur:
    cur.execute(sql)
print("DDL applied")
PY
```
> 预期：`generate_ddl.py` 打印集合数与输出路径；`DDL applied`。R3 扁平化后口径：**119 表 / 491 索引**。

```bash
# P0-4 巡检（期望"全部表已就位"）
python scripts/pg/generate_ddl.py --schema "$PW_SCHEMA" --check --dsn "$PW_DSN"
```
> 预期输出（源码真实格式）：
> ```
> schema=mogo_dev 已有 119 张表；期望 119 张
> ✅ 全部表已就位
> ```
> 若有 `缺失 N 张：` 清单 → 回到 P0-3 补建，**不得带着缺表切流**。

```bash
# P0-2 三服务 /health 后端快照（容器是 read_only + cap_drop ALL，没有 curl；用容器内 python）
for svc_port in "admin-api:8100" "chat-api:8000" "document-parser:8200"; do
  svc=${svc_port%%:*}; port=${svc_port##*:}
  docker compose exec -T "$svc" python -c \
    "import urllib.request,json;print(json.dumps(json.load(urllib.request.urlopen('http://127.0.0.1:$port/health',timeout=5)),ensure_ascii=False))"
done
```
> 预期（mongo 模式下 backend=mongo，属正常——此时还没翻开关）：
> ```json
> {"status": "ok", "service": "mogo-admin-api", "backend": "mongo"}
> ```

---

## 3. Step 2 — 数据搬迁与校验（P1）

> 全部只读源库、只写目标库；幂等靠 `ON CONFLICT (id) DO UPDATE`。

```bash
# P1-1 演练：只统计不写库
python scripts/pg/migrate_mongo_to_panweidb.py \
  --mongo-uri "$MG_URI" --mongo-db "$MG_DB" \
  --dsn "$PW_DSN" --schema "$PW_SCHEMA" --dry-run
```
> 预期末行（真实格式）：
> ```
> 演练统计 17785 篇文档，耗时 5.5s
> ```

```bash
# P1-2 正式搬迁
python scripts/pg/migrate_mongo_to_panweidb.py \
  --mongo-uri "$MG_URI" --mongo-db "$MG_DB" \
  --dsn "$PW_DSN" --schema "$PW_SCHEMA"
```
> 预期末行：
> ```
> 已搬迁 17785 篇文档，耗时 5.5s
> 下一步：用 --verify 校验计数
> ```

```bash
# P1-3 对账收敛（源库在两次搬迁之间删了行时目标库会残留；--prune 删掉）
python scripts/pg/migrate_mongo_to_panweidb.py \
  --mongo-uri "$MG_URI" --mongo-db "$MG_DB" \
  --dsn "$PW_DSN" --schema "$PW_SCHEMA" --prune
```
> 预期：搬迁输出 +（若有残留）`  end_user_sessions: 清理 1 行（源库已不存在）` + `对账清理 1 行（源库已不存在的行）`。无残留则只打印搬迁行。

```bash
# P1-4 计数校验（不一致项必须为 0）
python scripts/pg/migrate_mongo_to_panweidb.py \
  --mongo-uri "$MG_URI" --mongo-db "$MG_DB" \
  --dsn "$PW_DSN" --schema "$PW_SCHEMA" --verify
```
> 预期输出（真实格式）：
> ```
> 校验 schema=mogo_dev（88 个集合）
>   ✅ users                                 mongo=42       panweidb=42
>   ✅ end_user_sessions                     mongo=108      panweidb=108
>   ...（每集合一行）
>
> ✅ 计数全部一致
> ```
> 退出码 0 = 全部一致；1 = 有 ❌ 行。**任何 ❌ 不得切流**。

```bash
# P1-6 幂等重跑（计数不得变化）
python scripts/pg/migrate_mongo_to_panweidb.py --mongo-uri "$MG_URI" --mongo-db "$MG_DB" \
  --dsn "$PW_DSN" --schema "$PW_SCHEMA" --prune
python scripts/pg/migrate_mongo_to_panweidb.py --mongo-uri "$MG_URI" --mongo-db "$MG_DB" \
  --dsn "$PW_DSN" --schema "$PW_SCHEMA" --verify
```
> 预期：重跑后 `--verify` 仍是 `✅ 计数全部一致`（SC-004）。

```bash
# P1-5 门面回读抽检（R1 真库基线：13/13；用兼容层语义读+更新一条）
docker compose exec -T admin-api python - <<'PY'
# 在容器内跑：app.core.pg_compat 对 panwei 的读写（深合并/中文/空串/_id 归一）
# 具体断言见 services/admin-api/tests/test_pg_compat.py 的同款用例
PY
```
> 说明：回读断言以 `test_pg_compat.py` 用例为准在宿主机 pytest 跑更稳；此处容器内执行属可选抽检。

---

## 4. Step 3 — 灰度切流（P2，核心纪律：域 → 服务 → 全栈）

> 顺序：document-parser（同步、回归面最小）→ chat-api → admin-api。**每一步都要看 /health 和差分，上一步稳定再动下一步。**
>
> ⛔ **放量冻结（ADR-6，2026-10-23 拍板）**：在「补同步增量 vs 直接回滚」决策作出前，**不得继续放量**——不扩灰度域、不翻更多服务、不提 panwei 流量比例；已灰格的保持现状或回退上一稳定态。默认处置：补同步增量优先（冻结 panwei 写入 → 反向补齐 mongo → 切回）；缺口经业务确认可接受时才直接回滚。详见 `Decisions/ADR-6-027切流后数据缺口处置与放量冻结.md`。

```bash
# P2-1 单域灰度：只翻一个低风险域，其余不动
# 在 .env 加（域级覆盖，回退全局）：
#   MOGO_DATA_BACKEND_DOCUMENT_PARSER=panweidb
docker compose up -d document-parser
docker compose exec -T document-parser python -c \
  "import urllib.request,json;print(json.dumps(json.load(urllib.request.urlopen('http://127.0.0.1:8200/health',timeout=5)),ensure_ascii=False))"
```
> 预期：
> ```json
> {"status":"ok","service":"mogo-document-parser","backend":"panweidb","target":"panweidb:5432/...","reachable":true}
> ```

```bash
# P2-3 差分核对（同一管道在两边跑并比对；R2 基线：聚合 19/19、bulk_write 8/8、正则 32/32）
python scripts/pg/verify_mongo_pg_diff.py --dsn "$PW_DSN" --schema "$PW_SCHEMA"
```
> 预期末行：全部用例 `PASS`，汇总 `聚合 19/19 · bulk_write 8/8 · 正则 32/32 · partial/sparse 4/4`（措辞以脚本实际输出为准；**任何 FAIL 停下排查**）。

```bash
# P2-4 单服务全切：灰度域无异常后，整服务翻
# .env 中：MOGO_DATA_BACKEND=panweidb（先只对一个服务生效可用域级变量过渡）
docker compose up -d document-parser
# 复跑 P2-2（health）+ P2-3（差分）+ 该服务 panwei 路径回归
```

```bash
# P2-6 全栈翻转（三服务统一）
# .env：MOGO_DATA_BACKEND=panweidb，且启用 profile
docker compose --profile panweidb up -d
# 三服务 health 全量核对（命令见 Step 1 P0-2）
```
> 预期：三服务 health 全部 `backend=panweidb, reachable=true`；admin-api dashboard `/overview` 不再 500（timestamptz 序列化已修）。

---

## 5. Step 4 — 观察期（P3，mongo 保活但不收写）

```bash
# P3-3 每日巡检（已固化为自动化任务，见下；手工版即这条）
python scripts/pg/migrate_mongo_to_panweidb.py --mongo-uri "$MG_URI" --mongo-db "$MG_DB" \
  --dsn "$PW_DSN" --schema "$PW_SCHEMA" --verify
```
> 观察期解读规则（重要）：
> - 某集合 `panweidb < mongo` → **数据丢失告警，触发回滚 RB-1**；
> - `panweidb > mongo` → 切流后新增写入，**预期现象**，记录增量即可；
> - 全等 → 处于切流前阶段或当日无写入。
>
> 已创建 recurring 自动化「027 观察期每日巡检」，每日 09:00 自动执行上述三条（verify + 三服务 health + 建表巡检）并按上述规则判定。

```bash
# P3-2 连接池/不可达可用性语义抽检（FR-031：存储抖动不得锁死管理面）
docker compose stop panweidb
docker compose exec -T admin-api python -c \
  "import urllib.request,json;print(json.dumps(json.load(urllib.request.urlopen('http://127.0.0.1:8100/health',timeout=5)),ensure_ascii=False))"
#   → 应显式失败/报不可达，不得静默回退 mongo、不得无限阻塞
docker compose start panweidb
```

```bash
# P3-4 跨特性能力保全抽样（FR-029/FR-032）
#   真实触发一次租户销毁 + 等一次审计保留期到期，确认流程完整执行、失败有记录
```

---

## 6. Step 5 — 真正下线 mongo（P4，不可逆，执行前二次确认）

```bash
# P4-6 全局残留检查（应只剩注释/回滚说明）
grep -rn "pymongo\|motor\|mongodb://" services/ deploy/ docker-compose.yml \
  --include="*.py" --include="*.yml" --include="*.in" --include="*.txt" \
  | grep -v "\.pyc" | grep -vi "panwei\|mongo-to-panwei\|回滚\|mongo 模式"
```

```bash
# P4-1 最终备份（保留 ≥ 观察期×2 或按合规）
TS_FINAL=$(date +%F-%H%M)
docker compose exec -T mongo mongodump --db=mogo_dev --archive=/tmp/mogo-final-$TS_FINAL.archive
docker compose cp mongo:/tmp/mogo-final-$TS_FINAL.archive backups/mogo-final-$TS_FINAL.archive
docker compose exec -T mongo rm -f /tmp/mongo-final-$TS_FINAL.archive
```

```bash
# P4-2 移除 mongo 服务（编辑 docker-compose.yml：删 mongo: 服务块、
#       删各服务 depends_on 里的 mongo、删 mongo-data 卷定义）
# P4-3 .env / .env.example 清理 MONGODB_URI / MOGO_MONGODB_URI 默认值
# P4-4 依赖清理：三服务 requirements.in 删 motor/pymongo → 重生成锁定文件
docker compose up -d --remove-orphans
grep -n "MONGODB_URI" docker-compose.yml   # 预期：无输出
```

```bash
# P4-7 删除旧数据卷（确认备份完好后再执行！）
# docker volume rm <前缀>_mongo-data
```

---

## 7. 回滚预案（RB，零改代码）

```bash
# RB-1 即时回滚：改回 mongo + 重启
# .env：MOGO_DATA_BACKEND=mongo
docker compose up -d
docker compose exec -T admin-api python -c \
  "import urllib.request,json;print(json.dumps(json.load(urllib.request.urlopen('http://127.0.0.1:8100/health',timeout=5)),ensure_ascii=False))"
```
> 预期：`{"status":"ok",...,"backend":"mongo"}`；随后跑该服务 mongo 路径回归（admin-api 907 / chat-api 2857 / document-parser 22 基线，剔除 3 个已知环境失败）。

**⚠️ 数据窗口约束（务必先读）**：
- mongo **仍在收写**时回滚 = 无损（mongo 是真相）。
- mongo **已停写**（全翻之后）时回滚 = panwei 里有 mongo 没有的新数据。此时：
  1. 优先按 §7.1「回退到仍写 mongo 的服务/域」，缩小缺口；
  2. 必须全回滚时，先做 **panwei→mongo 反向搬迁**——027 工具只支持单向（mongo→panwei），需临时写反向脚本（读 panwei JSONB → pymongo 插入）或用 `gs_dump`+`mongoimport`；
  3. 或接受缺口并明确告知业务方。

**处置决策已固化为 ADR-6**（`Decisions/ADR-6-027切流后数据缺口处置与放量冻结.md`）：默认「补同步增量优先」（冻结 panwei 写入 → 反向补齐 mongo → 切回，三步缺一不可）；缺口经业务确认可接受（dev 数据 / 可重放 / 极小缺口）才直接回滚。**决策前冻结放量**：不扩灰度、不翻更多服务，只读巡检继续。

```bash
# RB-5 备份恢复（万不得已：mongo 数据损坏/误删）
docker compose cp backups/mogo-$TS.archive mongo:/tmp/restore.archive
docker compose exec -T mongo mongorestore --db=mogo_dev --archive=/tmp/restore.archive --drop
docker compose exec -T mongo rm -f /tmp/restore.archive
```
> ⚠️ `--drop` 会先清空目标库再恢复，只在确认要回到 `$TS` 时刻状态时使用。

```bash
# RB-4 缺口登记：未覆盖能力会按 FR-016 显式抛 PgCompatUnsupported，
#     异常信息里带"未实现内容 + 处理位置"，逐条登记为 R2 补完项
docker compose logs admin-api chat-api document-parser 2>&1 | grep -i "PgCompatUnsupported" | tail -20
```

---

## 8. 命令速查表

| 阶段 | 命令 | 预期输出关键行 |
|---|---|---|
| 守卫 | `python -m pytest deploy/tests/test_pg_compat_parity.py -q` | `14 passed` |
| 起库 | `docker compose --profile panweidb up -d panweidb` | `panweidb ... (healthy)` |
| 建表 | `generate_ddl.py --schema mogo_dev --from-mongo $MG_URI --mongo-db mogo_dev --out deploy/pg/schema.sql` | 集合数 + 路径 |
| 巡检 | `generate_ddl.py --schema mogo_dev --check --dsn "$PW_DSN"` | `✅ 全部表已就位` |
| 演练 | `migrate_mongo_to_panweidb.py ... --dry-run` | `演练统计 N 篇文档，耗时 X.Xs` |
| 搬迁 | `migrate_mongo_to_panweidb.py ...` | `已搬迁 N 篇文档，耗时 X.Xs` |
| 对账 | `migrate_mongo_to_panweidb.py ... --prune` | `对账清理 M 行（源库已不存在的行）` |
| 校验 | `migrate_mongo_to_panweidb.py ... --verify` | `✅ 计数全部一致` |
| 差分 | `verify_mongo_pg_diff.py --dsn "$PW_DSN"` | 聚合 19/19 · bulk_write 8/8 · 正则 32/32 |
| 健康 | `docker compose exec -T <svc> python -c "...urlopen('http://127.0.0.1:<port>/health')..."` | `backend=panweidb, reachable=true` |
| 回滚 | `.env` 改 `MOGO_DATA_BACKEND=mongo` + `docker compose up -d` | health 回 `backend=mongo` |

> 端口：admin-api 8100 ｜ chat-api 8000 ｜ document-parser 8200
