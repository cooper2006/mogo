# Requirements Quality Checklist: 049 project-members

**Purpose**: 校验 049（项目成员与项目层配额收口）spec.md 的需求质量——完整性、清晰度、一致性、边界与歧义。
**Created**: 2026-11-05
**Feature**: [spec.md](../spec.md) | [plan.md](../plan.md)

**Review Ownership**: 审阅人专属的需求质量评审工件。
**Marker Semantics**: `[x]` 表示"需求质量已审阅且达标"，**不表示**实现完成。

## 一、完整性

- [x] CHK001 读路径修复是否有独立验收？→ SC-001（2 条 `projects` 行在 admin 页可见）
- [x] CHK002 成员可见性是否有独立验收？→ SC-002（成员 B 的 `GET /projects` 含 P；非成员 C 不含 P）
- [x] CHK003 配额口径是否有独立验收？→ SC-003（成员用量合计命中限额被拒，非成员不受约束）
- [x] CHK004 跨服务一致性是否有验收？→ SC-004（双服务一致性测试加成员用例）
- [x] CHK005 `quota_projects` 退役是否有验收？→ SC-005（grep `services/` 读路径 0 命中）

## 二、清晰度

- [x] CHK006 成员字段的约束是否明确？→ FR-001：去重、上限 500、创建者不落此字段
- [x] CHK007 成员写权限是否明确？→ FR-002：仅创建者可写（`user_id = me`），非创建者 403，默认项目 400
- [x] CHK008 可见性过滤条件是否可执行？→ FR-003：`user_id = me OR me ∈ member_user_ids`，默认项目不做 ∪
- [x] CHK009 候选端点的响应字段是否枚举？→ FR-004：`{id, name, mobile, email, loginName, departmentName}`，仅 active 用户
- [x] CHK010 成员弹窗交互是否定义？→ FR-005：部门树 + 用户多选 + 保存；非创建者只读；默认项目不可打开

## 三、一致性

- [x] CHK011 与 046 的关系是否显式？→ 背景表"残留"列 + "与 046 的关系"段落，FR-012 继续成立、成员语义落在 `projects.member_user_ids`
- [x] CHK012 与 042 的边界是否清楚？→ Non-Goals："不改 042 引擎四层取小结构、不改 `scope_type` 枚举"
- [x] CHK013 双服务口径是否锁定？→ FR-006 + Edge Cases 最后一条："chat-api 与 admin-api 两份 `quota_policy.py` 的项目层成员来源必须同口径"
- [x] CHK014 046 D1"纯个人"语义如何扩展？→ Clarify 记录（2026-11-05）："用户主动把产品语义推进到个人 + 可协作"

## 四、边界与歧义

- [x] CHK015 创建者被自己移除后如何？→ Edge Cases 第 1 条："创建者也是成员，`member_user_ids` 可不含创建者；但可见性永远含创建者"
- [x] CHK016 成员账号被禁用/删除后如何？→ Edge Cases 第 2 条："成员列表保留 id；弹窗过滤展示时跳过非 active 用户"
- [x] CHK017 默认项目的成员语义？→ Edge Cases 第 3 条："默认项目拒绝 `member_user_ids` 变更（400）；默认项目配额口径仍为本 (tenant, user) 全部"
- [x] CHK018 PanWeiDB `$elemMatch` 不支持的影响是否预判？→ plan OQ-3："改用两个查询取并集；若 eq 匹配 JSONB 数组元素不支持，回退为拉全租户 active 项目在内存过滤"
- [x] CHK019 `quota_projects` 旧表处置？→ Edge Cases 第 5 条："不删表、不迁移（0 行），只在文档标记退役"

## 结论

19 项全部达标。无未决项阻塞实现。
