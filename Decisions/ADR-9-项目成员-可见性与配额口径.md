# ADR-9: 项目成员——可见性与配额口径

**Date**: 2026-11-05
**Status**: Accepted
**Deciders**: 用户（2026-11-05 会话拍板）

## Context

046（ADR-8）把三套"项目"收敛成 `projects` 一张表，项目 = 工作目录，**纯个人、无成员**（D1），并废弃 042 `quota_projects` 的成员内嵌数组（FR-012：`scope_id = project_id`）。执行后留下两处残留：

1. admin「项目管理」读路径停留在 `quota_projects`（0 行），页面恒空。
2. 项目层配额成员来源 = "项目内产生过会话的用户"（046 T030），无法表达"只有这几个人是成员"。

2026-11-05 用户报障"admin 项目管理无数据"，并追加需求：给项目加成员（user-web「…」菜单、`end_users` + 部门过滤、多选）。

## Decision

1. **成员语义**（本 ADR 的核心）：
   - `projects` 新增可选字段 `member_user_ids: [str]`（FR-001）。
   - **可见性**：`GET /projects` 返回"我的 ∪ 我作为成员的"（FR-003）；046 D1 的"纯个人"就此扩展为"个人 + 可协作"。
   - **配额口径**：项目层 = 该项目 `member_user_ids ∪ 创建者` 的会话用量合计（FR-006），恢复 042"成员"语义但成员来源换成 `projects.member_user_ids`；创建者兜底**取计算不落库**（OQ-4）。
2. **`quota_projects` 退役**：读路径 0 命中（SC-005），写端点（admin `POST/PUT/DELETE /traffic-allocations/projects`）下线；表不删（0 行）、不迁移。
3. **成员管理权**：仅创建者可写（403 兜底）；默认项目（`_id = "default"`）拒绝成员变更（400，与不可归档/删除同级）。
4. **候选端点**：chat-api `GET /api/v1/projects/member-candidates?department_id=`（OQ-1：user-web 无 admin token，不能走 admin-api 的 `/directory/users`）。

## Consequences

- 046 FR-012"成员内嵌数组下线"**继续成立**——新成员语义落在 `projects`，与旧 `quota_projects` 表无关。
- 双服务 `quota_policy.py` 必须同步改成员来源（047 T022 一致性测试锁死，049 T019 加成员用例）。
- 项目层 deleted 判断从 `quota_projects.status` 改为 `projects.status == "archived"`（归档项目不参与取小，046 US2 语义保留）。
- 历史遗留：挂 P 下但非成员的会话（迁移期）的用量**不计入** P 的项目层配额（非成员不受 P 约束）——见 US2 验收 1。

## Implementation notes（2026-11-05 22:10 严格收口后）

- **写端点**：决策 2 的「下线」最终落地为**删除路由**（FR-007 括号内「实现取下线」）。中途曾保留 410 Gone 壳作为退让，22:10 按用户「按 spec 严格收口」拍板把 `POST` / `PUT` / `DELETE /traffic-allocations/projects` 三个路由与 handler 连同无引用的 `ProjectPayload` 一并删除；`test_quota_projects.py` 改为断言「三个写路由不再注册 + gone handler 不存在」。`PUT/DELETE /projects/{id}/policy` 保留（决策 2 只下线项目实体写端点）。前端 3 个写函数与调用点同批清除。
- **默认项目可见性**：决策 1 的「我的 ∪ 我作为成员的」在实现里额外纳入 `{_id: "default"}`，属**已批准豁免**，见下节。
- **成员上限**：`MAX_PROJECT_MEMBERS = 500`（FR-001）；实现初版曾写 1000，收尾时已对齐。
- **双服务一致性**：`services/admin-api/tests/test_quota_consistency.py` 除静态源码比对外，新增 4 例运行时对拍——同 fixture 分别驱动两侧 `get_quota_summary`，逐字段比对 project 层 `total/used/remaining` 并捕获 `sum_usage(user_ids=...)`；变异验证确认口径偏差会令用例失败。

## 豁免与严格收口（2026-11-05 用户拍板）

用户选择「按 spec 严格收口」，四处偏差的处置结果：

| 偏差 | 处置 |
|---|---|
| D-1 写端点保留 410 Gone | **已收口**：删路由 + 删 `ProjectPayload` + 改测试断言 |
| D-3 `tenant_purge.py` 保留旧表清理项 | **已收口**：从租户清理集合清单移除 `"quota_projects"`（表壳保留不删，符合 Edge Cases 第 5 条），只留说明性注释 |
| D-4 T019 只做静态源码比对 | **已收口**：补运行时 fixture 对拍 + 变异自检 |
| D-2 默认项目按租户共享兜底 | **已批准豁免，保留实现**（唯一剩余偏差） |

**D-2 豁免理由**：FR-003 要求「每人自己的默认项目，不做 ∪」，但 046 遗留的 `pg_compat` 把 `id` 设为全局主键，同租户第二个用户 upsert `"default"` 会触发 `ON CONFLICT DO NOTHING` 而拿不到自己的行；实现把 `{_id: "default"}` 纳入 `$or`，让租户内所有用户都能看到这一条兜底行。改主键/DDL 会影响 046 数据面、超出 049 范围，故保留实现并在 `spec.md` FR-003 实现注、本 ADR、`tasks.md` 偏差处理节三处登记。**后续若要把默认项目改回每人一条，需单独立项处理主键。**

完整验收证据见 `specs/049-project-members/tasks.md` 文末。

## Alternatives considered

- **成员只做可见性、配额仍按"项目内全部会话用户"计**：用户明确否掉（"配额应该是项目下所有成员的会话用量合计"，2026-11-05）。
- **候选端点放 admin-api**：否——普通员工无 admin 会话，user-web 只会连 chat-api（`/askai-api` 前缀）。
- **创建者兜底落库（写进 `member_user_ids`）**：否——FR-001 定义"创建者不落此字段"，落库会在创建者被"移除"时产生歧义（id 既在数组又是创建者）。
