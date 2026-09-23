# 016 Skill Market Hardening — Quickstart

## Modules (chat-api `app/services/`)

| Module | Concern |
| --- | --- |
| `skill_lifecycle/service.py` | Skill lifecycle (install / upgrade / rollback / deprecate) |
| `skillhub/service.py` | SkillHub download / install |
| `skill_packages/validator.py` | Package validation |
| `dream_cycle/deprecation.py` | 低采纳检测 + `marked_low_quality` 共用位（011 T014） |

## 打分 / 回滚 / 标记（US2）

```python
from app.services.dream_cycle.deprecation import AdoptionStore, deprecation_flow

store = AdoptionStore()
for _ in range(30):
    store.record_exposure("skill-x", "t1")
record = deprecation_flow("skill-x", "t1", store)
# record["marked_low_quality"] 与 011 共用同一位
```

## T999 审计接入

`skill.quality.marked` / `skill.quality.restored` 事件经
`app/services/feature_audit.py::record_feature_event("016", ...)` 进 001
审计落点。
