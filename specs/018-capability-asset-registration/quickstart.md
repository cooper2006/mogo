# 018 Capability Asset Registration — Quickstart

## Module (chat-api `app/services/capability_assets.py`)

契约四段 + 版本 + owner 的资产注册；扫描去重（端点+方法）；
治理视图（列表 + 详情下钻）；状态管理（active/deprecated/offline + 审批）；
`a2a_exposed` 标记（供 012 生成 AgentCard）。

## 1. 发现 + 注册 + 去重（US1）

```python
from app.services.capability_assets import CapabilityAssetRegistry

registry = CapabilityAssetRegistry()
result = registry.discover_and_register([
    {"key": "tool.x", "endpoint": "/x", "method": "GET", "owner": "team"},
    {"key": "tool.x", "endpoint": "/x", "method": "GET", "owner": "team"},  # dup -> dedup
])
# {"registered": ["tool.x"], "duplicates": ["tool.x"]}
```

## 2. 治理视图 + 状态 + 标记（US2）

```python
registry.governance_view()                    # 列表（status/asset_type/owner）
registry.governance_detail("tool.x")          # 详情下钻
registry.set_status("tool.x", "deprecated", reason="superseded")
registry.set_status("tool.x", "offline", approver="admin", require_approval=True)
registry.mark_a2a_exposed("tool.x", exposed=True)   # 供 012 生成 AgentCard
```

## T999 审计接入

`asset.registered` / `asset.status.changed` / `asset.a2a.marked` 事件经
`app/services/feature_audit.py::record_feature_event("018", ...)` 进 001
审计落点。
