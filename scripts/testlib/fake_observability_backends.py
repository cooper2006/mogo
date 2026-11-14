#!/usr/bin/env python3
"""023 T116 测试用假可观测性后端（gateway / Loki / Tempo / Prometheus / Alertmanager）。

存在的理由：`scripts/verify_e2e_observability.sh` 的断言全是打真实 HTTP 的。
没有真实 compose 环境时它返回 2（明确失败），但「返回 2」证明不了断言本身有效——
一个永远 return 0 的脚本也会在坏环境里返回 2。所以这里起 5 个最小假后端，让验证
脚本在一个**已知答案**的环境里跑，分别验证「该过的时候过」和「该失败的时候失败」。

用法：python3 fake_observability_backends.py <port-file>
  端口以 `name=port` 逐行写入 <port-file>。
环境变量 FAKE_MODE 控制行为：
  pass        全部正常（默认）
  empty-loki  Loki 查不到日志
  empty-tempo Tempo 查不到 trace
  no-rules    Prometheus 的告警规则组为空
"""
from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

MODE = os.environ.get("FAKE_MODE", "pass")


def _send(handler: BaseHTTPRequestHandler, payload, status: int = 200, ctype: str = "application/json") -> None:
    body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    handler.send_response(status)
    handler.send_header("content-type", ctype)
    handler.send_header("content-length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class _Base(BaseHTTPRequestHandler):
    def log_message(self, *_args):  # 静音，避免污染测试输出
        pass


def _make_handler(routes):
    class _Handler(_Base):
        def do_GET(self):  # noqa: N802
            parsed = urlparse(self.path)
            handler = routes.get(parsed.path)
            if handler is None:
                _send(self, {"error": "not found", "path": parsed.path}, status=404)
                return
            handler(self, parse_qs(parsed.query))

    return _Handler


def _ready(handler, _query):
    _send(handler, {"status": "ok"})


def _gateway(handler, _query):
    _send(handler, {"status": "ok", "checks": {"mongodb": {"ok": True}}})


def _loki_query(handler, _query):
    if MODE == "empty-loki":
        result = []
    else:
        result = [{"stream": {"service_name": "chat-api"}, "values": [["1700000000000000000", "turn handled"]]}]
    _send(handler, {"status": "success", "data": {"resultType": "streams", "result": result}})


def _tempo_trace(handler, _query):
    if MODE == "empty-tempo":
        _send(handler, {})
    else:
        _send(handler, {"batches": [{"resource": {}, "scopeSpans": []}]})


def _prom_query(handler, query):
    raw = (query.get("query") or [""])[0]
    if "mogo_http_requests_total" in raw:
        value = "42"
    elif "mogo:slo:availability:error_rate" in raw:
        value = "0.0012"
    elif "mogo_circuit_breaker_state" in raw:
        value = "1"
    else:
        value = "1"
    _send(
        handler,
        {
            "status": "success",
            "data": {"resultType": "vector", "result": [{"metric": {}, "value": [1700000000, value]}]},
        },
    )


def _prom_rules(handler, _query):
    count = 0 if MODE == "no-rules" else 12
    rules = [
        {"name": "MogoAlert%d" % index, "state": "inactive", "labels": {"severity": "P1"}}
        for index in range(count)
    ]
    _send(handler, {"status": "success", "data": {"groups": [{"name": "mogo-alert-rules", "rules": rules}]}})


def _am_status(handler, _query):
    _send(handler, {"cluster": {"status": "ready", "peers": []}, "versionInfo": {"version": "0.27.0"}})


SERVICES = {
    "gateway": {"/ready": _gateway, "/health": _ready},
    "loki": {"/ready": _ready, "/loki/api/v1/query_range": _loki_query},
    "tempo": {"/ready": _ready, "/api/echo": _ready, "/api/traces": _tempo_trace},
    "prometheus": {"/-/ready": _ready, "/api/v1/query": _prom_query, "/api/v1/rules": _prom_rules},
    "alertmanager": {"/-/ready": _ready, "/api/v2/status": _am_status},
}


class _TempoHandler(_Base):
    """Tempo 的 trace 路径带 trace_id（`/api/traces/<id>`），需前缀匹配。"""

    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/traces/"):
            _tempo_trace(self, parse_qs(parsed.query))
            return
        handler = SERVICES["tempo"].get(parsed.path)
        if handler is None:
            _send(self, {"error": "not found"}, status=404)
            return
        handler(self, parse_qs(parsed.query))

    def log_message(self, *_args):
        pass


def main() -> int:
    if len(sys.argv) != 2:
        print("用法: fake_observability_backends.py <port-file>", file=sys.stderr)
        return 2
    port_file = sys.argv[1]

    servers = {}
    for name, routes in SERVICES.items():
        handler_cls = _TempoHandler if name == "tempo" else _make_handler(routes)
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
