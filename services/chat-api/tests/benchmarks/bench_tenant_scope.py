"""Performance baselines for tenant-scoping critical paths (QF-298/299/300).

These are pure functions with no IO/LLM dependency, so they run fully offline
and produce reproducible P50/P95/P99 numbers. Run with:

    pytest tests/benchmarks/test_bench_tenant_scope.py --benchmark-only \
        --benchmark-json=.qualityforge/bench_tenant_scope.json

Measurement window: 100 rounds (default pytest-benchmark), warmup 5. The
report records rounds/warmup/concurrency(=1, single-call latency) so the same
version can be re-measured independently.
"""
from app.core.tenant import add_tenant_scope, tenant_scope_filter, resolve_tenant_id


def test_bench_add_tenant_scope_default(benchmark):
    benchmark(add_tenant_scope, {}, None)


def test_bench_add_tenant_scope_named(benchmark):
    benchmark(add_tenant_scope, {"session_id": "x", "user_id": "u1"}, "org_1")


def test_bench_tenant_scope_filter_default(benchmark):
    benchmark(tenant_scope_filter, None)


def test_bench_tenant_scope_filter_named(benchmark):
    benchmark(tenant_scope_filter, "org_1")


def test_bench_resolve_tenant_id(benchmark):
    benchmark(resolve_tenant_id, "org_1")
