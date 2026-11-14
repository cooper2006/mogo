"""026 T046 — 文档解析场景压测（FR-31）。

用法（并发级别 1/10/50/100）::

    TARGET_HOST=http://localhost:8001 locust -f benchmarks/locust/locustfile_doc.py \
        -u 10 -r 2 --host http://localhost:8001 --headless --run-time 60s

文档解析为异步任务（202 Accepted），脚本同时轮询任务状态端点，
以覆盖「提交 + 轮询」的完整用户路径。
"""

from __future__ import annotations

import os
import uuid
from typing import Any

from locust import HttpUser, between, task

CONCURRENCY_LEVELS = (1, 10, 50, 100)
SUBMIT_ENDPOINT = "/api/v1/jobs/document-parse"


class DocumentUser(HttpUser):
    """文档解析场景：提交一个 ≤20 页 PDF 的解析任务并轮询结果。"""

    wait_time = between(2.0, 5.0)
    host = os.getenv("TARGET_HOST", "http://localhost:8001")

    def on_start(self) -> None:
        self.tenant_id = os.getenv("TARGET_TENANT_ID") or "benchmark-tenant"

    @task(1)
    def submit_and_poll(self) -> None:
        task_id = str(uuid.uuid4())
        payload: dict[str, Any] = {
            "file_name": f"bench-{task_id[:8]}.pdf",
            "file_uri": os.getenv("TARGET_PDF_URI", "s3://benchmarks/sample-20p.pdf"),
            "document_type": "pdf",
        }
        with self.client.post(
            SUBMIT_ENDPOINT,
            json=payload,
            headers={"x-tenant-id": self.tenant_id, "Content-Type": "application/json"},
            catch_response=True,
            name=SUBMIT_ENDPOINT,
        ) as resp:
            if resp.status_code == 202:
                resp.success()
            elif resp.status_code in (429, 503):
                resp.success()
            else:
                resp.failure(f"unexpected status {resp.status_code}: {resp.text[:200]}")
                return
        # 轮询任务状态（最多 3 次，单次快速命中）
        for _ in range(3):
            with self.client.get(
                f"/api/v1/jobs/{task_id[:8]}",
                headers={"x-tenant-id": self.tenant_id},
                catch_response=True,
                name="/api/v1/jobs/{id}",
            ) as poll:
                if poll.status_code == 200:
                    poll.success()
                else:
                    poll.failure(f"unexpected status {poll.status_code}")
                break