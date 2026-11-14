#!/usr/bin/env bash
# Keepalived 健康检查：判断本机 gateway 是否值得持有 VIP。
#
# 用在 VRRP 实例的 `vrrp_script` 里：
#
#   vrrp_script check_gateway {
#       script "/opt/mogo/deploy/keepalived/check_gateway.sh"
#       interval 3      # 每 3 秒探测一次
#       timeout  2      # 单次探测最多 2 秒
#       fall     3      # 连续 3 次失败才判定故障（避免抖动导致 VIP 来回漂）
#       rise     2      # 连续 2 次成功才恢复
#   }
#
# 退出码语义（keepalived 只认 0 / 非 0）：
#   0  → gateway 健康，可以持有 VIP
#   1  → gateway 不健康，应让出 VIP
#
# 注意：这里只查 gateway 的 `/health`（进程存活），**不查** /ready 的依赖状态。
# 依赖抖动时让出 VIP 会把流量赶到另一台同样连不上库的机器上，纯属折腾；
# 依赖问题由应用层降级处理，不由 VIP 漂移处理。

set -u -o pipefail

BASE_URL="${GATEWAY_HEALTH_URL:-http://127.0.0.1:8080}"
TIMEOUT="${GATEWAY_HEALTH_TIMEOUT:-2}"

# 优先 python3，退而求其次 python（镜像/发行版命名不统一）
PYTHON_BIN="$(command -v python3 || command -v python || true)"
if [ -z "${PYTHON_BIN}" ]; then
  echo "check_gateway: 找不到 python，无法探测 ${BASE_URL}" >&2
  exit 1
fi

exec "${PYTHON_BIN}" - "${BASE_URL}" "${TIMEOUT}" <<'PY'
import json
import sys
import urllib.error
import urllib.request

base_url = sys.argv[1].rstrip("/")
timeout = float(sys.argv[2])


def fail(message):
    print(f"check_gateway: {message}", file=sys.stderr)
    sys.exit(1)


try:
    with urllib.request.urlopen(f"{base_url}/health", timeout=timeout) as response:
        body = response.read()
        status = getattr(response, "status", 200)
except urllib.error.HTTPError as exc:
    fail(f"网关返回 {exc.code}")
except Exception as exc:  # noqa: BLE001 - 探测失败一律视为不健康
    fail(f"无法连接网关：{type(exc).__name__}")

if status != 200:
    fail(f"网关状态码 {status}")

# /health 的响应体不是所有服务都带 status 字段；带的时候顺带校验
try:
    payload = json.loads(body.decode("utf-8"))
except Exception:  # noqa: BLE001 - 非 JSON 视为健康（只看进程活着）
    print("check_gateway: ok")
    sys.exit(0)

status_value = str(payload.get("status", "ok")).lower()
if status_value not in {"ok", "healthy", "up"}:
    fail(f"网关自报状态 {status_value}")

print("check_gateway: ok")
PY
