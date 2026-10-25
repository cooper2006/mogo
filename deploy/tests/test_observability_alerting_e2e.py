"""023 Phase 5 告警分级 + 静默/抑制 的**端到端**回归守卫（T074 / T075）。

前面的 ``test_observability_alerting_config.py`` 只做静态检查，抓不到三类线上
才会暴露的缺陷——其中最关键的一类：**Alertmanager 模板解析失败**。2026-10-26
实测在真实 Alertmanager v0.27 下加载配置，日志报::

    failed to parse templates: template: mogo.tmpl:5: function "default" not defined

Go text/template 的函数集**不含** Sprig 的 ``default``，而 mogo.tmpl 用了 7 处
``| default "..."``。结果是整个模板解析失败，P0/P1 通知虽仍能发出，但
**FR-18 要求的三个排障入口（Runbook / Grafana / Trace 链接）会静默丢失**——
静态测试完全查不出。本文件在真实 Alertmanager 上做端到端断言：

1. ``T074``：P0 SLO 违约（``MogoAvailabilityBurnRateFast``）→ 通知触达
   IM webhook（``/im/p0``）**和** 邮件，且正文带 Runbook/Grafana/Trace 三链接。
2. ``T075a``：维护窗口 silence 内 P1 不投递；撤 silence 后同告警恢复投递。
3. ``T075b``：同 service+component 的 P0 抑制 P1/P2（同根因去重）。

**运行前置**（本机无镜像/二进制时自动 skip，CI 无 docker 因此天然跳过）::

    # 起一个真实 Alertmanager（--network host 使容器内 127.0.0.1 即宿主机）
    docker run -d --name am-test --network host \
      -v "$PWD/deploy/alertmanager/alertmanager.yml:/etc/alertmanager/alertmanager.yml:ro" \
      -v "$PWD/deploy/alertmanager/templates:/etc/alertmanager/templates:ro" \
      docker.m.daocloud.io/prom/alertmanager:v0.27.0 \
      --config.file=/etc/alertmanager/alertmanager.yml --storage.path=/alertmanager
    # 再运行本测试
    AM_E2E=1 python -m pytest deploy/tests/test_observability_alerting_e2e.py -q

若宿主机无法绑定 SMTP 25（mac 非 root），把配置里 ``smtp_smarthost`` 临时改成
``127.0.0.1:2525``（仅本机测试用，不提交）。
"""

from __future__ import annotations

import json
import os
import socketserver
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ALERTMANAGER_URL = os.environ.get("AM_URL", "http://127.0.0.1:9093")
WEBHOOK_ADDR = ("127.0.0.1", 9999)
# mac 非 root 无法绑 25；本机测试用 2525 时改 AM_SMTP_PORT=2525
SMTP_ADDR = ("127.0.0.1", int(os.environ.get("AM_SMTP_PORT", "25")))

RUNBOOK = "https://github.com/cooper2006/mogo/blob/main/docs/runbooks/high_error_rate.md"
DASHBOARD = "http://localhost:3001/d/mogo-troubleshooting"
TRACE = "http://localhost:3001/d/mogo-troubleshooting?var-trace_id="


# ── skip 判定 ────────────────────────────────────────────────────────────────────────


def _alertmanager_ready() -> bool:
    if not os.environ.get("AM_E2E"):
        return False
    try:
        with urllib.request.urlopen(ALERTMANAGER_URL + "/-/healthy", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _alertmanager_ready(),
    reason=(
        "需真实 Alertmanager 容器（AM_E2E=1 且 docker 起 am-test 后运行）；"
        "本机无 docker/镜像或 CI 环境自动跳过。"
    ),
)


# ── 本地捕获器（模拟 IM webhook 与 SMTP） ────────────────────────────────────────────


class _WebhookHandler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw)
        except Exception:
            body = {"raw": raw.decode("utf-8", "replace")}
        RECORDER["webhook"].append({"path": self.path, "body": body})
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args, **kwargs):
        pass


class _SmtpServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True


class _SmtpHandler(socketserver.StreamRequestHandler):
    def _send(self, line):
        self.wfile.write((line + "\r\n").encode())
        self.wfile.flush()

    def handle(self):
        self._send("220 mogo-e2e SMTP ready")
        data_mode = False
        current: list[str] = []
        while True:
            line = self.rfile.readline()
            if not line:
                break
            text = line.decode("utf-8", "replace").rstrip("\r\n")
            if data_mode:
                if text == ".":
                    RECORDER["smtp"].append("".join(current))
                    current, data_mode = [], False
                    self._send("250 OK queued")
                else:
                    current.append(text + "\n")
                continue
            up = text.upper()
            if up.startswith(("EHLO", "HELO")):
                self._send("250-mogo-e2e")
                self._send("250 8BITMIME")
            elif up.startswith(("MAIL FROM", "RCPT TO")):
                self._send("250 OK")
            elif up.startswith("DATA"):
                data_mode = True
                self._send("354 End data with <CR><LF>.<CR><LF>")
            elif up.startswith("QUIT"):
                self._send("221 Bye")
                break
            else:
                self._send("250 OK")


RECORDER: dict = {"webhook": [], "smtp": []}
_servers: list = []


@pytest.fixture(autouse=True)
def _capture_servers():
    """每个测试起 webhook+SMTP 监听，测完关闭并清空记录。"""
    RECORDER["webhook"].clear()
    RECORDER["smtp"].clear()
    wh = HTTPServer(WEBHOOK_ADDR, _WebhookHandler)
    smtp = _SmtpServer(SMTP_ADDR, _SmtpHandler)
    t1 = threading.Thread(target=wh.serve_forever, daemon=True)
    t2 = threading.Thread(target=smtp.serve_forever, daemon=True)
    t1.start()
    t2.start()
    yield
    wh.shutdown()
    smtp.shutdown()
    wh.server_close()   # 只 shutdown() 不 close，端口会残留占用，下一用例 bind 失败
    smtp.server_close()


# ── Alertmanager API 客户端 ──────────────────────────────────────────────────────────


def _api(method: str, path: str, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        ALERTMANAGER_URL + path, data=data, method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        raw = r.read().decode()
    return json.loads(raw) if raw else None


def _resolve_all():
    """清空 Alertmanager 状态（重建容器）。

    **为什么不能 docker restart**：``--storage.path=/alertmanager`` 挂的是持久卷，
    Alertmanager 会把 active alert 落盘。restart 后旧告警仍在内存里，POST 同指纹
    告警被当作「已有告警更新」，通知组不重新触发（``repeat_interval`` 未到），
    测试互相污染（实测 `docker restart` 后 P0 45s 内不投递，重建容器后 10s 内投递）。
    **为什么不用 API DELETE**：``DELETE /api/v2/alerts`` 在 v0.27 返回 405。
    唯一可靠手段是 ``docker rm -f`` + ``docker run`` 重建（配置挂载不变）。
    """
    import subprocess

    conf = os.environ.get(
        "AM_ALERTMANAGER_CONF",
        str(REPO_ROOT / "deploy/alertmanager/alertmanager.yml"),
    )
    container = os.environ.get("AM_CONTAINER", "am-test")
    image = os.environ.get("AM_IMAGE", "docker.m.daocloud.io/prom/alertmanager:v0.27.0")
    subprocess.run(["docker", "rm", "-f", container], capture_output=True)
    subprocess.run(
        [
            "docker", "run", "-d", "--name", container, "--network", "host",
            "-v", f"{conf}:/etc/alertmanager/alertmanager.yml:ro",
            "-v", f"{REPO_ROOT}/deploy/alertmanager/templates:/etc/alertmanager/templates:ro",
            image,
            "--config.file=/etc/alertmanager/alertmanager.yml",
            "--storage.path=/alertmanager",
        ],
        capture_output=True,
    )
    deadline = time.time() + 40
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(ALERTMANAGER_URL + "/-/healthy", timeout=3) as r:
                if r.status == 200:
                    time.sleep(3)
                    return
        except Exception:
            pass
        time.sleep(1)
    raise RuntimeError("Alertmanager 重建后未 healthy")


def _post_alerts(alerts):
    _api("POST", "/api/v2/alerts", alerts)


def _make_alert(alertname: str, severity: str, annotations: dict, **labels) -> dict:
    base = {"alertname": alertname, "severity": severity, "service": "chat-api",
            "component": "api"}
    base.update(labels)
    return {"labels": base, "annotations": annotations}


def _p0(**labels):
    return _make_alert(
        "MogoAvailabilityBurnRateFast", "P0",
        {"summary": "错误预算快速耗尽（SLO 违约）",
         "description": "错误预算消耗速度超过阈值",
         "runbook_url": RUNBOOK, "dashboard_url": DASHBOARD, "trace_url": TRACE},
        **labels,
    )


def _p1(**labels):
    return _make_alert(
        "MogoLatencyP99High", "P1",
        {"summary": "P99 延迟突增", "description": "关键路径 P99 延迟超过阈值",
         "runbook_url": RUNBOOK, "dashboard_url": DASHBOARD, "trace_url": TRACE},
        **labels,
    )


def _silence_service(service: str) -> str:
    return _api("POST", "/api/v2/silences", {
        "matchers": [{"name": "service", "value": service, "isRegex": False, "isEqual": True}],
        "startsAt": "2026-10-25T00:00:00Z",
        "endsAt": "2026-10-26T00:00:00Z",
        "createdBy": "e2e-test",
        "comment": "维护窗口 E2E",
    })["silenceID"]


def _wait(pred, timeout=45, interval=2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pred():
            return True
        time.sleep(interval)
    return False


def _im_hits(path: str):
    return [c for c in RECORDER["webhook"] if c["path"] == path]


# ── T074：P0 SLO 违约分级测试 ────────────────────────────────────────────────────────


def test_t074_p0_slo_violation_reaches_im_webhook():
    """P0 SLO 违约告警必须在 5 分钟内触达 IM webhook（FR-15/FR-17）。"""
    _resolve_all()
    _post_alerts([_p0()])
    assert _wait(lambda: _im_hits("/im/p0")), (
        "POST P0(MogoAvailabilityBurnRateFast) 后 45s 内未收到 /im/p0 —— 分级路由"
        "或 receiver 配置失效，P0 通知通道哑了。"
    )
    alerts = _im_hits("/im/p0")[0]["body"].get("alerts") or []
    assert alerts, "webhook 载荷缺 alerts 数组"
    labels = alerts[0].get("labels") or {}
    assert labels.get("severity") == "P0", f"通知载荷 severity={labels.get('severity')}"


def test_t074_p0_notification_contains_three_runbook_entries():
    """FR-18：P0 通知必须带 Runbook / Grafana / Trace 三个排障入口。"""
    _resolve_all()
    _post_alerts([_p0()])
    assert _wait(lambda: _im_hits("/im/p0"))
    annotations = (_im_hits("/im/p0")[0]["body"].get("alerts") or [{}])[0].get("annotations") or {}
    assert annotations.get("runbook_url") == RUNBOOK, "缺 Runbook 链接（排障入口 1）"
    assert annotations.get("dashboard_url") == DASHBOARD, "缺 Grafana 面板链接（排障入口 2）"
    assert annotations.get("trace_url") == TRACE, "缺 Trace 查询链接（排障入口 3）"


def test_t074_p0_reaches_email_with_runbook_link():
    """FR-17/FR-18：P0 同时触达邮件，正文含 Runbook 链接。"""
    _resolve_all()
    _post_alerts([_p0()])
    assert _wait(lambda: len(RECORDER["smtp"]) > 0), (
        "45s 内未收到 SMTP 投递 —— receiver 的 email_configs 未生效或 smtp_smarthost"
        "不可达。"
    )
    mail = RECORDER["smtp"][0]
    assert "high_error_rate.md" in mail, "邮件正文未包含 Runbook 链接"
    assert "[P0]" in mail, "邮件主题未体现告警分级 P0"


# ── T075a：维护窗口静默 ─────────────────────────────────────────────────────────────


def test_t075a_maintenance_silence_blocks_p1():
    """维护窗口 silence 内，P1 不投递 IM 与邮件。"""
    _resolve_all()
    _silence_service("chat-api")
    _post_alerts([_p1()])
    time.sleep(40)  # P1 group_wait=30s，留出触发窗口
    assert not _im_hits("/im/p1"), "维护窗口内 P1 不应投递 IM webhook"
    assert not RECORDER["smtp"], "维护窗口内 P1 不应投递邮件"
    # 清理所有 silence，避免污染后续用例
    for sl in _api("GET", "/api/v2/silences"):
        try:
            _api("DELETE", "/api/v2/silence/" + sl["id"])
        except Exception:
            pass


def test_t075a_p1_recovers_after_silence_removed():
    """撤 silence 后，同一条 P1 告警恢复投递（证明是 silence 生效而非告警失效）。"""
    sid = _silence_service("chat-api")
    _post_alerts([_p1()])
    time.sleep(3)
    _api("DELETE", "/api/v2/silence/" + sid)
    _resolve_all()  # 清掉静默期的旧 P1，让新的走全新 group_wait
    _post_alerts([_p1()])
    assert _wait(lambda: _im_hits("/im/p1")), (
        "撤 silence 后 P1 45s 内未恢复投递 —— 说明上一条通过是「告警根本没发」"
        "而非 silence 生效。"
    )
    for sl in _api("GET", "/api/v2/silences"):
        try:
            _api("DELETE", "/api/v2/silence/" + sl["id"])
        except Exception:
            pass


# ── T075b：同根因抑制 ───────────────────────────────────────────────────────────────


def test_t075b_inhibit_suppresses_p1_when_p0_fires():
    """同 service+component 的 P0 触发时，抑制 P1/P2（同根因去重）。"""
    _resolve_all()
    _post_alerts([_p0(), _p1()])  # 同 service=chat-api / component=api
    assert _wait(lambda: _im_hits("/im/p0")), "P0 应照常投递 /im/p0"
    time.sleep(35)  # 给 P1 group_wait(30s) 留出触发窗口
    assert not _im_hits("/im/p1"), (
        "P0 firing 时同 service+component 的 P1 不应投递 —— inhibit_rules[0]"
        "（severity=P0 → P1|P2, equal service+component）未生效。"
    )