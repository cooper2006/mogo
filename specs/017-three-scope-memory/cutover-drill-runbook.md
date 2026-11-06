# 017 / D4 切换演练与回归手册（T042 / T043 / T045 / T046）

本手册是把已落地的 B2–B4（代码侧）与 B6（迁移脚本）推进到 **生产原子切换** 的
操作清单。所有标「🔒 需维护窗口」的步骤都**不能在普通迭代中执行**，必须在约定
维护窗口、冻结写入、备好回滚的前提下操作；标「✅ 已可本地核验」的可在 CI / 本地
提前跑通。

> 关联文档：`rollout-017-d4-cutover.md`（M0–M4 主流程 + 三条铁律）、
> `design-2026-11-05-project-department-scopes.md`（§10 迁移算法 S1–S7）、
> `scripts/migrate_017_scopes.py`（迁移脚本，默认 dry-run）。
>
> 发布闸门（不可逾越）：B2/B3/B4 代码**必须**与 `migrate_017_scopes.py --apply`
> 在**同一维护窗口**原子切换；回滚必须「代码回退 + `--reverse`」成对执行；切换窗口
> 内**不得**新旧实例并存（见 rollout 文档「三条铁律」）。

---

## T042 切换演练（🔒 需维护窗口 + 真实库 + 写入冻结）

目标：在准生产/影子库完整演练一次「代码切换 + 数据迁移 + 回滚」，并核对旧 scope /
旧字段 0 条残留。

### T042-1 演练前准备
1. 选取影子库（与生产同构、含近 1 个月抽样数据），**冻结写入**（停会话沉淀、停记忆
   写入入口）。
2. 全量备份 `memories`、`projects`、`org_units`、`end_user_org_relations`、
   `chat_sessions`（脚本只读这四张，但回滚需整库可还原）。
3. 记录演练前基线计数：
   ```bash
   # 旧值基线（演练后必须归零）
   mongo> db.memories.countDocuments({scope:"workspace"})
   mongo> db.memories.countDocuments({scope:"org"})
   mongo> db.memories.countDocuments({workspace_id:{$exists:true}})
   mongo> db.memories.countDocuments({org_id:{$exists:true}})
   mongo> db.memories.countDocuments({project_owner_id:{$exists:true}})
   ```

### T042-2 正向演练（dry-run → apply）
```bash
# 1) 默认 dry-run：只打印统计与失败清单，不落盘
python scripts/migrate_017_scopes.py --report backups/017-dryrun.json
# 2) 自检（不连库也能跑，校验逆映射/S1-S7 可逆性逻辑）
python scripts/migrate_017_scopes.py --self-test
# 3) 冻结写入后，正式落盘
python scripts/migrate_017_scopes.py --apply --report backups/017-apply.json
```
- 检查 `017-apply.json`：S3（project_owner_id 回填）的「多行/零行归档」清单、
  S5（部门校验失败）清单、S7（孤儿）清单是否为预期空集或可解释项。
- 回放一遍 `rollout` 文档 M2–M4 的代码侧切换（部署 B2/B3/B4 镜像到影子环境）。

### T042-3 逆向演练（`--reverse`）
```bash
# 仅在「成对回滚窗口、已冻结写入」时执行；不撤销 S4/S7 的 archived 标记
python scripts/migrate_017_scopes.py --reverse --report backups/017-reverse.json
```
- 核对 `--reverse` 后：scope 值、字段名（`project_id/department_id ←
  workspace_id/org_id` 逆映射）、S3 补的 `project_owner_id` 被 `$unset`。
- 确认 `archived` 标记**未被撤销**（脚本会打印 WARN，符合预期）。

### T042-4 旧字面量 0 条对账（SC-15 后半）
演练结束后复测 T042-1 的基线查询，必须**全部为 0**：
```
scope=workspace       → 0
scope=org             → 0
workspace_id 残留     → 0
org_id 残留           → 0
```
（注：`project_owner_id` 是**新增**字段，演练后应 >0 且为合法值，不在此归零范围。）

### T042 通过判据
- [ ] dry-run / --self-test / --apply / --reverse 四步均按预期输出，无意外异常；
- [ ] 旧 scope 与旧字段在目标库 0 条残留；
- [ ] `--reverse` 可逆且 archived 不被误撤；
- [ ] 回滚后旧代码镜像可正常读写（验证「成对回滚」闭环）。

---

## T043 049 全链路手工回归（🔒 需 admin 会话 + A/B/C 账号凭据）

目标：确认 017 的 D4 改名**没有破坏** 049 项目管理（配额 / 成员 / 归档）。
自动侧 049 既有测试未在本轮重跑（见 T046），此处为手工端到端步骤。

前置：admin 账号 + 三个终端账号 A（项目 owner）、B（项目成员）、C（无关用户）；
项目 `P1` 由 A 创建并邀请 B 为成员。

### T043-1 配额（SC-9）
1. admin 进入「项目管理」，确认 `P1` 出现在列表（**修复点：049 已修「管理端无数据」**，
   网关 `projects-with-usage` 应返回 200 / 含 `P1`）。
2. 校验配额/用量字段：`member_count` 含 A、B；`usage` 与记忆条数一致。

### T043-2 成员（C-7 回归）
1. A 在 `P1` 下新增/移除成员，触发 `PATCH /api/v1/projects/{id}` → 校验
   `member_user_ids` diff 触发 `project.member.granted` / `project.member.revoked`
   审计事件（feature=049）。
2. B 退出 `P1`（移除成员）后：B 的 `visible_project_keys` 不再含 `P1`，B 对 `P1`
   项目记忆不可见（fail-closed，`visible_to` 收敛）。
3. C（无关用户）对 `P1` 记忆始终 404/不可见。

### T043-3 归档（H-3 / H-6 关联）
1. 归档 `P1` → 其 `status=archived`；B 的 `visible_project_keys` 立即不含 `P1`
   （viewer 每次解析，动态重算）。
2. 触发 017 治理端点 `POST /memories/admin/governance/project-archive`
   `{project_id, project_owner_id, reason}` → `P1` 的 project 记忆 `invalidated=true`
   退出 RAG 默认检索（H-6）。
3. 解除归档 `P1` → B 重新可见（成员仍有效时）。

### T043 通过判据
- [ ] `projects-with-usage` 200 且含 `P1`；配额/用量正确；
- [ ] 成员增删触发 049 `project.member.*` 审计；
- [ ] 成员移除/项目归档后记忆可见性按预期 fail-closed；
- [ ] `project-archive` 端点使 `P1` 记忆 `invalidated=true` 且退出 RAG。

---

## T045 M4 对账清理（🔒 随 T042 切换完成）

目标：切换成功后，固化备份、清理残留、校准监控；本步骤**依赖 T042 切换已完成**。

1. **备份保留**：迁移前的全量备份至少保留 **30 天**（或按合规要求），到期前不得删除；
   归档 `017-apply.json` / `017-reverse.json` 报告入配置/变更库。
2. **旧字段残留移除**：在目标库确认 T042-4 的 0 条基线后，提交一条一次性
   `$unset` 清理（仅针对演练/切换中意外残留的旧字段，须先 count 为 0 再操作）。
3. **监控告警阈值**：
   - `memories` 中 `scope` 取值分布告警（出现 `workspace`/`org` 立即告警，应为 0）；
   - 治理 `pending_approval` 堆积阈值（如 >50 待审批触发值班）；
   - `invalidated` 记忆占比异常告警（offboard 误操作排查）。
4. **SC-15 签收表**：维护一份签收清单（旧字面量残留 = 0、迁移可重入、回滚成对、
   无新旧并存），由值班 + 负责人双签。

### T045 通过判据
- [ ] 备份保留策略已记录并到期前不可删；
- [ ] 旧字段残留确认 0 条并完成清理；
- [ ] 监控阈值上线且能触发测试告警；
- [ ] SC-15 签收表双签完成。

---

## T046 全量回归清单（✅ 本地可跑 / 🔒 需维护窗口）

落地后的完整回归组合，**未执行项（依赖窗口/凭据/浏览器）保持未勾选**。

### T046-A 本地可立即核验（✅ 已在本轮执行）
- [x] chat-api 记忆相关测试全绿（本批次新增 20 例 + 既有套件 275+ passed）；
- [x] admin-api 治理端点测试 35 passed（含新增 approve/reject/offboard 路径）；
- [x] 双端 `vue-tsc --noEmit` 0 错误；
- [x] `scripts/migrate_017_scopes.py --self-test` 通过；
- [x] 两服务 `compileall` 通过。

### T046-B 真实构建 + E2E（🔒 未执行）
- [ ] `apps/user-web` 与 `apps/admin-web` 生产构建（`pnpm build`）0 错误；
- [ ] 真实浏览器 E2E：`apps/user-web/e2e/memory-promote.spec.ts`、
      `apps/admin-web/e2e/memories-governance.spec.ts` 全绿（见各自 README 的
      执行方式，需起服 + 凭据 + Playwright）。

### T046-C 049 自动回归 + 切换演练（🔒 未执行）
- [ ] 049 既有测试套件在本轮重跑全绿（自动侧，未随 017 重跑）；
- [ ] T042 切换演练四步 + T043 手工回归 + T045 对账全部签收。

### T046 最终放行条件
- [x] 本地全量回归（A 组）全绿 + 双端类型检查 + 迁移自检 + compileall；
- [ ] B 组真实构建与 E2E、C 组 049 回归与切换演练在维护窗口内完成签收。

---

## 附录：关键命令速查
```bash
# 迁移（默认 dry-run）
python scripts/migrate_017_scopes.py
# 自检（不连库）
python scripts/migrate_017_scopes.py --self-test
# 正式切换（冻结写入后）
python scripts/migrate_017_scopes.py --apply --report backups/017-apply.json
# 成对回滚（冻结写入后）
python scripts/migrate_017_scopes.py --reverse --report backups/017-reverse.json

# 测试
cd services/chat-api && .venv/bin/python -m pytest tests/memory/ -q
cd services/admin-api && .venv/bin/python -m pytest tests/test_memories_admin.py -q

# 前端类型检查
cd apps/user-web && pnpm vue-tsc --noEmit
cd apps/admin-web && pnpm vue-tsc --noEmit
```
