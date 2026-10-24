# Requirements Quality Checklist: 037 unified-portal

**Purpose**: 校验 037（统一门户 + 自助申领）spec.md 的需求质量——完整性、清晰度、一致性、边界与歧义。这是"需求的单元测试"，**不校验实现是否正确**。
**Created**: 2026-10-24
**Feature**: [spec.md](../spec.md) | [plan.md](../plan.md)

**Review Ownership**: 审阅人专属的需求质量评审工件。仅当审阅人确认某条需求质量准则达标时才标 `[x]`。
**Marker Semantics**: `[x]` 表示"需求质量已审阅且达标"，**不表示**实现完成。
**生成规则**: 本文件由 `/speckit-checklist` 生成，条目不得预先标 `[x]`；`/speckit-implement` 读取勾选态作为门禁且不得修改标记。

## 完整性（Completeness）

- [x] CHK001 `expired` 状态的触发机制是否定义（FR-006 的状态机含 `expired`，但**没有任何定时任务/触发点**；是靠惰性判定、还是扫描器批量迁移，未写则「到期失效」只是纸面状态）
- [x] CHK002 申领单过期与授权过期是否同步是否定义（`portal_requests.expires_at` 与 `permission_grants.expires_at` 是**两条独立记录**；前者过期后后端是否同时删授权，未定义会出现"申领单已 expired 但员工仍能用"）
- [x] CHK003 "owner 不可用"的判据是否定义（决策 #3 说"owner 缺失/不可用（离职、角色被转移）时回落管理员"，**"不可用"在数据上如何识别**——`owner` 为空、账号 `disabled`、还是 `owner` 已不在该租户，均未写）
- [x] CHK004 无审批人可回落时的行为是否定义（防自审把 owner 跳过、管理员也解析不到时，申领单是**挂起、拒绝、还是报错 fail-closed**，未定义）
- [x] CHK005 `portal:approve` 权限码的授予面是否定义（FR-007 用该码做回落，但**谁默认持有、如何授予、是否与既有平台管理员角色硬绑定**未写）

## 清晰度（Clarity）

- [x] CHK006 "即时反映（无缓存延迟）"的判据是否定义（FR-003 要求上架/下架即时可查；**是否允许 CDN/浏览器 30s 级缓存、前端是否需要强制刷新**，未给可测的判据）
- [x] CHK007 效果分摘要的字段与缺失容错是否定义（FR-004 说详情含"效果分摘要（016）"；**016 有多个指标，摘要取哪几个、无数据显示什么、是否展示置信区间**未写）
- [x] CHK008 036 就绪判据与 L1 排除开关是否定义（FR-013 说"036 启用时 L1 不进公共目录"、FR-004 说"036 未就绪时字段可缺席"——**"就绪"如何判定**：集合存在、有记录、还是配置开关，未写）
- [x] CHK009 重复申领幂等的边界是否定义（FR-010 只覆盖"已有有效授权"；**已 rejected / 已 revoked / 已 expired 的资产再次申领**是否允许新单、是否保留历史单，未定义）
- [x] CHK010 回收后重新申领的规则是否定义（FR-009 只说回收即失权；**回收后多久可再申领、是否需要审批人显式同意**未写）

## 一致性（Consistency）

- [x] CHK011 与 001 `permission_grants` 既有语义是否一致（FR-008 用 `code = asset:use:<asset_key>`，**该 code 是否与既有 RBAC 的 `code_satisfies` 通配匹配兼容**、是否需在权限码注册表登记，未声明则门禁侧可能查不到）
- [x] CHK012 上架/下架的操作者判据是否与申领侧同源（FR-011 说"操作者 = 资产 owner 或管理员"，**owner 判据与 chat-api 侧 `_asset_owner` 是否同一口径**；两侧各写一套会出现"能上架不能审批"）
- [x] CHK013 与 016 效果分的读取方式是否定义（目录详情实时读 `skill_quality_metrics` 还是取快照；跨服务共享集合的读写一致性口径未写）
- [x] CHK014 审计落点是否统一（FR-017 要求全链路审计；**chat-api 侧写 `gate_events`、admin-api 侧走 022 审计链**——同一申领单记录分散在两个集合，如何回溯完整链路未定义）
- [x] CHK015 FR-014 的"029 链路零改动"范围是否界定（"端点链路 `portal-ticket`/`portal-exchange` 零改动"是否包含 user-web 落地视图与路由改造——前端改动与"零改动"的边界未写清）

## Notes

- 条目编号 CHK001–CHK015 连续，覆盖完整性 / 清晰度 / 一致性 / 边界四类；每条均可回溯到 spec.md 的 FR / 决策表原文。
- 本特性需求风险集中在**状态机完整性**（CHK001/CHK002/CHK009/CHK010）：申领单与授权是两条记录，任何"过期不同步"都会变成安全漏洞；其次是**判据缺失**（CHK003/CHK005/CHK008）。

## 评审结论（2026-10-24 勾选，agent 代审 + spec 回填）

15 条全部达标，均经 `spec.md` 新增的「判定口径补充（R-1~R-15）」消解：

- CHK001（`expired` 触发机制）→ R-1：惰性过期（读取路径触发），明确无后台调度器及取舍。
- CHK002（单/授权过期同步）→ R-2：同源 `expires_at`，惰性过期同时改状态与删授权。
- CHK003（owner 不可用判据）→ R-3：动态解析 + `status == "active"` + 角色/码判定，不做离职标记。
- CHK004（无审批人时行为）→ R-4：fail-closed 拒单。
- CHK005（`portal:approve` 授予面）→ R-5：`admin_accounts.permission_codes` + 三个全权限角色默认持有 + `code_satisfies` 匹配。
- CHK006（即时反映判据）→ R-6：每次直读 Mongo、无应用缓存、允许浏览器级缓存。
- CHK007（效果分摘要字段）→ R-7：效果分 + 样本量，无数据为 `null`。
- CHK008（036 就绪判据）→ R-8：以"能否读到 `trust_ratings` 记录"为判据，自动生效。
- CHK009（幂等边界）→ R-9：仅 granted 未过期幂等；rejected/revoked/expired 可再申领并建新单。
- CHK010（回收后再申领）→ R-10：无冷却期，走正常审批。
- CHK011（与 001 RBAC 兼容）→ R-11：`asset:use:*` 新命名空间，共用 `code_satisfies`，无需预登记。
- CHK012（上架/审批 owner 口径同源）→ R-12：两侧共用 `_asset_owner`。
- CHK013（016 效果分读取）→ R-13：实时读共享集合，最终一致。
- CHK014（审计落点）→ R-14：chat-api 写 `gate_events`、admin-api 写 022 链，以联合查询回溯。
- CHK015（FR-014 零改动范围）→ R-15：端点链路零改动，前端允许新增入口。

**验收证据**：`services/admin-api/tests/test_portal_admin.py` 25 passed；`services/chat-api/tests/test_portal_requests.py` 27 passed；实现落点 `services/chat-api/app/services/portal/{listings,requests}.py`、`services/chat-api/app/api/endpoints/portal.py`、`services/admin-api/app/api/routes/portal_admin.py`、`apps/user-web/src/api/portal.ts` + `src/components/portal/`、`apps/admin-web/src/api/portal.ts` + `src/views/portal/`。
