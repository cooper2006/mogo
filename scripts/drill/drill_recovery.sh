#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════
# scripts/drill/drill_recovery.sh — 恢复演练 + 结果记录（T099 / T100）
# ═══════════════════════════════════════════════════════════════════════
#
# 用法：
#   scripts/drill/drill_recovery.sh [--archive <path>|--latest] [--from-offsite]
#                                   [--drill-db <name>] [--sample <n>]
#                                   [--report-dir <dir>] [--dry-run]
#
# 演练做的事（一条完整链路，缺一环就不算演练过）：
#   1. 取备份（本地最新，或 --from-offsite 从异地取回）
#   2. 校对校验和 → 用口令解密 → 恢复到**独立演练库**（默认 <db>_drill）
#   3. 抽样比对：源库与演练库的文档数 + 抽样 _id 集合必须一致
#   4. 记录时间线：开始/结束、RTO 实测（秒）、备份年龄（RPO 实测）、
#      数据丢失窗口（备份 finished_at → 演练开始），落一份 markdown 报告
#
# RTO/RPO 的口径（写在 docs/observability/rto-rpo.md，演练报告引用同一口径）：
#   RTO = 从"决定恢复"到"数据可对外服务"的墙钟时间；本脚本测的是
#         "拿到备份 → 恢复到可查询"这一段，不含 DNS/流量切换，切换耗时在
#         docs/runbooks/disaster-recovery.md 里另记。
#   RPO = 演练开始时"最新一次成功备份的 finished_at" 到 开始时刻 的间隔，
#         即最坏情况下会丢多久的数据。
#
# 演练库在结束时默认保留（便于事后排查），加 --drop-drill-db 才清理。
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../backup/lib.sh
source "${SCRIPT_DIR}/../backup/lib.sh"

mogo_drill_report_dir() {
  printf '%s' "${MOGO_DRILL_REPORT_DIR:-${MOGO_BACKUP_DIR:-$(mogo_backup_dir)}/../artifacts/drills}"
}

# 从清单读字段（缺失回显空）
mogo_drill_manifest_field() {
  local manifest="$1" field="$2"
  python3 - "${manifest}" "${field}" <<'PY'
import json, sys
try:
    data = json.load(open(sys.argv[1]))
except Exception:
    print("")
    raise SystemExit(0)
value = data
for part in sys.argv[2].split("."):
    if not isinstance(value, dict):
        value = None
        break
    value = value.get(part)
print("" if value is None else value)
PY
}

# 抽样 _id：源库与演练库各取 n 条，比较集合是否一致（顺序无关）。
mogo_drill_sample_ids() {
  local uri="$1" db="$2" n="$3"
  mongosh "${uri}" --quiet --eval "
    const target = db.getSiblingDB('${db}');
    target.getCollectionNames().sort().forEach(function (name) {
      const ids = target.getCollection(name).find({}, {_id: 1}).limit(${n}).toArray()
        .map(function (doc) { return String(doc._id); }).sort();
      print(name + '\\t' + ids.join(','));
    });
  "
}

mogo_drill_main() {
  local archive="" from_offsite=0 drill_db="" sample=5 report_dir="" dry_run=0
  local drop_drill_db=0
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --archive) archive="${2:-}"; shift 2 ;;
      --archive=*) archive="${1#*=}"; shift ;;
      --latest) archive=""; shift ;;
      --from-offsite) from_offsite=1; shift ;;
      --drill-db) drill_db="${2:-}"; shift 2 ;;
      --drill-db=*) drill_db="${1#*=}"; shift ;;
      --sample) sample="${2:-}"; shift 2 ;;
      --sample=*) sample="${1#*=}"; shift ;;
      --report-dir) report_dir="${2:-}"; shift 2 ;;
      --report-dir=*) report_dir="${1#*=}"; shift ;;
      --drop-drill-db) drop_drill_db=1; shift ;;
      --dry-run) dry_run=1; shift ;;
      -h|--help) sed -n '2,36p' "${BASH_SOURCE[0]}"; return 0 ;;
      *) mogo_backup_die "未知参数：$1" ;;
    esac
  done

  local dbname backup_dir uri
  dbname="$(mogo_backup_db)"
  backup_dir="$(mogo_backup_dir)"
  uri="$(mogo_backup_uri)"
  if [[ -z "${drill_db}" ]]; then
    drill_db="${dbname}_drill"
  fi
  if [[ -z "${report_dir}" ]]; then
    report_dir="$(mogo_drill_report_dir)"
  fi

  # 演练库必须是另一个库：同名"演练"等于拿生产库做实验
  if [[ "${drill_db}" == "${dbname}" ]]; then
    mogo_backup_die "演练库不能与源库同名（${drill_db}）：请用 --drill-db 指定独立库名"
  fi

  local started_epoch started_at
  started_epoch="$(mogo_backup_now_epoch)"
  started_at="$(mogo_backup_epoch_to_iso "${started_epoch}")"

  if (( dry_run == 1 )); then
    mogo_backup_log "dry-run: 归档 ${archive:-<latest>} → 演练库 ${drill_db}，报告目录 ${report_dir}"
    return 0
  fi

  mogo_backup_require_cmd openssl mongosh

  # 1) 取得备份（异地模式先取回；取回耗时计入 RTO，这是真实的恢复路径成本）
  local fetch_dir="" fetch_started="" fetch_seconds=0
  if (( from_offsite == 1 )); then
    [[ -n "${archive}" ]] || mogo_backup_die "--from-offsite 需要 --archive 指定归档名"
    fetch_dir="$(mktemp -d "${TMPDIR:-/tmp}/mogo-drill.XXXXXX")"
    mogo_backup_register_tmp "${fetch_dir}"
    trap 'mogo_backup_cleanup' EXIT
    fetch_started="$(mogo_backup_now_epoch)"
    mogo_backup_offsite_fetch "$(basename "${archive}")" "${fetch_dir}"
    fetch_seconds="$(( $(mogo_backup_now_epoch) - fetch_started ))"
    archive="${fetch_dir}/$(basename "${archive}")"
  elif [[ -z "${archive}" ]]; then
    archive="$(mogo_backup_latest_archive "${backup_dir}")" || mogo_backup_die "${backup_dir} 下没有可用备份"
  fi
  [[ -r "${archive}" ]] || mogo_backup_die "备份不可读：${archive}"
  local manifest_path
  manifest_path="$(mogo_backup_manifest_name "${archive}")"

  # 2) 备份年龄 = RPO 实测
  local backup_finished_at backup_finished_epoch rpo_seconds
  backup_finished_at=""
  if [[ -r "${manifest_path}" ]]; then
    backup_finished_at="$(mogo_drill_manifest_field "${manifest_path}" finished_at)"
  fi
  if [[ -z "${backup_finished_at}" ]]; then
    backup_finished_epoch="$(mogo_backup_stamp_of_archive "${archive}")"
  else
    backup_finished_epoch="$(mogo_drill_iso_to_epoch "${backup_finished_at}")"
  fi
  rpo_seconds="$(( started_epoch - backup_finished_epoch ))"

  mogo_backup_log "演练开始：归档 $(basename "${archive}")，备份完成于 ${backup_finished_at:-<未知>}，RPO 实测 ${rpo_seconds}s"

  # 3) 恢复（复用 restore 脚本，保证演练路径与真实恢复路径是同一份代码）
  local restore_started restore_seconds consistency="unknown"
  restore_started="$(mogo_backup_now_epoch)"
  if bash "${SCRIPT_DIR}/../backup/restore_mongo.sh" --archive "${archive}" \
      --target-db "${drill_db}" --drop --yes; then
    consistency="pass"
  else
    consistency="fail"
  fi
  restore_seconds="$(( $(mogo_backup_now_epoch) - restore_started ))"

  # 4) 抽样比对（独立于文档数校验：文档数对得上但内容错位是真事故）
  local sample_status="skipped"
  if [[ "${consistency}" == "pass" ]]; then
    local source_ids drill_ids
    source_ids="$(mogo_drill_sample_ids "${uri}" "${dbname}" "${sample}")"
    drill_ids="$(mogo_drill_sample_ids "${uri}" "${drill_db}" "${sample}")"
    if [[ "${source_ids}" == "${drill_ids}" ]]; then
      sample_status="pass"
    else
      sample_status="fail"
      consistency="fail"
      mogo_backup_log "抽样 _id 不一致：源库与演练库同集合抽样结果不同"
    fi
  fi

  local finished_epoch finished_at rto_seconds
  finished_epoch="$(mogo_backup_now_epoch)"
  finished_at="$(mogo_backup_epoch_to_iso "${finished_epoch}")"
  rto_seconds="$(( finished_epoch - started_epoch ))"

  local rto_budget="${MOGO_RTO_BUDGET_SECONDS:-1800}"
  local rpo_budget="${MOGO_RPO_BUDGET_SECONDS:-900}"
  local rto_ok="no" rpo_ok="no"
  (( rto_seconds <= rto_budget )) && rto_ok="yes"
  (( rpo_seconds <= rpo_budget )) && rpo_ok="yes"

  # 5) 报告（T100：时间线 + RTO/RPO 实测 + 数据丢失窗口）
  mkdir -p "${report_dir}"
  local report_path
  report_path="${report_dir}/$(date -u +%Y%m%dT%H%M%SZ)-drill.md"
  cat >"${report_path}" <<EOF
# 恢复演练报告 — ${started_at}

| 项 | 值 |
|---|---|
| 备份归档 | \`$(basename "${archive}")\` |
| 备份完成时间 | ${backup_finished_at:-未知} |
| 演练目标库 | \`${drill_db}\` |
| 异地取回耗时 | ${fetch_seconds}s |
| 恢复耗时（含校验） | ${restore_seconds}s |
| 演练总耗时（RTO 实测） | **${rto_seconds}s**（预算 ${rto_budget}s，达标：${rto_ok}） |
| 备份年龄（RPO 实测） | **${rpo_seconds}s**（预算 ${rpo_budget}s，达标：${rpo_ok}） |
| 数据丢失窗口 | ${started_at} 之前 ${rpo_seconds}s 内的写入（按最新备份计） |
| 文档数一致性 | ${consistency} |
| 抽样 _id 比对（n=${sample}） | ${sample_status} |

## 时间线

- ${started_at} 演练开始
- ${backup_finished_at:-未知} 备份完成（数据基线）
- $(mogo_backup_epoch_to_iso "${restore_started}") 开始恢复到 \`${drill_db}\`（异地取回 ${fetch_seconds}s 已在此之前完成）
- ${finished_at} 恢复 + 校验结束，RTO 实测 ${rto_seconds}s

## 结论

- 数据一致性：**${consistency}**（文档数逐集合比对 + 抽样 _id 比对）
- RTO ${rto_seconds}s ${rto_ok} · RPO ${rpo_seconds}s ${rpo_ok}（阈值见 docs/observability/rto-rpo.md）
- 数据丢失窗口：恢复点之后、故障之前的写入不可回收；如需更小窗口，见 rto-rpo.md「oplog 回放」一节。
EOF

  mogo_backup_log "演练报告：${report_path}"

  if (( drop_drill_db == 1 )); then
    mongosh "${mogo_backup_uri_with_db "${uri}" "${drill_db}"}" --quiet --eval 'db.dropDatabase()' >/dev/null
    mogo_backup_log "演练库 ${drill_db} 已清理"
  fi

  if [[ "${consistency}" != "pass" ]]; then
    mogo_backup_die "演练失败：数据一致性校验未通过（报告：${report_path}）"
  fi
  printf '%s\n' "${report_path}"
}

# ISO8601（...Z）→ epoch，兼容 BSD/GNU date
mogo_drill_iso_to_epoch() {
  local iso="$1"
  if date -u -j -f '%Y-%m-%dT%H:%M:%SZ' "${iso}" +%s >/dev/null 2>&1; then
    date -u -j -f '%Y-%m-%dT%H:%M:%SZ' "${iso}" +%s
  elif date -u -d "${iso}" +%s >/dev/null 2>&1; then
    date -u -d "${iso}" +%s
  else
    printf '0'
  fi
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  mogo_drill_main "$@"
fi
