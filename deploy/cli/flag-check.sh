#!/usr/bin/env bash
# 024 T053 (FR-027/FR-028)：特性开关登记校验。
# 校验 deploy/flags/flags.yml 每项四项登记（owner / defaultValue / expiry / cleanupPlan）齐全，
# expiry 早于今天（UTC）则输出到期清理告警（供 CI/发布前调用）。
#
# 用法：deploy/cli/flag-check.sh [--json] [--today YYYY-MM-DD]
# 退出码：0 全部合格；1 存在缺失项或到期告警。
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FLAGS_FILE="${MOGO_FLAGS_FILE:-${ROOT_DIR}/deploy/flags/flags.yml}"
OWNERS_FILE="${MOGO_OWNERS_FILE:-${ROOT_DIR}/deploy/flags/owners.yml}"
JSON=0
TODAY=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --json) JSON=1; shift ;;
    --today) TODAY="$2"; shift 2 ;;
    -h|--help) echo "用法: flag-check.sh [--json] [--today YYYY-MM-DD]"; exit 0 ;;
    *) echo "错误: 未知参数 $1" >&2; exit 2 ;;
  esac
done

if [[ ! -f "${FLAGS_FILE}" ]]; then
  echo "错误: 找不到 ${FLAGS_FILE}" >&2
  exit 2
fi
if ! python3 -c 'import yaml' 2>/dev/null; then
  echo "错误: 需要 python3 + pyyaml" >&2
  exit 2
fi

TODAY=${TODAY:-$(date -u +%Y-%m-%d)}
RESULT=$(python3 -c '
import json, sys, yaml, datetime

path = sys.argv[1]
today = sys.argv[2]
cfg = yaml.safe_load(open(path))
flags = cfg.get("flags", [])
required = ["owner", "defaultValue", "expiry", "cleanupPlan"]
problems = []
expired = []

for idx, f in enumerate(flags, 1):
    name = f.get("name", f"#<{idx}>")
    for key in required:
        if key not in f or f[key] in (None, ""):
            problems.append({"flag": name, "issue": f"missing {key}"})
    exp = f.get("expiry")
    if exp:
        try:
            if str(exp) < today:
                expired.append({"flag": name, "expiry": str(exp), "owner": f.get("owner","")})
        except Exception:
            problems.append({"flag": name, "issue": "invalid expiry"})

# 属主存活性：owner 必须登记且 status=active（FR-028）
owners = []
try:
    oc = yaml.safe_load(open(sys.argv[3]))
    owners = oc.get("owners", [])
except Exception:
    pass
owner_status = {o.get("id"): o.get("status") for o in owners}
owner_problems = []
for f in flags:
    o = f.get("owner", "")
    if o not in owner_status:
        owner_problems.append({"flag": f.get("name", ""), "owner": o, "issue": "owner not registered"})
    elif owner_status[o] != "active":
        owner_problems.append({"flag": f.get("name", ""), "owner": o, "issue": "owner departed/not active"})

print(json.dumps({"total": len(flags), "problems": problems, "expired": expired,
                  "owner_problems": owner_problems}, ensure_ascii=False))
' "${FLAGS_FILE}" "${TODAY}" "${OWNERS_FILE}")

if [[ "${JSON}" == "1" ]]; then
  echo "${RESULT}"
else
  python3 -c '
import json, sys
d = json.loads(sys.argv[1])
print(f"特性开关登记：共 {d["total"]} 项")
if d["problems"]:
    print("缺项:")
    for p in d["problems"]:
        print(f"  FAIL {p["flag"]}: {p["issue"]}")
else:
    print("  四项登记齐全 OK")
if d.get("owner_problems"):
    print("属主存活性:")
    for o in d["owner_problems"]:
        print("  FAIL " + o["flag"] + ": owner " + o["owner"] + " " + o["issue"] + "  -> 阻塞发布")
if d["expired"]:
    print("到期告警:")
    for e in d["expired"]:
        print(f"  EXPIRED {e["flag"]} (expiry={e["expiry"]}, owner={e["owner"]})  → 需清理或更新 expiry")
else:
    print("  无到期开关 OK")' "${RESULT}"
fi

python3 -c 'import json,sys;d=json.loads(sys.argv[1]);sys.exit(1 if d["problems"] or d["expired"] or d.get("owner_problems") else 0)' "${RESULT}"
