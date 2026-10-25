#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════
# deploy/probes/readiness.sh — Readiness 探针（T105）
# ═══════════════════════════════════════════════════════════════════════
#
# 用途：这个实例**现在能不能接流量**。
#
# 与 liveness 的分工（最容易配错的一对）：
#   * readiness 失败 → 从负载均衡后端摘掉，**不重启**。依赖（Mongo/Redis）
#     短暂不可用时，重启毫无意义，只会把还在恢复的连接池一起打散。
#   * liveness 失败 → 重启实例。只在进程真的卡死时才应该发生。
#
# 把依赖检查配到 liveness 上，会得到"数据库抖动 → 全部实例连环重启 →
# 抖动变成宕机"的经典放大故障。所以这里查依赖，liveness.sh 只查进程。
#
# 用法：
#   readiness.sh <base-url>        # 默认 http://127.0.0.1:8000
#
# 退出码：0 就绪；1 未就绪（compose healthcheck 视为 unhealthy）。
set -Eeuo pipefail

base_url="${1:-http://127.0.0.1:8000}"

# 镜像里 python 的可执行名不统一（python / python3 都可能），先探再用。
PYTHON_BIN="$(command -v python3 || command -v python || true)"
if [[ -z "${PYTHON_BIN}" ]]; then
  echo "probe: 找不到 python 解释器" >&2
  exit 1
fi

# 用 python 而不是 curl：镜像里不一定装了 curl，python 是应用自身依赖。
exec "${PYTHON_BIN}" - "${base_url%/}/ready" <<'PY'
import sys
import urllib.error
import urllib.request

url = sys.argv[1]
try:
    with urllib.request.urlopen(url, timeout=3) as response:
        body = response.read(4096).decode("utf-8", "replace")
        status = response.status
except urllib.error.HTTPError as exc:
    body = exc.read(4096).decode("utf-8", "replace") if exc.fp else ""
    print(f"readiness: HTTP {exc.code} from {url}: {body[:300]}", file=sys.stderr)
    raise SystemExit(1)
except Exception as exc:  # noqa: BLE001 - 探针只需要"行/不行"
    print(f"readiness: {type(exc).__name__}: {exc}", file=sys.stderr)
    raise SystemExit(1)

if status != 200:
    print(f"readiness: HTTP {status} from {url}: {body[:300]}", file=sys.stderr)
    raise SystemExit(1)

# /ready 契约：dependencies 里出现非 ok 状态即未就绪。
# 解析失败不算未就绪——老版本可能返回纯文本 "ok"。
if "dependencies" in body:
    import json

    try:
        payload = json.loads(body)
    except ValueError:
        raise SystemExit(0)
    deps = payload.get("dependencies") or {}
    bad = [name for name, value in deps.items() if isinstance(value, dict) and value.get("status") not in (None, "ok")]
    if bad:
        print(f"readiness: 依赖未就绪: {', '.join(sorted(bad))}", file=sys.stderr)
        raise SystemExit(1)
PY
