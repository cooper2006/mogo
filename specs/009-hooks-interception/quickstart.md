# Quickstart: Hooks Interception (009)

**Feature**: [spec.md](./spec.md) | [plan.md](./plan.md) | [contracts/hooks.md](./contracts/hooks.md)

本文件说明如何**启用并验证**五事件钩子。

---

## 1. 前置

- chat-api 服务
- **首期仅 PreToolUse**（其余事件按节奏启用）

---

## 2. 引擎使用

```python
from app.dsh_runtime.hooks import HookEngine, HookRegistry

registry = HookRegistry()          # 默认仅启用 PreToolUse
registry.enable("SessionStart")    # 按需启用其余事件

engine = HookEngine()
outcome = engine.evaluate_pre_tool_use(
    tool="crm",
    request={"customer_id": "c-1"},
    raw_rules=[
        {"scope": "tool", "rule_type": "require_field",
         "rule_config": {"fields": ["customer_id"]}},
        {"scope": "tenant", "rule_type": "observe",
         "rule_config": {"note": "audit trail"}},
    ],
)
if not outcome.allowed:
    # outcome.status_code == 403, outcome.reason 含规则原因
    ...
```

---

## 3. 挂载点

PreToolUse 挂载到 `dsh_runtime/turn_admission.admit_skill_selection`（工具调用前求值）。超时用 `run_with_timeout(op, timeout_seconds=5)`。

集成模块（009 T009-T018）：

```python
from app.dsh_runtime.hooks.integration import mount_into_turn_admission, audit_hook_execution
from app.dsh_runtime.hooks.lifecycle import emit_session_start, emit_post_tool_use, emit_session_end, emit_memory_commit
from app.dsh_runtime.hooks.store import HookRuleStore
from app.dsh_runtime.hooks.guard import evaluate_with_fail_closed, run_hooks_within_budget, HookLatencyBudget

# T009 挂载：拒绝的 outcome 永不进入真实 admission 逻辑
outcome = mount_into_turn_admission(admit_skill_selection, "web", {"x": 1}, raw_rules=[...])

# T011 钩子执行 100% 进 001 审计落点
entry = await audit_hook_execution(outcome, tenant_id="t1", user_id="u1", tool="web")

# T013 其余四事件（联动 002 会话事件）
registry.enable("SessionStart"); emit_session_start(registry, session_id="s1", actor="alice")

# T015-T016 管理端 CRUD + 三级作用域（tool > session > tenant）
store = HookRuleStore(db=None)
store.create(scope="tool", rule_type="deny_tool", rule_config={"tool": "web"}, tenant_id="t1")
ordered = store.ordered_rules_for(tool="web", session_id="s1", tenant_id="t1")

# T017-T018 fail_closed 自检 + 延迟预算（≤5s 共享，超限 fail_closed）
assert evaluate_with_fail_closed("web", {}, raw_rules=[{"scope": "tool", "rule_type": "nope"}]).failed_closed
assert run_hooks_within_budget("web", {}, budget=HookLatencyBudget(budget_seconds=5.0)).allowed
```

管理端点（admin-api `/api/hooks`，009 T015）：`GET/POST /rules`、`GET/PATCH/DELETE /rules/{id}`、`GET /scope?tool=&session_id=`。

---

## 4. 验证清单

| # | 验证项 | 期望 |
|---|---|---|
| 1 | deny_tool 命中 | 拒绝（403，与门禁拒绝区分） |
| 2 | deny_tool 非目标工具 | 放行 |
| 3 | require_field 缺字段 | 拒绝（提示缺失字段） |
| 4 | observe | 记录但不拦截 |
| 5 | deny 短路优先 | deny 先于 require 生效 |
| 6 | 规则解析失败 | fail_closed（未知 scope/type/缺字段均拒） |
| 7 | 超时 | `HookTimeout`（fail_closed） |
| 8 | PreToolUse 不可禁用 | `RegistryError` |

---

## 5. 单元测试（无需 DB/运行时）

```bash
cd services/chat-api
PYTHONPATH=. python -m pytest tests/dsh_runtime/test_hooks.py -o asyncio_mode=auto -q
```

期望：**26 项全部通过**（规则解析、排序、三类规则、短路、fail_closed、超时、注册表）。

---

## 6. 说明

- 超时默认 5s，复用 `execution_timeout.ExecutionTimeoutPolicy` 模式
- fail_closed **不可配置放行**（constitution 原则 III）
- 钩子审计复用 001 落点，不另建集合
