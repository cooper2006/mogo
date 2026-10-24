# 027 MongoDB → PanWeiDB 迁移 · 切流后观察期每日巡检

- **日期**：2026-10-23（周五）16:29 CST
- **范围**：只读巡检（计数比对 / 建表核查 / 服务健康 / 错误日志抽样），未做任何切流、重启、写库操作
- **当前 .env**：`MOGO_DATA_BACKEND=PanWeiDB`（三服务 health 自报 `backend=panweidb`，解读以此为准）

---

## 🚨 置顶：数据丢失告警（触发 RB-1 回滚条件，需人工决策）

计数巡检发现 **8 个集合 panweidb < mongo**，合计缺口 **6,956 行**。按 RB-1 规则触发回滚条件（`.env` 改回 `MOGO_DATA_BACKEND=mongo` 并 `docker compose up -d`）——本巡检不执行回滚，由人工决定。

| 集合 | mongo | panweidb | 缺口 | 搬迁快照数 | mongo 最后写入 (CST) |
|---|---|---|---|---|---|
| kernel_event_inbox | 14,409 | 11,022 | **-3,387** | 8,706 | 10-21 23:24 |
| kernel_event_projections | 13,808 | 10,460 | **-3,348** | 8,176 | — |
| memories | 264 | 72 | **-192** | 无进度记录 | 10-22 15:23 |
| token_usage_logs | 139 | 119 | -20 | 115 | 10-21 23:24 |
| enterprise_tool_audit | 121 | 117 | -4 | 109 | — |
| enterprise_action_receipts | 57 | 54 | -3 | 51 | — |
| chat_messages | 22 | 21 | -1 | 18 | 10-21 23:23 |
| skill_quality_metrics | 3 | 2 | -1 | 2 | — |

**缺口成因（时间线重建，供回滚/补救决策）**：
1. 搬迁于 **2026-10-13 07:34 UTC** 完成 88 个集合（`_migration_progress` 全部 done）；
2. 此后 mongo 仍持续接收写入直至切流生效前（10-21 23:24 / 10-22 15:23 CST），这些增量未同步进 PanWeiDB；
3. 切流随容器重启于今日约 10:23 生效，之后写入只进 PanWeiDB（18 个集合出现正向增量可证）；
4. **`memories` 等 7 个集合无迁移进度记录**（`business_entity_index`/`dag_definitions`/`sys_config`/`memories`/`mesc_ontology_class_detail`/`mesc_ontology_grant`/`mesc_ontology_perm_audit`），其中 `memories` 从未搬迁，panweidb 现有 72 行均为切流后服务新写——264 行历史数据只在 mongo。

**补救方向（供人工参考，未执行）**：对 8 个集合按 `_id`/时间窗做一次增量补同步（脚本支持 `--resume`），或按 RB-1 回滚；`memories` 需先补搬迁再同步。

---

## 三项检查结论

### 1. 计数巡检 —— ❌ 异常

`migrate_mongo_to_panweidb.py --verify`（mongo: 27018 转发 → mogo_dev；panweidb: 127.0.0.1:5432 → **mogo_dev**）：

- 95 个集合：**69 相等** ✅ / **18 个 panweidb > mongo**（切流后新增写入，预期）/ **8 个 panweidb < mongo**（见置顶告警）
- 18 个增量集合（合计 +340 行，属预期，不逐一展开）：admin_sessions +28、system_audit_logs +83、position_role_audit_logs +49、mesc_ontology_perm_audit +53、gate_events +70、admin_refresh_tokens +17、end_users +8、end_user_org_relations +8、agent_kernel_bindings +6、runtime_profile_audit +6、chat_sessions +2、audit_logs / admin_model_instances / enterprise_session_approval_grants / enterprise_tool_approvals / mesc_ontology_class_detail / mesc_ontology_grant / user_field_defs 各 +1

### 2. 建表巡检 —— ✅ 通过

`generate_ddl.py --schema mogo_dev --check`：**"✅ 全部表已就位"**（实际 134 张表 ≥ 期望 106 张，多出的为切流后服务/同步建表）。

### 3. 服务健康检查 —— ✅ 通过

| 服务 | 结果 |
|---|---|
| admin-api (8100) | `backend=panweidb`，`reachable=true`，target `panweidb://boncuser@panweidb:5432/mogo_dev` |
| chat-api (8000) | `backend=panweidb`，`reachable=true`，dsh_host healthy |
| document-api (8200) | `backend=panweidb`，`reachable=true` |

### 4. PgCompatUnsupported 日志抽样 —— ✅ 无命中

近 24h（admin-api / chat-api / document-api）`PgCompatUnsupported` **0 条**，R2 补完清单无新增。

---

## 执行环境备注（对任务预设的修正，后续巡检沿用）

1. **DSN 数据库名**：任务背景给的 `dbname=bonc` 下**不存在** schema `mogo_dev`（会导致 95 个集合全部误报 -1）；实测数据在数据库 **`mogo_dev`**（.env `PANWEIDB_DB=mogo_dev`，三服务 health target 一致）。本次已按 `dbname=mogo_dev` 执行，首次按 bonc 跑的结果作废。
2. **mongo 转发容器**：缺失且 Docker Hub 不可达（`alpine:3.20` Bad Gateway）；改用本地 `python:3.13-slim-bookworm` 基底构建等价镜像（fwd.py 纯 stdlib），已起 `mogo-mongo-fwd`（27018 → mogo-mongo-1:27017）。注意 compose v2 容器名是 `mogo-mongo-1`，任务描述里的 `mogo-mongo` DNS 解析失败。
3. **document-parser 实际服务名为 `document-api`**，健康路径为 `/api/health`（`/health` 返回 404）。
4. 宿主机依赖 pymongo 4.19.0 / psycopg 3.3.6 原本缺失，本次已安装。

---

## 总体结论：**需人工介入**

- 服务层与建表层健康、无未覆盖能力报错，切流本身运行正常；
- 但 8 个集合存在 mongo 独有数据（合计 6,956 行，含从未搬迁的 `memories` 264 行），**RB-1 回滚条件已触发**。建议人工决策：补同步增量 vs 回滚；在决策前不建议继续放量观察。
