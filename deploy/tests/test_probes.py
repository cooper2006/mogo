"""Liveness / Readiness 探针的行为测试（023 Phase 7 / T105）。

探针是**只有线上才会出错**的一类代码：本地什么都能跑通，线上因为一条错误的
退出码或者一个查不到的 python 解释器导致全部实例被判死，进而连环重启。

这里用真实的本地 HTTP server 驱动脚本，覆盖：

1. 就绪且依赖健康 → 退出 0
2. 依赖不健康（dependencies 里有非 ok）→ 退出 1
3. 服务返回 503 → 退出 1
4. 连不上 → 退出 1
5. liveness 只看进程：`/health` 返回 200 即通过，**不**因为依赖挂掉而失败

    python -m pytest deploy/tests/test_probes.py -q
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PROBES = REPO_ROOT / "deploy" / "probes"


class _Handler(BaseHTTPRequestHandler):
    """按路径返回预设响应；响应体来自 ``server.payloads``。"""

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler 约定
        payloads = self.server.payloads  # type: ignore[attr-defined]
        if self.path in payloads:
            status, body = payloads[self.path]
        else:
            status, body = 404, {"status": "missing"}
        encoded = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, *args: object) -> None:  # 静音访问日志
        return


@pytest.fixture()
def serve():
    """起一个本地 HTTP server，返回 (base_url, set_payloads) 与关闭钩子。"""
    servers: list[HTTPServer] = []

    def _start(payloads: dict[str, tuple[int, dict]]) -> str:
        httpd = HTTPServer(("127.0.0.1", 0), _Handler)
        httpd.payloads = payloads  # type: ignore[attr-defined]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        servers.append(httpd)
        host, port = httpd.server_address[:2]
        return f"http://{host}:{port}"

    yield _start

    for httpd in servers:
        httpd.shutdown()
        httpd.server_close()


def _run(script: str, url: str) -> tuple[int, str]:
    import subprocess

    completed = subprocess.run(
        ["bash", str(PROBES / script), url],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return completed.returncode, completed.stdout + completed.stderr


# ── readiness ─────────────────────────────────────────────────────────


def test_readiness_ok(serve) -> None:
    base = serve({"/ready": (200, {"status": "ok", "dependencies": {"mongodb": {"status": "ok"}, "redis": {"status": "ok"}}})})
    code, output = _run("readiness.sh", base)
    assert code == 0, output


def test_readiness_accepts_plain_text_ok(serve) -> None:
    base = serve({"/ready": (200, {"status": "ok"})})
    code, output = _run("readiness.sh", base)
    assert code == 0, output


def test_readiness_fails_when_dependency_unhealthy(serve) -> None:
    base = serve({"/ready": (200, {"status": "degraded", "dependencies": {"mongodb": {"status": "timeout"}}})})
    code, output = _run("readiness.sh", base)
    assert code == 1, output
    assert "依赖未就绪" in output


def test_readiness_fails_on_503(serve) -> None:
    base = serve({"/ready": (503, {"status": "unavailable"})})
    code, output = _run("readiness.sh", base)
    assert code == 1, output


def test_readiness_fails_when_unreachable() -> None:
    # 127.0.0.1:1 上没有服务
    code, output = _run("readiness.sh", "http://127.0.0.1:1")
    assert code == 1, output


def test_readiness_strips_trailing_slash(serve) -> None:
    base = serve({"/ready": (200, {"status": "ok"})})
    code, output = _run("readiness.sh", base + "/")
    assert code == 0, output


# ── liveness ──────────────────────────────────────────────────────────


def test_liveness_ok(serve) -> None:
    base = serve({"/health": (200, {"status": "ok"})})
    code, output = _run("liveness.sh", f"{base}/health")
    assert code == 0, output


def test_liveness_ignores_dependency_state(serve) -> None:
    """liveness 只关心进程；依赖状态是 readiness 的事。

    这条如果反过来，一次 Mongo 抖动会让所有副本被判死重启——可恢复的抖动
    被放大成真宕机。
    """
    base = serve({"/health": (200, {"status": "ok", "dependencies": {"mongodb": {"status": "timeout"}}})})
    code, output = _run("liveness.sh", f"{base}/health")
    assert code == 0, output


def test_liveness_fails_when_status_not_ok(serve) -> None:
    base = serve({"/health": (200, {"status": "degraded"})})
    code, output = _run("liveness.sh", f"{base}/health")
    assert code == 1, output


def test_liveness_fails_when_unreachable() -> None:
    code, output = _run("liveness.sh", "http://127.0.0.1:1/health")
    assert code == 1, output


# ── 纪律检查（源码级）─────────────────────────────────────────────────


def test_liveness_script_does_not_probe_dependencies() -> None:
    """liveness 脚本里出现 mongo/redis 就是配错了。"""
    body = (PROBES / "liveness.sh").read_text(encoding="utf-8")
    # 只检查可执行部分，注释里解释"为什么不查依赖"是允许的
    executable = "\n".join(
        line for line in body.splitlines() if not line.strip().startswith("#")
    )
    for needle in ("mongodb", "mongo:", "redis"):
        assert needle not in executable.lower(), f"liveness.sh 不应检查依赖：{needle}"


def test_readiness_script_checks_dependencies() -> None:
    body = (PROBES / "readiness.sh").read_text(encoding="utf-8")
    assert "dependencies" in body
    assert "/ready" in body
