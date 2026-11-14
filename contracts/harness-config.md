# Harness Elastic Config Contract (019)

> 019-harness-elastic-config — profile schema + 层开关契约。
> 本文件定义 chat-api `app/harness_config/` 的对外接口与不变量。

## Profile schema

```jsonc
{
  "scope": "tenant:t1",      // global | scene:<s> | tenant:<t> | tool:<x>
  "layers": ["identity", "rbac", "redaction", "approval", "quota", "audit"],
  "audit_granularity": "fine",   // fine | coarse | off (off 受 floor 约束)
  "mode": "thick"               // thick | thin
}
```

- 覆盖链：**tenant > scene > global**（更具体的 scope 覆盖更宽泛的）。
- `ProfileResolver.resolve(scope, key)` 沿覆盖链取第一个命中。
- `effective_layers(scene, tenant, tool)` 返回最终生效的层集合。

## 层开关契约

`resolve_layers(mode, enabled?)` 决定启用哪些门禁层。
- thin 模式默认裁剪非合规层，但**合规底线层不可关**。
- 每次层组合变更都必须过 `assert_floor_intact(layers, audit_granularity)`，
  违反抛 `FloorViolation`。

## 合规底线不变量（floor）

- **R4 红线恒 deny**（`r4_always_denied(mode)` 对任何 mode 都返回 True）。
- 审计粒度不能关到低于 floor 要求；`minimal_audit_record` 给出最小可接受
  审计字段，`audit_covers_floor` 校验。
- profile 只能**收紧**合规底线，不能**放宽**（放宽必须走 001 配置变更审计）。

## 与 001 联动

`gate_adapter.py` 把解析后的 profile 接进 001 gatekeeper；profile 变更 /
层开关切换事件复用 001 审计落点（`gate_events`），与 001 T030 同源。
