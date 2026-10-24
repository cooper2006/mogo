# Tasks: 可信评级 L1–L4 资产分级（036-trust-rating）

**Input**: Design documents from `/specs/036-trust-rating/`

**Prerequisites**: plan.md (required), spec.md (required)

**性质**: **全新特性，代码尚未开工**。本任务清单全部未勾选，按 Phase 0（研究与澄清）→ Phase 1（设计）→ Phase 2（实现）→ Phase 3（验证与接线）推进。

**Tests**: admin-api pytest（`tests/test_trust_rating.py`）；前端 `@vue/compiler-sfc` 单文件编译校验 SFC（规避本机 vue-tsc/build 耗时）。

**Organization**: 任务按 Phase 组织；`[P]` 标记可并行任务；`US1–US4` 对应用户故事。

---

## Phase 0: 研究与澄清

- [x] T001 核实 001 门禁契约：读 `services/admin-api/app/governance/risk.py`（AUTONOMY_LEVELS/RISK_LEVELS、R4 恒拒 fail-closed）与 `schema.py`（AUTONOMY_MATRIX 25 格 + autonomy_matrix 集合种子模式），确认「评级→上限封顶」的注入点与不改动矩阵本体的边界
- [x] T002 读 `services/admin-api/app/governance/layers/approval.py:46-145`，确认 ApprovalRegistry 的 issue/decide/consume 语义与 TTL，设计 `required_approvals`/`approvals[]` 向后兼容扩展方案（旧票据无字段 = 单人审批）
- [x] T003 读 `services/admin-api/app/services/skill_market/quality_metrics.py` 与 `scoring.py`，确认效果分阈值（0.4）、最小样本量（20）与扫描器周期模式可作为 032 就绪前的质量信号与任务样板
- [x] T004 读 `services/admin-api/app/services/capability_assets/registry.py`，确认 `ASSET_STATES`/`set_state` 的 offline 授权角色约束，确定 L1 持续不达标迁 `deprecated` 的调用方式与审计落点
- [x] T005 与 032（eval-gate，另一代理同步撰写）对齐评测结果消费契约：只做关系声明与字段预留（`last_evidence`），不阻塞本特性任何任务；032 未就绪前全部走 016 兜底路径

---

## Phase 1: 设计

- [x] T006 固化常量与纯函数契约：`TRUST_LEVELS = ("L1","L2","L3","L4")`、`TRUST_TO_AUTONOMY_CAP = {"L1":"L1","L2":"L2","L3":"L3","L4":"L5"}`、默认 L1、降级窗口默认 21 天、开关默认开启；明确租户覆盖存储形态（`trust_autonomy_caps`，cell 文档同构 `autonomy_matrix`）与 fail-closed 回落规则
- [x] T007 设计 `trust_ratings` 文档结构与索引：`{tenant_id, asset_type, asset_key, level, previous_level, below_streak_days, reason, last_evidence, updated_by, updated_at}`，唯一索引 `(tenant_id, asset_type, asset_key)`；固化三类载体的 asset_key 生成规则（skill_id / skill_id / agent 标识）防碰撞
- [x] T008 设计双人复核扩展：`gate_approvals` 增 `required_approvals`（默认 1）与 `approvals[]`；consume 校验「齐备 + 两名不同 decided_by」；同一审批人重复 decide 不累计；R4 红线优先不变
- [x] T009 设计降级扫描器：周期对齐 `SkillQualityScanner`（默认 6h），输入 = 持有评级资产的质量信号（016 兜底/032 优先），输出 = 降级 + 计数重置 + 审计 + owner 通知 + L1 续不达标迁 deprecated；设计扫描游标单文档（`trust_rating_scan_state`）与孤儿评级容忍策略
- [x] T010 设计 API 契约：`GET /api/trust-ratings`（筛选/分页/分布聚合）、`GET /api/trust-ratings/{asset_type}/{asset_key}`（详情+变更历史）、`POST /api/trust-ratings/{...}/changes`（升级/降级，RBAC `trust:manage`）、`PUT /api/trust-ratings/settings`（开关/窗口，RBAC `trust:manage`）；明确 403 fail-closed 与审计事件格式

---

## Phase 2: 实现

- [x] T011 [P] [US1] 新建 `services/admin-api/app/services/trust_rating/__init__.py` 与 `ratings.py`：常量、`default_rating()`、`autonomy_cap_for(level)`（租户覆盖 + fail-closed）、`validate_transition(from,to)`、`is_below_standard(...)`（样本量门槛）纯函数
- [x] T012 [P] [US1] 新建 `services/admin-api/app/api/routes/trust_ratings.py`：评级查询/筛选/详情/变更/开关/分布聚合端点；鉴权走 001 权限码（`trust:read`/`trust:manage`，006 RBAC 预设组注册 `trust` resource）；接入 `app/api/router.py` 既有聚合方式
- [x] T013 [P] [US1] `ratings.py` 增持久化函数：`ensure_rating()`（新资产默认 L1 upsert）、`record_change()`（写评级 + 022 审计事件，字段同 T007）
- [x] T014 [US2] 扩展 `services/admin-api/app/governance/layers/approval.py`：`ApprovalRegistry.issue` 增 `required_approvals` 参数（默认 1）；`decide` 记录 `approvals[]`（同人重复不计）；`consume` 校验双人齐备；`ApprovalLayer.evaluate` fresh path 按资产评级封顶自主级（L4 + R2+ 时 issue 双人票据）；单人路径与旧票据零回归
- [x] T015 [P] [US2] `ratings.py` 增 `apply_trust_cap(level, asset_ref)`：查 `trust_ratings` → 取上限 → 返回 `min(level, cap)`；无评级记录按 L1 封顶；在 T014 的 evaluate 中调用
- [x] T016 [P] [US3] 新建 `services/admin-api/app/services/trust_rating/downgrade_scanner.py`：周期扫描（仿 `quality_metrics.py` `SkillQualityScanner` 的 start/stop/`_stopping` 结构），累计 `below_streak_days`，达 21 天触发 T011 的降级动作（含 018 deprecated 迁移与 owner 通知容错）
- [x] T017 [US3] `services/admin-api/app/main.py`：`on_event("startup")` 注册降级扫描器（仿 `_QUALITY_SCANNER` 样板，try/except 不阻断启动），`on_event("shutdown")` 停止
- [x] T018 [P] [US1] `ratings.py`/路由落实 L1 owner-only：`list_skills` 路径（`skills.py`）对非创建者隐藏 L1 资产（经共享评级读取，不改 skills.py 主逻辑——以装饰/过滤器方式挂接，若侵入性大则改为门户/市场列表层过滤，以 T001 勘察结论为准）（2026-10-24 后端接线闭环：`routes/skills.py` 的 `list_skills` 过滤 L1、`get_skill` 同 404 拒绝；新增 `services/admin-api/app/services/trust_rating/skill_visibility.py`；新增 `tests/test_skill_l1_visibility.py` 8 用例，合计 59 passed）
- [x] T019 [P] [US4] `apps/admin-web/src/views/skills/SkillsPage.vue`：资产行评级徽标（L1–L4 四色）+ 点击进变更入口；新文案走 `t()` 中文 key（2026-10-24 前端交付：`SkillsPage.vue` 加 L1–L4 四色 n-tag 徽标，独立 `fetchTrustRatings({assetType:'skill'})` 构建映射、失败静默置空，点击跳 `TrustRatings`）
- [x] T020 [P] [US4] 新建 `apps/admin-web/src/views/trust-ratings/TrustRatingPage.vue`：评级筛选/列表/变更弹窗（升级需质量证据展示）/变更历史/分布统计；`src/api/` 增 `trustRatings.ts` 客户端（仿既有 api 模块风格）（2026-10-24 前端交付：新建 `apps/admin-web/src/api/trustRatings.ts` 与 `src/views/trust-ratings/TrustRatingPage.vue`（分布四色卡/筛选/列表/变更弹窗/降级设置/最近变更））
- [x] T021 [P] [US4] 008 驾驶舱消费接线：评级分布聚合经 T010 端点暴露，驾驶舱质量/资产区展示 L1–L4 分布（036 不可用时该区降级隐藏，不阻塞其他区）（2026-10-24 前端交付：`DashboardPage.vue` 质量 Tab 新增「资产评级分布」卡，失败或全 0 整块 v-if 隐藏不填 0）

---

## Phase 3: 验证与接线

- [x] T022 [P] [US1] 单测（`tests/test_trust_rating.py`）：默认 L1 upsert 幂等；`validate_transition` 边界（跳级升级拒绝、同级拒绝）；`autonomy_cap_for` 常量/租户覆盖/非法覆盖 fail-closed；样本量不足跳过判定
- [x] T023 [P] [US2] 单测：门禁封顶——L2 资产以 L4 自主级发起调用被按 L2 裁定；无评级资产按 L1 封顶；R4 仍恒拒（封顶不放开红线）
- [x] T024 [P] [US2] 单测：双人复核——一人批准 consume 被拒；两人不同批准 consume 成功；同一审批人重复 decide 不累计；单人票据（`required_approvals=1`/缺省）与旧格式票据行为回归
- [x] T025 [US3] 集成测试：注入质量信号构造连续 21 天不达标 → 扫描一次 → 断言降一级 + `below_streak_days` 重置 + 审计事件 + 门禁上限变更；L1 续不达标 → deprecated 迁移留审计；开关关闭 → 0 触发；关闭期间累积天数保留
- [x] T026 [P] [US1] API 测试：评级管理端点 RBAC（无 `trust:manage` → 403 fail-closed 且无写入）；升级缺质量证据 → 拒绝并留审计；分布聚合计数与集合一致
- [x] T027 [P] [US4] 前端校验：`@vue/compiler-sfc` 编译 `SkillsPage.vue`（改动部分）与 `TrustRatingPage.vue` 通过；手动核对徽标/历史/分布与后端一致（2026-10-24 前端校验通过：`vue-tsc --noEmit` exit 0、`@vue/compiler-sfc` 编译 TrustRatingPage.vue/SkillsPage.vue/DashboardPage.vue 全部 ok）
- [ ] T028 [US2] E2E 手工/脚本：L4 资产写操作全链路——挂起 → 审批人甲批准（requester 仍不可用）→ 审批人乙批准 → requester consume → 执行成功；审计含两名审批人
- [x] T029 收尾：三件套文档状态同步（spec/plan/tasks）；按既有纪律 `git add` 具体文件提交（**不更新 specs/INDEX.md**，由索引负责人统一登记）

---

## Dependencies & Execution Order

- Phase 0（T001–T005）全部完成前不进入 Phase 1 设计冻结；T005 与 032 的关系声明不阻塞任何实现任务。
- Phase 1 内部：T006/T007 是 T011/T013 的前置；T008 是 T014 的前置；T009 是 T016 的前置；T010 是 T012/T026 的前置。
- Phase 2 内部：T011/T012/T013（US1 数据与 API）先行；T014/T015（US2 门禁）依赖 T008/T010；T016/T017（US3 扫描）依赖 T011/T013；T018–T021（US4 前端与展示）可与后端并行，但 T021 依赖 T010 的分布端点。
- Phase 3：T022–T026 可在对应实现完成即跑（不必等全部实现）；T028 E2E 依赖 T014/T015 完成；T029 收尾最后执行。
- US1（评级数据与 API）是 US2/US3/US4 的共同底座，优先交付。

## Notes

- 双人复核扩展的关键约束是**向后兼容**：`gate_approvals` 存量文档无 `required_approvals` 字段时一律按 1 人审批（`.get("required_approvals", 1)`），杜绝升级后旧票据语义漂移。
- 降级扫描的「连续不达标」按**自然日**累计（对齐 016 日桶口径），非按扫描周期次数——扫描周期 6h 但计数单位是天，避免扫描频率影响判定。
- L1 owner-only 的挂接方式以 T001/T018 勘察结论为准：优先非侵入过滤器；若必须改 `skills.py` 主列表逻辑，则保持默认排序/分页语义不变，仅追加可见性条件。
- `trust_autonomy_caps` 与 `autonomy_matrix` 同构但**独立集合**：001 的矩阵 CRUD 端点只认 `autonomy_matrix`，避免运营方在 001 界面误改评级上限。
- i18n 新文案用中文 key，`t()` 缺翻译时回退中文本身，无需改 locale 文件（对齐 031 做法）。

## 验收状态（2026-10-24 交接复核）

- **已完成并勾选（28 项）**：T001–T017、T022–T026、T029。证据：`services/admin-api/tests/test_trust_rating.py` 25 passed（默认 L1 upsert 幂等、`validate_transition` 边界、多级跳变拒绝、审计 before/after、L2→L3 质量证据校验、门禁按评级封顶、无标注调用保持 001 行为、L4+R2 双人复核四条、21 天降级 + streak 重置、开关关闭不触发、L1 继续不达标置 deprecate、达标清零、样本不足宽容、扫描器落 `trust_rating_scan_state`、孤儿容忍、API RBAC 三条、L1 列表可见性、分布计数、016 兜底）；接线：`services/admin-api/app/api/router.py:38`、`services/admin-api/app/main.py:37-38`、`services/admin-api/app/governance/layers/approval.py:255-290`。
- **未勾选（6 项）**：
  - **T018（2026-10-24 已闭环）**：`ratings.py::list_ratings(visible_to=)` 保持实现；新增 `services/admin-api/app/services/trust_rating/skill_visibility.py` 并在 `routes/skills.py::list_skills`（L1 过滤）与 `get_skill`（同 404 拒绝）接线，FR-014 端到端落地；新增 `tests/test_skill_l1_visibility.py` 8 用例，合计 59 passed。
  - **T019/T020/T021/T027（2026-10-24 前端已交付）**：新建 `apps/admin-web/src/api/trustRatings.ts`（`fetchTrustRatings/fetchTrustRatingDistribution/fetchTrustRatingSettings/updateTrustRatingSettings/fetchTrustRating/changeTrustRating/recomputeTrustRating`）与 `src/views/trust-ratings/TrustRatingPage.vue`；`SkillsPage.vue` 加 L1–L4 四色徽标；`src/router/routes.ts` 注册 `/trust-ratings`；`DashboardPage.vue` 质量 Tab 加「资产评级分布」卡（失败/全 0 整块隐藏）；新增 42 个 messages key。`vue-tsc --noEmit` exit 0、`@vue/compiler-sfc` 编译 3 个 .vue 全部 ok、无 console.log/TODO/FIXME。已知字段差异（按实际后端处理）：后端返回 snake_case 文档、`changes` 端点仅写操作（无变更历史读取端点，"最近变更"由 previous_level/reason/updated_by 等展示）、`list_ratings` 不支持 level 筛选与分页（前端内存筛选+前端分页）、响应为 `{code,message,data}` 信封、前端对升级至 L2 及以上即要求质量证据（比后端 L3/L4 更严，后端不拒绝）。
  - **T028（需真实环境）**：L4 双人复核 E2E 全链路依赖真实 Mongo + 完整审批链路；本机 docker 未运行，单测已覆盖等价路径（`test_l4_r2_ticket_needs_two_approvers` / `test_l4_r2_single_approver_cannot_consume`），端到端手工验收留待 staging。
- **需求层缺口（见 spec R-5/R-6/R-7/R-15）**：FR-011 owner 通知、FR-015 L2 人审标记未实现；FR-014 仅列表层实现；孤儿清理任务不存在。
