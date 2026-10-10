"""Step-load throughput knee for the tenant-scoping path (QF-316).

Thread-pool concurrency ladder 10/50/100/200 hitting the pure add_tenant_scope
path (no IO/LLM). Reports throughput (ops/s) per step so the saturation knee
can be identified offline. Uses threads (not asyncio) to avoid event-loop
conflicts under pytest asyncio auto-mode. Run:

    python -m pytest tests/benchmarks/bench_scale_step.py -s \
        -p no:cacheprovider -o addopts=""
"""
import concurrent.futures as cf
import time
from app.core.tenant import add_tenant_scope


def _worker(per_worker):
    for _ in range(per_worker):
        add_tenant_scope({"session_id": "s", "user_id": "u"}, "org_1")


def _ladder(concurrency, per_worker=5000):
    t0 = time.perf_counter()
    with cf.ThreadPoolExecutor(max_workers=concurrency) as ex:
        list(ex.map(_worker, [per_worker] * concurrency))
    elapsed = time.perf_counter() - t0
    total = concurrency * per_worker
    return total / elapsed, elapsed


def test_step_load_knee():
    steps = [10, 50, 100, 200]
    prev = None
    print("\n=== step-load knee (pure tenant-scope path) ===")
    for c in steps:
        tps, el = _ladder(c)
        print(f"  concurrency={c:4d}  throughput={tps:,.0f} ops/s  elapsed={el:.2f}s")
        if prev is not None:
            print(f"            -> throughput growth x{tps / prev:.2f}")
        prev = tps
    assert True
