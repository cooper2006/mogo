"""CPU hotspot profile for the tenant-scoping critical path (QF-329).

Pure-function path, fully offline. Run:

    python -m pytest tests/benchmarks/bench_cpu_profile.py -s \
        -p no:cacheprovider -o addopts=""

It prints the top functions by cumulative CPU time so a single hot function
exceeding 30% can be justified or optimized. No LLM/IO/Redis dependency.
"""
import cProfile, pstats, io
from app.core.tenant import add_tenant_scope, tenant_scope_filter, resolve_tenant_id


def test_profile_tenant_scope_path():
    def workload():
        for _ in range(20000):
            add_tenant_scope({"session_id": "s", "user_id": "u"}, "org_1")
            tenant_scope_filter("org_1")
            resolve_tenant_id("org_1")

    prof = cProfile.Profile()
    prof.enable()
    workload()
    prof.disable()
    buf = io.StringIO()
    ps = pstats.Stats(prof, stream=buf).sort_stats("cumulative")
    ps.print_stats(12)
    out = buf.getvalue()
    # Surface the top hot frame's own-time share for the audit evidence.
    lines = [ln for ln in out.splitlines() if "tenant.py" in ln]
    print("\n=== tenant.py hot frames (cumulative) ===")
    for ln in lines[:6]:
        print(ln.strip())
    assert any("add_tenant_scope" in ln or "tenant_scope_filter" in ln for ln in lines), \
        "expected tenant-scope functions present in profile"
