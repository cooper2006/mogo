# 027「MongoDB → PanWeiDB 迁移」切流后每日巡检报告

- **日期**：2026-10-25（周日）
- **巡检性质**：只读巡检，未做任何切流、重启、写库操作
- **.env 当前值**：MOGO_DATA_BACKEND=PanWeiDB（health 按 panweidb 解读）

---

## 🔴 置顶高亮：数据丢失告警（触发 RB-1 回滚条件，需人工决策）

计数巡检中 **8 个集合 panweidb < mongo，合计缺口 -6,956 行**。缺口与 2026-10-23、10-24 两次巡检**逐集合完全一致**——连续三日未恶化、也未补齐：

| 集合 | mongo | panweidb | 缺口 |
|---|---:|---:|---:|
| kernel_event_inbox | 14409 | 11022 | -3387 |
| kernel_event_projections | 13808 | 10460 | -3348 |
| memories | 264 | 72 | -192 |
| token_usage_logs | 139 | 119 | -20 |
| enterprise_tool_audit | 121 | 117 | -4 |
| enterprise_action_receipts | 57 | 54 | -3 |
| chat_messages | 22 | 21 | -1 |
| skill_quality_metrics | 3 | 2 | -1 |
| **合计** | | | **-6,956** |

按判定规则，此为数据丢失类告警，触发 RB-1 回滚条件（.env 改回 MOGO_DATA_BACKEND=mongo 并 docker compose up -d）。本巡检不执行回滚，由人工决定。

---

## 三项检查结论

### 1. 计数巡检（migrate_mongo_to_panweidb.py --verify）—— ❌ 异常

95 个集合：**69 相等 / 18 增（预期）/ 8 缺（数据丢失）**。

- **数据丢失（置顶项）**：8 个集合见上表，合计 **-6,956 行**（连续三日不变）。
- **切流后新增写入（预期，只报增量）**：18 个集合 panweidb > mongo，合计 **+341 行**（与 10-24 的 +341 持平，近 24h 无净新增写入，疑系统空闲）：

  | 集合 | mongo → panweidb | 增量 |
  |---|---:|---:|
  | system_audit_logs | 44 → 127 | +83 |
  | gate_events | 2 → 72 | +70 |
  | mesc_ontology_perm_audit | 5 → 58 | +53 |
  | position_role_audit_logs | 122 → 172 | +50 |
  | admin_sessions | 55 → 83 | +28 |
  | admin_refresh_tokens | 13 → 30 | +17 |
  | end_user_org_relations | 10 → 18 | +8 |
  | end_users | 1 → 9 | +8 |
  | agent_kernel_bindings | 15 → 21 | +6 |
  | runtime_profile_audit | 16 → 22 | +6 |
  | mesc_ontology_grant | 2 → 6 | +4 |
  | chat_sessions | 3 → 5 | +2 |
  | admin_model_instances | 2 → 3 | +1 |
  | audit_logs | 2 → 3 | +1 |
  | enterprise_session_approval_grants | 1 → 2 | +1 |
  | enterprise_tool_approvals | 3 → 4 | +1 |
  | mesc_ontology_class_detail | 1 → 2 | +1 |
  | user_field_defs | 0 → 1 | +1 |

### 2. 建表巡检（generate_ddl.py --check）—— ❌ 异常

非「✅ 全部表已就位」：schema=mogo_dev 已有 **134 张表，期望 122 张，缺失 15 张**（与 10-24 清单完全一致，无新增缺失）：

connector_installs、egress_allowlist、portal_listings、portal_requests、portal_settings、quota_alert_events、quota_projects、skill_eval_cases、skill_eval_policies、skill_eval_runs、skill_shadow_runs、trust_autonomy_caps、trust_rating_scan_state、trust_rating_settings、trust_ratings

（缺失表均为新功能空表，mongo 侧计数亦为 0，数据风险低，但按判定规则列入异常，需人工确认是否补建 DDL。）

### 3. 三服务健康检查—— ✅ 通过

| 服务 | status | backend | reachable |
|---|---|---|---|
| admin-api | ok | panweidb | true |
| chat-api | ok | panweidb | true |
| document-api（document-parser） | ok | panweidb | true |

与 .env 当前 MOGO_DATA_BACKEND=PanWeiDB 一致，无异常。

### 4. PgCompatUnsupported 日志抽样—— ✅ 0 命中

近 24h 三服务日志共 30,178 行，PgCompatUnsupported 命中 **0 条**（R2 补完清单无新增）。

**附带观察（非判定项，仅供参考）**：日志中出现 6 次 `psycopg.errors.AdminShutdown: terminating connection due to administrator command`（document-api、chat-api 各数次）及 2 次 `scheduled.dispatch_failed`，均为 PG 侧连接被管理员命令终止后的瞬时失败，随后自愈（当前健康检查全部通过）。疑与宿主机 PG 维护/连接回收有关，建议人工留意是否需调整连接池参数。

---

## 总体结论：需人工介入

1. **数据丢失缺口 -6,956 行连续三日未处理**（8 个集合，与 10-23、10-24 完全一致）：持续触发 RB-1 回滚条件，需人工决策「回滚 mongo」或「补同步后继续观察」。
2. **15 张期望表缺失**（与 10-24 一致）：需人工确认是否补建 DDL（均为新功能空表，风险低）。
3. 三服务健康、切流后写入增量平稳（近 24h 无净新增），PgCompatUnsupported 零命中——PanWeiDB 侧运行面平稳，问题集中在迁移完整性而非运行时。
