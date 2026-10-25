#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════
# scripts/test_drill_recovery.sh — 恢复演练测试（T099 / T100 的行为验证）
# ═══════════════════════════════════════════════════════════════════════
#
# 覆盖：
#   1. 演练走完整链路：取备份 → 恢复到独立演练库 → 文档数 + 抽样 _id 比对
#   2. 报告落盘且含时间线、RTO/RPO 实测值、数据丢失窗口
#   3. 演练库与源库同名时拒绝（不能拿生产库做实验）
#   4. 数据不一致时演练失败（退出码非 0 且报告写 fail）
#   5. --from-offsite 走异地副本，取回耗时计入报告
#   6. RTO/RPO 超预算时报告标 no，但演练本身不算失败（预算只用于评估）
#
# 运行：bash scripts/test_drill_recovery.sh
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=./testlib/fake_mongo.sh
source "${ROOT_DIR}/scripts/testlib/fake_mongo.sh"
# shellcheck source=./backup/lib.sh
source "${ROOT_DIR}/scripts/backup/lib.sh"

fail() {
  printf 'FAIL: %s\n' "$1" >&2
  exit 1
}

assert_eq() {
  local actual="$1" expected="$2" label="$3"
  [[ "${actual}" == "${expected}" ]] || fail "${label}: expected '${expected}', got '${actual}'"
}

assert_contains() {
  local haystack="$1" needle="$2" label="$3"
  case "${haystack}" in
    *"${needle}"*) : ;;
    *) fail "${label}: 输出里找不到 '${needle}'" ;;
  esac
}

assert_file_exists() { [[ -e "$1" ]] || fail "$2: 期望存在，实际缺失（$1）"; }

WORK="$(mktemp -d "${TMPDIR:-/tmp}/mogo-drill-test.XXXXXX")"
export MOGO_BACKUP_DIR="${WORK}/backups"
export MOGO_BACKUP_OFFSITE_DIR="${WORK}/offsite"
export MOGO_DRILL_REPORT_DIR="${WORK}/reports"
export MOGO_MONGODB_URI="mongodb://mongo:27017"
export MOGO_MONGODB_DB="mogo"
export MOGO_BACKUP_PASSPHRASE="drill-test-passphrase"

cleanup() {
  fake_mongo_cleanup
  rm -rf "${WORK}"
}
trap cleanup EXIT

fake_mongo_init
PATH="${FAKE_MONGO_BIN}:${PATH}"
export PATH

backup_out="$(bash "${ROOT_DIR}/scripts/backup/backup_mongo.sh" --mode full 2>&1)" || fail "准备备份失败：${backup_out}"
ARCHIVE="$(printf '%s\n' "${backup_out}" | tail -1)"

# ── 1. 正常演练：链路 + 报告 ───────────────────────────────────────────
printf '== 正常演练 ==\n'
report_path="$(bash "${ROOT_DIR}/scripts/drill/drill_recovery.sh" --archive "${ARCHIVE}" 2>"${WORK}/drill.err" | tail -1)" \
  || fail "演练失败：$(cat "${WORK}/drill.err")"
assert_file_exists "${report_path}" "演练报告"
report="$(cat "${report_path}")"
assert_contains "${report}" "RTO 实测" "报告含 RTO 实测"
assert_contains "${report}" "RPO 实测" "报告含 RPO 实测"
assert_contains "${report}" "数据丢失窗口" "报告含数据丢失窗口"
assert_contains "${report}" "## 时间线" "报告含时间线"
assert_contains "${report}" "mogo_drill" "报告记录演练库名"
assert_contains "${report}" "文档数一致性" "报告含一致性结论"
assert_contains "${report}" "**pass**" "文档数一致性为 pass"

# 演练库独立于源库：源库数据不能被改动
source_state="$(python3 - "${FAKE_MONGO_STATE}" <<'PY'
import json, sys
state = json.load(open(sys.argv[1]))
print(",".join(f"{k}:{len(v)}" for k, v in sorted(state.get("mogo", {}).items())))
PY
)"
assert_eq "${source_state}" "posts:2,users:3" "演练不应改动源库"
drill_state="$(python3 - "${FAKE_MONGO_STATE}" <<'PY'
import json, sys
state = json.load(open(sys.argv[1]))
print(",".join(f"{k}:{len(v)}" for k, v in sorted(state.get("mogo_drill", {}).items())))
PY
)"
assert_eq "${drill_state}" "posts:2,users:3" "演练库内容与源库一致"

# 抽样 _id 比对必须是 pass（替身让两库内容一致）
assert_contains "${report}" "抽样 _id 比对（n=5） | pass" "抽样比对结论"

# ── 2. 演练库与源库同名 → 拒绝 ─────────────────────────────────────────
printf '== 同名保护 ==\n'
set +e
same_out="$(bash "${ROOT_DIR}/scripts/drill/drill_recovery.sh" --archive "${ARCHIVE}" --drill-db mogo 2>&1)"
same_status=$?
set -e
[[ "${same_status}" != "0" ]] || fail "演练库与源库同名时应失败"
assert_contains "${same_out}" "演练库不能与源库同名" "同名保护的报错"

# ── 3. 数据不一致 → 演练失败且报告为 fail ──────────────────────────────
printf '== 数据不一致 ==\n'
set +e
mismatch_out="$(FAKE_RESTORE_TRUNCATE=1 bash "${ROOT_DIR}/scripts/drill/drill_recovery.sh" \
  --archive "${ARCHIVE}" --drill-db mogo_drill_bad 2>&1)"
mismatch_status=$?
set -e
[[ "${mismatch_status}" != "0" ]] || fail "数据不一致时演练应失败"
assert_contains "${mismatch_out}" "演练失败" "不一致时的报错"

# ── 4. 异地副本演练：取回耗时进入报告 ──────────────────────────────────
printf '== 异地副本演练 ==\n'
offsite_report="$(bash "${ROOT_DIR}/scripts/drill/drill_recovery.sh" \
  --archive "$(basename "${ARCHIVE}")" --from-offsite --drill-db mogo_drill_offsite 2>"${WORK}/drill-offsite.err" | tail -1)" \
  || fail "异地演练失败：$(cat "${WORK}/drill-offsite.err")"
offsite_body="$(cat "${offsite_report}")"
assert_contains "${offsite_body}" "异地取回耗时" "报告记录异地取回耗时"
assert_contains "${offsite_body}" "mogo_drill_offsite" "报告记录异地演练库"

# ── 5. RTO/RPO 超预算：报告标 no，但演练不算失败 ───────────────────────
printf '== 预算超限 ==\n'
budget_report="$(MOGO_RTO_BUDGET_SECONDS=0 MOGO_RPO_BUDGET_SECONDS=0 \
  bash "${ROOT_DIR}/scripts/drill/drill_recovery.sh" --archive "${ARCHIVE}" \
  --drill-db mogo_drill_budget 2>"${WORK}/drill-budget.err" | tail -1)" \
  || fail "预算超限不应导致演练失败"
assert_contains "$(cat "${budget_report}")" "达标：no" "超预算时报告标 no"

# ── 6. 演练报告与 cron 的接线 ──────────────────────────────────────────
printf '== 接线检查 ==\n'
assert_contains "$(cat "${ROOT_DIR}/scripts/backup/crontab.example")" "drill_recovery.sh --from-offsite" "cron 里应有每周演练"

printf 'Recovery drill behaviour is valid.\n'
