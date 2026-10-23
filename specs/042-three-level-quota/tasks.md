# Tasks: 三级配额（团队/项目级）（042-three-level-quota）

**Input**: Design documents from `/specs/042-three-level-quota/`

**Prerequisites**: plan.md (required), spec.md (required)

**性质**: **全新特性**（整合方案 §4.11 立项，代码尚未开工）——spec 先行，tasks 全部未勾选；与 031 的"回溯补规格"（已实现项勾选）不同。

**Tests**: chat-api / admin-api pytest（新增三层语义单测 + 等价回归测试）；前端 `@vue/compiler-sfc` 单文件编译校验。

**Organization**: Phase 0 研究与澄清 → Phase 1 设计 → Phase 2 实现 → Phase 3 验证与接线；T001 起连续编号，全部 `- [ ]`。

---

## Phase 0: 研究与澄清

- [ ] T001 建立 spec/plan/tasks 三件套（`specs/042-three-level-quota/`，本文件）
- [ ] T002 核实 `services/chat-api/app/core/quota_policy.py` 与 `services/admin-api/app/core/quota_policy.py` 两份副本的差异面（逐函数 diff），确认本特性的同步修改清单与唯一差异点
- [ ] T003 澄清团队层成员口径：确认 `end_user_org_relations` 中用户-部门关系的基数（单部门 vs 多部门）与查询路径，落实"直接成员、不做子树聚合"的解析 SQL/MQL 形态
- [ ] T004 澄清告警去重口径：确认"同租户同层同周期去重"的实现位点（周期窗口键 or 文档 upsert），与 008 `ANOMALY_STATUSES` 统计口径对齐

## Phase 1: 设计

- [ ] T005 设计三层解析函数签名与返回结构：`resolve_scoped_policies(tenant_id, user_id)` → `{team: [...], project: [...], user: ..., org: ...}`，明确各层 `total/used/remaining/period` 计算与 unlimited 判定
- [ ] T006 设计 `QuotaSummary` 扩展字段（`teamRemainingPoints` / `projectRemainingPoints` / `limitingScope`）与"未配置层缺省而非哨兵值"的序列化口径（延续 020 FR-037 精神）
- [ ] T007 设计 `quota_projects` 集合 schema（`{tenant_id, name, note, member_user_ids[], status, created_at, updated_at}`）与成员维护服务 `quota_projects.py` 的 CRUD 边界（不含策略本体——策略仍走 `user_quota_policies`）
- [ ] T008 设计告警事件结构 `{tenant_id, scope_type, scope_id, kind: exceeded|approaching, ratio, at}` 与 `ANOMALY_STATUSES` 扩展值（quota_exceeded / quota_approaching）的落点
- [ ] T009  Constitution Check 复核（plan.md 门禁）：确认三层扩展未引入新依赖、未改 001 门禁层、失败路径口径明确

## Phase 2: 实现

- [ ] T010 [P] `services/chat-api/app/core/quota_policy.py`：`scope_type` 支持 team/project；新增团队/项目策略点查与成员反查；`get_quota_summary` 扩展为多层解析 + 取小 + 分层明细 + `limitingScope`；`assert_quota_available` 错误信息按 `limitingScope` 指明超限层
- [ ] T011 [P] `services/chat-api/app/core/quota_policy.py`：接近阈值判定（默认 20%，租户可配）与告警事件产出（超限/接近两类，同租户同层同周期去重）
- [ ] T012 `services/admin-api/app/core/quota_policy.py`：与 T010/T011 同步修改（同名副本，行为一致）
- [ ] T013 [P] `services/admin-api/app/services/quota_projects.py`：项目分组 CRUD + 成员维护（新增集合 `quota_projects`；docstring 声明与桌面 Code `projects` 端点的语义隔离）
- [ ] T014 `services/admin-api/app/api/routes/traffic_allocations.py`：团队额度配置端点（部门树 scope_id + 额度/周期）与项目分组/策略配置端点；复用既有 `update_org_quota_policy` 的鉴权、`ensure_org_quota_policy` 模式与 `user_token_allocation_logs` 写入模式
- [ ] T015 `services/admin-api/app/api/dashboard_metrics.py`：`ANOMALY_STATUSES` 增加 quota 类状态口径，使驾驶舱质量看板异常统计可覆盖配额超限/接近事件
- [ ] T016 [P] `apps/admin-web/src/api/traffic-allocations.ts`：团队/项目配置 API 客户端（既有文件扩展，复用既有请求封装）
- [ ] T017 `apps/admin-web/src/views/organizations/TrafficAllocationsPage.vue`：新增"团队额度"配置区（部门树选择 + 额度/周期表单，复用目录部门树组件）与"项目分组"CRUD 区（名称/成员多选/额度）；新文案走 `t()` 中文 key 回退；编辑既有配置区的交互模式保持一致

## Phase 3: 验证与接线

- [ ] T018 [P] chat-api 单测：三层（team/project/user/org）取小语义矩阵；多团队/多项目命中取最严；未配置层跳过；`points_unlimited` 短路优先；`status != active` 层视同未配置
- [ ] T019 [P] chat-api 单测：单层超限拒绝信息指明层名（team/project/org/user 四种）；接近阈值（<20%）与超限各产一条告警事件；同租户同层同周期去重
- [ ] T020 [P] admin-api 单测：`quota_projects` 服务 CRUD + 成员维护；团队/项目策略端点落库与 `user_token_allocation_logs` 审计；与既有 `test_setup_quota.py` 同树运行
- [ ] T021 等价回归：同一 fixture 下 `get_quota_summary` 改造前后输出逐字段相等（零 team/project 策略场景）；既有 020/001 配额相关测试全绿
- [ ] T022 001 门禁层零改动核验：`git diff --stat` 断言 `services/admin-api/app/governance/layers/quota.py` 无 diff；`tests/` 下 001 配额层既有测试（如 `tests/test_governance_us4_us5.py`）全绿
- [ ] T023 前端校验：`@vue/compiler-sfc` 编译 `TrafficAllocationsPage.vue` 通过；手工联调——配置团队/项目策略 → 成员对话触发限额/恢复 → 驾驶舱异常统计可见 quota 类事件
- [ ] T024 文档接线：在 001/008/020 对应 spec 的"跨特性关系"补记本特性的双向声明（仅文档，不改代码）；本目录 tasks 勾选状态更新（含本条）

---

## Dependencies & Execution Order

- Phase 0（T001-T004）全部完成后进入 Phase 1；T005-T008 为 Phase 2 的前置契约。
- Phase 2 内：T010/T011（chat-api 核心语义）先行；T012 依赖 T010/T011 的定稿形态；T013-T015、T016-T017 可并行（[P] 标记）。
- Phase 3：T018/T019 依赖 T010/T011；T020 依赖 T013/T014；T021/T022 为放行门禁；T023 依赖 T016/T017；T024 收尾。
- 每个 Phase 边界设 checkpoint：Phase 1 完 = 三层解析契约与 schema 冻结；Phase 2 完 = 后端语义 + 配置入口齐备；Phase 3 完 = 回归零漂移 + 001 零 diff + 前端编译通过。

## Notes

- `user_quota_policies` 集合名历史遗留（实为"scoped policies"存储），本特性以 `scope_type` 区分四层，**不重命名、不迁移**——重命名的收益（命名优雅）远低于迁移风险。
- 团队/项目层用量按"当前成员"聚合，成员中途变动不追溯——这是运营口径而非技术妥协，管理端说明文案需明示（T017）。
- 两层 `quota_policy.py` 的同步修改是现状格局（admin-api 与 chat-api 各自持有副本）；T002 的 diff 清单是 T012 的输入，避免漏改。
- 告警去重与 `ANOMALY_STATUSES` 的口径对齐在 T004 澄清——008 spec 明示"异常 = 失败 + 超时 + 限流 合并计"（FR-4），quota 类是新增大类，不改既有三类语义。
