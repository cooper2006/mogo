"""026 T045 — 对话场景压测（FR-31）。

用法（并发级别 1/10/50/100）::

    TARGET_HOST=http://localhost:8000 locust -f benchmarks/locust/locustfile_chat.py \
        -u 10 -r 2 --host http://localhost:8000 --headless --run-time 60s

并发级别通过 locust 的 ``-u/--users`` 指定：``1``（单实例基准）、``10``、``50``、``100``。
"""

from __future__ import annotations

import json
import os
from typing import Any

from locust import HttpUser, between, task

CONCURRENCY_LEVELS = (1, 10, 50, 100)
CHAT_ENDPOINT = "/api/v1/chat/completions"


def _chat_payload(message: str) -> dict[str, Any]:
    return {
        "messages": [{"role": "user", "content": message}],
        "stream": False,
        "temperature": 0.2,
        "max_tokens": 128,
    }


class ChatUser(HttpUser):
    """对话场景：模拟终端用户发送一条短对话，等待流式/非流式响应。"""

    wait_time = between(1.0, 3.0)
    host = os.getenv("TARGET_HOST", "http://localhost:8000")

    def on_start(self) -> None:
        self.tenant_id = os.getenv("TARGET_TENANT_ID") or "benchmark-tenant"
        self.end_user_id = os.getenv("TARGET_END_USER_ID") or "benchmark-user"

    @task(10)
    def chat_short(self) -> None:
        with self.client.post(
            CHAT_ENDPOINT,
            json=_chat_payload("今天的工作计划"),
            headers={
                "x-tenant-id": self.tenant_id,
                "x-end-user-id": self.end_user_id,
                "Content-Type": "application/json",
            },
            catch_response=True,
            name=CHAT_ENDPOINT,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            elif resp.status_code in (429, 503):
                # 限流/背压按 FR-28 期望命中，计入 rejected 而非失败
                resp.success()
            else:
                resp.failure(f"unexpected status {resp.status_code}: {resp.text[:200]}")

    @task(2)
    def chat_long_context(self) -> None:
        payload = _chat_payload("总结以下对话要点")
        payload["messages"] = [
            {"role": "system", "content": "你是知识库助手"},
            {"role": "user", "content": "背景：" + "历史数据 " * 40},
            {"role": "assistant", "content": "已记录。"},
            {"role": "user", "content": "总结要点"},
        ]
        with self.client.post(
            CHAT_ENDPOINT,
            json=payload,
            headers={"x-tenant-id": self.tenant_id, "Content-Type": "application/json"},
            catch_response=True,
            name=f"{CHAT_ENDPOINT}:long",
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"unexpected status {resp.status_code}")


def _json_fixture() -> str:
    return json.dumps({"users": CONCURRENCY_LEVELS})