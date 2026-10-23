# Tasks: 统一门户 + 自助申领（037-unified-portal）

**Input**: Design documents from `/specs/037-unified-portal/`

**Prerequisites**: plan.md (required), spec.md (required)

**性质**: **全新特性，代码尚未开工**。本任务清单全部未勾选，按 Phase 0（研究与澄清）→ Phase 1（设计）→ Phase 2（实现）→ Phase 3（验证与接线）推进。

**Tests**: chat-api pytest（`tests/test_portal_requests.py`）；admin-api pytest（`tests/test_portal_admin.py`）；前端 `@vue/compiler-sfc` 单文件编译校验；E2E 脚本覆盖「浏览→申领→审批→开通→调用→回收」。

**Organization**: 任务按 Phase 组织；`[P]` 标记可并行任务；`US1–US5` 对应用户故事。

---

## Phase 0: 研究与澄清

- [ ] T001 读 `services/chat-api/app/core/portal_sso.py` 与 `apps/user-web/src/App.vue` 换票落地逻辑，确认 029 免登链路零改动边界与门户落地视图的挂接点（history.state 清除后落地页可达）
- [ ] T002 读 `services/admin-api/app/api/routes/skills.py`（列表口径 + 低质降权排序）与 `services/admin-api/app/services/capability_assets/registry.py`（`capability_assets` 集合字段），固化目录聚合的字段来源与 active 过滤条件
- [ ] T003 读 `services/admin-api/app/governance/permission_grants.py`（grant/revoke 函数签名、`permission_grants` 集合字段、审计口径），确定 chat-api 侧按契约直写集合的可行性与契约测试方案
- [ ] T004 读 `services/admin-api/app/governance/layers/approval.py:46-145`（decide/consume 分离、防自审、TTL、fail-closed）与 `services/chat-api/app/governance/approval_runtime.py`（内存态 Runtime），确认申领审批复用语义但自带持久状态机的设计
- [ ] T005 与 036（trust-rating，另一代理同步撰写）对齐评级展示字段与 L1 不进目录的软裁剪约定（字段可选、双向不阻塞）；确认 013 `im_gateway.py` 入口对已开通资产的触达路径无需改动

---

## Phase 1: 设计

- [ ] T006 设计 `portal_listings` 文档结构与索引：`{tenant_id, asset_type, asset_key, category, published_by, published_at, unpublished_at?}`，唯一索引 `(tenant_id, asset_type, asset_key)`；明确 chat-api 读 / admin-api 写的职责边界
- [ ] T007 设计 `portal_requests` 申领单状态机：`applied → approved | rejected → granted → revoked | expired`；条件更新（`status` 前置匹配）保证并发审批幂等；终态集合与迁移合法性表
- [ ] T008 设计审批人解析规则：默认资产 owner（动态解析，不缓存——owner 可经 018 转移）→ 回落持 `portal:approve` 的管理员；防自审（requester = owner 时回落管理员）；解析失败 fail-closed
- [ ] T009 设计目录 API 契约：`GET /portal/catalog`（分类/关键词/分页）、`GET /portal/catalog/{asset_type}/{asset_key}`（详情）、`GET /portal/requests/mine`、`POST /portal/requests`；明确租户隔离（end_user 会话）、active+已上架过滤、效果分/评级字段可选
- [ ] T010 设计管理侧 API 契约：`POST /api/portal/listings`（上架）、`DELETE /api/portal/listings/{...}`（下架）、`GET /api/portal/approvals`（待审队列）、`POST /api/portal/approvals/{request_id}/decide`（批准/拒绝）；admin-web 既有鉴权基座
- [ ] T011 设计开通授权码与回收路径：`code = asset:use:<asset_key>`（level=user，写入 `permission_grants`）；回收 = 移除记录；到期 = 扫描或惰性过期（二选一以 T003 勘察结论冻结，默认惰性过期 + 列表标注，YAGNI）；001 门禁 RBAC 层对该码 fail-closed 校验

---

## Phase 2: 实现

- [ ] T012 [P] [US1] 新建 `services/chat-api/app/services/portal/__init__.py` 与 `listings.py`：`portal_listings` 读写 + 目录聚合（join `skills`/`capability_assets` + 016 效果分摘要 + 036 评级可选字段）
- [ ] T013 [P] [US1] 新建 `services/chat-api/app/api/endpoints/portal.py`：目录列表/分类/搜索/详情端点（end_user 会话鉴权，租户隔离），接入 chat-api 既有路由聚合
- [ ] T014 [P] [US2] 新建 `services/chat-api/app/services/portal/requests.py`：申领单状态机（issue/decide/consume-grant/revoke/expire），条件更新幂等 + 防自审 + 审计事件（T007/T008 设计落地）
- [ ] T015 [US2] `portal.py` 增申领端点：`POST /portal/requests`（重复申领幂等返回已开通）、`GET /portal/requests/mine`（状态列表）；审批人解析挂接 T008 规则
- [ ] T016 [US2] 开通接线：审批通过 → 按 `permission_grants` 字段契约写用户级授权（`asset:use:<asset_key>`）；回收/到期 → 移除记录；操作留 022 审计（失败不阻断）
- [ ] T017 [P] [US4] 新建 `services/admin-api/app/api/routes/portal_admin.py`：上架/下架端点（owner 或管理员，即时生效）+ 审批队列与批准/拒绝端点（与 chat-api 申领单经共享集合联动，条件更新防并发重复授权）
- [ ] T018 [P] [US3] `requests.py` 增回收与到期：revoke（管理员/owner）+ expire（授权有效期到期，惰性过期 + 列表标注）；均移除授权并留审计
- [ ] T019 [P] [US1] `apps/user-web/src/api/portal.ts`：门户 API 客户端（`createApiClient` 基座，Bearer 拦截器复用）
- [ ] T020 [P] [US1] `apps/user-web/src/components/portal/`：新建 `PortalCatalog.vue`（分类/搜索/分页）、`PortalDetail.vue`（详情 + 申领入口 + 已开通态）、`MyRequests.vue`（状态列表/理由/时间线）；在 `App.vue` 以 `defineAsyncComponent` 挂接门户入口（仿 SkillsPage 等既有惰性加载模式）
- [ ] T021 [P] [US4] `apps/admin-web/src/api/portal.ts` + `apps/admin-web/src/views/portal/PortalListingPage.vue`（上架/下架管理）与 `PortalApprovalPage.vue`（待审队列 + 批准/拒绝）
- [ ] T022 [P] [US5] 029 落地接线：确认换票成功后 user-web 启动流可达门户入口（App.vue onMounted 落地逻辑零改动或最小增量）；外部门户侧接入示例文档置 `docs/samples/`（对齐 029 FR-015 口径，不进核心服务代码）
- [ ] T023 [P] [US5] 013 IM 触达验证准备：确认 IM 入口调用已开通资产过 001 门禁/审计的既有路径（无代码改动，仅验证接线）

---

## Phase 3: 验证与接线

- [ ] T024 [P] [US2] 单测（chat-api `tests/test_portal_requests.py`）：状态机全迁移合法性；重复申领幂等；并发双审批仅一次 granted（条件更新）；防自审（requester=owner 回落/拒绝）；审批人解析（owner 动态 + 回落管理员 + 解析失败 fail-closed）
- [ ] T025 [P] [US1] 单测：目录过滤——未上架/非 active/已下架不返回；租户隔离（A 租户员工看不到 B 租户资产）；036 L1 软裁剪（036 桩启用时 L1 不进目录、未启用时全量）
- [ ] T026 [P] [US2] 契约测试（admin-api `tests/test_portal_admin.py`）：chat-api 写入的授权文档字段与 `permission_grants.py` 解析兼容（开通后 001 RBAC 层认可、回收后不再解析）；防跨服务字段漂移
- [ ] T027 [P] [US4] 单测/API 测试：上架即时生效（列表立即可见）、下架即时生效（不可见 + 不可新申领 + 存量授权保留）；审计事件齐全
- [ ] T028 [US2] E2E 脚本：浏览 → 申领 → 审批 → 开通 → 调用（user-web）；回收 → 再次调用被 001 门禁拒绝（fail-closed）；全链路审计可回查
- [ ] T029 [US5] E2E 脚本：029 门户后端服务令牌签票 → user-web 换票 → 落地门户目录（无二次登录）；013 IM @bot 使用已开通资产成功、未开通被拒
- [ ] T030 [P] [US1] 前端校验：`@vue/compiler-sfc` 编译 `PortalCatalog.vue`/`PortalDetail.vue`/`MyRequests.vue` 与 admin-web 两个门户视图通过；手动核对空态/已开通态/分页
- [ ] T031 收尾：三件套文档状态同步（spec/plan/tasks）；按既有纪律 `git add` 具体文件提交（**不更新 specs/INDEX.md**，由索引负责人统一登记）

---

## Dependencies & Execution Order

- Phase 0（T001–T005）全部完成前不进入 Phase 1 设计冻结；T005 与 036 的软裁剪约定不阻塞任何实现任务（桩/开关兜底）。
- Phase 1 内部：T006/T007 是 T012/T014 的前置；T008 是 T015/T024 的前置；T009 是 T013/T015 的前置；T011 是 T016/T026 的前置。
- Phase 2 内部：T012/T013（目录）与 T014/T015/T016（申领开通）是后端主干，先后完成；T017/T018（管理侧/回收）可与前端并行；T019–T021（前端）依赖对应 API 契约冻结；T022/T023（入口接线）依赖 T013/T015。
- Phase 3：T024–T027 随实现完成即跑；T028/T029 E2E 依赖 US1/US2 全链路就绪；T030 前端校验与后端并行；T031 收尾最后执行。
- US1（目录）与 US2（申领开通）是特性主干，优先交付；US3（回收/到期）与其共享状态机；US4（管理侧）保障供给与审批吞吐；US5（入口）为接线验证。

## Notes

- 跨服务协作的唯一约定面是两个集合的字段契约（`portal_listings`/`portal_requests`）与 `permission_grants` 写入口径——三者都必须有测试锁定（T024–T026），这是本特性最主要的漂移风险点。
- 授权过期默认**惰性过期**（读取时判定 + 列表标注），不新增定时扫描任务——YAGNI；若租户强要求实时回收语义，后续可在既有扫描器模式上加任务（与 036 降级扫描器同样板）。
- 防自审与并发幂等是申领单状态机的两条红线：前者沿用 001「审批与消费分离」的审计教训（`approval.py` 模块 docstring），后者靠 MongoDB 条件更新（`status` 前置匹配 + `modified_count==1`），不引入分布式锁。
- user-web 门户页严格走既有模式：`api/portal.ts` 用 `createApiClient`、页面用 `defineAsyncComponent` 惰性加载、文案走 `t()` 中文 key 回退——不引入新状态管理/新组件库。
- ADR-7 边界在实现期的体现：user-web 响应式适配即可（不建独立移动站）；`components/portal/` 内不做任何 IM 协议代码；移动触达验证只走 013 既有入口。
