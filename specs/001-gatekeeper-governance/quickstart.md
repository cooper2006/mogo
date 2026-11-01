# Quickstart: Unified Six-Layer Gatekeeper (001)

**Feature**: [spec.md](./spec.md) | [plan.md](./plan.md) | [contracts/gatekeeper.md](./contracts/gatekeeper.md)

本文件说明如何**启用并验证**六层门禁。

---

## 1. 前置

- admin-api 服务（`services/admin-api`）已部署
- MongoDB 可用（门禁表落 MongoDB，不引入 Redis）
- Python 3.10+（仓库 `motor==2.5.1` 与 3.11+ 不兼容）

---

## 2. 初始化门禁表

首次启动时调用一次（由 `tools.py::ensure_indexes` 自动挂接）：

```python
from app.governance.schema import ensure_indexes
await ensure_indexes()
```

会创建：`gatekeeper_rules`、`risk_tiers`、`autonomy_matrix`、`pii_policies`、`quota_counters`、`gate_events`，并**种子**默认门禁配置（厚模式）、25 格矩阵、默认 PII 策略。

---

## 3. 门禁入口

工具调用入口（`POST /api/tools/{tool_id}/test`、`POST /api/tools/test-draft`）在执行前自动过门禁：

```python
from app.governance import GateContext, gatekeeper

ctx = GateContext(
    tool="crm",
    tenant_id="t1",
    user_id="u1",
    roles=["role-sales"],          # 岗位角色 id（006），展开为权限码
    risk_level="R2",
    autonomy_level="L3",
    request={"q": "..."},
)
verdict = await gatekeeper.evaluate("crm", ctx)
if not verdict.allowed:
    # verdict.status_code ∈ {403, 409, 429, 500}
    ...
```

---

## 4. 验证清单

| # | 验证项 | 期望 |
|---|---|---|
| 1 | 无权限用户调工具 | 第 2 层拒绝（403，审计记 RBAC 拒绝） |
| 2 | 全能力管理员调工具 | 六层全过（allow，审计记通过） |
| 3 | **中途拒绝的审计** | RBAC 拒绝时 `gate_events` 仍有记录（审计不丢） |
| 4 | L5 × R4 | deny（红线不可覆盖） |
| 5 | L3 × R2 | require_approval（409 + approval_token） |
| 6 | 配额超限 | 429（返回超限维度） |
| 7 | 禁用必需层配置 | `GateConfigError`（配置被拒绝） |

---

## 5. 单元测试（无需 DB）

```bash
cd services/admin-api
PYTHONPATH=. python -m pytest \
  tests/test_governance_rbac_model.py \
  tests/test_governance_config.py \
  tests/test_governance_gatekeeper.py \
  -o asyncio_mode=auto -q
```

期望：**28 项全部通过**（权限码解析/通配/未知码 fail-closed、配置必需层守护、六层链短路与中途拒绝审计）。

> `tests/conftest.py` 仅当 `motor` 不可用时注入 stub，使纯逻辑测试可在任意解释器运行。

---

## 6. 说明

- 审批层（第 4 层）复用既有 `chat-api/enterprise_capabilities/tools/approval_runtime`，**不新建审批表**；恢复走 poll，默认 5 分钟超时。
- 配额用 MongoDB 原子计数（`quota_counters`），**不引入 Redis**。
- PII 全局默认策略 + 租户可覆盖（`pii_policies`）。
