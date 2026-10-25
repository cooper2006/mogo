#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════
# deploy/probes/liveness.sh — Liveness 探针（T105）
# ═══════════════════════════════════════════════════════════════════════
#
# 用途：这个实例的进程**还活着吗**。失败意味着该重启。
#
# 只查进程自身，**故意不查 Mongo/Redis**：依赖不可用是 readiness 的事。
# 把依赖检查放在这里，会让一次数据库抖动把所有副本连锁重启，把可恢复的
# 抖动放大成真宕机（见 readiness.sh 顶部注释）。
#
# 用法：
#   liveness.sh <health-url>       # 默认 http://127.0.0.1:8000/health
#
# 退出码：0 存活；1 需要重启。
set -Eeuo pipefail

health_url="${1:-http://127.0.0.1:8000/health}"

# 镜像里 python 的可执行名不统一（python / python3 都可能），先探再用。
PYTHON_BIN="$(command -v python3 || command -v python || true)"
if [[ -z "${PYTHON_BIN}" ]]; then
  echo "probe: 找不到 python 解释器" >&2
  exit 1
fi

exec "${PYTHON_BIN}" - "${health_url}" <<'PY'
import sys
import urllib.error
import urllib.request
import json

url = sys.argv[1]
try:
    with urllib.request.urlopen(url, timeout=3) as response:
        body = response.read(4096).decode("utf-8", "replace")
        status = response.status
except urllib.error.HTTPError as exc:
    print(f"liveness: HTTP {exc.code} from {url}", file=sys.stderr)
    raise SystemExit(1)
except Exception as exc:  # noqa: BLE001
    print(f"liveness: {type(exc).__name__}: {exc}", file=sys.stderr)
    raise SystemExit(1)

if status != 200:
    print(f"liveness: HTTP {status} from {url}", file=sys.stderr)
    raise SystemExit(1)

# 明确要求 "status": "ok"/"healthy"（若响应里带 status 字段）。
try:
    payload = json.loads(body)
except ValueError:
    raise SystemExit(0)
if isinstance(payload, dict):
    status_value = payload.get("status")
    if status_value is not None and str(status_value).lower() not in ("ok", "healthy", "up"):
        print(f"liveness: status={status_value}", file=sys.stderr)
        raise SystemExit(1)
PY
