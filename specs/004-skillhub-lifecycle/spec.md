# Feature Specification: SkillHub Marketplace & Skill Lifecycle

**Feature Branch**: `004-skillhub-lifecycle`

**Created**: 2026-07-08

**Status**: Draft

**Input**: 回溯固化 MOGO 既有优势能力（规划文档 §1.2"SkillHub 市场 + ZIP 安装、知识闭环与生态分发已成型"）：组织级 Skill 生命周期（草稿→发布→版本回看→反馈）、SkillHub ZIP 安装与包校验、Skill 启用/停用与授权、Skill 更新与分享、以及 Skill 调用进入治理审计。

## User Scenarios & Testing *(mandatory)*

用户故事按优先级排列，每个独立可交付、可测试。

### User Story 1 (P1) — Skill 草稿与发布（组织级生命周期）

管理面可对组织 Skill 进行草稿编辑（initialize/save），草稿带版本号递增与"是否有未发布变更"标记；发布时生成不可变版本快照（digest + 快照 + release notes + 时间戳），版本号唯一约束；可回看历史版本列表（最近 20 条）。

**Acceptance Scenarios:**
- 初始化草稿 → 首次保存 revision=1，has_unpublished_changes=True
- 修改后保存 → revision 递增，digest 与已发布 digest 不一致时标记未发布
- 发布 → 生成新版本号，release 落 organization_skill_releases，skill 切到 published 态
- 同版本号重复发布 → 拒绝（该版本号已存在）
- 发布后改草稿 → 再次标记未发布，不影响已发布快照

### User Story 2 (P1) — Skill 版本回看

管理面可查看某 Skill 的历史版本（最近 20 条），含版本号、发布时间、release notes；回看时不改变当前已发布态。

**Acceptance Scenarios:**
- 列出 releases → 按时间倒序，最多 20 条
- 回看某版本 → 展示该版本快照与 notes
- 无发布历史 → 空态

### User Story 3 (P1) — Skill 反馈收集

管理面可查看 Skill 的调用/使用反馈（organization_skill_feedback），用于质量打分与迭代决策。

**Acceptance Scenarios:**
- 列出 feedback → 返回反馈记录
- 反馈与 Skill 版本可关联

### User Story 4 (P2) — SkillHub ZIP 安装与包校验

用户/Agent 可通过 SkillHub 安装 Skill ZIP 包；包经校验（结构/签名/版本约束）后安装到运行时；校验失败时明确报错，不半装。

**Acceptance Scenarios:**
- 合法 ZIP 包 → 校验通过并安装，运行时可加载
- 缺失必需字段的包 → 校验拒绝，错误定位到具体项
- 版本约束冲突 → 拒绝安装并提示

### User Story 5 (P2) — Skill 启用/停用与授权

组织可对 Skill 进行启用/停用与按角色授权；未授权的岗位角色不可调用该 Skill；启停与授权变更留审计。

**Acceptance Scenarios:**
- 停用某 Skill → 运行时不再提供该 Skill 给 Agent
- 授权岗位角色 → 该角色可调用
- 未授权角色调用 → 拒绝并审计（与特性 001 权限码联动）
- 启停/授权变更 → 写入审计通道

### User Story 6 (P2) — Skill 更新与分享

Skill 可被更新（新 ZIP/新版本）与在组织内分享；更新与分享行为留审计，版本可追溯。

**Acceptance Scenarios:**
- 更新 Skill → 生成新版本，旧版本可回看
- 分享 Skill 到组织内其他成员/租户 → 对方可见可装
- 更新/分享操作 → 审计记录操作者与版本

### Notes / Assumptions
- 本特性为**回溯固化**既有能力，目标是把现有行为写成可验收契约，防止回归
- Skill 生命周期服务：services/admin-api/app/services/skill_lifecycle.py + api/routes/skill_lifecycle.py
- Skill 包校验与安装：services/chat-api/app/enterprise_capabilities/skills/ + skill_packages/validator.py + api/endpoints/skill_package_install.py、skill_shares.py、skill_updates.py
- 组织级存储：MongoDB skills 集合 + organization_skill_releases（digest 去重）
- 版本快照不可变：发布后 release 文档不被修改
- 与特性 001（gatekeeper）联动：Skill 调用的授权/审计复用 001 权限码与审计落点
- 与特性 003（文档交付物）解耦：Skill 是能力单元，文档是数据/产物

## Functional Requirements

- FR-1: Skill 草稿可 initialize/save，revision 递增，标记未发布变更（digest 比对）
- FR-2: 发布生成不可变版本快照（digest + snapshot + release notes + 时间戳），版本号唯一
- FR-3: 历史版本回看（最近 20 条），不改变当前已发布态
- FR-4: Skill 反馈收集与版本关联
- FR-5: SkillHub ZIP 包安装前校验（结构/签名/版本约束），校验失败不半装
- FR-6: Skill 启用/停用 + 按角色授权，未授权不可调用
- FR-7: Skill 更新与组织内分享，版本可追溯
- FR-8: Skill 调用、启停、授权、更新、分享、安装全部进入审计通道
- FR-9: 组织级 Skill 存储于 MongoDB，release 用 digest 去重防重复版本
- FR-10: 已发布快照不可变（发布后 release 文档不被修改）

## Non-Goals
- 不实现 Skill 全生命周期市场强化（版本灰度/回滚/低质量自动标记）——属规划文档 P2 第 12 项"Skill 市场强化"
- 不实现会话→经验→Skill 自动沉淀闭环（Dream Cycle，特性 004 之后范围）
- 不改变 DSH 运行时 Skill 加载语义
- 不实现 Skill 跨租户/跨组织分发（仅组织内）
- 不引入新的 Skill 包格式（仅 ZIP）

## Success Criteria
- Skill 草稿→发布→回看全链路 100% 可追溯，版本号无重复
- ZIP 安装校验失败 100% 报明确错误（不半装、不静默）
- 未授权岗位角色调用 Skill 拒绝率 100%（审计可查）
- 启停/授权/更新/分享操作 100% 进审计
- 已发布快照不可变性 100%（发布后 digest 不变）

## Further Details
- 技术实现（包校验细节、授权模型、审计落点）由 plan.md 承载
- 与特性 001（gatekeeper）的关系：Skill 调用授权与审计复用 001 权限码模型
- 与规划文档 P2 第 12 项的关系：本特性固化现有"SkillHub + ZIP 安装"，市场强化与沉淀闭环为后续独立特性

### 跨特性关系（被依赖方视角，2026-07-08 双向声明）
- **与 011（dream-cycle）**：004 的 Skill 生命周期**以 011 的自进化草稿为上游来源之一**——011 生成的 Skill 草稿进入 004 的草稿态，人工审阅后发布；004 提供草稿/发布/版本契约。
- **与 016（skill-market-hardening）**：004 的版本模型是 **016 市场侧监控/灰度/回滚/低质量标记的基础**——016 在 004 的 Skill/版本契约之上叠加市场强化，不改变 004 的草稿/发布契约（叠加层）。
- **与 018（capability-asset-registration）**：004 的 Skill **可引用 018 注册的能力资产**——018 的资产经 `skill_refs` 与 004 的 Skill 多对多关联（一个资产可被多 Skill 引用），资产化不改变 004 的 Skill 契约。
