# Quickstart: 三级配额 (042)

**Feature**: [spec.md](./spec.md) | [plan.md](./plan.md) | [tasks.md](./tasks.md) | [checklists/requirements.md](./checklists/requirements.md)

本文件说明如何**启用并验证** 三级配额（042）。

---

## 1. 前置

- 相关服务已部署：admin-api, chat-api（视特性所属服务而定）
- MongoDB 可用（或 PanWeiDB 可选后端；`MOGO_DATA_BACKEND` 未设置即 MongoDB，行为不变）
- 后端测试需 Python 3.10+ 与对应服务 venv；前端测试需 Node/pnpm

## 2. 该特性做了什么

把用量配额从租户+用户两级扩展为部门/项目+租户+用户三级：部门复用 `org_units`、项目取 `project_id`，三层同时生效时扣减取最小、单层超限即拒（fail-closed）。

关键功能需求（FR 摘要）：
- FR-001：系统 MUST 支持 `scope_type ∈ {org, user, team, project}` 四层配额策略；team/project 策略 MUST 存于既有 `user_quota_policies` 集合（其 `(tenant_id, scope_type, scope_id)` 结
- FR-002：部门层 MUST 以 `org_units` 部门树节点为 `scope_id`，成员关系 MUST 复用 `end_user_org_relations`（直接成员口径，不做子树自动聚合）。
- FR-003：~~项目层 MUST 使用新建轻量分组实体（集合 `quota_projects`，成员以内嵌数组维护），MUST 与桌面 Code `projects` 端点语义隔离（命名、入口、docstring 三处区分）~~ —— **已作废**（修订 #2）：项目层 `scope_id` 直接取 `pro
- FR-004：`get_quota_summary` MUST 对每个已配置层分别计算剩余，总结算 `remainingPoints = max(0, min(各已配置层 remaining))`，并在返回值中给出分层明细与 `limitingScope`（当前最严层）。
- FR-005：任一已配置层 remaining ≤ 0 时 `assert_quota_available` MUST 拒绝（`QuotaExceededError`），错误信息 MUST 指明超限层（部门/项目/租户/用户）。

关键验收点（Success Criteria）：
- SC-001: 三层（加租户/用户共四层）策略同时生效时，`remainingPoints` 等于各层取小的手算值（单测覆盖 team/project/user/org 组合矩阵）。
- SC-002: 任一单层超限即拒，错误信息 100% 指明超限层；001 门禁消费端无需改动即获得该语义。
- SC-003: 零部门/项目策略的租户，`get_quota_summary` 输出与改造前逐字段相等（等价回归测试），既有 `test_setup_quota.py` 等配额测试全绿。
- SC-004: 超限与 20% 接近阈值各产生一条可审计告警事件，`ANOMALY_STATUSES` 口径可统计，无重复刷量；无任何新推送通道代码（grep 断言）。

## 3. 如何启用

在 admin-web「项目管理」(`/projects`) 配置项目额度、既有流量分配页（`/organizations/traffic?open=quota`）配置部门额度；`user_quota_policies` 集合支持 org/user/team/project 四层，同时生效取最小，单层超限即拒。

## 4. 如何验证

### 4.1 自动化测试（首选）

逐服务运行下列实测测试文件（INDEX 记录全绿）：


**admin-api（后端）**：
```bash
cd services/admin-api && python -m pytest services/admin-api/tests/test_quota_three_level.py services/admin-api/tests/test_quota_projects.py services/admin-api/tests/test_quota_unlimited.py services/admin-api/tests/test_governance_us4_us5.py -q
```

**chat-api（后端）**：
```bash
cd services/chat-api && python -m pytest services/chat-api/tests/test_quota_three_level.py -q
```

## 5. 注意事项

- 标准深度审计（2026-11-04）确认本特性 `tasks.md` 已 100% 勾选、代码已落地；测试以 INDEX 记录的全绿数为准，**发布前仍建议 CI 跑一次对应服务全量 pytest 对齐计数**。
- 跨特性依赖已在 spec「跨特性关系 / 判定口径补充」节声明（如 036→001/032、037→016/018/036、041→018/034、042→020/008、046→035/042），启用时注意相关特性就绪状态。
