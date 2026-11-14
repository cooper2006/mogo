# Contract: Hooks Interception (009)

**Feature**: [spec.md](../spec.md) | [plan.md](../plan.md) | [tasks.md](../tasks.md)

本契约定义五事件钩子的规则 schema、求值语义、超时与 fail_closed 底线。实现见 `services/chat-api/app/dsh_runtime/hooks/`。

---

## 1. 五事件

| 事件 | 首期启用 | 说明 |
|---|---|---|
| `SessionStart` | ✗ | 会话开始（可注入初始上下文） |
| `PreToolUse` | **✓** | 工具调用前（声明式拦截） |
| `PostToolUse` | ✗ | 工具调用后（成功/失败均执行） |
| `SessionEnd` | ✗ | 会话结束（可清理临时态） |
| `MemoryCommit` | ✗ | 记忆提交（可过滤待提交记忆） |

**首期仅 PreToolUse**（clarify OQ-3）；其余注册为目标态，后续按节奏启用（`HookRegistry.enable`）。
**PreToolUse 不可禁用**（合规拦截点）。

---

## 2. 规则 schema（hook_rules）

```json
{
  "scope": "tool",                    // tool | session | tenant
  "rule_type": "deny_tool",           // deny_tool | require_field | observe
  "rule_config": {"tool": "rm"},      // 规则参数
  "enabled": true
}
```

### 规则类型语义

| `rule_type` | 语义 | 可否拦截 |
|---|---|---|
| `deny_tool` | 拒绝指定工具调用（`rule_config.tool`，空/`*` = 全部） | ✓ |
| `require_field` | 请求缺必填字段则拒绝（`rule_config.fields`） | ✓ |
| `observe` | **仅记录，不改拦截结果** | ✗ |

---

## 3. 求值顺序（FR-9）

1. **按作用域**：`tool`(3) > `session`(2) > `tenant`(1)
2. **按类型**：`deny`(3) > `require`(2) > `observe`(1)
3. **deny 命中即短路**返回，不再求值后续规则

---

## 4. 超时与 fail_closed（FR-3 / FR-11）

| 项 | 值 |
|---|---|
| 默认超时 | **5s**（`hook_timeout_seconds` 可配） |
| 超时/异常 | **fail_closed 拒绝**（不可配放行） |
| 规则解析失败 | **fail_closed**（三类：JSON 非法 / 必填字段缺失 / 未知 rule_type） |
| 延迟预算 | 单次工具调用的钩子**总延迟 ≤ 5s**（多钩子共享预算，超限 fail_closed，FR-13） |

---

## 5. 输出契约（HookOutcome）

```python
@dataclass
class HookOutcome:
    allowed: bool
    reason: str = ""
    rule_type: str = ""
    scope: str = ""
    observations: list[dict] = []    # observe 规则的记录
    failed_closed: bool = False

    status_code: int                 # 403（拒绝）/ 200（通过）
```

**拒绝提示**：403 + "被钩子规则拒绝"（**与门禁拒绝区分**：门禁拒绝提示权限/配额原因，钩子拒绝提示规则原因）。

---

## 6. 审计契约

钩子执行事件进 **001 的审计落点**（不另建集合），含：身份/工具/结果（通过/拒绝）/时间戳 + 规则命中详情。

---

## 7. 与 019 的关系

019 薄模式可跳过**非红线钩子**（observe / 非 R4 的 require）；**fail_closed 底线保留**（钩子故障仍 fail_closed）。
