#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════
# scripts/backup/schedule.sh — 备份时刻表（T096）
# ═══════════════════════════════════════════════════════════════════════
#
# 单独成文件是为了可测：`container_run.sh` 是常驻循环，没法在测试里
# source；把"这一分钟该跑什么"的判断抽出来，测试就能喂任意时刻断言。
#
# 时刻表（UTC，与 scripts/backup/crontab.example 保持一致）：
#   02:30      full
#   04:00      rotate
#   周一 05:00 drill
#   其余每 15 分钟 oplog

job_for_minute() {
  local hour="$1" minute="$2" dow="$3"
  # 特殊任务优先：同一分钟既满足 */15 又满足全量时，不能跑两次 oplog。
  if [[ "${minute}" == "30" && "${hour}" == "02" ]]; then
    printf 'full'
    return 0
  fi
  if [[ "${minute}" == "00" && "${hour}" == "04" ]]; then
    printf 'rotate'
    return 0
  fi
  if [[ "${minute}" == "00" && "${hour}" == "05" && "${dow}" == "1" ]]; then
    printf 'drill'
    return 0
  fi
  if (( 10#${minute} % 15 == 0 )); then
    printf 'oplog'
    return 0
  fi
  printf ''
}
