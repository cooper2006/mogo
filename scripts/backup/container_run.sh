#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════
# scripts/backup/container_run.sh — 备份容器内的调度器（T096 / T101）
# ═══════════════════════════════════════════════════════════════════════
#
# 官方 mongo 镜像里没有 cron daemon，且备份进程不适合寄生在数据库容器里
# （库重启会把备份拦腰截断）。这里用纯 bash 做一个小调度循环，时区固定 UTC：
#
#   每 15 分钟      backup_mongo.sh --mode oplog     （增量，含 oplog 切片）
#   每天 02:30      backup_mongo.sh --mode full       （全量，基线）
#   每天 04:00      rotate_backups.sh                （本地 30 天 / 异地 90 天）
#   每周一 05:00    drill_recovery.sh --from-offsite （恢复演练 + RTO/RPO 实测）
#
# 和 crontab.example 里的时刻表**故意保持一致**：两种部署方式（宿主 cron /
# 容器调度器）走同一套节奏，验收清单只写一份。
#
# 用法：
#   container_run.sh                 # 常驻调度（容器 entrypoint）
#   container_run.sh --once full     # 只跑一次指定任务后退出（测试/手动补跑）
#   container_run.sh --dry-run       # 只打印本轮会做什么，不执行
#
# 环境变量：见 docker-compose.yml 的 mongo-backup 服务段。
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./lib.sh
source "${SCRIPT_DIR}/lib.sh"
# shellcheck source=./schedule.sh
source "${SCRIPT_DIR}/schedule.sh"

BACKUP_DIR="${MOGO_BACKUP_DIR:-/backups}"
STATE_DIR="${BACKUP_DIR}/.state"
LAST_SUCCESS="${BACKUP_DIR}/.last-success"

mkdir -p "${BACKUP_DIR}" "${STATE_DIR}"

usage() {
  cat <<'USAGE'
用法：container_run.sh [--once <full|oplog|rotate|drill>] [--dry-run]

不带参数时常驻，按 UTC 时刻表执行；--once 只跑一次后退出。
USAGE
}

once_job=""
dry_run=0
while (( $# > 0 )); do
  case "$1" in
    --once)
      [[ $# -ge 2 ]] || mogo_backup_die "--once 需要一个任务名：full|oplog|rotate|drill"
      once_job="$2"
      shift 2
      ;;
    --dry-run)
      dry_run=1
      shift
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      mogo_backup_die "未知参数：$1"
      ;;
  esac
done

run_job() {
  local job="$1"
  local -a cmd
  case "${job}" in
    full)
      cmd=(bash "${SCRIPT_DIR}/backup_mongo.sh" --mode full)
      ;;
    oplog)
      cmd=(bash "${SCRIPT_DIR}/backup_mongo.sh" --mode oplog)
      ;;
    rotate)
      cmd=(bash "${SCRIPT_DIR}/rotate_backups.sh")
      ;;
    drill)
      # 演练固定拿最新的异地副本；异地没配时脚本自己会失败并告警，
      # 这是有意的——演练静默跳过等于以为验证过。
      cmd=(bash "${SCRIPT_DIR}/../drill/drill_recovery.sh" --from-offsite)
      ;;
    *)
      mogo_backup_die "未知任务：${job}（可用：full|oplog|rotate|drill）"
      ;;
  esac

  if (( dry_run == 1 )); then
    mogo_backup_log "dry-run：将执行 ${cmd[*]}"
    return 0
  fi

  mogo_backup_log "开始任务 ${job}：${cmd[*]}"
  local status=0
  # 不能用 `if cmd; then ... fi` 后再取 $?：if 的退出码恒为 0，会把失败吞掉。
  "${cmd[@]}" || status=$?
  if (( status == 0 )); then
    if [[ "${job}" == "full" || "${job}" == "oplog" ]]; then
      mogo_backup_now_epoch >"${LAST_SUCCESS}"
    fi
    mogo_backup_log "任务 ${job} 完成"
    return 0
  fi
  mogo_backup_log "任务 ${job} 失败（退出码 ${status}）：备份停摆必须告警，见 docs/operations/alerting.md"
  return "${status}"
}

# 同一分钟内被循环多跑一次的去重标记（sleep 抖动/容器快照恢复都可能重入）。
claim_minute() {
  local job="$1" stamp="$2"
  local marker="${STATE_DIR}/${job}-${stamp}"
  if [[ -e "${marker}" ]]; then
    return 1
  fi
  : >"${marker}"
  # 顺手清掉两天前的标记，避免状态目录无限增长。
  find "${STATE_DIR}" -type f -mtime +2 -delete 2>/dev/null || true
  return 0
}

if [[ -n "${once_job}" ]]; then
  run_job "${once_job}"
  exit $?
fi

# 首启补一次全量：新装的部署不该空等着到凌晨 02:30 才有第一份基线备份。
if [[ ! -e "${LAST_SUCCESS}" ]] && (( dry_run == 0 )); then
  mogo_backup_log "没有历史成功记录：先跑一次全量作为基线"
  run_job full || mogo_backup_log "基线备份失败，调度继续（会按时刻表重试）"
fi

mogo_backup_log "备份调度启动：oplog 每 15 分钟 / 全量 02:30 / 轮转 04:00 / 演练周一 05:00（UTC）"

while :; do
  # 对齐到下一个整分：避免 59.7s 那种抖动把某一分钟漏掉。
  sleep "$(( 60 - $(date +%S) ))"
  now_hour="$(date -u +%H)"
  now_minute="$(date -u +%M)"
  now_dow="$(date -u +%u)"
  stamp="$(date -u +%Y%m%dT%H%M)"

  job="$(job_for_minute "${now_hour}" "${now_minute}" "${now_dow}")"
  [[ -n "${job}" ]] || continue

  claim_minute "${job}" "${stamp}" || continue
  # 单次失败不能把调度器带走：失败已经是告警信号，调度还要继续跑下一轮。
  run_job "${job}" || true
done
