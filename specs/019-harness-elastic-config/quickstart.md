# 019 Harness Elastic Config — Quickstart

## Modules (chat-api `app/harness_config/`)

| Module | Concern |
| --- | --- |
| `profile.py` | `HarnessProfile` + `ProfileResolver`（tenant > scene > global 覆盖链） |
| `layer_switch.py` | 层开关（identity/rbac/redaction/approval/quota/audit 的启用组合） |
| `floor.py` | 合规底线（R4 红线等不可被 profile 下探） |
| `gate_adapter.py` | 把 profile 解析结果接进 001 gatekeeper |

## 1. 解析 profile（三层覆盖）

```python
from app.harness_config.profile import HarnessProfile, ProfileResolver

resolver = ProfileResolver()
resolver.add(HarnessProfile(scope="tenant:t1", layers=["identity","rbac"], audit_granularity="fine"))
layers = resolver.effective_layers(scene="chat", tenant="t1", tool="web")
```

## 2. 层开关 + 合规底线

```python
from app.harness_config.floor import assert_floor_intact, r4_always_denied

# profile 不能关 R4 红线（floor 兜底）
assert r4_always_denied(mode="thin") is True
# 层解析后过 floor 校验，违反则 FloorViolation
assert_floor_intact(layers, audit_granularity="fine")
```

## T015 契约文档

见 `contracts/harness-config.md`：profile schema + 层开关契约 + 合规底线不变量。

## T999 审计接入

profile 变更 / 层开关切换事件复用 001 审计落点（`gate_events`），与
001 T030 配置变更审计同源。
