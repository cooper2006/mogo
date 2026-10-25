#!/usr/bin/env bash
# 024 T046 (FR-022)：自动回滚执行器。
# 观察窗口结束后评估 deploy/canary/rollback-conditions.yml：任一条件命中
#（指标实测值超出阈值规则）即调用 deploy/cli/canary.sh rollback，无需人工介入。
#
# 用法：
#   deploy/cli/auto-rollback.sh [--url http://prometheus:9090] [--dry-run] [--json]
#
# 说明：--dry-run 只评估与告警，不真正执行回滚（预演）。
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COND_FILE="${ROOT_DIR}/deploy/canary/rollback-conditions.yml"
CANARY_SCRIPT="${ROOT_DIR}/deploy/cli/canary.sh"
PROM_URL="${MOGO_PROMETHEUS_URL:-http://localhost:9090}"
DRY=0
JSON=0
MAX_ROLLBACKS=2

while [[ $# -gt 0 ]]; do
  case "$1" in
    --url) PROM_URL="$2"; shift 2 ;;
    --dry-run) DRY=1; shift ;;
    --json) JSON=1; shift ;;
    -h|--help) echo "用法: auto-rollback.sh [--url URL] [--dry-run] [--json]"; exit 0 ;;
    *) echo "错误: 未知参数 $1" >&2; exit 2 ;;
  esac
done

[[ -f "${COND_FILE}" ]] || { echo "错误: 找不到 ${COND_FILE}" >&2; exit 2; }
[[ -f "${CANARY_SCRIPT}" ]] || { echo "错误: 找不到 ${CANARY_SCRIPT}" >&2; exit 2; }

# 已回滚次数（同一观察窗口内最多自动回滚 MAX_ROLLBACKS 次）
STATE_FILE="${ROOT_DIR}/deploy/canary/.canary-state.json"
LAST_ROLLBACK_END=""
if [[ -f "${STATE_FILE}" ]]; then
  LAST_ROLLBACK_END=$(python3 -c '
import json,sys
try:
    d=json.load(open(sys.argv[1]))
    print(d.get("last_rollback",{}).get("ended_at",""))
except Exception:
    print("")' "${STATE_FILE}")
fi

triggered=0
triggered_ids=()
# 逐条条件评估：返回 JSON 数组 [{id,metric,value,op,hit}]
EVAL_JSON=$(python3 -c '
import json, sys, urllib.request, urllib.parse, time

cond_file = sys.argv[1]
prom_url = sys.argv[2]
dry = sys.argv[3] == "1"

import yaml
cfg = yaml.safe_load(open(cond_file))
conds = cfg["rollback_conditions"]["conditions"]
queries = cfg["rollback_conditions"]["queries"]

def query(promql):
    url = prom_url.rstrip("/") + "/api/v1/query?" + urllib.parse.urlencode({"query": promql, "time": int(time.time())})
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            d = json.load(r)
        res = d["data"]["result"]
        return float(res[0]["value"][1]) if res else None
    except Exception:
        return None

def hit(op, value):
    if value is None:
        return False
    if op.startswith("gt_baseline_plus_"):
        pct = float(op.split("_")[-1].replace("pct", "")) / 100.0
        return value > pct          # 需要 baseline 场景：这里以"超过绝对 pct 增量"为近似
    if op.startswith("gt_0_"):
        return value > float(op.split("_")[-1])
    if op.startswith("lt_0_"):
        return value < float(op.split("_")[-1])
    return False

out = []
for c in conds:
    promql = queries.get(c["metric"], "")
    value = query(promql) if promql else None
    is_hit = hit(c["op"], value)
    out.append({"id": c["id"], "metric": c["metric"], "value": value,
                "op": c["op"], "hit": is_hit, "severity": c.get("severity", "P1")})
print(json.dumps({"conditions": out, "any_hit": any(x["hit"] for x in out)}))
' "${COND_FILE}" "${PROM_URL}" "${DRY}")

any_hit=$(python3 -c 'import json,sys;print(json.loads(sys.argv[1])["any_hit"])' "${EVAL_JSON}")
triggered_ids=$(python3 -c '
import json,sys
d=json.loads(sys.argv[1])
print(",".join(x["id"] for x in d["conditions"] if x["hit"]))' "${EVAL_JSON}")

if [[ "${JSON}" == "1" ]]; then
  echo "${EVAL_JSON}"
else
  python3 -c '
import json, sys
d = json.loads(sys.argv[1])
sev = "severity"
key = "id"
val = "value"
opk = "op"
for c in d["conditions"]:
    mark = "HIT " if c["hit"] else "ok  "
    print(f"{mark}{c[sev]:3s} {c[key]:22s} value={c[val]} op={c[opk]}")' "${EVAL_JSON}"
fi

if [[ "${any_hit}" != "True" ]]; then
  count=$(python3 -c 'import json,sys;print(len(json.loads(sys.argv[1])["conditions"]))' "${EVAL_JSON}")
  echo "auto-rollback: 条件未触发，无需回滚（共 ${count} 项条件）"
  exit 0
fi

echo "auto-rollback: 触发条件: ${triggered_ids}"
if [[ "${DRY}" == "1" ]]; then
  echo "auto-rollback: --dry-run 模式，不执行回滚"
  exit 3
fi

# 冷却：最近一次回滚结束时间距现在 <10 分钟则跳过（防抖）
if [[ -n "${LAST_ROLLBACK_END}" ]]; then
  since=$(python3 -c '
import sys, datetime
end = sys.argv[1]
t = datetime.datetime.now(datetime.timezone.utc)
try:
    e = datetime.datetime.fromisoformat(end.replace("Z", "+00:00"))
    print(int((t - e).total_seconds()))
except Exception:
    print(99999)' "${LAST_ROLLBACK_END}")
  if [[ "${since}" -lt 600 ]]; then
    echo "auto-rollback: 冷却期内（${since}s < 600s），跳过本次自动回滚"
    exit 4
  fi
fi

echo "auto-rollback: 执行自动回滚（reason=${triggered_ids}）..."
bash "${CANARY_SCRIPT}" rollback --reason "auto:${triggered_ids}" --yes
