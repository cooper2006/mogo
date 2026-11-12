# Feature Specification: 审批单一内核（056-unified-approval-kernel）

**Feature Branch**: `056-unified-approval-kernel`

**Created**: 2026-11-12

**Status**: Draft

**Input**: 通用设计复审报告 §整改路线第 3 项："把审批收敛为一个内核：统一票据/待办查询/审计出口（gate_events）/审批人解析；补 revision 原子条件更新仲裁（取消、决策、超时、驳回优先）；补 reassign 到 resolve_review"

> **来源说明**：本特性是对既有 `services/chat-api/app/governance/approval_runtime.py`（进程内票据 dict）、`services/admin-api/app/governance/layers/approval.py`（admin 层 `gate_approvals` collection）、`services/chat-api/app/services/portal/requests.py`（申领单状态机）三套并存状态的结构性合并。代码未做新能力引入，属架构治理类变更，影响面为三个服务的调用方接口。

## 背景与问题

当前审批能力分属于三个历史实现，各自维护独立的状态机与待办端点：

| 层 | 代码位置 | 状态机 | 待办端点 |
|---|---|---|---|
| 进程内票据 | `chat-api/governance/approval_runtime.py:25-100` | `pending → approved/denied/expired`（内存 dict） | 无持久化端点 |
| admin 审批层 | `admin-api/governance/layers/approval.py:46-199` | `pending → approved → consumed / denied`（MongoDB `gate_approvals`） | `POST /internal/admin/approvals/{id}/decide` |
| 037 申领 | `chat-api/services/portal/requests.py:74-79,478-565` | `applied → granted → revoked`（`portal_requests`） | `POST /api/v1/portal/admin/approvals/{id}` |

此外，050 SOP 编排的审批节点走的是 `run_store.claim_pending()` + `human_approval.decide()` 路径，既不经过 `ApprovalRegistry.decide()`，也不走 037 申领流程。三者互不相识，导致：

1. **P1-1 三套身份口径**：037 `approver_id`（`requests.py:216-237`）与 admin 决策端 `PORTAL_APPROVE` 不校验 `actor == approver_id`（`portal_admin.py:463-467,488-490`），两套身份体系并存
2. **P1-2 TOCTOU 竞态**：`cancel()`（`:294-309`）读-改-写分离，`record_decision()`（`:203-207`）无并发保护，"取消覆盖已生效决策"或"终态被覆盖"均可能发生
3. **P1-3 审计链断裂**：orchestration 目录零命中 `gate_events` 写入方（见 `audit_events.py:3` 注释），SOP 审批事件只对 `orchestration_runs.events[]` / `decision_history[]` 自洽，跨能力对账是盲区
4. **P1-4 改派出口残缺**：`reassign()`（`:277-292`）只 `$set` 改 `approver`，不改状态、不重生成 `resume_token` / `deadline`；`resolve_review` 端点只收 `("skip","terminate")` 不接受 `reassign`；审批人离职触发 `needs_review` 后新审批人看不到待办 → 死锁

## 用户故事

### User Story 1 — 管理员查看统一审批待办并完成决策（Priority: P1）🎯 MVP

管理员在管理端「审批中心」看到所有来源（admin 工具审批 + 037 申领 + 050 SOP 运行）的统一待办列表；点击某条待办后进入决策页，可批准/驳回/改派；操作立即生效并写入审计。

**Why this priority**: 这是本次重构的直接目的——消除三套状态机并存的混乱局面；任何单一来源都无法单独提供端到端价值，必须合并后才可用。

**Independent Test**: 起服后通过 admin API 分别走三种来源各创建一条待办，断言三条都在同一列表端点可见；分别执行批准/驳回/改派，断言对应来源的状态同步推进、审计事件中三类 action 均有记录且前缀可区分。

**Acceptance Scenarios**:

1. **Given** 系统中存在来自 admin 审批层、037 申领、050 SOP 运行三处来源的各一条待办，**When** 访问统一待办列表端点 `GET /api/v1/admin/approvals/todos?status=pending&approver={user_id}`，**Then** 返回三条待办，每条含统一字段 `source_type`（`tool`/`portal`/`sop`）、`source_id`、`approver_id`、`deadline`、`state`。
2. **Given** 一条 pending 待办，**When** 审批人通过 `POST /api/v1/admin/approvals/{source_type}/{source_id}/decide` 提交批准（附理由），**Then** 该待办状态变为 `approved`，对应的业务操作（工具放行/申领开通/SOP 续跑）立即执行，一条 `approval.decided` 事件落 `gate_events`。
3. **Given** 一条 pending 待办，**When** 审批人通过同一端点提交驳回（必填理由 ≤500 字符），**Then** 该待办状态变为 `denied`，对应业务失败（拒绝工具调用/关闭申领申请/SOP 运行终止），一条 `approval.denied` 事件落 `gate_events`。
4. **Given** 一条 pending 待办，审批人已离职或不可用，**When** 管理员通过 `POST /api/v1/admin/approvals/{id}/reassign` 改派给新审批人（同 tenant 有效用户），**Then** 待办的 `approver_id`、`deadline`（重新计算）、`resume_token`（重新签发）均已更新，原审批人的决策窗口关闭，新审批人在 `list_todos` 可见。

---

### User Story 2 — 并发决策与取消的原子仲裁（Priority: P1）

两条路径在同一待办的不同时刻到达时（取消 vs 决策），以先到者为准，后者幂等返回一致结论；不会出现「取消后又批准」「一分支驳回另一分支仍在」等非法终态。

**Why this priority**: P0-1 已修复 `claim_pending` BEFORE/AFTER bug，但 P1-2 描述的 TOCTOU 问题仍然存在——`cancel()` 与 `record_decision()` 仍是两个独立的更新操作，无前置条件锁，并发下会互相覆盖。

**Independent Test**: 起服后用两条并发请求分别调用 cancel() 和 decide() 作用于同一 run_id，断言最终状态为终态（`cancelled` 或 `rejected`/`completed`），且两次请求均返回一致结果（幂等），审计中只有单一决策事件。

**Acceptance Scenarios**:

1. **Given** 运行处于 `awaiting_approval` 状态，**When** 取消请求先到达（`POST /runs/{id}/cancel`），**Then** 运行状态置 `cancelled`、`pending_approvals` 清空、一条 `run.cancelled` 事件落 `gate_events`；后到的批准请求因运行已非 `awaiting_approval` 而拒绝，返回幂等的 "已取消" 结论、无副作用。
2. **Given** 运行处于 `awaiting_approval` 状态，**When** 批准决策先到达并成功消费票据，**Then** 运行从挂起点续跑、`pending_approvals` 删除、一条 `approval.decided.approve` 事件落 `gate_events`；后到的取消请求因运行已非 `awaiting_approval` 而拒绝。
3. **Given** 运行有两个并行审批节点 A、B，**When** A 被驳回（任一审批人），**Then** 整个运行立即进入 `rejected` 终态，B 的待办同步作废（不再出现在 `list_todos`），不等待 B 的审批。
4. **Given** 运行正在恢复扫描中被判定超时，**When** 同一毫秒内审批人提交了批准决策，**Then** 以 `claim_pending` 的原子性为先，批准生效（不会同时出现 timeout 和 approve 两种状态）。

---

### User Story 3 — 跨服务审批事件统一汇入 001 审计汇（Priority: P2）

所有审批相关的生命周期事件（issue/decide/deny/reassign/timeout/cancel）都写入 001 gatekeeper 的 `gate_events` 集合，事件前缀按来源分类（`approval.tool.*`、`approval.portal.*`、`approval.sop.*`），供跨能力对账与审计检索使用。

**Why this priority**: P1-3 指出当前 orchestration 目录零命中 `gate_events` 写入方，SOP 审批是唯一缺失的审计闭环。虽不影响运行时正确性，但违反 Constitution III（"所有管理面操作必须可审计"）。

**Independent Test**: 创建一个 050 SOP 审批运行并通过 Admin API 完成一次批准操作，断言 `gate_events` 集合中存在一条 `approval.sop.decided` 事件，其 `action`、`actor_id`、`tenant_id`、`detail.source_type=sop`、`detail.run_id` 字段完整可读；与 `orchestration_runs.events[]` 中的同源事件核对一致。

**Acceptance Scenarios**:

1. **Given** 任意审批操作的发起（无论 tool/portal/sop），**When** 操作完成，**Then** 一条带 `source_service=chat-api` 的审计事件落 `gate_events`，event action 形如 `approval.{source_type}.{approve|deny|reassign|issue|timeout}`。
2. **Given** 审计库与业务库分离配置（`MONGODB_AUDIT_DB`），**When** 写入审批事件，**Then** 事件落到审计库（遵循 T044 的 `get_audit_db()` 语义），不对业务库产生额外写压力。
3. **Given** 审计写入失败（存储异常），**When** 重试 3 次仍失败，**Then** 操作本身继续（fail-open 降级与 001 既有用例一致），但记录一条错误日志 `approval.audit_write_failed`，供运维监控告警。

---

## 需求规格（Requirements）

### R-1 单一内核：统一 `ApprovalKernel` 类

新建 `services/chat-api/app/governance/approval_kernel.py`，封装三种来源共用的一套状态机：

```python
class ApprovalState(Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    REASSIGNED = "reassigned"  # 改派后的中间态，仍需新审批人决策

class ApprovalSource(str, Enum):
    TOOL = "tool"          # admin-api app/governance/layers/approval.py 原有路径
    PORTAL = "portal"      # 037 portal_requests 路径
    SOP = "sop"            # 050 human_approval 节点路径
```

核心方法：

```python
class ApprovalKernel:
    """Unified approval state machine, backed by MongoDB or pg_compat."""

    async def issue(
        self,
        *,
        source: ApprovalSource,
        source_id: str,
        tenant_id: str,
        actor_id: str,           # 发起人 ID
        approver_id: str,        # 审批人 ID（支持 user_id 或 role_id）
        deadline: datetime,
        ttl_seconds: int = 300,  # 票据 TTL（与 ApprovalRuntime 对齐）
    ) -> ApprovalTicket:
        """签发待办，返回 ticket（含一次性 token）。"""

    async def decide(
        self,
        *,
        source: ApprovalSource,
        source_id: str,
        token: str,
        actor_id: str,           # 审批人 ID（须匹配 approver_id，校验见 R-5）
        approved: bool,
        reason: str = "",
    ) -> ApprovalOutcome:
        """审批人决策（approve/deny），原子地推进状态并回调业务侧。"""

    async def cancel(
        self,
        *,
        source: ApprovalSource,
        source_id: str,
        actor_id: str,
        reason: str = "",
    ) -> ApprovalOutcome:
        """取消待办，带 revision 前置条件防止 TOCTOU。"""

    async def reassign(
        self,
        *,
        source: AnnotationSource,
        source_id: str,
        new_approver_id: str,
        actor_id: str,
        reason: str = "",
    ) -> ApprovalOutcome:
        """改派：更新 approver_id + 重置 deadline + 重签 resume_token。"""

    async def list_todos(
        self,
        *,
        tenant_id: str,
        approver_id: str,
        status: Literal["pending", "all"] = "pending",
    ) -> list[ApprovalTodo]:
        """查询审批人待办列表（统一视图）。"""

    async def resolve_timeout(self, *, source_id: str) -> None:
        """定时器调用的超时处置（fail-closed：悬而未决一律视为过期）。"""
```

**约束**：
- `issue`/`decide`/`cancel`/`reassign` 全部走 `update_one` + `{"revision": expected_revision}` 前置条件，失败抛 `ApprovalConflictError`，由调用方处理重试或幂等返回
- 每个 method 完成后**必须**写一条 `gate_events` 审计事件（R-7）
- 禁用旧 `ApprovalRegistry`（`admin-api/app/governance/layers/approval.py`）的 `validate_and_consume` 入口（`:173-180`），保留 `approve`/`consume` 两阶段语义不变但迁移至 Kernel

---

### R-2 revision 原子条件更新仲裁（解决 P1-2）

所有状态转换操作必须满足：
- **取消与决策竞态**：`cancel()` 的 filter 加 `{"status": "awaiting_approval"}`；`decide()` 的 filter 加 `{"status": "pending"}`；两者互斥，先落库者胜
- **撤销分支优先级**：任一并行审批节点被驳回 → 整个运行立即进入终态，其余 pending 节点强制 expire（不调 `decide`，直接 `$unset` 并写 `approval.timeout.expire` 事件）
- **超时与批准竞态**：恢复扫描判定时，对候选运行执行 `find_one_and_update({"run_id": id, "status": "awaiting_approval"}, {"$set": {"status": "timeout"}}, return_document=True)`——若找得到则超时生效，找不到则已被其他路径消费，忽略

---

### R-3 审批人解析统一（解决 P1-4 前半）

新增 `resolve_approver(actor_id: str, tenant_id: str) -> str` 函数，支持两种形态：
- **用户型**：`actor_id` 字面等于 `approver_id`（现有行为，`human_approval.py:343`）
- **角色型**：`approver_id` 为 role ID，查 `position_roles` 表得成员列表，轮询或随机选一名 active 成员作为实际决策者

**约束**：角色型暂列为 clarify 项（需确认是否有真实业务场景），首期仅实现用户型；role_id 传值时记录 warning 事件但不阻塞。

---

### R-4 改派出口补齐（解决 P1-4 后半）

`reassign()` 方法必须同步完成以下动作（缺一不可）：
1. `$set pending_approvals.{node_id}.approver = new_approver_id`
2. `$set pending_approvals.{node_id}.deadline = utcnow() + node.timeout`
3. `$inc revision 1`
4. 删除旧的 `resume_token`（或标记 expired），生成新的
5. 写 `approval.reassigned` 审计事件
6. 回调 `on_reassign` hook（若有声明）

`resolve_review` API 端点（`orchestration_runs.py:278,301`）增加 `reassign` 选项：
```python
# 现有：if review_action not in ("skip", "terminate"): raise 400
# 修改为：if review_action in ("skip", "terminate", "reassign"): handle accordingly
```

---

### R-5 身份一致性校验（解决 P1-1 身份双口径）

`ApprovalKernel.decide()` 必须校验 `actor_id == approver_id`，否则返回 `403 Forbidden`，原因码 `approval.actor_mismatch`。
- 对 `portal` 来源，沿用既有 `approver_id` 字段校验
- 对 `tool` 来源，沿用 admin-api 侧的审批人权限校验（通过 position_roles RBAC）
- 对 `sop` 来源，沿用当前 `human_approval.py:343` 的字面等值校验

---

### R-6 审计事件命名规范

所有 `gate_events` 写入的动作遵循命名模式：
```
approval.{source_type}.{action}
```
其中 `{action}` ∈ {`issued`, `decided`, `denied`, `cancelled`, `reassigned`, `timeout`, `expire_branch`}
`{source_type}` ∈ {`tool`, `portal`, `sop`}

`detail` 字段必须包含：`source_id`、`run_id`（若有）、`node_id`（若有）、`previous_state`、`new_state`、`actor_id`。

---

### R-7 下线兼容层

- `services/admin-api/app/governance/layers/approval.py:ApprovalRegistry` → 废弃，所有调用方迁移至 `ApprovalKernel`
- `services/chat-api/app/orchestration/human_approval.py:human_decide()` → 内部改为调 `ApprovalKernel.decide(source=SOP, ...)`
- `services/chat-api/app/services/portal/requests.py:PortalRequestService.approve()` → 内部改为调 `ApprovalKernel.decide(source=PORTAL, ...)`
- `services/chat-api/app/orchestration/run_store.py:cancel()`、`record_decision()`、`set_status()` 的内部逻辑下沉至 `ApprovalKernel`

---

## 边界与假设（Edge Cases & Assumptions）

- **E1 角色型审批人**：暂不支持（spec clarify 项），输入 role_id 时打印 warning 并 fallback 为 `approval.actor_mismatch`
- **E2 超长历史数据迁移**：既有 `gate_approvals` / `portal_requests` 表中存量记录不做热迁移；新内核从上线后首个请求开始接管，存量记录的查询走兼容视图（read-through proxy）
- **E3 多租户并发**：Kernel 的所有写操作均携带 `tenant_id` 前置条件，跨租户不可能误操作
- **E4 双后端**：Kernel 基于 `app.core.db.get_db()` 抽象，Mongo 与 PanWeiDB 均透明支持，不动 pg_compat 层
- **A1 不影响既有 001 gate 层**：Kernel 是审批状态机的替换，不改变 gate 层的六层串行结构（identity→RBAC→redact→approval→quota→audit）
- **A2 不影响 052 team 模式**：052 的「跨模式挂起」是二期任务（复审 P0-2 后明确），本次范围仅限于 graph 模式内的审批内核统一

## Clarify Decisions（待用户在 implement 前拍板）

| # | 决策点 | 建议默认值 | 阻塞 implement？ |
|---|---|---|---|
| D1 | 存量 `gate_approvals`/`portal_requests` 数据是否迁移 | 不迁移，上线后读兼容视图 | 否（E2） |
| D2 | 改派时 `resume_token` 是否需要通知原审批人 | 需要，发一条 `approval.reassigned.notify` IM 消息 | 否 |
| D3 | `resolve_review` 端点的 HTTP method | POST（与既有 skip/terminate 一致） | 否 |

---

## 验收标准（Acceptance Criteria）

- [ ] 三类来源（tool/portal/sop）的所有审批操作均可通过 `ApprovalKernel` 的同一个 API 完成
- [ ] `cancel()` 与 `decide()` 并发测试：100 次并发下，0 次出现「双重生效」或「状态回退」
- [ ] `list_todos()` 返回的所有待办均由 `source_type` 标注来源，前端可筛选
- [ ] 所有审批操作均产生一条 `gate_events` 审计事件，且事件前缀可正确区分来源
- [ ] 旧 `ApprovalRegistry.validate_and_consume` 路径 0 生产引用（grep 验证）
- [ ] `services/chat-api/tests/test_approval_kernel.py` 单测覆盖率 ≥ 90%
- [ ] `tests/orchestration/` 全量回归通过，无新增 failure

---

## 风险与回滚

- **Risky**：涉及三个服务的调用方接口变更，需逐一核查所有 `ApprovalRegistry` / `human_approval` / `portal_requests.approve` 的生产调用点
- **Backout**：Kernel 为新增模块，旧代码保留至下一个版本再删；期间可通过环境变量 `APPROVAL_KERNEL_ENABLED=false` 切换回旧路径
- **影响范围**：只改动 `services/chat-api/app/governance/` 与 `services/admin-api/app/governance/layers/` 下的核心文件，API 契约（`contracts/`）保持不变（只增不改），故对下游消费者透明
