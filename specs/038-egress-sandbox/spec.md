# Feature Specification: 出站白名单与沙箱隔离强化（Egress Allowlist & Sandbox Isolation）

**Feature Branch**: `038-egress-sandbox`

**Created**: 2026-10-23

**Status**: Draft

**Input**: 整合方案（`docs/MOGO-AgentOS整合方案.md`）§4.7（P1，Wave 2）与 §2.3 防线③：HTTP 工具/浏览器 Agent 的出站域名白名单（按租户/工具配置，默认拒绝 + 审计）；把脚本沙箱已有"网络默认拒绝"语义提升为全出站路径统一管控；远程沙箱只保留契约与接口预留，不实现本体。

> **设计来源**：本特性为**全新特性**（代码尚未开工）。设计细节以整合方案 §4.7 / §2.3 防线③为准，本文件在其上补充落地口径；冲突时以本 spec 的 FR 与已定决策表为准。

> **性质说明**：与 031 的"回溯补规格"本质不同——本特性代码零落地，tasks.md 全部任务未勾选（`- [ ]`）。

## 定位（一句话）

补齐治理防线③的"沙箱隔离 + 出站白名单"：把脚本沙箱（`services/chat-api/app/enterprise_capabilities/data/script_engine/executor.py`：子进程 `python -I` 隔离 + rlimit 资源限额 + L572-576 网络默认拒绝 `socket.socket = _deny_network`）的"网络默认拒绝"语义，提升为 **HTTP 工具与浏览器 Agent 两条出站路径的统一白名单管控**（按平台/租户/工具三层配置，默认拒绝 + 命中/拒绝审计 + 配置热更新）；远程沙箱（`services/chat-api/app/dsh_runtime/contracts/kernel.py:63` 的 `remote_sandbox` 已是契约枚举值但无实现）本特性只做契约保留与接口预留，不实现本体。

## 已定决策（2026-10-23，立项拍板）

| # | 决策点 | 结论 | 落点 |
| --- | --- | --- | --- |
| 1 | 白名单匹配粒度 | **域名后缀匹配**（条目 `example.com` 覆盖其全部子域，如 `api.example.com`）+ **可选路径前缀**（如 `example.com/v1/`）；不做单 URL 精确匹配、不做通配符正则（YAGNI） | `egress_guard` 匹配器 |
| 2 | 默认策略 | **默认拒绝**（与脚本沙箱 `socket.socket = _deny_network` 语义一致）；白名单为空、判定异常、存储不可用一律按拒绝处理（fail-closed），**不可配置为放行** | `EgressGuard.check` |
| 3 | 生效层级 | **平台默认 + 租户覆盖 + 工具例外三层，并集语义**（任一层命中即放行；工具级条目仅对绑定的工具生效）；不提供"豁免白名单"总开关（否则破坏默认拒绝底线） | `egress_allowlist` 集合 |
| 4 | 浏览器 Agent 管控面 | 首期管控**顶层导航目标 URL** 与**重定向最终落地 URL**（以落地域判定）；页面子资源（图片/CSS/JS 等）不逐项管控，仅在审计记录最终落地域（浏览器 Agent 功能依赖页面资源加载，子资源域不可枚举） | `browser_task` 入口 + navigate action contract |
| 5 | 远程沙箱边界 | **只留契约，不实现本体**：保留 `kernel.py:63` 的 `execution_location: "remote_sandbox"` 枚举与参数结构，预留错误码占位；远程执行进程管理/镜像/网络本体列入 Non-Goals | `contracts/kernel.py`（不改动） |
| 6 | 出站检查的落地形态 | 复用 **009 PreToolUse 求值链的同一执行点**（`tools/service.py:489-494` 真实工具调用点）落地出站检查，与 deny/require 规则同链 fail-closed；**不新增 rule_type 枚举值**（避免扩散 009 FR-11"未知 rule_type fail-closed"语义），白名单配置存独立集合而非 `hook_rules` | `tools/service.py` 求值点内联 |
| 7 | 非 http(s) scheme 与 IP 字面量 | 白名单只表达域名；`data:`/`javascript:` 等非 http(s) scheme 与 IP 字面量（含内网/回环/链路本地地址）**一律拒绝**——出站白名单同时是 SSRF 防护的执行机制 | `EgressGuard` 前置校验 |

## User Scenarios & Testing *(mandatory)*

### User Story 1 - HTTP 工具出站调用过白名单，未命中即拒且审计可查（Priority: P1）

Agent 调用 HTTP/MCP 工具时，系统在真实工具执行前（009 PreToolUse 同一求值点）对工具的出站域名做白名单判定：命中任一上层级条目则放行进入原有执行链（`external_tools.execute_runtime`），未命中则拒绝调用并写入审计（租户/工具/域名/拒绝原因）。管理员无需改代码，只在白名单配置里加一行即可放行新域名。

**Why this priority**: 这是治理防线③"出站白名单"的主路径——HTTP 工具是 Agent 出网的最高频出口，当前无任何管控（整合方案 §2.3 明示"HTTP 工具/浏览器 Agent 无出站管控"）。US1 构成可交付 MVP：一条路径 + 拒绝 + 审计。

**Independent Test**: 配置一条白名单条目（域名后缀 + 可选路径前缀），用测试工具走 `execute_runtime`：命中域名放行、未命中拒绝；直接对拒绝路径断言审计事件含 `egress.denied` 与完整字段。全程不启动真实外部服务（用 mock HTTP 响应）。

**Acceptance Scenarios**:

1. **Given** 白名单含 `example.com` 且工具出站 URL 为 `https://api.example.com/v1/data`，**When** Agent 调用该工具，**Then** 判定命中（后缀覆盖子域），工具进入原有执行链，审计记录 `egress.allowed`。
2. **Given** 白名单不含 `evil.com`，**When** 工具出站 URL 为 `https://evil.com/steal`，**Then** 调用在执行前被拒（错误提示与门禁/钩子拒绝可区分），审计记录 `egress.denied`（含 tenant_id/tool_id/domain/reason），且真实 HTTP 请求未发出。
3. **Given** 白名单条目为 `example.com/v1/`（带路径前缀），**When** 工具出站 URL 为 `https://example.com/v2/data`，**Then** 路径前缀不命中，调用被拒。
4. **Given** 工具出站 URL 为 `https://127.0.0.1:8080/admin` 或 `data:text/html,...`，**When** 执行判定，**Then** 无需查白名单即拒绝（IP 字面量/非 http(s) scheme 前置拒绝），审计记录原因。

---

### User Story 2 - 白名单配置三层管理与热更新（Priority: P1）

平台管理员在 admin-web「出站白名单」页维护平台默认条目（随种子提供模型 provider 官方域等）；租户管理员维护本租户条目；工具编辑页可为单个工具配置工具级例外条目。保存后**下一调用即按新配置求值**（不重启服务），与 009 FR-4"规则变更即时生效"口径一致。

**Why this priority**: 没有配置入口，US1 的白名单只能靠种子数据，租户无法自助放行自己的业务域名——管控会因不可运营而沦为"全线拒绝"。配置与热更新是白名单可用的前提，与 US1 同为 P1。

**Independent Test**: admin-api 对 `/api/egress/allowlist` 走 CRUD（列表/新增/改/删，仿 hooks 路由信封口径）；保存后不重启，立即用 US1 的测试工具复测判定结果随配置变化；断言租户隔离（租户 A 看不到/改不到租户 B 与平台条目）。

**Acceptance Scenarios**:

1. **Given** 平台默认白名单为空且租户白名单为空，**When** 任意工具出站，**Then** 一律拒绝（默认拒绝底线）。
2. **Given** 管理员新增租户级条目 `api.partner.com` 并保存，**When** 立即（不重启）发起该域出站调用，**Then** 命中放行。
3. **Given** 租户管理员尝试修改平台级条目或其他租户条目，**When** 提交请求，**Then** 被权限拒绝（平台条目仅平台管理员可维护）。
4. **Given** 某工具绑定了工具级例外条目 `internal.corp.example`，**When** 该工具出站该域，**Then** 放行；而另一未绑定工具出站同一域，**Then** 仍拒绝（工具级条目仅对绑定工具生效）。

---

### User Story 3 - 浏览器 Agent 导航过白名单，与 HTTP 工具行为一致（Priority: P1）

浏览器 Agent 执行任务前（`browser_task` 入口）对 `target_url` 过同一白名单机制：未命中拒绝执行；任务执行后回收的最终落地 URL（navigate action contract 的 `final_url`）若不在白名单（重定向逃逸），该次导航判失败并审计。两条出站路径共用同一 `EgressGuard`，同域同结果。

**Why this priority**: 浏览器 Agent 是第二条（也是最后一条）无管控出站路径——它能打开任意 URL 并把页面内容带回会话，风险面比 HTTP 工具更宽（可执行页面脚本）。与 US1 共用检查器，边际成本低，故同列 P1。

**Independent Test**: 构造 `browser_task` 调用：target_url 命中/未命中两种；再构造重定向场景（target_url 命中但最终落地域不命中），断言导航判失败 + 审计。浏览器进程本身用既有测试替身（`agent_registry` 连接态由现有测试基建覆盖）。

**Acceptance Scenarios**:

1. **Given** 白名单含 `oa.example.com`，**When** 浏览器 Agent 以 `https://oa.example.com/list` 为目标执行，**Then** 放行进入既有执行链。
2. **Given** 白名单不含 `phish.example.net`，**When** 浏览器 Agent 以该域为目标，**Then** 执行前拒绝，审计记录 `egress.denied`，不启动浏览器任务。
3. **Given** target_url 命中白名单但服务端重定向到 `https://collect.other-domain.io/`，**When** 任务回收最终落地 URL 判定，**Then** 该次导航记失败（重定向逃逸），审计记录逃逸域。
4. **Given** 任务只给了 `target_name`（站点名称）而未给 URL，**When** 执行入口，**Then** 不做出站拒绝（域名不可解析），但审计记录"目标无 URL，未经出站检查"。

---

### User Story 4 - 远程沙箱契约保留与接口预留（Priority: P2）

`kernel.py:63` 的 `execution_location: Literal["server", "desktop", "remote_sandbox"]` 中 `remote_sandbox` 是已有契约枚举但无实现。本特性只做：契约不变更、在出站检查接口上为远程执行位置预留判定分支（远程沙箱内的出站由沙箱本体负责时的接口形状），并在文档中明示边界。不实现远程沙箱本体。

**Why this priority**: 整合方案把远程沙箱列为"后续项"。当前价值仅是防止后续实现被出站白名单的接口形状堵死（接口预留），以及把"契约已有、实现没有"这一事实显式记录，避免误读为已支持。P2 因为不阻塞前三个 Story 的交付。

**Independent Test**: 代码级断言 `contracts/kernel.py` 的枚举与校验行为不变（既有契约测试全绿）；审查出站检查接口对 `execution_location` 的预留分支有类型定义但无运行时依赖。

**Acceptance Scenarios**:

1. **Given** 现有 `SessionSpec.validate_execution_boundary` 契约测试，**When** 运行回归，**Then** 全部通过（枚举值 `remote_sandbox` 行为零变化）。
2. **Given** 出站检查接口定义，**When** 审查其入参/返回结构，**Then** 对 `execution_location=remote_sandbox` 有显式预留分支（类型或文档注释），且无任何代码路径真正实例化远程沙箱。

---

### Edge Cases

- **白名单存储（DB）不可用**：求值时读不到配置，按 fail-closed 拒绝（与 009 钩子超时 fail_closed 同语义，`services/admin-api/app/api/routes/hooks.py` 同款降级不允许）；不静默放行、不静默失败。
- **判定服务超时**：出站检查在工具调用链路上，必须有超时预算（复用 009 `hook_timeout_seconds` 5s 同量级思路，`egress_check_timeout_ms` 可配）；超时按拒绝处理。
- **URL 归一化**：大小写、尾部点（`example.com.`）、IDN/百分号编码、默认端口（:443/:80）在匹配前归一化；归一化失败按拒绝。
- **重定向链**：只有"最终落地 URL"参与判定；中间跳命中不豁免最终跳（防白名单域跳转到非白名单域）。
- **空路径前缀**：条目只配域名时对任意路径放行；配了路径前缀则前缀须匹配（大小写不敏感）。
- **MCP 工具**：MCP 工具经 `_mcp_jsonrpc` 出站到 `config.endpoint`——端点域同样过白名单（MCP 与 HTTP 两类 provider 一视同仁）。
- **审计与隐私**：审计记录域名与工具名，不记录完整 URL 查询串（可能含凭证）；与 034（凭证加密，规划中）在调用链上先后成立，互不影响。
- **工具禁用/停用**：工具未启用时根本不到出站检查点（`execute_runtime` 既有校验在前），不产生额外审计。
- **热更新竞态**：配置写入与求值读取之间允许秒级不一致（后写先读/先写后读），语义上以"读时快照"为准；不做强一致读（YAGNI，配错可立即改回）。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 系统 MUST 提供出站白名单配置，支持三层：平台默认（`scope=platform`）、租户级（`scope=tenant`）、工具例外（`scope=tool`，绑定 `tool_id`）；三层为**并集语义**——任一层命中即放行，无任何命中即拒绝。
- **FR-002**: HTTP/MCP 工具调用 MUST 在真实执行前（009 PreToolUse 求值点，`services/chat-api/app/enterprise_capabilities/tools/service.py:489-494` 同一位置）过出站检查；未命中 MUST 拒绝且不得向外部发出真实请求。
- **FR-003**: 浏览器 Agent MUST 在 `browser_task` 入口（`services/chat-api/app/enterprise_capabilities/browser/service.py:35`）对可解析的 `target_url` 过出站检查；未命中 MUST 拒绝执行。
- **FR-004**: 浏览器 Agent 重定向 MUST 以最终落地 URL（navigate action contract 的 `final_url`）判定；最终落地域未命中白名单时该次导航 MUST 记失败并审计（防重定向逃逸）。
- **FR-005**: 默认策略 MUST 为拒绝；白名单为空、URL 归一化失败、判定服务异常/超时、存储不可用，一律 MUST fail-closed 拒绝，**不得提供"放行"配置项**（与 001 R4 红线恒拒同语义，`services/admin-api/app/governance/risk.py:117`）。
- **FR-006**: 匹配 MUST 为域名后缀（条目覆盖全部子域）+ 可选路径前缀；非 http(s) scheme、IP 字面量（含回环/内网/链路本地地址）MUST 前置拒绝，不查白名单。
- **FR-007**: 白名单配置变更 MUST 热更新——保存后下一调用即按新配置求值，无需重启服务（与 009 FR-4 口径一致）。
- **FR-008**: 命中（`egress.allowed`）与拒绝（`egress.denied`）MUST 均落审计，字段含租户、工具/能力、判定域、scope 来源、结果与原因；审计 MUST 复用既有工具调用审计通道（`tools/service.py` 的 `tool.started`/`tool.succeeded` 同通道），不另建审计集合。
- **FR-009**: 脚本沙箱现有行为 MUST 不回退（回归）：子进程 `python -I` 隔离、rlimit 资源限额、网络默认拒绝（`executor.py:544-556` 与 `572-576`）三项既有测试 MUST 全绿。
- **FR-010**: 远程沙箱 MUST 仅保留 `kernel.py:63` 契约枚举与接口预留（类型定义/文档注释），MUST NOT 实现远程沙箱本体（进程管理、镜像、远程网络）。
- **FR-011**: 系统 MUST 提供 admin-api 白名单 CRUD（`/api/egress/allowlist`，契约定稿仿 `services/admin-api/app/api/routes/hooks.py`：列表 `{items,total}` 信封、更新走 `PATCH`、删除 `204`）与 admin-web 配置页。
- **FR-012**: 平台级条目 MUST 仅平台管理员可维护，租户级/工具级条目 MUST 按租户隔离（管理员只见本租户数据）；租户间、租户与平台间不得越权读写。

### Key Entities

- **EgressAllowlistEntry**: `{scope ∈ {platform, tenant, tool}, tenant_id, tool_id?, match_domain, path_prefix?, enabled, note, updated_at}`，白名单条目（集合 `egress_allowlist`）。`match_domain` 为后缀匹配基准域；`path_prefix` 可选。
- **EgressDecision**: `{allowed: bool, matched_scope?: platform|tenant|tool, domain: str, reason: str}`，一次出站判定的结果（审计事件的载荷）。
- **EgressGuard**: 出站检查器——URL 归一化 → scheme/IP 前置拒绝 → 三层并集匹配 → 决策；带超时预算，异常 fail-closed。HTTP 工具与浏览器 Agent 两条路径共用同一实例逻辑。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 未命中白名单的出站调用 100% 被拒（HTTP 工具与浏览器 Agent 两路径），且拒绝 100% 可在审计检索到（含域名/租户/工具/原因）。
- **SC-002**: 白名单配置保存后，下一调用即按新配置求值（热更新），全程无服务重启；管理员自助放行一个新域名的操作步数 ≤ 3（打开页 → 加一行 → 保存）。
- **SC-003**: 同一域名在 HTTP 工具与浏览器 Agent 两条路径下判定结果 100% 一致（共用 `EgressGuard`）。
- **SC-004**: 脚本沙箱既有行为回归 0 破坏（`executor.py` 现有测试全绿：隔离/限额/网络拒绝三项不回退）。
- **SC-005**: fail-closed 场景（存储不可用/判定超时/归一化失败）100% 拒绝，无一条静默放行；渗透式抽测 IP 字面量与非 http(s) scheme 100% 前置拒绝。

## Assumptions

- 假设白名单条目量级为百级/租户，求值时全量加载进内存判定，不建索引服务、不做缓存分层（YAGNI；条目量增长到万级再议）。
- 假设平台默认白名单以种子数据随代码提供（首批含模型 provider 官方域与部署探测常用域），租户在种子上增删本租户条目。
- 假设浏览器 Agent 的任务执行在用户本地 desktop agent（`agent_registry.get(context.user_id)` 连接态），服务端只能管控"目标下发前"与"结果回收后"两个时刻，无法管控浏览器进程内每一跳——故重定向判定依赖 navigate action contract 回收的 `final_url`；若 desktop agent 未回收 `final_url`，该次导航按"无法验证"记失败。
- 假设 admin-api 与 chat-api 共用同一 MongoDB 部署（白名单集合与 `hook_rules`、`dag_definitions` 同库），跨服务读取走既有 `get_db` 通道。
- 假设审计通道容量可承接每次出站调用两条事件（allowed + 既有 tool.started/succeeded），不新增审计集合。
- 假设 034（凭证存储加密，整合方案 §4.3，spec 已立项 Draft、代码未开工）落地后出站调用仍走服务端凭证注入（`services/chat-api/app/services/external_tools.py` 注入点），两特性在调用链上先后成立，互不阻塞。

## 跨特性关系（被依赖方视角，2026-10-23 双向声明）

- **与 009（hooks-interception）**：本特性的出站检查是 009 PreToolUse 求值链的一种落地——执行时机同在 `tools/service.py:489-494` 真实工具调用点，fail-closed 语义与 009 OQ-2（超时/异常一律拒绝）对齐；本特性**不新增 rule_type 枚举值**（009 FR-11"未知 rule_type fail-closed"语义保持不变），白名单存独立集合 `egress_allowlist` 而非 `hook_rules`。009 spec 无需修改，但建议在本特性实现后于 009 文档补一节"出站检查挂载说明"（文档层，非契约变更）。
- **与 001（gatekeeper-governance）**：白名单判定失败的 fail-closed 与 001 的 R4 红线恒拒（`risk.py:117`，`matrix_decision` 硬失败任何声称 R4 非 deny 的配置）同语义；拒绝事件进 001 审计落点（复用工具调用审计通道），门禁拒绝提示与出站拒绝提示在错误信息上可区分（同 009 FR-10 思路）。
- **与 022（security-hardening）**：出站白名单是 022 安全基线"数据不出域"的执行机制补全——022 已有脚本沙箱网络拒绝，本特性把该语义扩展到 HTTP 工具/浏览器 Agent；审计五要素与保留期口径沿用 022。
- **与 034（credential-encryption，spec 已立项 Draft、代码未开工）**：两特性在调用链上先后成立——034 管凭证存储加密（`external_tools` 存取路径），038 管出口域名（执行前置）；出站调用仍走服务端凭证注入不变，Agent 侧仍不拿明文。互不阻塞、无共同改动文件。
- **与 010（dag-orchestration-engine）**：编排节点内的工具出站同样过本检查（节点执行经工具调用链，009 已声明 010 节点执行是 PreToolUse 触发点之一）；本特性不给 010 增加任何新义务。
- **与 019（harness-elastic-config）**：薄模式不豁免出站检查——与 009 声明的"fail_closed 底线保留"一致，出站检查属红线检查，不因薄模式跳过。

## 判定口径补充（2026-10-24，/speckit-checklist 回填）

- **R-1 归一化与匹配规则**：`normalize_match_domain()` 转小写、剥离 `*.` 前缀与尾点、IDNA 编码（中文域名转 punycode）；`matches_domain(host, domain)` = 精确相等或 `host.endswith("." + domain)`（后缀匹配覆盖全部子域）。`normalize_path_prefix()` 转小写、去首尾 `/`；`matches_path(path, prefix)` 要求路径为 `/<prefix>` 或 `/<prefix>/...`，**只匹配 `parsed.path`、不含查询串与 fragment**，大小写不敏感（两侧均 lower）。
- **R-2 三层并集与工具条目过滤**：快照按 `tenant_id` 加载（平台 + 本租户 + 工具条目）；评估时先滤掉 `scope == "tool"` 且 `tool_id` 不等于当前工具的条目，再做域名/路径匹配。命中归因按 scope 优先级 `tool(0) → tenant(1) → platform(2)` 取首个命中条目，用于审计 `matched_scope`/`matched_entry_id`。**工具级条目只对绑定的 `tool_id` 生效**。
- **R-3 IP 字面量与 SSRF 防护范围**：`is_ip_literal()` 用 `ipaddress.ip_address()` 判定，**IPv4 与 IPv6 全覆盖**（含回环/内网/链路本地/`0.0.0.0`），命中即前置拒绝、不查白名单。**不拦截** `localhost` 之类域名（靠白名单不含它兜底），**不承诺**防御 DNS rebinding（解析发生在白名单判定之后的下游，本特性不做 DNS 二次校验）。
- **R-4 热更新时效**：进程内快照缓存 `DEFAULT_SNAPSHOT_TTL_SECONDS = 2.0`，即配置保存后**最多 2 秒**生效；`EgressGuard.invalidate(tenant_id)` 可在同进程内立即失效。因此 FR-007 的"下一调用即生效"精确表述为"≤2s（或显式 invalidate 后即时）"，不承诺跨进程实时。
- **R-5 检查超时口径**：`DEFAULT_EGRESS_TIMEOUT_MS = 5000`，`asyncio.wait_for` 包裹整个评估（含快照加载）；超时 → `reason="egress-check-timeout"`、异常 → `reason="egress-check-error: <Type>"`，**两者均为拒绝**。5s 上限只覆盖白名单评估本身，不含工具真实网络请求耗时。
- **R-6 `remote_sandbox` 的显式拒绝**：`execution_location == "remote_sandbox"` 时直接返回拒绝（`reason="remote_sandbox-not-implemented (038)"`），即使域名命中白名单也不放行——契约预留但不实现本体，且不因预留而放松默认拒绝。
- **R-7 审计落点与脱敏**：写 `EGRESS_AUDIT_COLLECTION = "enterprise_tool_audit"`（与 `tool.started`/`tool.succeeded` 同集合），事件 `egress.allowed` / `egress.denied` / `egress.target_url_missing`；URL 只记 `strip_url_secrets()` 结果（**去掉 query/fragment/userinfo**），避免把令牌写进审计。
- **R-8 CRUD 契约形状**：`GET /api/egress/allowlist`（列表，`{items,total}` 信封）、`GET /api/egress/allowlist/{entry_id}`、`POST`（201）、`PATCH`（部分更新）、`DELETE`（204）、`GET /api/egress/logs`（审计查询）。`PATCH` 只更新传入字段，**`scope`/`tool_id` 变更需重新校验租户归属**。
- **R-9 多 URL 聚合判定**：`decide_urls(urls, ...)` 对工具的全部出站候选 URL（`resolve_tool_outbound_urls()` 抽取的 `url`/`endpoint` 等）**全部求值，任一拒绝即整体拒绝**；首个拒绝原因作为返回 reason。
- **R-10 浏览器重定向防逃逸**：入口按 `target_url` 检查（`browser/service.py:46`）；navigate action 落地后以 `artifacts["final_url"]` 复核（`browser/service.py:141-143` + `_navigate.py`），落地域未命中即记该次导航失败并写 `egress.denied`。无 `final_url` 时（如非 navigate 动作）不做二次判定，入口检查已生效。
- **R-11 与 009 求值点的执行顺序**：HTTP/MCP 工具在 `tools/service.py:583-599` 处——**先做出站判定、再发真实请求**；拒绝时记 `egress.denied` 审计并直接返回失败，不进入 `tool.started` 之后的真实执行阶段。浏览器 Agent 在 `browser_task` 入口判定。
- **R-12 脚本沙箱不回退的回归范围**：`services/chat-api/app/enterprise_capabilities/data/script_engine/executor.py` 的 `python -I` 子进程隔离、rlimit 限额、`socket.socket = _deny_network` 三项既有测试保持全绿（不在本特性改动范围）；038 的测试只新增 egress 相关用例。
- **R-13 空白单与业务可用性**：平台/租户白名单均为空时**全部出站拒绝**（fail-closed 的直接后果）；上线初期需由平台管理员先写入必需域名（如模型/检索供应商域名），这是运维前置动作而非需求缺陷。`monitor` 观察模式**不提供**（不设"只审计不拒绝"开关）。
- **R-14 远程沙箱契约预留的验收判据**：`services/chat-api/app/dsh_runtime/contracts/kernel.py` 的 `remote_sandbox` 枚举值与注释保留；验收 = "枚举存在且无远程沙箱实现代码（无进程/镜像/远程网络模块）"+ `execution_location == "remote_sandbox"` 被显式拒绝（R-6）。
- **R-15 平台条目的可见性**：平台级条目对租户管理员**可读不可写**（列表可见，维护仅限平台管理员）；租户级/工具级条目按 `tenant_id` 隔离，跨租户不可见。租户与平台之间不越权读写（FR-012）。

## Non-Goals

- **不实现远程沙箱本体**：`kernel.py:63` 的 `remote_sandbox` 仅保留契约枚举与接口预留；远程执行的进程管理、镜像分发、远程网络管控不在本特性范围（整合方案明示"可作为后续"）。
- 不实现请求内容/响应内容的深度检查（不做 DLP、不做响应脱敏——那是执行链下游既有能力的事）。
- 不实现浏览器页面子资源（图片/CSS/JS/XHR 等）的逐项域名管控（首期只管顶层导航与最终落地）。
- 不实现按时间窗口/配额的出站速率限制或并发限制（属配额体系既有范围）。
- 不修改脚本沙箱实现本身（仅以回归保证其现有行为不回退；把它的"网络默认拒绝"语义提升为全路径管控是指机制复用，不是改 `executor.py`）。
- 不引入新的网络库（判定与配置读写均走既有依赖）。
