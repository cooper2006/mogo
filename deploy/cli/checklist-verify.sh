#!/usr/bin/env bash
# 024 T064 (FR-033)：发布检查单"执行人 + 结论"机器校验。
# 任一项执行人为空或结论为空（含"未通过"/空白）→ exit 1（视为未通过）。
#
# 用法：deploy/cli/checklist-verify.sh [--checklist <path>] [--json]
# 默认检查单：docs/release-checklist-self-hosted.md
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CHECKLIST="${ROOT_DIR}/docs/release-checklist-self-hosted.md"
JSON=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --checklist) CHECKLIST="$2"; shift 2 ;;
    --json) JSON=1; shift ;;
    -h|--help) echo "用法: checklist-verify.sh [--checklist <path>] [--json]"; exit 0 ;;
    *) echo "错误: 未知参数 $1" >&2; exit 2 ;;
  esac
done

if [[ ! -f "${CHECKLIST}" ]]; then
  echo "错误: 找不到 ${CHECKLIST}" >&2
  exit 2
fi

RESULT=$(python3 -c '
import json, re, sys
path = sys.argv[1]
items = []
pat = re.compile(r"^- \[ \] (C\d+)\s*\|\s*(.*?)\s*\|\s*执行人:\s*(.*?)\s*\|\s*结论:\s*(.*?)\s*\|\s*理由:\s*(.*?)\s*$")
with open(path, encoding="utf-8") as fh:
    for line in fh:
        m = pat.match(line.rstrip("\n"))
        if m:
            cid, desc, owner, verdict, reason = m.groups()
            missing = []
            if not owner.strip():
                missing.append("executor")
            if not verdict.strip() or verdict.strip() == "未通过":
                missing.append("verdict")
            if verdict.strip() == "不适用" and not reason.strip():
                missing.append("reason-for-na")
            items.append({"id": cid, "desc": desc, "owner": owner.strip(), "verdict": verdict.strip(),
                          "reason": reason.strip(), "missing": missing})
print(json.dumps({"total": len(items), "items": items}, ensure_ascii=False))' "${CHECKLIST}")

if [[ "${JSON}" == "1" ]]; then
  echo "${RESULT}"
else
  python3 -c '
import json, sys
d = json.loads(sys.argv[1])
print("发布检查单校验 (FR-033)：共 " + str(d["total"]) + " 项")
fail = 0
for it in d["items"]:
    if it["missing"]:
        fail += 1
        print("  FAIL " + it["id"] + ": 缺 " + ", ".join(it["missing"]))
    else:
        print("  OK   " + it["id"] + ": " + it["verdict"] + (("（" + it["reason"] + "）") if it["verdict"] == "不适用" else ""))
print("结论: " + ("PASS 全部项执行人与结论非空" if fail == 0 else "FAIL " + str(fail) + " 项未通过（空值视为未通过）"))' "${RESULT}"
fi

python3 -c 'import json,sys;d=json.loads(sys.argv[1]);sys.exit(1 if any(it["missing"] for it in d["items"]) else 0)' "${RESULT}"
