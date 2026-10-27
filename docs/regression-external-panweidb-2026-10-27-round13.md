# ARM 准生产回归 · 2026-10-27 round 13（外部 PanWeiDB 回归）

> 本轮形态：**用户将后端指向栈外 PanWeiDB（`172.17.5.145:17700`，库 `mogo`，schema `public`，`boncuser/1qaz!QAZ`）→ 停栈内 panweidb/mongo → 应用指向外部库 → 确认 healthy → 全套件回归**。镜像 `570012e` 不变，**无代码改动**。

## 一、外部库接入配置

| 项 | 值 |
| --- | --- |
| 外部实例 | `172.17.5.145:17700` |
| 数据库 / schema | `mogo` / `public` |
| 账号 | `boncuser`（口令见 `.env`，不入库） |
| `select version()` | `PostgreSQL 9.2.4 on x86_64-pc-linux-gnu` |
| public 表数（接入前） | **179** |

`.env` 关键项（已本地备份 `.env.bak-external-panweidb-20261027-212133`）：

```
MOGO_USE_EXTERNAL_DB=0          # 不启用外部 overlay，保留栈内 redis 等
MOGO_DATA_BACKEND=panweidb
PANWEIDB_HOST=172.17.5.145
PANWEIDB_PORT=17700
PANWEIDB_USER=boncuser
PANWEIDB_PASSWORD=<见 .env>
PANWEIDB_DB=mogo
PANWEIDB_SCHEMA=public
```

- 停掉栈内 `mogo-panweidb-1`、`mogo-mongo-1`（外部模式下不再需要）。
- 用 `./mogo compose ... up -d --no-deps` 重建 4 个应用服务容器（注入本地镜像 tag `<service>:570012e`，`--profile panweidb` 保证 profile 校验通过，`--no-deps` 不拉起栈内 panweidb）。

## 二、连通性与健康

| 探针 | 结果 |
| --- | --- |
| 容器内 TCP → `172.17.5.145:17700` | 通（双网络 `mogo_backend`+`mogo_public`） |
| 容器内 `psycopg` 直连 | **0.1s** 连上，`public tables = 179` |
| 应用 `pg.init_async_pg()` → 外部库 | `backend = panweidb`, `target = panweidb://boncuser@172.17.5.145:17700/mogo`, `public tables = 179` |
| gateway `/askai-api/health` | `backend=panweidb`, `reachable=true` |
| admin-api `/health` | `backend=panweidb`, `target=panweidb://boncuser@172.17.5.145:17700/mogo`, `reachable=true` |
| chat-api `/health` | `backend=panweidb`, `reachable=true` |
| document-api `/health` | `backend=panweidb`, `reachable=true` |
| gateway `/healthz` | `ok` |

## 三、回归结果（全部在外部 PanWeiDB 下）

| 套件 | 跑法 | 结果 | 对照 round 11/12 |
| --- | --- | --- | --- |
| admin-api 全量 pytest | 容器 `--network mogo_backend --network mogo_public`，`-m "not dsh_host_e2e"` | **1470 passed, 1 skipped, 0 failed**（56.57s） | 逐字一致 |
| document-parser 全量 pytest | 容器内 | **28 passed, 0 failed**（10.29s） | 逐字一致 |
| chat-api 全量 pytest | 容器内，`MOGO_TEST=1`，`-m "not dsh_host_e2e and not network"` | **2985 passed, 3 skipped, 27 deselected, 0 failed**（49.10s） | 逐字一致 |
| deploy/tests 守卫 | 宿主 `python3`（ServBay 3.13.16），`PYTHONPATH=services/admin-api`，忽略 mongo-only 文件 | **275 passed, 13 skipped, 0 failed**（20.10s） | 逐字一致 |

- 回归后外部库表数仍为 **179**（只读为主，未产生污染）。
- 容器 11 个：admin-api / chat-api / document-api / gateway / redis / weaviate / admin-web / user-web / dsh-runtime-host 均 `healthy`；document-worker、mongo-fwd 无 healthcheck（既有）。

## 四、本轮发现并修复的测试工具缺陷

初版回归脚本 `gen_env_args.py` 用 `shlex.quote(kv)` 拼参数串，再以 `${ENVS}` **不加引号**展开。bash 不会对展开结果重新做引号解析，于是含 `!` 的值被包成 `'PANWEIDB_PASSWORD=1qaz!QAZ'`，Docker 按首个 `=` 切分后变量名变成 `'PANWEIDB_PASSWORD`，容器里 `PANWEIDB_PASSWORD` 实为 `None`：

```
PW= None
QUOTED_NAME= "1qaz!QAZ'"
```

- round 11/12 密码是 `Bonc@2026`（`@` 属 shlex 安全字符）不触发引号，故未暴露；本轮 `1qaz!QAZ` 的 `!` 触发。
- 修复：改用 `gen_env_file.py` 生成 Docker `--env-file`（无 shell 展开、无引号问题），并复验 `PW='1qaz!QAZ'`、`HOST='172.17.5.145'` 均正确。
- **说明**：四套件在缺陷态下同样全绿，因为单测多数走 mock；但以修复后重跑的 `--env-file` 结果为准，且应用层 `init_async_pg()` 真实连上外部库（179 表）。

## 五、deploy 守卫差异说明

- 忽略 `deploy/tests/test_ontology_permission_mongo_parity.py`：该文件文档化要求 **mongo 后端 + 容器网络** 运行，当前 `MOGO_DATA_BACKEND=panweidb` 下首条断言即失败（`assert not is_panweidb_backend()`），属 030 遗留的 skip 条件写法问题，非本轮引入。
- 未设置 `MOGO_TLS` 环境变量，让 `.env` 的 `MOGO_TLS=0` 生效，避免 `test_tls_cert_guard_reads_switch_from_dotenv` 的既有 env 泄漏误报。

## 六、结论

- 在 `570012e` 镜像不变、**无代码改动**前提下，应用成功切到栈外 PanWeiDB（`PostgreSQL 9.2.4`）并全部 `healthy`；
- 四套件 + 健康探针全绿，与 round 11（栈内 PanWeiDB）/ round 12（mongo）基线**逐字一致**；
- 外部库回归**未引入回归**；
- 唯一实质产出是修复了回归脚本的 env 传参缺陷（`--env-file`），并把该轮报告落盘。

## 七、未提交改动说明

- 本轮**未修改任何 tracked 文件**；`git status` 中的 `M docker-compose.yml` 属**上一任务（后端变量合并方案 A）**的在途改动，与本轮无关，未纳入。
- 未跟踪：`.dsh-tmp/`、`docs/panweidb-migration-daily-inspection-2026-10-27.md`、`docs/regression-arm-orbstack-2026-10-27-round11.md`、`docs/regression-arm-orbstack-2026-10-27-round12.md`、本文件。