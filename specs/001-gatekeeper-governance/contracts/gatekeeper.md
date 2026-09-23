# Contract: Unified Six-Layer Gatekeeper (001)

**Feature**: [spec.md](../spec.md) | [plan.md](../plan.md) | [tasks.md](../tasks.md)

本契约定义 001 六层门禁的**对外接口**：调用输入、逐层判定输出、短路语义、HTTP 状态码映射、以及 25 格自主矩阵。实现见 `services/admin-api/app/governance/`。

---

## 1. 门禁链（Layer Chain）

固定顺序（声明式配置可增删层，但必需层不可禁用）：

| # | 层名 | 职责 | 可省（薄模式） |
|---|---|---|---|
| 1 | `identity` | 解析调用主体（租户/用户/岗位角色） | ✗ 必需 |
| 2 | `rbac` | 权限码判定（`<resource>:<action>[:<target>]`），fail-closed | ✗ 必需 |
| 3 | `redaction` | PII 脱敏（mask/remove/hash/abstract） | ✗ 必需 |
| 4 | `approval` | 高风险 × 高自主级别 → 人工审批 | ✓ 可省 |
| 5 | `quota` | 三维配额（租户/用户/工具），MongoDB 计数 | ✓ 可省 |
| 6 | `audit` | 通过/拒绝事件落 `gate_events` | ✗ 必需 |

**短路**：任一层返回非 `allow` 即短路，后续层不执行，拒绝原因落审计（FR-1）。
**审计必落**：无论通过或拒绝，`audit` 层都执行并落库（FR-9）。

---

## 2. 输入契约（GateContext）

```python
@dataclass
class GateContext:
    tool: str                      # 工具标识（必填）
    tenant_id: str = ""            # 租户（identity 层强校验）
    user_id: str = ""              # 用户
    roles: list[str] = []          # 岗位角色 id 列表（rbac 层展开为权限码）
    risk_level: Optional[str]      # R0..R4
    autonomy_level: Optional[str]  # L1..L5
    request: dict                  # 工具请求体（redaction/quota 使用）
    response: dict = {}            # 工具响应体（redaction 使用）
    scope: str = "tool"            # tool | session | tenant
    session_id: str = ""
```

---

## 3. 输出契约（GateVerdict）

```python
@dataclass
class GateVerdict:
    decision: GateDecision         # allow | deny | require_approval
    layer: str                     # 判定发生的层名
    reason: str = ""               # 拒绝原因（人类可读）
    detail: dict = {}              # 结构化细节（required/granted/approval_token…）

    allowed: bool                  # decision is allow
    status_code: int               # HTTP 状态码（见 §4）
```

---

## 4. HTTP 状态码映射（FR-1）

| 层 | 场景 | 状态码 | 响应体 |
|---|---|---|---|
| `identity` | 主体不可解析 | 403 | `{"layer":"identity","reason":"..."}` |
| `rbac` | 权限码不满足 | 403 | `{"layer":"rbac","reason":"...","required":"<code>"}` |
| `redaction` | 脱敏失败 | 403 | `{"layer":"redaction","reason":"..."}` |
| `approval` | 需人工审批 | 409 | `{"layer":"approval","reason":"...","approval_token":"<token>"}` |
| `quota` | 配额超限 | 429 | `{"layer":"quota","reason":"...","dimension":"tenant|user|tool"}` |
| `audit` | 审计落库失败 | 500 | `{"layer":"audit","reason":"审计落库失败（fail-closed）"}` |

`approval` 挂起默认 **5 分钟超时**，超时后按 fail-closed 拒绝（FR-11）。

---

## 5. 权限码模型（FR-5）

格式：`<resource>:<action>[:<target>]`

- 资源通配：`knowledge:*` 授予该资源任意 action
- 全局通配：`*`（全能力管理员）授予一切
- 无 target 的码可匹配带 target 的请求；target 不匹配则拒绝
- **未知/拼写错误的码一律不匹配（fail-closed）**

岗位角色 → 权限码预设组（对接 006）：

| 粗粒度能力（006 `capabilities`） | 映射权限码 |
|---|---|
| `content_generation` | `content:generate` |
| `image_generation` | `image:generate` |
| `code_generation` | `code:execute` |
| `browser_automation` | `browser:automate` |
| `internal_knowledge` | `knowledge:read` |

`system_key = full_access_admin` 的角色展开为 `{"*"}`。

---

## 6. 25 格 AUTONOMY_MATRIX（L1–L5 × R0–R4）

行 = 自主级别 L（L1 最低 → L5 最高），列 = 风险级 R（R0 最低 → R4 红线）：

| L \ R | R0 | R1 | R2 | R3 | R4 |
|---|---|---|---|---|---|
| **L1** | allow | allow | allow | require_approval | deny |
| **L2** | allow | allow | allow | require_approval | deny |
| **L3** | allow | allow | require_approval | require_approval | deny |
| **L4** | allow | allow | require_approval | require_approval | deny |
| **L5** | allow | allow | allow | require_approval | deny |

**不变量**：R4 任意 L = `deny`（红线，全能力管理员亦不可覆盖，FR-4）；R0/R1 任意 L = `allow`。

---

## 7. 审计事件（gate_events）

```json
{
  "event_id": "<uuid>",
  "occurred_at": "<ISO8601 UTC>",
  "tenant_id": "t1", "user_id": "u1", "roles": ["role-1"],
  "tool": "crm", "risk_level": "R3", "autonomy_level": "L4",
  "decision": "deny", "layer": "rbac",
  "reason": "权限码不满足：需要 crm:execute",
  "detail": {"required": "crm:execute", "granted": ["knowledge:read"]}
}
```

---

## 8. 声明式配置（gatekeeper_rules / kind=gate_config）

```json
{
  "kind": "gate_config",
  "enabled_layers": ["identity","rbac","redaction","approval","quota","audit"],
  "audit_enabled": true,
  "mode": "thick",
  "tenant_overrides": {}
}
```

**守护**：`enabled_layers` 缺少 `identity`/`rbac`/`redaction`/`audit` 或 `audit_enabled=false` → `GateConfigError`（拒绝加载，回退厚模式）。
