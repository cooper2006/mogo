"""026 T047 — 搜索场景压测（FR-31）。

用法（并发级别 1/10/50/100）::

    TARGET_HOST=http://localhost:8001 locust -f benchmarks/locust/locustfile_search.py \
        -u 50 -r 5 --host http://localhost:8001 --headless --run-time 60s

搜索场景覆盖 document-parser 的向量检索端点（``/api/v1/retrieval/search``）
与 chat-api 的记忆列表端点（``/api/v1/memories``），以混合检索读负载。
"""

from __future__ import annotations

import os

from locust import HttpUser, between, task

CONCURRENCY_LEVELS = (1, 10, 50, 100)
RETRIEVAL_ENDPOINT = "/api/v1/retrieval/search"
MEMORIES_ENDPOINT = "/api/v1/memories"


class SearchUser(HttpUser):
    """检索场景：混合向量检索 + 结构化记忆查询，模拟知识库检索读负载。"""

    wait_time = between(0.5, 2.0)
    host = os.getenv("TARGET_HOST", "http://localhost:8001")

    def on_start(self) -> None:
        self.tenant_id = os.getenv("TARGET_TENANT_ID") or "benchmark-tenant"

    @task(7)
    def vector_search(self) -> None:
        with self.client.post(
            RETRIEVAL_ENDPOINT,
            json={"query": "性能优化实践", "top_k": 10},
            headers={"x-tenant-id": self.tenant_id, "Content-Type": "application/json"},
            catch_response=True,
            name=RETRIEVAL_ENDPOINT,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            elif resp.status_code in (429, 503):
                resp.success()
            else:
                resp.failure(f"unexpected status {resp.status_code}: {resp.text[:200]}")

    @task(3)
    def memory_list(self) -> None:
        with self.client.get(
            MEMORIES_ENDPOINT,
            params={"limit": 20, "offset": 0},
            headers={"x-tenant-id": self.tenant_id},
            catch_response=True,
            name=MEMORIES_ENDPOINT,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            elif resp.status_code in (429, 503):
                resp.success()
            else:
                resp.failure(f"unexpected status {resp.status_code}")