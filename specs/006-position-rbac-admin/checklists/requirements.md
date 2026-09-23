# Requirements Quality Checklist: 006 position-rbac-admin

**Purpose**: 校验 006（组织/用户/岗位角色 RBAC 管理）spec.md 的需求质量——完整性、清晰度、一致性、边界与歧义。这是"需求的单元测试"，**不校验实现是否正确**。
**Created**: 2026-07-08
**Feature**: [spec.md](../spec.md) | [plan.md](../plan.md)

**Review Ownership**: 审阅人专属的需求质量评审工件。仅当审阅人确认某条需求质量准则达标时才标 `[x]`。
**Marker Semantics**: `[x]` 表示"需求质量已审阅且达标"，**不表示**实现完成。
**生成规则**: 本文件由 `/speckit-checklist` 生成，条目不得预先标 `[x]`；`/speckit-implement` 读取勾选态作为门禁且不得修改标记。

## 完整性（Completeness）

- [ ] CHK001 角色状态是否穷举（enabled / disabled / 内置不可删）？"全能力管理员"内置角色的不可删/不可停是否在 spec 级声明？
- [ ] CHK002 用户-角色绑定（FR-2）是否覆盖"无主角色但有多角色"的合法性（spec 写主角色必须在角色集内，是否意味着至少 1 角色 + 1 主角色）？
- [ ] CHK003 资源访问（FR-5/FR-6）的"all"模式是否定义"all"的实际范围（该租户全部工具/Skill 的快照语义，随资源增减如何变化）？
- [ ] CHK004 能力开关（FR-4）是否枚举当前支持的能力维度（模型/知识/Skill/工具/审计各开关），还是有意留开放？
- [ ] CHK005 审计（FR-8）是否枚举全部需审计事件（create/update/copy/enable/disable/delete/assign/replace/migration）？

## 清晰度（Clarity）

- [ ] CHK006 "能力开关影响用户功能面"（FR-4）是否定义具体影响（哪些管理面/运行面功能被关闭）？
- [ ] CHK007 "复制角色"（FR-1）是否定义复制时资源 ID 列表是否一并复制（toolIds/skillIds 复制 vs 仅配置复制）？
- [ ] CHK008 租户内唯一名（FR-1）的校验范围（创建时/更新时/复制时是否都校验）是否明确？
- [ ] CHK009 "迁移补全 complete_migration"（FR-3）是否定义迁移触发条件与幂等性（重复执行是否安全）？

## 一致性（Consistency）

- [ ] CHK010 与 001（gatekeeper）"岗位角色作为权限码预设组"是否一致（006 的粗粒度模型如何在 001 细粒度权限码下映射，spec 是否声明过渡关系）？
- [ ] CHK011 与 004（skillhub-lifecycle）"角色 Skill 访问面"口径是否一致（004 FR-6 的"按角色授权"是否即 006 的岗位角色模型，"角色"是否同一概念）？
- [ ] CHK012 与 019（harness-elastic）"厚度配置"是否一致（019 的薄/厚是否覆盖 006 的角色能力开关，二者如何叠加）？
- [ ] CHK013 "selected 模式资源 ID 必须存在"（FR-6）与"all 模式随资源增减"的口径是否在 spec 中统一表述（避免"all"被误解为固定集合）？

## 边界与歧义（Edge cases & Ambiguity）

- [ ] CHK014 删除角色时已绑定该角色的用户如何处理（解绑/报错/自动主角色迁移）？spec 是否定义？
- [ ] CHK015 主角色被停用/删除时用户是否失去主角色（需重设）？spec 是否覆盖此边界？
- [ ] CHK016 "全能力管理员"在多租户下是否每租户独立（main_id 维度）？spec 是否声明租户隔离粒度？
- [ ] CHK017 资源 ID 校验（FR-9）引用 external_tools/skills 集合——若资源刚被并发删除，校验失败的语义（拒绝/重试）是否定义？

## Notes

- 本清单为需求质量门禁，全部条目需审阅人逐条评估后勾选；未勾选项构成 `/speckit-implement` 的拦截门禁。
- 标 `[x]` 仅代表"需求质量达标"，不代表实现完成。
- 与 001/004/019 的口径对齐（CHK010/CHK011/CHK012）须在 clarify 阶段统一消解；OQ（权限码联动/能力维度）须 clarify 定论后回填 spec。
