#!/usr/bin/env bash
# 024 T056 (FR-029)：数据库变更先于依赖它的代码发布的门禁。
#
# 迁移版本号（scripts/migrations/ 下 `<序号>_*.py` 的序号）必须先于依赖它的代码发布。
# 门禁：本次发布引入的最高迁移号 `migration_max` MUST >= 代码声明的迁移基线 `code_migration_base`，
#       否则阻塞发布（exit 1）。
#
# 用法：
#   deploy/cli/migration-gate.sh \
#       --migration-max 5 --code-migration-base 3 [--json]
#   deploy/cli/migration-gate.sh --release-file deploy/releases/latest.json [--json]
# 退出码：0 通过；1 代码先于迁移（阻塞）；2 参数错误。
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MIGRATION_DIR="${ROOT_DIR}/scripts/migrations"
JSON=0
MIGRATION_MAX=""
CODE_BASE=""
RELEASE_FILE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --migration-max) MIGRATION_MAX="$2"; shift 2 ;;
    --code-migration-base) CODE_BASE="$2"; shift 2 ;;
    --release-file) RELEASE_FILE="$2"; shift 2 ;;
    --json) JSON=1; shift ;;
    -h|--help) echo "用法: migration-gate.sh --migration-max N --code-migration-base M [--json]"; exit 0 ;;
    *) echo "错误: 未知参数 $1" >&2; exit 2 ;;
  esac
done

# 支持从发布记录读 migration_max / code_migration_base
if [[ -z "${MIGRATION_MAX}" || -z "${CODE_BASE}" ]]; then
  if [[ -n "${RELEASE_FILE}" && -f "${RELEASE_FILE}" ]]; then
    read MIGRATION_MAX CODE_BASE <<< "$(python3 -c '
import json,sys
d=json.load(open(sys.argv[1]))
print(d.get("migration_max",0), d.get("code_migration_base",0))' "${RELEASE_FILE}")"
  fi
fi

if [[ -z "${MIGRATION_MAX}" || -z "${CODE_BASE}" ]]; then
  echo "错误: 缺少 --migration-max / --code-migration-base（或 --release-file）" >&2
  exit 2
fi

# 扫描迁移脚本最大序号
SCANNED_MAX=0
if [[ -d "${MIGRATION_DIR}" ]]; then
  SCANNED_MAX=$(python3 -c '
import glob, os, re, sys
mx = 0
for p in glob.glob(os.path.join(sys.argv[1], "[0-9]*_*.py")):
    m = re.match(r"([0-9]+)_", os.path.basename(p))
    if m:
        mx = max(mx, int(m.group(1)))
print(mx)' "${MIGRATION_DIR}")
fi

if [[ "${SCANNED_MAX}" -gt "${MIGRATION_MAX}" ]]; then
  MIGRATION_MAX="${SCANNED_MAX}"
fi

BLOCKED=0
if [[ "${CODE_BASE}" -gt "${MIGRATION_MAX}" ]]; then
  BLOCKED=1
fi

RESULT=$(python3 -c '
import json, sys
d = {"migration_max": int(sys.argv[1]), "code_migration_base": int(sys.argv[2]), "blocked": sys.argv[3] == "1"}
d["verdict"] = "PASS 数据库变更先于代码发布（FR-029）" if not d["blocked"] else "BLOCKED 代码依赖的迁移未先发布（FR-029）"
print(json.dumps(d, ensure_ascii=False))' "${MIGRATION_MAX}" "${CODE_BASE}" "${BLOCKED}")

if [[ "${JSON}" == "1" ]]; then
  echo "${RESULT}"
else
  python3 -c '
import json, sys
d = json.loads(sys.argv[1])
print("迁移门禁 (FR-029)：迁移版本号=" + str(d["migration_max"]) + "，代码迁移基线=" + str(d["code_migration_base"]))
print("结论: " + d["verdict"])' "${RESULT}"
fi

exit "${BLOCKED}"
