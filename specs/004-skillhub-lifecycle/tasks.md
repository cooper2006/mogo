# Tasks: SkillHub Marketplace & Skill Lifecycle

> ⚠️ **落地审计说明**：本特性为回溯固化既有能力，任务条目标记当前落地状态。
> `[x]` 表示已实现；`[ ]` 表示规划中/待补。

**Input**: Design documents from `/specs/004-skillhub-lifecycle/`

**Prerequisites**: plan.md (required), spec.md (required)

**Organization**: 任务按用户故事分组，每组可独立实现与测试。

---

## Phase 1: Foundational — Skill 生命周期基础

**Goal**: 建立 Skill 草稿/发布/版本的核心服务层。

- [x] T001 实现 `SkillLifecycleService`：草稿初始化/保存/发布核心接口
- [x] T002 实现 revision 递增与 digest 比对：保存时 revision+1，比对已发布 digest 标记未发布变更
- [x] T003 实现发布快照生成：digest + snapshot + release_notes + 时间戳，版本号唯一约束
- [x] T004 实现 digest 去重：organization_skill_releases 用 digest 防重复版本
- [x] T005 实现已发布快照不可变：发布后 release 文档不被修改（FR-10）

---

## Phase 2: User Story 1 (P1) — Skill 草稿与发布

**Goal**: 组织级 Skill 草稿编辑→发布→版本快照全链路。

**独立测试**: 初始化→保存→发布；同版本号重复发布→拒绝。

- [x] T006 [P] 实现草稿初始化 API：`initialize` 创建草稿，revision=1
- [x] T007 [P] 实现草稿保存 API：`save` revision 递增，has_unpublished_changes 标记
- [x] T008 [P] 实现发布 API：生成版本快照，版本号唯一约束
- [x] T009 [P] 实现版本号唯一校验：同版本号重复发布拒绝
- [x] T010 单元测试：草稿→保存→发布全链路
- [x] T011 单元测试：重复版本号拒绝

---

## Phase 3: User Story 2 (P1) — Skill 版本回看

**Goal**: 管理面查看历史版本（最近 20 条），不改变当前已发布态。

**独立测试**: 列出 releases→按时间倒序；回看版本→不改变当前态。

- [x] T012 [P] 实现 list_releases API：按时间倒序，limit=20
- [x] T013 [P] 实现 get_release API：回看指定版本快照与 notes
- [x] T014 单元测试：版本列表排序与限制
- [x] T015 单元测试：回看不改变当前已发布态

---

## Phase 4: User Story 3 (P1) — Skill 反馈收集

**Goal**: 管理面查看 Skill 调用/使用反馈，与版本关联。

**独立测试**: 列出 feedback→返回记录；反馈与版本可关联。

- [x] T016 [P] 实现 feedback 存储：organization_skill_feedback 集合
- [x] T017 [P] 实现 list_feedback API：返回反馈记录
- [x] T018 [P] 实现反馈-版本关联：feedback 记录关联 skill version
- [x] T019 单元测试：反馈收集与版本关联

---

## Phase 5: User Story 4 (P2) — SkillHub ZIP 安装与校验

**Goal**: ZIP 包安装前校验（结构/签名/版本约束），校验失败不半装。

**独立测试**: 合法 ZIP→安装；缺失字段→拒绝并定位；版本冲突→拒绝。

- [x] T020 [P] 实现包校验器：结构校验（必需字段/格式）
- [x] T021 [P] 实现签名校验：ZIP 包签名验证
- [x] T022 [P] 实现版本约束校验：版本冲突检测
- [x] T023 [P] 实现安装入口：`skill_package_install` 端点，校验通过后安装
- [x] T024 单元测试：合法包/缺失字段/版本冲突三组校验用例

---

## Phase 6: User Story 5 (P2) — Skill 启停与授权

**Goal**: 组织可对 Skill 启停与按角色授权，未授权不可调用。

**独立测试**: 停用→运行时不提供；授权→可调用；未授权→拒绝并审计。

- [x] T025 [P] 实现 set_enabled API：Skill 启用/停用
- [x] T026 [P] 实现 authorize_role API：按岗位角色授权（006 联动）
- [x] T027 [P] 实现授权检查：未授权角色调用 Skill→拒绝（001 权限码联动）
- [x] T028 [P] 实现启停/授权审计：变更写入审计通道
- [x] T029 单元测试：启停与授权全链路

---

## Phase 7: User Story 6 (P2) — Skill 更新与分享

**Goal**: Skill 可更新与组织内分享，版本可追溯。

**独立测试**: 更新→新版本可回看；分享→对方可见可装；操作→审计记录。

- [x] T030 [P] 实现 Skill 更新：新 ZIP/新版本安装，旧版本可回看
- [x] T031 [P] 实现组织内分享：`skill_shares` 端点，分享后对方可见可装
- [x] T032 [P] 实现更新/分享审计：记录操作者与版本
- [x] T033 单元测试：更新与分享全链路

---

## Phase 8: Cross-Cutting — 治理与安全

- [x] T034 [P] 实现全量审计：Skill 调用/启停/授权/更新/分享/安装全部进审计（FR-8）
- [x] T035 [P] 实现组织级隔离：Skill 存储于 MongoDB，组织间隔离
- [x] T036 [P] 实现运行时加载：chat-api 运行时按授权加载 Skill

---

## Phase 9: Testing & Verification

- [x] T037 草稿→发布→回看全链路 100% 可追溯，版本号无重复（Success Criteria 1）
- [x] T038 ZIP 安装校验失败 100% 报明确错误（Success Criteria 2）
- [x] T039 未授权岗位角色调用 Skill 拒绝率 100%（Success Criteria 3）
- [x] T040 启停/授权/更新/分享操作 100% 进审计（Success Criteria 4）
- [x] T041 已发布快照不可变性 100%（Success Criteria 5）
