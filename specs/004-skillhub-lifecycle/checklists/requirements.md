# Requirements Quality Checklist: 004 skillhub-lifecycle

**Purpose**: 校验 004（SkillHub 市场与 Skill 生命周期）spec.md 的需求质量——完整性、清晰度、一致性、边界与歧义。这是"需求的单元测试"，**不校验实现是否正确**。
**Created**: 2026-07-08
**Feature**: [spec.md](../spec.md) | [plan.md](../plan.md)

**Review Ownership**: 审阅人专属的需求质量评审工件。仅当审阅人确认某条需求质量准则达标时才标 `[x]`。
**Marker Semantics**: `[x]` 表示"需求质量已审阅且达标"，**不表示**实现完成。
**生成规则**: 本文件由 `/speckit-checklist` 生成，条目不得预先标 `[x]`；`/speckit-implement` 读取勾选态作为门禁且不得修改标记。

## 完整性（Completeness）

- [ ] CHK001 状态机是否完整覆盖所有 Skill 状态（draft / published / unpublished / deprecated / archived）？spec FR 是否穷举生命周期终态？
- [ ] CHK002 ZIP 安装（FR-5）的"结构/签名/版本约束"是否逐一明确定义——"签名"当前代码是否真的存在？若不存在，spec 是否如实写"本期仅结构 + 版本约束，签名后续"？
- [ ] CHK003 安装/更新/分享是否都定义了"失败回滚"语义（半装/半更新的清理要求）？
- [ ] CHK004 启用/停用（FR-6）是否定义"停用后已进行中的调用如何处理"（拒绝/排队/自然结束）？
- [ ] CHK005 按角色授权（FR-6）是否定义授权粒度（角色级 vs 岗位角色级，与 006 的映射关系）？
- [ ] CHK006 审计覆盖（FR-8）是否枚举全部需审计事件（安装/更新/分享/启停/授权/调用/解引用）？

## 清晰度（Clarity）

- [ ] CHK007 "不可变版本快照"（FR-10）是否明确"不可变"的边界（版本号不可改，release notes 是否可补）？
- [ ] CHK008 "组织内分享"（FR-7）是否定义"分享"与"安装"的授权链（分享者需何权限、被分享者如何获得）？
- [ ] CHK009 反馈（FR-4）是否定义反馈的维度（评分/文本/标签）与"与版本关联"的键（哪条 release）？
- [ ] CHK010 "更新 Skill 生成新版本"（FR-7）与 011 自进化产出的"草稿"是否边界清晰（004 更新是人工，011 是自动草稿，二者入口是否分开）？

## 一致性（Consistency）

- [ ] CHK011 spec 与 006（position-rbac）的"角色授权"口径是否一致（004 FR-6 说"按角色授权"，006 是岗位角色模型，二者是否同一"角色"概念）？
- [ ] CHK012 与 001（gatekeeper）"Skill 调用复用权限码模型"是否一致（004 未实现权限码时，Skill 调用授权如何过渡）？
- [ ] CHK013 与 016（skill-market-hardening）"市场强化"边界是否清晰（004 是生命周期基础，016 是灰度/打分/标记，Non-Goals 是否互斥）？
- [ ] CHK014 "digest 去重防重复版本"是否 spec 级要求还是实现细节（spec 是否应只写"版本号唯一"，digest 归 plan）？

## 边界与歧义（Edge cases & Ambiguity）

- [ ] CHK015 ZIP 包内 SKILL.md 缺失/损坏时是否定义明确拒绝（而非静默装空包）？
- [ ] CHK016 zip-slip 防护（`_safe_zip_path`）是否在 spec 中作为安全要求显式声明（而非仅实现细节）？
- [ ] CHK017 同一 Skill 多版本并存时，"当前生效版本"的判定规则（最新发布 vs 指定版本）是否明确？
- [ ] CHK018 分享后源 Skill 删除/下线，已分享的副本是否继续可用（悬空引用处理）？

## Notes

- 本清单为需求质量门禁，全部条目需审阅人逐条评估后勾选；未勾选项构成 `/speckit-implement` 的拦截门禁。
- 标 `[x]` 仅代表"需求质量达标"，不代表实现完成。
- 与 001/006/016 的依赖与边界（CHK011/CHK012/CHK013）建议在 clarify 阶段消解；OQ-1（签名是否存在）须在 clarify 定论后回填 spec。
