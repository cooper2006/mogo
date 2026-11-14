#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════
# scripts/backup/rotate_backups.sh — 备份保留策略（T098）
# ═══════════════════════════════════════════════════════════════════════
#
# 用法：
#   scripts/backup/rotate_backups.sh [--dry-run] [--local-days N] [--offsite-days N]
#                                    [--keep-min N] [--now <ISO8601|epoch>]
#
# 策略：本地保留 30 天、异地保留 90 天（T098 要求）。三条安全规则：
#   1. 只处理文件名匹配 mongo-*.archive.gz.enc 的归档及其 .json / .sha256，
#      不碰目录里的任何其他文件（同目录可能放着人工导出的 dump）。
#   2. 年龄按**文件名里的 UTC 时间戳**判断，不看 mtime——rclone/rsync 复制会
#      改 mtime，按 mtime 清理会把刚同步过来的备份当过期删掉。
#   3. --keep-min 保底：每个目录至少留 N 份最新归档，防止时钟错乱/时间戳解析
#      失败时把备份清空。默认保留 2 份。
#
# --now 用于测试把"现在"固定住；生产用默认的系统时间。
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./lib.sh
source "${SCRIPT_DIR}/lib.sh"

MOGO_ROTATE_KEEP_MIN_DEFAULT=2

mogo_rotate_epoch_now() {
  local fixed="${1:-}"
  if [[ -z "${fixed}" ]]; then
    mogo_backup_now_epoch
    return 0
  fi
  case "${fixed}" in
    *T*Z) mogo_backup_stamp_of_archive "mongo-x-full-${fixed}.archive.gz.enc" ;;
    ''|*[!0-9]*) mogo_backup_die "--now 只接受 epoch 秒数或 20261025T031500Z 形式（收到：${fixed}）" ;;
    *) printf '%s' "${fixed}" ;;
  esac
}

# 删除 dir 下超龄归档；回显删除数量。sorted oldest-first。
mogo_rotate_dir() {
  local dir="$1" max_days="$2" now_epoch="$3" keep_min="$4" dry_run="$5"
  local archives=() path stamp age total idx keep_from=0 deleted=0

  [[ -d "${dir}" ]] || return 0
  for path in "${dir}"/mongo-*.archive.gz.enc; do
    [[ -e "${path}" ]] || continue
    stamp="$(mogo_backup_stamp_of_archive "${path}")"
    if [[ "${stamp}" == "0" ]]; then
      mogo_backup_log "WARN: 无法解析时间戳，跳过：${path}"
      continue
    fi
    archives+=("${stamp}|${path}")
  done
  total="${#archives[@]}"
  (( total > 0 )) || return 0

  # 按时间戳升序（bash 3.2 没有 mapfile/sort -V，用 sort 处理 "stamp|path" 行）
  local sorted
  sorted="$(printf '%s\n' "${archives[@]}" | sort -n -t'|' -k1,1)"
  idx=0
  # 保底：只对「第 keep_min 份之后」的归档判断过期
  if (( total > keep_min )); then
    keep_from="$(( total - keep_min ))"
  fi
  while IFS='|' read -r stamp path; do
    [[ -n "${stamp}" ]] || continue
    idx=$(( idx + 1 ))
    if (( idx > keep_from )); then
      # 落在保底区间内：无论多老都留
      continue
    fi
    age="$(( (now_epoch - stamp) / 86400 ))"
    if (( age > max_days )); then
      if (( dry_run == 1 )); then
        mogo_backup_log "dry-run: 将删除 ${path}（${age} 天 > ${max_days} 天）"
      else
        rm -f "${path}" "${path%.enc}.json" "${path}.sha256"
        mogo_backup_log "已删除 ${path}（${age} 天 > ${max_days} 天）"
      fi
      deleted=$(( deleted + 1 ))
    fi
  done <<EOF
${sorted}
EOF
  printf '%s' "${deleted}"
}

mogo_rotate_main() {
  local dry_run=0 local_days offsite_days keep_min now_arg="" now_epoch
  local_days="$(mogo_backup_local_retention_days)"
  offsite_days="$(mogo_backup_offsite_retention_days)"
  keep_min="${MOGO_BACKUP_KEEP_MIN:-${MOGO_ROTATE_KEEP_MIN_DEFAULT}}"

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --dry-run) dry_run=1; shift ;;
      --local-days) local_days="${2:-}"; shift 2 ;;
      --local-days=*) local_days="${1#*=}"; shift ;;
      --offsite-days) offsite_days="${2:-}"; shift 2 ;;
      --offsite-days=*) offsite_days="${1#*=}"; shift ;;
      --keep-min) keep_min="${2:-}"; shift 2 ;;
      --keep-min=*) keep_min="${1#*=}"; shift ;;
      --now) now_arg="${2:-}"; shift 2 ;;
      --now=*) now_arg="${1#*=}"; shift ;;
      -h|--help) sed -n '2,30p' "${BASH_SOURCE[0]}"; return 0 ;;
      *) mogo_backup_die "未知参数：$1" ;;
    esac
  done
  now_epoch="$(mogo_rotate_epoch_now "${now_arg}")"

  local backup_dir offsite_dir local_deleted=0 offsite_deleted=0
  backup_dir="$(mogo_backup_dir)"
  offsite_dir="${MOGO_BACKUP_OFFSITE_DIR:-}"

  mogo_backup_log "保留策略：本地 ${local_days} 天 / 异地 ${offsite_days} 天 / 保底 ${keep_min} 份（now=$(mogo_backup_epoch_to_iso "${now_epoch}")）"
  local_deleted="$(mogo_rotate_dir "${backup_dir}" "${local_days}" "${now_epoch}" "${keep_min}" "${dry_run}")"
  if [[ -n "${offsite_dir}" ]]; then
    offsite_deleted="$(mogo_rotate_dir "${offsite_dir}" "${offsite_days}" "${now_epoch}" "${keep_min}" "${dry_run}")"
  else
    mogo_backup_log "WARN: 未配置 MOGO_BACKUP_OFFSITE_DIR，跳过异地保留策略"
  fi
  mogo_backup_log "清理完成：本地 ${local_deleted:-0} 份、异地 ${offsite_deleted:-0} 份（dry-run=${dry_run}）"
  printf 'local=%s offsite=%s\n' "${local_deleted:-0}" "${offsite_deleted:-0}"
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  mogo_rotate_main "$@"
fi
