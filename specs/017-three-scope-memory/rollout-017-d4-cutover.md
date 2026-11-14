# 017 D4 一次性切换 · 发布与回滚手册（T041 / T042）

**状态**：B6 维护窗口执行手册（配套 `scripts/migrate_017_scopes.py`，T039 / T040）。
**权威依据**：[`design-2026-11-05-project-department-scopes.md`](./design-2026-11-05-project-department-scopes.md)
§10「数据迁移与一次性切换」（M0–M4、S1–S7、成对回滚 SOP、R9 / R15）、§2.2、§9.2、§11（SC-10 / SC-15）；
[`tasks.md`](./tasks.md) T039–T042；仓库既有迁移纪律 `scripts/migrate_046_project_dimension.py`。

> **D4 裁决**：`workspace/org → project/department` 直接改名，**无运行时兼容层**。
> 目标态只存在一套拼写，历史数据由离线幂等脚本在切换窗口内一次性转换。
> **取消的是运行时兼容层，不是数据迁移**——跳过 B6 直接发布 B2 代码会造成新旧实例数据分叉且无法自动修复（R15）。

---

## 0. 三条铁律（执行前逐条确认）

1. **切换窗口内不得新旧实例并存**。没有别名兜底时，旧实例仍写入 `workspace` / `workspace_id`，
   新实例读不到 → 数据分叉且无自动修复路径（R15）。必须冻结写入 → 全量替换副本 → 才解冻。
2. **回滚必须成对执行**：「代码回退 + `--reverse`」两者必须同时执行，缺一不可（R9）。
   只回退代码会留下新拼写数据，旧代码读不到，记忆表现为「消失」。
3. **B2 代码产物必须与迁移同窗口发布**（J-6 / `tasks.md` Dependencies）：
   M1 代码替换阶段**只进分支、不上线**，等到 M2 迁移完成的同一维护窗口才随 M3 一起发布。

---

## 1. 工件与命令速查

| 工件 | 路径 / 说明 |
|---|---|
| 迁移脚本 | `scripts/migrate_017_scopes.py`（T039 / T040，默认 dry-run） |
| 本手册 | `specs/017-three-scope-memory/rollout-017-d4-cutover.md` |
| 失败清单 / 三清单 | 默认 `services/chat-api/backups/017-scope-cutover-<mode>-<UTC时间戳>.json`（`--report` 可改；**不写死已有备份文件名**） |
| `memories` 备份 | `MOGO_MIGRATION_DUMP_DIR/017-pre-cutover-<ts>/`（M0 产出，保留 N 天） |
| M1 代码分支 | B2 / T011–T017 产物（`MemoryScope` / `Visibility` / `Memory` / `address.py` / `store.py` / 端点 / 契约 / 021 文档） |

```bash
# 纯函数自测（不连库、不写库）——任何环境都可先跑
python3 scripts/migrate_017_scopes.py --self-test

# dry-run（只打印统计 + 写 JSON 清单，不写库）——永远第一步
python3 scripts/migrate_017_scopes.py

# 落盘（可重入，第二次 0 条变更）
python3 scripts/migrate_017_scopes.py --apply

# 单租户 / 指定报告 / 追加外部持久化引用盘点源
python3 scripts/migrate_017_scopes.py --tenant-id t1 \
  --report /tmp/017-report.json \
  --address-source chat_sessions.context \
  --address-source position_role_audit_logs.details

# 成对回滚的数据侧（必须先回退代码）
python3 scripts/migrate_017_scopes.py --reverse --apply
```

**T040 写入边界**：脚本默认只写 `memories`；`projects` / `org_units` /
`end_user_org_relations` / `chat_sessions` **只读、禁止写入**（只读查询允许）。
`--address-source` 追加的外部引用源默认只盘点、不改写；
`--address-allow-rewrite COLLECTION` 可显式授权写其它集合，但只读白名单仍由
`_assert_writable` 强制拦截。

---

## 2. 切换流程 M0 → M4

顺序（强约束，不可调换）：

```
M0 前置 → M1 代码替换（不发布） → M2 冻结写入 + 离线迁移 → M3 发布新代码 / 解冻 → M4 对账清理
```

### M0 · 前置（独立提交，可单独回滚）

- [ ] **依赖就绪**：DEP-1（统一 `MemoryViewerContext`）、DEP-2（降级：`end_user_org_relations`
      读取侧不带 `status` 过滤，跟随 049 写法）、DEP-3（真实 auth 契约 + 真实 `projects` /
      `org_units` fixture 的回归用例）。
- [ ] **J-5 全仓旧字面量清单核对**：确认 B2 已一次性替换
      `scope.py`（`MemoryScope` / `Visibility` / `SCOPE_VISIBILITY` / `Memory` dataclass）、
      `sediment.py`、`retrieval.py`、`store.py`、`address.py`、`api/endpoints/memory.py`、
      `adapters.py`、`context_space/`、`contracts/memory-context-contract.md:12-24`、
      017 与 021 的 spec / plan / tasks / quickstart。
      替换后全仓 `workspace` / `org` 字面量**仅**允许残留在迁移脚本与历史说明（SC-15 前半）。
- [ ] **盘点持久化旧地址**（`mogo://memory/workspace|org/...`）：逐项登记载体，供 S6 使用
      ——会话上下文 / 021 引用 / 前端缓存（localStorage、会话草稿）/ 审计 `details` 字段。
      用 `--address-source COLLECTION.FIELD` 把库内载体接进 S6 盘点；库外载体（前端缓存、
      外部系统书签）由 M0 人工清单登记并通知持有方。
- [ ] **备份 `memories` 集合**（046 同款门禁：`MOGO_MIGRATION_DUMP_DIR`）：

      ```bash
      TS=$(date -u +%Y%m%dT%H%M%SZ)
      mongodump --uri "$MONGODB_URI" --db "${MOGO_DB_NAME:-mogo}" \
        --collection memories --out "${MOGO_MIGRATION_DUMP_DIR}/017-pre-cutover-${TS}"
      ```

- [ ] **演练环境预演**：`--self-test` → dry-run → `--apply` → 第二次 `--apply`（0 条）→
      `--reverse --apply` → 再 `--apply`，见 §4.1 / §4.4。演练记录随切换单归档。

### M1 · 代码替换（离线，**不发布**）

- [ ] B2 产物一次性替换：scope 枚举、dataclass 字段、模块参数、地址段、契约与 SDD 文档。
- [ ] **删除** `normalize_scope`、双写、三级回退、别名分支、`legacy_alias` 回显；
      新代码只认 `personal / project / department`，`visible_to` 对未知 scope fail-closed。
- [ ] `parse_memory_uri()` 对 `mogo://memory/workspace|org/...` 返回解析失败 / 404，
      不再原样回显（§9.2 / §10.3）。
- [ ] 分支保留，**不发布**；未上线即可弃用，单独回滚不影响数据。

### M2 · 冻结写入 + 离线迁移（维护窗口）

1. **冻结 017 写入**：网关短暂停写 / 特性开关；确认所有在途请求排空。
   记录冻结开始时间。
2. **dry-run 预演**：`python3 scripts/migrate_017_scopes.py`
   （可用 `--tenant-id` 先单租户试跑）。核对 stdout 统计与 `--report` JSON：
   - `stats.changed` / `stats.archived` / `stats.conflicts` 是否符合预期；
   - `failures[]` 的 `archive_reasons` 是否集中在 S3 / S4 / S5 / S7，且**无猜测性归属**
     （任何一条都不应出现「任选一行回填」）；
   - `addresses` 三清单齐全：`rewritten`（已改写）/ `need_manual_review`（需人工确认）/
     `unparseable`（无法解析）；无法定位的旧地址**只登记不重写**。
3. **落盘**：`python3 scripts/migrate_017_scopes.py --apply`。
4. **可重入校验**：再次执行 `--apply`，`stats.changed` 必须为 **0**（SC-10）。
5. **对账：旧 scope / 旧字段 0 条**（命令见 §4.2）。
6. **S6 三清单签收**：`need_manual_review` / `unparseable` 逐条指派责任人与处置结论；
   外部只读载体由人工按清单改写或通知持有方（R15）。

> 迁移**不触碰** `projects` / `org_units` / `end_user_org_relations` / `chat_sessions`（T040）。
> `project_owner_id` 一旦写入即不可变，迁移后无需订阅 049 事件。

### M3 · 原子切换 + 解冻

- [ ] **同批次发布**：部署 M1 新代码 + 解冻写入，一次变更完成（M3 与 M2 在同一维护窗口）。
- [ ] 确认**无旧实例残留**：滚动更新期间不得新旧实例并存；全部副本替换完成后才解冻。
- [ ] 冒烟：写 `scope=project` / `scope=department` 各一条 → 读回 → RAG 命中 → 地址往返一致。
- [ ] 若冒烟失败，立即进入 §3 成对回滚 SOP，不要「只回退代码」。

### M4 · 对账与清理

- [ ] 抽样验证读 / 写 / RAG / 地址往返；确认 `scope_invalid` 与旧地址 404 无异常突增（§4.3）。
- [ ] 备份保留 N 天（N 由运维策略定），期内可再次 `--reverse`（R9）。
- [ ] 同步 SDD 与 021 契约（`contracts/memory-context-contract.md`、021 quickstart 的
      `mogo://memory/workspace/...` 示例改为 `project/...`）。
- [ ] 移除旧字段残留（应已由 S2 `$unset` 清零，见 §4.2 复核）；配置监控告警阈值。
- [ ] SC-15 检查单逐项签收（§4.5）。

---

## 3. 成对回滚 SOP（R9）

**触发**：M3 冒烟失败、切换后出现数据分叉、或必须退回旧代码的任何情形。

```
[1] 冻结写入（若尚未冻结）
[2] 回退代码：把 M1 新代码回滚到上一版（旧拼写：personal/workspace/org + workspace_id/org_id）
[3] 立刻执行数据反向迁移（与 [2] 成对，间隔越短越好）：
      python3 scripts/migrate_017_scopes.py --reverse --apply
[4] 核对：旧 scope / 旧字段恢复；用 M0 备份与失败清单交叉比对
[5] 解冻写入
[6] 记录演练 / 回滚时间线，归档报告 JSON
```

**禁止**：只回退代码、不执行 `--reverse`。旧代码读不到新拼写数据，记忆会「消失」且无自动修复路径。

**`--reverse` 边界（务必告知值班）**：

| 还原 | 不还原 |
|---|---|
| S1：`project→workspace`、`department→org` | **S4 / S7 写入的 `archived` 标记不自动撤销** |
| S2：`project_id→workspace_id`、`department_id→org_id`（`$rename` + `$unset` 残留） | 归档记忆的归属判定（由管理员按失败清单手工决定） |
| S3：`$unset` 删除 `project_owner_id` | 外部只读持久化引用的人工改写（脚本从未自动改写，需人工回退） |
| S6：`memories` 文本字段内的地址逆映射 | |

> 「不撤销 `archived`」是**刻意设计**：避免把 S3（同名项目歧义 / 零行）、S4（`default`）、
> S5（无效部门节点）、S7（孤儿）已判定为越权的记忆重新放出。脚本输出会打印 WARN。
> `--reverse` 是对 `memories` 的整库逆映射，仅在成对回滚窗口、已冻结写入时执行。

---

## 4. 切换演练与对账清单（T042）

### 4.1 切换前演练（预演环境，禁止连生产库写入）

| # | 步骤 | 预期 |
|---|---|---|
| 1 | `python3 scripts/migrate_017_scopes.py --self-test` | `self-test passed`，不连库 |
| 2 | 造样例数据：`workspace` / `org` / 未知 scope / `project_id="default"` / 同名 `project_id` 多行 / 零行 / 无效 `department_id` / 缺 `project_owner_id` | 覆盖 S1–S7 |
| 3 | dry-run | 只打印统计 + 写 JSON 清单，不写库 |
| 4 | `--apply` | 按 S1–S7 转换；三类孤儿全部进 `failures[]` 且带 `archived` |
| 5 | 第二次 `--apply` | **`stats.changed == 0`**（可重入 / SC-10） |
| 6 | `--reverse --apply` | 旧 scope / 旧字段恢复，`project_owner_id` 被删除，`archived` 仍在 |
| 7 | 再 `--apply` | 数据回到目标态，再次验证 0 条 |

### 4.2 旧 scope / 旧字段 0 条校验命令

在 `mongosh` 中对 `memories` 执行（**切换后 M2 对账 / M4 复核各跑一次**，全部期望 `0`）：

```javascript
// 1) 旧 scope 值 0 条
db.memories.countDocuments({scope: {$in: ["workspace", "org"]}})                       // 0

// 2) 旧字段 0 条（S2 $rename + $unset 残留）
db.memories.countDocuments({$or: [
  {workspace_id: {$exists: true}}, {org_id: {$exists: true}}
]})                                                                                     // 0

// 3) 未知 scope 0 条（S1/S7）
db.memories.countDocuments({scope: {$nin: ["personal", "project", "department"]}})      // 0

// 4) 未归档 project 记忆缺归属 / 指向 default 0 条（S3/S4/S7）
db.memories.countDocuments({scope: "project", archived: {$ne: true}, $or: [
  {project_id: {$in: ["", null]}}, {project_id: {$exists: false}},
  {project_owner_id: {$in: ["", null]}}, {project_owner_id: {$exists: false}},
  {project_id: "default"}
]})                                                                                     // 0

// 5) 未归档 department 记忆缺 department_id 0 条（S5/S7）
db.memories.countDocuments({scope: "department", archived: {$ne: true}, $or: [
  {department_id: {$in: ["", null]}}, {department_id: {$exists: false}}
]})                                                                                     // 0

// 6) memories 文本字段内仍残留旧地址段 0 条（S6 已改写部分）
const OLD = /mogo:\/\/memory\/(workspace|org)\//
db.memories.countDocuments({$or: [
  {content: OLD}, {l0_summary: OLD}, {l1_overview: OLD}, {l2_raw: OLD}
]})                                                                                     // 0

// 7) 归档总数应与迁移报告 failures[].archive_reasons 非空条目数一致
db.memories.countDocuments({archived: true})
```

> 第 4/5 条刻意排除 `archived: true`：归档记忆本来就是判定为不可靠、由管理员按清单
> 决定是否重建的，不要求它们补齐归属字段。

### 4.3 监控点

| 监控项 | 位置 | 切换后期望 | 异常含义 |
|---|---|---|---|
| `scope_invalid` 写入拒绝 | 写入端点 `400 scope_invalid` / 观测日志 | 基线附近，无突增 | 仍有旧客户端 / 旧实例在写 `workspace` / `org`（R15） |
| 旧地址 404 | 021 `context/resolve` 对 `mogo://memory/workspace\|org/...` | 基线附近，无突增 | 外部持久化旧地址未在 S6 / M0 改写，按 `need_manual_review` 清单处置 |
| `memory.default_project_fallback` | 观测日志 | 正常 | `default` 沉淀回落 `personal` 生效（N2） |
| `retrieval_trace` 的 `skipped` | 观测通道 | 原因可归类（含 `default_project_excluded` / `missing_project_owner`） | 缺 `project_owner_id` 的历史记忆应 fail-closed |
| `memory.promoted` / `memory.archived` | 001 审计 | 正常 | 治理动作可查 |

> `scope_invalid` 与旧地址 404 突增是 R15 的第一信号：一旦出现，先确认是否有旧实例
> 残留（违反「切换窗口内不得新旧实例并存」），再按 §3 决定是否回滚。

### 4.4 `--reverse` 演练步骤（预演环境）

```bash
# 前置：演练环境已完成一次 --apply，且 M0 备份可用
python3 scripts/migrate_017_scopes.py --reverse              # 先 dry-run 看统计 / WARN
python3 scripts/migrate_017_scopes.py --reverse --apply      # 落盘
```

演练验收：

- [ ] stdout 出现 WARN：`--reverse 不撤销 S4/S7 的 archived 标记`；
- [ ] 报告 `warnings[]` 含 3 条（archived 不撤销 / 外部只读引用不自动还原 / 整库逆映射约束）；
- [ ] §4.2 的旧 scope / 旧字段校验在 reverse 后**不再为 0**（说明已还原到旧拼写）；
- [ ] `project_owner_id` 字段已删除；
- [ ] `archived: true` 的文档数量与 reverse 前**一致**（未被撤销）；
- [ ] 演练全程未连生产库、未对生产执行写操作。

### 4.5 SC-10 / SC-15 签收表

| 验收项 | 判据 | 证据 | 签收 |
|---|---|---|---|
| **SC-10** 迁移脚本连续两次执行，第二次 0 条写入 | 第二次 `--apply` 报告 `stats.changed == 0` | 两份报告 JSON | ☐ |
| **SC-10** `--reverse` 还原 S1/S2/S6 且不撤销 S4/S7 的 `archived` | §4.4 全部勾选项 | 演练记录 + 报告 | ☐ |
| **SC-10** 同名 `project_id` 多行 / 零行 / `default` 三类孤儿全部进清单且无猜测性归属 | `failures[].archive_reasons` 含 `S3` / `S4`；无 `project_owner_id` 猜测性回填 | 失败清单 JSON | ☐ |
| **SC-10** S6 三清单齐全、无法定位的旧地址只登记不重写 | `addresses` 三个数组均存在；`need_manual_review` 中「无法定位」条目未出现在 `rewritten` | 报告 JSON | ☐ |
| **SC-15** 全仓 `workspace`/`org` 字面量仅残留在迁移脚本与历史说明（J-5） | 全仓检索结果 | 检索输出 | ☐ |
| **SC-15** `memories` 中旧 scope 值 0 条、`workspace_id`/`org_id` 字段 0 条 | §4.2 第 1/2 条 | mongosh 输出 | ☐ |
| **SC-15** 写入旧 scope / 请求旧字段 / 解析旧地址分别 `400 scope_invalid` / `400` / `404` | M3 冒烟用例 | 冒烟记录 | ☐ |
| **SC-15** M1 代码与 M2 数据切换在同一维护窗口完成 | 变更单时间线（M2 冻结 → `--apply` → M3 发布/解冻连续） | 变更单 | ☐ |
| **SC-15** `--reverse` 演练通过 | §4.4 全部勾选项 | 演练记录 | ☐ |
| **成对回滚 SOP** 已演练并留记录 | 代码回退 + `--reverse --apply` 成对执行记录 | 演练记录 | ☐ |
| **切换窗口内无新旧实例并存** | 冻结 → 全量替换 → 解冻的副本核对记录 | 发布记录 | ☐ |

---

## 5. 归档判定速查（S3 / S4 / S5 / S7）

| 步骤 | 判定 | 处置 |
|---|---|---|
| **S3** | `project_id` 非空且非 `default` 时，按 `{tenant_id, _id: project_id}` 查 `projects.user_id`；**命中多行（N1 同名项目）或零行** | 标 `archived` + 进 `failures[]`，**不得猜测性归属**；命中恰好一行才回填 `project_owner_id` |
| **S4** | `project_id == "default"` | 直接 `archived`（N2：049 的 `_id="default"` 是租户共享兜底行，禁止承载项目记忆） |
| **S5** | 所有非空 `department_id` 校验为真实 `org_units` 节点且 `tenant_id` 匹配 | 节点不存在 / 跨租户 → `archived`（D3）；脚本**不固化**部门名单，可见性在读取时按 `path_ids` 子树重算 |
| **S7** | 未知 scope、`scope=project` 缺 `project_id` / `project_owner_id`、`scope=department` 缺 `department_id`、缺 `tenant_id` | 统一 `archived` + 进 `failures[]`，由管理员按清单决定重建 |

> S2 新旧字段并存且**值冲突**时不覆盖新字段、仅清理旧字段残留并进 `failures[].conflicts`，
> 保证 M4 对账「旧字段 0 条」成立。

---

## 6. 字段名核对备注（设计文档 vs 真实代码）

落地前已按只读方式核对以下事实（**未修改任何现有文件**）：

| 项 | 设计文档 | 真实代码 | 结论 |
|---|---|---|---|
| `memories` 集合名 | §2.2 `memories` | `store.py:21` `COLLECTION = "memories"` | 一致 |
| 旧 scope 取值 | `personal / workspace / org` | `scope.py:25-28` `MemoryScope` | 一致 |
| 旧字段 | `workspace_id` / `org_id` | `store.py:52-56,140-158` | 一致 |
| `org_units` 后代字段 | §1.2 / §3.2 `path_ids` | `directory.py:290,137,332`、`subjects.py:70-75`、`column_map.py:394` 均为 `path_ids` | **一致，无字段名不符** |
| `org_units` 实际写入字段 | §1.2 列 `_id / tenant_id / name / code / parent_id / path_ids / path_names / status / ...` | `directory.py:284-298` | 一致；`path_ids` 是**祖先 id 数组**（后代展开 = 查 `path_ids` 含目标 id 的节点），S5 只校验节点存在 + tenant 匹配，不展开 |
| `projects` 主键 / 唯一索引 | §1.1 / §2.4：`_id = workspace_id`；唯一索引 `{tenant_id, user_id, workspace_id}`，`_id` 租户内不保证唯一（N1） | `projects.py:134`（`$setOnInsert._id = workspace_id`）、`main.py:502` 唯一索引 | 一致；故 S3 不能用 `find_one`（会掩盖多行），脚本统计全部匹配行 |
| `projects._id="default"` | §2.4 / N2 租户共享兜底行 | `projects.py:104-119`（`$setOnInsert._id="default"`，且该行**不写 `workspace_id` 字段**） | 一致；S3 按 `_id` 反查不依赖 `workspace_id` |
| `mogo://memory/...` 地址 | §9.2 `<scope>/<owner>/<id>/[L0\|L1\|L2]` | `address.py:21` `VALID_SCOPES = ("personal","workspace","org")` | 一致（旧值），M1 改为三新值 |

**需要留意的口径差异（非字段名不符）**：

1. **字段改名范围**：D4 的 `workspace_id→project_id` / `org_id→department_id` 只针对
   **`memories` 集合**。`projects` 集合的真实字段仍叫 `workspace_id`
   （`projects.py:8-9` 明确「HTTP contract ... `workspace_id` ... deliberately unchanged」），
   脚本按 `{tenant_id, _id: project_id}` 反查，不依赖 `workspace_id` 字段。
2. **S5 失败处置**：设计文档 §10.2 写「进清单」，任务 T039 要求「否则归档」；
   脚本按任务口径 **归档 + 进清单**，并在报告里同时保留归档原因。
3. **S6 三清单命名**：设计文档 §10.2 为「已改写 / 无法定位 / 已失效」，
   任务 T039 为「已改写 / 需人工确认 / 无法解析」；脚本报告按任务口径命名，
   其中「需人工确认」涵盖设计文档的「无法定位（对应记忆）」与「只读引用源（已失效 /
   不自动改写）」，「无法解析」对应格式非法的地址。
4. **`project_owner_id` 缺失的历史记忆**：运行时 `visible_to` 对其 fail-closed（§4.2），
   迁移期由 S3 回填、回填失败由 S7 归档；两者不冲突。

**未找到 / 未在本次落地范围内核实的字段**：S6 的「前端缓存」持久化旧地址不在数据库内，
无固定集合 / 字段名可核对（已按 M0 人工清单登记处理，不编造字段名）；
审计 `details` 的具体子键随事件而异，脚本用 `--address-source` 的 JSON 往返扫描顶层字段，
不假设子键名。检索过的关键词：`path_ids`、`ancestors`、`org_units`、
`end_user_org_relations`、`mogo://memory`、`memory/workspace`、`memory/org`。
