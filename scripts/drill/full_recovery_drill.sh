#!/usr/bin/env bash
#
# full_recovery_drill.sh — 023 T118 端到端恢复验证（备份 → 恢复 → 一致性校验 → 服务切换）
#
# 与 drill_recovery.sh 的分工
# --------------------------
# drill_recovery.sh 只负责「拿到一个归档之后的恢复与校验」。它假设备份已经存在，
# 所以它验证不了「备份这一环是否还在正常工作」。本脚本把三环串起来：
#
#   1. backup_mongo.sh --mode full        产出真实归档（含清单与校验和）
#   2. drill_recovery.sh --archive <最新> 恢复到演练库 + 文档数一致性 + 抽样比对
#   3. 服务切换检查                        恢复后的库能否让服务通过就绪探针
#
# 每一步都用**生产同一个脚本**，不另写一套逻辑——演练路径与真实恢复路径不同，
# 演练就失去意义（这是 T118 的核心要求）。
#
# 退出码: 0 通过 / 1 断言失败 / 2 环境不具备
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
# shellcheck source=../backup/lib.sh
source "${SCRIPT_DIR}/../backup/lib.sh"

DB_NAME=""
DRILL_DB=""
API_URL="${MOGO_CHAT_API_URL:-}"
SAMPLE=5
REPORT_DIR=""
DRY_RUN=0
KEEP_DRILL_DB=0
FAILURES=0
declare -a RESULTS=()

usage() {
  sed -n '2,30p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
  cat <<'USAGE'

参数:
  --db NAME           源库名（默认 $MOGO_MONGO_DB 或 mogo）
  --drill-db NAME     演练库名（默认 <db>_drill，不能与源库同名）
  --api-url URL       恢复后做就绪检查的服务地址（缺省则跳过切换检查）
  --sample N          每集合抽样比对文档数（默认 5）
  --report-dir DIR    报告目录（默认 <备份目录>/../artifacts/drills）
  --keep-drill-db     演练结束不删演练库
  --dry-run           只打印将执行的步骤
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --db) DB_NAME="${2:-}"; shift 2 ;;
    --drill-db) DRILL_DB="${2:-}"; shift 2 ;;
    --api-url) API_URL="${2:-}"; shift 2 ;;
    --sample) SAMPLE="${2:-}"; shift 2 ;;
    --report-dir) REPORT_DIR="${2:-}"; shift 2 ;;
    --keep-drill-db) KEEP_DRILL_DB=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "未知参数：$1" >&2; usage >&2; exit 2 ;;
  esac
done

log() { printf '[recovery-drill] %s\n' "$*"; }

record() {
  RESULTS+=("$1|$2|$3")
  case "$1" in
    pass) log "PASS  $2 — $3" ;;
    fail) log "FAIL  $2 — $3"; FAILURES=$((FAILURES + 1)) ;;
    skip) log "SKIP  $2 — $3" ;;
  esac
}

die() { log "错误：$*"; exit 2; }

for tool in bash openssl; do
  command -v "${tool}" >/dev/null 2>&1 || die "缺少命令 ${tool}"
done

if [[ -n "${DB_NAME}" ]]; then
  export MOGO_MONGO_DB="${DB_NAME}"
fi
DB_NAME="$(mogo_backup_db)"
BACKUP_DIR="$(mogo_backup_dir)"
if [[ -z "${DRILL_DB}" ]]; then
  DRILL_DB="${DB_NAME}_drill"
fi
if [[ "${DRILL_DB}" == "${DB_NAME}" ]]; then
  die "演练库不能与源库同名（${DRILL_DB}）"
fi
if [[ -z "${REPORT_DIR}" ]]; then
  # 与 drill_recovery.sh 的默认口径保持一致：<备份目录>/../artifacts/drills
  REPORT_DIR="${MOGO_DRILL_REPORT_DIR:-$(cd "${BACKUP_DIR}/.." 2>/dev/null && pwd || echo "${BACKUP_DIR}/..")/artifacts/drills}"
fi
mkdir -p "${REPORT_DIR}"

log "源库=${DB_NAME} 演练库=${DRILL_DB} 备份目录=${BACKUP_DIR}"

if [[ "${DRY_RUN}" -eq 1 ]]; then
  log "dry-run: 将执行 1) backup_mongo.sh --mode full"
  log "dry-run: 将执行 2) drill_recovery.sh --archive <最新> --drill-db ${DRILL_DB} --sample ${SAMPLE}"
  log "dry-run: 将执行 3) 就绪检查 ${API_URL:-（未提供 --api-url，将跳过）}"
  exit 0
fi

START_EPOCH="$(date -u +%s)"

# ───────────────────── 阶段 1：真实全量备份 ─────────────────────

BACKUP_OUT="${REPO_ROOT}/artifacts/recovery-drill/.backup.$$.log"
mkdir -p "$(dirname "${BACKUP_OUT}")"
if bash "${SCRIPT_DIR}/../backup/backup_mongo.sh" --mode full >"${BACKUP_OUT}" 2>&1; then
  record pass "阶段 1 全量备份" "backup_mongo.sh --mode full 成功"
else
  record fail "阶段 1 全量备份" "backup_mongo.sh 失败（详见 ${BACKUP_OUT}）"
fi

ARCHIVE="$(mogo_backup_latest_archive "${BACKUP_DIR}" || true)"
if [[ -n "${ARCHIVE}" && -f "${ARCHIVE}" ]]; then
  record pass "取到最新归档" "$(basename "${ARCHIVE}")"
else
  record fail "取到最新归档" "备份目录 ${BACKUP_DIR} 里没有 mongo-*.archive.gz.enc"
fi

MANIFEST="$(mogo_backup_manifest_name "${ARCHIVE}" 2>/dev/null || true)"
if [[ -n "${MANIFEST}" && -f "${MANIFEST}" ]]; then
  record pass "归档带清单" "$(basename "${MANIFEST}")"
else
  record fail "归档带清单" "缺少同名 .json 清单（无法校验 RPO）"
fi

# ───────────────────── 阶段 2：恢复 + 一致性校验 ─────────────────────

if [[ "${FAILURES}" -gt 0 ]]; then
  record skip "阶段 2 恢复演练" "阶段 1 未通过，跳过（避免在坏归档上做无意义恢复）"
else
  DRILL_OUT="${REPO_ROOT}/artifacts/recovery-drill/.drill.$$.log"
  DRILL_ARGS=(--archive "${ARCHIVE}" --drill-db "${DRILL_DB}" --sample "${SAMPLE}" --report-dir "${REPORT_DIR}")
  if bash "${SCRIPT_DIR}/drill_recovery.sh" "${DRILL_ARGS[@]}" >"${DRILL_OUT}" 2>&1; then
    record pass "阶段 2 恢复演练" "drill_recovery.sh 成功"
  else
    record fail "阶段 2 恢复演练" "drill_recovery.sh 失败（详见 ${DRILL_OUT}）"
  fi

  # 演练脚本把日志和报告路径一起写到 stdout，最后一行才是路径（已启用 pipefail）
  DRILL_REPORT="$(tail -1 "${DRILL_OUT}" 2>/dev/null || true)"
  if [[ -n "${DRILL_REPORT}" && -f "${DRILL_REPORT}" ]]; then
    record pass "生成演练报告" "$(basename "${DRILL_REPORT}")"
  else
    record fail "生成演练报告" "没有拿到报告路径（最后一行：${DRILL_REPORT}）"
  fi

  RTO_LINE="$(grep -F 'RTO 实测' "${DRILL_REPORT}" 2>/dev/null | head -1 || true)"
  RPO_LINE="$(grep -F 'RPO 实测' "${DRILL_REPORT}" 2>/dev/null | head -1 || true)"
  if [[ -n "${RTO_LINE}" && -n "${RPO_LINE}" ]]; then
    record pass "记录 RTO/RPO" "RTO/RPO 已写入演练报告"
  else
    record fail "记录 RTO/RPO" "演练报告里找不到 RTO/RPO 实测行"
  fi

  CONSISTENCY="$(grep -F '文档数一致性' "${DRILL_REPORT}" 2>/dev/null | head -1 || true)"
  if printf '%s' "${CONSISTENCY}" | grep -q 'pass'; then
    record pass "数据一致性" "文档数一致性通过"
  else
    record fail "数据一致性" "文档数一致性未通过（${CONSISTENCY:-无该项}）"
  fi

  if [[ "${KEEP_DRILL_DB}" -eq 0 ]]; then
    record skip "清理演练库" "由 drill_recovery.sh 的默认行为处理；如需保留请加 --keep-drill-db"
  else
    record skip "清理演练库" "--keep-drill-db：保留 ${DRILL_DB}"
  fi
fi

# ───────────────────── 阶段 3：服务切换检查 ─────────────────────

if [[ -z "${API_URL}" ]]; then
  record skip "阶段 3 服务切换检查" "未提供 --api-url"
else
  READY_CODE="$(curl -sS -m 10 -o /dev/null -w '%{http_code}' "${API_URL%/}/ready" 2>/dev/null || echo 000)"
  if [[ "${READY_CODE}" == "200" ]]; then
    record pass "阶段 3 服务切换检查" "${API_URL%/}/ready → 200（恢复后服务可服务）"
  else
    record fail "阶段 3 服务切换检查" "${API_URL%/}/ready → ${READY_CODE}"
  fi
fi

END_EPOCH="$(date -u +%s)"
TOTAL_SECONDS=$((END_EPOCH - START_EPOCH))

# ─────────────────────────────── 报告 ───────────────────────────────

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
REPORT="${REPORT_DIR}/${STAMP}-full-recovery.md"
{
  echo "# 端到端恢复演练报告"
  echo
  echo "- 时间：$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "- 源库：\`${DB_NAME}\`　演练库：\`${DRILL_DB}\`"
  echo "- 归档：\`$(basename "${ARCHIVE:-无}")\`"
  echo "- 总耗时：${TOTAL_SECONDS}s"
  echo "- 结果：$([[ "${FAILURES}" -eq 0 ]] && echo "全部通过" || echo "${FAILURES} 项失败")"
  echo
  echo "| 结果 | 检查项 | 说明 |"
  echo "| --- | --- | --- |"
  for row in "${RESULTS[@]}"; do
    IFS='|' read -r verdict name detail <<<"${row}"
    case "${verdict}" in
      pass) mark="pass" ;;
      fail) mark="**fail**" ;;
      *) mark="skip" ;;
    esac
    echo "| ${mark} | ${name} | ${detail//|/\\|} |"
  done
  echo
  echo "## 注意"
  echo
  echo "- 本脚本验证的是「备份 → 恢复 → 校验」这条脚本链路；**服务切换**只做就绪探针验证。"
  echo "- 真实的主备切换（VIP 漂移/节点 drain）见 \`deploy/keepalived/README.md\` 与"
  echo "  \`scripts/drill/drill_az_failover.sh\`（非 Swarm 环境下返回 2，不产生通过结论）。"
} >"${REPORT}"

log "报告：${REPORT}"

if [[ "${FAILURES}" -gt 0 ]]; then
  log "${FAILURES} 项断言失败"
  exit 1
fi
log "端到端恢复演练通过（总耗时 ${TOTAL_SECONDS}s）"
exit 0
