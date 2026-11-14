# mogo 权限控制说明（含数据权限）

> **文档类型**：技术说明 / 运维与架构评审参考
> **代码基线**：`/Users/cooper/Github/mogo`（main 分支，2026-10-08 快照）
> **撰写日期**：2026-10-08
> **事实来源**：本文所有结论均以**代码**为准，spec 仅作对照。每条关键结论标注 `文件路径:行号`。
> **冲突处理**：spec 与代码不一致时**以代码为准**，并在 [第 12 章](#12-spec-与代码不一致清单重要) 单独列出差异。

---

## 目录

| 章节 | 标题 | 内容概要 |
|---|---|---|
| [1](#1-文档目的读者对象与术语表) | 文档目的、读者对象与术语表 | 读者定位、术语定义（租户/岗位角色/权限码/数据范围等 20+ 术语） |
| [2](#2-权限模型总览) | 权限模型总览 | 五层判定链路 ASCII 图、判定顺序、短路规则、fail-closed 矩阵 |
| [3](#3-功能权限capability--action-维度) | 功能权限（Capability / Action 维度） | RBAC 权限码模型、岗位角色体系、权限授予与回收、API 挂载 |
| [4](#4-数据权限data-scope-维度重点) | 数据权限（Data Scope 维度，重点） | 6 种数据范围模型、上下文寻址可见性、三域记忆隔离、access 范式、多租户隔离 |
| [5](#5-配额quota) | 配额（Quota） | 配额与权限的关系、两套配额体系、`2099d5f` 修复 |
| [6](#6-审计audit) | 审计（Audit） | 6 个审计落点、字段模型、覆盖度分析 |
| [7](#7-完整判定流程-walkthrough) | 完整判定流程 Walkthrough | 4 个真实场景端到端逐步追踪 |
| [8](#8-配置与运维) | 配置与运维 | 环境变量、集合与索引清单、如何新增权限点/数据范围 |
| [9](#9-测试覆盖现状) | 测试覆盖现状 | 各测试文件验证内容、**覆盖缺口清单** |
| [10](#10-安全与越权风险点按严重度排序) | 安全与越权风险点（按严重度排序） | 12 个风险点，含 PoC 与修复建议 |
| [11](#11-附录核心文件清单) | 附录 A：核心文件清单 | 路径 + 行数 + 职责一句话 |
| [12](#12-spec-与代码不一致清单重要) | 附录 B：spec 与代码不一致清单 | 16 条差异，**本文档最有价值的部分** |
| [13](#13-附录c权限点全表) | 附录 C：权限点全表 | 全部权限码、能力键、DENIAL_STATUS 映射 |
| [14](#14-附录d死代码与未接线清单) | 附录 D：死代码与未接线清单 | 已定义但无生产调用者的函数 |

---

## 1. 文档目的、读者对象与术语表

### 1.1 文档目的

mogo 是一个多租户企业级智能体平台，包含四个主要进程：

| 进程 | 端口 | 职责 | 权限相关职责 |
|---|---|---|---|
| `admin-api` | 8100 | 管理端后端（管理后台） | 治理平面：六层门禁（Gatekeeper）、岗位角色 CRUD、权限码授予、租户生命周期 |
| `chat-api` | 8200 | 对话端后端（员工侧） | 数据平面：员工策略求值、数据可见性判定、调用门禁 |
| `apps/admin-web` | 3000 | 管理端前端 | 岗位角色配置界面、审计查看界面 |
| `apps/user-web` | 3001 | 对话端前端 | 员工聊天界面，能力受限体现 |

本文档回答三个问题：

1. **一个请求从chat-api 发起、经过 admin-api 的门禁、最终落到数据层，权限是怎么判定的？**（第 2、7 章）
2. **功能权限（能不能做这个操作）和数据权限（能不能看这份数据）分别由哪些代码强制？**（第 3、4 章）
3. **现有实现在哪些地方与设计文档不符、哪些地方可能被越权？**（第 10、12 章）

### 1.2 读者对象与阅读路径

| 读者 | 建议阅读路径 | 关注重点 |
|---|---|---|
| **新人开发者**（第1 周） | 第 1 章术语 → 第 2 章总览 → 第 3 章功能权限 → 第 7 章 walkthrough | 建立"权限在哪些地方被强制"的心智模型 |
| **架构评审者** | 第 2 章 → 第 4 章数据权限 → 第 10 章风险 → 第 12 章差异 | 设计意图 vs 实现的 gap |
| **运维/SRE** | 第 5 章配额 → 第 6 章审计 → 第 8 章配置与运维 → 第 8.4 故障排查 | 配额不生效、审计查不到、层被降级 |
| **安全工程师** | 第 10 章风险点 → 第 12 章差异 → 第 9.3 覆盖缺口 | 可利用的越权路径与盲区 |
| **产品/需求方** | 第 1.3 术语表 → 第 3.2 岗位角色 → 第 4.2 数据范围 | 能给客户讲清楚"权限怎么配" |

### 1.3 术语表

> 术语按字母/拼音顺序排列。中文在前，英文原文（代码中的标识符）在后。

#### A. 主体类（Subject）

| 术语 | 英文原文 / 标识符 | 定义 | 代码位置 |
|---|---|---|---|
| **租户** | Tenant / `main_id` | 一个企业实例。数据隔离的第一边界。所有业务集合都带 `main_id` 字段分区。**注意：代码里租户 ID 叫 `main_id`，不是 `tenant_id`**（两者在治理层指同一概念） | `services/chat-api/app/core/tenant.py:6` |
| **平台超级管理员** | Platform Admin / `__platform__` | 不属于任何企业的管理账号，全局唯一，只管租户生命周期 | `services/admin-api/app/api/deps.py:75-83` |
| **租户管理员** | Tenant Admin | 归属于某租户的管理账号，配置 `role_name="组织管理员"` | `services/admin-api/app/api/deps.py:42` |
| **员工** | Employee / `end_users` | 对话端的普通用户，权限由岗位角色决定 | `services/chat-api/app/governance/position_policy.py:86` |
| **岗位角色** | Position Role / `position_roles` | 006 特性引入的粗粒度角色，是权限码的"预设组"。一个员工可绑定多个角色，其中一个是主角色 | `services/admin-api/app/position_roles/constants.py:12` |
| **全能力管理员** | Full-Access Admin / `full_access_admin` | 系统内置岗位角色，`_id = system:<main_id>:full_access_admin`，不可改不可停不可删，权限展开为通配符 `*` | `services/admin-api/app/position_roles/constants.py:9-10` |

#### B. 客体与动作类（Object / Action）

| 术语 | 英文原文 / 标识符 | 定义 | 代码位置 |
|---|---|---|---|
| **权限码** | Permission Code | 形如 `<resource>:<action>[:<target>]` 的细粒度授权标识，如 `knowledge:read`、`document:read:doc-1` | `services/admin-api/app/governance/rbac_model.py:37-63` |
| **资源** | Resource | 权限码的第一段，如 `knowledge`、`document`、`bizdata`、`kg` | 同上 |
| **动作** | Action | 权限码的第二段，如 `read`、`generate`、`execute`、`assign` | 同上 |
| **目标** | Target | 权限码的可选第三段，限定到具体对象 | 同上 |
| **Agent 能力** | Agent Capability | 006 的粗粒度功能开关，共 5 个键（见 [3.3](#33-能力键全表)） | `services/admin-api/app/position_roles/constants.py:1-7` |
| **能力资产** | Capability Asset | 018 引入的能力注册单元，地址为 `mogo://skill/asset/<assetKey>` | `services/chat-api/app/context_space/address.py:36` |
| **工具 / MCP** | External Tool / `external_tools` | 企业接入的外部工具（HTTP 或 MCP 类型） | `services/admin-api/app/api/routes/position_roles.py:113` |
| **Skill** | Skill / `skills` | 企业 Skill，岗位角色可限定可见范围 | `services/admin-api/app/api/routes/position_roles.py:114` |

#### C. 数据范围类（Data Scope）

| 术语 | 英文原文 / 标识符 | 定义 | 代码位置 |
|---|---|---|---|
| **数据范围** | Data Scope | 主体能看到哪些数据的判定维度。本平台**没有统一的 DataScope 枚举**，而是由 6 套独立机制共同实现（见 [4.2](#42-数据范围模型六套机制拼装)） | — |
| **记忆范围** | Memory Scope | 三级记忆隔离：`personal` / `workspace` / `org` | `services/chat-api/app/memory/scope.py:25-28` |
| **可见性** | Visibility | 记忆的可见群体：`owner` / `members` / `organization` | `services/chat-api/app/memory/scope.py:31-34` |
| **统一上下文地址** | Unified Context Address / `mogo://` | 021 引入的虚拟寻址层，4 个根：`memory` / `resource` / `skill` / `session` | `services/chat-api/app/context_space/address.py:145-163` |
| **地址** | Address | `<scheme>://<root>/<...>/<tier>` 的字符串，**是定位符不是凭证**（`visibility.py:57-61` 明确） | `services/chat-api/app/context_space/address.py` |
| **密度层** | Density Tier / `L0`/`L1`/`L2` | 与 scope 正交的另一维度：L0=一行摘要、L1=结构要点、L2=原始详情 | `services/chat-api/app/memory/scope.py:61-64` |
| **委托式可见性** | Delegated Visibility | 021 地址层不自己实现鉴权，委托给各后端既有检查 | `services/chat-api/app/context_space/visibility.py:1-15` |
| **检索轨迹** | Retrieval Trace | 记录"召回了什么、跳过了什么、为什么"的记录，落观测日志而非审计流 | `services/chat-api/app/context_space/trace.py:1-9` |
| **空间类型** | Space Type | `personal`（个人空间）/ `enterprise`（企业空间），影响配额路径 | `services/chat-api/app/core/quota_policy.py:170-171` |

#### D. 门禁类（Gate）

| 术语 | 英文原文 / 标识符 | 定义 | 代码位置 |
|---|---|---|---|
| **闸门 / 门禁** | Gatekeeper | 001 引入的六层串行判定链，admin-api 实现一次，通过 HTTP 供 chat-api 调用 | `services/admin-api/app/governance/gatekeeper.py:93-152` |
| **层** | Layer | 六层之一：`identity` / `rbac` / `redaction` / `approval` / `quota` / `audit` | `services/admin-api/app/governance/config.py:24-31` |
| **地板** | Floor | 不可禁用的层集合：`identity`、`rbac`、`redaction`、`audit` | `services/admin-api/app/governance/config.py:36` |
| **判定** | Decision / `GateDecision` | `allow` / `deny` / `require_approval` | `services/admin-api/app/governance/gatekeeper.py:18-23` |
| **风险级** | Risk Level / `R0`-`R4` | 工具的风险分级，R4=红线不可逆 | `services/admin-api/app/governance/risk.py:30` |
| **自主级别** | Autonomy Level / `L1`-`L5` | 执行上下文的自主程度，L1=全人工、L5=全自动 | `services/admin-api/app/governance/risk.py:29` |
| **自主矩阵** | Autonomy Matrix / `AUTONOMY_MATRIX` | 5×5=25 格 `[L][R]` → 判定 | `services/admin-api/app/governance/schema.py:32-38` |
| **红线** | Red Line | R4 在任何 L 下必须 `deny`，代码双重强制 | `services/admin-api/app/governance/risk.py:117-118` |
| **审批票据** | Approval Ticket / `gate_approvals` | 挂起调用的一次性凭证，5 分钟 TTL | `services/admin-api/app/governance/layers/approval.py:32-33` |
| **厚度模式** | Harness Mode / `thick`\|`thin` | 019 引入的层开关：`thin` 模式丢弃 `approval` + `quota` | `services/admin-api/app/governance/gatekeeper.py:56,109-114` |
| **显式授权** | Explicit Grant / `permission_grants` | 直接授予的权限码，三级隔离：`tenant` / `org` / `user` | `services/admin-api/app/governance/permission_grants.py:32-34` |
| **特殊授权** | Capability Override / `end_user_capability_overrides` | 针对单个员工的临时授权（允许/拒绝能力、工具、Skill），带有效期 | `services/admin-api/app/position_roles/constants.py:14` |
| **脱敏** | PII Redaction | 5 类 PII × 4 种策略（mask/remove/hash/abstract） | `services/admin-api/app/governance/pii.py:41-52` |

#### E. 配额与审计类

| 术语 | 英文原文 / 标识符 | 定义 | 代码位置 |
|---|---|---|---|
| **不限额** | Unlimited | 配额短路标记，`unlimited=True` 时永不拦截 | `services/admin-api/app/core/quota_policy.py:82-87` |
| **剩余额度** | Remaining Points | 剩余 token 数；`-1` 表示不限额（哨兵值） | `services/admin-api/app/core/quota_policy.py:189` |
| **门禁事件** | Gate Event / `gate_events` | 每次门禁判定的审计记录（通过 + 拒绝） | `services/admin-api/app/governance/layers/audit.py:17` |
| **系统审计** | System Audit / `system_audit_logs` | 管理端所有变更类HTTP 请求的审计记录 | `services/admin-api/app/system_audit/constants.py:1` |
| **岗位审计** | Position Role Audit / `position_role_audit_logs` | 岗位角色操作 + 员工能力使用/拒绝事件 | `services/admin-api/app/position_roles/constants.py:16` |

---

## 2. 权限模型总览

### 2.1 五层判定链路

mogo 的权限判定**不是一个统一的授权引擎**，而是分布在四个进程/模块的多个判定点。按请求生命周期排列：

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  阶段 A：认证（Authentication）—— 你是谁？                                    │
│                                                                             │
│  admin-api: deps.py::_load_authenticated_account                             │
│    ├─ 解码 JWT Bearer token                                                │
│    ├─ 校验 admin_sessions.status == "active"                               │
│    ├─ 加载 admin_accounts（status == "active"）                             │
│    └─ ★ 租户 ID 只从 token subject 取，无 bootstrap 兜底（deps.py:14-16）      │
│                                                                             │
│  chat-api: end_user_session.py::resolve_session_user│
│    ├─ 校验 end_user_sessions（token_id + status=active + 未过期）              │
│    └─ ★ 返回 {session, user, main_id} —— 只有 3 个键（:70）                  │
│                                                                             │
│  ✗ 风险 R-01：chat-api 端点大量读取 resolved["user_id"] / ["role"]，          │
│    但这两个键在返回里不存在 → 恒为""（详见第 10 章）                          │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │ main_id / user_id / roles
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  阶段 B：员工策略求值（Position Policy）—— 你的岗位角色允许什么？               │
│                                                                             │
│  chat-api: governance/position_policy.py::MongoEmployeePolicyResolver        │
│    ├─ 查 end_user_position_roles（main_id + user_id）→ role_ids              │
│    ├─ 查 position_roles（main_id + _id in role_ids + status=active）          │
│    ├─ 查 end_user_capability_overrides（status=active + 生效期内）            │
│    ├─ 查 position_role_migrations（判断是否迁移完成）                         │
│    └─ ★ build_effective_policy() 合并出EffectiveEmployeePolicy               │
│                                                                             │
│    产出 4 个判定方法（第 45-64 行）：                                         │
│      allows_capability(key)          → 功能开关                              │
│      allows_external_tool(tool_id)   → 工具访问                              │
│      allows_skill(skill_id)          → Skill 访问                            │
│      allows_internal(capability_ref) → 内部能力引用                          │
│                                                                             │
│    ★ 特例：既无角色又无绑定 + 迁移未完成 → 返回全开legacy-full-access         │
│      （position_policy.py:133-141）← 见风险 R-02│
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  阶段 C：六层门禁（Gatekeeper）—— 这次工具调用允许吗？                        │
│                                                                             │
│  chat-api 发起                     admin-api 判定                             │
│  ─────────────                     ─────────────                             │
│  turn_admission.py                                     │
│    └─ run_gate_plan()                gatekeeper_internal.py                   │
│         │                                   │                               │
│         │ ① POST /api/internal/            │ _require_service(token)      │
│         │    gatekeeper/evaluate ───────────▶│  hmac.compare_digest 校验     │
│         │    Header: X-MOVO-Service-Token    │                               │
│         │    body: {tool, tenantId,           ▼                              │
│         │           userId, roles,          gatekeeper.py::evaluate           │
│         │           request, sessionId,        │                              │
│         │           harnessMode,              │ 拆出 audit 层（提前）          │
│         │           approvalToken}            ▼                              │
│         │                              ┌─────────────────────────────┐      │
│         │                              │ 1. identity  主体可解析？     │      │
│         │                              │    ↓ 失败 → DENY(403)       │      │
│         │                              │ 2. rbac      持权限码？       │      │
│         │                              │    ↓ 失败 → DENY(403)       │      │
│         │                              │ 3. redaction PII 脱敏        │      │
│         │                              │    ↓ 永不拒绝（改写 ctx）     │      │
│         │                              │ 4. approval  矩阵判定        │      │
│         │                              │    ↓ require_approval        │      │
│         │                              │        → REQUIRE(409)+token  │      │
│         │                              │ 5. quota     额度够？         │      │
│         │                              │    ↓ 失败 → DENY(429)       │      │
│         │                              │ 6. audit     落库            │      │
│         │                              │    ↓ 失败 → DENY(500)       │      │
│         │                              └─────────────────────────────┘      │
│         │◀────── {decision, layer, reason, request(已脱敏)} ────────────────│
│         │                                                               │
│         ├─ decision != "allow"  → raise GateDeniedError（fail-closed）       │
│         └─ decision == "allow"   → 用**已脱敏**的 request 转发后端           │
│                                     （turn_admission.py:265-269）            │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  阶段 D：数据可见性（Data Visibility）—— 这份数据你能看吗？                   │
│                                                                             │
│  chat-api: context_space/visibility.py::check_visibility（按地址根分派）        │
│    ├─ memory  → memory/scope.py::visible_to（对**已存储记录**判定）          │
│    │             memory 为 None → fail-closed拒绝（:69-75）                 │
│    ├─ resource→ 仅比对 addr.tenant_id == ctx.tenant_id（:84-94）              │
│    ├─ skill   → 仅比对 addr.identifiers[0] == ctx.tenant_id（:97-108）        │
│    └─ session → 仅比对 addr.tenant_id == ctx.tenant_id（:111-119）            │
│                                                                             │
│  另有 2 套独立的 access 模块（不走 021 地址层）：                             │
│    ├─ personal_knowledge/access.py  → owner / resource_grants 三态判定       │
│    └─ resource_feedback/access.py  → 按 resource_type 分派3 种判定           │
│                                                                             │
│  ★ 全部 6 套机制的 fail模式统计见[表 4-3](#43-六套机制的失败模式对比)          │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  阶段 E：配额（Quota）—— 你还有额度吗？                                       │
│                                                                             │
│  chat-api: core/quota_policy.py::assert_quota_available                       │
│    ├─ 空间类型判定（personal / enterprise）                                  │
│    ├─ points_unlimited → 立即返回（不限额）                                  │
│    ├─ remainingPoints == -1 → 视为不限额                                     │
│    └─ remainingPoints <= 0 → raise QuotaExceededError                        │
│                                                                             │
│  admin-api: governance/layers/quota.py（门禁第5 层）                          │
│    └─ default_credit_checker → 调admin-api 侧 get_quota_summary              │
│       ★ 与 chat-api 是两份独立实现，行为已漂移（见 [12.14](#1214-差异-14)）  │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 六层门禁的执行顺序与短路规则

层的**规范顺序**定义在 `config.py:24-31`，任何配置都会被强制按此顺序重排（`config.py:54-57`）：

```python
CANONICAL_LAYER_ORDER = ("identity", "rbac", "redaction", "approval", "quota", "audit")
```

**短路规则**（`gatekeeper.py:139-152`）：

```python
for layer in chain:                # chain 已剔除 audit
    verdict = await layer.evaluate(context)
    if verdict.decision is not GateDecision.ALLOW:
        await self._record(audit_layer, context, verdict)   # 先落审计
        return verdict                                   # 立即返回，后续层不执行
final = GateVerdict(ALLOW, "gatekeeper", "all layers passed")
audit_verdict = await self._record(audit_layer, context, final)
if audit_verdict.decision is not ALLOW:
    return audit_verdict                # 审计落库失败 → 整个调用被拒
return final
```

三个关键设计点：

1. **audit 层被提前拆出**（`gatekeeper.py:128-137`）。因为 audit 排在最后，中间层拒绝会直接 return 导致审计永不执行。拆出后在短路分支显式调用。
2. **审计落库失败 = 整个调用被拒**（`gatekeeper.py:150-151`）。注释说明这是 2026-10-03 审计修复："an unauditable allow must not slip through (FR-9)"。对应测试 `test_governance_gatekeeper.py:97-118`。
3. **redaction 层永不拒绝**。它改写 `ctx.request` 后返回 ALLOW，只在 `ctx.annotations["redaction"]` 留指纹（`redaction.py:88-96`）。

### 2.3 拒绝原因到 HTTP 状态码的映射

`gatekeeper.py:30-37` 定义：

| 层 | 状态码 | 语义 |
|---|---|---|
| `identity` | 403 | 主体无法解析 |
| `rbac` | 403 | 缺权限码 |
| `redaction` | 403 | （实际不会触发，该层永不拒绝） |
| `approval` | 409 | 挂起等待审批，响应带 token |
| `quota` | 429 | 配额耗尽 |
| `audit` | 500 | 审计落库失败 |
| 其他未列出 | 403 | 兜底 |

工具执行侧的消费代码在 `tools.py:362-371`：审批挂起时把 `token` / `action_id` 放进 HTTP 响应 detail。

### 2.4 fail-closed 矩阵

平台的"拒绝默认值"（fail-closed = 出错时倾向拒绝）覆盖情况：

| 场景 | 行为 | 位置 | fail-closed? |
|---|---|---|---|
| 租户缺失 | DENY | `identity.py:16-21` | ✅ |
| 用户与角色都缺失 | DENY | `identity.py:22-29` | ✅ |
| 权限码为空 | DENY | `rbac.py:76-83` | ✅ |
| 权限码格式非法 | 解析时丢弃 → 空集 → DENY | `rbac_model.py:69-73` | ✅ |
| `required` 为空串 | `has_permission` 返回 False | `rbac_model.py:114-115` | ✅ |
| 审计落库失败 | DENY(500) | `audit.py:70-74` | ✅ |
| 门禁服务不可用（超时/5xx） | chat-api 抛 `GateDeniedError` | `gatekeeper_client.py:89-96` | ✅ |
| 门禁返回非 allow | chat-api 抛 `GateDeniedError` | `gatekeeper_client.py:100-105` | ✅ |
| 记忆记录未加载到 | `check_memory_visibility` 返回 False | `visibility.py:69-75` | ✅ |
| R4 矩阵格被改成非 deny | 硬编码回 deny | `risk.py:117-118` | ✅ |
| 配置试图禁用必需层 | `GateConfigError` | `config.py:59-66` | ✅ |
| 配置存储不可用 | 回退到 thick 默认 | `config.py:105-119` | ✅ |
| **未知工具的风险级** | **默认 R0（最宽松）** | `risk.py:35,98-99` | ❌ fail-open |
| **未知自主格** | **默认 allow** | `risk.py:141-143` | ❌ fail-open |
| **配额探测失败** | **返回 None（放行）** | `layers/quota.py:46-49` | ❌ fail-open（有意） |
| **PII 策略加载失败** | 用内置默认 + WARN 日志 | `redaction.py:63-72` | ⚠️ 部分（有日志） |
| **审批 registry `decide` 遇未知票据** | 返回 False | `approval.py:104-105` | ✅ |
| **`promote_to_org` 角色不足** | `MemoryAccessError` | `scope.py:127-128` | ✅ |
| **记忆写入 org scope 无授权** | HTTP 403 | `endpoints/memory.py:49-53` | ✅ |

**结论**：门禁链本身（阶段 C）是完整的 fail-closed；两处 fail-open 是**有意设计**（未知工具按只读处理，避免新工具一上线就全部被拦；配额探测失败放行，避免存储抖动阻断业务），但需要运维知晓。

---

## 3. 功能权限（Capability / Action 维度）

### 3.1 权限码模型（Permission Code Model）

#### 3.1.1 语法

定义在 `rbac_model.py:37-63`：

```
<resource>:<action>[:<target>]
```

- `resource`：必填，非空
- `action`：必填，非空
- `target`：可选；含`:` 时用 `":".join(parts[2:])` 拼接（`rbac_model.py:54`），即target 本身可以含冒号

解析失败抛 `ValueError`（`rbac_model.py:49-56`）：

| 输入 | 结果 | 原因 |
|---|---|---|
| `""` / `"  "` | ValueError | 空串 |
| `"knowledge"` | ValueError | 段数 < 2 |
| `":"` | ValueError | resource/action 为空 |
| `"a:"` | ValueError | action 为空 |
| `"knowledge:read"` | OK | 两段 |
| `"document:read:doc-1"` | OK | 三段 |

#### 3.1.2 匹配语义

`has_permission(granted, required)` 的完整规则（`rbac_model.py:104-134`）：

| 规则 | 条件 | 结果 | 代码 |
|---|---|---|---|
| 通配符 | `"*" in granted` | ✅ True（**空required 也返回 True** ⚠️ 见下） | `:116-117` |
| 空required | `not required` | ❌ False | `:114-115` |
| required 非法 | parse 抛 ValueError | ❌ False | `:118-121` |
| 精确匹配 | resource+action+target 全等 | ✅ True | `:127-133` |
| 资源级通配 | `have.action == "*"` | ✅ True | `:129` |
| **无 target 授予带 target 请求** | `have.target` 为空 | ✅ **True** | `:131` |
| target 不匹配 | `need.target and have.target and !=` | ❌ 继续循环 | `:131-132` |

**已主动验证的匹配行为**（用 Python 复现 `rbac_model.py:104-134` 逻辑）：

```
A有 doc-1 要 doc-2  : False     ← target 正确隔离
B 无target 要 secret: True      ← ⚠️ 宽授予：无 target 的码可访问任意 target
C resource:* 要 kg:read:x: True ← 资源通配 + 无 target 授予叠加
D 空 required      : True      ← ⚠️ 需注意：通配符先于空 required 检查
```

> **注意 D**：代码顺序是先 `if not required: return False`（`:114`），再 `if WILDCARD_CODE in granted: return True`（`:116`）。所以 `has_permission({"*"}, "")` **返回 False**，与我的复现脚本顺序相反。**以代码为准：D 的正确结果是 False**，这也是测试 `test_governance_rbac_model.py:62` 断言的。规则 B 是真实存在的行为。

#### 3.1.3 岗位角色 → 权限码的展开

`expand_role_to_codes(role)`（`rbac_model.py:77-101`）：

```python
marker = role.get("system_key") or role.get("role_key") or role.get("key")
if marker == FULL_ACCESS_ROLE_KEY:      # "full_access_admin"
    return {"*"}                        # 通配符短路

codes = set(parse_codes(role.get("permission_codes", []) or []))   # 显式码

capabilities = role.get("capabilities") or role.get("agent_capabilities") or {}
for key, enabled in capabilities.items():
    if enabled:
        codes.update(CAPABILITY_TO_CODES.get(key, ()))             # 能力键 → 码
return codes
```

三个输入字段都是"可选别名"设计（`system_key` / `role_key` / `key`，`capabilities` / `agent_capabilities`），代码对存量数据格式做了兼容。

#### 3.1.4 能力键 → 权限码映射表

`rbac_model.py:25-31` 定义 5 条映射：

| 能力键 | 展开的权限码 |
|---|---|
| `content_generation` | `content:generate` |
| `image_generation` | `image:generate` |
| `code_generation` | `code:execute` |
| `browser_automation` | `browser:automate` |
| `internal_knowledge` | `knowledge:read` |

⚠️ **重要限制**：这张表只有 5 条。001 spec 的 Success Criteria 要求"权限码模型支持至少 10 个 resource × 3 个 action"（`specs/001-gatekeeper-governance/spec.md:113`）。**代码里没有任何 resource/action 的注册表或枚举**——权限码是完全开放的字符串。这意味着：

- 任何符合 `<非空>:<非空>` 格式的字符串都是"合法权限码"
- 唯一的注册表是 `permission_grants` 集合里的实际文档
- 因此"未注册的码"和"拼错的码"在 `has_permission` 层面**行为相同**（都不匹配），满足 FR-5 的 fail-closed，但无法给出"该码不存在"的诊断

### 3.2 岗位角色体系（position_roles）

#### 3.2.1 数据模型

集合 `position_roles`（`constants.py:12`），文档结构（由 `service.py:169-179` 的 `_document()` 构造）：

| 字段 | 类型 | 说明 | 代码 |
|---|---|---|---|
| `_id` | str | 角色 ID。系统角色为 `system:<main_id>:full_access_admin` | `repository.py:54` |
| `main_id` | str | 所属租户 | `service.py:170` |
| `name` | str | 角色名，**租户内唯一**（`service.py:153-158`），最长 120 | `service.py:171` |
| `description` | str | 描述，最长 1000 | `service.py:172` |
| `status` | str | `active` / `disabled` | `service.py:173` |
| `protected` | bool | 系统保障角色不可删除 | `service.py:64` |
| `system_key` | str | 系统角色标识（如 `full_access_admin`），租户内唯一 | `repository.py:32-37` |
| `capabilities` | dict[str,bool] | 5 个能力开关 | `service.py:174` |
| `tool_access_mode` | str | `all` / `selected` | `service.py:175` |
| `tool_ids` | list[str] | `selected` 模式下的工具白名单 | `service.py:176` |
| `skill_access_mode` | str | `all` / `selected` | `service.py:177` |
| `skill_ids` | list[str] | `selected` 模式下的 Skill 白名单 | `service.py:178` |
| `created_at` / `updated_at` | datetime | 时间戳 | `service.py:64,76` |

**关键不变式**（`service.py:176,178`）：

```python
"tool_ids": [] if tool_mode == "all" else list(dict.fromkeys(...))
"skill_ids": [] if skill_mode == "all" else list(dict.fromkeys(...))
```

即**`all` 模式下 ID 列表被强制清空**。这是一个干净的规范化——避免"既是all 又列了部分 ID"的歧义语义。

#### 3.2.2 内置角色：全能力管理员

`repository.py:52-78` 的 `ensure_full_access_role()` 用 upsert 语义保证每个租户都有且只有这个角色：

```python
role_id = f"system:{main_id}:full_access_admin"
await db[POSITION_ROLE_COLLECTION].update_one(
    {"main_id": main_id, "system_key": FULL_ACCESS_ROLE_KEY},
    {"$setOnInsert": {"_id": role_id, "name": "全能力管理员", ...},
     "$set": {"status": "active", "protected": True,
              "capabilities": {key: True for key in AGENT_CAPABILITY_KEYS},
              "tool_access_mode": "all", "tool_ids": [],
              "skill_access_mode": "all", "skill_ids": [], ...}},
    upsert=True,
)
```

保护措施（三重）：

| 保护 | 实现 | 代码 |
|---|---|---|
| 不可修改 | `update_role` 检查 `system_key == FULL_ACCESS_ROLE_KEY` → 409 | `service.py:71-72` |
| 不可停用 | `set_status` 检查 → 409 | `service.py:102-103` |
| 不可删除 | `delete_role` 检查 `protected` → 409 | `service.py:111-112` |

#### 3.2.3 高权限角色的复制防护

`copy_role`（`service.py:82-98`）禁止复制 `all` 模式的角色：

```python
if src_mode == "all":
    raise HTTPException(403, "不能复制全量工具访问模式的岗位角色；请使用创建接口并走审批流程")
if skill_mode == "all":
    raise HTTPException(403, "不能复制全量技能访问模式的岗位角色；请使用创建接口并走审批流程")
```

**设计意图**（`service.py:84-85` 注释）：防止通过"复制"这条低摩擦路径批量制造高权限角色，绕过创建接口的审批流程。

#### 3.2.4 资源 ID 校验

`validate_resource_ids`（`service.py:129-145`）在创建/更新/批量授权覆盖时校验：

| 资源 | 集合 | 过滤条件 | 错误提示 |
|---|---|---|---|
| 工具 | `external_tools` | `organization_tool_query(main_id, _id in ids, status="active")` | "包含不存在、未启用或非企业级的 MCP/工具" |
| Skill | `skills` | `main_id + _id in ids + enabled=True` | "包含不存在或未启用的企业 Skill" |

数量不匹配即拒绝（`service.py:136,144`）——注意用的是 `count != len(set(ids))`，即**去重后的数量**，与存储时的 `dict.fromkeys` 去重一致。

#### 3.2.5 用户-角色绑定

集合 `end_user_position_roles`（`constants.py:13`），文档字段（`repository.py:115-127`）：

| 字段 | 说明 |
|---|---|
| `main_id` / `user_id` / `role_id` | 三元组 |
| `is_primary` | 是否主角色 |
| `created_by` / `updated_by` / `created_at` / `updated_at` | 审计字段 |

唯一索引：`(main_id, user_id, role_id)`（`repository.py:38-40`）。

**主角色不变式**（`service.py:119-127` 的 `validate_roles`）：

```python
unique = list(dict.fromkeys(str(item) for item in role_ids if str(item)))
if not primary_role_id or primary_role_id not in unique:
    raise HTTPException(400, "必须选择主要岗位角色")            # 主角色必须在角色集内
count = await db[POSITION_ROLE_COLLECTION].count_documents(
    {"main_id": main_id, "_id": {"$in": unique}, "status": "active"})
if count != len(unique):
    raise HTTPException(400, "岗位角色不存在或已停用")# 全部角色必须存在且启用
```

**删除保护**（`service.py:113-115`）：有成员的角色不能删除。

**批量分配**（`repository.py:129-166`）：用 `bulk_write(ops, ordered=True)` 做原子替换，避免部分写入。

#### 3.2.6 特殊授权（Capability Override）

集合 `end_user_capability_overrides`（`constants.py:14`），针对**单个员工**的临时授权：

| 字段 | 说明 | 代码 |
|---|---|---|
| `allow_capabilities` / `deny_capabilities` | 能力白/黑名单 | `position_roles.py:207-208` |
| `allow_tool_ids` / `deny_tool_ids` | 工具白/黑名单 | `:209-210` |
| `allow_skill_ids` / `deny_skill_ids` | Skill 白/黑名单 | `:211-212` |
| `effective_at` | 生效时间 | `:213` |
| `expires_at` | 失效时间（可空= 永不过期） | `:214` |
| `reason` | 授权理由（**必填**，min_length=1） | `position_roles.py:57` |
| `status` | `active` / `revoked` | `position_roles.py:206,254` |

校验规则（`position_roles.py:188-194`）：
1. `expires_at` 必须晚于 `effective_at`
2. 能力键必须在 `AGENT_CAPABILITY_KEYS` 内
3. **同一能力不能同时出现在 allow 和 deny**

生效条件（`position_policy.py:98-104`）：`status=="active"` 且 `effective_at <= now` 且（`expires_at` 为空/不存在/大于 now）。

**deny 优先于 allow**：求值时先union allow 再union deny，最后统一应用（`position_policy.py:175-180`）：

```python
for key in allowed_capabilities:
    if key in capabilities: capabilities[key] = True
for key in denied_capabilities:
    if key in capabilities: capabilities[key] = False     # deny 后执行 → 优先
```

工具/Skill 同理（`position_policy.py:48-60`）：

```python
def allows_external_tool(self, tool_id):
    return tool_id not in self.denied_tool_ids and (self.tool_access_mode == "all" or tool_id in self.tool_ids)
```

#### 3.2.7 员工策略合成算法

`build_effective_policy`（`position_policy.py:116-195`）的完整决策树：

```
                    ┌─ 无角色 且 无绑定 ─┐
                    │                   │
        ┌───────────┴───────────┐       ├── 迁移完成 → 全关（migration-complete-no-role）
        │ 是│ 是       │
        └───┴───────────┘       └── 迁移未完成 → ★全开（legacy-full-access）
             │                              ↑ 风险 R-02
             ▼
    ┌─────────────────────────────────────────┐
    │ 阶段 1：遍历所有 active 角色，OR 合并      │
    │   capabilities[key] |= role.capabilities[key]│
    │   tool_all |= (role.tool_access_mode=="all")│
    │   skill_all |= (role.skill_access_mode=="all")
    │   tool_ids |= role.tool_ids              │
    │   skill_ids |= role.skill_ids            │
    └─────────────────────────────────────────┘
             ▼
    ┌─────────────────────────────────────────┐
    │ 阶段 2：遍历所有生效 override，OR 合并     │
    │   allowed_capabilities |= allow_*        │
    │   denied_capabilities |= deny_*│
    │   tool_ids |= allow_tool_ids             │
    │   skill_ids |= allow_skill_ids           │
    │   denied_tool_ids |= deny_tool_ids       │
    │   denied_skill_ids |= deny_skill_ids     │
    └─────────────────────────────────────────┘
             ▼
    ┌─────────────────────────────────────────┐
    │ 阶段 3：apply deny（覆盖 allow）           │
    │   allow → True；deny → False             │
    │   tool_access_mode = all if tool_all else selected│
    │   skill_access_mode = all if skill_all else selected │
    └─────────────────────────────────────────┘
```

**版本指纹**（`position_policy.py:164,173,194`）：`version = "|".join([f"{role_id}:{updated_at}"..., f"override:{oid}:{updated_at}"...])`，可用于缓存失效判定与排障。

#### 3.2.8 Skill 别名处理

`allows_skill`（`position_policy.py:51-60`）有一个特殊逻辑：

```python
aliases = {skill_id}
if skill_id.startswith("org_skill:"):
    aliases.add(skill_id.removeprefix("org_skill:"))
denied = any(item in self.denied_skill_ids for item in aliases)
allowed = self.skill_access_mode == "all" or any(item in self.skill_ids for item in aliases)
return not denied and allowed
```

**原因**（注释 `:52-54`）：管理员角色的资源用组织资产的原始 id，而员工 Skill 适配器暴露为 `org_skill:<id>` 以避免与个人资产冲突。两者视为**同一个治理身份**——防止用带前缀/不带前缀绕过 deny 列表。

### 3.3 能力键全表

| 能力键 | 中文名（前端标签） | 前端描述 | 展开权限码 |
|---|---|---|---|
| `content_generation` | 内容生成 | 文章、报告、方案等专业内容生产 | `content:generate` |
| `image_generation` | 图片生成 | 直接生成图片或为内容任务生成配图 | `image:generate` |
| `code_generation` | 代码生成 | Code Agent、项目、文件、终端与 Git 操作 | `code:execute` |
| `browser_automation` | 浏览器自动运行 | 允许 Agent 操作本地浏览器完成网页任务 | `browser:automate` |
| `internal_knowledge` | 内部知识检索 | 在既有知识权限范围内检索企业资料 | `knowledge:read` |

来源：`position_roles/constants.py:1-7`（后端） + `apps/admin-web/src/views/position-roles/RoleCapabilityEditor.vue:19-25`（前端标签）。

#### 3.3.1 内部能力引用映射

`position_policy.py:19-26` 定义了 5 条"内部能力 → 能力键"的映射：

| 内部能力引用 | 需求能力键 |
|---|---|
| `content.produce@v1` | `content_generation` |
| `presentation.create@v1` | `content_generation` |
| `document.pdf_retain_pages@v1` | `content_generation` |
| `image.generate@v1` | `image_generation` |
| `browser.task@v1` | `browser_automation` |
| `knowledge.search@v1` | `internal_knowledge` |

判定逻辑（`position_policy.py:62-64`）：

```python
def allows_internal(self, capability_ref: str) -> bool:
    required = INTERNAL_CAPABILITY_REQUIREMENTS.get(capability_ref)
    return required is None or self.allows_capability(required)
```

⚠️ **未注册的 `capability_ref` 默认放行**（`required is None` → True）。这是 fail-open：新增内部能力时若忘记登记映射，该能力对所有员工开放。相关消费点在 `dsh_runtime/profile/tools.py:90`。

### 3.4 权限的授予与回收

#### 3.4.1 岗位角色路径（预设组）

```
授予： admin-web 岗位角色页→ POST /api/position-roles
       → service.create_role() → 写 position_roles
       → repository.audit(action="create")

绑定： admin-web 员工管理 → PUT /api/position-roles/assignments/users/{user_id}
       → service.validate_roles()（主角色在集内 + 全部 active）
       → repository.replace_user_roles()（先delete_many 再 insert_many）
       → repository.audit(action="assign")

回收：把员工角色集替换为不含目标角色的集合（replace_user_roles 是全量替换）
       或 停用角色（status=disabled → position_policy.py:94 的 status:"active" 过滤使其失效）
```

**生效时机**：`MongoEmployeePolicyResolver.resolve()` **每次调用都重新查库**（`position_policy.py:87-113`），无缓存。所以角色变更在下一次工具调用/接口请求即生效，不需要重部署。这与 `permission_grants.py:15-18` 的描述一致。

#### 3.4.2 显式授权路径（细粒度权限码）

API（`api/routes/governance.py:145-195`）：

| 端点 | 方法 | 作用 |
|---|---|---|
| `/api/governance/permissions/grant` | POST | 授予权限码 |
| `/api/governance/permissions/revoke` | POST | 撤销权限码 |
| `/api/governance/permissions` | GET | 列出本租户所有显式授权 |
| `/api/governance/permissions/check` | GET | 管理员自查（⚠️ 见R-08） |

请求体（`governance.py:46-57`）：`code`（必填）、`level`（`tenant|org|user`，默认 `user`）、`org_id`、`user_id`。

写入语义（`permission_grants.py:93-97`）：按 `(tenant_id, level, org_id, user_id, code)` upsert，**幂等**——重复授予同一 scope 是替换而非累加。

唯一索引：`permission_grants` 上的 `(tenant_id, level, org_id, user_id, code)` unique（`permission_grants.py:191-195`）。

#### 3.4.3 三级隔离的求值

`effective_grant_codes`（`permission_grants.py:134-156`）：

```python
scopes = [{"tenant_id": tenant_id, "level": "tenant"}]
if org_id: scopes.append({"tenant_id": tenant_id, "level": "org", "org_id": org_id})
if user_id: scopes.append({"tenant_id": tenant_id, "level": "user", "user_id": user_id})
codes = set()
for scope in scopes:
    for doc in await db[...].find(scope).to_list(length=10_000):
        codes.add(doc.get("code", ""))
return {c for c in codes if c}
```

即**并集（union）语义**，不是"上级含下级"或"用户级未授权时回落组织级"。001 spec FR-5 写的是"**上级含下级，用户级未授权时回落组织级再回落租户级**"（`spec.md:93`）——**这是 spec 与代码的差异**，代码是纯并集，语义上比 spec 更宽松（任一层授权即授权）。详见 [12.3](#123-差异-3)。

⚠️ **性能隐患**：`to_list(length=10_000)` 是硬上限。一个租户若有超过 1 万条授权记录，超出部分会被**静默截断**，导致权限判定错误（既可能误拒也可能漏授）。

⚠️ **`org_id` 从哪来**：`RbacLayer._explicit_grants`（`layers/rbac.py:39-56`）读`ctx.annotations.get("org_id")`。但**没有任何代码写入这个 annotation**——`gatekeeper_internal.py:88-104` 构造 `annotations` 时只放 `approval_token` / `approval_action_id`。因此 `org_id` 恒为 `""`，**组织级授权在任何调用路径上都无法生效**。详见 [12.5](#125-差异-5) 与 R-04。

#### 3.4.4 岗位角色与显式授权的合并

`RbacLayer._effective_codes`（`layers/rbac.py:58-69`）：

```python
codes = set()
roles = await self._role_documents(ctx.tenant_id, ctx.roles)
for role in roles:
    codes.update(expand_role_to_codes(role))      # 岗位角色预设组
codes.update(await self._explicit_grants(ctx))     # 显式授权（三级并集）
ctx.annotations["effective_codes"] = codes          # 单次求值内缓存
return codes
```

两者是**并集**关系：任一来源授予即生效。撤销也是独立的：从岗位角色移除不影响显式授权，反之亦然。

**缓存范围**：`ctx.annotations` 是单次 `Gatekeeper.evaluate` 调用的上下文（`gatekeeper.py:41-62`），因此缓存在一次门禁求值内有效，跨请求不复用。

#### 3.4.5 角色文档查询

`RbacLayer._role_documents`（`layers/rbac.py:23-37`）：

```python
cursor = db["position_roles"].find({"main_id": tenant_id, "_id": {"$in": list(role_ids)}})
```

⚠️ **未过滤 `status`**。对比 `position_policy.py:94` 是 `{"main_id":..., "_id": {"$in": role_ids}, "status": "active"}`。所以**已停用的岗位角色在门禁 RBAC 层仍然生效**（只要 `_id` 还在角色列表里）。而 `gatekeeper_internal.py:69-72` 的 `_resolve_roles` 会返回该员工的所有绑定角色（含已停用角色的绑定记录）。详见 R-05。

### 3.5 权限点在API 层的挂载

#### 3.5.1 三个挂载层级

mogo 的 API 权限**没有统一的依赖注入式权限检查**。实际存在三种粒度：

| 层级 | 机制 | 代码 | 覆盖范围 |
|---|---|---|---|
| **L1 认证** | `Depends(get_current_admin_user)` | `api/deps.py:62-72` | 绝大多数管理端路由 |
| **L2 平台隔离** | `is_reserved_main_id` 检查 | `api/deps.py:70-71` | 同上，隐式 |
| **L3 门禁** | `_enforce_gate()` → `gatekeeper.evaluate()` | `api/routes/tools.py:302,314,320-371` | **仅 2 个工具端点** |

#### 3.5.2 L1/L2 的实际覆盖

`get_current_admin_user`（`deps.py:62-72`）做两件事：

```python
user = await _load_authenticated_account(authorization)
if is_reserved_main_id(user["main_id"]):
    raise HTTPException(403, "Tenant context is required")
return user
```

这带来**两个自动保证**（`deps.py:14-16` 注释明确）：

1. **无bootstrap_main_id 兜底**——租户 ID 只从 JWT subject 取，空值直接 401（`deps.py:30-32`）
2. **平台租户反向隔离**——`__platform__` / `default` 标识访问业务路由自动 403

三个依赖的区分（`deps.py:53-83`）：

| 依赖 | 允许平台管理员 | 允许租户管理员 | 用途 |
|---|---|---|---|
| `get_authenticated_admin` | ✅ | ✅ | 账号自助端点（`/auth/me`） |
| `get_current_admin_user` | ❌ 403 | ✅ | 业务路由（默认） |
| `get_current_platform_admin` | ✅ | ❌ 403 | 租户生命周期 |

#### 3.5.3 哪些路由声明了门禁

**只有 2 个**（`tools.py`）：

| 端点 | 行号 | 说明 |
|---|---|---|
| `POST /api/tools/{tool_id}/test` | `:294-306` | 测试工具连接 |
| `POST /api/tools/test-draft` | `:309-317` | 测试草稿工具 |

**未声明门禁的相邻端点**（同一文件）：

| 端点 | 行号 | 说明 | 风险 |
|---|---|---|---|
| `POST /api/tools/{tool_id}/discover` | `:382-388` | 发现工具能力（会真实调用后端 `/discover`） | 未过门禁 |
| `POST /api/tools/generate-description` | `:391-395` | 生成工具描述（调用后端） | 未过门禁 |

这两个端点都会发起对外部工具后端的实际请求，但**不经过六层门禁**——没有 PII 脱敏、没有风险级判定、没有审批、没有审计事件。详见 R-06。

#### 3.5.4 管理端工具调用的角色回退

`_enforce_gate`（`tools.py:320-371`）有一段关键的回退逻辑：

```python
roles = current_user.get("role_ids") or current_user.get("roles") or []
if not roles and main_id:
    roles = [f"system:{main_id}:full_access_admin"]    # ← 兜底成全能力管理员
```

**原因**（`tools.py:327-331` 注释）：管理端账号**没有岗位角色绑定**——006 的 `end_user_position_roles` 是给*员工*（`end_users`）设计的，管理端 `admin_accounts` 不在这个体系里。没有这个兜底，RBAC 层会因为空角色集fail-closed，导致**每一次管理端工具调用都被拒**。

**后果**：任何管理端账号（只要通过 L1 认证 + 非平台租户）都自动获得 `*` 通配符权限码，等价于 `full_access_admin`。对应测试 `test_governance_rbac_model.py:75-113` 固化了这一行为。

#### 3.5.5 chat-api 侧的门禁调用点

| 调用点 | 行号 | 触发时机 |
|---|---|---|
| `dsh_runtime/turn_admission.py::run_gate_plan` | `:205-270` | 工具调用前 |
| `dsh_runtime/turn_admission.py::admit_skill_selection` | `:273-350` | Skill 选择时（先过 009 钩子，再过门禁） |
| `a2a/outbound.py` | `:100-107` | A2A 出站调用 |

`run_gate_plan` 的执行序列（`turn_admission.py:222-270`）：

```
1. _resolve_gate_plan(tool, request)     ← 019 厚度配置求值
2. record_position_policy_event("gate.plan.resolved")   ← 落岗位审计
3. if not plan.audit_enabled: raise PermissionError     ← floor 违规 fail-closed
4. gatekeeper_client.evaluate(...)       ← 真实调 admin-api 六层链
   ├─ GateDeniedError → record("gate.denied") + raise PermissionError
   └─ 其他 Exception  → raise PermissionError（fail-closed）
5. plan = dataclasses.replace(plan, redacted_request=redacted)  ← 用脱敏后的请求
```

第 3 步是**客户端侧的 floor 校验**：即使 019 配置试图跳过审计层，chat-api 也会拒绝执行（`turn_admission.py:235-236`）。

### 3.6 内部端点的服务间认证

`gatekeeper_internal.py` 的 4 个端点全部用 `_require_service`（`:28-31`）保护：

```python
def _require_service(token: str) -> None:
    expected = str(settings.backend_service_token or "")
    if not token or not expected or not hmac.compare_digest(token, expected):
        raise HTTPException(401, "invalid_service_token")
```

✅ 使用 `hmac.compare_digest`（时序安全比较），且对空 token / 空 expected 都拒绝。

令牌解析（`admin-api/app/core/internal_service_auth.py:6-14`）：

```python
canonical = str(os.getenv("ADMIN_BACKEND_SERVICE_TOKEN") or "").strip()
return canonical or str(configured_alias or "").strip()
```

优先级：`ADMIN_BACKEND_SERVICE_TOKEN` 环境变量 > 前缀兼容别名。

⚠️ **注意**：`settings.backend_service_token` 若为空（未配置环境变量），`_require_service` 会因为 `not expected` 而**拒绝所有请求**——这是 fail-closed 的正确行为，但意味着**未配置该环境变量时门禁完全不可用**，员工侧所有工具调用都会被拒。运维必须配置 `ADMIN_BACKEND_SERVICE_TOKEN`。

覆盖的端点：

| 端点 | 方法 | 用途 | 行号 |
|---|---|---|---|
| `/api/internal/gatekeeper/evaluate` | POST | 运行六层链 | `:77-120` |
| `/api/internal/gatekeeper/decide` | POST | 人工审批决策 | `:133-159` |
| `/api/internal/gatekeeper/approvals` | GET | 审批待办列表 | `:162-193` |
| `/api/internal/gatekeeper/events` | GET | 读取审计轨迹 | `:196-235` |

---

## 4. 数据权限（Data Scope 维度，重点）

### 4.1 数据权限的六套机制

**mogo 没有统一的 Data Scope 模型**。数据可见性由 6 套彼此独立的机制共同实现：

| # | 机制 | 覆盖对象 | 判定位置 | 隔离粒度 |
|---|---|---|---|---|
| 1 | **记忆三域**（017） | `memories` 集合 | `memory/scope.py::visible_to` | personal / workspace / org |
| 2 | **统一上下文可见性**（021） | 4 类 `mogo://` 地址 | `context_space/visibility.py` | 租户（+ 记忆委托 1） |
| 3 | **个人知识授权** | `knowledge_resources` + `resource_grants` | `personal_knowledge/access.py` | owner / 被授权人 |
| 4 | **反馈访问** | 3 类资源 | `resource_feedback/access.py` | owner / 成员 / 岗位策略 |
| 5 | **员工岗位策略** | 工具 / Skill / 能力 | `governance/position_policy.py` | 角色 + 特殊授权 |
| 6 | **多租户 `main_id` 过滤** | 全部业务集合 | `core/tenant.py` + 各查询 | 租户 |

**关键理解**：机制 2（021 地址层）对 resource / skill / session **只做租户级比对**，把细粒度授权委托给后端业务查询。而机制 3/4 才是真正做owner / 授权人级判定的 place。

### 4.2 数据范围模型：六套机制拼装

把6 套机制合起来看，平台实际支持的数据范围（Data Scope）如下：

| 数据范围 | 适用对象 | 判定规则 | 代码 |
|---|---|---|---|
| **本人（personal）** | 记忆 | `viewer_id == memory.owner_id` | `scope.py:107-108` |
| **工作区成员（workspace）** | 记忆 | `is_workspace_member and viewer_id != ""` | `scope.py:109-110` |
| **组织内全员（org）** | 记忆 | `viewer_id != ""`（任意租户成员） | `scope.py:111-112` |
| **全能力管理员特权** | 记忆 | `viewer_role in {"full_access_admin"}` → 任意 scope 可读 | `scope.py:105-106` |
| **资源所有者（owner）** | 个人知识 | `resource.owner_user_id == user_id` | `personal_knowledge/access.py:32` |
| **被授权人（grantee）** | 个人知识 | `resource_grants` 中有 `status=active` 记录 | `personal_knowledge/access.py:35-41` |
| **可再共享（reshare）** | 个人知识 | owner 或 `grant.can_reshare` | `personal_knowledge/access.py:48` |
| **分发成员** | Skill 分发 | owner 或 `skill_distribution_members` 中 `status=active` | `resource_feedback/access.py:36-43` |
| **岗位策略允许** | 组织 Skill | `policy.allows_skill(raw_id)` | `resource_feedback/access.py:48-50` |
| **本租户** | resource/skill/session 地址 | `addr.tenant_id == ctx.tenant_id` | `visibility.py:94,108,119` |
| **本租户 + 本人** | session 地址解析 | 上述 + `chat_sessions.user_id == viewer_id` | `adapters/session.py:90-92` |

⚠️ **注意**：001 spec 和 020 spec 提到的"本部门及子树"（组织架构层级）在代码中**没有对应实现**。组织单元集合是 `org_units`，但它只被用于目录/通讯录展示，**不参与任何数据可见性判定**。详见 [12.9](#129-差异-9)。

### 4.3 六套机制的失败模式对比

| 机制 | 存储不可用时 | 记录未找到时 | 判定为"不可见"时 | 数据加载方|
|---|---|---|---|---|
| 记忆三域 | `list_for_viewer` 返回 `[]`（store.py:170） | — | 从结果中过滤 | Python 内存过滤 |
| 021 地址层 | `get_db()` 返回 None → `ContextNotFoundError` | `ContextNotFoundError`（LookupError） | `ContextVisibilityError`（PermissionError） | Python |
| 个人知识 | 抛异常（无兜底） | `resolve` 返回 None → `require_view` 抛 `LookupError` | `PermissionError("knowledge_forbidden")` | MongoDB 查询 |
| 反馈访问 | 抛异常（无兜底） | `LookupError("feedback_resource_not_found")` | `PermissionError("feedback_forbidden")` | MongoDB 查询 |
| 岗位策略 | `MongoEmployeePolicyResolver` 无 try/except → 抛异常 | — | `PermissionError` | MongoDB 查询 |
| `main_id` 过滤 | 无兜底 | 查询返回空 | — | MongoDB 查询 |

⚠️ **机制 2 的一个语义不一致**：`context_space/visibility.py:1-15` 的模块 docstring 说"不可见候选被**静默裁剪**（never error）"，但 `router.py:85-88` 实际上在 `ContextVisibilityError` 时**记入skipped 后重新抛出**。这是"记轨迹 + 抛异常"，不是"静默裁剪"。021 spec US3 的 Acceptance Scenario 写的是"跨范围/无权限 URI → 在候选中被静默剔除（不报错）"（`spec.md:51`）——**spec 与代码不一致**。详见 [12.7](#127-差异-7)。

### 4.4 统一上下文地址（021）与可见性组合

#### 4.4.1 地址空间总览

`address.py:6-12` 定义了完整的地址 scheme：

```
mogo://memory/<scope>/<owner_id>/<memory_id>/[L0|L1|L2]      ← 017
mogo://resource/doc/<tenantId>/<documentId>/<chunkId>         ← 005
mogo://resource/biz/<tenantId>/<system>/<entityType>/<recordId>  ← 014
mogo://resource/kg/<tenantId>/<nodeId>                        ← 015
mogo://skill/<orgId>/<skillId>[/<version>]                    ← 004
mogo://skill/asset/<assetKey>                                 ← 018
mogo://session/<tenant>/<sessionId>/[L0|L1|L2]                ← 002
```

⚠️ **021 spec 与代码不一致**：spec US1 写 `mogo://resource/biz/<system>/<entity_type>/<record_id>`（**不含 tenant**，`spec.md:19`），`mogo://resource/kg/<node_id>`（**不含 tenant**，`spec.md:20`）。代码强制要求 biz 4 段、kg 2 段且**第一段必须是 tenantId**（`address.py:69-72`）：

```python
if subtype == BIZ and len(id_parts) != 4:
    raise ValueError("resource/biz needs <tenantId>/<system>/<entityType>/<recordId>")
if subtype == KG and len(id_parts) != 2:
    raise ValueError("resource/kg needs <tenantId>/<nodeId>")
```

**代码比 spec 更严格**。这实际上是好事——强制把租户写进地址，使得 `check_resource_visibility` 的租户比对成为可能。详见 [12.6](#126-差异-6)。

#### 4.4.2 解析与规范化

`parse_context_uri`（`address.py:145-163`）按root 分派：

| root | 解析器 | 段数要求 |
|---|---|---|
| `memory` | `app.memory.address.parse_memory_uri`（复用 017，避免漂移） | — |
| `resource` | `ResourceAddress.parse` | doc=3, biz=4, kg=2（均含 tenant） |
| `skill` | `SkillAddress.parse` | asset=1；skill=2~3 |
| `session` | `SessionAddress.parse` | ≥2 |
| 其他 | `raise ValueError(f"unknown context root: {root!r}")` | — |

Tier 段处理（`_split_tier`，`address.py:138-142`）：末段若为 `L0`/`L1`/`L2` 则弹出作为 tier，否则默认 `L0`。

**URL 编解码**：解析时 `unquote`，序列化时 `quote(safe="")`（`address.py:54,59`）。所以含 `/` 或中文的 ID 可以安全编解码。

#### 4.4.3 可见性判定：委托而非重实现

`visibility.py:1-15` 的设计声明：

> The address layer does **not** re-implement authorization. For each tenant it delegates the visibility decision to the backend's *existing* check.

四个分派函数（`visibility.py:50-119`）：

| 函数 | 判定内容 | 空tenant 时的行为 |
|---|---|---|
| `check_memory_visibility` | 委托 017 `visible_to`（**要求传入已存储记录**） | — |
| `check_resource_visibility` | `addr.tenant_id == ctx.tenant_id` | **`return True`**（`visibility.py:91-93`，best-effort 非致命） |
| `check_skill_visibility` | asset → `True`；skill → `identifiers[0] == ctx.tenant_id` | **`return True`**（`:106-107`） |
| `check_session_visibility` | `addr.tenant_id == ctx.tenant_id` | **`return True`**（`:117-118`） |

⚠️ **三个资源/skill/session 判定函数在 `ctx.tenant_id` 为空时全部 fail-open**。虽然注释标为"best-effort, non-fatal"，但在多租户平台上这是危险的默认。调用方 `router.py:73-78` 传入的 `tenant_id` 来自函数参数，理论上应该总是有值。详见 R-07。

#### 4.4.4 记忆可见性：地址是定位符而非凭证

这是 021 里**最重要的安全设计**（R3 审计，2026-10-06 修复）。`visibility.py:50-81`：

```python
def check_memory_visibility(*, addr, ctx, memory=None) -> bool:
    """The address is a **locator, not a credential**. ``scope`` / ``owner_id`` in
    the URI are supplied by the caller and must never decide authorization:
    trusting them let any tenant member read any other member's memory by
    forging ``mogo://memory/personal/<self>/<victim_id>`` (R3 audit, 2026-10-06)."""
    if memory is None:
        log_print("... URI identity is not a credential")
        return False                              # ← fail-closed
    return visible_to(memory, viewer_id=ctx.viewer_id, ...)
```

**攻击与防御对照**：

| 攻击 | 防御 | 测试 |
|---|---|---|
| 伪造 `mogo://memory/personal/<自己>/<受害者id>` 读他人记忆 | 必须传入 `memory`（已存储记录），按记录的 `owner_id` 判定 | `test_address_visibility.py:99-125` |
| 伪造 `mogo://memory/org/...` 把个人记忆伪装成组织记忆 | 同上，用记录的真实 `scope` 判定 | `test_address_visibility.py:120-125` |
| 不提供记录（`memory=None`）试图跳过判定 | `return False` fail-closed | `test_address_visibility.py:128-131` |

对应测试三个用例名字即攻击场景：
- `test_check_memory_visibility_uses_stored_record_not_uri`
- `test_check_memory_visibility_fails_closed_without_record`

#### 4.4.5 Session 地址解析：额外的所有者过滤

`adapters/session.py:86-92`：

```python
# 002 ownership: every other read of ``chat_sessions`` in the app filters by
# ``user_id``. Omitting it here let any tenant member resolve any session —
# including the L2 transcript (R3 audit, 2026-10-06).
doc = await db["chat_sessions"].find_one(
    add_main_scope({"_id": oid, "user_id": str(viewer_id)}, main_id)
```

同样是 R3 审计修复。地址层的租户比对只是粗保护，真正的所有者过滤在**数据加载时**做。这印证了 4.1 节的结论：**021 地址层是"路由+组合"，细粒度授权在数据加载侧**。

#### 4.4.6 各adapter 的分层内容

| adapter | 根 | L0 | L1 | L2 | 行数 |
|---|---|---|---|---|---|
| `MemoryTierAdapter` | memory | `l0_summary or content` | `l1_overview or l0_summary or content` | `content` | 80 |
| `ResourceTierAdapter` | resource/doc | `title_path + text[:200]` | `contextualText or text[:800]` | `text` | 182 |
| | resource/biz | `title or f"{entityType}:{recordId}"` | `type=... source=... + 前 8 个字段` | `content` | |
| | resource/kg | `name or node_id` | `type=... neighbours=前10` | `attributes=...` | |
| `SkillTierAdapter` | skill | — | — | — | 154 |
| `SessionTierAdapter` | session | `title + summary` | `participants=... messages=... active_document=...` | 最近 50 条消息转录 | 136 |

**渐进检索**（017 FR-14）：默认只注入 L0+L1，L2 需显式请求。实现方式是地址末段 tier + `tier` 参数覆盖（`adapters/memory.py:33-35`、`adapters/session.py:46-47`）。

⚠️ **spec 说静默裁剪，代码抛异常**：`router.py:85-92` 在 `ContextVisibilityError` 时记 skipped 后 `raise`。见[12.7](#127-差异-7)。

⚠️ **`_load_biz` 用 URI 里的 tenant 而非认证 tenant**：`adapters/resource.py:114,128`：

```python
tenant_id, system, entity_type, record_id = addr.identifiers   # ← 来自 URI
...
row = await db["business_entity_index"].find_one(
    {"entity_id": {"$in": candidates}, "tenant_id": tenant_id})  # ← 用 URI 的 tenant
```

对比同文件的 `_load_doc`（`:85`）和 `_load_kg`（`:159`）都用**函数参数** `resolve_main_id(tenant_id)`。`_load_biz` 是唯一用 URI 值的。目前因为 `check_resource_visibility` 已比对过 `addr.tenant_id == ctx.tenant_id`，所以不构成直接越权；但如果 `ctx.tenant_id` 为空（fail-open 分支），就变成纯 URI 驱动。详见 R-09。

#### 4.4.7 检索轨迹

`trace.py` 定义 `TraceRecord`（`:18-35`）：

| 字段 | 说明 |
|---|---|
| `trace_id` | uuid4 hex |
| `session_id` / `turn_id` | 绑定会话，支持回看 |
| `candidates` | 命中项：`uri` / `tier_used` / `hit_reason` / `score` |
| `skipped` | 跳过项：`uri` / `reason` |

**落点明确分离**（`trace.py:6-8` 注释）：轨迹落**观测日志**，**不落 001 审计流**，避免污染安全审计日志。高价值命中可由调用方抽样进 001。

⚠️ **未落库**：`build_trace` 只在内存构造并`to_dict()` 返回（`router.py:100-101`），代码里**没有任何持久化调用**。017 FR-16 要求"轨迹落观测日志"。这是 spec 与代码的差异，见 [12.11](#1211-差异-11)。

### 4.5 三域记忆（017）的权限隔离

#### 4.5.1 范围与可见性映射

`scope.py:37-41` 定义固定映射：

```python
SCOPE_VISIBILITY = {
    "personal":   "owner",         # 仅本人
    "workspace":  "members",       # 该工作区成员
    "org":        "organization",  # 全组织
}
```

`Memory.__post_init__`（`scope.py:72-74`）在构造时校验 scope 合法性——**非法 scope 直接 `ValueError`**，fail-closed：

```python
def __post_init__(self) -> None:
    if self.scope not in SCOPE_VISIBILITY:
        raise ValueError(f"unknown memory scope: {self.scope!r}")
```

#### 4.5.2 可见性判定函数

`visible_to`（`scope.py:93-113`）：

```python
if viewer_role in ORG_PROMOTION_ROLES:      # {"full_access_admin"}
    return True                              # 特权：任意 scope 可读
if memory.scope == "personal":
    return viewer_id == memory.owner_id
if memory.scope == "workspace":
    return is_workspace_member and viewer_id != ""
if memory.scope == "org":
    return viewer_id != ""                   # 同租户任意成员
return False                                 # 兜底 fail-closed
```

⚠️ **`org` scope 只检查 `viewer_id != ""`**，不检查 `viewer_id` 是否属于该租户。安全性完全依赖调用方已在 store 层按 `tenant_id` 过滤（`store.py:169`：`find({"tenant_id": main_id})`）。这是一个**隐式契约**：任何绕过 store 直接调用 `visible_to` 的代码都会引入跨租户读取。021 的 `check_memory_visibility` 正是这样直接调用的（`visibility.py:76-81`）——但它传入的 `memory` 来自 `MemoryStore.get()`，已按 tenant 过滤。**契约成立但脆弱**。详见 R-10。

⚠️ **`viewer_role` 的来源存疑**：`visible_to` 的特权分支依赖 `viewer_role`。但 `endpoints/memory.py` 从 `resolve_session_user()` 取 `role`（`:36,114,189`）——而该函数返回的字典里**没有 `role` 键**（详见 R-01）。所以生产环境中 `viewer_role` 恒为 `""`，**全能力管理员的特权分支在记忆可见性上永不生效**。

#### 4.5.3 默认范围策略

`resolve_default_scope`（`scope.py:88-90`）：

```python
return MemoryScope.WORKSPACE.value if multi_user_session else MemoryScope.PERSONAL.value
```

017 FR-3澄清决策：单人会话默认 personal，多人协同（co-presence）会话默认 workspace。

#### 4.5.4 范围升级授权

`can_promote_to_org`（`scope.py:116-118`）+ `promote_to_org`（`:121-132`）：

```python
ORG_PROMOTION_ROLES = frozenset({"full_access_admin"})       # :22

def can_promote_to_org(*, role: str) -> bool:
    return role in ORG_PROMOTION_ROLES

def promote_to_org(memory: Memory, *, role: str) -> Memory:
    if not can_promote_to_org(role=role):
        raise MemoryAccessError(f"role {role!r} may not promote memory to the org scope")
    memory.scope = MemoryScope.ORG.value
    _audit_memory_promoted(memory, role)                     # 审计
    return memory
```

**审计**（`scope.py:135-158`）通过 `feature_audit_bridge.emit_feature_event("017", "memory.promoted", {...})`，且审计失败会留日志（`:148-157`）：

```python
except Exception as exc:
    # 审计失败绝不影响主流程，但必须留痕：静默吞掉会让"审计桥未接线"
    # 与"审计已通过"在日志上无法区分。
    log_print(f"[memory.scope] memory.promoted audit emit failed ...")
```

#### 4.5.5 API 层的授权检查

`endpoints/memory.py` 提供 4 个端点，授权检查：

| 端点 | 授权检查 | 行号 |
|---|---|---|
| `POST /api/memories` | scope 合法性 + org scope 需 `full_access_admin` | `:42-53` |
| `GET /api/memories` | 委托 `store.list_for_viewer` → `scope_filter` | `:117-122` |
| `DELETE /api/memories/{id}` | store 层按 `(memory_id, tenant_id, owner_id)` 过滤 | `:166` |
| `PATCH /api/memories/{id}/promote` | 存在性 + `owner_id != user_id` → 403 + `promote_to_org` 授权 | `:192-201` |

**org scope 直接写入的防护**（`memory.py:46-53`，注释说明了必要性）：

```python
# 017 FR-4: creating at ``org`` scope grants visibility to the whole tenant,
# so it needs the same authorization as promotion. Without this, any user
# could write an org-wide memory directly and bypass ``promote_to_org``.
if scope == MemoryScope.ORG.value and role not in ORG_PROMOTION_ROLES:
    raise HTTPException(403, "org scope requires full_access_admin")
```

⚠️ **但这个检查因R-01 恒真**：`role` 来自 `resolved.get("role")` = `""`，`"" not in ORG_PROMOTION_ROLES` → **恒为 True → 恒 403**。即**当前生产环境下 org scope 记忆既不能创建也不能提升**——功能不可用（fail-closed 但因 bug 而不可用）。

⚠️ **`promote` 端点的数据丢失**（`memory.py:203-210`）：重新保存时只传了5 个字段，**丢失 `l0_summary` / `l1_overview` / `l2_raw` / `tierable` / `summary_generated_at` / `source_session_id` / `source_type` / `summary_refresh_days`**：

```python
await store.save(
    memory_id=promoted.memory_id,
    content=promoted.content,
    owner_id=promoted.owner_id,
    tenant_id=promoted.tenant_id,
    workspace_id=promoted.workspace_id,
    scope=promoted.scope,        # ← 只有这些
)
```

而 `store.save` 是 `replace_one(..., upsert=True)`（`store.py:151-155`）——**全量替换**，未传的字段被删除。提升后该记忆的分层摘要与溯源信息全部丢失，退化为单一 content。这是数据完整性 bug，见R-11。

#### 4.5.6 Store 层的隔离

`MemoryStore` 的每个方法都按 `main_id` 过滤：

| 方法 | 过滤条件 | 行号 |
|---|---|---|
| `save` | `replace_one({"memory_id": mem_id, "tenant_id": main_id})` | `:151-155` |
| `list_for_viewer` | `find({"tenant_id": main_id})` + Python 侧 `scope_filter` | `:169,180-186` |
| `get` | `find_one({"memory_id": memory_id, "tenant_id": main_id})` | `:200` |
| `delete` | `delete_one({"memory_id", "tenant_id", "owner_id"})` | `:210-214` |

`list_for_viewer` 的注释说明了为何在 Python 侧过滤（`store.py:167-168`）：

> Pull all memories for the tenant; visibility is enforced in Python so we do not leak org-scoped data across tenants.

⚠️ **性能隐患**：`to_list(length=500)` 硬上限。租户内记忆超过 500 条时，超出部分被静默截断——即使对当前 viewer 可见的记忆也可能被漏掉。

⚠️ **全表扫描**：每条查询都 `find({"tenant_id": main_id})` 拉全租户数据到内存再过滤。`memories` 集合上没有 `(tenant_id, scope)` 复合索引（`schema.py:50-68` 的 `ensure_indexes` 不含 memories；记忆集合的索引在 chat-api 侧）。

### 4.6 access 模块的统一范式

`personal_knowledge/access.py` 与 `resource_feedback/access.py` 是两套独立的数据访问判定，**没有抽象出统一接口**。但可以归纳出一个共同的判定范式：

#### 4.6.1 范式：resolve → require_*

```
┌─────────────────────────────────────────────────────────────┐
│ 1. resolve(...)   —— 返回"访问上下文对象"，不抛权限异常│
│    · 加载主记录（按 tenant + id +未删除）                  │
│    · 判定所有权                                          │
│    · 若非所有者，加载授权记录                              │
│    · 计算 can_view / can_share / can_manage 布尔           │
│    · 返回不可变 dataclass                                │
├─────────────────────────────────────────────────────────────┤
│ 2. require_view(...)   —— resolve + 检查 can_view           │
│    require_owner(...)  —— require_view + 检查 is_owner     │
│    require_share(...)  —— require_view + 检查 can_share     │
│    失败时抛 PermissionError（权限）或 LookupError（不存在）│
└─────────────────────────────────────────────────────────────┘
```

`PersonalKnowledgeAccess`（`access.py:14-21`）的 6 元组：

| 字段 | 语义 |
|---|---|
| `resource` | 资源文档 |
| `grant` | 授权记录（None= 无授权或是所有者） |
| `is_owner` | 是否所有者 |
| `can_view` | `owner or grant is not None` |
| `can_share` | `owner or grant.can_reshare` |
| `can_manage` | `owner`（只有所有者能管理） |

判定逻辑（`access.py:32-50`）：

```python
owner = str(resource.get("owner_user_id") or "") == str(user_id)
grant = None
if not owner:
    grant = await db["resource_grants"].find_one({
        "main_id": tenant_id, "resource_type": "personal_knowledge",
        "resource_id": str(resource_id), "recipient_user_id": str(user_id),
        "status": "active",
    })
can_view = owner or grant is not None
```

**注意**：`can_view = owner or grant is not None`。授权记录存在即为可见，**不检查授权范围/期限**——`resource_grants` 的查询只过滤 `status="active"`，没有有效期字段过滤。

#### 4.6.2 `FeedbackAccessResolver`：按资源类型分派

`resource_feedback/access.py:19-29` 的分派表：

| resource_type | 处理函数 | 判定依据 |
|---|---|---|
| `skill_distribution` | `_distribution` | owner 或 `skill_distribution_members` 中有 active 记录 |
| `organization_skill` | `_organization_skill` | `policy.allows_skill(raw_id)`（**委托岗位策略**） |
| `personal_knowledge` | `_personal_knowledge` | 委托 `PersonalKnowledgeAccessService.require_view` |
| 其他 | `raise PermissionError("feedback_resource_unsupported")` | — |

**这是唯一一处把 access 模块与岗位策略打通的场景**（`access.py:47-50`）：

```python
raw_id = resource_id.removeprefix("org_skill:")
policy = await MongoEmployeePolicyResolver().resolve(main_id, user_id)
if not policy.allows_skill(raw_id):
    raise PermissionError("feedback_forbidden")
```

`FeedbackSubject`（`access.py:10-15`）携带 4 个字段，其中 `activity_recipient_user_id` 用于通知定向（`access.py:64`：`grant.granted_by_user_id or owner_user_id`）。

#### 4.6.3 两套 access 模块的差异

| 维度 | `personal_knowledge/access.py` | `resource_feedback/access.py` |
|---|---|---|
| 风格 | 面向对象（Service 类） | 面向过程（Resolver 类 + 模块函数） |
| 返回值 | 6 字段 dataclass（含 3 个能力布尔） | 4 字段 dataclass（无能力布尔） |
| 授权查询 | `resource_grants` 集合 | 分散在 `skill_distribution_members` / 岗位策略 / 委托 personal_knowledge |
| 分派 | 无（单一资源类型） | 3 种类型分派 |
| 软删除过滤 | `deleted_at: None`（`:28,74,81`） | 部分（`status: "active"`） |
| 抛错类型 | `LookupError`（不存在）/ `PermissionError`（无权） | 同 |

⚠️ **`personal_knowledge` 忽略传参 `main_id` 之外租户来源**：`access.py:26`调 `resolve_main_id(main_id)`，然后所有查询都用这个值。调用方传的 `main_id` 若为 `""` 会被解析成 `"default"`——落进单租户兼容模式。

### 4.7 多租户隔离（020）

#### 4.7.1 `main_id` 的解析与过滤

`core/tenant.py`（36 行）定义 3 个函数：

```python
DEFAULT_MAIN_ID = "default"                                    # :6

def resolve_main_id(value=None) -> str:                       # :9-11
    main_id = str(value or "").strip()
    return main_id or DEFAULT_MAIN_ID

def main_scope_filter(main_id=None) -> Dict[str, Any]:         # :14-25
    resolved = resolve_main_id(main_id)
    if resolved == DEFAULT_MAIN_ID:
        return {"$or": [{"main_id": resolved},
                        {"main_id": {"$exists": False}},
                        {"main_id": ""}, {"main_id": None}]}
    return {"main_id": resolved}

def add_main_scope(query, main_id=None) -> Dict[str, Any]:     # :28-36
    # 把 main_scope_filter 与 query 合并（$or 时用 $and）
```

⚠️ **`default` 是兼容模式而非真租户**：当 `main_id` 解析为 `"default"` 时，filter 变成 `$or`，**匹配所有没有 `main_id` 字段的文档**。这意味着：

- 单租户部署（未配置多租户）：所有历史无 `main_id` 的文档都能访问 ✅ 符合预期
- 多租户部署：若某处漏传 `main_id`，查询会**匹配到所有历史无 `main_id` 标记的文档** ⚠️

020 spec FR-017 明确要求"**MUST NOT** 在缺少企业标识时回退到任何默认企业"（`spec.md:210`），Edge Case 也写了"请求上下文企业标识缺失或为保留值 → 拒绝，绝不回退默认租户"（`spec.md:171`）。**`resolve_main_id` 的行为与 spec 直接冲突**。见[12.8](#128-差异-8)。

代码注释显示这是刻意的兼容设计（`admin-api/app/api/deps.py:14-16` 说的是另一层——token 层已无兜底）。`resolve_main_id` 是**数据层**的兜底，与认证层的严格性不一致。

#### 4.7.2 租户 ID 如何贯穿请求链路

```
[登录/会话建立]
  admin-api: JWT subject.main_id（唯一来源，deps.py:30）
  chat-api: end_user_sessions.main_id（end_user_session.py:59）
                    │
                    ▼
[业务请求]
  admin-api: get_current_admin_user → user["main_id"]（deps.py:45）
             ├─ 拒绝 reserved 标识（deps.py:70-71）
             └─ 路由内_main_id(user) → "main_id" or "default"（position_roles.py:69-70）
                    │
                    ▼
  chat-api: resolve_session_user → main_id（end_user_session.py:59）
           └─ 各端点自行 resolve_main_id(...) 过滤
                    │
                    ▼
[门禁]
  GateContext.tenant_id（gatekeeper.py:49）
    ├─ RbacLayer: position_roles.find({"main_id": tenant_id})（rbac.py:35）
    ├─ permission_grants:所有查询带tenant_id（permission_grants.py:146-150）
    ├─ risk: risk_tiers.find({"tenant_id": tenant_id}) →回退全局（risk.py:93-95）
    └─ audit: gate_events.tenant_id = ctx.tenant_id（audit.py:52）
                    │
                    ▼
[数据层]
  所有集合查询带 main_id / tenant_id
```

**不一致点**：admin-api 路由内用 `str(user.get("main_id") or "default")`（如 `position_roles.py:70`、`tools.py:296`），chat-api 用 `resolve_main_id()`。两者对空值的处理结果相同（都是 `"default"`），但 admin-api 侧是**散落的内联表达式**，容易漏。

#### 4.7.3 平台管理员的反向隔离

020 FR-019："系统 MUST 拒绝以平台管理标识访问租户业务接口"（`spec.md:212`）。

实现（`admin-api/app/api/deps.py:70-71, 76-83`）：

```python
# 业务路由
async def get_current_admin_user(authorization=None) -> dict:
    user = await _load_authenticated_account(authorization)
    if is_reserved_main_id(user["main_id"]):
        raise HTTPException(403, "Tenant context is required")
    return user

# 平台路由
async def get_current_platform_admin(authorization=None) -> dict:
    user = await _load_authenticated_account(authorization)
    if not is_platform_main_id(user["main_id"]):
        raise HTTPException(403, "Platform administrator privileges are required")
    return user
```

这是**双保险**：业务路由排除平台租户，平台路由要求平台租户。符合 FR-019 与 Edge Case "保留的平台管理标识被当作普通租户处理 → 必须排除，不得为其创建组织与岗位角色"。

⚠️ **chatai-api 侧无对应保护**：chat-api 的租户解析走 `resolve_main_id`（回退 `"default"`），没有 `is_reserved_main_id` 检查。若 chat-api 收到 `main_id="__platform__"`，会当作普通租户处理。

#### 4.7.4 租户清理（tenant_purge）与数据权限

`services/tenant_purge.py`（689 行）实现 020 US6（彻底清理）。与数据权限的关联：清理必须覆盖**所有**按 `main_id` 分区的集合，包括权限数据。

两组清单（`tenant_purge.py:40-123` 与 `:127-150`）：

| 组| 数量 | 权限相关集合 |
|---|---|---|
| `TENANT_SCOPED_COLLECTIONS` | ~60 | `position_roles`、`end_user_position_roles`、`end_user_capability_overrides`、`position_role_migrations`、`position_role_audit_logs`、`resource_grants`、`org_quota_policies`、`user_quota_policies`、`user_quota_overrides`、`token_usage_logs`、`memories`、`organizations`、`end_users`、`end_user_sessions` 等 |
| `TENANT_GOVERNANCE_COLLECTIONS` | ~20 | `gate_events`、`gate_approvals`、`gatekeeper_rules`、`permission_grants`、`pii_policies`、`risk_tiers`、`autonomy_matrix`、`quota_counters`、`hook_rules` 等 |

**关键设计约束**（`tenant_purge.py:34-39` 注释）：

> this list must cover *both* admin-api and chat-api collections — a tenant's data lives in both services, and purge is executed by admin-api only. Cross-check it against the collection constants used by `app.services.setup_cleanup.SETUP_SCOPED_COLLECTIONS` before adding a collection to either service, otherwise tenant data survives a purge (SC-005).

即**新增集合必须同步两个清单**，否则租户数据在清理后残留。这是运维最容易踩的坑。

流程（`tenant_purge.py:1-17`）：
1. 前置：租户必须是 `archived` 状态（FR-028，任务启动时重新检查）
2. Phase mongo：删除所有 `main_id` 匹配的行
3. Phase vectors：调 document-parser 清除 Weaviate 向量
4. Phase files：删除本地存储目录
5. 任一 phase 失败 → 租户保持 `archived`，失败原因写 `archive_reason`，任务标记 `failed`（FR-033）
6. 全部成功 → 租户翻转为 `purged`（墓碑），30 天后自动删除

### 4.8 脱敏（pii.py / redaction.py）在数据权限中的角色

#### 4.8.1 定位：脱敏不是授权

**脱敏（Redaction）解决的是"数据最小化"，不是"数据可见性"。** 二者是正交维度：

| 维度 | 问题 | 实现 |
|---|---|---|
| 可见性（Visibility） | 谁能读到这份数据 | RBAC + scope + tenant |
| 脱敏（Redaction） | 读到的人能看到什么 | 5 类 PII × 4 策略 |

举例：员工 A 有 `internal_knowledge` 能力 → 能读知识库（可见性 allow）→ 但读到的是 `138****0000`（脱敏生效）。

#### 4.8.2 PII 分类与识别器

`pii.py:41`定义 5 类，`:69-86` 定义 7 个识别器（按**特异性从高到低**排序）：

| 类别 | 正则 | 顺序理由 |
|---|---|---|
| `private_key` | PEM 块（`BEGIN...PRIVATE KEY` 到 `END...`） | 最具体，必须先匹配 |
| `private_key` | `AIza...`(Google) / `AKIA...`(AWS) / `ghp_...`(GitHub) / `sk-...`(OpenAI) | 密钥前缀 |
| `id_card` | `\d{17}[\dXx]` | 18 位身份证 |
| `bank_card` | `\d{16,19}` | 16-19 位卡号 |
| `phone` | `(?<!\d)1[3-9]\d{9}(?!\d)` | 中国手机号 |
| `phone` | `(?<!\d)0\d{2,3}-?\d{7,8}(?!\d)` | 中国固定电话 |
| `email` | RFC 风格 | 最不具体 |

**重叠消解**（`pii.py:105-111`）：

```python
for match in recognizer.pattern.finditer(text):
    start, end = match.span()
    if any(not (end <= s or start >= e) for s, e, _, _ in taken):
        continue                    # 与已认领的命中重叠 → 跳过
    taken.append((start, end, recognizer.type, value))
```

即**先认领的（更具体的）胜出**。例：`110101199003077896` 不会被识别为 `bank_card`（18 位），因为 `id_card` 先认领了整个 span。测试 `test_governance_pii.py`（119 行）覆盖此行为。

#### 4.8.3 四种脱敏策略

`pii.py:127-151` 的 `apply_strategy`：

| 策略 | 效果 | 示例 |
|---|---|---|
| `remove` | 替换为空串 | 私钥 → `""` |
| `hash` | SHA-256 前 12 字符 + `…` | 身份证 → `a1b2c3d4e5f6…` |
| `abstract` | 类型占位符；手机号保留前 3 | 邮箱 → `[EMAIL]`；手机 → `138****` |
| `mask` | 数字：前 3 + `*` + 后 4；其他：前 2 + `*` + 后 2 | 卡号 → `6222021234567890` → `622******7890` |

⚠️ **未知策略回退到 `mask`**（`pii.py:128`）：`strategy if strategy in STRATEGIES else "mask"`。fail-safe（保守）方向正确。

#### 4.8.4 默认策略与租户覆盖

默认（`pii.py:46-52` / `schema.py:41-47`，两份常量同步）：

| PII 类 | 默认策略 |
|---|---|
| `private_key` | `remove` |
| `id_card` | `hash` |
| `bank_card` | `mask` |
| `phone` | `mask` |
| `email` | `abstract` |

生效策略计算（`redaction.py:47-73` 的 `_policies_for`）：

```python
policies = dict(DEFAULT_STRATEGY)                            # 内置默认
cursor = db["pii_policies"].find({"tenant_id": {"$in": ["", ctx.tenant_id]}})
for row in rows:
    if row.get("tenant_id"):                                 # 租户行→ 覆盖
        policies[pii_type] = strategy
    elif pii_type not in policies:                           # 全局行 → 补充缺失
        policies[pii_type] = strategy
```

即**全局默认 <全局 `pii_policies` 行< 租户 `pii_policies` 行**。

⚠️ **策略加载失败会静默降级**（`redaction.py:63-72`）：

```python
except Exception as exc:
    # Do not swallow this. A failed policy load silently degrades
    # redaction to the built-in defaults, and "no tenant override
    # configured" is indistinguishable from "policy store is down"
    # once the failure is dropped (QA R5).
    logger.warning("pii policy load failed for tenant %s; using built-in defaults: %s", ...)
```

修复后保留了 WARNING 日志——这是 QA R5 的修复，注释明确说明"不要静默吞掉"。

⚠️ **001 spec 要求租户覆盖需 006 授权**（`pii.py:26-27`："An override requires 006 authorization at the admin boundary (enforced at the CRUD endpoint)"）——**但代码里没有 `pii_policies` 的 CRUD 端点**（`api/routes/` 下无此文件）。策略只能直接改数据库。见 [12.13](#1213-差异-13)。

#### 4.8.5 脱敏的生效点与回传

`RedactionLayer.evaluate`（`redaction.py:75-96`）：

```
1. 取有效策略
2. 遍历 ctx.request 和 ctx.response 的**所有字符串字段**
3. find_pii → redact_text → 原地覆写 payload[key]
4. 记录 trace（types 计数 + fingerprints）
5. 返回 ALLOW（永不拒绝）
```

**关键设计：原地改写 + 回传**（`gatekeeper_internal.py:8-11, 116-118`）：

```python
"request": ctx.request,   # ← 脱敏后的 body
```

chat-api 侧接收（`turn_admission.py:265-269`）：

```python
redacted = gate_result.get("request")
if isinstance(redacted, dict):
    plan = dataclasses.replace(plan, redacted_request=redacted)
```

001 spec FR-7 要求"脱敏**作用于工具请求体之前**（remove 后该字段不出现在请求体）"。代码实现了这一点：chat-api 转发给后端的是脱敏后的 body。测试 `test_gatekeeper_internal.py:79-119` 固化了此契约。

**审计指纹**（`redaction.py:29-41` 的 `RedactionTrace`）：

```python
{"types": {"phone": 2}, "fingerprints": ["a1b2c3d4e5f6a7b8"], "count": 2}
```

`fingerprint()`（`pii.py:184-186`）= SHA-256 前 16 字符。**明文永不进审计**（`redaction.py:11-13`）。

⚠️ **限制**：`RedactionLayer._redact_fields`（`redaction.py:98-111`）只处理 `payload` 的**顶层字符串字段**：

```python
for key, value in list(payload.items()):
    if not isinstance(value, str) or not value:
        continue          # ← 非字符串（dict/list/int）跳过
```

所以**嵌套结构中的 PII 不会被脱敏**。若工具参数形如 `{"payload": {"phone": "138..."}}`，内层手机号会原样通过。

---

## 5. 配额（Quota）

### 5.1 配额与权限的关系

配额在门禁链中排第 5 位（`config.py:29`），位于 RBAC（功能权限）之后、audit（审计）之前。语义上是**授权后的资源约束**：先确认"能不能做"，再确认"还有没有额度"。

拒绝时返回 429（`gatekeeper.py:35`），`quota` 层的 detail 带 `scope`（`layers/quota.py:156`）。

### 5.2 两套配额体系

平台存在**两套独立实现的配额系统**：

| 体系 | 位置 | 消费者 | 维度 |
|---|---|---|---|
| **020 token 预算** | `org_quota_policies` / `user_quota_policies` / `user_quota_overrides` | chat-api 业务路径 + admin-api 门禁第 5 层 | token 数（周期：hourly/daily/monthly） |
| **001 调用计数** | `quota_counters` | 仅 admin-api 门禁第 5 层（遗留） | 调用次数（窗口：min/day/month） |

`layers/quota.py:1-16` 的模块 docstring 明确说明了这个关系：

> **Wiring note (2026-10-03)**: this repo has no `quota_limits` collection and no consumer for "call-count limits" (the original spec's three dimensions). What does exist is feature 020's real token-quota system (`org_quota_policies` / `user_quota_policies`), already enforced on the chat path. Rather than build a second, parallel quota model, this layer delegates to that system... The legacy call-count path (`limits_resolver` + `quota_counters`) is kept intact for backward compatibility and is still what the unit tests exercise.

**即：001 spec 定义的"三维调用计数"在生产中不是主路径，只有测试在跑。** 见 [12.4](#124-差异-4)。

### 5.3 门禁第5 层的判定逻辑

`QuotaLayer.evaluate`（`layers/quota.py:144-180`）两步：

```python
# 1) 真实预算（020）
if self._credit_checker is not None:
    reason = self._credit_checker(ctx.tenant_id, ctx.user_id)
    if hasattr(reason, "__await__"): reason = await reason
    if reason:
        return GateVerdict(DENY, "quota", str(reason),
                          detail={"scope": "budget", "tool": ctx.tool})
# 2) 遗留调用计数
limits = await self._limits_for(ctx.tenant_id)
if not limits:
    return GateVerdict(ALLOW, "quota", "within budget")     # ← 无配置即放行
exceeded = await store.check_and_consume(...)
```

**生产装配**（`layers/__init__.py:36-39`）：

```python
if name == "quota":
    layers.append(factory(credit_checker=quota.default_credit_checker))
else:
    layers.append(factory())
```

即 `limits_resolver` **永远为 None** → 第 2 步永远在 `if not limits` 处返回 ALLOW。测试 `test_governance_us4_us5.py:230-237` 固化了"生产层集必须安装 020 checker"。

⚠️ **这意味着 `quota_counters` 集合在生产中永远不会被写入**（只有 `check_and_consume` 会写，而它只在 `limits_resolver` 提供了 limits 时被调用）。

#### 5.3.1 `default_credit_checker`

`layers/quota.py:31-54`：

```python
async def default_credit_checker(tenant_id, user_id) -> Optional[str]:
    try:
        db = get_db()
        if db is None: return None
        user = await db["end_users"].find_one({"_id": user_id}) if user_id else None
        summary = await get_quota_summary(tenant_id, user or {})
    except Exception:
        return None                # ← fail-open（有意）
    if summary.get("unlimited"): return None
    if int(summary.get("remainingPoints") or 0) <= 0:
        return "token 额度已用尽（001 配额层复用 020 配额体系）"
    return None
```

⚠️ **注意 `get_quota_summary` 是 admin-api 版本**（`from app.core.quota_policy import get_quota_summary`，`layers/quota.py:39`），**不是** chat-api 那个带 `2099d5f` 修复的版本。两份实现已漂移，见 [5.4](#54-2099d5f-修复与双实现漂移)。

⚠️ **注释与代码语义不符**：`:46-48` 注释说 "The gate's own denial path stays fail-closed"，但 `AuditLayer` 之外的层失败都是 fail-open。实际上"fail-closed"指的是 `AuditLayer`（审计落库失败 → deny），与 quota 无关。注释措辞容易误导。

### 5.4 `2099d5f` 修复与双实现漂移

#### 5.4.1 修复内容

提交 `2099d5f`（2026-10-08）"fix(chat-api): treat orgs with no provisioned quota as unlimited instead of blocking"，改了 chat-api 侧 `quota_policy.py`（+43/-3）：

```
- space_type inference now also reads org.org_name / org.space_type, not only
  user.org_name, so personal-space orgs (e.g. setup-test-*) are no longer
  misclassified as enterprise.
- A personal space with total_points unset/0 is returned as unlimited rather
  than remaining=0 (avoid '个人赠送额度已用尽' for unconfigured orgs).
- An enterprise org with no provisioned allocation (org total 0 and no per-user
  override) is returned as unlimited instead of raising
  '当前企业分派额度已用尽，请联系企业管理员调整额度'.
```

三处 fallback（`services/chat-api/app/core/quota_policy.py`）：

| 位置 | 条件 | 返回 |
|---|---|---|
| `:178-190` | `org.points_unlimited` 为真 | unlimited（跳过所有用量统计） |
| `:198-213` | 个人空间且 `total_points <= 0` | unlimited |
| `:241-256` | 企业空间且 `org_total <= 0 且 user_total <= 0` | unlimited |

以及 `assert_quota_available`（`:283-285`）加了短路：

```python
if summary.get("unlimited"):
    return summary                # ← 新增
if int(summary.get("remainingPoints") or 0) <= 0:
    ...
```

#### 5.4.2 漂移：admin-api 侧没有这些修复

对比两服务的 `get_quota_summary`：

| 维度 | chat-api（已修复） | admin-api（未修复） |
|---|---|---|
| `points_unlimited` 短路 | ✅ `:178-190` | ✅ `:179-192` |
| 个人空间 `total<=0` → unlimited | ✅ `:198-213` | ❌ 无，`remainingPoints = max(0, total-used) = 0` |
| 企业空间 `org_total<=0 且 user_total<=0` → unlimited | ✅ `:241-256` | ❌ 无，`remaining = max(0, min(0-used, 0-orgUsed)) = 0` |
| `assert_quota_available` 的 unlimited 短路 | ✅ `:283-285` | ✅ `:255`（有 `and not summary.get("unlimited")`） |
| `ensure_org_quota_policy` 写 `unlimited: True` | ❌ **不写** | ✅ **写**（`:87`） |
| `space_type` 推断读 org 字段 | ✅ `:169` | ❌ 只读 `user.space_type`（`:169`） |

**后果**：门禁第 5 层（`layers/quota.py`）调的是 **admin-api 版本**。对于一个"未配置配额的租户"：

- chat-api 业务路径：unlimited → 放行 ✅
- admin-api 门禁第 5 层：`org_policy` 若已由 `ensure_org_quota_policy` 创建则 `unlimited=True` → 放行 ✅
- 但若 `org_quota_policies` 中存在**历史记录**（`$setOnInsert` 不会更新已存在文档），没有 `unlimited` 字段 → `bool(org_policy.get("unlimited", False))` = **False**（`admin-api/app/core/quota_policy.py:203`）→ 走限额路径 → `org_total=0` → `remaining=0` → **门禁 DENY(429)**

即：**存量租户的未配置配额会阻断所有工具调用，即使 chat-api 侧已放行。** 见 [12.14](#1214-差异-14)。

⚠️ 两服务 `utc_now()` 也不一致：admin-api 返回 aware datetime（`:27`），chat-api 返回 **naive** datetime（`chat-api/app/core/quota_policy.py:26`：`datetime.now(timezone.utc).replace(tzinfo=None)`）。跨服务比较需注意。这是提交 `75d30eb` 修复的另一条线。

### 5.5 配额策略的数据模型

| 集合 | 主键 | 关键字段 | 代码 |
|---|---|---|---|
| `org_quota_policies` | `main_id` | `total_tokens`、`unlimited`、`period`、`timezone`、`status` | `admin-api/app/core/quota_policy.py:13,84-95` |
| `user_quota_policies` | `(main_id, scope_type, scope_id)` | `quota_tokens`、`period`、`priority`、`status` | `:14,105-115` |
| `user_quota_overrides` | — | `extra_tokens`、`expires_at`、`status` | `:15,147-163` |
| `token_usage_logs` | — | `total_tokens`、`created_at`、`status`、`user_id` | `:12,118-130` |

**周期窗口**（`period_window`，`:44-66`）：支持 `hourly` / `daily` / `monthly`，按 `timezone`（默认 `Asia/Shanghai`）计算本地边界后转 UTC。

**用户策略解析优先级**（`resolve_user_policy`，`:133-144`）：

```
1. user_quota_policies where scope_type="user" AND scope_id=user_id
   （按 priority desc, updated_at desc 排序取第一条）
2. org_quota_policies 的 period
3. ensure_default_user_policy（scope_type="all", scope_id="", priority=10）
```

**剩余额度计算**（有限额路径，`:225-231`）：

```python
remaining = max(0, min(user_total - user_used, org_total - org_used))
```

即**用户配额与组织配额的较小值**。`user_total = max(0, base_user_total + extra)`（`:230`），其中 `extra` 是生效的 override 之和。

**不限额时的返回值**（`:208-223`）：

| 字段 | 值 |
|---|---|
| `totalPoints` | `-1` |
| `remainingPoints` | `-1` |
| `unlimited` | `True` |
| `usedPoints` | **真实用量**（仍统计用于报表） |
| `orgTotalPoints` / `orgRemainingPoints` | `-1` |

即**不限额时仍记录用量但不阻断**，符合 020 FR-035/036。

### 5.6 配额相关的死代码

| 符号 | 位置 | 状态 |
|---|---|---|
| `QuotaLayer` 的 `limits_resolver` 路径 | `layers/quota.py:137-142` | 生产永不触发（`build_layers` 不传 resolver） |
| `quota_counters` 集合 | `layers/quota.py:25` | 生产永不写入 |
| `WINDOWS` 常量 | `layers/quota.py:28` | 只被遗留路径使用 |

⚠️ `WINDOWS` 的窗口定义与 020 的 `VALID_PERIODS` **不一致**：

| 体系 | 支持值 |
|---|---|
| 001 遗留（`layers/quota.py:28`） | `min`(1分钟) / `day`(1440分钟) / `month`(43200分钟) |
| 020 实际（`admin-api/app/core/quota_policy.py:18`） | `hourly` / `daily` / `monthly` |

001 spec FR-8 说"每分钟/每天/每月"（`spec.md:96`），代码的 `WINDOWS` 与之一致；但生产实际走 020 的 `hourly/daily/monthly`。**生产没有"每分钟"窗口**。

---

## 6. 审计（Audit）

### 6.1 六个审计落点

平台没有单一审计流，而是 6 个集合各自承载：

| # | 集合 | 写入方 | 记录内容 | 代码 |
|---|---|---|---|---|
| 1 | `gate_events` | admin-api `AuditLayer` | **每次**门禁判定的通过/拒绝事件 | `layers/audit.py:17,49-65` |
| 2 | `system_audit_logs` | admin-api `SystemAuditMiddleware` | 所有变更类 HTTP 请求（POST/PUT/PATCH/DELETE） | `system_audit/constants.py:1` |
| 3 | `position_role_audit_logs` | admin-api `PositionRoleRepository.audit` + chat-api `record_position_policy_event` | 岗位角色 CRUD + 员工能力使用/拒绝 | `position_roles/constants.py:16` |
| 4 | `pii_policies`（兼审计） | admin-api `RedactionLayer` | 脱敏指纹写入 `gate_events` 的 annotation | `layers/redaction.py:29-41` |
| 5 | `enterprise_tool_audit` | chat-api | 工具调用的投影结果 | `system_audit/query.py:76,88` |
| 6 | `audit_logs` | admin-api | 历史目录/组织操作 | `system_audit/query.py:101` |

001 spec FR-9 要求"所有门禁通过/拒绝事件落审计日志，含层号、风险级、自主级别、时间戳"（`spec.md:97`）。

### 6.2 `gate_events` 的字段模型

`layers/audit.py:49-62`：

```python
document = {
    "event_id": uuid.uuid4().hex,
    "occurred_at": _utcnow(),              # UTC aware
    "tenant_id": ctx.tenant_id,
    "user_id": ctx.user_id,
    "roles": list(ctx.roles),
    "tool": ctx.tool,
    "risk_level": ctx.risk_level,          # R0..R4
    "autonomy_level": ctx.autonomy_level,  # L1..L5
    "decision": verdict.decision.value,    # allow/deny/require_approval
    "layer": verdict.layer,                # 拒绝发生的层
    "reason": verdict.reason,              # 人类可读原因
    "detail": verdict.detail,              # 层特有 detail
}
```

索引（`layers/audit.py:40-41`）：

```python
[("tenant_id", 1), ("occurred_at", -1)]                              # gate_events_tenant_time
[("tenant_id", 1), ("decision", 1), ("occurred_at", -1)]             # gate_events_tenant_decision_time
```

⚠️ **只按 `tenant_id` 建索引，没有 `user_id`**。运维排查"某用户做了什么"需要全表扫。

### 6.3 审计 fail-closed

`AuditLayer.evaluate`（`layers/audit.py:63-75`）：

```python
try:
    await db[GATE_EVENTS_COLLECTION].insert_one(document)
except Exception:
    return GateVerdict(DENY, self.name, "审计落库失败（fail-closed）")
return GateVerdict(ALLOW, self.name, "audited")
```

且 `gatekeeper.py:150-151` 采纳这个 deny：

```python
if audit_verdict is not None and audit_verdict.decision is not GateDecision.ALLOW:
    return audit_verdict
```

注释（`gatekeeper.py:147-149`）说明这是 2026-10-03 的修复——之前 gatekeeper **丢弃**这个返回值，导致"fail-closed 承诺是装饰性的"。测试 `test_governance_gatekeeper.py:97-118` 固化。

**含义**：`gate_events` 集合不可写（如磁盘满、Mongo 宕机）时，**所有工具调用被拒**。这是安全优先的取舍，运维需知晓。

### 6.4 特殊工具名的审计事件

有几类审计事件通过 `tool` 字段编码，而非真实工具名：

| `tool` 字段值 | 写入方 | 含义 | 代码 |
|---|---|---|---|
| `gate.config.update` | `config.py:166` | 门禁配置变更 | `config.py:159-174` |
| `gate.permissions.grant` / `.revoke` | `permission_grants.py:174` | 权限码授予/撤销 | `:167-182` |
| `gate.matrix.<L>:<R>` | `risk.py:161` | 自主矩阵单元格修改 | `:154-169` |

这些事件的 `layer` 字段分别是 `config_admin` / `permission_admin` / `matrix_admin`——**不是六层之一**。查审计时按 `layer` 过滤需注意。

⚠️ **`tenant_id` 被写成空串**（`config.py:163`、`risk.py:158`）：配置变更和矩阵变更的审计事件**不带租户标识**，因为它们是全局配置。这样按租户查审计会漏掉这些事件。

### 6.5 `system_audit_logs`（管理端 HTTP 审计）

`SystemAuditMiddleware`（`system_audit/middleware.py:15-36`）拦截所有 `MUTATING_METHODS = {POST, PUT, PATCH, DELETE}`（`constants.py:3`）的已认证请求。

**上下文提取**（`middleware.py:39-56`）：

```python
authorization = request.headers.get("authorization")
if not authorization.startswith("Bearer "): return None      # 未认证 → 不审计
payload = decode_access_token(...)
subject = payload.get("sub")
main_id = subject.get("main_id"); actor = subject.get("username")
if not main_id or not actor: return None
```

⚠️ **未认证的变更请求不审计**。若攻击者用无效 token 发 POST，请求会 401 且**没有审计记录**。这降低了暴力破解的可探测性。

**结果判定**（`middleware.py:90-97`）：

```python
def _audit_result(status_code, operation_result=None):
    marker = str(operation_result or "").strip().lower()
    if marker in {"success", "passed"}: return "success"
    if marker in {"failed", "failure", "error"}: return "failed"
    return "success" if status_code < 400 else "failed"
```

即**业务显式结果优先于 HTTP 状态**。业务端点通过响应头 `X-MOVO-Operation-Result` 声明真实结果（如 `tools.py:305`）。测试 `test_system_audit.py:54-57` 固化。

**脱敏保证**（`middleware.py:71-84`）：记录字段**不含请求体**。测试 `test_system_audit.py:13-37` 明确断言 `"body" not in item["details"]`，且输入文档带 `"body": {"apiKey": "must-not-leak"}`。

### 6.6 `position_role_audit_logs`（岗位审计）

**写入源1：admin-api 岗位操作**（`position_roles/repository.py:168-178`）：

```python
{"_id": uuid4, "main_id": main_id, "actor": actor, "action": action,
 "target_type": target_type, "target_id": target_id,
 "details": details, "created_at": utcnow()}
```

`action` 取值：`create` / `update` / `delete` / `enable` / `disable` / `assign` / `bulk_assign` / `complete_migration` / `grant_override` / `revoke_override`（散见`service.py:66,79,107,117` 与 `position_roles.py:153,163,178,222,258`）。

**写入源 2：chat-api 员工能力事件**（`chat-api/app/governance/audit.py:10-22`）：

```python
{"main_id": tenant_id, "actor": user_id, "action": action,
 "target_type": "employee", "target_id": user_id,
 "details": {"target": target, **details}, "created_at": utcnow()}
```

`action` 取值（按 `^capability\.` 正则被归类为"Agent 能力"活动）：

| action | 触发点 | 含义 |
|---|---|---|
| `capability.denied` | `dsh_chat.py:33`、`turn_admission.py:331` | 能力被拒（code_generation / skill） |
| `capability.used` | `turn_admission.py:347` | 能力使用成功 |
| `gate.plan.resolved` | `turn_admission.py:226` | 门禁计划求值 |
| `gate.denied` | `turn_admission.py:258` | 门禁拒绝 |
| `hook.denied` | `turn_admission.py:304` | 009 钩子拒绝 |
| `memory.promoted` | `memory/scope.py:141` | 记忆提升（经 feature_audit_bridge） |

⚠️ **只有 `^capability\.` 前缀的 action 被 `_agent` 分类查询**（`system_audit/query.py:74`）。`gate.*` / `hook.*` / `memory.promoted` 会落到 `_legacy` 分类（`query.py:96`：`action: {"$not": {"$regex": r"^capability\."}}`）——即门禁拒绝事件在"Agent 能力"视图里**看不到**，要去"历史管理操作"视图查。

### 6.7 审计查询接口

`SystemAuditQuery`（`system_audit/query.py`）提供 4 个视图：

| 方法 | 数据源 | 分类 | 行号 |
|---|---|---|---|
| `_management` | `system_audit_logs` | `category="management"` | `:54-70` |
| `_agent` | `position_role_audit_logs` + `enterprise_tool_audit` | `category="agent"` | `:72-91` |
| `_legacy` | `audit_logs` + `position_role_audit_logs`（非 capability） | `category="legacy"` | `:93-106` |
| `overview` | 统计 4 个指标 | — | `:41-52` |

`overview` 的 4 个指标（`query.py:41-52`）：

```python
{"managementOperations": <system_audit_logs 计数>,
 "failedOperations": <result=failed 计数>,
 "agentActivities": <position_role_audit_logs 中 ^capability. 计数>,
 "permissionDenials": <action=capability.denied 计数>}
```

⚠️ **`permissionDenials` 只统计 `capability.denied`**，不含 `gate.denied`（门禁层拒绝）。真正的权限拒绝事件分散在两个 action 名下，指标口径不完整。

⚠️ **关键词搜索用正则**（`query.py:61-67`）：`re.escape(keyword)` 后作为 `$regex`。已正确转义，但**未加 `$options: "i"` 之外的复杂度限制**，且对 4 个字段做 `$or` 正则——大关键词集下可能慢查询。

### 6.8 审计覆盖度分析

| 事件类型 | 覆盖 | 说明 |
|---|---|---|
| 工具调用通过 | ✅ 100% | `AuditLayer` 无条件执行 |
| 工具调用拒绝 | ✅ 100% | audit 提前拆出（`gatekeeper.py:128-137`） |
| 审计落库失败 | ✅ 转为拒绝 | 2026-10-03 修复 |
| 门禁配置变更 | ✅ | `gate.config.update` |
| 权限码授予/撤销 | ✅ | `gate.permissions.*` |
| 矩阵修改 | ✅ | `gate.matrix.*` |
| 岗位角色 CRUD | ✅ | `position_role_audit_logs` |
| 员工能力使用/拒绝 | ✅ | `capability.used` / `capability.denied` |
| 记忆提升 | ✅ | `memory.promoted`（经 bridge） |
| 数据可见性拒绝 | ❌ | `ContextVisibilityError` 不落审计 |
| 配额拒绝 | ✅ | `gate_events` 的 quota 层 |
| 审批挂起 | ✅ | `gate_events` 的 approval 层 + `gate_approvals` |
| 未认证的 HTTP 请求 | ❌ | `middleware.py:41` 直接跳过 |

⚠️ **数据可见性拒绝不落审计**：`visibility.py` / `adapters/*` 抛 `ContextVisibilityError` 时**没有任何审计写入**。越权尝试（如伪造 memory 地址）不留痕。这是审计覆盖的一个实质缺口，见 R-12。

---

<!-- Part 2 将在下方继续：第 7-14 章 -->
## 7. 完整判定流程 Walkthrough

本章用4 个真实场景逐步追踪。每步标注命中哪一层、返回什么、以及证据位置。

### 7.1 场景一：普通员工发起一次对话

**场景设定**：员工 `u1` 在 `t1` 租户，绑定岗位角色 `system:t1:engineer`（能力：`content_generation=true`、`internal_knowledge=true`，工具 `selected:["crm"]`）。他发起一次对话并调用了 `crm` 工具。

#### 步骤 1：chat-api 认证

```
请求 → /api/chat/message（dsh_chat.py）
```

`_resolve_session_user(authorization)`（`end_user_session.py:25-70`）：

| 检查 | 代码 | 结果 |
|---|---|---|
| token 解析 | `:27-30` | `token_id` 有效 |
| 会话存在且 active | `:35-39` | ✅ |
| 未过期 | `:44-53` | ✅ |
| 用户有效 | `:60-64` | ✅ |
| **返回** | `:70` | `{"session": {...}, "user": {...}, "main_id": "t1"}` |

⚠️ 注意返回只有 3 个键。这正是 R-01 的根源。

#### 步骤 2：代码能力检查（若任务涉及代码）

`_require_code_capability("t1", "u1")`（`dsh_chat.py:30-39`）：

```python
policy = await MongoEmployeePolicyResolver().resolve("t1", "u1")
if not policy.allows_capability("code_generation"):
    await record_position_policy_event(..., action="capability.denied", target="code_generation")
    raise HTTPException(403, detail={"code": "position_role_denied", ...})
```

`build_effective_policy`（`position_policy.py:116-195`）求值：

| 输入 | 值 | 来源 |
|---|---|---|
| `end_user_position_roles` | `role_ids = ["system:t1:engineer"]` | `position_policy.py:89-91` |
| `position_roles` | 1 个 active 角色 | `:93-95` |
| `end_user_capability_overrides` | 无生效记录 | `:98-104` |
| `position_role_migrations` | `status="complete"` | `:105` |

合成结果：

```python
capabilities = {"content_generation": True, "image_generation": False,
                "code_generation": False, "browser_automation": False,
                "internal_knowledge": True}
tool_access_mode = "selected";  tool_ids = frozenset({"crm"})
skill_access_mode = "selected"; skill_ids = frozenset()
```

`allows_capability("code_generation")` → **False** → 记录 `capability.denied` → **HTTP 403**。

若任务是普通内容生成（`content_generation`），此检查不触发，继续。

#### 步骤 3：门禁计划求值

`admit_skill_selection`（`turn_admission.py:273-350`），假设 `tool="crm"`：

```python
if tool:
    gate = await run_pre_tool_use(...)        # 009 声明式钩子，fail-closed
    if gate.denied: raise PermissionError(...)
```

`_resolve_gate_plan`（`turn_admission.py:195-202`）→ `build_gate_plan`（`gate_adapter.py:54-84`）：

```
mode = "thick"（默认）
layers = ["identity", "rbac", "redaction", "approval", "quota", "audit"]
assert_floor_intact(...)   ← floor 校验（gate_adapter.py:70）
backend = backend_for(gatekeeper_ready)  ← "gatekeeper"
```

`assert_floor_intact` 若发现 audit 被跳过会抛异常（`turn_admission.py:235-236` 也会二次检查）。

记录审计事件 `gate.plan.resolved` → `position_role_audit_logs`。

#### 步骤 4：调用 admin-api 门禁

`gatekeeper_client.evaluate()`（`gatekeeper_client.py:49-106`）：

```json
POST http://127.0.0.1:8100/api/internal/gatekeeper/evaluate
Header: X-MOVO-Service-Token: <ADMIN_BACKEND_SERVICE_TOKEN>
{
  "tool": "crm", "tenantId": "t1", "userId": "u1",
  "roles": [],                          // ← 注意：客户端不传角色
  "request": {...}, "sessionId": "...",
  "scope": "tool", "approvalToken": "", "approvalActionId": "",
  "harnessMode": "thick"
}
```

⚠️ **`roles` 传空**。admin-api 的 `_resolve_roles`（`gatekeeper_internal.py:52-74`）会回填：

```python
rows = await db["end_user_position_roles"].find(
    {"main_id": "t1", "user_id": "u1"}, {"role_id": 1}).to_list(length=100)
→ ["system:t1:engineer"]
```

#### 步骤 5：六层判定

**层 1 identity**（`layers/identity.py:15-35`）：

| 检查 | 值 | 结果 |
|---|---|---|
| `ctx.tenant_id` | `"t1"` | ✅ 非空 |
| `ctx.user_id or ctx.roles` | `"u1"` / `["system:t1:engineer"]` | ✅ |
| 写 annotation | `ctx.annotations["subject"] = {...}` | — |

→ **ALLOW** `"subject resolved"`

**层 2 RBAC**（`layers/rbac.py:71-96`）：

```python
required = ctx.annotations.get("required_code") or required_code_for_tool("crm")
          = required_code_for_tool("crm") = "crm:execute"     # rbac_model.py:137-143
```

`_effective_codes`（`layers/rbac.py:58-69`）：

| 来源 | 结果 |
|---|---|
| `position_roles.find({"main_id":"t1", "_id": ["system:t1:engineer"]})` | 1 个角色文档 |
| `expand_role_to_codes(role_doc)` | `system_key` 非 `full_access_admin` → 展开 `capabilities`：`internal_knowledge` → `knowledge:read` |
| `_explicit_grants` | `org_id` 为空（见 R-04）→ 只查 tenant + user 级 → 无授权 → `set()` |

```python
granted = {"knowledge:read"}
```

`has_permission({"knowledge:read"}, "crm:execute")`（`rbac_model.py:104-134`）：
- `have.resource("knowledge") != need.resource("crm")` → continue → **False**

→ **DENY(403)** `"权限码不满足：需要 crm:execute"`

**审计**：`_record(audit_layer, ...)` → `gate_events` 插入：

```json
{"tenant_id": "t1", "user_id": "u1", "roles": ["system:t1:engineer"],
 "tool": "crm", "decision": "deny", "layer": "rbac",
 "reason": "权限码不满足：需要 crm:execute",
 "detail": {"required": "crm:execute", "granted": ["knowledge:read"]}}
```

**回到 chat-api**（`gatekeeper_client.py:100-105`）：

```python
if decision != "allow":
    raise GateDeniedError("权限码不满足：需要 crm:execute", layer="rbac", status_code=403)
```

**记录审计** `gate.denied` → `position_role_audit_logs`（`turn_admission.py:255-261`）

→ **raise PermissionError("001 门禁拒绝：权限码不满足：需要 crm:execute")**

#### 场景一的结论

**这是一个重大发现**：一个绑定了 `crm` 工具的岗位角色员工，调用 `crm` 工具时**被 RBAC 层拒绝**。

原因：`CAPABILITY_TO_CODES`（`rbac_model.py:25-31`）只定义了 5 个粗粒度能力 → 权限码的映射，**`tool_access_mode` / `tool_ids` 完全没有对应的权限码**。也就是说岗位角色的工具授权（006 FR-5）在门禁 RBAC 层（001）**不被识别**。

员工要通过门禁，必须由管理员额外在 `permission_grants` 里显式授予 `<tool_id>:execute` 权限码。而员工策略层（`position_policy.py:48-49`的 `allows_external_tool`）是**独立生效**的——见场景二。

### 7.2 场景二：员工调用外部工具端点（chat-api 侧）

**场景设定**：同上一场景。员工从对话框触发 `crm` 工具调用，走 chat-api 的 `/api/tools/...` 端点。

#### 步骤 1-3：同场景一（认证、策略求值）

#### 步骤 4：`allows_external_tool` 判定

`api/endpoints/external_tools.py:54-55`：

```python
policy = await MongoEmployeePolicyResolver().resolve(main_id, user_id)
if tool_id is not None and not policy.allows_external_tool(tool_id):
    ...拒绝
```

`allows_external_tool("crm")`（`position_policy.py:48-49`）：

```python
tool_id not in self.denied_tool_ids                    # "crm" not in frozenset() → True
and (self.tool_access_mode == "all" or tool_id in self.tool_ids)
    # "selected" != "all" → 但 "crm" in frozenset({"crm"}) → True
→ True✅
```

**这里通过了**。

#### 步骤 5：工具列表过滤

`external_tools.py:68`：

```python
data = [row for row in data if policy.allows_external_tool(str(row.get("id") or row.get("_id") or ""))]
```

员工只看到自己被授权的工具。

#### 场景二的结论

**同一个授权（岗位角色的 `tool_ids`）在两条路径上行为不同**：

| 路径 | 判定依据 | `crm` 是否通过 |
|---|---|---|
| chat-api `/api/tools/*` | `allows_external_tool`（岗位策略） | ✅ 通过 |
| admin-api 六层门禁 | `has_permission({"knowledge:read"}, "crm:execute")` |❌ 拒绝 |

这是**两套并行的授权体系**（006 岗位策略 vs 001 权限码），二者没有打通。001 spec FR-6 说"岗位角色作为权限码预设组，向下兼容"（`spec.md:94`）——代码里只有 `capabilities`（5 个能力键）被打通，`tool_ids` / `skill_ids` 没有。见[12.2](#122-差异-2)。

**运维含义**：如果只配置了岗位角色的工具白名单，员工在对话框里能选到工具，但实际调用会被门禁拒绝。如果只配置了 `permission_grants` 权限码，员工在对话框里**看不到**该工具。两边必须都配。

### 7.3 场景三：管理员配置模型（管理端）

**场景设定**：租户 `t1` 的管理员 `admin1`（`admin_accounts`，无岗位角色绑定）在管理端测试一个 MCP 工具连接。

#### 步骤 1：admin-api 认证

`get_current_admin_user`（`deps.py:62-72`）：

| 检查 | 值 | 结果 |
|---|---|---|
| Bearer token 解码 | `sub = {username, session_id, main_id}` | ✅ |
| `username` / `session_id` / `main_id` 均非空 | `deps.py:31-32` | ✅ |
| `admin_sessions.status == "active"` | `deps.py:35-36` | ✅ |
| `admin_accounts.status == "active"` | `deps.py:39-40` | ✅ |
| `is_reserved_main_id("t1")` | `deps.py:70` | False → 放行 |

返回 `{**user, "main_id": "t1", "role_name": "组织管理员", ...}`（`deps.py:44-50`）。

#### 步骤 2：工具存在性与租户归属

`tools.py:298-300`：

```python
doc = await db.external_tools.find_one(organization_tool_query(main_id, _id=str(tool_id)))
if not doc: raise HTTPException(404, "企业工具连接不存在")
```

#### 步骤 3：门禁强制

`_enforce_gate(tool_id, "t1", current_user, payload)`（`tools.py:320-371`）：

```python
roles = current_user.get("role_ids") or current_user.get("roles") or []
# → 管理端账号无这些字段 → []
if not roles and main_id:
    roles = [f"system:{main_id}:full_access_admin"]    # → ["system:t1:full_access_admin"]
```

测试 `test_governance_rbac_model.py:75-113` 固化了这一行为（`assert captured["roles"] == ["system:t1:full_access_admin"]`）。

风险级解析（`tools.py:355-357`）：

```python
ctx.risk_level = await governance_risk.risk_level_for(tenant_id="t1", tool="tool-1")
```

若 `risk_tiers` 中无注册 → 默认 `R0`（`risk.py:35,98-99`）。

自主级别（`tools.py:358`）：

```python
ctx.autonomy_level = str(current_user.get("autonomy_level") or "L3")    # → "L3"
```

#### 步骤 4：六层判定

**层 1 identity**：`tenant_id="t1"`, `user_id` 为空（`current_user.get("user_id") or current_user.get("id")`，管理端账号字段名可能不同）但 `roles` 非空 → ✅ ALLOW

**层 2 RBAC**：

```python
required = required_code_for_tool("tool-1") = "tool-1:execute"
```

⚠️ `PermissionCode.parse("tool-1:execute")`：
- resource = `"tool-1"`（**注意：不是 `"tool"`**）
- `required_code_for_tool`（`rbac_model.py:137-143`）：`resource = (tool or "").strip() or "tool"`，因为 `"tool-1"` 非空所以直接用。resource 含连字符不影响解析（只按 `:` split）。

`expand_role_to_codes({"system_key": "full_access_admin", ...})` → `{"*"}`（`rbac_model.py:91-92`）

`has_permission({"*"}, "tool-1:execute")` → `"*" in granted` → **True** ✅

→ ALLOW `"permission granted"`

**层 3 redaction**：读 `pii_policies` → 应用默认策略 → 改写 `ctx.request` → ALLOW

**层 4 approval**：

```python
risk = ctx.risk_level or "R0"      # "R0"
level = ctx.autonomy_level or "L1" # "L3"
decision = await matrix_decision(level="L3", risk="R0")   # → "allow"（schema.py:35）
```

→ ALLOW `"matrix L3xR0=allow"`

**层 5 quota**：

```python
reason = await default_credit_checker("t1", "")
# → user 为 {}（user_id 空）→ get_quota_summary("t1", {})
# → space_type 推断：user.space_type 为空，org_name 为空 → "enterprise"
# → org_policy 若 unlimited=True → return None
```

→ ALLOW `"within budget"`

**层 6 audit**：写`gate_events` → ALLOW

→ **最终 ALLOW**，工具测试执行（`tools.py:304`）

#### 步骤 5：HTTP 审计

`SystemAuditMiddleware` 记录到 `system_audit_logs`：

```json
{"main_id": "t1", "actor": "admin1", "category": "management",
 "module": "tools", "module_label": "工具与 MCP",
 "action": "create_or_execute", "method": "POST",
 "route": "/api/tools/{tool_id}/test", "target": "/api/tools/tool-1/test",
 "result": "success", "status_code": 200, "duration_ms": 123, "client_ip": "..."}
```

（`action` 由 `METHOD_ACTIONS["POST"]` 决定，`constants.py:20`）

#### 场景三的结论

**管理端账号自动获得 `*` 通配符权限**，绕过了岗位角色体系。这是 2026-10-03 审计的有意修复（`tools.py:327-331` 注释）——不修的话管理端工具调用全被拒。

**代价**：任何能通过 admin-api 认证的非平台租户账号都能执行任意工具，无粒度区分。`role_name` 字段（`deps.py:42`）虽存在但**不参与门禁判定**。

**R3 工具的风险**：若工具被注册为 R3，L3×R3 = `require_approval`（`schema.py:35`）→ 返回 409 + token。但**审批由同一个服务令牌驱动**（`gatekeeper_internal.py:143`），即需要 chat-api 或另一个持有服务令牌的调用方来`decide`。管理端前端是否有审批 UI 需确认——`gatekeeper_internal.py:162-193` 提供了 `GET /approvals` 列表端点，但**没有管理端路由调用它**（`api/router.py` 中无对应挂载）。

### 7.4 场景四：跨部门读取知识库

**场景设定**：员工 `u1`（`t1`/`engineering`）尝试读取员工 `u2`（`t1`/`marketing`）的个人知识库资源。

#### 路径 A：走个人知识 access 模块

`PersonalKnowledgeAccessService.require_view(main_id="t1", user_id="u1", resource_id="res-1")`：

```python
resource = await db["knowledge_resources"].find_one(
    {"_id": "res-1", "main_id": "t1", "deleted_at": None})
# → 找到，owner_user_id = "u2"

owner = ("u2" == "u1")   # → False

grant = await db["resource_grants"].find_one({
    "main_id": "t1", "resource_type": "personal_knowledge",
    "resource_id": "res-1", "recipient_user_id": "u1", "status": "active"})
# → None（u2 没分享给 u1）

can_view = False or (None is not None)   # → False
```

`require_view`（`access.py:52-58`）→ `raise PermissionError("knowledge_forbidden")`

→ **拒绝** ✅

若 `u2` 分享给了 `u1` 且 `can_reshare=True`，则 `can_share=True`，`u1` 可再分享（`access.py:48`）。

#### 路径 B：走 021 统一地址

`mogo://resource/doc/t1/doc-1/chunk-2`：

```python
addr = ResourceAddress.parse("doc/t1/doc-1/chunk-2")
# → ResourceAddress(subtype="doc", identifiers=("t1","doc-1","chunk-2"), tier="L0")

check_resource_visibility(addr, ViewerContext(viewer_id="u1", tenant_id="t1"))
# → addr.tenant_id ("t1") == ctx.tenant_id ("t1") → True ✅
```

然后 `_load_doc`（`adapters/resource.py:78-108`）：

```python
row = await db["knowledge_document_chunks"].find_one({
    "main_id": resolve_main_id("t1"),         # "t1"
    "document_id": "doc-1", "chunk_id": "chunk-2",
    "$or": [{"chunk_stage": "rag"}, {"chunk_stage": {"$exists": False}}]})
```

⚠️ **这里只按租户过滤，没有按部门/个人归属过滤**。

**结论**：路径 B **只做租户隔离，不做部门或个人隔离**。如果 `doc-1` 是 `u2` 的个人知识库文档，`u1` 可以通过 `mogo://resource/doc/...` 地址读到内容。

**这是场景四的核心结论，也是 R-09 的关联风险。**

对比：路径 A（个人知识 access 模块）做了 owner + grant 判定。路径 B（021 地址层）只做租户判定。

021 spec US3 的设计意图（`spec.md:41-48`）：

> doc → 005 `retrieval_access_policy`（租户/组织隔离）
> biz → 014 `bizdata:read`（001 权限码）
> kg → 015 `kg:read`（001 权限码）

即 spec 要求委托给 005 的 `retrieval_access_policy` 和 001 的权限码。**代码里 `check_resource_visibility` 只比对租户，没有调用 `retrieval_access_policy`，也没有检查权限码**。见 [12.10](#1210-差异-10)。

#### 场景四的补充：memory 根的行为对比

若改为读 `mogo://memory/personal/u2/m-9`：

```python
memory = await MemoryStore().get(tenant_id="t1", memory_id="m-9")
# → 找到 scope="personal", owner_id="u2"

check_memory_visibility(addr, ViewerContext(viewer_id="u1", tenant_id="t1"), memory=memory)
  → visible_to(memory, viewer_id="u1", viewer_role="", is_workspace_member=False)
  → scope == "personal" → return ("u1" == "u2")  → False
→ ContextVisibilityError ✅
```

**memory 根做了正确的所有者判定，resource 根没有。**

差异根源：memory 根有 `visible_to` 可委托（017 提供），resource 根的委托目标（005 的 `retrieval_access_policy`）**在代码里不存在**。

### 7.5 四个场景的汇总对照

| 场景 | 认证 | 岗位策略 | 六层门禁 | 数据可见性 | 最终结果 |
|---|---|---|---|---|---|
| 一：员工对话调 crm | ✅ t1/u1 | ✅ 允许 crm | ❌ **RBAC deny** | — | **403 权限码不满足** |
| 二：员工调工具端点 | ✅ | ✅ 允许 crm | — | — | ✅ 放行 |
| 三：管理员测工具 | ✅ t1 | —（无角色绑定） | ✅ ALLOW（`*`） | — | ✅ 放行 |
| 四 A：跨部门读个人知识 | ✅ | — | — | ❌ `knowledge_forbidden` | **拒绝** ✅ |
| 四 B：跨部门读 resource 地址 | ✅ | — | — | ⚠️ **仅租户校验** | **放行** ⚠️ |

**核心洞察**：场景一 vs 二 展示了 **006 岗位策略与 001 权限码未打通**；场景四 A vs B 展示了 **021 地址层对 resource 根的委托是不完整的**。这两组差异是本文档最重要的发现。

---

## 8. 配置与运维

### 8.1 环境变量

#### 8.1.1 门禁相关（必需）

| 变量 | 服务 | 默认值 | 作用 | 代码 |
|---|---|---|---|---|
| `ADMIN_BACKEND_SERVICE_TOKEN` | 两侧 | 空 | chat-api → admin-api 内部端点的服务令牌。**未配置则门禁完全不可用**（所有调用被 401） | `admin-api/app/core/internal_service_auth.py:13` |
| `ADMIN_API_BASE_URL` | chat-api | `http://127.0.0.1:8100` | admin-api 地址 | `chat-api/app/core/config.py:118` |
| `GATE_LAYERS` | admin-api | 空 | **死代码**：见 [附录 D](#14-附录d死代码与未接线清单) | `governance/config.py:127-132` |

⚠️ `ADMIN_BACKEND_SERVICE_TOKEN` 的解析优先级（`internal_service_auth.py:13-14`）：

```python
canonical = os.getenv("ADMIN_BACKEND_SERVICE_TOKEN")
return canonical or configured_alias        # 前缀兼容别名
```

若两侧配置的令牌不一致，chat-api 的所有门禁调用会401 → `GateDeniedError` → **所有工具调用被拒**。

#### 8.1.2 记忆与上下文相关

| 变量 | 默认值 | 作用 | 代码 |
|---|---|---|---|
| `MEMORY_SUMMARY_REFRESH_DAYS` | 30 | L0/L1 摘要的过期窗口 | `chat-api/app/memory/store.py:31-40` |
| `MEMORY_L2_HARD_MAX_BYTES` | — | `tierable=false` 内容的硬上限（**按编码后字节数比较**，非字符数） | `store.py:112-118` |

`store.py:107-111` 注释说明了字节 vs 字符的重要性：

> The limit is named `..._BYTES` and is compared against the *encoded* size: `len()` counts characters, so CJK content (3 bytes/char) would otherwise slip through at up to 3x the configured ceiling.

#### 8.1.3 认证相关

| 变量 | 服务 | 作用 | 代码 |
|---|---|---|---|
| `END_USER_AUTH_SECRET` | chat-api | 员工会话 token 的签名密钥 | `chat-api/app/services/end_user_session.py:28` |
| admin JWT secret | admin-api | 管理端 access token 签名 | `admin-api/app/api/deps.py:23` |

⚠️ 两个密钥任一为空或泄露，后果是**可伪造任意用户的会话/令牌**。

### 8.2 集合与索引清单

#### 8.2.1 治理层集合（admin-api）

`schema.py:50-68` 的 `ensure_indexes()`：

| 集合 | 索引 | 名称 | 行号 |
|---|---|---|---|
| `gatekeeper_rules` | `kind` unique | `gate_config_kind` | `:56` |
| `risk_tiers` | `(tenant_id, tool)` | `risk_tier_tenant_tool` | `:57` |
| `autonomy_matrix` | `cell` unique | `autonomy_matrix_cell` | `:58` |
| `pii_policies` | `(tenant_id, pii_type)` | `pii_policy_tenant_type` | `:59` |
| `quota_counters` | `(tenant_id, dimension, subject, window)` | `quota_counter_key` | `:60-63` |
| `gate_events` | `(tenant_id, occurred_at desc)` | `gate_events_tenant_time` | `:64-66` |

`layers/audit.py:40-41` 额外建：

| 集合 | 索引 | 名称 |
|---|---|---|
| `gate_events` | `(tenant_id, occurred_at desc)` | `gate_events_tenant_time`（与上重复） |
| `gate_events` | `(tenant_id, decision, occurred_at desc)` | `gate_events_tenant_decision_time` |

`permission_grants.py:187-195`：

| 集合 | 索引 | 名称 |
|---|---|---|
| `permission_grants` | `(tenant_id, level, org_id, user_id, code)` **unique** | `permission_grant_key` |

⚠️ `gate_events` **没有 `user_id` 索引**，按用户查审计需全集合扫。

#### 8.2.2 岗位角色集合（admin-api）

`repository.py:28-50` 的 `ensure_indexes()`：

| 集合 | 索引 | unique | 名称 |
|---|---|---|---|
| `position_roles` | `(main_id, name)` | ✅ | `position_role_main_name_unique` |
| `position_roles` | `(main_id, system_key)` | ✅（partial：`system_key` 存在且为 string） | `position_role_main_system_unique` |
| `end_user_position_roles` | `(main_id, user_id, role_id)` | ✅ | `user_position_role_unique` |
| `end_user_position_roles` | `(main_id, role_id)` | ❌ | `position_role_members` |
| `end_user_capability_overrides` | `(main_id, user_id, expires_at)` | ❌ | `user_capability_override_active` |
| `position_role_migrations` | `main_id` | ✅ | `position_role_migration_main` |
| `position_role_audit_logs` | `(main_id, created_at desc)` | ❌ | `position_role_audit_main_created` |

⚠️ **缺 `memories` 集合的 `(tenant_id, scope)` 索引**——见[4.5.6](#456-store-层的隔离)。

#### 8.2.3 其他权限相关集合

| 集合 | 索引定义位置 | 说明 |
|---|---|---|
| `end_user_position_roles` | `repository.py:38-43` | 员工角色绑定 |
| `end_user_capability_overrides` | `repository.py:44-46` | 特殊授权 |
| `resource_grants` | 无显式索引定义 | 个人知识授权，**建议手工加 `(main_id, resource_type, resource_id, recipient_user_id, status)`** |
| `memories` | 无 | 记忆记录，**建议加 `(tenant_id, scope)`** |
| `skills` / `external_tools` | 依赖业务查询 | 岗位角色资源校验 |

### 8.3 前端配置界面

#### 8.3.1 管理端页面

| 文件 | 行数 | 职责 |
|---|---|---|
| `apps/admin-web/src/views/position-roles/PositionRolesPage.vue` | 131 | 岗位角色列表 + CRUD + 员工分配 |
| `apps/admin-web/src/views/position-roles/RoleCapabilityEditor.vue` | 92 | 能力开关 + 工具/Skill 访问模式编辑器 |
| `apps/admin-web/src/api/positionRoles.ts` | 99 | 13 个 API 封装 |

路由挂载（`admin-api/app/api/router.py:14`）：

```python
api_router.include_router(position_roles.router, prefix="/position-roles", tags=["position-roles"])
```

前端调用的 13 个端点（`positionRoles.ts:45-99`）：

| 函数 | HTTP | 路径 |
|---|---|---|
| `listPositionRoles` | GET | `/api/position-roles` |
| `roleResourceCatalog` | GET | `/api/position-roles/catalog/resources` |
| `createPositionRole` | POST | `/api/position-roles` |
| `updatePositionRole` | PUT | `/api/position-roles/{id}` |
| `copyPositionRole` | POST | `/api/position-roles/{id}/copy` |
| `setPositionRoleEnabled` | PATCH | `/api/position-roles/{id}/status` |
| `deletePositionRole` | DELETE | `/api/position-roles/{id}` |
| `pendingRoleAssignments` | GET | `/api/position-roles/assignments/pending` |
| `completeRoleMigration` | POST | `/api/position-roles/assignments/migration/complete` |
| `assignUserRoles` | PUT | `/api/position-roles/assignments/users/{userId}` |
| `bulkAssignUserRoles` | POST | `/api/position-roles/assignments/bulk` |
| `listCapabilityOverrides` | GET | `/api/position-roles/assignments/users/{userId}/overrides` |
| `createCapabilityOverride` | POST | `/api/position-roles/assignments/users/{userId}/overrides` |
| `revokeCapabilityOverride` | DELETE | `/api/position-roles/assignments/overrides/{id}` |

⚠️ **前端无 `dataScope`（数据范围）配置界面**。管理端能配的只有功能权限（能力开关 + 工具/Skill 白名单）。数据权限要么在后端 `resource_grants` 集合手工写，要么走个人知识的分享 UI。

⚠️ **`/api/governance/permissions/*` 的 4 个端点无前端入口**——`apps/admin-web/src/api/` 下无 `governance.ts`。权限码授予/撤销只能通过 API 直接调。

#### 8.3.2 对话端（user-web）

`apps/user-web/src/` 下**没有任何权限/角色相关代码**（grep `allows_capability` / `positionRole` / `permission` 均无命中）。

员工的能力限制**完全在服务端生效**：

| 限制点 | 服务端位置 | 客户端表现 |
|---|---|---|
| 代码生成任务 | `dsh_chat.py:30-39` | 收到 403 `position_role_denied` |
| Skill 选择 | `turn_admission.py:328-336` | `PermissionError("当前岗位未开通该 Skill")` |
| 工具列表 | `external_tools.py:68` | 只返回授权的工具 |
| Skill 列表 | `catalog.py:36` | 组织 Skill 被过滤 |
| 能力快照 | `auth.py:143-145` | `profile.agentPolicy` 返回给前端供 UI 灰化 |

`auth.py:143-145` 把策略快照注入登录/档案响应：

```python
policy = await MongoEmployeePolicyResolver().resolve(resolve_main_id(main_id), str(user.get("_id") or ""))
profile["agentPolicy"] = policy.public_snapshot()
```

`public_snapshot()`（`position_policy.py:66-79`）返回：

```python
{"capabilities": {...}, "toolAccessMode": ..., "toolIds": [...], "deniedToolIds": [...],
 "skillAccessMode": ..., "skillIds": [...], "deniedSkillIds": [...],
 "roleIds": [...], "roleNames": [...], "migrationPending": ..., "version": ...}
```

⚠️ 该快照包含 `deniedToolIds` / `deniedSkillIds`——**把黑名单暴露给客户端**。虽然不是直接越权（服务端仍会校验），但便于攻击者探测。

### 8.4 常见故障排查

| 现象 | 可能原因 | 排查步骤 |
|---|---|---|
| 所有员工工具调用 403 "门禁服务不可用" | `ADMIN_BACKEND_SERVICE_TOKEN` 未配置或两侧不一致 | 检查两侧环境变量；直接 curl admin-api `/api/internal/gatekeeper/evaluate` 带错误 token 验证 401 |
| 所有员工工具调用 403 "权限码不满足" | 只配了岗位角色，没配 `permission_grants` | 见 [7.1](#71-场景一普通员工发起一次对话) 结论；用 `GET /api/internal/gatekeeper/events?decision=deny` 查 `detail.granted` 看实际持有什么码 |
| 员工看不到某工具 | 岗位角色 `tool_access_mode` 不是 `all` 且 `tool_ids` 不含该工具 | 检查 `position_roles.tool_ids` 与 `end_user_capability_overrides.deny_tool_ids` |
| 员工在对话框选得到工具但调用失败 | 同上一行（两套体系未打通） | 必须**同时**配 `permission_grants` 的 `<tool_id>:execute` |
| 创建 org scope 记忆 403 | R-01 导致 `role` 恒为空 | 见 [10.1](#101-r-01-高); workaround：直接改库|
| 配额层429 但业务侧正常 | admin-api / chat-api 配额实现漂移 | 见 [5.4](#54-2099d5f-修复与双实现漂移)；检查 `org_quota_policies` 是否缺 `unlimited` 字段 |
| 审计查不到某次拒绝 | `layer` 是 `config_admin`/`permission_admin`/`matrix_admin`；或 `tenant_id=""` | 见 [6.4](#64-特殊工具名的审计事件) |
| 门禁拒绝事件在"Agent 能力"视图看不到 | 只 `^capability\.` 前缀被归到 agent 分类 | 去"历史管理操作"视图查 `gate.denied` |
| 记忆提升后摘要丢失 | R-11 数据完整性 bug | 见 [10.11](#1011-r-11-中) |
| 租户清理后数据残留 | 新增集合未同步两个清单 | 见 [4.7.4](#474-租户清理tenant_purge与数据权限) |

### 8.5 如何新增一个权限点

#### 8.5.1 新增一个 resource:action 权限码

**无需改代码**。权限码是开放字符串，只需：

1. 在 `permission_grants` 集合授予（`permission_grants.grant_code()`）
2. **在调用方设置 `ctx.annotations["required_code"]`**——否则 `required_code_for_tool` 会用 `f"{tool_id}:execute"` 自动推导（`rbac.py:72`）

```
POST /api/governance/permissions/grant
{"code": "bizdata:read", "level": "user", "user_id": "u1"}
```

审计自动落`gate_events`（`permission_grants.py:98`）。

⚠️ 若要让**岗位角色的能力键**映射到新权限码，需改 `CAPABILITY_TO_CODES`（`rbac_model.py:25-31`）并同步 `AGENT_CAPABILITY_KEYS`（`position_roles/constants.py:1-7`）与前端 `AgentCapabilityKey` 类型（`positionRoles.ts:3-8`）与 `RoleCapabilityEditor.vue:19-25`。三处必须同步，漏一处会导致前端能配但后端不认（或反之）。

#### 8.5.2 新增一个 Agent 能力键（完整流程）

| 步骤 | 文件 | 改动 |
|---|---|---|
| 1 | `admin-api/app/position_roles/constants.py:1-7` | `AGENT_CAPABILITY_KEYS` 加新键 |
| 2 | `admin-api/app/governance/rbac_model.py:25-31` | `CAPABILITY_TO_CODES` 加映射（否则 RBAC 层不认） |
| 3 | `admin-api/app/position_roles/service.py:14-16` | `normalized_capabilities` 自动读 `AGENT_CAPABILITY_KEYS`，**无需改** |
| 4 | `chat-api/app/governance/position_policy.py:11-17` | `CAPABILITY_KEYS` 加新键（**独立常量，必须手动同步**） |
| 5 | `apps/admin-web/src/api/positionRoles.ts:3-8` | `AgentCapabilityKey` 类型加新键 |
| 6 | `apps/admin-web/src/views/position-roles/RoleCapabilityEditor.vue:19-25` | `capabilityOptions` 加新项 |
| 7 | 视需要 | `position_policy.py:19-26` `INTERNAL_CAPABILITY_REQUIREMENTS` 加内部能力映射 |

⚠️ **步骤 1 和 4 是两个独立的常量**，没有共享定义。漏改 4 会导致 `build_effective_policy` 的 capabilities 字典缺该键 → `allows_capability` 恒返回 False（`position_policy.py:46`：`self.capabilities.get(key, False)`）。

⚠️ **步骤 2 漏改的后果**：`expand_role_to_codes` 的 `CAPABILITY_TO_CODES.get(key, ())` 返回空元组（`rbac_model.py:100`）→ 新能力在 RBAC 层**完全无权限码** → 员工调用相关工具必被拒。

### 8.6 如何新增一个数据范围

#### 8.6.1 在记忆域新增一个 scope（如 `team`）

| 步骤 | 文件 | 改动 |
|---|---|---|
| 1 | `chat-api/app/memory/scope.py:25-28` | `MemoryScope` 枚举加 `TEAM = "team"` |
| 2 | `chat-api/app/memory/scope.py:37-41` | `SCOPE_VISIBILITY` 加映射 |
| 3 | `chat-api/app/memory/scope.py:93-113` | `visible_to` 加分支 |
| 4 | `chat-api/app/api/endpoints/memory.py:42-44` | 端点的 scope 校验自动读 `MemoryScope`，**无需改** |
| 5 | `chat-api/app/memory/address.py` | 若 URI 格式需带 team_id，需扩展 |

⚠️ `Memory.__post_init__`（`scope.py:72-74`）会自动校验，新 scope 未登记到 `SCOPE_VISIBILITY` 会抛 `ValueError`（fail-closed）。

#### 8.6.2 在 021 地址空间新增一个根（如 `workflow`）

| 步骤 | 文件 | 改动 |
|---|---|---|
| 1 | `chat-api/app/context_space/address.py:145-163` | `parse_context_uri` 加 root 分派 |
| 2 | `chat-api/app/context_space/address.py` | 新增 `<Root>Address` dataclass |
| 3 | `chat-api/app/context_space/adapters/` | 新增 `TierAdapter` 子类 |
| 4 | `chat-api/app/context_space/router.py:31-36` | `_ADAPTERS` 注册 |
| 5 | `chat-api/app/context_space/visibility.py:122-137` | `check_visibility` 加分派 |
| 6 | `chat-api/app/context_space/visibility.py` | 新增 `check_<root>_visibility` 函数 |

⚠️ 步骤 5 若遗漏，`check_visibility` 抛 `NotImplementedError`（`visibility.py:137`），测试 `test_address_visibility.py:152-157` 固化了该行为。

⚠️ 新根的 `check_*_visibility` **必须显式实现租户比对**，不要照抄 `ctx.tenant_id` 为空时 `returnTrue` 的模式（见 R-07）。

---

## 9. 测试覆盖现状

### 9.1 各测试文件验证了什么

#### 9.1.1 admin-api 治理测试

| 文件 | 行数 | 验证内容 |
|---|---|---|
| `test_governance_rbac_model.py` | 113 | 权限码解析（合法/非法）、`parse_codes` 丢弃无效项、`full_access_admin` → `*`、能力键展开、`has_permission` 五种规则、target 隔离、`required_code_for_tool` 推导、**管理端工具调用回退到全能力预设**（`:75-113`） |
| `test_governance_gatekeeper.py` | 118 | 全通过→ allow、RBAC 拒绝短路后续层、拒绝状态码映射、审计总是执行、**审计落库失败→整个调用被拒**（`:97-118`） |
| `test_governance_us4_us5.py` | 237 | US4：显式授权放行、无码拒绝、角色预设组生效、通配符、target 隔离、RbacLayer 集成；US5：租户日配额、单工具配额独立、配额层拒绝维度、无配置放行、**020 预算耗尽拒绝**、**生产层集必装020 checker** |
| `test_governance_config.py` | 67 | 默认 thick 六层、层序重排、**禁用必需层被拒**、**禁用 audit 被拒**、thin 模式可丢 approval+quota、文档往返、空文档→thick、**租户覆盖生效** |
| `test_governance_polish.py` | 195 | 门禁链 p95 < 15ms（2000 次采样）、**配置保存被审计**、**薄化配置被拒且不写入**、审计覆盖率（每次链运行恰好一条事件） |
| `test_governance_pii.py` | 119 | 5 类 PII 识别器、4 种策略、重叠消解、指纹 |
| `test_governance_matrix.py` | 154 | 矩阵读取/更新、**R4 红线冻结**、未知格回退 |
| `test_governance_approval_flow.py` | 135 | 审批票据签发/决策/消费、过期、actor 不匹配 |
| `test_gatekeeper_internal.py` | 246 | 服务令牌校验（缺失/错误/正确）、**角色回填**（`:60-72`）、显式角色优先、**脱敏请求回传**（`:79-119`）、审批 token 注入、决策端点、**审计事件读取** |
| `test_system_audit.py` | 57 | 模块 key 提取、**body 不泄漏**、权限拒绝归类为 failed 活动、业务结果优先于 HTTP 状态 |

#### 9.1.2 chat-api 权限相关测试

| 文件 | 行数 | 验证内容 |
|---|---|---|
| `tests/memory/test_memory_endpoints.py` | 271 | CRUD + promote 端点、分层字段返回、非法 scope 拒绝、超限非分层内容拒绝 |
| `tests/memory/test_memory.py` | 226 | 记忆模型、scope 校验 |
| `tests/memory/test_sediment.py` | 132 | 会话沉淀 |
| `tests/memory/test_tiering.py` | 90 | L0/L1/L2 分层 |
| `tests/memory/test_retrieval_trace.py` | 52 | 检索轨迹 |
| `tests/context_space/test_address_visibility.py` | 158 | 地址解析（7 种）、**记忆可见性用存储记录而非 URI**（`:99-125`）、**无记录 fail-closed**（`:128-131`）、resource/skill/session 租户隔离、未知类型抛 `NotImplementedError` |
| `tests/context_space/test_adapters_integration.py` | — | adapter 集成 |
| `tests/context_space/test_context_space.py` | — | 路由 |
| `tests/context_space/test_context_endpoints.py` | — | HTTP 端点 |
| `tests/dsh_runtime/test_position_role_governance.py` | — | 能力/工具/Skill 策略求值、`org_skill:` 别名 |
| `tests/dsh_runtime/test_gate_plan_wiring.py` | — | 门禁计划接线 |
| `tests/dsh_runtime/test_pdf_retain_pages_capability.py` | — | `allows_internal` |

### 9.2 测试覆盖的关键断言（安全相关）

这些断言是**安全契约的固化点**，修改时需格外小心：

| 断言 | 位置 | 保护的行为 |
|---|---|---|
| `assert not has_permission({"*"}, "")` | `test_governance_rbac_model.py:62` | 空 required 永不允许 |
| `assert not has_permission({"document:read:doc-1"}, "document:read:doc-2")` | `:67` | target 隔离 |
| `assert quota.calls == 0` | `test_governance_gatekeeper.py:74` | 短路后续层 |
| `assert verdict.decision is GateDecision.DENY`（audit 失败） | `:117` | 审计不可用则拒绝 |
| `assert captured["roles"] == ["system:t1:full_access_admin"]` | `test_governance_rbac_model.py:113` | 管理端回退（**固化了一个宽松行为**） |
| `pytest.raises(GateConfigError)` | `test_governance_config.py:27,35` | 必需层不可禁用 |
| `assert not db._collections.get("gatekeeper_rules")` | `test_governance_polish.py:137` | 无效配置不写入 |
| `assert "body" not in item["details"]` | `test_system_audit.py:37` | 审计不泄漏请求体 |
| `check_visibility(...) is False`（伪造 URI） | `test_address_visibility.py:115,122` | URI 不是凭证 |
| `check_visibility(...) is False`（无记录） | `:131` | 无记录 fail-closed |
| `quota._credit_checker is not None` | `test_governance_us4_us5.py:237` | 生产不装pass-through |

### 9.3 测试覆盖缺口（重要发现）

#### 9.3.1 完全无覆盖的权限点/路径

| 缺口 | 说明 | 影响的代码 |
|---|---|---|
| **G1：`_load_biz` 的租户来源** | 无测试验证 `_load_biz` 用 URI tenant 而非认证 tenant | `adapters/resource.py:114,128` |
| **G2：组织级显式授权** | 无测试覆盖 `level="org"` 的 grant 被实际使用 | `permission_grants.py:147-148`；因 `org_id` 恒空，实际不可达 |
| **G3：`check_resource_visibility` 的空 tenant 分支** | 无测试验证 `ctx.tenant_id=""` 时 `return True` | `visibility.py:91-93` |
| **G4：`check_skill_visibility` 的空 tenant 分支** | 同上 | `visibility.py:106-107` |
| **G5：`check_session_visibility` 的空 tenant 分支** | 同上 | `visibility.py:117-118` |
| **G6：`allows_internal` 未注册引用** | 无测试验证 `capability_ref` 未在映射表时默认放行 | `position_policy.py:62-64` |
| **G7：`promote_memory` 的字段保留** | 测试的 fake store 不校验字段完整性，故 promote 后字段丢失未被捕获 | `endpoints/memory.py:203-210` |
| **G8：`resolve_session_user` 的返回契约** | 测试用 fake 替换了它，**从未验证真实实现的返回键** | `end_user_session.py:70` vs `endpoints/memory.py:36,114,189` |
| **G9：`_role_documents` 不过滤 status** | 无测试验证已停用角色在 RBAC 层仍生效 | `layers/rbac.py:34-36` |
| **G10：`permissions/check` 端点** | 无测试覆盖 | `routes/governance.py:198-204` |
| **G11：`pii_policies` 租户覆盖的端点** | 无 CRUD 端点，故无测试；租户覆盖路径（`redaction.py:59-60`）也无测试 | `redaction.py:59-60` |
| **G12：嵌套结构的 PII 脱敏** | 无测试验证嵌套 dict 中的 PII 不被脱敏 | `redaction.py:98-101` |
| **G13：`/api/tools/{id}/discover` 门禁缺失** | 无测试断言该端点应/不应过门禁 | `tools.py:382-388` |
| **G14：`effective_grant_codes` 的 10000 上限** | 无测试验证超限截断行为 | `permission_grants.py:154` |
| **G15：`list_for_viewer` 的 500 上限** | 无测试验证超限截断 | `store.py:169` |
| **G16：数据可见性拒绝的审计** | 无测试断言越权尝试应落审计（因为根本没落） | `visibility.py` |
| **G17：chat-api 的 reserved main_id** | 无测试验证 chat-api 收到 `__platform__` 的行为 | `core/tenant.py` |

#### 9.3.2 测试的"剧场化"（Test Theater）问题

**这是本章最重要的发现。** 有多处测试用 mock 替换掉了被测行为的关键前提，导致测试通过但生产失败。

**案例 1：memory 端点的 session 解析**（最严重）

`test_memory_endpoints.py:70-78` 的 fixture：

```python
async def _fake_resolve(authorization):
    return {
        "user_id": "u1",            # ← 真实实现不返回此键
        "main_id": "t1",
        "role": "",                 # ← 真实实现不返回此键
        "is_workspace_member": False,  # ← 真实实现不返回此键
    }
monkeypatch.setattr("app.api.endpoints.auth._resolve_session_user", _fake_resolve)
```

而真实的 `resolve_session_user`（`end_user_session.py:70`）返回：

```python
return {"session": session_doc, "user": user_doc, "main_id": main_id}
```

**fake 返回了 3 个真实实现不存在的键。** 后果：

| 端点 | 代码读| 真实值 | fake 值 | 测试断言 |
|---|---|---|---|---|
| `create_memory` | `resolved.get("user_id")` | `""` | `"u1"` | `owner_id == "u1"` ✅ 通过 |
| `create_memory`（org scope） | `resolved.get("role")` | `""` | `""` | 403 ✅ 偶然一致 |
| `list_memories` | `resolved.get("user_id")` | `""` | `"u1"` | 可见性过滤正确 ✅ |
| `promote_memory` | `resolved.get("user_id")` | `""` | `"u1"` | `owner_id` 匹配 ✅ |

**所有涉及 `user_id` 的测试都建立在错误的前提上**，生产环境全部失效（R-01）。

**案例 2：门禁链的层替换**

`test_governance_gatekeeper.py:44-48`：

```python
def _make_gatekeeper(layers, monkeypatch) -> Gatekeeper:
    monkeypatch.setattr(layers_module, "build_layers", lambda config: layers)
```

完全替换 `build_layers`，因此**从未测试真实的 `build_layers` 装配**（唯一测试是 `test_governance_us4_us5.py:230-237` 单独测的）。

**案例 3：审计层的替换**

`test_governance_gatekeeper.py:32-41` 的 `_RecordingAuditLayer` 和 `:148-155` 的 `_RecordingAudit` 都**不写数据库**，所以"审计覆盖率 100%"（`:189`的 `assert len(events) == 2`）实际只验证了"evaluate 被调用了"，没验证"落库了"。

**案例 4：PII 策略存储不可用路径**

`redaction.py:63-72` 的 `except` 分支（QA R5 修复）**没有测试覆盖**——因为它需要 mock `db[PII_POLICIES_COLLECTION].find` 抛异常。

### 9.4 覆盖率总结

| 维度 | 覆盖状况 |
|---|---|
| 权限码模型（纯逻辑） | ✅ 充分（13 个用例） |
| 六层编排与短路 | ✅ 充分 |
| 门禁配置约束 | ✅ 充分 |
| 审批状态机 | ✅ 充分 |
| PII 识别与策略 | ✅ 充分（缺嵌套场景） |
| 岗位角色 CRUD 业务规则 | ✅ 充分 |
| **chat-api 端点的 session 解析契约** | ❌ **被 mock 掩盖** |
| **数据可见性的空 tenant 边界** | ❌ 无 |
| **组织级授权** | ❌ 不可达且无测试 |
| **配额双实现的等价性** | ❌ 无 |
| **门禁与岗位策略的集成** | ❌ 无（这是最大的语义缺口） |
| **越权尝试的审计** | ❌ 无 |

---

## 10. 安全与越权风险点（按严重度排序）

>评级依据：可利用性 × 影响面 × 是否被其他控制缓解。
> 每条含：证据、复现、影响、修复建议。

### 10.1 R-01【严重】chat-api 端点读取不存在的 session 字段，权限判定全部失效

**证据**

`resolve_session_user` 返回 3 个键（`services/chat-api/app/services/end_user_session.py:70`）：

```python
return {"session": session_doc, "user": user_doc, "main_id": main_id}
```

但 `services/chat-api/app/api/endpoints/memory.py` 读取了 3 个不存在的键：

| 行号 | 代码 | 真实值 |
|---|---|---|
| `:35` | `user_id = str(resolved.get("user_id") or "")` | `""` |
| `:36` | `role = str(resolved.get("role") or "")` | `""` |
| `:121` | `bool(resolved.get("is_workspace_member") or False)` | `False` |
| `:114` | `viewer_role = str(resolved.get("role") or "")` | `""` |
| `:113` | `viewer_id = str(resolved.get("user_id") or "")` | `""` |
| `:188-189` | `user_id = ...`、`role = ...` | `""` |

**复现（逻辑推演，无需运行）**

| 场景 | 代码路径 | 实际行为 |
|---|---|---|
| 员工 A 创建记忆 | `memory.py:73` `owner_id=user_id=""` | 记忆归属空字符串 |
| 列出记忆 | `memory.py:117-122` → `store.list_for_viewer(viewer_id="")` → `visible_to` personal 分支 `scope.py:108`：`return "" == memory.owner_id` | 若所有记忆 `owner_id` 都是 `""` → **所有员工的个人记忆对所有员工可见** ⚠️ |
| 创建 org 记忆 | `memory.py:49` `role not in ORG_PROMOTION_ROLES` → `"" not in {"full_access_admin"}` → True |恒 403，功能不可用 |
| 提升记忆 | `memory.py:199` `promote_to_org(memory, role="")` → `scope.py:127` 抛 `MemoryAccessError` | 恒 403，功能不可用 |
| 全能力管理员特权 | `visible_to` 的 `viewer_role in ORG_PROMOTION_ROLES` 分支（`scope.py:105-106`） | **永不触发**（`viewer_role` 恒 `""`） |

**影响**

1. **数据可见性**：所有通过 HTTP 端点创建的记忆 `owner_id` 为空，导致 `visible_to` 的 personal 分支对所有 viewer 返回 True。**这是一条真实的跨用户读取路径。**
   > 缓解：`store.py:169` 仍按 `tenant_id` 过滤，所以**跨租户**读取不成立。但**同租户内跨员工**读取成立。
2. **功能不可用**：org scope 记忆无法创建/提升（fail-closed，但是 bug 导致的不可用）。
3. **特权失效**：`full_access_admin` 的记忆特权永不生效（该角色无法读他人 personal 记忆——反而是"更安全"的方向，但与设计不符）。

**测试掩盖**

`test_memory_endpoints.py:70-78` 的 fake 返回了真实实现不存在的键，详见 [9.3.2](#932-测试的剧场化test-theater-问题) 案例 1。**8 个 memory 端点测试全部建立在错误前提上。**

**修复建议**

```python
# services/chat-api/app/services/end_user_session.py:70
return {
    "session": session_doc,
    "user": user_doc,
    "main_id": main_id,
    # 补齐端点依赖的字段
    "user_id": user_id,                      # 已在 :55 算出
    "role": _effective_role(user_doc),# 需确认 role 来源
    "is_workspace_member": _is_workspace_member(db, main_id, user_id),
}
```

⚠️ **`role` 的来源需要产品决策**：`ORG_PROMOTION_ROLES = {"full_access_admin"}` 是岗位角色的 `system_key`，但员工会话的 `user_doc` 里没有这个字段。需通过 `MongoEmployeePolicyResolver` 查该员工是否有 `full_access_admin` 角色来推导。不能简单用 `user_doc.get("role_name")`。

**同时必须补测试**：一个不 mock `_resolve_session_user` 的集成测试（或至少一个断言真实返回键集合的测试）。

---

### 10.2 R-02【严重】无岗位角色且迁移未完成 → 返回全开权限

**证据**

`services/chat-api/app/governance/position_policy.py:124-141`：

```python
if not roles and not assigned_role_ids:
    if migration_completed:
        return EffectiveEmployeePolicy(
            capabilities={key: False for key in CAPABILITY_KEYS},   # 全关
            migration_pending=False, version="migration-complete-no-role")
    return EffectiveEmployeePolicy(
        capabilities={key: True for key in CAPABILITY_KEYS},     # ★ 全开
        tool_access_mode="all", skill_access_mode="all",
        migration_pending=True, version="legacy-full-access")
```

`migration_completed` 来自 `position_role_migrations.status == "complete"`（`:105-112`）。

**攻击路径**

1. 租户管理员尚未完成岗位角色分配（`complete_migration` 未调用），或该租户的迁移记录被删除
2. 攻击者创建一个员工账号（或任意未分配角色的员工）
3. 该员工解析出的策略是 `version="legacy-full-access"`，**全部 5 个能力 +全部工具 + 全部 Skill**
4. `is_workspace_member=False` 不影响这个分支

**影响**：**未分配岗位角色的员工获得全平台能力**，含代码生成、浏览器自动化、全部 MCP 工具、全部 Skill。

**缓解**：
- 需要攻击者能创建员工账号（有`user_invites` 流程约束）
- 门禁 RBAC 层仍会校验权限码（`required_code_for_tool`），所以工具调用可能仍被拒（见 R-13）
- `migration_pending=True` 可被前端用于提示

**为什么是"设计意图"还是"缺陷"**：注释与`migration_pending` 标记表明这是**有意的向后兼容**——老租户在迁移完成前保持原有行为。但风险在于"迁移未完成"是一个**持续状态**，不是瞬时状态。

**修复建议**

```python
# 至少：把 fallback 限制为"仅当租户不存在任何岗位角色定义"（全新租户），
# 而非"该员工无角色"
has_any_roles = await db.position_roles.count_documents(
    {"main_id": tenant_id}, limit=1) > 0
if has_any_roles and not roles:
    # 租户已配置角色体系但该员工未分配 → fail-closed
    return EffectiveEmployeePolicy(
        capabilities={key: False for key in CAPABILITY_KEYS},
        version="no-role-fail-closed")
```

并加告警日志 + 监控指标。

---

### 10.3 R-03【高】021 地址层对 resource 根只做租户校验，无个人/部门隔离

**证据**

`services/chat-api/app/context_space/visibility.py:84-94`：

```python
def check_resource_visibility(*, addr: ResourceAddress, ctx: ViewerContext) -> bool:
    """Delegate to 005/014/015 tenant isolation (021)."""
    if not ctx.tenant_id:
        return True                              # ← fail-open
    return addr.tenant_id == ctx.tenant_id      # ← 仅租户比对
```

数据加载侧同样只按租户过滤（`adapters/resource.py:85`）：

```python
row = await db["knowledge_document_chunks"].find_one({
    "main_id": resolve_main_id(tenant_id),
    "document_id": document_id, "chunk_id": chunk_id,
    "$or": [{"chunk_stage": "rag"}, {"chunk_stage": {"$exists": False}}]})
# ← 无个人/部门归属过滤
```

对比：`adapters/memory.py:44-46` 加载后调用 `check_visibility(..., memory=memory)` 做所有者判定；`adapters/session.py:90-92` 加载时带 `user_id` 过滤。**唯独 resource 根两者都没有。**

**复现（见 [7.4](#74-场景四跨部门读取知识库) 路径 B）**

员工 `u1`（engineering）请求 `mogo://resource/doc/t1/<u2的个人文档id>/<chunkId>`：

- `check_resource_visibility` → `addr.tenant_id == ctx.tenant_id` → True
- `_load_doc` → 只按 `main_id` 查 → 返回 chunk 文本

**影响**：**同租户内任意员工可读取任意知识文档 chunk**，包括其他员工的个人知识库内容（若这些内容进了 `knowledge_document_chunks` 且 `chunk_stage="rag"`）。

**关联**：021 spec US3 要求委托给 005 的 `retrieval_access_policy`（`specs/021-unified-context-address/spec.md:44`），但**该函数在代码中不存在**。

**修复建议**

```python
def check_resource_visibility(*, addr, ctx) -> bool:
    if not ctx.tenant_id:
        return False                             # 改为 fail-closed
    if addr.tenant_id != ctx.tenant_id:
        return False
    # 个人知识文档：额外校验归属（参照 personal_knowledge/access.py）
    return True
```

并在 `_load_doc` 中对 `scope == "personal"` 的文档走 `PersonalKnowledgeAccessService.require_view`（复用现成逻辑，见 [4.6.1](#461-范式resolve--require)）。

---

### 10.4 R-04【高】`org_id` 从未被注入，组织级授权永久不可达

**证据**

`layers/rbac.py:50` 读`ctx.annotations.get("org_id")`：

```python
codes = await effective_grant_codes(
    tenant_id=ctx.tenant_id,
    org_id=str(ctx.annotations.get("org_id") or ""),   # ← 恒为 ""
    user_id=ctx.user_id,
)
```

但**没有任何代码写入 `org_id` annotation**。`gatekeeper_internal.py:88-104` 构造 annotations：

```python
annotations: dict[str, Any] = {}
if payload.approvalToken:
    annotations["approval_token"] = ...
    annotations["approval_action_id"] = ...
ctx = GateContext(..., annotations=annotations, ...)     # ← 只有审批相关
```

`tools.py:338-344` 同样只放审批字段。

**后果**

`permission_grants.effective_grant_codes`（`permission_grants.py:146-150`）的org scope 分支永不进入：

```python
scopes = [{"tenant_id": tenant_id, "level": "tenant"}]
if org_id:                                       # ← 恒 False
    scopes.append({"tenant_id": tenant_id, "level": "org", "org_id": org_id})
```

即 **`level="org"` 的授权记录可以被写入（API 接受，`governance.py:48` 的正则允许 `org`），但永远不生效**。

**影响**

- **静默失效**：管理员配置了组织级授权，以为生效了，实际不生效
- **可能反向**：管理员发现不生效，改用 `level="tenant"` 授予 → **全租户成员都被授权**，比预期范围大
- 001 spec FR-5 明确要求"三级隔离（租户/组织/用户）"（`spec.md:93`），代码只实现了 2 级

**修复建议**

1. 在 `gatekeeper_internal.py` 的 payload 加 `orgId` 字段
2. 在 `_resolve_roles` 同时解析员工的组织归属（`end_user_org_relations`）
3. 或：在 `RbacLayer._explicit_grants` 内部直接查组织归属，不依赖外部注入

**测试缺口**：G2（见 [9.3.1](#931-完全无覆盖的权限点路径)）。

---

### 10.5 R-05【高】RBAC 层加载岗位角色时不过滤 `status`

**证据**

`services/admin-api/app/governance/layers/rbac.py:34-36`：

```python
cursor = db[POSITION_ROLE_COLLECTION].find(
    {"main_id": tenant_id, "_id": {"$in": list(role_ids)}})   # ← 无 status 过滤
```

对比同类的`position_policy.py:94`：

```python
roles = await db.position_roles.find(
    {"main_id": tenant_id, "_id": {"$in": role_ids}, "status": "active"})  # ← 有
```

**攻击路径**

1. 管理员停用一个岗位角色（`PATCH /api/position-roles/{id}/status {"enabled": false}`）
2. 该角色的 `status` 变为 `disabled`，但 `end_user_position_roles` 中的绑定记录仍在
3. 员工侧策略层：`position_policy.py:94` 的 `status:"active"` 过滤生效 → 该角色不再授予能力 ✅
4. **但门禁 RBAC 层**：`rbac.py:34-36` 不过滤 → 该角色仍展开权限码 ❌

**影响**

**停用角色无法撤销其在门禁层的权限**。若某角色曾授予 `knowledge:read`（`CAPABILITY_TO_CODES`），停用后员工仍能通过门禁的 RBAC 检查。

**缓解**：能力类权限的影响有限（只有 5 个能力键 → 5 个权限码）。若该角色还带 `permission_codes` 字段（`rbac_model.py:94`），影响范围可扩大。

**修复建议**

```python
cursor = db[POSITION_ROLE_COLLECTION].find(
    {"main_id": tenant_id, "_id": {"$in": list(role_ids)}, "status": "active"})
```

**测试缺口**：G9。

---

### 10.6 R-06【中】两个工具端点未过门禁

**证据**

`services/admin-api/app/api/routes/tools.py`：

| 端点 | 行号 | 是否过门禁 | 是否调后端 |
|---|---|---|---|
| `POST /{tool_id}/test` | `:294-306` | ✅ `:302` | ✅ `:304` |
| `POST /test-draft` | `:309-317` | ✅ `:314` | ✅ `:315` |
| **`POST /{tool_id}/discover`** | `:382-388` | ❌ **无** | ✅ `:388` `_request_backend("POST", f"/{tool_id}/discover", ...)` |
| **`POST /generate-description`** | `:391-395` | ❌ **无** | ✅ `:395` `_request_backend("POST", "/generate-description", ...)` |

**影响**

这两个端点会向企业外部工具后端发起真实 HTTP 请求，但：

- ❌ 无 PII 脱敏（若有请求体含 PII，原样发往后端）
- ❌ 无风险级判定与审批
- ❌ 无 `gate_events` 审计
- ✅ 有 `system_audit_logs` 审计（中间件覆盖所有变更类请求）

**利用场景**：管理端账号（已有 `full_access_admin` 权限，但门禁未被调用）通过 `discover` 让内部工具后端访问任意目标。若 `config.base_url` 可控，构成 SSRF 面。

**修复建议**

```python
@router.post("/{tool_id}/discover")
async def discover_tool(tool_id, request: Request, current_user=Depends(get_current_admin_user)):
    main_id = str(current_user.get("main_id") or "default")
    # ... 存在性校验 ...
    await _enforce_gate(f"{tool_id}:discover", main_id, current_user, {})   # ← 补门禁
    return _backend_data(_request_backend("POST", f"/{tool_id}/discover", main_id, {}, ...))
```

**测试缺口**：G13。

---

### 10.7 R-07【中】resource / skill / session 可见性在空 tenant 时fail-open

**证据**

`visibility.py:91-93`、`:106-107`、`:117-118` 三处相同模式：

```python
if not ctx.tenant_id:
    # No tenant context → treat as the owning tenant (best-effort, non-fatal).
    return True
```

对比 memory 根（`:69-75`）是 fail-closed：

```python
if memory is None:
    log_print("... URI identity is not a credential")
    return False
```

**影响**

若某个调用路径传入空的 `tenant_id`（如新增的 endpoint 忘记传参），则：

- resource 根：任意 `mogo://resource/doc/*` 地址可被解析
- skill 根：任意 `mogo://skill/*` 地址可被解析
- session 根：任意 `mogo://session/*` 地址可被解析

虽然后续 `_load_doc` / `_load_kg` 会用 `resolve_main_id("")` = `"default"` 过滤（导致查不到数据），但 `_load_biz` 用的是 **URI 里的 tenant**（见 R-09），可被利用。

**修复建议**

三处统一改为 `return False`，并在 `router.py:73-78` 加断言：

```python
if not tenant_id:
    raise ValueError("tenant_id is required to resolve a context address")
```

**测试缺口**：G3/G4/G5。

---

### 10.8 R-08【中】`/api/governance/permissions/check` 端点逻辑错误

**证据**

`services/admin-api/app/api/routes/governance.py:198-204`：

```python
@router.get("/permissions/check")
async def check_permission(code: str, actor = Depends(get_current_admin_user)) -> dict[str, Any]:
    """Whether the caller's *own* effective codes satisfy ``code`` (admin self-check)."""
    granted = {str(actor.get("user_id") or "")}        # ← 把 user_id 当成权限码集合！
    return {"code": code, "satisfied": has_permission(granted, code) or "*" in granted}
```

**问题**

`granted` 被赋值为**单元素集合，元素是 user_id 字符串**（如 `{"admin-1"}`）。这不是权限码集合。

`has_permission({"admin-1"}, "knowledge:read")`：
- `"*" in granted` → False
- `PermissionCode.parse("admin-1")` → `parts = ["admin-1"]` → `len < 2` → ValueError → continue
- → 返回 False

**即该端点永远返回 `satisfied=False`**（除非 user_id 字面量是 `"*"` 或恰好是合法权限码串）。

**影响**

- 功能失效：管理员无法自查权限
- **误导性**：返回 `False` 会让管理员以为"我没有这个权限"，从而重复配置
- 安全影响低（只读端点，无副作用）

**修复建议**

```python
from ...governance.permission_grants import effective_grant_codes
from ...governance.layers.rbac import RbacLayer

@router.get("/permissions/check")
async def check_permission(code: str, actor = Depends(get_current_admin_user)):
    tenant_id = _tenant(actor)
    user_id = str(actor.get("user_id") or "")
    granted = await effective_grant_codes(tenant_id=tenant_id, user_id=user_id)
    # 叠加岗位角色
    layer = RbacLayer()
    ctx = GateContext(tool=code, tenant_id=tenant_id, user_id=user_id)
    ctx.annotations["required_code"] = code
    verdict = await layer.evaluate(ctx)
    return {"code": code, "satisfied": verdict.allowed, "detail": verdict.detail}
```

**测试缺口**：G10。

---

### 10.9 R-09【中】`_load_biz` 用URI 里的 tenantId 而非认证 tenantId

**证据**

`services/chat-api/app/context_space/adapters/resource.py:113-128`：

```python
async def _load_biz(addr: ResourceAddress, tenant_id: str) -> tuple[Optional[str], dict]:
    tenant_id, system, entity_type, record_id = addr.identifiers   # ← 覆盖了参数！
    ...
    row = await db["business_entity_index"].find_one(
        {"entity_id": {"$in": candidates}, "tenant_id": tenant_id})   # ← 用 URI 的值
```

参数 `tenant_id` 在函数体第一行被**元组解包覆盖**。对比同文件：

| 函数 | 用的 tenant | 位置 |
|---|---|---|
| `_load_doc` | `resolve_main_id(tenant_id)`（参数） | `:85` |
| `_load_kg` | `TenantKgStore(tenant_id=tenant_id)`（参数） | `:159` |
| **`_load_biz`** | **`addr.identifiers[0]`（URI）** | `:114,128` |

**当前可利用性**

`check_resource_visibility` 已比对 `addr.tenant_id == ctx.tenant_id`（`visibility.py:94`），所以当 `ctx.tenant_id` 非空时两者相等 → **当前不构成直接越权**。

但结合 R-07（`ctx.tenant_id` 为空时 `return True`），若 `ctx.tenant_id` 为空，则：

1. `check_resource_visibility` 返回 True（fail-open）
2. `_load_biz` 用 URI 里的 tenantId 查询 → **可跨租户读取 `business_entity_index`**

**影响**：条件性跨租户数据读取。触发条件是 `ctx.tenant_id` 为空，而 `router.py:77` 的 `ViewerContext(tenant_id=tenant_id)` 来自 `resolve_memory(tenant_id=...)` 的必填参数，所以**当前调用路径不会传空**。属于潜在风险 + 代码健壮性问题。

**修复建议**

```python
async def _load_biz(addr, tenant_id):
    auth_tenant = resolve_main_id(tenant_id)          # ← 用认证 tenant
    addr_tenant, system, entity_type, record_id = addr.identifiers
    if auth_tenant != addr_tenant:
        raise ContextVisibilityError("tenant mismatch")  # 双保险
    row = await db["business_entity_index"].find_one(
        {"entity_id": {"$in": candidates}, "tenant_id": auth_tenant})
```

**测试缺口**：G1。

---

### 10.10 R-10【中】`visible_to` 的 org 分支不校验租户，依赖隐式契约

**证据**

`services/chat-api/app/memory/scope.py:111-112`：

```python
if memory.scope == MemoryScope.ORG.value:
    return viewer_id != ""    # 任何 viewer_id 非空即可，不校验是否同租户
```

安全性完全依赖调用方已按 `tenant_id` 过滤。`MemoryStore` 确实这样做（`store.py:169`），021 的 `check_memory_visibility` 传入的 `memory` 也来自 `MemoryStore.get()`（`adapters/memory.py:40`）——**契约成立**。

但 `visible_to` 是**公开函数**（`memory/__init__.py:29` 导出），任何新调用方若直接传入未过滤的 `memory` 对象，就会引入跨租户读取。

**影响**：当前无直接漏洞，但契约脆弱。一次疏忽的调用即产生跨租户读取。

**修复建议**

在 `visible_to` 增加可选的租户参数：

```python
def visible_to(memory, *, viewer_id, viewer_role="", is_workspace_member=False, viewer_tenant=""):
    if viewer_tenant and memory.tenant_id != viewer_tenant:
        return False        # 显式租户校验
    ...
```

并在 `ViewerContext` 已有 `tenant_id` 的前提下由 `check_memory_visibility` 传入。

---

### 10.11 R-11【中】记忆提升丢失全部分层与溯源字段

**证据**

`services/chat-api/app/api/endpoints/memory.py:203-210`：

```python
await store.save(
    memory_id=promoted.memory_id,
    content=promoted.content,
    owner_id=promoted.owner_id,
    tenant_id=promoted.tenant_id,
    workspace_id=promoted.workspace_id,
    scope=promoted.scope,
)      # ← 只有 6 个字段
```

`MemoryStore.save`（`store.py:151-155`）用 `replace_one(..., upsert=True)`——**全量替换**，未传字段被删除。

丢失的字段（`store.py:141-150` 的完整字段列表减去传入的）：

| 字段 | 影响 |
|---|---|
| `l0_summary` | 渐进检索的 L0 层失效（`_select_tier` 回退到 content） |
| `l1_overview` | L1 层失效 |
| `l2_raw` | L2 原始数据丢失 |
| `tierable` | 回落 `True`，可能触发超限拒绝 |
| `summary_generated_at` | 摘要时间戳丢失，惰性补全逻辑异常 |
| `summary_refresh_days` | 回落配置默认值 |
| `source_session_id` | **溯源断裂**（017 FR-20 要求） |
| `source_type` | 溯源类型丢失 |

**影响**

- 提升后该记忆的分层结构被破坏，渐进检索退化
- **溯源信息永久丢失**——无法回答"这条组织级记忆来自哪个会话"
- 因为 R-01 导致 `role` 恒空，org 提升路径实际不可达，所以**当前无生产影响**。修复 R-01 后此bug 立即生效。

**修复建议**

```python
await store.save(
    memory_id=promoted.memory_id, content=promoted.content,
    owner_id=promoted.owner_id, tenant_id=promoted.tenant_id,
    workspace_id=promoted.workspace_id, scope=promoted.scope,
    l0_summary=promoted.l0_summary,          # ← 补齐
    l1_overview=promoted.l1_overview,
    l2_raw=promoted.l2_raw,
    tierable=promoted.tierable,
    summary_generated_at=promoted.summary_generated_at,
    summary_refresh_days=promoted.summary_refresh_days,
    source_session_id=promoted.source_session_id,
    source_type=promoted.source_type,
)
```

更根本的修复：给 `MemoryStore` 加 `update_scope(memory_id, tenant_id, scope)` 方法，只改 scope 一个字段。

**测试缺口**：G7。

---

### 10.12 R-12【低】数据可见性拒绝不落审计

**证据**

`context_space/visibility.py` 与 `adapters/*.py` 抛 `ContextVisibilityError` 时**无任何审计写入**。对比同一场景下的其他拒绝都有审计：

| 拒绝类型 | 审计位置 |
|---|---|
| 门禁 RBAC 拒绝 | `gate_events`（`layers/audit.py:65`） |
| 门禁 quota 拒绝 | `gate_events` |
| 岗位能力拒绝 | `position_role_audit_logs`（`dsh_chat.py:33`） |
| HTTP 变更请求 | `system_audit_logs` |
| **数据可见性拒绝** | ❌ **无** |
| **未认证 HTTP 请求** | ❌ 无（`middleware.py:41` 直接跳过） |

**影响**

**越权尝试不可观测**。攻击者尝试伪造 memory 地址、跨租户解析 session 等行为**不留痕**，无法做入侵检测或事后追溯。

对 R-03（resource 根只做租户校验）尤其不利——因为它**不会抛异常**，连"拒绝"都不会有。

**修复建议**

在 `router.py:85-88` 的 `except ContextVisibilityError` 分支加审计：

```python
except ContextVisibilityError as exc:
    skipped.append(skipped_entry(uri=uri, reason="visibility_denied"))
    build_trace([], skipped, session_id=session_id, turn_id=turn_id)
    await record_position_policy_event(
        tenant_id=tenant_id, user_id=viewer_id,
        action="capability.denied", target="context_visibility",
        details={"uri": uri, "reason": str(exc)})
    raise
```

并考虑在 `SystemAuditMiddleware` 中记录 401/403（当前只记 `MUTATING_METHODS` 且需认证）。

**测试缺口**：G16。

---

### 10.13 R-13【低】`allows_internal` 对未注册能力引用默认放行

**证据**

`services/chat-api/app/governance/position_policy.py:62-64`：

```python
def allows_internal(self, capability_ref: str) -> bool:
    required = INTERNAL_CAPABILITY_REQUIREMENTS.get(capability_ref)
    return required is None or self.allows_capability(required)
    #          ^^^^^^^^^^^^^^ 未注册 → 放行
```

消费点`dsh_runtime/profile/tools.py:90`：

```python
if policy is not None and not policy.allows_internal(capability.capability_ref):
    ...拒绝
```

**影响**

新增一个内部能力（如 `"database.query@v1"`）但忘记登记到 `INTERNAL_CAPABILITY_REQUIREMENTS` → 该能力**对所有员工开放**，包括无任何岗位角色的员工（叠加 R-02）。

**修复建议**

改为 fail-closed + 白名单：

```python
_INTERNAL_ALLOWLIST = frozenset(INTERNAL_CAPABILITY_REQUIREMENTS)

def allows_internal(self, capability_ref: str) -> bool:
    if capability_ref not in _INTERNAL_ALLOWLIST:
        logger.warning("unregistered internal capability_ref: %s", capability_ref)
        return False           # fail-closed
    return self.allows_capability(INTERNAL_CAPABILITY_REQUIREMENTS[capability_ref])
```

或在profile/tools.py 侧对未注册引用直接拒绝加载。

**测试缺口**：G6。

---

### 10.14 风险汇总表

| ID | 严重度 | 风险 | 触发条件 | 当前可利用性 |
|---|---|---|---|---|
| **R-01** | 🔴 严重 | chat-api 端点读不存在字段，个人记忆跨员工可见 | 任何经 HTTP 端点创建+ 列表记忆 | ✅ 同租户内可利用 |
| **R-02** | 🔴 严重 | 无角色 + 迁移未完成 → 全开权限 | 租户未完成角色分配 | ✅ 可利用 |
| **R-03** | 🟠 高 | resource 根只做租户校验 | 走 `mogo://resource/*` 读他人文档 | ✅ 同租户内可利用 |
| **R-04** | 🟠 高 | `org_id` 从未注入，组织级授权失效 | 配置 `level="org"` 授权 | ✅ 静默失效 |
| **R-05** | 🟠 高 | RBAC 层不过滤 role status | 停用某角色 | ✅ 权限无法撤销 |
| **R-06** | 🟡 中 | 2 个工具端点未过门禁 | 调用 `discover` / `generate-description` | ✅ |
| **R-07** | 🟡 中 | 3 处可见性空 tenant fail-open | 调用方传空 tenant | ⚠️ 潜在（当前路径不触发） |
| **R-08** | 🟡 中 | `permissions/check` 逻辑错误 | 使用该端点 | ✅ 功能失效 |
| **R-09** | 🟡 中 | `_load_biz` 用 URI tenant | 叠加 R-07 | ⚠️ 条件性 |
| **R-10** | 🟡 中 | `visible_to` org 分支依赖隐式契约 | 新增不严格的调用方 | ⚠️ 潜在 |
| **R-11** | 🟡 中 | 记忆提升丢字段 | 修复 R-01 后 | ⚠️ 潜伏 |
| **R-12** | 🔵 低 | 可见性拒绝不落审计 | 任何越权尝试 | ✅ 不可观测 |
| **R-13** | 🔵 低 | `allows_internal` 未注册放行 | 新增内部能力未登记 | ⚠️ 潜伏 |

**修复优先级建议**

| 优先级 | 风险 | 理由 |
|---|---|---|
| **P0** | R-01 | 唯一确认的**数据泄露**路径（同租户跨员工读个人记忆） |
| **P0** | R-02 | 权限绕过（无角色员工得全能力） |
| **P1** | R-03 | 同租户跨员工读知识文档 |
| **P1** | R-04 | 静默失效导致管理员误配，反而放大授权范围 |
| **P1** | R-05 | 停用角色无法撤销权限 |
| **P2** | R-06, R-08, R-11 | 功能完整性 + 攻击面 |
| **P3** | R-07, R-09, R-10, R-12, R-13 | 健壮性与可观测性 |

---

## 11. 附录 A：核心文件清单

> 行数为撰写时快照（2026-10-08）。

### 11.1 治理层（admin-api）

| 文件 | 行数 | 职责 |
|---|---|---|
| `services/admin-api/app/governance/__init__.py` | 22 | 导出 `GateContext` / `gatekeeper` / `GateDecision` / `GateVerdict` |
| `services/admin-api/app/governance/gatekeeper.py` | 164 | 六层编排、短路、审计提前拆出、`DENIAL_STATUS` 映射 |
| `services/admin-api/app/governance/config.py` | 174 | 层顺序、必需层地板、`GateConfig`、配置加载/保存、`GATE_LAYERS` 环境变量 |
| `services/admin-api/app/governance/schema.py` | 100 | 集合常量、`AUTONOMY_MATRIX`（25 格）、默认 PII 策略、`ensure_indexes` |
| `services/admin-api/app/governance/rbac_model.py` | 143 | `PermissionCode` 解析、`parse_codes`、`expand_role_to_codes`、`has_permission`、`required_code_for_tool`、`CAPABILITY_TO_CODES` |
| `services/admin-api/app/governance/risk.py` | 173 | 风险级注册/查询、矩阵判定（**R4 硬编码 deny**）、矩阵变更审计 |
| `services/admin-api/app/governance/pii.py` | 186 | 5 类 PII 识别器、4 种策略、`find_pii` / `redact_text` / `fingerprint` |
| `services/admin-api/app/governance/permission_grants.py` | 195 | 三级显式授权 CRUD、`effective_grant_codes`、索引、变更审计 |
| `services/admin-api/app/governance/layers/__init__.py` | 43 | `build_layers` 工厂（装配 6 层 + quota checker） |
| `services/admin-api/app/governance/layers/identity.py` | 35 | 层1：主体可解析（tenant 必填） |
| `services/admin-api/app/governance/layers/rbac.py` | 96 | 层 2：岗位角色展开 + 显式授权 → 权限码判定 |
| `services/admin-api/app/governance/layers/redaction.py` | 114 | 层 3：PII 脱敏（原地改写 + 指纹留痕） |
| `services/admin-api/app/governance/layers/approval.py` | 266 | 层 4：矩阵判定 + `ApprovalRegistry`（签发/决策/消费/过期） |
| `services/admin-api/app/governance/layers/quota.py` | 183 | 层 5：020 token 预算 + 遗留调用计数 |
| `services/admin-api/app/governance/layers/audit.py` | 75 | 层 6：落`gate_events`，失败即拒绝 |

### 11.2 岗位角色（admin-api）

| 文件 | 行数 | 职责 |
|---|---|---|
| `services/admin-api/app/position_roles/__init__.py` | 5 | 包声明 |
| `services/admin-api/app/position_roles/constants.py` | 16 | 6 个集合名 + 5 个能力键 + `FULL_ACCESS_ROLE_KEY` |
| `services/admin-api/app/position_roles/repository.py` | 178 | 索引、`ensure_full_access_role`、角色绑定（单/批量）、审计写入 |
| `services/admin-api/app/position_roles/service.py` | 179 | CRUD 业务规则（唯一名、高权限复制防护、删除保护、资源 ID 校验） |
| `services/admin-api/app/api/routes/position_roles.py` | 259 | 14 个 HTTP 端点 + 请求模型校验 |

### 11.3 API 层（admin-api）

| 文件 | 行数 | 职责 |
|---|---|---|
| `services/admin-api/app/api/deps.py` | 83 | 3 个认证依赖（authenticated / tenant admin / platform admin） |
| `services/admin-api/app/api/router.py` | 36 | 36 个路由挂载（`/position-roles`、`/internal/gatekeeper`、`/governance`） |
| `services/admin-api/app/api/routes/governance.py` | 207 | 风险级 CRUD、矩阵读写、权限码 grant/revoke/list/check |
| `services/admin-api/app/api/routes/gatekeeper_internal.py` | 235 | 内部端点：`/evaluate`、`/decide`、`/approvals`、`/events` |
| `services/admin-api/app/api/routes/tools.py` | 405 | 工具 CRUD + **`_enforce_gate`（门禁强制）** + 角色回退 |
| `services/admin-api/app/core/tenant_identity.py` | — | `is_platform_main_id` / `is_reserved_main_id` |
| `services/admin-api/app/core/internal_service_auth.py` | 17 | 服务令牌解析（环境变量优先） |
| `services/admin-api/app/core/quota_policy.py` | 259 | 020 配额（**admin-api 版，与 chat-api 有差异**） |
| `services/admin-api/app/services/tenant_purge.py` | 689 | 租户彻底清理（2 个集合清单） |

### 11.4 审计（admin-api）

| 文件 | 行数 | 职责 |
|---|---|---|
| `services/admin-api/app/system_audit/__init__.py` | 6 | 包声明 |
| `services/admin-api/app/system_audit/constants.py` | 24 | 集合名、变更方法集、模块标签、动作映射 |
| `services/admin-api/app/system_audit/middleware.py` | 108 | HTTP 变更审计中间件（**不落请求体**） |
| `services/admin-api/app/system_audit/query.py` | 151 | 4 个查询视图 + `overview` 统计 |
| `services/admin-api/app/system_audit/repository.py` | 30 | 审计写入 |

### 11.5 治理层（chat-api）

| 文件 | 行数 | 职责 |
|---|---|---|
| `services/chat-api/app/services/gatekeeper_client.py` | 111 | 六层链 HTTP 客户端（**fail-closed**） |
| `services/chat-api/app/governance/position_policy.py` | 203 | `EffectiveEmployeePolicy` + 4 个判定方法 + `MongoEmployeePolicyResolver` + `build_effective_policy` |
| `services/chat-api/app/governance/audit.py` | 22 | `record_position_policy_event` → `position_role_audit_logs` |
| `services/chat-api/app/governance/approval_runtime.py` | 100 | chat-api 侧审批运行时 |
| `services/chat-api/app/governance/action_receipt_store.py` | 256 | 动作回执存储 |
| `services/chat-api/app/dsh_runtime/turn_admission.py` | — | `run_gate_plan`（调门禁）+ `admit_skill_selection`（Skill 授权） |
| `services/chat-api/app/harness_config/gate_adapter.py` | 107 | 019 厚度profile → 门禁计划映射 + floor 校验 |
| `services/chat-api/app/core/quota_policy.py` | 291 | 020 配额（**chat-api 版，含2099d5f 修复**） |
| `services/chat-api/app/core/tenant.py` | 36 | `resolve_main_id` / `main_scope_filter` / `add_main_scope` |

### 11.6 数据权限（chat-api）

| 文件 | 行数 | 职责 |
|---|---|---|
| `services/chat-api/app/memory/scope.py` | 158 | 三域枚举、`SCOPE_VISIBILITY`、`visible_to`、`promote_to_org` |
| `services/chat-api/app/memory/store.py` | 222 | MongoDB 存储、租户隔离、FR-16 硬上限 |
| `services/chat-api/app/memory/retrieval.py` | — | `scope_filter` + 检索 |
| `services/chat-api/app/memory/address.py` | — | `mogo://memory/...` 地址与 `parse_memory_uri` |
| `services/chat-api/app/memory/sediment.py` | — | 会话 → 记忆沉淀 |
| `services/chat-api/app/api/endpoints/memory.py` | 218 | 4 个记忆端点（create/list/delete/promote） |
| `services/chat-api/app/context_space/__init__.py` | 34 | 包导出 |
| `services/chat-api/app/context_space/address.py` | 177 | 4 类地址 dataclass + `parse_context_uri` |
| `services/chat-api/app/context_space/visibility.py` | 147 | 委托式可见性 4 个分派 + `ViewerContext` |
| `services/chat-api/app/context_space/router.py` | 101 | `resolve_memory`（统一入口，4 root 注册） |
| `services/chat-api/app/context_space/trace.py` | 75 | `TraceRecord` + candidates/skipped 构造 |
| `services/chat-api/app/context_space/adapters/base.py` | 59 | `TierAdapter` 协议 + `ResolvedTier` |
| `services/chat-api/app/context_space/adapters/memory.py` | 80 | 记忆 tier 解析（**传存储记录给可见性**） |
| `services/chat-api/app/context_space/adapters/resource.py` | 182 | doc/biz/kg tier 解析（**biz 用 URI tenant**） |
| `services/chat-api/app/context_space/adapters/session.py` | 136 | 会话 tier 解析（**带 user_id 过滤**） |
| `services/chat-api/app/context_space/adapters/skill.py` | 154 | Skill tier 解析 |
| `services/chat-api/app/services/personal_knowledge/access.py` | 82 | 个人知识 owner/grant 三态判定 |
| `services/chat-api/app/services/resource_feedback/access.py` | 67 | 反馈访问 3 类型分派 |
| `services/chat-api/app/services/end_user_session.py` | 71 | 员工会话解析（**只返回 3 个键**） |

### 11.7 前端

| 文件 | 行数 | 职责 |
|---|---|---|
| `apps/admin-web/src/api/positionRoles.ts` | 99 | 14 个岗位角色 API 封装 + TS 类型 |
| `apps/admin-web/src/views/position-roles/PositionRolesPage.vue` | 131 | 角色列表 + CRUD + 员工分配 |
| `apps/admin-web/src/views/position-roles/RoleCapabilityEditor.vue` | 92 | 能力开关 + 工具/Skill 编辑器 + 影响预览 |

---

## 12. spec 与代码不一致清单（重要）

> **本章是本文档最有价值的部分。** 每条差异都标注 spec 说什么、代码实际是什么、以及运维/开发的影响。

### 12.1 差异 1：配额三维模型

| | 内容 |
|---|---|
| **spec 说** | 001 FR-8："配额三维（租户/用户/工具）独立配置，计数存于 MongoDB（`quota_counters`，原子 findOneAndUpdate，不引入 Redis）；时间窗口 每分钟/每天/每月"（`specs/001-gatekeeper-governance/spec.md:96`） |
| **代码实际** | `layers/quota.py:1-16` 明确："this repo has no `quota_limits` collection and no consumer for 'call-count limits' (the original spec's three dimensions). What does exist is feature 020's real token-quota system"。三维调用计数路径（`limits_resolver` + `quota_counters`）在生产中**永不触发**——`layers/__init__.py:36-39` 只传`credit_checker`，不传 `limits_resolver` |
| **影响** | ① `quota_counters` 集合生产永不写入；② spec 要求的"每分钟"窗口生产不存在（020 只有 hourly/daily/monthly）；③ spec 的三维配额（按调用次数）实际不可配置 |
| **测试固化** | `test_governance_us4_us5.py:150-199` 测试的是**遗留路径**（直接构造 `QuotaLayer(store=..., limits_resolver=...)`），与生产装配无关 |

### 12.2 差异 2：岗位角色的工具/Skill 授权未打通到权限码

| | 内容 |
|---|---|
| **spec 说** | 001 FR-6："现有岗位角色作为权限码预设组（**角色 → 权限码列表映射，可部分覆盖**），向下兼容"（`spec.md:94`）；US4 AC："岗位角色'工程师'绑定预设权限码组，权限变更即时生效"（`spec.md:67`）。006 FR-5："角色工具/Skill 访问模式为 all 或 selected + 显式 ID 列表"（`specs/006-position-rbac-admin/spec.md:70`） |
| **代码实际** | `CAPABILITY_TO_CODES`（`rbac_model.py:25-31`）**只有 5 条能力键映射**。`tool_ids` / `skill_ids` / `tool_access_mode` / `skill_access_mode` **完全没有对应的权限码展开**。`expand_role_to_codes`（`rbac_model.py:77-101`）只读 `permission_codes` 和 `capabilities` |
| **影响** | **岗位角色的工具授权在门禁 RBAC 层完全无效**（见 [7.1](#71-场景一普通员工发起一次对话) vs [7.2](#72-场景二员工调用外部工具端点chat-api-侧)）。运维必须**双重配置**：岗位角色（给员工看到工具）+ `permission_grants`（让门禁放行） |
| **严重度** | 🔴 高。这是本文档发现的最严重的"spec 承诺 vs 代码实现"gap |

### 12.3 差异 3：三级权限码隔离的语义

| | 内容 |
|---|---|
| **spec 说** | 001 FR-5："三级隔离（租户/组织/用户，**上级含下级，用户级未授权时回落组织级再回落租户级**）"（`spec.md:93`） |
| **代码实际** | `effective_grant_codes`（`permission_grants.py:134-156`）是**纯并集**：`tenant ∪ org ∪ user`，无"回落"语义。且 `org` 因`org_id` 恒空而不可达（见 R-04） |
| **影响** | spec 描述的是"优先级链"（用户级拒绝则回落组织级），代码是"任一层授权即授权"。语义上代码**更宽松**——只要任一层有该码就放行。若产品预期"用户级显式拒绝应阻断组织级授权"，当前实现不满足 |
| **注意** | "回落"一词本身有歧义（可能是"向上回落"也可能是"权限不足时逐级放宽"）。**需产品澄清 spec 意图** |

### 12.4 差异 4：配额层是 pass-through

| | 内容 |
|---|---|
| **spec 说** | 001 FR-1："工具调用必须经过六层串行门禁链（身份→RBAC→脱敏→审批→配额→审计）"（`spec.md:89`）；Success Criteria："配额超限 100% 触发第 5 层拒绝"（`spec.md:111`） |
| **代码实际** | 遗留路径在无 `limits_resolver` 时直接 `return GateVerdict(ALLOW, "quota", "within budget")`（`layers/quota.py:160-162`）。生产装配虽安装了 020 checker（`:36-37`），但 `default_credit_checker` 的探测异常路径 `return None`（`:46-49`） |
| **影响** | 设计上是"复用 020 真实预算"而非 pass-through（`layers/__init__.py:27-29` 注释说明）。但 020 侧的 fail-open（探测失败放行）使第 5 层在存储抖动时形同虚设 |
| **缓解** | 注释明确说明这是有意的 fail-open（`:46-48`）："an unreadable quota row must not block tool calls" |

### 12.5 差异 5：`org_id` 注入缺失

| | 内容 |
|---|---|
| **spec 说** | 001 FR-5 三级隔离含"组织级"（`spec.md:93`）；US4："细粒度 RBAC 权限码模型（001 US4 three-level isolation）"（`layers/rbac.py:40` 注释也这么写） |
| **代码实际** | `org_id` 从 `ctx.annotations` 读取（`rbac.py:50`），但无任何写入方（`gatekeeper_internal.py:88-104`、`tools.py:338-344` 都只放审批字段） |
| **影响** | 组织级授权永久不可达。见 R-04 |

### 12.6 差异 6：021 地址格式要求 tenantId

| | 内容 |
|---|---|
| **spec 说** | 021 US1：`mogo://resource/biz/<system>/<entity_type>/<record_id>`（**不含 tenant**，`spec.md:19`）；`mogo://resource/kg/<node_id>`（**不含 tenant**，`spec.md:20`） |
| **代码实际** | `address.py:66-72` 强制要求第一段是 tenantId：`resource/biz needs <tenantId>/<system>/<entityType>/<recordId>`、`resource/kg needs <tenantId>/<nodeId>` |
| **影响** | **代码比 spec 更严格**。这是好事——强制把租户写进地址使 `check_resource_visibility` 的租户比对成为可能（若按 spec 不带 tenant，该函数无法比对租户）。**建议更新 spec** |
| **例外** | spec 的 `mogo://resource/doc/<tenant_id>/...`（`spec.md:18`）与代码一致 |

### 12.7 差异 7：不可见项是"静默裁剪"还是"抛异常"

| | 内容 |
|---|---|
| **spec 说** | 021 US3 AC："跨范围/无权限 URI → 在候选中被**静默剔除（不报错**，与 017 '不越权'一致）"（`spec.md:51`）；`visibility.py:13-15` 自己的 docstring 也写"Invisible candidates are silently trimmed (never error)" |
| **代码实际** | `router.py:85-88` 在 `ContextVisibilityError` 时记 skipped 后 **`raise` 重新抛出** |
| **影响** | 行为不一致：调用 `resolve_memory` 处理不可见地址会**收到异常**而非静默跳过。若上层有批量解析逻辑（如"解析 10 个地址"），一个不可见就会中断全部 |
| **建议** | 二选一：① 改代码为真正的静默裁剪（`return {"resolved": None, "trace": trace}`）；② 改 spec + docstring 说明是"记轨迹后抛异常" |

### 12.8 差异 8：租户 ID 缺失时的回退

| | 内容 |
|---|---|
| **spec 说** | 020 FR-017："系统 **MUST NOT** 在缺少企业标识时回退到任何默认企业"（`specs/020-platform-multi-tenancy/spec.md:210`）；Edge Case："请求上下文企业标识缺失或为保留值 → 拒绝，绝不回退默认租户"（`spec.md:171`）；US3 AC5："任一业务请求，当请求上下文缺失企业标识或使用了保留标识 → 一律拒绝，不回退到默认租户"（`spec.md:69`） |
| **代码实际** | `resolve_main_id(value)`（`core/tenant.py:9-11`）：`return str(value or "").strip() or DEFAULT_MAIN_ID`，即 `""` → `"default"`。`main_scope_filter("default")`（`:14-25`）变成 `$or` 匹配所有无 `main_id` 字段的文档 |
| **缓解** | **认证层**已严格：`admin-api/app/api/deps.py:14-16` 注释明确"removing it is what closes the cross-tenant leak"，空 main_id 直接 401。所以认证层无此问题。问题在**数据层兜底** |
| **影响** | 单租户部署 ✅ 符合预期。多租户部署中若某处漏传 main_id，查询会匹配所有历史无 `main_id` 标记的文档 |
| **建议** | 保留 `resolve_main_id` 的兼容行为，但在多租户模式下（`tenants` 集合有>1 条记录）改为抛错 |

### 12.9 差异 9：不存在"本部门及子树"数据范围

| | 内容 |
|---|---|
| **task-lead 给定范围** | 数据可见范围应包括"个人 / 本组织 / **本部门及子树** / 本租户 / 全局" |
| **代码实际** | `org_units` 集合存在（`auth.py:38` 的 `DEPARTMENT_COLLECTION`），但**不参与任何数据可见性判定**。全部 6 套机制（见 [4.1](#41-数据权限的六套机制)）中没有部门/组织层级概念 |
| **影响** | 若产品需要"部门经理能看到本部门及下级的数据"，**当前代码不支持**，需新增数据范围类型 |
| **建议** | 需产品明确是否需要。若需要，应参照 `visible_to` 的模式新增 `department` scope，并在 `position_policy` 中加入组织层级解析 |

### 12.10 差异 10：021 resource 根的委托目标不存在

| | 内容 |
|---|---|
| **spec 说** | 021 US3："doc → 005 `retrieval_access_policy`（租户/组织隔离）；biz → 014 `bizdata:read`（001 权限码）；kg → 015 `kg:read`（001 权限码）"（`spec.md:44-46`） |
| **代码实际** | `check_resource_visibility`（`visibility.py:84-94`）**只比对 `addr.tenant_id == ctx.tenant_id`**。`retrieval_access_policy` 函数在代码中**不存在**；`bizdata:read` / `kg:read` 权限码**从未被检查** |
| **影响** | 见 R-03。resource 根只有租户级隔离，无个人/部门/权限码级隔离 |

### 12.11 差异 11：检索轨迹未落库

| | 内容 |
|---|---|
| **spec 说** | 017 FR-16："每次检索产出 `retrieval_trace`... 轨迹落**观测日志**（非 001 审计），支持按 `trace_id` 回看与调试"（`specs/017-three-scope-memory/spec.md:72`）；021 US4："一次检索 → 1 条 trace"（`spec.md:59`）；Success Criteria："检索轨迹 100% 可回看（按 trace_id）"（`spec.md:95`） |
| **代码实际** | `build_trace`（`trace.py:38-51`）只在内存构造 `TraceRecord`；`router.py:100-101` 返回 `trace.to_dict()`。**代码中无任何持久化调用**——`log_print` 都没调用 |
| **影响** | 轨迹只存在于返回值里，调用方不保存就丢失。"按 trace_id 回看"无法实现 |
| **建议** | 在 `router.py:101` 后加 `log_print(json.dumps(trace.to_dict()))` 或写入观测日志集合 |

### 12.12 差异 12：017 的"生命周期可配置"

| | 内容 |
|---|---|
| **spec 说** | 017 FR-8："记忆生命周期（衰减/清理）可配置；衰减周期默认 30 天，访问命中重置计时"（`spec.md:64`）；Success Criteria："记忆生命周期 100% 可配置"（`spec.md:88`） |
| **代码实际** | `lifecycle.py` 存在（`services/chat-api/app/memory/lifecycle.py`）。`summary_refresh_days` 可配置（`MEMORY_SUMMARY_REFRESH_DAYS`），但这是**摘要过期窗口**（FR-15）不是**记忆衰减周期**（FR-8）。`Memory.archived` 字段存在（`scope.py:60`）由衰减扫描打标 |
| **影响** | 摘要窗口可配 ✅；衰减周期本身**未见配置项**（可能是硬编码 30 天） |

### 12.13 差异 13：`pii_policies` 无 CRUD 端点

| | 内容 |
|---|---|
| **spec 说** | `pii.py:26-27` 注释："An override requires 006 authorization at the admin boundary (**enforced at the CRUD endpoint**) and is audited (FR-10)"；001 OQ-3："租户级可覆盖（白名单 + 策略改配走 006 RBAC 授权 + 001 审计）"（`specs/001-gatekeeper-governance/spec.md:155`） |
| **代码实际** | `api/routes/` 下**无 `pii_policies` 的 CRUD 路由**。策略只能直接操作数据库 |
| **影响** | ① 租户无法自助配置脱敏策略；② spec 声称的"006 RBAC 授权"无处实现；③ `redaction.py:59-60` 的租户覆盖路径**永远走不到**（除非手工改库） |
| **建议** | 新增 `POST/PUT/DELETE /api/governance/pii-policies`，用 `get_current_admin_user` + 审计 |

### 12.14 差异 14：配额双实现漂移

| | 内容 |
|---|---|
| **背景** | `2099d5f`（2026-10-08）修复了 chat-api 侧的"未配置配额视为不限量"，但**admin-api 侧未同步** |
| **chat-api（有修复）** | `core/quota_policy.py:178-190`（`points_unlimited` 短路）、`:198-213`（个人空间 `total<=0` → unlimited）、`:241-256`（企业空间 `org_total<=0 且 user_total<=0` → unlimited）、`:283-285`（`assert_quota_available` 的 unlimited 短路）、`:169`（`space_type` 读 org 字段）、**`ensure_org_quota_policy` 不写 `unlimited`** |
| **admin-api（无修复）** | `core/quota_policy.py:179-192`（个人空间无 `total<=0` 检查）、`:225-231`（企业空间无 `org_total<=0` 检查）、`:169`（`space_type` 只读 user）、**`ensure_org_quota_policy` 写 `unlimited: True`**（`:87`） |
| **影响** | **门禁第 5 层用 admin-api 版本**（`layers/quota.py:39`）。存量租户若`org_quota_policies` 有历史记录（缺 `unlimited` 字段），`bool(org_policy.get("unlimited", False))` = False（`:203`）→ 走限额路径 → `org_total=0` → `remaining=0` → **门禁 DENY(429)**，而 chat-api 业务侧已放行 |
| **额外** | 两服务 `utc_now()` 时区处理不同：admin-api 返回 aware（`:27`），chat-api 返回 naive（`chat-api/app/core/quota_policy.py:26`） |
| **建议** | 抽取共享的配额计算模块，或至少把 `2099d5f` 的 3 个 fallback 同步到 admin-api |

### 12.15 差异 15：权限码资源维度无注册表

| | 内容 |
|---|---|
| **spec 说** | 001 Success Criteria："权限码模型支持至少 **10 个 resource × 3 个 action** 的权限码"（`spec.md:113`）；"跨特性关系"："001 权限码模型支持下游特性注册 resource 维度——014 的 `bizdata`、015 的 `kg`"（`spec.md:140`） |
| **代码实际** | 无 resource/action 枚举或注册表。权限码是完全开放的字符串（`rbac_model.py:46-57` 只校验 `<非空>:<非空>` 格式）。实际使用的 resource 只有 5 个（`CAPABILITY_TO_CODES`）+动态的 `<tool_id>:execute` |
| **影响** | ① 无法给出"该码不存在"的诊断（拼错与未注册行为相同）；② 无从校验"至少 10×3"；③ `bizdata` / `kg` 这两个 spec 点名的 resource **在代码中完全没出现** |
| **建议** | 引入权限码注册表（可以是简单的 `permission_code_registry` 集合 + 启动时校验），或在文档中明确"权限码是开放字符串" |

### 12.16 差异 16：`org_skill:` 前缀的 spec 缺失

| | 内容 |
|---|---|
| **代码实际** | `position_policy.py:51-60` 的 `allows_skill` 处理 `org_skill:<id>` 别名；`resource_feedback/access.py:47` 用 `resource_id.removeprefix("org_skill:")` |
| **spec 状态** | 006 spec 与 021 spec 均**未提及**这个前缀约定 |
| **影响** | 治理身份约定只存在于代码注释中（`position_policy.py:52-54`）。新开发者不知道这个约定，容易在别处漏掉前缀处理导致 bypass |
| **建议** | 把这个约定写进 spec 或 ADR |

### 12.17 差异汇总表

| # | 差异 | 严重度 | 代码是否符合 spec |
|---|---|---|---|
| 1 | 配额三维模型 | 🟡 中 | ❌ 代码换成了 020 token 预算（合理，但 spec 未更新） |
| 2 | **岗位角色工具授权 → 权限码** | 🔴 高 | ❌ **完全未实现** |
| 3 | 三级权限码的"回落"语义 | 🟡 中 | ❌ 代码是纯并集（需产品澄清 spec） |
| 4 | 配额层 pass-through | 🟢 低 | ⚠️ 设计变更，注释有说明 |
| 5 | `org_id` 注入缺失 | 🟠 高 | ❌ 未实现 |
| 6 | 021 地址格式要求 tenantId | 🟢 低 | ⚠️ **代码比 spec 更好**，应更新 spec |
| 7 | 静默裁剪 vs 抛异常 | 🟡 中 | ❌ 代码抛异常，docstring 说静默 |
| 8 | 租户 ID 缺失回退 | 🟠 高 | ❌ 数据层回退（认证层已修） |
| 9 | 不存在"部门及子树" | 🟠 高 | ❌ 未实现（若产品需要） |
| 10 | **021 resource 根委托目标不存在** | 🔴 高 | ❌ 未实现 |
| 11 | 检索轨迹未落库 | 🟡 中 | ❌ 未实现 |
| 12 | 记忆衰减周期可配置 | 🟢 低 | ⚠️ 部分（摘要窗口可配，衰减周期未验证） |
| 13 | `pii_policies` CRUD 端点 | 🟡 中 | ❌ 未实现 |
| 14 | **配额双实现漂移** | 🟠 高 | ❌ admin-api 侧缺 `2099d5f` 修复 |
| 15 | 权限码资源维度注册表 | 🟡 中 | ❌ 未实现 |
| 16 | `org_skill:` 前缀约定 | 🔵 低 | ⚠️ 代码有，spec 无 |

**统计**：16 条差异中，**代码不符合 spec 的有 12 条**，代码优于 spec 的 2 条，spec 缺失（代码有实现）2 条。

---

## 13. 附录 C：权限点全表

### 13.1 权限码（Permission Codes）

#### 13.1.1 代码中实际出现的权限码

| 权限码 | 来源 | 含义 |
|---|---|---|
| `*` | `rbac_model.py:34` `WILDCARD_CODE` | 通配符，仅 `full_access_admin` 展开产生 |
| `content:generate` | `rbac_model.py:26` | 内容生成能力 |
| `image:generate` | `:27` | 图片生成能力 |
| `code:execute` | `:28` | 代码生成能力 |
| `browser:automate` | `:29` | 浏览器自动化能力 |
| `knowledge:read` | `:30` | 内部知识检索能力 |
| `<tool_id>:execute` | `rbac_model.py:137-143` `required_code_for_tool` 默认动作 | 工具调用（动态生成） |
| `<tool_id>:<action>[:<target>]` | `permission_grants.grant_code()` | 管理员显式授予（任意） |

#### 13.1.2 spec 点名但代码中不存在的权限码

| 权限码 | spec 出处 | 状态 |
|---|---|---|
| `admin:role:assign` | 001 US4 AC（`spec.md:66`） | ❌ 代码中无产生方（仅测试用） |
| `bizdata:read` | 001 跨特性（`spec.md:140`） | ❌ 完全不存在 |
| `kg:read` | 001 跨特性（`spec.md:140`） | ❌ 完全不存在 |

### 13.2 Agent 能力键（Agent Capability Keys）

| 键 | 权限码 | 内部能力引用映射 | 前端标签 |
|---|---|---|---|
| `content_generation` | `content:generate` | `content.produce@v1`、`presentation.create@v1`、`document.pdf_retain_pages@v1` | 内容生成 |
| `image_generation` | `image:generate` | `image.generate@v1` | 图片生成 |
| `code_generation` | `code:execute` | — | 代码生成 |
| `browser_automation` | `browser:automate` | `browser.task@v1` | 浏览器自动运行 |
| `internal_knowledge` | `knowledge:read` | `knowledge.search@v1` | 内部知识检索 |

### 13.3 六层门禁的拒绝映射

| 层 | 状态码 | `DENIAL_STATUS` 键 | 触发条件 |
|---|---|---|---|
| `identity` | 403 | `"identity"` | tenant 缺失，或 user+roles 均缺失 |
| `rbac` | 403 | `"rbac"` | 无权限码 / 权限码不满足 |
| `redaction` | 403 | `"redaction"` | （实际不触发，该层永不拒绝） |
| `approval` | 409 | `"approval"` | 矩阵 `require_approval`，或 token 无效 |
| `quota` | 429 | `"quota"` | token 预算耗尽 |
| `audit` | 500 | `"audit"` | 审计落库失败 |
| 其他 | 403 | 兜底 | — |

### 13.4 自主矩阵（25 格）

`schema.py:32-38` 的规范值表：

| L\R | R0 | R1 | R2 | R3 | R4 |
|---|---|---|---|---|---|
| **L1** | allow | allow | allow | require_approval | **deny** |
| **L2** | allow | allow | allow | require_approval | **deny** |
| **L3** | allow | allow | require_approval | require_approval | **deny** |
| **L4** | allow | allow | require_approval | require_approval | **deny** |
| **L5** | allow | allow | allow | require_approval | **deny** |

不可覆盖规则（`risk.py:117-118`）：

```python
if risk == "R4":
    return "deny"# 硬编码，任何存储值都被忽略
```

管理端也有防护（`routes/governance.py:111-115`）：R4 单元格改非 deny → 400。

未知格回退（`risk.py:141-143`）：`return "allow"`（**fail-open**）。

### 13.5 API 端点的权限要求全表

#### 13.5.1 admin-api 治理端点

| 端点 | 方法 | 认证依赖 | 额外权限 |
|---|---|---|---|
| `/api/governance/risk-tiers` | POST | `get_current_admin_user` | 无（任何租户管理员） |
| `/api/governance/risk-tiers` | GET | `get_current_admin_user` | 无 |
| `/api/governance/autonomy-matrix` | GET | `get_current_admin_user` | 无 |
| `/api/governance/autonomy-matrix/cells` | PUT | `get_current_admin_user` | R4 冻结校验 |
| `/api/governance/permissions/grant` | POST | `get_current_admin_user` | 无 |
| `/api/governance/permissions/revoke` | POST | `get_current_admin_user` | 无 |
| `/api/governance/permissions` | GET | `get_current_admin_user` | 无 |
| `/api/governance/permissions/check` | GET | `get_current_admin_user` | 无（且逻辑错误 R-08） |
| `/api/internal/gatekeeper/*` | 4 个 | `X-MOVO-Service-Token` | hmac 时序安全比较 |

⚠️ **治理端点无细粒度权限**：任何租户管理员都能改自主矩阵、授予任意权限码。若需要"只有超级管理员能改矩阵"，当前无此控制。

#### 13.5.2 admin-api 岗位角色端点

全部用 `get_current_admin_user`（`position_roles.py`）：

| 端点 | 方法 | 额外校验 |
|---|---|---|
| `/api/position-roles` | GET/POST | POST 校验资源 ID 存在性 |
| `/api/position-roles/{id}` | PUT/DELETE | PUT 拒绝系统角色；DELETE 拒绝 protected + 有成员 |
| `/api/position-roles/{id}/copy` | POST | 拒绝 `all` 模式源角色 |
| `/api/position-roles/{id}/status` | PATCH | 拒绝停用 `full_access_admin` |
| `/api/position-roles/catalog/resources` | GET | 只返回本租户 active 工具/Skill |
| `/api/position-roles/assignments/*` | 6 个 | 主角色必须在集内、角色必须 active |

⚠️ **无"谁能管理岗位角色"的区分**——任何租户管理员都能改任何岗位角色，包括给别人授予 `tool_access_mode: "all"`。

#### 13.5.3 chat-api 员工侧端点

| 端点 | 判定 | 位置 |
|---|---|---|
| `/api/memories`（POST） | scope 合法性 + org需 `full_access_admin` | `memory.py:42-53` |
| `/api/memories`（GET） | `list_for_viewer` + 可选 scope 过滤 | `:117-125` |
| `/api/memories/{id}`（DELETE） | store 按 `(tenant_id, owner_id)` 过滤 | `:166` |
| `/api/memories/{id}/promote`（PATCH） | 存在性 + owner + `full_access_admin` | `:192-201` |
| `/api/tools/*` | `allows_external_tool` | `external_tools.py:54-55,68` |
| Skill 选择 | `allows_skill` | `turn_admission.py:329` |
| 代码生成任务 | `allows_capability("code_generation")` | `dsh_chat.py:31-32` |
| 工具/Skill 实际调用 | 六层门禁（HTTP） | `turn_admission.py:244-253` |

### 13.6 记忆范围与可见性全表

| scope | visibility | 判定条件 | 特例 |
|---|---|---|---|
| `personal` | `owner` | `viewer_id == memory.owner_id` | `full_access_admin` 可读任意 scope |
| `workspace` | `members` | `is_workspace_member and viewer_id != ""` | 同上 |
| `org` | `organization` | `viewer_id != ""` | 同上+ ⚠️ 不校验租户（R-10） |

### 13.7 数据范围判定全表

| 数据对象 | 判定函数 | 粒度 | fail 模式 |
|---|---|---|---|
| 记忆 | `memory/scope.py::visible_to` | personal/workspace/org | 返回 False（`return False`，`scope.py:113`） |
| resource 地址 | `context_space/visibility.py::check_resource_visibility` | 租户 | 空tenant → True（R-07） |
| skill 地址 | `check_skill_visibility` | 租户（asset 根不判） | 空 tenant → True |
| session 地址 | `check_session_visibility` | 租户 | 空 tenant → True |
| session 数据加载 | `adapters/session.py:91` | 租户 + **owner** | 查不到 → `ContextNotFoundError` |
| 个人知识 | `personal_knowledge/access.py::require_view` | owner / grant | `PermissionError` / `LookupError` |
| Skill 分发反馈 | `resource_feedback/access.py::_distribution` | owner / member | `PermissionError` |
| 组织 Skill 反馈 | `_organization_skill` |岗位策略 `allows_skill` | `PermissionError` |
| 外部工具 | `position_policy.py::allows_external_tool` | 角色 + override | 返回 False |
| Skill | `allows_skill` | 角色 + override（含 `org_skill:` 别名） | 返回 False |
| 能力 | `allows_capability` | 角色 + override | 返回 False（缺键也是 False） |
| 内部能力引用 | `allows_internal` | 映射到能力键 | **未注册 → True**（R-13） |

---

## 14. 附录 D：死代码与未接线清单

以下符号**已定义但无生产调用者**（仅测试或完全未使用）。列出以便清理或补接线。

| 符号 | 定义位置 | 状态 | 说明 |
|---|---|---|---|
| `GateConfig.for_tenant` | `governance/config.py:68-78` | **完全未调用** | 租户级层覆盖。`tenant_overrides` 字段因此是死字段。测试 `test_governance_config.py:60-67` 覆盖了该函数但生产不用 |
| `gate_config_env_override` | `config.py:127-132` | **完全未调用** | `GATE_LAYERS` 环境变量。**运维会以为设它能改层，实际完全无效** |
| `layer_enabled` | `config.py:122-124` | **完全未调用** | — |
| `ApprovalRegistry.validate_and_consume` | `layers/approval.py:147-173` | **仅保留兼容** | docstring 标"DEPRECATED"。原实现允许调用者自我审批，2026-10-03 改为 `decide` + `consume` 两步 |
| `ApprovalRegistry.deny` | `layers/approval.py:175-188` | **未被门禁调用** | `decide(approved=False)` 已覆盖 deny 语义 |
| `GateContext.actor()` | `gatekeeper.py:61-62` | 被 `approval.py:216` 调用 | ✅ 正常使用 |
| `Memory.addr()` | `memory/scope.py:79-85` | 被端点调用 | ✅ |
| `Memory.visibility()` | `scope.py:76-77` | **未被生产调用** | `SCOPE_VISIBILITY` 的 accessor |
| `promoted_memories_retrievable` | `memory/retrieval.py:186-211` | **未被生产调用** | T011 的验证函数 |
| `quota_counters` 集合 | `layers/quota.py:25` | **生产永不写入** | 见 [12.1](#121-差异-1) |
| `WINDOWS` | `layers/quota.py:28` | 仅遗留路径使用 | 生产不使用 |
| `QuotaLayer` 的 `limits_resolver` | `layers/quota.py:120,137-142` | **生产永不触发** | `build_layers` 不传 |
| `PermissionCode.__str__` | `rbac_model.py:59-63` | 被 `parse_codes` 使用 | ✅（标`pragma: no cover`） |
| `main_id` 参数 `_load_biz` | `adapters/resource.py:113` | **被第一行覆盖** | 见 R-09 |
| `risk.list_risk_tiers` | `risk.py:68-77` | 被治理端点调用 | ✅ |
| `redaction.strategy == "pass_through"` | `pii.py:170` | **不在 `STRATEGIES` 内** | 死分支：`effective.get(t) != "pass_through"` 恒真（4 个策略都 != pass_through） |
| `PII 策略的"白名单"** | 001 OQ-3 提及 | **未实现** | spec 说"白名单 + 策略改配"，代码只有策略改配 |

### 14.1 未接线的功能点

| 功能 | spec | 代码 | 状态 |
|---|---|---|---|
| 审批待办 UI | 001 OQ-1："恢复机制：**poll**（前端轮询 `list_pending`/`decide`）"（`spec.md:146`） | `gatekeeper_internal.py:162-193` 有 `GET /approvals`，但 `api/router.py` 无管理端挂载，`apps/admin-web` 无调用 | **后端有API，前端无UI** |
| 门禁审计查看 UI | 001 FR-9 要求可追溯 | `gatekeeper_internal.py:196-235` 有 `GET /events`，同样无管理端挂载 | **后端有 API，前端无 UI** |
| `pii_policies` 管理 UI | 001 OQ-3 | 无端点、无 UI | **完全未实现** |
| 检索轨迹回看 | 017 FR-16 / 021 US4 | 无落库、无 UI | **完全未实现** |
| 部门数据范围 | — | 无 | **未实现**（见 [12.9](#129-差异-9)） |

---

## 15. 结论与建议

### 15.1 平台权限模型的 strengths

1. **门禁链的 fail-closed 设计扎实**。6 层中除2 处有意的 fail-open（未知工具风险级、配额探测失败）外，全部 fail-closed。审计落库失败即拒绝整个调用（`gatekeeper.py:150-151`），且有测试固化。
2. **红线不可覆盖是双重强制**。`risk.py:117-118` 硬编码 + `routes/governance.py:111-115` API 层拦截。即使有人直接改数据库，`matrix_decision` 仍返回 `deny`。
3. **审批已修正"自我审批"漏洞**。`decide`（审批人）+ `consume`（请求者）两步分离（`approval.py:92-145`），2026-10-03 修复。
4. **R3 审计修复了"URI 即凭证"漏洞**。`visibility.py:50-81` + `adapters/session.py:86-92` 两处，且都有攻击场景命名的测试。
5. **岗位角色的高权限路径有防护**。不可改/不可停/不可删（`service.py:71-72,102-103,111-112`）+ 拒绝复制 `all` 模式角色（`service.py:86-97`）。
6. **服务间认证用时序安全比较**（`gatekeeper_internal.py:30`）。
7. **脱敏在请求体层面生效并回传**（`gatekeeper_internal.py:116-118` + `turn_admission.py:265-269`），且审计只存指纹。

### 15.2 平台权限模型的核心弱点

1. **006 岗位策略与 001 权限码两套体系未打通**（差异 2）。这是最大的语义 gap——管理员配了岗位角色的工具白名单，员工在对话框能看到，但实际调用被门禁拒。
2. **021 地址层对 resource 根的委托不完整**（差异 10 / R-03）。只有租户隔离，无个人/部门/权限码隔离。
3. **chat-api 端点的 session 解析契约破裂**（R-01）。8 个端点测试建立在 mock 的错误前提上。
4. **组织级授权完全不可达**（差异 5 / R-04）。API 接受配置但永不生效，会误导管理员放大授权范围。
5. **多处 fail-open 默认值**（未知工具 R0、未知格 allow、未注册 capability_ref 放行、可见性空 tenant 放行）。单看每一处都合理，累积起来是系统性风险。

### 15.3 建议的行动项

| 优先级 | 行动 | 对应风险/差异 | 预计工作量 |
|---|---|---|---|
| **P0** | 修复 `resolve_session_user` 返回字段 + 补真实契约测试 | R-01 | 0.5 天 + 测试 |
| **P0** | 把"无角色且迁移未完成 → 全开"改为 fail-closed + 告警 | R-02 | 0.5 天 |
| **P1** | resource 根委托 `PersonalKnowledgeAccessService`；空 tenant 改 fail-closed | R-03, R-07, 差异 10 | 2 天 |
| **P1** | 注入 `org_id`（查 `end_user_org_relations`）或删除 org 级授权 API | R-04, 差异 5 | 1 天 |
| **P1** | `rbac.py` 的角色查询加 `status: "active"` | R-05 | 0.5 小时 + 测试 |
| **P1** | 同步 `2099d5f` 的 3 个 fallback 到 admin-api 配额 | 差异 14 | 1 小时 |
| **P2** | 补 `discover` / `generate-description` 的门禁 | R-06 | 2 小时 |
| **P2** | 修复 `permissions/check` 端点 | R-08 | 2 小时 |
| **P2** | `promote_memory` 补齐字段，或加 `update_scope` 方法 | R-11 | 1 小时 |
| **P2** | 为 `tool_ids`/`skill_ids` 增加权限码展开，或明确文档化"需双重配置" | 差异 2 | 需产品决策 |
| **P3** | 可见性拒绝落审计 | R-12 | 1 天 |
| **P3** | `allows_internal` 改 fail-closed + 白名单 | R-13 | 2 小时 |
| **P3** | 清理或接线死代码（`for_tenant` / `GATE_LAYERS` / `validate_and_consume` 等） | 附录 D | 2 小时 |
| **P3** | 检索轨迹落库 | 差异 11 | 1 天 |
| **P3** | 更新 6 份 spec 以反映代码现状（差异 1/6/7/16） | 附录 B | 0.5 天 |

### 15.4 运维检查清单

上线前逐项确认：

- [ ] `ADMIN_BACKEND_SERVICE_TOKEN` 两侧配置**且一致**
- [ ] `END_USER_AUTH_SECRET` 与 admin JWT secret 已配置（非默认值）
- [ ] `gatekeeper_rules` 集合中 `kind="gate_config"` 文档的 `enabled_layers` 含全部 4 个必需层
- [ ] `autonomy_matrix` 集合已 seed（`schema.py:_seed_defaults`），**特别是所有 R4 格为 deny**
- [ ] 每个租户的 `org_quota_policies` 有 `unlimited` 字段（或明确接受限额为 0 的后果）
- [ ] 每个租户已调用 `POST /api/position-roles/assignments/migration/complete`（否则触发 R-02）
- [ ] 每个员工至少绑定一个岗位角色
- [ ] `TENANT_SCOPED_COLLECTIONS` + `TENANT_GOVERNANCE_COLLECTIONS` 覆盖所有新加的集合
- [ ] `gate_events` 的 `audit` 层未被禁用（否则所有工具调用被拒）
- [ ] `memories` 集合已建 `(tenant_id, scope)` 索引

---

## 文档修订记录

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026-10-08 | v1.0 | 首版。基于 main 分支代码快照撰写。覆盖 001/006/017/020/021 五个 spec + 56 个代码文件 + 20 个测试文件。记录 16 条 spec-vs代码差异与 13 个风险点。 |
