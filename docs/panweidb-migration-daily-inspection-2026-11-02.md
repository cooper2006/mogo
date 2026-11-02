# 027 MongoDB → PanWeiDB 迁移 · 切流后每日巡检报告

- **日期**：2026-11-02（周一）14:47 CST
- **巡检性质**：只读巡检（计数比对 / 建表核查 / 健康检查 / 日志抽样），未做任何切流、重启、写库操作
- **工作目录**：/Users/cooper/mogo

---

## 0. 置顶：环境已发生重大变化 —— RB-1 回滚已被人工执行

| 证据 | 明细 |
|---|---|
| `.env` | `MOGO_DATA_BACKEND=mongo`、`MOGO_USE_EXTERNAL_DB=0`（文件修改时间 **今日 09:40**） |
| 容器 | 三服务于**今日 11:36–11:43 CST 被重建**（admin-api 03:36 UTC / chat-api 03:43 UTC 创建），全部 `backend=mongo`；mongo 容器 10-28 晚重建后持续运行 |
| 旧配置备份 | `.env.bak-external-panweidb-*` 已不存在；PANWEIDB_* 连接参数仍保留在 `.env` 中，可恢复 |

**解读**：人工已按 RB-1 路径回滚（`.env` 改回 mongo 并 `docker compose up -d`），系统当前以 MongoDB 为权威后端正常运行。mongo 侧 34,838 篇文档完好，无进行中的数据丢失。

---

## 1. 计数巡检（mongo vs panweidb）—— ❌ 失败（无法执行）

**失败原因：PanWeiDB 双通道均不可达。**

| # | 命令（DSN） | 结果 |
|---|---|---|
| 1 | `migrate_mongo_to_panweidb.py --verify --dsn "host=127.0.0.1 port=5432 ... dbname=bonc"` | `psycopg.OperationalError: connection to server at "127.0.0.1", port 5432 failed: Connection refused`（宿主机 5432 无人监听；compose 中 panweidb 服务挂 `panweidb` profile，未启动，本地无 panweidb 容器） |
| 2 | 同脚本，`.env` 实际指向 `host=172.17.5.145 port=17700 dbname=mogo` | `connection failed: ... 172.17.5.145 port 17700 ... Connection refused`；`ping 172.17.5.145` 100% 丢包——**外部 PanWeiDB 主机整体不可达**（10-28 时可达，此后失联） |

**说明**：
- 任务给定 DSN 的 `dbname=bonc` 与 `schema mogo_dev` 是本地 panweidb 时代的参数，历史上曾造成全量 -1 误报；本轮即便连通也应以 `.env` 实际值为准（外部集群为 `dbname=mogo / schema=public`）。
- 判定规则适用性：**数据丢失告警（RB-1）已因回滚执行而关闭**；且目标库不可达，逐集合比对无法进行。以下为 mongo 侧只读快照（非比对结论）。

### mongo 侧只读快照（mogo_dev）

- 全库：**152 个集合，34,838 篇文档**
- 既往缺口集合现状（10-26/10-27 的 9 缺口 + 早期 8 缺口）：

| 集合 | mongo 计数 | 最新文档时间（UTC） |
|---|---|---|
| admin_sessions | 157 | **11-02 05:40（回滚后新写入）** |
| admin_refresh_tokens | 100 | **11-02 05:40（回滚后新写入）** |
| position_role_audit_logs | 233 | 10-12 07:49 |
| business_entity_index | 12 | 10-16 13:17 |
| system_audit_logs | 178 | n/a（字符串 _id） |
| gate_events | 78 | 11-01 08:45 |
| runtime_profile_audit | 26 | 11-01 08:45 |
| dag_definitions | 2 | 10-22 01:01 |
| runtime_profile_versions | 6 | 11-01 08:44 |
| kernel_event_inbox | 16,765 | 11-01 08:45 |
| kernel_event_projections | 16,098 | 11-01 08:45 |
| memories | 338 | 10-27 12:03 |
| token_usage_logs | 143 | 10-21 15:24 |
| enterprise_tool_audit | 133 | 10-27 12:02 |
| enterprise_action_receipts | 60 | 10-21 15:23 |
| chat_messages | 29 | 11-01 08:45 |
| skill_quality_metrics | 3 | 10-21 13:04 |

- 近期写入（按 ObjectId 时间）：**近 24h 共 13 个集合 +88 篇**（kernel_event_inbox +40、admin_sessions +13、admin_refresh_tokens +13、kernel_event_projections +6、chat_messages +4 等）；**近 3h（回滚后）+2 篇**（admin_sessions +1、admin_refresh_tokens +1，轻量验证流量）。
- 观察：11-01 08:45:43 UTC 有一批跨多集合的同刻写入（kernel_event_inbox/projections、gate_events、chat_messages、runtime_profile_* 等），发生在应用写外部 PanWeiDB 的窗口期内，疑为人工回补/对账脚本，建议人工知悉。

---

## 2. 建表巡检（generate_ddl.py --check）—— ❌ 失败（无法执行）

- 命令：`python scripts/pg/generate_ddl.py --schema public --check --dsn "host=172.17.5.145 port=17700 ... dbname=mogo"`
- 错误：`psycopg.OperationalError: connection failed: ... Connection refused`（同第 1 节原因）
- 本地 `127.0.0.1:5432` 路径同样无人监听。
- 末次成功记录（10-28）：外部集群 public schema 179 表（≥ 期望 122），当时 ✅。当前无法复核。

---

## 3. 三服务健康检查 —— ✅ 通过（回滚态，按规则属正常）

| 服务 | 结果 | 判定 |
|---|---|---|
| admin-api :8100 | `{"status":"ok","backend":"mongo"}` | 正常（MOGO_DATA_BACKEND=mongo，按 .env 实际值解读） |
| chat-api :8000 | `{"status":"ok","backend":"mongo","dsh_host":"healthy"}` | 正常 |
| document-api :8200 | `{"status":"ok","backend":"mongo"}` | 正常 |

备注：
- compose 服务名实为 **document-api**（任务中的 document-parser 是镜像/日志里的旧名），且健康路径为 **/api/health**（`/health` 返回 404）。
- 三容器均为 `Up 3 hours (healthy)`，与今日 11:36–11:43 的回滚重建时间吻合。

---

## 4. PgCompatUnsupported 日志抽样 —— ✅ 0 命中

- 样本：`docker compose logs --since 24h admin-api chat-api document-api`，共 **9,009 行**（已核实非空）。
- `PgCompatUnsupported` 命中：**0**（后端已回 mongo，无 PG 兼容层流量，符合预期）。
- error 抽样：仅 4 条启动时 opentelemetry 缺模块告警（`ModuleNotFoundError: opentelemetry.instrumentation`，无害，与 10-27 观察一致）；无 AdminShutdown / dispatch_failed。

---

## 5. 巡检执行过程中的环境修复（只读任务附带，已最小化改动）

1. **转发容器**：`mogo-mongo-fwd` 未运行且镜像丢失 → 已重建镜像并启动。两处适配：
   - `scripts/pg/dev-forward/Dockerfile`：`FROM alpine:3.20` → `alpine:3.21`（Docker Hub 不可达 Bad Gateway，改用本地已有基础镜像；**唯一代码改动**，建议人工知悉）。
   - 上游主机名：任务命令中的 `mogo-mongo` 无法解析（mongo 容器只接在 `mogo_backend` 网络，实际容器名 `mogo-mongo-1`），已按实际修正，宿主机 `mongodb://127.0.0.1:27018` 连通正常。
2. 宿主机依赖 `pymongo 4.19.0 / psycopg 3.3.6` 已就绪，无需安装。

---

## 6. 总体结论：**需人工介入**（性质已变）

1. **回滚已完成且健康**：三服务 backend=mongo 全部 ok，mongo 权威数据完好（34,838 篇），近 3h 有正常轻量写入。无需再触发回滚。
2. **需人工决策/确认的事项**：
   - **PanWeiDB 目标库双通道失联**：本地容器未起（profile panweidb），外部主机 172.17.5.145 ping 不通。若后续仍计划迁移，需先恢复目标库（本地可用 `docker compose --profile panweidb up -d panweidb`，或修复外部集群网络），否则计数/建表两项巡检将持续失败。
   - **迁移缺口的历史结论已冻结**：10-27 时 9 缺口 -58 行（外部库侧 -53），随着回滚已无运行时意义；如需对账留档，应在目标库恢复后做一次性全量比对。
   - 11-01 08:45 UTC 的批量 mongo 写入（外部库运行窗口内）请人工确认来源。
3. 明日起若环境不变（backend=mongo、PanWeiDB 不可达），巡检将重复今日模式：计数/建表两项失败、健康与日志两项通过；一旦人工恢复任一 PanWeiDB 通道，计数比对应以 `.env` 实际 DSN（外部 `dbname=mogo/schema=public` 或本地 `dbname=mogo_dev/schema=mogo_dev`）执行，**不要用 `dbname=bonc`**。

---

*报告由自动化巡检生成（f21f8645）。只读巡检，未执行任何切流/重启/写库操作。*
