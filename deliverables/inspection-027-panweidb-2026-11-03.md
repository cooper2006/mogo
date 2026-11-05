# mogo 027 · MongoDB → PanWeiDB 迁移 · 切流后每日巡检报告

- **日期**：2026-11-03（周二）21:50 GMT+8
- **巡检性质**：只读巡检，**未执行任何切流 / 重启 / 写库操作**
- **连接信息（脱敏）**：PanWeiDB `host=172.17.5.145 port=17700 user=boncuser dbname=mogo schema=public`（口令已隐去）；Mongo 经转发 `mongodb://127.0.0.1:27018` → `mogo_dev`

---

## ⚠️ 置顶高亮（关键状态，请优先阅读）

- **当前活动数据后端 = `mongo`**，依据两条独立证据：
  1. 磁盘 `.env`：`MOGO_DATA_BACKEND=mongo`（第 36 行）
  2. 三服务 `/health`：`admin-api` / `chat-api` / `document-api` 均回报 `backend=mongo` 且 `reachable=true`
- 这与任务背景"已切到 PanWeiDB、mongo 只读"**相矛盾**——实测系统**已回滚到 mongo**。按判定规则"按当前 `.env` 实际值解读，不要误报"，健康检查判为**通过**，计数差异**不按"活动后端丢数据"处理**。
- 严格的 **RB-1（回滚到 mongo）** 在当前已回滚状态下**不适用**（系统已在 mongo，无需再回滚）。但是否"有意回滚"还是"误操作"需**人工确认**。

---

## 一、三项检查结论

| 检查项 | 结论 | 关键数字 |
|---|---|---|
| 计数巡检（mongo `mogo_dev` vs panweidb `public`） | ⚠️ 异常 | 152 集合：94 相等 / 58 不一致 |
| 建表巡检（`generate_ddl --check`） | ⚠️ 异常 | `public` 缺 2 张表 |
| 三服务健康检查 | ✅ 通过 | 3/3 `backend=mongo` 且 `reachable=true` |
| `PgCompatUnsupported` 日志（近 24h） | ✅ 无命中 | 0 条 |

---

## 二、计数巡检异常明细

汇总：相等 **94** / `panweidb < mongo` **44** / `panweidb > mongo` **12** / 表缺失(`-1`) **2**。
> 解读前提：活动后端为 `mongo`，`panweidb` 为冻结快照。`<mongo` 方向主要反映**回滚后 mongo 增量 + panweidb 静态快照**，非活动后端数据丢失；`>mongo` 方向为**切流期间写入 panweidb 的增量**（详见第五部分研判）。

### 2.1 表缺失（`-1`，巡检时 `to_regclass` 复核：均 MISSING）— 2 项（均已补建表结构）
- `dsh_plugin_installations`：mongo=1，panweidb=缺失 → **已补建表结构（22:13），行数据未回填**
- `admin_model_groups`：mongo=0，panweidb=缺失（与建表巡检重叠）→ **已补建（22:07）**
> 注：`topic_admission_policies` 同属建表巡检缺口，亦已于 22:07 补建（见 2.3 / 处置记录）；三张缺口表现在全部 EXISTS。

### 2.2 `panweidb < mongo`（44 项，格式：集合 mongo/panweidb，按差距降序）
memories 347/0、knowledge_document_chunks 255/0、system_audit_logs 194/9、position_role_audit_logs 279/134、token_usage_logs 284/154、business_entity_index 12/0、end_user_org_relations 16/4、document_jobs 11/0、projects 10/0、admin_refresh_tokens 107/98、admin_model_instances 11/3、enterprise_action_receipts 89/82、egress_allowlist 7/1、knowledge_documents 5/0、audit_logs 5/1、enterprise_tool_approvals 5/1、presence_heartbeats 5/1、session_presence_state 5/1、admin_recovery_tokens 3/0、capability_assets 3/0、end_user_sessions 3/0、end_users 7/4、external_search_configs 3/0、gate_events 98/95、runtime_profile_versions 9/6、user_token_allocation_logs 5/2、bw_probe2 2/0、bw_probe3 2/0、bw_probe_dbg 2/0、bw_probe_dbg2 2/0、dag_definitions 2/0、enterprise_session_approval_grants 2/0、mesc_ontology_grant 2/0、mesc_ontology_perm_audit 11/9、user_quota_policies 3/1、admin_account_groups 3/2、admin_accounts 3/2、org_quota_policies 2/1、portal_listings 1/0、position_role_migrations 2/1、session_snapshots 1/0、tenants 2/1、user_field_defs 1/0、user_skills 1/0

### 2.3 `panweidb > mongo`（12 项，切流期间增量，格式：集合 mongo/panweidb(+超出)，按超出降序）
kernel_event_inbox 21550/47843(+26293)、kernel_event_projections 20496/46013(+25517)、chat_messages 55/134(+79)、enterprise_tool_audit 196/250(+54)、chat_sessions 7/33(+26)、agent_kernel_bindings 33/58(+25)、org_units 4/21(+17)、skills 1/6(+5)、external_tools 0/5(+5)、skill_packages 2/6(+4)、admin_sessions 164/167(+3)、skill_quality_metrics 3/4(+1)

---

## 三、建表巡检异常明细

- `schema=public`：已有 **183** 张表，静态扫描期望 **124** 张，**缺失 2 张**：
  - `admin_model_groups`（与计数巡检缺失重叠）
  - `topic_admission_policies`（mongo 侧若无此集合，则属纯建表缺口）
- 判定：非"✅ 全部表已就位" → **异常**，列入 R1 建表补完清单。

---

## 四、`PgCompatUnsupported` 命中清单（近 24h）

- 命中 **0** 条。无新增未覆盖能力失败，R2 补完清单本日无变化。

---

## 五、总体结论：**需人工介入**

- 活动后端 = `mongo`，三服务健康，PanWeiDB 可读；当前**无紧急回滚必要**（已在 mongo）。
- 但存在两类需人研判事项：
  1. **计数差异**：`panweidb` 不是 `mongo` 的实时镜像。若后续决定**正式切回 panweidb**，须先重新全量/增量同步（尤其 `memories`、`knowledge_document_chunks` 等 panweidb=0 的大集合），否则切回会丢数据。
  2. **建表缺口**：`admin_model_groups`、`topic_admission_policies` 在 `public` 缺失，需补建（R1）。
- 另有 `panweidb > mongo` 的 12 个集合含"**仅存于 panweidb、未回流 mongo**"的数据（`kernel_event_inbox`/`chat_messages`/`chat_sessions` 等）。若最终定案采用 `mongo`，这些数据在 mongo 侧缺失，需人工确认处置（是否回流或舍弃）。

---

## 附：执行备注（非结论）

- PanWeiDB 实测用原生 `psycopg` 可连（`172.17.5.145:17700`，`dbname=mogo`，`schema=public`），与 `.env` 注释"openGauss MD5 不兼容、仅 gsql 可连"的担忧不符——本次连接正常。
- Mongo 转发容器 `mogo-mongo-fwd` 已启动（上游 `mogo_backend` 的 `mongo:27017` → 宿主 `27018`），Mongo 可达（`mogo_dev` 共 152 集合）。上游主机名用 `mongo`（非任务文案的 `mongo-mongo`），按 `docker network inspect` 实测别名校正。
- 任务文案中的 `document-parser` 实际对应 compose 服务 `document-api`（端口 8200，health 路径为 `/api/health` 或 `/api/v1/health`，裸 `/health` 为 404），已按实际校正。
- 本报告初版为只读巡检产出；口令在文中已脱敏，未执行任何切流 / 重启。后续按用户指令于 2026-11-03 22:07 受控补建 2 张缺失表（见下方处置记录），未写行数据。

---

## 处置记录（2026-11-03 22:07）

- 按用户指令补建**建表巡检缺口的 2 张表**到 PanWeiDB `public`，复用 `scripts/pg/generate_ddl.py` 的 `table_ddl`/`index_ddl` 模板（含 `tenant_id` btree 索引），`CREATE TABLE IF NOT EXISTS` 幂等执行：
  - `admin_model_groups`（表 + `admin_model_groups_tenant_idx`）→ 已 EXISTS
  - `topic_admission_policies`（表 + `topic_admission_policies_tenant_idx`）→ 已 EXISTS
- 重跑建表巡检：`schema=public` 已有 **185** 张表，期望 124 张 → **✅ 全部表已就位**（原 2 缺失已闭合）。
- 计数巡检缺口表 `dsh_plugin_installations`（mongo=1，未纳入静态扫描清单）**已于 22:13 一并补建**（见下方处置记录）；三张缺口表现全部 EXISTS，仅该行数据尚未回填 mongo→panweidb。

## 处置记录（2026-11-03 22:13）

- 按用户指令**一并补建**计数巡检发现的第 3 张缺口表 `dsh_plugin_installations` 到 PanWeiDB `public`：
  - 该表未纳入 `generate_ddl.py` 的静态扫描期望清单（故建表巡检不报），但统一采用项目固定四列 schema（`id TEXT PK` / `tenant_id TEXT` / `doc JSONB NOT NULL` / `created_at` `updated_at TIMESTAMPTZ DEFAULT now()`）+ `tenant_id` btree 索引，与现有 183 张表结构一致。
  - `dsh_plugin_installations`（表 + `dsh_plugin_installations_tenant_idx`）→ 已 EXISTS，`to_regclass` 复核通过。
  - 注意：`generate_ddl.py` 的统一 schema 将所有业务字段存入 `doc` JSONB，因此本表**不按 mongo 文档字段展开成列**，符合项目"新增业务字段不需改 DDL"的约定。
- 至此三张缺口表（建表巡检 2 张 + 计数巡检 1 张）全部补建完成；`public` 表总数由 183 → 185，增量含本次 1 张。
- **数据回填提醒**：三次补建均只建表结构，**未回填行数据**。`dsh_plugin_installations` 在 mongo 侧有 1 条文档（`tenant_id='default'`、`engine='dsh'`、`name='dsh-ops'` 等），尚未同步进 PanWeiDB。若后续正式切回 PanWeiDB，需将该文档一并迁移，否则此条数据会丢失。
- 本次仍为受控写表操作（仅建表 + 索引，未写入行数据、未切流 / 重启），符合用户明确指令；口令脱敏。
