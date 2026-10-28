# 027「MongoDB → PanWeiDB 迁移」切流后每日巡检报告

- **日期**：2026-10-27（周二）
- **巡检性质**：只读巡检，未做任何切流、重启、写库操作
- **执行说明**：本报告由 09:33 首轮巡检生成；09:36 按同一自动化任务复核执行一轮，全部结果与首轮完全一致（下文日志行数为两轮合计口径中的后者）。复核轮 mongo 各集合计数与 10-26 逐集合相同（零实时写入），panweidb 缺口集合计数与首轮相同（缺口维持 -58，回补进度两轮间无变化）。
- **.env 当前值**：MOGO_DATA_BACKEND=PanWeiDB（health 按 panweidb 解读）

---

## 🔴 置顶高亮：数据丢失告警（触发 RB-1 回滚条件，需人工决策）

计数巡检中 **9 个集合 panweidb < mongo，合计缺口 -58 行**：

| 集合 | mongo | panweidb | 缺口 | vs 10-26 |
|---|---:|---:|---:|---|
| position_role_audit_logs | 197 | 177 | -20 | 174→177，缩小 3 |
| admin_sessions | 95 | 84 | -11 | 83→84，缩小 1 |
| admin_refresh_tokens | 41 | 31 | -10 | 30→31，缩小 1 |
| business_entity_index | 12 | 6 | -6 | 持平 |
| system_audit_logs | 132 | 127 | -5 | 持平 |
| gate_events | 74 | 72 | -2 | 持平 |
| runtime_profile_audit | 24 | 22 | -2 | 持平 |
| dag_definitions | 2 | 1 | -1 | 持平 |
| runtime_profile_versions | 5 | 4 | -1 | 持平 |
| **合计** | | | **-58** | 10-26 为 -63 |

按判定规则，此为数据丢失类告警，触发 RB-1 回滚条件（.env 改回 MOGO_DATA_BACKEND=mongo 并 docker compose up -d）。本巡检不执行回滚，由人工决定。

**性质判断（与 10-26 一致，且今日出现缩小证据）**——缺口高度疑似**人工回补作业仍在进行中**，而非 PanWeiDB 运行时丢数据，佐证：

1. **mongo 侧零实时写入**：9 个缺口集合的 mongo 计数与 10-26 逐集合完全一致（41/95/197/12/132/74/24/2/5）；各集合最新文档时间戳全部 ≤ 2026-10-23 03:48 UTC（system_audit_logs 因 _id 为字符串无时间戳字段，但计数两日不变），均在切流前——"mongo 多出来的行"仍是旧文档回写痕迹，无新增。
2. **panweidb 侧正在追赶**：admin_sessions 83→84、admin_refresh_tokens 30→31、position_role_audit_logs 174→177，24h 内合计补入 5 行，缺口 -63 → -58；其余 6 个集合 panweidb 计数两日不变。
3. 综合推断：回补/同步进程仍在跑但进度缓慢且不均衡（近 24h 仅闭合 5/63 行）。**需人工确认：该同步进程是否仍在运行？剩余 58 行是否会被补完？若已停止，需决定补数据还是回滚。**

---

## 三项检查结论

### 1. 计数巡检（migrate_mongo_to_panweidb.py --verify）—— ❌ 异常

本次覆盖 **148 个集合**（与 10-26 相同）：**134 相等 / 5 增（预期）/ 9 缺（置顶告警）**。

- **数据丢失（置顶项）**：9 个集合见上表，合计 **-58 行**（性质见上文判断，缺口较昨日缩小 5 行）。
- **切流后新增写入（预期，只报增量）**：5 个集合 panweidb > mongo，合计 **+60 行**：

  | 集合 | mongo → panweidb | 增量 | vs 10-26 |
  |---|---:|---:|---|
  | mesc_ontology_perm_audit | 5 → 58 | +53 | 持平 |
  | mesc_ontology_grant | 2 → 6 | +4 | 持平 |
  | skill_quality_metrics | 3 → 4 | +1 | 持平 |
  | mesc_ontology_class_detail | 1 → 2 | +1 | 持平 |
  | trust_rating_scan_state | 0 → 1 | +1 | 今日新增 |
  | **合计** | | **+60** | 10-26 为 +59 |

  近 24h mesc_* 三集合增量与昨日完全相同（无新写入），仅 trust_rating_scan_state 新增 1 行。

### 2. 建表巡检（generate_ddl.py --check）—— ✅ 通过

「✅ 全部表已就位」：schema=mogo_dev 已有 **149 张表**，期望 122 张，**无缺失**（与 10-26 一致）。

### 3. 三服务健康检查—— ✅ 通过

| 服务 | status | backend | reachable |
|---|---|---|---|
| admin-api | ok | panweidb | true |
| chat-api | ok | panweidb | true |
| document-api（document-parser） | ok | panweidb | true |

与 .env 当前 MOGO_DATA_BACKEND=PanWeiDB 一致，无异常。三容器当前 Up 16h (healthy)。

### 4. PgCompatUnsupported 日志抽样—— ✅ 0 命中

近 24h 三服务日志共 **14,985 行**（09:36 复核轮统计；首轮 09:33 为 14,501 行，均已核实非空、覆盖至巡检时刻），PgCompatUnsupported 命中 **0 条**（R2 补完清单无新增）。附带观察：

- AdminShutdown / dispatch_failed / psycopg 类错误均为 **0**（连续两日为零）。
- 日志中有 12 条 `level: error`，全部为服务启动时 opentelemetry instrumentation 模块缺失（`ModuleNotFoundError: No module named 'opentelemetry.instrumentation'`，伴生 "app runs without tracing"），发生在 10-26 UTC 06:20 / 09:53 两个启动时刻，属无害启动噪音，不影响数据链路。三服务于 10-26 下午有重启痕迹，当前均 healthy。

---

## 总体结论：需人工介入

1. **9 个集合缺口 -58 行**（如 admin_sessions mongo 95 > panweidb 84）：按规则触发 RB-1。佐证表明系回补作业中间态（mongo 零实时写入、panweidb 侧 24h 内补入 5 行、缺口 63→58 缩小中）。09:36 复核轮缺口与 09:33 首轮完全一致（-58，逐集合计数无变化），当日回补节奏明显放缓。**需人工确认同步进程是否仍在运行；若已停止，请决定将剩余 58 行补入 panweidb 或执行回滚。**
2. **运行面持续平稳**：建表 149/122 无缺失、三服务 health 全 panweidb/reachable=true、PgCompatUnsupported 连续 6 日 0 命中、瞬时故障连续两日 0 次。
3. 切流后新增写入 +60 行符合预期（mongo 已冻结，服务只写 panweidb）。
