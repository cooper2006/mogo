# 011 Self-Evolution / Dream Cycle — Quickstart

## Modules (chat-api `app/services/dream_cycle/`)

| Module | Concern |
| --- | --- |
| `runner.py` | Dream pipeline: rank → validate → apply (dry-run / shadow) → report |
| `friction.py` | Friction capture (retry / fallback / timeout) + experience store |
| `mr.py` | High-confidence improvement MR vs draft boundary |
| `deprecation.py` | Low-adoption detection + deprecation + manual restore |
| `evolution_audit.py` | Full-chain audit + configurable thresholds (T017/T018) |
| `runtime.py` | **Production entry**（T007）: periodic scan + wiring the five `audit_*` into 001 |

## 1. Run a dream cycle

```python
from app.services.dream_cycle.runner import run_dream_cycle

result = run_dream_cycle(
    signals=[{"key": "sig-a", "score": 0.9}],
    dry_run=True,
    top_n=10,
)
```

## 2. Capture friction

```python
from app.services.dream_cycle.friction import extract_friction_from_signals, FrictionStore

store = FrictionStore()
fragments = extract_friction_from_signals(
    [{"key": "call-1", "tool": "web", "retries": 2, "outcome": "ok"}],
    store=store,
)
```

## 3. Improvement MR

```python
from app.services.dream_cycle.mr import build_candidate, generate_improvement_mr

candidate = build_candidate({"key": "improve-x", "jaccard": 0.8, "samples": 6})
mr = generate_improvement_mr(candidate)  # None when not high-confidence
```

## 4. Low-adoption deprecation

```python
from app.services.dream_cycle.deprecation import AdoptionStore, deprecation_flow

store = AdoptionStore()
for _ in range(25):
    store.record_exposure("skill-a", "t1")
record = deprecation_flow("skill-a", "t1", store)  # -> deprecated
store.restore("skill-a")  # manual restore
```

## 5. Configurable thresholds (T018)

```python
from app.services.dream_cycle.evolution_audit import EvolutionConfig

cfg = EvolutionConfig(
    scan_interval_hours=12,
    jaccard_threshold=0.7,
    min_samples=5,
    low_adoption_window_days=14,
    low_adoption_min_exposure=20,
    low_adoption_rate=0.10,
    shadow_ratio=0.1,
)
cfg.confidence_gate(0.8, 6)  # True
```

## 6. Periodic scan in production (T007)

```python
from app.services.dream_cycle import runtime

await runtime.ensure_indexes(db)           # kernel_event_projections index
await runtime.dream_cycle_scanner.start()  # 24h loop, mounted in app/main.py lifespan
...
await runtime.dream_cycle_scanner.stop()
```

`runtime.run_once()` 从 `kernel_event_projections` 里**已落库**的工具事件
（`item.failed` / `item.completed`）派生摩擦信号，按租户扫描并生成草稿，
同时对 capture / generate / mr / deprecate / restore 逐个写 001 审计
（`position_role_audit_logs`）。它**不改动** DSH turn 热路径 —— 采集发生在 turn 之后。

注意：模式聚类默认叠加**动作序列编辑相似度**作为次级门槛
（`DEFAULT_ACTION_SIMILARITY_THRESHOLD = 0.5`，可由
`ScanConfig.action_similarity_threshold = None` 关闭），详见 `contracts/self-evolution.md`。
