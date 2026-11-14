#!/usr/bin/env python3
"""023 T117 测试用假故障环境：API + Prometheus + Alertmanager + Grafana。

它们共享 `FAKE_DOCKER_STATE`（由 fake_docker.py 改写），于是「容器停掉」这件事
会真实地反映到探针、指标和告警上——这正是演练脚本要断言的因果链。

FAKE_MODE 用于注入「不该通过」的场景，验证断言确实会失败：
  pass         正常因果链
  no-alert     容器停了但 Alertmanager 没有告警
  stuck-ready  容器停了但 /ready 仍然 200（探针没查依赖）
  no-circuit   容器停了但熔断指标没打开（熔断未接线）

用法：fake_fault_env.py <port-file>
"""
from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

MODE = os.environ.get("FAKE_MODE", "pass")
STATE_PATH = os.environ.get("FAKE_DOCKER_STATE", "")


def _running() -> list[str]:
    if not STATE_PATH or not os.path.exists(STATE_PATH):
        return []
    try:
        with open(STATE_PATH, encoding="utf-8") as handle:
            return json.load(handle).get("running", [])
    except Exception:
        return []


def _send(handler, payload, status: int = 200) -> None:
    body = json.dumps(payload).encode()
    handler.send_response(status)
    handler.send_header("content-type", "application/json")
    handler.send_header("content-length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class _Base(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass


class _ApiHandler(_Base):
    def do_GET(self):  # noqa: N802
        path = urlparse(self.path).path
        if path not in {"/ready", "/health"}:
            _send(self, {"error": "not found"}, status=404)
            return

        mongo_up = "mongo" in _running()
        if path == "/health":
            _send(self, {"status": "ok"})
            return

        if MODE == "stuck-ready":
            # 故障场景：探针明明依赖 Mongo，却仍然报就绪
            _send(self, {"status": "ok", "dependencies": {"mongodb": {"ok": True}}})
            return

        if mongo_up:
            _send(self, {"status": "ok", "dependencies": {"mongodb": {"ok": True}}})
        else:
            _send(
                self,
                {
                    "status": "degraded",
                    "dependencies": {
                        "mongodb": {"ok": False, "reason": "circuit_open", "error": "circuit breaker open"}
                    },
                },
                status=503,
            )


class _PromHandler(_Base):
    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path in {"/-/ready"}:
            _send(self, {"status": "ok"})
            return
        if parsed.path != "/api/v1/query":
            _send(self, {"error": "not found"}, status=404)
            return

        query = (parse_qs(parsed.query).get("query") or [""])[0]
        mongo_up = "mongo" in _running()
        value = "0"
        if "mogo_circuit_breaker_state" in query:
            if 'state="open"' in query:
                if not mongo_up and MODE != "no-circuit":
                    value = "1"
            elif 'state="closed"' in query:
                if mongo_up:
                    value = "1"
        _send(
            self,
            {"status": "success", "data": {"resultType": "vector", "result": [{"metric": {}, "value": [1700000000, value]}]}},
        )


class _AmHandler(_Base):
    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/-/ready":
            _send(self, {"status": "ok"})
            return
        if parsed.path != "/api/v2/alerts":
            _send(self, {"error": "not found"}, status=404)
            return

        mongo_up = "mongo" in _running()
        if not mongo_up and MODE != "no-alert":
            _send(
                self,
                [
                    {
                        "labels": {"alertname": "MogoCriticalPathErrorRateSpike", "severity": "P1"},
                        "status": {"state": "firing"},
                    }
                ],
            )
        else:
            _send(self, [])


class _GrafanaHandler(_Base):
    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/dashboards/uid/"):
            uid = parsed.path.rsplit("/", 1)[-1]
            _send(self, {"dashboard": {"uid": uid, "title": "Troubleshooting"}, "meta": {"canSave": False}})
            return
        _send(self, {"error": "not found"}, status=404)


SERVICES = {
    "api": _ApiHandler,
    "prometheus": _PromHandler,
    "alertmanager": _AmHandler,
    "grafana": _GrafanaHandler,
}


def main() -> int:
    if len(sys.argv) != 2:
        print("用法: fake_fault_env.py <port-file>", file=sys.stderr)
        return 2
    port_file = sys.argv[1]

    servers = {}
    for name, handler_cls in SERVICES.items():
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
        servers[name] = server
        threading.Thread(target=server.serve_forever, daemon=True).start()

    with open(port_file, "w", encoding="utf-8") as handle:
        for name, server in servers.items():
            handle.write("%s=%d\n" % (name, server.server_address[1]))

    threading.Event().wait()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
