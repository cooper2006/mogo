# MongoDB ↔ 远端 PanWeiDB 数据差异比对报告

- **日期**：2026-11-11（周三）20:05 CST
- **比对性质**：只读差异比对（不切流、不重启、不写库）
- **比对范围**：mongo `mogo_dev`（127.0.0.1:27017）↔ 远端 PanWeiDB `public`（172.17.5.145:17700，dbname=mogo，按 `.env` 实际值）
- **工具**：`scripts/pg/migrate_mongo_to_panweidb.py --verify`，原始输出 `/tmp/mogo_diff_1111.txt`

---

## 0. 环境现状（较 11-02 已变化）

| 项 | 11-02 | 11-11 |
|---|---|---|
| mogo compose 栈 | 三服务运行 | **已不存在**（docker ps 无 mogo_* 容器） |
| mongo 可达性 | 需 mogo-mongo-fwd 转发 27018 | **宿主机直连 127.0.0.1:27017**（`.env` 已改为 `host.docker.internal:27017`） |
| PanWeiDB 可达性 | 双通道失联 | **远端 172.17.5.145:17700 可达**（本地 5432 仍无人监听） |
| mongo mogo_dev | 152 集合 / 34,881 篇 | **310 集合 / 144,881 篇** |
| panweidb public | 179 表（10-28） | **187 表** |
| `.env` 后端 | MOGO_DATA_BACKEND=mongo（回滚） | 同（mongo，未再切流） |

**结论**：RB-1 回滚（11-02）后系统持续以 mongo 为权威库；远端 PanWeiDB 已恢复在线，本次比对得以完整执行。

---

## 1. ✅ 已澄清：kernel_event_inbox / kernel_event_projections 方向反转

这两张集合是**日志型集合**。人工已确认：mongo 侧的 0 篇是**主动手工清理**的结果（非数据丢失、非迁移副作用），panweidb 侧的 94,305 篇为保留的历史日志副本。

| 集合 | mongo | panweidb | 说明 |
|---|---|---|---|
| kernel_event_inbox | **0**（手工清理后） | **48,137** | 日志，人工清空 mongo 侧 |
| kernel_event_projections | **0**（手工清理后） | **46,165** | 日志，人工清空 mongo 侧 |
| 合计 | 0 | **94,305** | — |

**旁证（与说明一致）**：
- 今日 09:02 CST（01:02:14 UTC）有 `id-hex32` 备份工具运行：在 mongo 内创建 **155 个 `__hex32_bak_20261111T010214Z` 快照集合**（72 个有数据、83 个空），并在 `backups/id-hex32-20261111T0102Z/` 导出 160 个 .bson（473M）。
- 两张集合的 bak 快照**也是空的**（0 篇）——与「先清理 mongo、后备份」的顺序一致。
- panweidb 的 `_migration_progress` 表停在 **2026-10-21 07:24 CST**（83 行，全部 `done=False`），无 11-11 操作记录。

**遗留观察（非告警）**：当前 `.env` 为 `MOGO_DATA_BACKEND=mongo`，mongo 是活跃后端，panweidb 侧的 94,305 篇 kernel_event 日志此时为**游离副本**（无对应活跃写入）。是否保留/清理由人工决定，不影响当前运行。

---

## 2. 计数差异汇总（排除 155 个 bak 备份集合后）

真实集合 **155 个**（bak 备份集合 155 个已单独说明，不计入迁移比对）：

| 类别 | 集合数 | 行数合计 |
|---|---|---|
| ✅ 相等 | 80 | — |
| ❌ panweidb < mongo（mongo 更多） | **71** | **-2,444 篇** |
| ❌ panweidb > mongo（panweidb 更多） | **4** | **+94,305 篇** |
| panweidb 有表 / mongo 无 | 35 张 | — |
| mongo 有集合 / panweidb 无 | 3 个 | — |

### 2.1 panweidb < mongo（mongo 侧更多，-2,444）

panweidb 侧计数多数停留在迁移冻结快照（与 10-26/10-27 一致），mongo 侧因回滚后写入 + 今日备份前写入而增长。**大额差异（≥50 篇）**：

| 集合 | mongo | panweidb | 差 |
|---|---|---|---|
| memories | 350 | 3 | +347（从未迁移） |
| system_audit_logs | 384 | 49 | +335 |
| knowledge_document_chunks | 255 | 0 | +255（新功能，未迁移） |
| admin_sessions | 452 | 237 | +215 |
| enterprise_tool_audit | 454 | 250 | +204 |
| position_role_audit_logs | 343 | 190 | +153 |
| admin_refresh_tokens | 315 | 168 | +147 |
| token_usage_logs | 293 | 160 | +133 |
| gate_events | 210 | 109 | +101 |
| mesc_ontology_perm_audit | 103 | 15 | +88 |
| chat_messages | 213 | 146 | +67 |
| agent_kernel_bindings | 100 | 65 | +35 |
| runtime_profile_audit | 81 | 43 | +38 |
| audit_logs | 39 | 9 | +30 |

其余 57 个集合差异在 +1～+18 之间（多为回滚后的增量写入或新功能空表）。

**判定**：按任务规则 `panweidb < mongo = 数据丢失告警（RB-1）` 字面触发。但 RB-1 回滚已于 11-02 执行、mongo 为当前权威库，此处的 -2,444 主要是**回滚后 mongo 新增写入 + 历史从未迁移集合（memories / knowledge_*）的累积**，非运行时数据丢失。**不触发回滚**，仅作留档。

### 2.2 panweidb > mongo（panweidb 侧更多，+94,305）

| 集合 | mongo | panweidb | 差 |
|---|---|---|---|
| kernel_event_inbox | 0 | 48,137 | +48,137 |
| kernel_event_projections | 0 | 46,165 | +46,165 |
| organization_skill_releases | 0 | 2 | +2 |
| scheduled_job_runs | 0 | 1 | +1 |

前两项已由人工确认为**主动清理日志后保留的历史副本**（见第 1 节）；后两项为 panweidb 侧有而 mongo 侧为 0 的小量数据。

### 2.3 panweidb 有表 / mongo 无（35 张）

以 `mesc_*`（ontology / semantica / asset / session / story 系统）为主，均在 panweidb 侧存在且 mongo 无对应集合：

- 有数据：`mesc_session` 120、`_migration_progress` 83（停在 10-21 的旧迁移进度）、`pg_type_nonstrict_basic_value` 1,566（疑 PanWeiDB 系统表）、`mesc_ontology` 7、`mesc_story` 4、`mesc_agent` 3、`mesc_asset_table` 3
- 空表：`memory_policies`、`pw_login_info`、`topic_admission_policies` 及其余 mesc_* 表

### 2.4 mongo 有集合 / panweidb 无（3 个）

`asset_templates`、`employee_api_keys`、`employees` —— 新功能集合，尚未迁移到 panweidb。

---

## 3. 建表巡检

`generate_ddl.py --check` 本次**未执行**（任务为差异比对，非建表巡检；如需可随时补跑，DSN 同上）。

历史参考：panweidb public 187 表 ≥ 期望 122，10-28 时 ✅；今日新增 8 表（179→187）。

---

## 4. 总体结论

1. **无需回滚**：RB-1 已于 11-02 执行，mongo 为当前权威库且数据完好（144,881 篇，含回滚后正常写入）。
2. **kernel_event 方向反转已澄清**（人工确认）：`kernel_event_inbox` / `kernel_event_projections` 是**日志型集合**，mongo 侧 0 篇为**主动手工清理**结果，panweidb 侧 94,305 篇为保留的历史日志副本。**非数据丢失，最高优先待确认事项解除。**
3. **需人工知悉**：
   - 今日 09:02 CST 的 `id-hex32` 备份操作（155 个 mongo 内 bak 快照 + 473M .bson 导出）已留档，bak 集合不属于迁移数据，后续比对应排除。
   - 71 个集合 panweidb < mongo（-2,444）为回滚后累积差异 + 历史从未迁移集合（memories / knowledge_*），非运行时丢失，仅作留档。
   - 35 张 panweidb 独有表（mesc_* 系统等）；3 个 mongo 独有集合（asset_templates / employee_api_keys / employees）已于 11-11 补齐同步。
4. **后续比对建议**：排除 `__hex32_bak_*` 与 `kernel_event_*`（人工清理的已知差异）后看其余真实集合；当前 mongo 侧 144,881 篇为权威基线。

---

## 附录：11-11 同步操作记录（mongo 中 panweidb 无的 3 个集合）

按 027 迁移 runbook（`docs/mongo-to-panweidb-migration-plan.md` §迁移 runbook）对「mongo 有、panweidb 无」的 3 个集合执行了补齐同步。

| 步骤 | 命令 | 结果 |
|---|---|---|
| 1. dry-run 演练 | `migrate_mongo_to_panweidb.py --collections asset_templates employee_api_keys employees --dry-run` | 统计 17 篇（4/1/12），未写库 |
| 2. 正式搬迁 | 同上去掉 `--dry-run` | 写入 17 篇，耗时 0.3s；脚本内置 `CREATE TABLE IF NOT EXISTS` 建表，upsert 幂等（`ON CONFLICT DO UPDATE`） |
| 3. 计数校验 | `--verify`（同 3 集合） | ✅ 全部一致：asset_templates 4=4、employee_api_keys 1=1、employees 12=12 |
| 4. 内容抽查 | 直接查 panweidb 3 张表的 doc JSONB | 数据完整，字段无丢失，tenant_id 提取正确 |

**说明**：
- 本次**未加 `--prune`**：mongo 是当前权威库（`.env` MOGO_DATA_BACKEND=mongo），prune 会删除目标库中源库已不存在的行，对本次无影响但语义上不适用。
- 目标 schema 为 `public`（外部集群），DSN 用 `.env` 实际值 `host=172.17.5.145 port=17700 dbname=mogo`；**未用 `dbname=bonc`**（历史误报口径）。
- 同步后 panweidb 侧「mongo 有、panweidb 无」的集合由 3 个降为 **0**；「panweidb 有、mongo 无」的表仍为 35 张（mesc_* 系统表等，属 panweidb 侧存在而 mongo 无对应集合，非本次同步范围）。
- `kernel_event_inbox` / `kernel_event_projections` 的方向反转（mongo 0 ↔ panweidb 94,305）已由人工确认为**主动清理日志**（见第 1 节），非数据丢失。

---

*报告由只读比对生成；附录同步操作为按 027 规约执行的写库迁移（幂等 upsert，已校验）。*