# 027「MongoDB → PanWeiDB 迁移」切流后每日巡检报告 — 2026-10-28

- **执行时间**：2026-10-28 09:33（自动化触发）– 09:37 完成
- **巡检性质**：只读巡检，未执行任何切流、重启、写库操作
- **.env 当前值**：MOGO_DATA_BACKEND=panweidb；PANWEIDB_HOST=172.17.5.145、PORT=17700、DB=mogo、SCHEMA=public（昨晚 22:50 改版，详见下文）

---

## 🔴 置顶高亮 1：巡检基础设施在本次巡检期间被整体销毁（环境重大变更）

**整个 mogo compose 栈（mongo / panweidb / redis / weaviate / admin-api / chat-api / document-api / document-worker / dsh-runtime-host / 各 web / gateway / bootstrap）于今日 09:34:07–09:35:04 被销毁**（docker events 实测，恰逢 09:30 有并发会话在跑 playwright bundle 容器，疑为并发运维动作）。

- .env 已于**昨晚 22:50** 被改写：PanWeiDB 从栈内容器改为**外部集群**（VPN 172.17.5.145:17700，db=mogo，schema=public，口令 1qaz!QAZ），MOGO_USE_EXTERNAL_DB=0（redis 仍栈内），旧配置备份为 `.env.bak-external-panweidb-20261027-212133`。容器销毁前最后一次创建在 24h 以前（24h 内无 create/start 事件），即**运行中的服务仍连着旧的栈内 panweidb**，.env 变更尚未被任何容器加载。
- 直接后果：任务指定的巡检路径全部失效——宿主机 127.0.0.1:5432 无人监听（连接被拒）；mongo 转发容器 `mogo-mongo-fwd` 虽在跑，但上游 `mogo-mongo-1` 已不存在（日志持续 `upstream connect failed: [Errno -2] Name or service not known`）。
- **数据卷仍在盘上**（mogo_mongo-data、mogo_panweidb-storage 等 10 个命名卷完好），无数据删除证据；但不起容器即无法查询。
- 本巡检不重启任何容器（任务约束），重建/切栈由人工决定。

## 🔴 置顶高亮 2：9 个集合数据缺口未闭合（以 10-27 mongo 计数为基准，外部集群仍少 53 行）

正式计数巡检因 mongo 不可达而失败（见下）。以昨日报告记载的 mogo mongo 计数（10-27，此后 mongo 无写入且已销毁）为基准，与外部集群现状比对：

| 集合 | mongo（10-27 最后已知） | 外部集群 panweidb（10-28 09:3x） | 缺口 | vs 10-27 本地库 |
|---|---:|---:|---:|---|
| position_role_audit_logs | 197 | 180 | -17 | 本地 177→外部 180，回补 +3 |
| admin_sessions | 95 | 85 | -10 | 本地 84→外部 85，回补 +1 |
| admin_refresh_tokens | 41 | 32 | -9 | 本地 31→外部 32，回补 +1 |
| business_entity_index | 12 | 6 | -6 | 持平 |
| system_audit_logs | 132 | 127 | -5 | 持平 |
| gate_events | 74 | 72 | -2 | 持平 |
| runtime_profile_audit | 24 | 22 | -2 | 持平 |
| dag_definitions | 2 | 1 | -1 | 持平 |
| runtime_profile_versions | 5 | 4 | -1 | 持平 |
| **合计** | | | **-53** | 10-27 为 -58，续缩小 5 行 |

按判定规则性质，panweidb < mongo 仍触发 RB-1 关注线（昨日 -58 → 今日 -53）。**佐证表明回补作业已转向外部集群且今晨仍在活跃**：admin_refresh_tokens / admin_sessions / position_role_audit_logs 三表的 `updated_at` 最大值分别为**今日 09:02:27 / 09:05:58 / 09:16:19（+08:00）**——就在本巡检触发前半小时内，有进程在往外部集群写这三张回补目标表。mongo 已销毁，无法执行正式比对，上述为人工基准比对，供决策参考。

---

## 三项检查结论

### 1. 计数巡检（migrate_mongo_to_panweidb.py --verify）—— ❌ 失败（无法执行）

失败命令与错误输出（原样）：

```
$ python3 scripts/pg/migrate_mongo_to_panweidb.py --mongo-uri mongodb://127.0.0.1:27018 \
    --mongo-db mogo_dev --dsn 'host=127.0.0.1 port=5432 user=boncuser password=*** dbname=mogo_dev' \
    --schema mogo_dev --verify
pymongo.errors.ServerSelectionTimeoutError: 127.0.0.1:27018: connection closed
(configured timeouts: socketTimeoutMS: 20000.0ms, connectTimeoutMS: 20000.0ms), Timeout: 30s
```

原因：mongo 上游容器已销毁，转发器无上游。RB-1 正式判定今日无法执行，以上表人工基准比对代替。

### 2. 建表巡检（generate_ddl.py --check）—— ❌ 指定目标失败 / ✅ 适配外部集群通过

指定目标（127.0.0.1:5432）失败，错误输出（原样）：

```
psycopg.OperationalError: connection failed: connection to server at "127.0.0.1",
port 5432 failed: Connection refused
Is the server running on that host and accepting TCP/IP connections?
```

适配执行（只读，直连外部集群，schema=public）：

```
$ python3 scripts/pg/generate_ddl.py --schema public --check \
    --dsn 'host=172.17.5.145 port=17700 user=boncuser password=*** dbname=mogo'
schema=public 已有 179 张表；期望 122 张
✅ 全部表已就位
```

### 3. 三服务健康检查—— ❌ 失败（容器不存在）

三个服务容器均已不存在，`docker compose exec` 全部返回（原样）：

```
service "admin-api" is not running
service "chat-api" is not running
service "document-api" is not running
```

无法验证 backend=panweidb / reachable。另注：任务命令中的 `document-parser` 并非 compose 服务名（实际为 `document-api`），即便栈正常也会报 `no such service: document-parser`。

### 4. PgCompatUnsupported 日志抽样—— ❌ 无法采样（无容器、0 行日志）

`docker compose logs --since 24h admin-api chat-api document-api` 输出 0 行（容器已销毁，日志随容器消失）。**0 行 ≠ 0 命中**，今日无法评估 R2 补完清单。附带观察：AdminShutdown / dispatch_failed 同样无法采样。

---

## 异常明细与汇总数字（只列异常项）

- **计数**：正式巡检失败。人工基准比对：9 集合缺 **-53 行**（见置顶 2）；5 个切流后增量集合中，mesc_ontology_grant 6→11、mesc_ontology_class_detail 2→8、skill_quality_metrics 4、trust_rating_scan_state 1；**mesc_ontology_perm_audit 本地昨日 58 → 外部今日 18（不升反降）**，外部集群并非本地库的完整快照，数据口径需人工确认。
- **外部集群完整度**：public 共 179 表，**87 张有数据、90 张为空**。昔日大表在外部集群为 0 行：kernel_event_inbox（本地 16725→外部 **0**）、kernel_event_projections（**0**）、conversations（**0**）；memories 336 / chat_messages 25 / token_usage_logs 143，且三者 `updated_at` 最大值冻结在 **10-25 11:47**（快照口径）。**若外部集群要作为新生产目标，全量数据加载明显未完成。**
- **建表**：外部集群 179 表 ≥ 期望 122，无缺失（通过）；但"表在"≠"数据在"，见上条。
- **健康 / 日志**：三服务不可达、24h 日志 0 行，均因栈销毁。

---

## 总体结论：需人工介入

1. **环境变更需确认**：昨晚 22:50 .env 改指外部 PanWeiDB，今晨 09:34 栈被整体销毁（并发会话活跃时段）。请确认：销毁是有意的切栈动作还是误操作？栈是否将按新 .env（外部 PanWeiDB + 栈内 redis）重建？重建前本自动化巡检无法按任务背景路径执行。
2. **外部集群数据不完整**：90 张空表、kernel_event_inbox 等大表 0 行、memories 等冻结在 10-25 快照。若以其为新目标，需先完成全量搬迁并复核；mesc_ontology_perm_audit 58→18 的口径差异需解释。
3. **数据缺口 -53 行未闭合**：回补已转至外部集群且今晨 09:02–09:16 仍在写（三张回补目标表 updated_at 为证），节奏约 +5 行/日前日持平。请确认同步进程是否仍在跑、剩余 53 行是否补完。
4. **回滚路径已变化**：RB-1 回滚（.env 改回 mongo + compose up）现在意味着**从零重建整个栈**（容器已全部销毁），成本高于此前；且 mongo / panweidb 数据卷完好，正式计数巡检随时可在人工决定重启 mongo 后恢复。
5. **巡检适配建议**：若外部集群成为既定目标，后续本巡检的 DSN 应改为 `host=172.17.5.1.145 port=17700 dbname=mogo schema=public`（或在宿主建 5432→17700 转发），mongo 侧需先恢复容器；本报告已将今日起的环境事实记入自动化记忆。
