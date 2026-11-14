# 027「MongoDB → PanWeiDB 迁移」切流后每日巡检报告 — 2026-11-03

> 巡检时间：2026-11-03 09:11–09:20 CST ｜ 模式：只读巡检，未做任何切流、重启、写库操作
> 执行环境：宿主机 python3（pymongo 4.19.0 / psycopg 3.3.6）；mongo 经 mogo-mongo-fwd 转发（127.0.0.1:27018 → mogo-mongo-1:27017）

## 一、三项检查结论

| 检查项 | 结论 | 说明 |
|---|---|---|
| 计数巡检（mongo vs PanWeiDB） | ❌ **失败** | PanWeiDB 双通道失联，无法比对（详见三-1） |
| 建表巡检（generate_ddl --check） | ❌ **失败** | 同上，两条 DSN 均 Connection refused（详见三-1） |
| 三服务健康检查 | ✅ **通过** | admin-api / chat-api / document-api 均 `backend=mongo, status=ok`（详见三-3） |
| PgCompatUnsupported 日志抽样 | ✅ **0 命中** | 24h 日志 385 行（非空，已核实），无未覆盖能力显式失败 |

## 二、环境事实（今日实测）

- **.env 实际值**：`MOGO_DATA_BACKEND=mongo`、`MOGO_USE_EXTERNAL_DB=0`、`PANWEIDB_PASSWORD` 存在（未缺失，不构成阻塞项）。PanWeiDB 参数仍指向外部集群 172.17.5.145:17700（db=mogo / schema=public）。
- **RB-1 回滚维持生效**：11-02 人工将 .env 改回 mongo 后至今未变；三服务 health 的 `backend=mongo` 按判定规则属**正常**，非误报。
- **compose 栈今日 09:05 左右再次重建**：admin-api / chat-api / document-api / gateway / user-web / admin-web / dsh-runtime-host / document-worker 8 个服务于巡检前 6 分钟重启（Up 6 minutes），mongo / redis / weaviate 已连续运行 13 小时。**重启原因未知，建议人工确认是否本人在场操作。**
- **PanWeiDB 双通道均失联**（与 11-02 相同）：
  - 本地：127.0.0.1:5432 无人监听（compose profile panweidb 的 panweidb 容器未起）
  - 外部：172.17.5.145:17700 Connection refused（nc 与 psycopg 直连均确认）

## 三、异常明细

### 1. 计数/建表巡检失败（如实记录，未伪造成功）

本地通道（任务字面 DSN，dbname=bonc）与外部通道（.env 实际值，dbname=mogo/schema=public）各执行一次，均失败：

```
migrate_mongo_to_panweidb.py --verify:
  psycopg.OperationalError: connection to server at "127.0.0.1", port 5432 failed: Connection refused
  psycopg.OperationalError: connection to server at "172.17.5.145", port 17700 failed: Connection refused
generate_ddl.py --check:
  同上，两条 DSN 均在 psycopg.connect 处 Connection refused
```

mongo 侧可读（转发正常），PanWeiDB 侧不可读，故**逐集合计数比对今日无法进行**：既未发现 panweidb < mongo 的数据丢失告警，也不能证明无缺口——请人工知悉此局限。既往 17 个缺口集合的 mongo 侧计数已留存（见四），待 PanWeiDB 恢复后可继续比对。

### 2. 无 panweidb < mongo 告警可判定

因 PanWeiDB 不可达，判定规则中的"数据丢失告警 → RB-1"**今日无法触发也无法排除**。

### 3. 健康检查明细（全部通过）

| 服务 | 端点 | 结果 |
|---|---|---|
| admin-api | 8100 /health | `{"status":"ok","backend":"mongo"}` |
| chat-api | 8000 /health | `{"status":"ok","backend":"mongo"}`（dsh_host healthy） |
| document-api | 8200 /api/health | `{"status":"ok","backend":"mongo"}` |

注：document-api 的 `/health` 为 404（已知问题，须用 `/api/health`；compose 服务名为 document-api 而非 document-parser）。

## 四、附带观测：mongo 权威库快照（只读）

- 152 集合 / 34,933 篇，较 11-02（34,838）+95 篇，**回滚后 mongo 持续接收新写入，权威库运转正常**。
- 按 ObjectId 时间戳口径近 24h 新增 0 篇，但总数仍在增长——已定位原因：**19 个集合使用业务自定义 _id**（projects、tenants、skills、system_audit_logs、position_role_audit_logs、knowledge_documents 等），其新写入不体现在 _id 时间戳上。抽样增量：position_role_audit_logs 233→249（+16）、admin_sessions 157→158、system_audit_logs/kernel_event_inbox 等亦有增长。
- 既往 17 个缺口集合当前 mongo 计数（供 PanWeiDB 恢复后比对）：kernel_event_inbox 16805、kernel_event_projections 16104、memories 340、token_usage_logs 143、enterprise_tool_audit 137、enterprise_action_receipts 60、chat_messages 33、skill_quality_metrics 3、admin_sessions 158、position_role_audit_logs 249、admin_refresh_tokens 101、business_entity_index 12、system_audit_logs 180、gate_events 80、runtime_profile_audit 28、dag_definitions 2、runtime_profile_versions 6。

## 五、PgCompatUnsupported 命中清单

**无命中（0 条）**。24h 日志共 385 行（已核实非空）；除 opentelemetry 启动告警外无其他 error。

## 六、总体结论：**需人工介入**

1. 【回滚本身】✅ 维持生效：backend=mongo、三服务健康、mongo 权威库正常写入，无需动作。
2. 【需决策一】PanWeiDB 双通道连续两日（11-02、11-03）失联：本地 panweidb 容器未起、外部集群 17700 refused。迁移观察期事实上已无法观察——请人工确认是彻底放弃 PanWeiDB（则本巡检任务可退订或改口径），还是修复通道后继续比对（届时以今日第四节的 mongo 计数为基准）。
3. 【需留意】今日 09:05 compose 栈 8 个服务再次重启，原因未知，请人工确认。
4. 计数与建表两项因通道失联失败，非脚本或环境配置问题；宿主机依赖、mongo 转发链均正常。
