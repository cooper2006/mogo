#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════
# scripts/test_rotate_backups.sh — 保留策略测试（T111）
# ═══════════════════════════════════════════════════════════════════════
#
# 覆盖：
#   1. 本地超过 30 天的归档被清理，30 天内的保留
#   2. 异地按 90 天窗口清理（同一批文件在异地存活更久）
#   3. 非归档文件（人工导出、日志）一律不碰
#   4. 保底份数：即使全部超龄，也至少留 N 份最新
#   5. 按文件名时间戳判断年龄，不按 mtime（mtime 被改不改结论）
#   6. --dry-run 只报告不删
#   7. 时间戳无法解析的文件跳过并告警
#
# 用 --now 把"现在"固定住，测试不依赖真实时钟。
# 运行：bash scripts/test_rotate_backups.sh
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
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

assert_exists() { [[ -e "$1" ]] || fail "$2: 期望存在，实际缺失（$1）"; }
assert_missing() { [[ ! -e "$1" ]] || fail "$2: 期望已删除，实际仍存在（$1）"; }

WORK="$(mktemp -d "${TMPDIR:-/tmp}/mogo-rotate-test.XXXXXX")"
export MOGO_BACKUP_DIR="${WORK}/backups"
export MOGO_BACKUP_OFFSITE_DIR="${WORK}/offsite"
mkdir -p "${MOGO_BACKUP_DIR}" "${MOGO_BACKUP_OFFSITE_DIR}"

cleanup() { rm -rf "${WORK}"; }
trap cleanup EXIT

# 用固定的"现在"：2026-10-25T00:00:00Z
NOW_ISO="20261025T000000Z"
NOW_EPOCH="$(mogo_backup_stamp_of_archive "mongo-x-full-${NOW_ISO}.archive.gz.enc")"
[[ "${NOW_EPOCH}" != "0" ]] || fail "无法把固定的 now 解析成 epoch"

make_archive() {
  local dir="$1" days_ago="$2" mode="${3:-full}" stamp_path archive
  stamp_path="$(date -u -r "$(( NOW_EPOCH - days_ago * 86400 ))" +%Y%m%dT%H%M%SZ 2>/dev/null \
    || date -u -d "@$(( NOW_EPOCH - days_ago * 86400 ))" +%Y%m%dT%H%M%SZ)"
  archive="${dir}/$(mogo_backup_archive_name mogo "${mode}" "${stamp_path}")"
  printf 'encrypted-bytes' >"${archive}"
  printf '{}' >"$(mogo_backup_manifest_name "${archive}")"
  printf 'deadbeef  %s\n' "$(basename "${archive}")" >"${archive}.sha256"
  printf '%s' "${archive}"
}

# ── 1. 本地 30 天窗口 ──────────────────────────────────────────────────
printf '== 本地 30 天 ==\n'
young="$(make_archive "${MOGO_BACKUP_DIR}" 5)"
edge="$(make_archive "${MOGO_BACKUP_DIR}" 30)"
old="$(make_archive "${MOGO_BACKUP_DIR}" 45)"
ancient="$(make_archive "${MOGO_BACKUP_DIR}" 120)"
# 非归档文件：人工导出的 dump、日志、目录
printf 'manual' >"${MOGO_BACKUP_DIR}/manual-export.archive.gz"
printf 'log' >"${MOGO_BACKUP_DIR}/backup.log"
mkdir -p "${MOGO_BACKUP_DIR}/keep-me"

: >"${WORK}/rotate.out"
MOGO_BACKUP_KEEP_MIN=1 bash "${ROOT_DIR}/scripts/backup/rotate_backups.sh" \
  --now "${NOW_EPOCH}" >"${WORK}/rotate.out" 2>&1 || fail "清理脚本失败：$(cat "${WORK}/rotate.out")"

assert_exists "${young}" "5 天前的备份应保留"
assert_exists "${edge}" "整 30 天的备份应保留（不是 > 30）"
assert_missing "${old}" "45 天前的备份应清理"
# ancient=120 天：保底 1 份最新仍应保留最新（young），ancient 应删
assert_missing "${ancient}" "120 天前的备份应清理"
assert_exists "${MOGO_BACKUP_DIR}/manual-export.archive.gz" "非归档文件不应被删"
assert_exists "${MOGO_BACKUP_DIR}/backup.log" "日志文件不应被删"
assert_exists "${MOGO_BACKUP_DIR}/keep-me" "目录不应被删"
# 清单与校验和跟着归档一起走
assert_missing "$(mogo_backup_manifest_name "${old}")" "清理归档时应同时删除清单"
assert_missing "${old}.sha256" "清理归档时应同时删除校验和"

# ── 2. 异地 90 天窗口：同一份 45 天的备份在异地必须活着 ─────────────────
printf '== 异地 90 天 ==\n'
offsite_young="$(make_archive "${MOGO_BACKUP_OFFSITE_DIR}" 40)"
offsite_old="$(make_archive "${MOGO_BACKUP_OFFSITE_DIR}" 95)"
# 异地只有 2 份候选，保底份数设 1，否则"最新 N 份"会把 95 天那份也护住
MOGO_BACKUP_KEEP_MIN=1 bash "${ROOT_DIR}/scripts/backup/rotate_backups.sh" --now "${NOW_EPOCH}" \
  >"${WORK}/rotate2.out" 2>&1 || fail "第二轮清理失败：$(cat "${WORK}/rotate2.out")"
assert_exists "${offsite_young}" "异地 40 天前的备份应保留（窗口 90 天）"
assert_missing "${offsite_old}" "异地 95 天前的备份应清理"

# ── 3. 保底份数 ────────────────────────────────────────────────────────
printf '== 保底份数 ==\n'
rm -rf "${MOGO_BACKUP_DIR}"/* "${MOGO_BACKOFFSITE_DIR:-/nonexistent}" 2>/dev/null || true
rm -rf "${MOGO_BACKUP_DIR}"
mkdir -p "${MOGO_BACKUP_DIR}"
keep1="$(make_archive "${MOGO_BACKUP_DIR}" 200)"
keep2="$(make_archive "${MOGO_BACKUP_DIR}" 300)"
keep3="$(make_archive "${MOGO_BACKUP_DIR}" 400)"
MOGO_BACKUP_KEEP_MIN=2 bash "${ROOT_DIR}/scripts/backup/rotate_backups.sh" \
  --now "${NOW_EPOCH}" --offsite-days 90 >"${WORK}/rotate3.out" 2>&1 || fail "保底轮失败"
# 最新两份（200 天、300 天）保留，最老一份（400 天）删除
assert_exists "${keep1}" "保底：最新一份必须留"
assert_exists "${keep2}" "保底：第二新必须留"
assert_missing "${keep3}" "保底之外的最老一份应清理"

# ── 4. 按文件名时间戳，不按 mtime ──────────────────────────────────────
printf '== 不看 mtime ==\n'
rm -rf "${MOGO_BACKUP_DIR}"
mkdir -p "${MOGO_BACKUP_DIR}"
stale_by_name="$(make_archive "${MOGO_BACKUP_DIR}" 60)"
fresh_by_name="$(make_archive "${MOGO_BACKUP_DIR}" 1)"
# 把两份的 mtime 都改到 1 天前：如果实现按 mtime 判断，60 天那份会被误留
touch -t 202610240000 "$stale_by_name" "$(mogo_backup_manifest_name "${stale_by_name}")" 2>/dev/null || true
touch -t 202001010000 "$fresh_by_name" "$(mogo_backup_manifest_name "${fresh_by_name}")" 2>/dev/null || true
MOGO_BACKUP_KEEP_MIN=1 bash "${ROOT_DIR}/scripts/backup/rotate_backups.sh" --now "${NOW_EPOCH}" \
  >"${WORK}/rotate4.out" 2>&1 || fail "mtime 轮失败"
assert_missing "${stale_by_name}" "60 天前的归档应按文件名时间戳清理（mtime 新也没用）"
assert_exists "${fresh_by_name}" "1 天前的归档应保留（mtime 旧也没用）"

# ── 5. dry-run ────────────────────────────────────────────────────────
printf '== dry-run ==\n'
rm -rf "${MOGO_BACKUP_DIR}"
mkdir -p "${MOGO_BACKUP_DIR}"
# 保底 1 份会护住最新的一份，所以这里要造两份：新的那份当保底，老的那份才该删
dry_keep="$(make_archive "${MOGO_BACKUP_DIR}" 1)"
dry_old="$(make_archive "${MOGO_BACKUP_DIR}" 100)"
dry_out="$(MOGO_BACKUP_KEEP_MIN=1 bash "${ROOT_DIR}/scripts/backup/rotate_backups.sh" \
  --now "${NOW_EPOCH}" --dry-run 2>&1)" || fail "dry-run 失败：${dry_out}"
case "${dry_out}" in
  *"dry-run: 将删除"*) : ;;
  *) fail "dry-run 应报告将删除的文件" ;;
esac
assert_exists "${dry_old}" "dry-run 不应真的删除"

# ── 6. 无法解析时间戳的文件跳过 ────────────────────────────────────────
printf '== 异常文件名 ==\n'
weird="${MOGO_BACKUP_DIR}/mongo-mogo-full-not-a-timestamp.archive.gz.enc"
printf 'x' >"${weird}"
weird_out="$(MOGO_BACKUP_KEEP_MIN=1 bash "${ROOT_DIR}/scripts/backup/rotate_backups.sh" \
  --now "${NOW_EPOCH}" 2>&1)" || fail "含异常文件名时不应失败"
case "${weird_out}" in
  *"无法解析时间戳"*) : ;;
  *) fail "应对异常文件名告警并跳过" ;;
esac
assert_exists "${weird}" "无法解析时间戳的文件不应被删除"

printf 'Retention behaviour is valid.\n'
