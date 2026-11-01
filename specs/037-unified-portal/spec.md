# Feature Specification: 统一门户 + 自助申领（员工侧应用门户：目录 → 申领 → 审批 → 开通即用）

**Feature Branch**: `037-unified-portal`

**Created**: 2026-10-23

**Status**: Draft

**Input**: 整合方案 §4.6「统一门户 + 自助申领」（`docs/MOGO-AgentOS整合方案.md`），形态边界遵循 ADR-7（§六.4 已拍板）

> **设计来源**：本规约落地整合方案 §4.6——员工侧「应用门户」：已上架 Agent/Skill 目录（分类/搜索/详情）→ 自助申领 → 审批流 → 开通即用。解决「智能体上线不等于被使用，员工不会为了用智能体再登录一个新系统」。
>
> **形态边界（ADR-7，必须遵守）**：门户以 **Web 形态**交付；移动触达以 013 多 IM 入口覆盖为主，本特性**不做 H5/App/桌面端**；分发经 029 SSO 接收（外部门户免登进入）与 IM 入口。
>
> **性质说明**：**全新特性，代码尚未开工**（与 031「回溯补规格」本质不同）。tasks.md 全部任务未勾选。

## 定位（一句话）

在 user-web 内新增「应用门户」：员工浏览已上架 Agent/Skill 目录（分类/搜索/详情）→ 自助申领 → 走 001 审批语义的审批流 → 开通即授予对应能力访问权（回收即失效），让已上架资产「找得到、申得到、批得完、用得上」，全程审计。

## 已定决策（2026-10-23，spec 撰写时拍板）

| # | 决策点 | 结论 | 依据 / 论证 |
| --- | --- | --- | --- |
| 1 | 门户承载方 | **user-web 扩展**（既有 SPA 内新增门户页），**不建独立门户服务**。论证：029 SSO 接收方已在 user-web 落地（换票建会话、`localStorage` 写入、多租户挑战流程）；员工侧账号/会话/工作台都已在 user-web；独立门户 = 重复一套鉴权、部署、运维，违反 YAGNI；ADR-7 只约束形态（Web）不约束载体 | 029 `portal_sso.py` + `App.vue` 既有链路；整合方案 §4.6「user-web（或独立门户页）」二选一 |
| 2 | 上架流程 | 上架（publish）= 资产 owner 或管理员**显式动作，上架即发布**（无需二级审批）；下架（unpublish）即时生效；上架/下架留审计。理由：目录数据源已是 016/018 治理后的 active 资产；上架是低风险可见性动作；高风险场景（资产下线）在 018 已有 offline 审批覆盖 | 016/018 治理现状；避免审批冗余 |
| 3 | 申领审批人规则 | 默认 = **资产 owner**；owner 缺失/不可用（离职、角色被转移）时回落持 `portal:approve` 权限码的租户管理员；**不做按部门规则**（首期部门数据不齐，YAGNI）。**防自审**：requester ≠ approver（owner 申领自己的资产时回落管理员审批） | 复用 001「审批与消费分离」防自审教训（`approval.py:46-145`） |
| 4 | 开通的权限语义 | 申领通过 = **自动授权**（开通即用）：写 `permission_grants` 用户级记录（`code = asset:use:<asset_key>`），即时生效；**回收 = 删授权记录，下次调用 fail-closed**。不采用「仅记录待管理员配置」——那不解决「开通即用」的目标 | `permission_grants.py` 明示「grant 即时生效、移除即失效、审计走 gate_events」 |
| 5 | 目录可见范围 | **租户内全员可见**（已上架且 018 active），不按部门裁剪（首期）；**036 L1 实验级资产不进公共目录**（其「仅创建者本人可用」语义优先；036 未启用时无此裁剪） | 整合方案 §4.6；036 spec 跨特性声明 |
| 6 | API 载体 | 终端用户侧 API（目录/申领/我的申领）落 **chat-api**（user-web 走 `/askai-api` 既有基座 + 与 029 换票同域 + end_user 会话鉴权）；管理侧 API（上架/下架/审批队列）落 **admin-api**（admin-web 既有基座 + 管理员鉴权）；两侧经共享 MongoDB 集合协作（沿用 016 quality_metrics 跨服务读写既有模式） | `apps/user-web/src/api/client.ts` 基座；跨服务共享集合为仓库既有模式 |
| 7 | 审批承载 | 申领单用**持久状态机**（`portal_requests` 集合：applied→approved/rejected→granted→revoked/expired），**复用 001 审批语义**（approver/requester 分离、fail-closed、审计）；不把 5min TTL 的门禁票据（`gate_approvals`）用于跨天业务审批——门禁票据面向执行挂起，申领审批是人工业务流 | `approval.py` APPROVAL_TTL_MINUTES=5 面向执行挂起；001 FR-11「不新建第二张审批表」指门禁审批表，申领单是业务单据 |

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 员工浏览门户目录（分类/搜索/详情）(Priority: P1)

员工登录 user-web（含经 029 免登进入）后打开「应用门户」，看到租户内已上架的 Agent/Skill 目录：按分类筛选、关键词搜索、分页浏览；点进详情可见名称、描述、分类、owner、效果分摘要（016）与评级（036 就绪后），并可一键发起申领。

**Why this priority**: 目录是整个特性的入口与「找得到」的兑现——没有目录，申领无从发生。它也直接回应「员工不会为了用智能体再登录一个新系统」：门户就在员工已有的 user-web 里。

**Independent Test**: 预置 3 个已上架 active 资产 + 1 个未上架 + 1 个已下架；员工会话调 `GET /askai-api/api/portal/catalog` → 断言仅返回 3 个；切分类/搜关键词/翻页 → 断言过滤与分页正确；029 签发票据换票进入 → 断言落地后门户目录可达。

**Acceptance Scenarios**:

1. **Given** 租户内有已上架且 018 active 的资产，**When** 员工打开门户目录，**Then** 列表展示这些资产（名称/分类/评级徽标），未上架/非 active/已下架资产不出现。
2. **Given** 目录页，**When** 按分类筛选或输入关键词，**Then** 结果按资产名称/描述/标签匹配，分页参数生效。
3. **Given** 目录某项，**When** 打开详情，**Then** 展示名称/描述/分类/owner/效果分摘要（016），036 就绪后追加评级字段；详情提供「申领」入口。
4. **Given** 该资产已被当前员工开通，**When** 查看详情，**Then** 显示「已开通」状态与使用入口（不重复展示申领按钮）。

---

### User Story 2 - 自助申领 → 审批 → 开通即用全链路 (Priority: P1)

员工对未开通资产点「申领」，填写用途理由提交；系统生成申领单（applied）并按规则路由审批人（资产 owner → 回落管理员）；审批人在 admin-web 审批队列看到待审项，批准后系统自动写授权（开通）并通知员工；员工随即可在 user-web / 013 IM 入口使用该资产，全程零额外配置。拒绝则申领单终态为 rejected 并告知理由。

**Why this priority**: 这是特性核心价值链路（「申得到、批得完、用得上」），也是 P1 验收口径「申领→审批→开通→使用全链路 E2E」的本体。

**Independent Test**: 员工 A 申领资产 X → 断言申领单 applied 且审批人为 X 的 owner；owner 在 admin-web 批准 → 断言 `permission_grants` 出现 `(user=A, code=asset:use:X, level=user)` 且申领单转 granted；员工 A 立即调用资产 X → 成功；回收后再次调用 → 被 001 门禁 RBAC 层拒绝（fail-closed）。

**Acceptance Scenarios**:

1. **Given** 员工未开通某资产，**When** 提交申领（含理由），**Then** 生成申领单 applied，审计事件落链，审批人按决策 #3 解析。
2. **Given** 待审申领单，**When** 审批人（owner 或回落管理员）在 admin-web 批准，**Then** 系统自动写用户级授权、申领单转 granted、通知申请人；申请人下次调用即通过门禁。
3. **Given** 待审申领单，**When** 审批人拒绝（可填理由），**Then** 申领单转 rejected、通知申请人、不产生任何授权。
4. **Given** requester 与审批人是同一人（owner 申领自己的资产），**When** 尝试审批，**Then** 系统按防自审规则拒绝，回落管理员审批。
5. **Given** 同一员工对同一已开通资产再次申领，**When** 提交，**Then** 返回「已开通」幂等结果，不重复授权、不生成第二张有效申领单。

---

### User Story 3 - 我的申领与失效回收 (Priority: P2)

员工在「我的申领」查看全部申领单及状态（applied/approved/rejected/granted/revoked/expired）；管理员或资产 owner 可回收已开通授权（revoked），回收即时生效；租户可配置授权有效期，到期自动失效（expired）。

**Why this priority**: 状态可见 + 可回收是权限收敛闭环的另一半——只开不放会造成权限蔓延。优先级低于开通链路本身，但与其共享状态机，可独立测试。

**Independent Test**: 员工查看我的申领列表与状态流转；管理员回收某授权 → 断言 `permission_grants` 记录被移除且员工下次调用被拒；配置有效期（如 7 天）并用可注入时钟推进 → 断言到期自动 expired 且授权移除。

**Acceptance Scenarios**:

1. **Given** 员工有不同状态的申领单，**When** 打开「我的申领」，**Then** 按状态分组/筛选展示，含审批理由与时间线。
2. **Given** 已开通授权，**When** 管理员/owner 执行回收，**Then** 授权记录移除、申领单标记 revoked、员工下次调用 fail-closed、审计落链。
3. **Given** 授权配置了有效期，**When** 到期，**Then** 授权自动失效（expired）、员工下次调用被拒、审计落链。

---

### User Story 4 - admin-web 上架与审批管理 (Priority: P2)

资产 owner/管理员在 admin-web 对上架资产执行发布/下架（即时生效）；在审批队列查看待审申领单（申请人/资产/理由/审批规则），执行批准/拒绝；上架与审批操作全部留审计。

**Why this priority**: 管理侧是目录供给与审批吞吐的保障。优先级低于员工侧核心链路（US1/US2），但 US2 的审批动作在此落地，需同步交付。

**Independent Test**: admin-web 对上架资产执行下架 → 目录 API 即时不返回；审批队列对 T002 构造的申领单批准/拒绝 → 状态机与授权按预期变化；审计链可查全部操作。

**Acceptance Scenarios**:

1. **Given** 资产为 018 active，**When** owner/管理员执行上架，**Then** 目录即时可见（`portal_listings` 落记录 + 审计）。
2. **Given** 资产已上架，**When** 执行下架，**Then** 目录即时不可见、不可新申领；存量授权保留至显式回收或到期（避免打断进行中的使用）。
3. **Given** 审批队列有待审单，**When** 管理员批准/拒绝，**Then** 与 US2 链路一致（开通/拒绝 + 通知 + 审计）。

---

### User Story 5 - 分发入口接线：029 免登直达与 013 IM 触达 (Priority: P3)

外部门户已登录员工经 029 SSO 免登进入 user-web 后，落地即可见门户入口与目录（029 换票链路零改动）；已开通资产可经 013 多 IM 入口 @bot 使用（IM 侧不建目录 UI，ADR-7：移动触达以 IM 入口覆盖为主）。

**Why this priority**: 分发决定「员工是否真的够得着门户」。依赖 US1/US2 的能力已就绪，属接线验证；P3 因其不改变核心链路、且 029/013 均已生产接线。

**Independent Test**: 门户后端持服务令牌调 `POST /api/auth/portal-ticket` → 前端带票进 user-web 换票 → 断言落地后门户目录可达且无需二次登录；IM 渠道 @bot 触发已开通资产 → 断言执行成功且过 001 门禁/审计。

**Acceptance Scenarios**:

1. **Given** 外部门户用户持有效票据跳转 user-web，**When** 换票建会话完成，**Then** 落地视图含门户入口，目录数据正常返回（无二次登录）。
2. **Given** 员工已开通资产 X，**When** 在 013 任一 IM 渠道 @bot 使用 X，**Then** 执行成功并过 001 门禁/审计；未开通时按无授权拒绝（fail-closed）。
3. **Given** 票据过期/无效，**When** 换票失败，**Then** 回落登录弹窗（029 既有行为），门户不静默卡死。

---

### Edge Cases

- **下架时存量授权**：下架不即时撤销已开通授权（避免打断进行中的使用），但目录不可见、不可新申领；再次上架**不恢复**已回收/已过期的授权（需重新申领）。
- **资产被 018 offline**： offline 资产的待审申领单自动 rejected（reason=asset_offline）；已开通授权记录保留但调用自然被 018 状态门禁拒绝（授权与状态双层收敛）。
- **owner 角色转移（018 FR-11）**：审批人解析动态取当前 owner，不缓存——owner 调岗后新申领单路由到新 owner。
- **并发审批**：两个管理员同时批准同一申领单 → 状态机条件更新（`status: applied` → approved 仅一次 `modified_count==1`），第二个请求返回「已处理」幂等结果，不重复授权。
- **多租户**：目录/申领/授权严格按 end_user 会话的租户隔离；票据跨租户由 029 既有校验拒绝（门户不新开跨租户通道）。
- **申领单洪水**：同一员工对同一资产的重复申领幂等（US2-5）；对不同资产的高频申领不做限流首期（配额属既有 001 层 5 范畴，不重复建设）。
- **效果分/评级字段缺失**：036 未就绪或资产无效果分时，详情页对应区域隐藏而非报错（字段可选，前端容错）。
- **搜索空结果**：搜索无命中时展示空态与「清除筛选」引导，不报错。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: user-web MUST 提供「应用门户」页（目录/详情/我的申领三个视图），承载于既有 user-web SPA；**不做 H5/App/桌面端**（ADR-7）。
- **FR-002**: chat-api MUST 提供门户目录 API（列表/分类/搜索/详情），数据源 = `portal_listings`（上架标记）+ `skills` 集合 + `capability_assets` 集合（016/018 治理数据），按 end_user 会话租户隔离。
- **FR-003**: 目录 MUST 仅返回已上架且 018 状态 active 的资产；上架/下架与状态变更 MUST 即时反映（无缓存延迟）。
- **FR-004**: 资产详情 MUST 包含名称、描述、分类、owner、效果分摘要（016）；036 就绪后 MUST 追加评级字段，036 未就绪时该字段 MUST 可缺席（前端容错）。
- **FR-005**: 登录员工 MUST 能对未开通资产发起自助申领，生成申领单（`portal_requests`：requester/asset/reason/status/applied_at）。
- **FR-006**: 申领单生命周期 MUST 为 `applied → approved | rejected → granted → revoked | expired`，全部状态迁移 MUST 留 022 审计。
- **FR-007**: 申领审批 MUST 复用 001 审批语义：approver ≠ requester（防自审）、fail-closed、审计落链；审批人 = 资产 owner（默认）→ 回落持 `portal:approve` 权限码的管理员；**不做按部门审批规则**（首期）。
- **FR-008**: 审批通过 MUST 自动开通：写 `permission_grants` 用户级授权（`code = asset:use:<asset_key>`），即时生效，开通即用（员工随即可在 user-web / 013 IM 入口使用）。
- **FR-009**: 回收（管理员/owner 撤销或授权到期）MUST 移除对应授权记录，移除后该员工下次调用该资产 MUST 被 001 门禁 RBAC 层拒绝（fail-closed）。
- **FR-010**: 重复申领 MUST 幂等：同一员工对同一已有有效授权的资产再次申领，返回已开通状态，不重复授权、不生成第二张有效申领单。
- **FR-011**: admin-api MUST 提供上架/下架 API，操作者 = 资产 owner 或管理员，即时生效，留审计。
- **FR-012**: admin-web MUST 提供上架管理视图与待审审批队列（含批准/拒绝与理由），审批决策与 chat-api 申领单状态机经共享集合联动。
- **FR-013**: 目录可见范围 MUST 为租户内全员（已上架 active），不按部门裁剪；036 L1 实验级资产 MUST 不进公共目录（036 启用时）。
- **FR-014**: 029 SSO 免登用户 MUST 可直接到达门户：换票建会话后落地视图含门户入口；029 端点链路（`portal-ticket`/`portal-exchange`）零改动。
- **FR-015**: 013 IM 入口 MUST 可触达已开通资产（@bot 使用，过 001 门禁/审计）；IM 侧 MUST NOT 建目录 UI（ADR-7）。
- **FR-016**: 员工 MUST 可查看「我的申领」列表与状态（applied/approved/rejected/granted/revoked/expired）及审批理由。
- **FR-017**: 申领审批与开通/回收 MUST 全链路审计（申请人/审批人/资产/理由/时间/结果），审计失败不阻断主流程（对齐 `registry.py` audit 容错写法）。

### Key Entities

- **PortalListing**：`{tenant_id, asset_type, asset_key, category, published_by, published_at, unpublished_at?}`，`portal_listings` 集合的一行——上架标记与分类；chat-api 读、admin-api 写。
- **PortalRequest**：`{tenant_id, request_id, requester_id, asset_type, asset_key, reason, status, approver_id, decided_at, decided_reason, granted_at, expires_at?, revoked_at, applied_at}`，`portal_requests` 集合的一行——申领单生命周期。
- **AssetUseGrant**：`permission_grants` 集合中的用户级授权文档（`level=user`、`code=asset:use:<asset_key>`），开通即写、回收即删（复用 001 授权机制，不新建授权表）。
- **CatalogItem**：目录聚合视图 = 资产基础字段（`skills` / `capability_assets`）+ `PortalListing` 分类 + 016 效果分摘要 + 036 评级（可选），只读投影，不落库。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 员工从「浏览目录 → 申领 → 审批 → 开通 → 调用」全链路 E2E 跑通，开通后**零额外配置**即可使用（user-web 与 013 IM 入口双验证）。
- **SC-002**: 回收后该员工下次调用被 001 门禁拒绝（fail-closed），授权移除即时生效（`permission_grants` 无缓存语义，下—次调用即验）。
- **SC-003**: 申领/审批/开通/回收/上架/下架操作 100% 有 022 审计事件可回查。
- **SC-004**: 029 SSO 免登用户进入 user-web 即可见门户目录（全程无二次登录）。
- **SC-005**: 未上架/非 active/已下架资产在目录 API 与 UI 均不出现（双重验证，含竞态：上架与列表并发）。
- **SC-006**: 防自审生效：requester = owner 时无法自审（回落管理员），并发双审批仅一次生效。

## Assumptions

- user-web 既有 axios 基座（`apps/user-web/src/api/client.ts`，`/askai-api/api` + Bearer token from `localStorage`）可直接承载门户 API 客户端，不改鉴权中间件。
- `permission_grants` 的「即时生效 / 移除即失效 / 审计走 gate_events」语义（`permission_grants.py` 模块文档）为开通/回收的权限机制；`asset:use:<asset_key>` 注册为 001 权限码模型的 `asset` resource 维度（沿用 001「下游特性注册 resource」扩展点）。
- 016/018 数据可读：技能列表（`skills.py` 列表路径，含低质降权排序）与 `capability_assets` 集合提供目录基础数据；效果分摘要取 016 现成聚合。
- 001 审批语义（`approval.py` decide/consume 分离、防自审、fail-closed）可复用于申领审批的业务状态机；chat-api `ApprovalRuntime`（`approval_runtime.py`）为内存态，不适合跨天业务审批，故申领单持久化。
- 029 票据链路（`portal_sso.py` 60s TTL、accept-once、跨租户拒绝）已生产接线，门户只增量落地视图、不改端点。
- 013 多 IM 入口（`im_gateway.py` webhook + 持久化绑定）已生产接线；门户不触碰 IM 协议与消息格式。
- 036 未就绪时目录不展示评级（字段可选）；036 就绪后 L1 资产按 FR-013 退出公共目录（软依赖，双向不阻塞）。

## 跨特性关系（被依赖方视角，2026-10-23 双向声明）

- **与 029（user-web-sso-receiver）**：037 消费 029 的 SSO 接收链路作为**分发通道**（外部门户免登进入直达门户）；037 不改 029 端点（`portal-ticket`/`portal-exchange`）与票据语义；029 不依赖 037。
- **与 001（gatekeeper-governance）**：037 消费 001 的审批语义（approver/requester 分离、fail-closed、审计落 `gate_events`）与 RBAC 权限码（开通授权经门禁校验生效）；037 不新建第二张门禁审批表、不改 25 格矩阵；001 不依赖 037。
- **与 016（skill-market-hardening）/ 018（capability-asset-registration）**：037 消费其市场与资产数据（`skills` 集合列表口径 + `capability_assets` 集合 + 018 active 状态）作为目录数据源；目录过滤不改变 016/018 的写路径；016/018 不依赖 037。
- **与 013（multi-im-entry）**：037 已开通资产经 013 IM 入口 @bot 使用（移动触达答案，ADR-7）；037 不碰 IM 协议、不在 IM 侧建目录 UI；013 不依赖 037。
- **与 036（trust-rating，同步撰写中）**：037 目录详情消费 036 评级展示；036 L1 资产按 FR-013 不进公共目录；两特性互不阻塞（字段可选 + 软裁剪，036 未启用时门户全功能可用）。
- **与 ADR-7（形态边界）**：门户以 Web 形态交付于 user-web；移动/桌面触达回到 ADR-7 既有结论（013 IM 覆盖为主，不做 H5/App/桌面端新建）。

## 判定口径补充（2026-10-24，/speckit-checklist 回填）

- **R-1 过期是惰性触发，无后台调度器**：`expire_stale_grants(db, *, tenant_id="", now=None)` 在**列表/详情读取路径**被调用，把 `expires_at` 已到的 `granted` 单转 `expired` 并删除对应 `permission_grants` 记录；不引入定时任务（避免新依赖）。因此"到期失效"在**下一次读取时**生效，未读取期间授权仍可用——这是已接受的取舍。
- **R-2 申领单与授权的过期同源**：`portal_requests.expires_at` 与 `permission_grants.expires_at` 由**同一次开通**写入（`_expires_at(granted_at, ttl_days)`），TTL 取自租户设置 `portal_settings.grant_ttl_days`（缺省 `DEFAULT_GRANT_TTL_DAYS = 0` = 不过期）。惰性过期**同时**改状态与删授权，不会出现"单已 expired 但仍有授权"。
- **R-3 "owner 不可用"判据**：`resolve_approver()` **动态读、不缓存**——`owner` 解析不到（为空）或等于申请人时跳过 owner，回落 `_appointable_admins()`（`admin_accounts` 中 `tenant_id` 匹配且 `status == "active"`，且 `role_name ∈ ALL_CODES_ROLES = {"平台管理员","超级管理员","full_access_admin"}` 或 `code_satisfies(permission_codes, "portal:approve")` 的记录，按 `username` 稳定排序取首个）。**不做离职标记判断**——只要账号仍 active 就视为可用，离职靠管理员停用账号体现。
- **R-4 无审批人可回落时 fail-closed 拒单**：`resolve_approver()` 解析不到时返回空串，`issue_request()` **直接拒单**（不挂起、不生成无审批人的申领单）。
- **R-5 `portal:approve` 授予面**：权限码存于 `admin_accounts.permission_codes`；`ALL_CODES_ROLES` 三个全权限角色名**默认拥有**该能力，其他管理员须显式授予 `portal:approve`。权限码匹配用 `code_satisfies()`（与 001 `has_permission` 同口径：`*` 全通配、`portal:*` 前缀通配、精确匹配）。
- **R-6 "即时反映"判据**：目录查询**每次直读 MongoDB**（`portal_listings` 的 `_ACTIVE_LISTING_FILTER = {"$or": [{"unpublished_at": None}, {"unpublished_at": {"$exists": False}}]}`），无应用层缓存；**允许**浏览器/网关级短缓存，前端提供手动刷新。判据 = 下架后重新请求即不可见，不要求毫秒级推送。
- **R-7 效果分摘要字段**：目录/详情从 `skill_quality_metrics` 取摘要，含效果分与样本量（`_effect_summary_from_rows`），无数据时该字段为 `null`（前端显示"—"，不填 0）；不展示置信区间。
- **R-8 036 就绪判据**：不设显式开关——**能否读到 `trust_ratings` 记录**即为就绪判据：有记录则追加 `rating` 摘要并按 `_is_l1_asset()` 把 L1 资产排除出公共目录；无记录（集合空/不可读）则字段缺席、不做 L1 裁剪。因此 036 上线并产生评级记录后自动生效。
- **R-9 重复申领与历史单**：幂等仅在"已有 **granted 且未过期** 授权"时返回已开通状态（不建新单）；`rejected` / `revoked` / `expired` 之后**允许再次申领**并生成**新单**，历史单保留可查（`我的申领` 按时间倒序展示）。
- **R-10 回收后重新申领**：回收（`revoke_asset_use`）即删除授权记录，**不设冷却期**；重新申领走正常审批流（同一审批人规则、仍防自审）。
- **R-11 授权码与 001 RBAC 的兼容**：开通写 `permission_grants`，`code = asset:use:<asset_key>`（`build_asset_use_code()`）；该 code 是**新增命名空间**，与既有权限码并存，走同一 `code_satisfies()` 匹配（支持 `*` / `asset:*` 通配），不需要在权限码注册表预登记。
- **R-12 上架/下架操作者判据同源**：admin-api 侧与 chat-api 侧**共用同一 owner 解析口径**（`_asset_owner`：skill/workflow 取 `skills` 的 owner 字段、agent 取能力资产 owner；解析不到时仅管理员可操作），避免"能上架不能审批"。
- **R-13 效果分读取方式**：目录详情**实时读** `skill_quality_metrics`（跨服务共享集合，chat-api 直读），不取快照、不复制数据；允许最终一致（016 写入后最多一次查询间隔的延迟）。
- **R-14 审计落点（双集合，按服务归属）**：chat-api 侧门户动作（申领/审批/开通/回收/过期）写 `gate_events`（`layer="portal"`、`tool="portal.<action>"`、`event_id`/`occurred_at`/`detail` 与 001 同构）；admin-api 侧上架/下架写 022 审计链（`record_management_operation`）。**完整链路回溯** = 以 `tenant_id + asset_key + 时间窗` 联合查询两个集合，首期不建统一视图。
- **R-15 FR-014 "零改动"范围**：指 **chat-api 的 `portal-ticket` / `portal-exchange` 端点链路与换票协议零改动**；user-web 侧允许新增门户页、路由与入口（属 037 自身交付），SSO 换票成功后的落地视图由 037 追加门户入口，不修改 029 的接口契约。

## Non-Goals

- 不做 H5/App/桌面端门户（ADR-7 已拍板，移动触达以 013 IM 入口覆盖）。
- 不做可视化编排画布、连接器市场（整合方案 4.8/4.10，另行立项）。
- 不做按部门/按角色的目录可见性裁剪（首期仅租户内全员 + L1 软裁剪）。
- 不新建第二套审批表/授权体系（复用 001 审批语义与 `permission_grants`）。
- 不做跨租户资产市场（延续 018 Non-Goal：资产在租户内）。
- 不做 IM 侧目录 UI 与消息内申领交互（申领审批走 Web 管理端）。
- 不实现评测、上架质量门禁（属 032/016 范畴；上架即发布的论证见决策 #2）。
