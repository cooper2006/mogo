#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════
# scripts/test_backup_schedule.sh — 备份调度测试（T096 / T109 补充）
# ═══════════════════════════════════════════════════════════════════════
#
# 覆盖：
#   1. 时刻表判定：02:30 全量、04:00 轮转、周一 05:00 演练、其余每 15 分钟增量
#   2. 特殊任务优先：02:30 不会同时被判成 oplog
#   3. 非整刻分钟不触发
#   4. `--once full` 真的产出备份并刷新 .last-success
#   5. `--once rotate` 走保留策略
#   6. 未知任务名直接失败（写错名字不能静默什么都不做）
#   7. `--dry-run --once` 不落盘
#   8. 首次启动（无 .last-success）先补一次全量基线
#
# 运行：bash scripts/test_backup_schedule.sh
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=./testlib/fake_mongo.sh
source "${ROOT_DIR}/scripts/testlib/fake_mongo.sh"
# shellcheck source=./backup/lib.sh
source "${ROOT_DIR}/scripts/backup/lib.sh"
# shellcheck source=./backup/schedule.sh
source "${ROOT_DIR}/scripts/backup/schedule.sh"

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

WORK="$(mktemp -d "${TMPDIR:-/tmp}/mogo-schedule-test.XXXXXX")"
export MOGO_BACKUP_DIR="${WORK}/backups"
export MOGO_MONGODB_URI="mongodb://mongo:27017"
export MOGO_MONGODB_DB="mogo"
export MOGO_BACKUP_PASSPHRASE="schedule-test-passphrase"

cleanup() {
  fake_mongo_cleanup
  rm -rf "${WORK}"
}
trap cleanup EXIT

fake_mongo_init
PATH="${FAKE_MONGO_BIN}:${PATH}"
export PATH

RUNNER="${ROOT_DIR}/scripts/backup/container_run.sh"

# ── 1. 时刻表判定 ──────────────────────────────────────────────────────
printf '== 时刻表 ==\n'
assert_eq "$(job_for_minute 02 30 7)" "full" "02:30 应为全量"
assert_eq "$(job_for_minute 02 30 1)" "full" "02:30 与星期无关"
assert_eq "$(job_for_minute 04 00 7)" "rotate" "04:00 应为轮转"
assert_eq "$(job_for_minute 05 00 1)" "drill" "周一 05:00 应为演练"
assert_eq "$(job_for_minute 05 00 2)" "oplog" "周二 05:00 应为增量（不是演练）"
assert_eq "$(job_for_minute 00 15 3)" "oplog" "整刻 15 分应为增量"
assert_eq "$(job_for_minute 23 45 6)" "oplog" "23:45 应为增量"
assert_eq "$(job_for_minute 00 07 3)" "" "非整刻分钟不触发"
assert_eq "$(job_for_minute 00 00 3)" "oplog" "00:00 也是整刻"

# 特殊任务优先：02:30 同时也是 */15，只能出一个任务，且是全量
assert_eq "$(job_for_minute 02 30 3)" "full" "02:30 不能被判成 oplog"

# 时刻表必须与 crontab.example 一致，否则两种部署方式节奏不同
cron_body="$(cat "${ROOT_DIR}/scripts/backup/crontab.example")"
assert_contains "${cron_body}" "*/15 * * * *" "cron 增量频率"
assert_contains "${cron_body}" "30 2 * * *" "cron 全量时刻"
assert_contains "${cron_body}" "0 4 * * *" "cron 轮转时刻"
assert_contains "${cron_body}" "0 5 * * 1" "cron 演练时刻"

# ── 2. --once full 产出备份并刷新 .last-success ────────────────────────
printf '== --once full ==\n'
[[ ! -e "${MOGO_BACKUP_DIR}/.last-success" ]] || fail "前置条件：不应已有 .last-success"
full_out="$(bash "${RUNNER}" --once full 2>&1)" || fail "全量任务失败：${full_out}"
assert_contains "${full_out}" "任务 full 完成" "全量任务完成日志"
assert_contains "${full_out}" "开始任务 full" "全量任务开始日志"
[[ -e "${MOGO_BACKUP_DIR}/.last-success" ]] || fail "全量成功后应写 .last-success"
last_success="$(cat "${MOGO_BACKUP_DIR}/.last-success")"
case "${last_success}" in
  '' | *[!0-9]*) fail ".last-success 应是 epoch 秒，实际 '${last_success}'" ;;
  *) : ;;
esac
# 健康检查阈值 7200s：刚写完就该是新鲜的
now_epoch="$(mogo_backup_now_epoch)"
age="$(( now_epoch - last_success ))"
(( age >= 0 && age < 60 )) || fail ".last-success 时间戳不合理（age=${age}s）"

# ── 3. --once oplog ────────────────────────────────────────────────────
printf '== --once oplog ==\n'
oplog_out="$(bash "${RUNNER}" --once oplog 2>&1)" || fail "增量任务失败：${oplog_out}"
assert_contains "${oplog_out}" "任务 oplog 完成" "增量任务完成日志"
# 增量备份带 --oplog，且会多出一份 oplog 模式的归档
oplog_count="$(find "${MOGO_BACKUP_DIR}" -name 'mongo-mogo-oplog-*.archive.gz.enc' | wc -l | tr -d ' ')"
[[ "${oplog_count}" == "1" ]] || fail "应产出 1 份 oplog 归档，实际 ${oplog_count}"

# ── 4. --once rotate 走保留策略 ────────────────────────────────────────
printf '== --once rotate ==\n'
rotate_out="$(bash "${RUNNER}" --once rotate 2>&1)" || fail "轮转任务失败：${rotate_out}"
assert_contains "${rotate_out}" "任务 rotate 完成" "轮转任务完成日志"
# 刚备份的文件都在窗口内，不该被删
# 注意 mogo_backup_manifest_name 返回的是完整路径，别再拼目录
latest_manifest="$(mogo_backup_manifest_name "$(mogo_backup_latest_archive "${MOGO_BACKUP_DIR}")")"
[[ -e "${latest_manifest}" ]] || fail "轮转不应删掉新鲜备份的清单（${latest_manifest}）"

# ── 5. 未知任务名 → 失败 ───────────────────────────────────────────────
printf '== 未知任务 ==\n'
set +e
unknown_out="$(bash "${RUNNER}" --once not-a-job 2>&1)"
unknown_status=$?
set -e
[[ "${unknown_status}" != "0" ]] || fail "未知任务名应失败（否则打错字会静默不备份）"
assert_contains "${unknown_out}" "未知任务" "未知任务的报错"

# 缺 --once 参数也要报错，不能当成常驻启动
set +e
bash "${RUNNER}" --once >"${WORK}/missing-arg.out" 2>&1
missing_status=$?
set -e
[[ "${missing_status}" != "0" ]] || fail "--once 缺参数应失败"

# ── 6. --dry-run 不落盘 ────────────────────────────────────────────────
printf '== dry-run ==\n'
before_count="$(find "${MOGO_BACKUP_DIR}" -name '*.enc' | wc -l | tr -d ' ')"
dry_out="$(bash "${RUNNER}" --dry-run --once full 2>&1)" || fail "dry-run 失败：${dry_out}"
assert_contains "${dry_out}" "dry-run：将执行" "dry-run 报告计划"
after_count="$(find "${MOGO_BACKUP_DIR}" -name '*.enc' | wc -l | tr -d ' ')"
assert_eq "${after_count}" "${before_count}" "dry-run 不应产出备份"

# ── 7. 首启补全量基线 ──────────────────────────────────────────────────
printf '== 首启基线 ==\n'
rm -rf "${MOGO_BACKUP_DIR}"
mkdir -p "${MOGO_BACKUP_DIR}"
# 常驻模式跑 3 秒就杀掉：只要它进过"首启补全量"分支并产出基线即可。
set +e
boot_out="$(timeout 3 bash "${RUNNER}" 2>&1 || true)"
set -e
assert_contains "${boot_out}" "先跑一次全量作为基线" "首启应补一次全量"
baseline_count="$(find "${MOGO_BACKUP_DIR}" -name 'mongo-mogo-full-*.archive.gz.enc' | wc -l | tr -d ' ')"
[[ "${baseline_count}" -ge 1 ]] || fail "首启应产出至少 1 份全量基线，实际 ${baseline_count}"
assert_contains "${boot_out}" "备份调度启动" "常驻模式应打印启动信息"

printf 'Backup schedule behaviour is valid.\n'
