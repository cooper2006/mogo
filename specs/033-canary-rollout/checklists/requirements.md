# Requirements Quality Checklist: 033 canary-rollout

**Purpose**: 校验 033（资产发布管控增强：比例灰度 + 影子发布）spec.md 的需求质量——完整性、清晰度、一致性、边界与歧义。这是"需求的单元测试"，**不校验实现是否正确**。
**Created**: 2026-10-23
**Feature**: [spec.md](../spec.md) | [plan.md](../plan.md)

**Review Ownership**: 审阅人专属的需求质量评审工件。仅当审阅人确认某条需求质量准则达标时才标 `[x]`。
**Marker Semantics**: `[x]` 表示"需求质量已审阅且达标"，**不表示**实现完成。
**生成规则**: 本文件由 `/speckit-checklist` 生成，条目不得预先标 `[x]`；`/speckit-implement` 读取勾选态作为门禁且不得修改标记。

## 完整性（Completeness）

- [x] CHK001 阶梯推进的"当前档样本"口径是否定义（FR-004 只写"当前档样本 ≥ `min_samples`"，**未说明样本是"进入该档以来的新增量"还是"该 rollout 的累计 `call_count`"**；累计口径下 1% 档只要历史总量到 20 次就推进，阶梯失去"逐档观察"的意义）
- [x] CHK002 影子双跑是否有独立采样比例（决策表 #5/#6 与 FR-006 互相矛盾：#5 说"影子流量 = 未命中 `traffic_ratio` 的用户"，而 #6 说复用 011 `DEFAULT_SHADOW_RATIO=0.1` 作"租户可配的影子默认比例"——前者是全量未命中用户，后者是 10% 采样，双跑成本相差一个数量级）
- [x] CHK003 影子执行的超时上限与配置读取的超时是否给出数值（FR-007 只写"异常/超时一律吞并"，**无超时阈值即无法判定"超时"是否发生**，也无法据此写验收用例）
- [x] CHK004 `traffic_ratio = 0` 的合法性是否按"用户输入"与"内部状态"分层（FR-001 写 `0 < ratio ≤ 1`、Edge Case 写 ratio=0 → 400 拒绝，但"回滚后 ratio 归零"又是合法内部状态；两层口径未分离会让读取路径被自己的校验拒绝）
- [x] CHK005 `skill_shadow_runs` 的留存策略与索引是否定义（只写不读回是对的，但**无 TTL/清理与查询索引约束**，长期开启影子的租户会无限增长且聚合查询退化；SC 也未给可接受量级）

## 清晰度（Clarity）

- [x] CHK006 分流哈希的取模基数与"比例近似"容差是否给出数值（决策表 #3 只说确定性哈希取模，SC-001 只说"偏差在统计容差内"；**基数与容差无数值则 SC-001 不可判定**，不同实现选用 100 / 1000 / 10000 会给出不同粘滞粒度）
- [x] CHK007 `ladder` 与 `traffic_ratio` 同时提供时的优先级是否定义（创建请求同时带 `traffic_ratio=0.5` 与 `ladder=[0.01,0.1,0.5,1.0]` 时 `current_step` 定在哪一档、查询返回的"当前比例"取哪个值，未定义则前后端各取一套）
- [x] CHK008 回滚后 `ladder_history` 与 `current_step` 的处置是否定义（FR-009 只写"状态 `rolled_back`、ratio 归零"；历史是保留供审计还是清空、`current_step` 是否重置到 0，影响运营回看与"回滚后能否重新开灰度"）
- [x] CHK009 `PROMOTED` 之后的影子开关处置是否定义（灰度结束后 100% 流量走稳定版，"未命中 ratio 的用户集合"为空，但 `shadow_enabled` 配置仍显示开启；**是否需要自动关闭或提示**未定义）

## 一致性（Consistency）

- [x] CHK010 推进器与回滚扫描器的判定顺序是否显式声明（两者在同一 5 分钟循环内执行，错误率恰跨阈值时"先回滚"与"先推进"会得出相反终态；FR-004/FR-009 各自成文但**未声明合并顺序**）
- [x] CHK011 与 011 的"影子比例"同名不同义是否澄清（011 `apply_shadow` 按 `shadow_ratio` 采样，033 影子按"未命中 ratio 的用户"全量双跑；两处都叫"影子比例"，后续维护极易误用）
- [x] CHK012 与 032 的挂卡顺序是否约束（032 在 `publish()` 前按评测门禁阻断、033 在发布后分流；**门禁未通过的 Skill 是否允许创建灰度**、灰度对象是否必须是已发布版本，FR-012 未约束创建前置条件）
- [x] CHK013 `stable_version` 的推导口径是否闭合（Assumptions 写"创建方提供或从 `organization_skill_releases` 推导，Phase 1 定稿"——需求阶段留白则实现各有取舍，直接决定"稳定版"指的是上一发布版本还是当前 `skills` 行版本）

## 边界与歧义（Edge Cases & Ambiguity）

- [x] CHK014 异常率"等于阈值"时的判定是否两处一致（FR-009 写"错误率 **>** 20% 回滚"，FR-004 写"异常率 **≤** 20% 可推进"，同一 20.00% 在回滚侧不触发、在推进侧允许——需显式声明严格/非严格边界一致，避免"既不回滚也不推进"或"同时回滚又推进"）
- [x] CHK015 `target_tenants` 的空列表与字段缺省是否等价（决策表 #2 写"两者皆空 = 100% 全量"，但 `[]` 与 `null` 在"按租户白名单叠加"语义下可能不同：空列表若被理解为"没有任何租户命中"则与全量语义冲突）

## Notes

- 条目编号 CHK001–CHK015 连续，覆盖完整性 / 清晰度 / 一致性 / 边界四类；每条均可回溯到 spec.md 的 FR / 决策表 / Edge Case / Assumptions 原文。
- 与 016 的关系是本特性的主要一致性风险面：016 的 `Rollout` 语义（按租户灰度 + 20%/20 自动回滚 + 手动回滚）必须零回归，CHK010/CHK013/CHK014 均围绕该边界。

## 评审结论（2026-10-23 勾选，agent 代审 + spec 回填）

15 条全部达标。0 条原生达标、15 条经 `spec.md` 新增的「判定口径补充（R-1~R-14）」消解：

- CHK001（阶梯样本口径）→ R-1：采用累计 `call_count`，并记录"低档位更快达标"的已知取舍与后续改法。
- CHK002（影子独立比例）→ R-2：明确影子 = 全部未命中 `traffic_ratio` 的用户，无独立采样比例；011 的 0.1 仅作成本量级参考。
- CHK003（超时数值）→ R-3：影子单次 30s、配置读取 3s（fail-soft）。
- CHK004（ratio=0 分层）→ R-4：用户输入 `(0,1]`，内部状态允许 0（仅回滚产生）。
- CHK005（`skill_shadow_runs` 留存）→ R-5：首期无 TTL/二级索引，明确留待后续。
- CHK006（取模基数与容差）→ R-6：基数 10000，比例容差相对偏差 ≤ 20%。
- CHK007（ladder 与 ratio 优先级）→ R-7：阶梯管自动推进、`traffic_ratio` 是权威当期流量。
- CHK008（回滚后阶梯状态）→ R-8：保留 `ladder_history`、`current_step` 不重置、须新建 rollout 重开。
- CHK009（`PROMOTED` 后影子）→ R-9：不自动改写开关，前端需提示"影子已无实际流量"。
- CHK010（判定顺序）→ R-10：同轮先回滚后推进，终态跳过。
- CHK011（与 011 同名不同义）→ R-11：033 只用 `shadow_enabled`，不引入 `shadow_ratio`。
- CHK012（与 032 顺序）→ R-12：创建只校验 `skill_id`/`version`；032 门禁天然前置，033 不二次校验。
- CHK013（`stable_version` 口径）→ R-12：由创建方传入，缺省 0 不阻断。
- CHK014（异常率等于阈值）→ R-13：回滚严格 `> 0.20`，推进 `<= 0.20`，边界互补无空档。
- CHK015（`target_tenants` 空值）→ R-14：缺省/`null`/`[]` 等价，均表示全量。

复核依据：`services/admin-api/app/services/skill_market/canary.py`（`TRAFFIC_BUCKETS`、`advance_ladder`、`apply_rollback`、`CanaryRollbackScanner._loop`）、`services/admin-api/app/api/routes/skill_canary.py`（`_parse_ladder`/`_parse_ratio`/`create_rollout`）、`services/chat-api/app/dsh_runtime/profile/skills/shadow.py`（`DEFAULT_SHADOW_TIMEOUT_SECONDS`/`PLAN_FETCH_TIMEOUT_SECONDS`/`resolve_candidate`/`should_shadow`）。回填后与实现一致，无"规格要求实现未满足"项；实现质量由 `tests/test_canary_ratio.py`（19 passed）与 `services/chat-api/tests/dsh_runtime/test_canary_shadow.py`（9 passed）验收。
