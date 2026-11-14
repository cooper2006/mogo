#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════
# scripts/drill/drill_az_failover.sh — 跨 AZ 故障切换演练（T112）
# ═══════════════════════════════════════════════════════════════════════
#
# 「单个 AZ 挂掉，多久能自动接上」是没法用单元测试证明的，只能真的把节点
# 拿掉一次。这个脚本做的是**可控的**一次：
#
#   1. 记下目标服务的当前副本分布（每节点各几个）
#   2. `docker node update --availability drain <node>` —— 模拟该 AZ 失联
#      （drain 会驱逐该节点上的副本，但不销毁换机，可回滚；比真关机安全）
#   3. 轮询服务副本数，直到所有任务 Running 且分布在存活节点上
#   4. 记录耗时 = RTO 实测，与预算（默认 1800s = 30min）比较
#   5. 可选 `--restore` 把节点改回 active
#
# 需要 Docker Swarm 与真实双节点环境；单机没有可切换的节点，脚本会明确
# 告诉你「这一项只能上线后演练」，而不是假装通过。
#
# 用法：
#   drill_az_failover.sh --node az-a-node-1 --service mogo_chat-api \
#     --restore --report-dir /var/log/mogo/drills
#
#   drill_az_failover.sh --dry-run          # 只打印将执行的命令
#
# 退出码：0 切换成功且 RTO 达标；1 切换失败；2 环境不具备（无 docker/swarm）
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
# shellcheck source=../backup/lib.sh
source "${ROOT_DIR}/scripts/backup/lib.sh"

NODE=""
SERVICE=""
TIMEOUT="${MOGO_AZ_FAILOVER_TIMEOUT_SECONDS:-1800}"
RESTORE=0
DRY_RUN=0
REPORT_DIR="${MOGO_DRILL_REPORT_DIR:-${ROOT_DIR}/artifacts/drills}"

usage() {
  cat <<'USAGE'
用法：drill_az_failover.sh [选项]

  --node <节点名>        要模拟失联的节点（docker node ls 里的名字）
  --service <服务名>     目标服务（docker service ls 里的名字），可重复或用逗号分隔
  --timeout <秒>         切换超时，默认 1800（= RTO 预算 30 分钟）
  --restore              演练后把节点恢复成 active
  --report-dir <目录>    报告落盘位置
  --dry-run              只打印将执行的命令
  -h, --help
USAGE
}

while (( $# > 0 )); do
  case "$1" in
    --node) NODE="${2:?--node 需要值}"; shift 2 ;;
    --service) SERVICE="${SERVICE:+${SERVICE},}${2:?--service 需要值}"; shift 2 ;;
    --timeout) TIMEOUT="${2:?--timeout 需要值}"; shift 2 ;;
    --restore) RESTORE=1; shift ;;
    --report-dir) REPORT_DIR="${2:?--report-dir 需要值}"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h | --help) usage; exit 0 ;;
    *) mogo_backup_die "未知参数：$1" ;;
  esac
done

[[ -n "${NODE}" ]] || mogo_backup_die "必须指定 --node"
[[ -n "${SERVICE}" ]] || mogo_backup_die "必须指定 --service"

main() {
  if (( DRY_RUN == 1 )); then
    mogo_backup_log "dry-run：将 drain 节点 ${NODE}"
    mogo_backup_log "dry-run：将等待服务 ${SERVICE} 在 ${TIMEOUT}s 内恢复"
    (( RESTORE == 1 )) && mogo_backup_log "dry-run：将把 ${NODE} 恢复为 active"
    return 0
  fi

  # 环境不具备时**明确失败**：假通过比不跑更危险——它会让人以为演练过了。
  if ! command -v docker >/dev/null 2>&1; then
    mogo_backup_log "环境不具备：没有 docker CLI。跨 AZ 切换只能在上线后的双节点环境演练，"
    mogo_backup_log "手工步骤见 ${ROOT_DIR}/docs/runbooks/disaster-recovery.md「跨 AZ 拓扑」。"
    return 2
  fi
  # 注意别用 `grep -q active` 判：docker 的 "inactive" 里也含 "active"。
  local swarm_state
  swarm_state="$(docker info --format '{{.Swarm.LocalNodeState}}' 2>/dev/null || true)"
  if [[ "${swarm_state}" != "active" ]]; then
    mogo_backup_log "环境不具备：本节点不在活跃的 Swarm 里（状态：${swarm_state:-未知}）；"
    mogo_backup_log "单机 compose 没有可切换的节点，手工步骤见 docs/runbooks/disaster-recovery.md"
    return 2
  fi

  mkdir -p "${REPORT_DIR}"
  local started_at started_epoch finished_at finished_epoch rto_seconds budget_ok
  started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  started_epoch="$(mogo_backup_now_epoch)"
  local -a services
  IFS=',' read -r -a services <<<"${SERVICE}"

  mogo_backup_log "开始演练：drain 节点 ${NODE}，目标服务 ${SERVICE}"

  # 1) 记录切换前的分布，报告里要能看出「切换前主备在不同的节点上」。
  local before
  before="$(docker service ps --format '{{.Name}}\t{{.Node}}\t{{.CurrentState}}' ${services[*]} 2>&1 | head -40 || true)"

  # 2) 模拟该 AZ 失联
  docker node update --availability drain "${NODE}" >/dev/null
  mogo_backup_log "节点 ${NODE} 已 drain（模拟该 AZ 失联）"

  # 3) 等所有副本恢复到 Running；超时即判定切换失败
  local status=0 elapsed=0 pending
  while :; do
    pending="$(docker service ls --format '{{.Name}}\t{{.Replicas}}' \
      | awk -v names="${services[*]}" 'BEGIN{split(names, a, " "); for (i in a) want[a[i]]=1}
        want[$1] { split($2, r, "/"); if (r[1] != r[2]) print $1 }')"
    if [[ -z "${pending}" ]]; then
      break
    fi
    elapsed="$(( $(mogo_backup_now_epoch) - started_epoch ))"
    if (( elapsed > TIMEOUT )); then
      mogo_backup_log "切换超时：${elapsed}s 后仍不完整（${pending}）"
      status=1
      break
    fi
    sleep 5
  done

  finished_epoch="$(mogo_backup_now_epoch)"
  finished_at="$(mogo_backup_epoch_to_iso "${finished_epoch}")"
  rto_seconds="$(( finished_epoch - started_epoch ))"
  budget_ok="no"
  (( status == 0 && rto_seconds <= TIMEOUT )) && budget_ok="yes"

  local after
  after="$(docker service ps --format '{{.Name}}\t{{.Node}}\t{{.CurrentState}}' ${services[*]} 2>&1 | head -40 || true)"

  # 4) 报告
  local report_path
  report_path="${REPORT_DIR}/$(date -u +%Y%m%dT%H%M%SZ)-az-failover.md"
  cat >"${report_path}" <<EOF
# 跨 AZ 故障切换演练 — ${started_at}

| 项 | 值 |
|---|---|
| 失联节点 | \`${NODE}\` |
| 目标服务 | ${SERVICE} |
| 开始时间 | ${started_at} |
| 结束时间 | ${finished_at} |
| **RTO 实测** | **${rto_seconds}s**（预算 ${TIMEOUT}s，达标：${budget_ok}） |
| 切换结果 | $([[ "${status}" == "0" ]] && printf 'pass' || printf 'fail') |

## 时间线

- ${started_at} 演练开始，记录副本分布
- $(mogo_backup_epoch_to_iso "$(( started_epoch + 0 ))") 节点 drain（该 AZ 视为失联）
- ${finished_at} 所有目标服务副本恢复 Running（或超时放弃）

## 切换前副本分布

\`\`\`
${before}
\`\`\`

## 切换后副本分布

\`\`\`
${after}
\`\`\`

## 结论

- RTO ${rto_seconds}s ${budget_ok}（目标 ≤ 30min，见 docs/observability/rto-rpo.md）
- 若切换失败，检查：节点标签 \`mogo.data\`/\`mogo.az\` 是否打全、副本是否因数据卷
  不可跨节点而无法迁移（有状态服务本就不该跨节点漂移）、镜像是否已在存活节点上。
- 演练会临时降低冗余，请在业务低峰执行，并用 \`--restore\` 恢复节点。
EOF

  mogo_backup_log "演练报告：${report_path}"

  if (( RESTORE == 1 )); then
    docker node update --availability active "${NODE}" >/dev/null
    mogo_backup_log "节点 ${NODE} 已恢复 active"
  else
    mogo_backup_log "提醒：${NODE} 仍处于 drain 状态，用完请手动改回 active"
  fi

  printf '%s\n' "${report_path}"
  return "${status}"
}

main "$@"
