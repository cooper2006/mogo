# 027「MongoDB → PanWeiDB 迁移」切流后每日巡检报告

- **日期**：2026-10-26（周一）
- **巡检性质**：只读巡检，未做任何切流、重启、写库操作
- **.env 当前值**：MOGO_DATA_BACKEND=PanWeiDB（health 按 panweidb 解读）

---

## 🔴 置顶高亮：数据丢失告警（触发 RB-1 回滚条件，需人工决策）

计数巡检中 **9 个集合 panweidb < mongo，合计缺口 -63 行**：

| 集合 | mongo | panweidb | 缺口 |
|---|---:|---:|---:|
| admin_refresh_tokens | 41 | 30 | -11 |
| admin_sessions | 95 | 83 | -12 |
| position_role_audit_logs | 197 | 174 | -23 |
| business_entity_index | 12 | 6 | -6 |
| system_audit_logs | 132 | 127 | -5 |
| gate_events | 74 | 72 | -2 |
| runtime_profile_audit | 24 | 22 | -2 |
| dag_definitions | 2 | 1 | -1 |
| runtime_profile_versions | 5 | 4 | -1 |
| **合计** | | | **-63** |

按判定规则，此为数据丢失类告警，触发 RB-1 回滚条件（.env 改回 MOGO_DATA_BACKEND=mongo 并 docker compose up -d）。本巡检不执行回滚，由人工决定。

**性质判断（重要，与前三日不同）**——本次缺口高度疑似**人工回补作业的中间态**，而非 PanWeiDB 运行时丢数据，佐证：

1. **mongo 侧无任何实时新写入**：上述 9 个缺口集合及已补齐集合的最新文档时间戳全部 ≤ 2026-10-22（切流前），近 24h ObjectId 写入均为 0——"mongo 增长"系旧文档（保留原始 _id/时间戳）被重新 upsert 的回补痕迹。
2. **panWeiDB 侧数据未动**：admin_sessions=83、system_audit_logs=127、gate_events=72 等与 10-25 巡检值完全一致（零增长），缺口感来自 mongo 一侧被回写。
3. **前 8 个大缺口已双向补齐**：如 kernel_event_inbox 14409/11022 → 16725/16725（-3387 → 0），memories 264/72 → 336/336（-192 → 0），连续三日的 -6,956 行大缺口**今日全部归零**。
4. 综合推断：10-25 09:17 之后有人执行了 mongo↔panweidb 双向补数据（疑回滚准备或对账），部分集合只回写了 mongo 一侧、未同步 panweidb，形成新的反向缺口。**需人工确认该同步进程的状态与最终意图。**

---

## 三项检查结论

### 1. 计数巡检（migrate_mongo_to_panweidb.py --verify）—— ❌ 异常

本次覆盖 **148 个集合**（10-25 为 95 个，疑与新功能集合落库/人工补数据有关，建议人工留意）：**135 相等 / 4 增（预期）/ 9 缺（置顶告警）**。

- **数据丢失（置顶项）**：9 个集合见上表，合计 **-63 行**（性质见上文判断）。
- **切流后新增写入（预期，只报增量）**：4 个集合 panweidb > mongo，合计 **+59 行**：

  | 集合 | mongo → panweidb | 增量 |
  |---|---:|---:|
  | mesc_ontology_perm_audit | 5 → 58 | +53 |
  | mesc_ontology_grant | 2 → 6 | +4 |
  | skill_quality_metrics | 3 → 4 | +1 |
  | mesc_ontology_class_detail | 1 → 2 | +1 |

- **积极变化**：连续三日未动的 8 个大缺口集合（kernel_event_inbox、kernel_event_projections、memories、token_usage_logs、enterprise_tool_audit、enterprise_action_receipts、chat_messages、skill_quality_metrics）**今日全部补齐**（-6,956 → 0）。

### 2. 建表巡检（generate_ddl.py --check）—— ✅ 通过

「✅ 全部表已就位」：schema=mogo_dev 已有 **149 张表**，期望 122 张，**无缺失**（10-24/10-25 缺失的 15 张——portal_* 5、skill_eval_* 4、trust_* 5、quota_projects、quota_alert_events、connector_installs、egress_allowlist——已补建）。

### 3. 三服务健康检查—— ✅ 通过

| 服务 | status | backend | reachable |
|---|---|---|---|
| admin-api | ok | panweidb | true |
| chat-api | ok | panweidb | true |
| document-api（document-parser） | ok | panweidb | true |

与 .env 当前 MOGO_DATA_BACKEND=PanWeiDB 一致，无异常。

### 4. PgCompatUnsupported 日志抽样—— ✅ 0 命中

近 24h 三服务日志共 59,380 行（已核实非空），PgCompatUnsupported 命中 **0 条**（R2 补完清单无新增）。附带观察：AdminShutdown / dispatch_failed / psycopg 类错误今日亦为 **0**（10-25 分别为 6 / 2 次），瞬时故障未复现。

---

## 总体结论：需人工介入

1. **9 个集合反向缺口 -63 行**（mongo 95 > panweidb 83 等）：按规则触发 RB-1，但佐证表明系人工回补作业中间态（mongo 零实时写入、panweidb 侧数据未动）。**需人工确认：同步进程是否仍在跑？最终以哪侧为权威？是否需要把 mongo 侧回写的 63 行补入 panweidb 或回滚？**
2. **连续三日的 -6,956 行大缺口今日全部归零、15 张缺失表已补建**：迁移完整性问题已修复，PanWeiDB 侧运行面（三服务健康、零 PgCompatUnsupported、零瞬时故障）持续平稳。
3. 巡检集合数由 95 → 148，疑与新功能集合落库有关，建议人工顺带确认。
