# 027 后续：从「可切换」到「真正下线 mongo」——切流 + 下线清单（含回滚预案）

**关联**：`specs/027-mongo-to-panweidb-migration/`（R1/R2/R3 已完成，默认后端仍是 mongo）
**状态**：待执行。本清单是 027 落地的"收尾阶段"，非 027 原 spec 范围。
**核心前提（务必先读）**：027 已交付的是"可切换 + 已验证能迁 + 可即时回滚"的能力，**当前运行栈默认仍是 mongo**（`docker-compose.yml` 第 475/578/650 行 `MOGO_DATA_BACKEND:-mongo`；`mongo:` 服务仍在拓扑里；PanWeiDB 是 `--profile panweidb` 门控、默认不启动）。本清单覆盖"翻转开关 → 全流量验证 → 稳定观察 → 下线 mongo"的全过程。

---

## 0. 目标与成功定义

**目标**：三个后端服务（admin-api / chat-api / document-parser）在运行态全部以 PanWeiDB 为唯一业务数据存储，mongo 容器与依赖被移除，且仍可即时回滚到 mongo。

**下线完成的可判定标准（DoD）**：
- [ ] 运行栈三服务 `MOGO_DATA_BACKEND=panweidb` 持续运行 ≥ 观察期（建议 ≥ 7×24h）。
- [ ] `docker-compose.yml` 中 `mongo:` 服务已移除；`MONGODB_URI` / `motor` / `pymongo` 默认值已清理。
- [ ] 全量回归（默认 panwei 路径）通过：admin-api / chat-api / document-parser 与 R2 基线（907 / 2857 / 22）一致（剔除已知环境失败）。
- [ ] 计数校验不一致项 = 0；巡检报"全部表已就位"。
- [ ] 回滚演练一次成功（改回 mongo + 重启，零改代码）。

---

## 1. 门槛 / 就绪检查（Gate —— 不通过不得切流）

> 这些项未闭合，意味着"切过去可能拿不到等价行为或无法判定健康"，必须先解。

- [ ] **G1｜未决规格项先定值**：`checklists/requirements.md` 中 **CHK015（兼容层性能预算 p95/吞吐）** 与 **CHK027（索引验收抽样口径）** 仍为"提案待 clarify"。切流前至少给一版临时阈值（提案值可用：主键 `find_one` p95 ≤ 1.5× mongo 基线；条件查询 ≤ 4×；写吞吐 ≥ 0.7×；行数 >1000 的表不得 Seq Scan）。
- [ ] **G2｜守卫全绿**：`python -m pytest deploy/tests/test_pg_compat_parity.py` → **14/14**（异步副本逐字节一致 / 同步==机械变换 / 禁用 A 模式函数 / 异步探活）。
- [ ] **G3｜差分脚本可连真实 mongo**：`python scripts/pg/verify_mongo_pg_diff.py` 能跑（聚合 19/19、bulk_write 8/8、正则 32/32、partial/sparse 4/4 的基线）。
- [ ] **G4｜源库可停机/可备份**：切流前对 mongo 做一次**全量备份**（切流期不再双写，备份即"最后一份 mongo 真相"，用于回滚 delta）。记录备份位置与恢复命令。
- [ ] **G5｜目标库制备工具就绪**：`scripts/pg/generate_ddl.py`（含 `--from-mongo`）、`migrate_mongo_to_panweidb.py`（含 `--dry-run/--verify/--prune/--resume`）可运行；`deploy/pg/schema.sql` 存在。
- [ ] **G6｜应用层定时任务确认**：7 处 TTL（`expireAfterSeconds`）在 panwei 下走应用层清理——确认各服务 `ttl_purge_loop` 与 `purge_expired_ttl` 已随启动启用（T083 / plan §5.5）。
- [ ] **G7｜审计库分离配置确认**：独立 schema 已配且业务 schema 不可见；未配置时回退业务 schema 仍可用（FR-030 / T079）。
- [ ] **G8｜域级路由可用作灰度手段**：确认 `effective_data_backend_for`（T082）支持 `MOGO_DATA_BACKEND_<DOMAIN>` 按域覆盖，可用于"先切一个低风险域"。

---

## 2. 阶段 0 — 目标库制备（PanWeiDB 就位）

- [ ] **P0-1** 启动目标库：`MOGO_DATA_BACKEND=panweidb docker compose --profile panweidb up -d`。
- [ ] **P0-2** 健康检查：`/health` 返回 panwei 后端快照 `backend: panweidb` / `reachable: true`（确认 `PANWEIDB_HOST` 默认服务名可达、连接池建立成功）。
- [ ] **P0-3** 建表：`python scripts/pg/generate_ddl.py --from-mongo`（以源库实际集合为权威来源，规避静态漏扫；含 T064 修补）+ 应用 `deploy/pg/schema.sql`。
- [ ] **P0-4** 巡检：`python scripts/pg/generate_ddl.py --check` → 报"期望 N / 已有 M"，缺失项 = 0（最终应为 119 表 / 491 索引，R3 扁平化后真库口径）。
- [ ] **P0-5** 启动 TTL 清理循环 + 审计独立 schema（G6/G7 落地验证）。

---

## 3. 阶段 1 — 数据搬迁与校验（只读源库，幂等）

> 设计是"先搬迁、后切换、可回滚"，**不双写**。本阶段源 mongo 仍是活数据源，目标库只进不出。

- [ ] **P1-1 演练**：`python scripts/pg/migrate_mongo_to_panweidb.py --dry-run` → 输出每集合待搬文档数，不写库。
- [ ] **P1-2 搬迁**：去掉 `--dry-run` 执行；支持 `--resume` 续跑（进度表 `<schema>._migration_progress`）；ON CONFLICT DO UPDATE 保证幂等。
- [ ] **P1-3 对账删除**：`--prune` 删除目标库中源库已不存在的行（解决会话 GC 等源侧删除，T065）。
- [ ] **P1-4 校验**：`--verify` 逐集合比对源/目标文档数，不一致项 = 0。
- [ ] **P1-5 门面回读抽检**：用兼容门面对目标库读取 + 更新若干条，断言字段/嵌套/数组/中文/空串/`_id` 归一/深合并与源一致（R1 真库回读 13/13 基线）。
- [ ] **P1-6 重跑幂等**：重复 P1-2/P1-3，目标库计数**不增加**（SC-004）。

---

## 4. 阶段 2 — 灰度切流（关键新增阶段，先不一次性全翻）

> ⛔ **放量冻结（ADR-6，2026-10-23 拍板）**：在「补同步增量 vs 直接回滚」决策作出前，**不得继续放量**——不扩大灰度域、不翻转更多服务、不提高 panwei 流量比例；已灰度的保持现状或回退上一稳定态。默认处置：补同步增量优先（冻结 panwei 写入 → 反向补齐 mongo → 切回）；缺口经业务确认可接受时才直接回滚。详见 `Decisions/ADR-6-027切流后数据缺口处置与放量冻结.md`。

> 用域级路由做最小爆炸半径。顺序建议：先 document-parser（同步、历史只用同步驱动、回归面最小）→ 再 chat-api → 最后 admin-api（含 dashboard，已修 T 500）。

- [ ] **P2-1 单域灰度**：对某低风险域设 `MOGO_DATA_BACKEND_<DOMAIN>=panweidb`，其余仍 mongo。跑真实流量。
- [ ] **P2-2 观测**：`/health` 后端快照正确；错误率/延迟对照 mongo 基线；dashboard `/overview` 不再 500（T 修复已就位）；租户销毁流程（FR-029）与墓碑回收（FR-032）抽样验证。
- [ ] **P2-3 差分核对**：对灰度域用 `verify_mongo_pg_diff.py` 比对同一管道在两边结果（聚合/bulk_write/正则），确认语义等价。
- [ ] **P2-4 单服务全切**：灰度域无异常后，整服务翻转 `MOGO_DATA_BACKEND=panweidb` 重启（document-parser 先行）。重复 P2-2/P2-3。
- [ ] **P2-5 扩散**：依次 chat-api → admin-api，每步重复 P2-2/P2-3，上一步稳定再动下一步。
- [ ] **P2-6 全栈翻转**：三服务 `MOGO_DATA_BACKEND=panweidb`（`.env` 统一设置，不再依赖 per-domain）。

---

## 5. 阶段 3 — 稳定观察期（Soak）

- [ ] **P3-1** mongo **保持运行但不接收写入**（开关已全翻），作为即时回滚源。
- [ ] **P3-2** 观察期 ≥ 7×24h，持续监控：错误率、p95 延迟（对照 G1 阈值）、连接池耗尽/不可达可用性语义（FR-031，存储抖动不得锁死管理面账号）。
- [ ] **P3-3** 观察期内周期性 `--verify` 计数校验（确认无意外漂移）。
- [ ] **P3-4** 真实触发一次租户销毁 + 一次审计保留期到期，确认 FR-029/FR-032 在 panwei 下行为不变。
- [ ] **P3-5** 性能预算复核：达到 G1 定值即算通过；未达需回退该服务或回滚（见 §7）。

---

## 6. 阶段 4 — 真正下线 mongo

> 仅当阶段 3 全绿、且已确认 panwei 为唯一活数据源后执行。**不可逆操作，执行前再二次确认**。

- [ ] **P4-1** 停止 mongo 写入已确认（阶段 2 起即无写入）；对 mongo 做最终备份归档（保留策略：建议 ≥ 观察期 ×2 或按合规要求）。
- [ ] **P4-2** 从 `docker-compose.yml` 移除 `mongo:` 服务定义及其 `depends_on` / 卷 `mongo-data`。
- [ ] **P4-3** 清理应用环境变量：`MONGODB_URI` / `MOGO_MONGODB_URI` 默认值、`.env.example` 中 mongo 示例；保留 `MOGO_DATA_BACKEND` 但默认值可改为 `panweidb`（或保留 `mongo` 仅作回滚入口，由团队决定）。
- [ ] **P4-4** 依赖清理：三服务 `requirements.in` / `requirements.txt` 移除 `motor` / `pymongo`（确认 panwei 路径不再 `import`）；重生成带哈希锁定文件并 `pip install --require-hashes` 实测（FR-028 / T044 基线）。
- [ ] **P4-5** 代码收口：`app/core/db.py` 与 `config.py` 中"默认 mongo 分支"——保留开关骨架（便于回滚），但移除 mongo 专用初始化路径与惰性 import；`pg_compat.py` 三副本守卫（`sync_pg_compat.py`）仍保留以防漂移。
- [ ] **P4-6** 全局搜索确认无残留 mongo 连接/调用：`grep -rn "pymongo\|motor\|mongodb://" services/ deploy/` 仅剩注释与回滚说明。
- [ ] **P4-7** 移除 mongo 卷/容器；保留备份归档与恢复文档。
- [ ] **P4-8** 更新 `docs/mongo-to-panweidb-migration-plan.md` 与 027 规约，登记"mongo 已下线 + 日期 + 备份位置"。

---

## 7. 回滚预案（Rollback）

**开关式回滚是 027 的设计根基（SC-008）：回滚 = 改回 `MOGO_DATA_BACKEND=mongo` + 重启，零改代码。**

### 7.1 回滚窗口与数据一致性（重要警告）
- **安全回滚窗口**：在**阶段 2 灰度 / 阶段 3 早期且 mongo 仍持续接收写入**时，直接改回 mongo 即无损——因为 panwei 的写入可在窗口内反向迁回，或干脆丢弃（mongo 仍是真相）。
- **危险区**：一旦 mongo **完全停止接收写入**（阶段 2 全翻后），panwei 成为唯一活数据源。此时若回滚到 mongo，**mongo 缺少切流期间的新增/变更数据**，必须做 **panwei→mongo 反向迁移**（当前工具只支持 mongo→panwei 单向；需临时扩展或手工导出）才能无损。
- **结论**：阶段 3 观察期内若必须回滚，优先"回退到上一个仍写 mongo 的服务/域"，避免全栈翻回造成数据缺口。

**处置决策已固化为 ADR-6**（`Decisions/ADR-6-027切流后数据缺口处置与放量冻结.md`）：默认「补同步增量优先」——① 冻结 panwei 写入（补数窗口=停写窗口，需业务窗口配合）→ ② 反向补齐 mongo（027 工具只单向，需临时脚本：panwei JSONB → pymongo，`_id` 字符串→ObjectId 按集合主键策略还原）→ ③ 切回 mongo 并跑回归；缺口经业务确认可接受（dev 数据/可重放/极小缺口）才直接回滚。**决策前冻结放量**：不扩灰度、不翻更多服务；只读巡检继续跑，为决策供数。

### 7.2 回滚步骤
- [ ] **RB-1** 任一阶段发现阻断性问题（错误率飙升、关键调用点抛 `PgCompatUnsupported`、dashboard 500、租户销毁失败）：立即将受影响服务/域的 `MOGO_DATA_BACKEND` 改回 `mongo`。
- [ ] **RB-2** 重启该服务；`/health` 确认 `backend: mongo` / `reachable: true`；跑该服务 mongo 路径回归（admin-api 907 / chat-api 2857 / document-parser 22 基线）确认恢复。
- [ ] **RB-3** 若已全翻且无 mongo 写入：先执行 panwei→mongo 反向搬迁（或接受数据缺口并明确告知），再切回。
- [ ] **RB-4** 记录根因：未覆盖能力按 FR-016 会显式抛异常——把异常里的"未实现内容 + 处理位置"登记为 R2 补完项，修复后重新进入阶段 2。
- [ ] **RB-5** 回滚后 mongo 容器/备份保持不变，不删除，直到确认不再需要。

### 7.3 回滚演练（建议阶段 3 内做一次）
- [ ] 在观察期第 1 天，主动把一服务切回 mongo 再切回 panwei，验证"零改代码回滚"真实可用，并验证反向数据一致。

---

## 8. 风险与未决项（切流前必读）

| 项 | 说明 | 关联 |
|---|---|---|
| 性能预算未定值 | CHK015 仍"提案"，需 clarify 或先用提案阈值 | G1 |
| 索引验收口径未定值 | CHK027 仍"提案"，GIN 不可用只能 btree(tenant_id) | G1 / SC-009 |
| 主键 `_id` 类型归一 | mongo 对象 → panwei 字符串，115 处调用点已解耦（T085），但切流后按对象比较的隐藏点需回归 | plan §2.9 |
| 正则方言差异 | PCRE vs 目标库方言，`translate_regex_pattern` 已处理常见情形，复杂断言需改写 | T084 |
| 唯一/稀疏/部分索引语义 | 34 处 unique / 3 处 sparse 已实现为应用层或内联字面量，需抽样核对约束行为 | T083 |
| 未覆盖能力 | 聚合/算子未覆盖项会显式抛异常（FR-016），切流后由异常日志精确枚举缺口 | R2 |
| 双写缺失导致回滚数据缺口 | 见 §7.1，避免在"mongo 已停写"后回滚 | §7 |

---

## 9. 执行顺序速览

```
Gate(G1-G8) → P0 制库 → P1 搬迁校验 → P2 灰度切流(域→服务→全栈)
            → P3 观察期(≥7d, mongo 保活) → P4 下线 mongo
回滚随时可走 RB-1..RB-5（受 §7.1 数据窗口约束）
```

**一句话**：027 把"能迁、能切、能回"做扎实了；这份清单补的是"把开关真正翻过去 + 把 mongo 真正拆掉"的最后一段，核心纪律是**灰度切流、观察期保活 mongo、回滚受数据窗口约束**。
