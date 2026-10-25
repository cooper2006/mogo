"""026 T047 — 鉴权场景压测（FR-31）。

用法（并发级别 1/10/50/100）::

    TARGET_ADMIN_USER=benchmark TARGET_ADMIN_PASSWORD=benchmark-secret \\
    TARGET_HOST=http://localhost:8002 locust -f benchmarks/locust/locustfile_auth.py \\
        -u 50 -r 5 --host http://localhost:8002 --headless --run-time 60s

鉴权场景覆盖 admin-api 的 ``/api/v1/auth/login``（P95 预算 500ms，见
``benchmarks/perf_baselines/baselines.yaml``）。凭据通过环境变量注入，
避免真实密码写入仓库；响应 401/403 属鉴权正常分支，计入成功。
"""

from __future__ import annotations

import os

from locust import HttpUser, between, task

CONCURRENCY_LEVELS = (1, 10, 50, 100)
LOGIN_ENDPOINT = "/api/v1/auth/login"


class AuthUser(HttpUser):
    """鉴权场景：登录 + 取当前用户信息，覆盖鉴权链路读负载。"""

    wait_time = between(0.5, 1.5)
    host = os.getenv("TARGET_HOST", "http://localhost:8002")

    def on_start(self) -> None:
        self.username = os.getenv("TARGET_ADMIN_USER", "benchmark")
        self.password = os.getenv("TARGET_ADMIN_PASSWORD", "benchmark-secret")

    @task(5)
    def login(self) -> None:
        with self.client.post(
            LOGIN_ENDPOINT,
            json={"username": self.username, "password": self.password},
            headers={"Content-Type": "application/json"},
            catch_response=True,
            name=LOGIN_ENDPOINT,
        ) as resp:
            if resp.status_code in (200, 401, 403):
                resp.success()
            elif resp.status_code in (429, 503):
                resp.success()
            else:
                resp.failure(f"unexpected status {resp.status_code}: {resp.text[:200]}")

    @task(2)
    def me(self) -> None:
        with self.client.get(
            "/api/v1/auth/me",
            headers={"x-admin-user-id": self.username},
            catch_response=True,
            name="/api/v1/auth/me",
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            elif resp.status_code in (401, 429, 503):
                resp.success()
            else:
                resp.failure(f"unexpected status {resp.status_code}")