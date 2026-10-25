#!/usr/bin/env bash
# 024 T045 (FR-021)：灰度期新旧版本指标并排对比。
# 从 Prometheus 查询 rollback-conditions.yml 里定义的指标，按 canary / stable
# 两个版本维度输出对照表（错误率、p95 延迟、5xx 率、超时率、可用性）。
# 指标口径复用 007 llm-gateway-resilience。
#
# 用法：deploy/cli/canary-metrics.sh [--url http://prometheus:9090] [--window 5m] [--json]
# 依赖：curl、python3（含 pyyaml）。
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COND_FILE="${ROOT_DIR}/deploy/canary/rollback-conditions.yml"
PROM_URL="${MOGO_PROMETHEUS_URL:-http://localhost:9090}"
WINDOW="5m"
JSON=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --url) PROM_URL="$2"; shift 2 ;;
    --window) WINDOW="$2"; shift 2 ;;
    --json) JSON=1; shift ;;
    -h|--help) echo "用法: canary-metrics.sh [--url URL] [--window 5m] [--json]"; exit 0 ;;
    *) echo "错误: 未知参数 $1" >&2; exit 2 ;;
  esac
done

if [[ ! -f "${COND_FILE}" ]]; then
  echo "错误: 找不到 ${COND_FILE}" >&2
  exit 2
fi
command -v curl >/dev/null 2>&1 || { echo "错误: curl 不可用" >&2; exit 2; }

metric_expr() { python3 -c '
import json, yaml, sys
d = yaml.safe_load(open(sys.argv[1]))
print(d["rollback_conditions"]["queries"].get(sys.argv[2], ""))' "${COND_FILE}" "$1"; }
metric_rule() { python3 -c '
import json, yaml, sys
d = yaml.safe_load(open(sys.argv[1]))
for c in d["rollback_conditions"]["conditions"]:
    if c["metric"] == sys.argv[2]:
        print(c["op"]); break' "${COND_FILE}" "$1"; }

query_value() {
  local promql="$1"
  local ts="$2"
  local out
  out=$(curl -sf --max-time 10 -G "${PROM_URL}/api/v1/query" \
    --data-urlencode "query=${promql}" \
    --data-urlencode "time=${ts}" 2>/dev/null) || { echo "N/A"; return; }
  python3 -c '
import json, sys
try:
    d = json.loads(sys.argv[1])
    res = d["data"]["result"]
    print(res[0]["value"][1] if res else "N/A")
except Exception:
    print("N/A")' "${out}"
}

METRICS=$(python3 -c '
import json, yaml, sys
d = yaml.safe_load(open(sys.argv[1]))
print(" ".join(d["rollback_conditions"]["queries"].keys()))' "${COND_FILE}")

NOW=$(python3 -c 'import time; print(int(time.time()))')
STAMP=$(python3 -c 'import datetime; print(datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))')

echo "# 灰度新旧版本指标对比（窗口 ${WINDOW}，查询时刻 ${STAMP}）"
echo
echo "| 指标 | canary（新版本） | stable（稳定版） | 基线规则 |"
echo "| --- | --- | --- | --- |"

for metric in ${METRICS}; do
  expr_base=$(metric_expr "${metric}")
  [[ -z "${expr_base}" ]] && continue
  c_expr=${expr_base//\{canary=\"1\"/\{canary=\"1\"}
  s_expr=${expr_base//\{canary=\"1\"/\{canary!=\"1\"}
  c_val=$(query_value "${c_expr}" "${NOW}")
  s_val=$(query_value "${s_expr}" "${NOW}")
  rule=$(metric_rule "${metric}")

  if [[ "${JSON}" == "1" ]]; then
    python3 -c '
import json, sys
print(json.dumps({"metric": sys.argv[1], "canary": sys.argv[2], "stable": sys.argv[3], "rule": sys.argv[4]}))' \
      "${metric}" "${c_val}" "${s_val}" "${rule}"
  else
    printf '| %s | %s | %s | %s |\n' "${metric}" "${c_val}" "${s_val}" "${rule}"
  fi
done

if [[ "${JSON}" != "1" ]]; then
  echo
  echo "说明：canary 版指标带 label canary=1（nginx 分流进入 canary 副本的流量），"
  echo "稳定版为 canary 不等于 1。任一 canary 指标命中 rollback-conditions.yml 的 op 即触发自动回滚。"
fi
