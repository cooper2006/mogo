#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════
# scripts/backup/restore_mongo.sh — MongoDB 从备份恢复（T097）
# ═══════════════════════════════════════════════════════════════════════
#
# 用法：
#   scripts/backup/restore_mongo.sh [--archive <path>|--latest] [--from-offsite]
#                                   [--target-db <name>] [--drop] [--yes]
#                                   [--consistency-only] [--dry-run]
#
#   --archive       指定 .archive.gz.enc；默认取 MOGO_BACKUP_DIR 里最新一份
#   --from-offsite  先从异地副本取回再恢复（证明"只靠异地也能恢复"）
#   --target-db     恢复到的库名（演练/校验时用别的库名，避免污染源库）
#   --drop          先删掉目标库里的同名集合（默认不删，冲突即失败）
#   --yes           跳过破坏性操作确认
#   --consistency-only   只跑一致性校验，不写库（对已恢复的库做复核）
#
# 安全约束（都是踩过的真实事故形态）：
#   * 默认拒绝覆盖已有集合：mongorestore 不加 --drop 时对已存在集合是**合并**，
#     合并后文档数变多、看起来"恢复成功"却混入了旧数据。
#   * 恢复前用 openssl 解出全量到 /dev/null 验证口令；口令错时报的是
#     "bad decrypt"，不是让 mongorestore 读半个文件。
#   * 校验和必须在解密前核对：先校验再解密，避免把损坏的密文恢复进库。
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./lib.sh
source "${SCRIPT_DIR}/lib.sh"

# 从清单里取某个 "collections": [...] 的文档数，用于对比。
# 输入："name\tcount" 行；输出同样的行，缺失的集合补 0。
mogo_restore_compare_counts() {
  local expected="$1" actual="$2" name count actual_count status=0
  local expected_names="" actual_names=""
  expected_names="$(printf '%s\n' "${expected}" | awk -F'\t' 'NF{print $1}')"
  actual_names="$(printf '%s\n' "${actual}" | awk -F'\t' 'NF{print $1}')"

  while IFS= read -r name; do
    [[ -n "${name}" ]] || continue
    count="$(printf '%s\n' "${expected}" | awk -F'\t' -v n="${name}" '$1==n{print $2}' | head -1)"
    actual_count="$(printf '%s\n' "${actual}" | awk -F'\t' -v n="${name}" '$1==n{print $2}' | head -1)"
    if [[ "${count}" != "${actual_count:-0}" ]]; then
      mogo_backup_log "不一致：集合 ${name} 期望 ${count} 实际 ${actual_count:-0}"
      status=1
    fi
  done <<EOF
${expected_names}
EOF

  while IFS= read -r name; do
    [[ -n "${name}" ]] || continue
    if ! printf '%s\n' "${expected_names}" | grep -qxF "${name}"; then
      mogo_backup_log "不一致：目标库多出集合 ${name}（备份里没有）"
      status=1
    fi
  done <<EOF
${actual_names}
EOF
  return "${status}"
}

mogo_restore_mongo_main() {
  local archive="" from_offsite=0 target_db="" drop=0 assume_yes=0
  local consistency_only=0 dry_run=0
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --archive) archive="${2:-}"; shift 2 ;;
      --archive=*) archive="${1#*=}"; shift ;;
      --latest) archive=""; shift ;;
      --from-offsite) from_offsite=1; shift ;;
      --target-db) target_db="${2:-}"; shift 2 ;;
      --target-db=*) target_db="${1#*=}"; shift ;;
      --drop) drop=1; shift ;;
      --yes) assume_yes=1; shift ;;
      --consistency-only) consistency_only=1; shift ;;
      --dry-run) dry_run=1; shift ;;
      -h|--help) sed -n '2,32p' "${BASH_SOURCE[0]}"; return 0 ;;
      *) mogo_backup_die "未知参数：$1" ;;
    esac
  done

  local backup_dir dbname
  backup_dir="$(mogo_backup_dir)"
  dbname="$(mogo_backup_db)"

  local fetch_dir=""
  if (( from_offsite == 1 )) && [[ -z "${archive}" ]]; then
    mogo_backup_die "--from-offsite 需要配合 --archive 指定要取回的归档名（避免误取最新）"
  fi
  if (( from_offsite == 1 )); then
    fetch_dir="$(mktemp -d "${TMPDIR:-/tmp}/mogo-offsite.XXXXXX")"
    mogo_backup_register_tmp "${fetch_dir}"
    mogo_backup_offsite_fetch "$(basename "${archive}")" "${fetch_dir}"
    archive="${fetch_dir}/$(basename "${archive}")"
  elif [[ -z "${archive}" ]]; then
    archive="$(mogo_backup_latest_archive "${backup_dir}")" || mogo_backup_die "${backup_dir} 下没有可用备份"
    mogo_backup_log "未指定 --archive，使用最新备份：$(basename "${archive}")"
  fi
  [[ -r "${archive}" ]] || mogo_backup_die "备份不可读：${archive}"

  local manifest_path
  manifest_path="$(mogo_backup_manifest_name "${archive}")"
  [[ -r "${manifest_path}" ]] || mogo_backup_log "WARN: 缺少清单 ${manifest_path}，一致性校验只能比对目标库自洽性"
  if [[ -z "${target_db}" ]]; then
    target_db="${dbname}"
  fi

  if (( dry_run == 1 )); then
    mogo_backup_log "dry-run: 归档 ${archive} → 目标库 ${target_db}（drop=${drop}）"
    return 0
  fi

  mogo_backup_require_cmd openssl
  if (( consistency_only == 0 )); then
    mogo_backup_require_cmd mongorestore mongosh
  else
    mogo_backup_require_cmd mongosh
  fi

  # 1) 校验和
  local expected_sha actual_sha
  if [[ -r "${archive}.sha256" ]]; then
    expected_sha="$(awk '{print $1}' "${archive}.sha256")"
    actual_sha="$(mogo_backup_sha256 "${archive}")"
    if [[ "${expected_sha}" != "${actual_sha}" ]]; then
      mogo_backup_die "校验和不匹配（期望 ${expected_sha} 实际 ${actual_sha}）：备份已损坏，拒绝恢复"
    fi
    mogo_backup_log "校验和一致：${actual_sha}"
  else
    mogo_backup_log "WARN: 缺少 ${archive}.sha256，跳过完整性校验"
  fi

  # 2) 解密（远端 target 库恢复需要明文流；--archive 支持从 stdin 读，这里落临时文件便于重试）
  local pass_file raw_path
  pass_file="$(mogo_backup_materialize_passphrase)"
  trap 'mogo_backup_cleanup' EXIT
  raw_path="$(mktemp "${TMPDIR:-/tmp}/mogo-restore.XXXXXX")"
  mogo_backup_register_tmp "${raw_path}"
  mogo_backup_decrypt "${archive}" "${raw_path}" "${pass_file}"
  mogo_backup_log "解密完成：$(wc -c <"${raw_path}" | tr -d ' ') 字节"

  # AES-CBC 没有认证标签：口令错时 openssl 常返回 0 并输出乱码。用清单里的明文
  # 摘要兜底，否则"恢复成功"可能实际恢复出一堆垃圾（甚至 mongorestore 直接报
  # 格式错误，让人以为备份坏了而不是口令错了）。
  local expected_raw_sha actual_raw_sha
  expected_raw_sha=""
  if [[ -r "${manifest_path}" ]]; then
    expected_raw_sha="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("plaintext_sha256",""))' "${manifest_path}" 2>/dev/null || true)"
  fi
  if [[ -n "${expected_raw_sha}" ]]; then
    actual_raw_sha="$(mogo_backup_sha256 "${raw_path}")"
    if [[ "${actual_raw_sha}" != "${expected_raw_sha}" ]]; then
      mogo_backup_die "解密后内容校验失败：明文摘要不匹配（口令错误或密文损坏）—— 期望 ${expected_raw_sha} 实际 ${actual_raw_sha}"
    fi
    mogo_backup_log "解密后明文摘要一致"
  else
    mogo_backup_log "WARN: 清单缺少 plaintext_sha256，无法判断解密结果是否正确（建议重新备份）"
  fi

  # 3) 目标库非空时的保护
  local uri existing
  uri="$(mogo_backup_uri)"
  if (( drop == 0 )) && (( consistency_only == 0 )); then
    existing="$(mogo_backup_collection_counts "$(mogo_backup_uri_with_db "${uri}" "${target_db}")" 2>/dev/null | wc -l | tr -d ' ')"
    if [[ "${existing}" != "0" ]] && [[ "${target_db}" == "${dbname}" ]]; then
      if (( assume_yes == 0 )); then
        mogo_backup_die "目标库 ${target_db} 非空：确认覆盖请加 --drop --yes（默认拒绝合并写入）"
      fi
      mogo_backup_log "目标库非空，按 --drop 覆盖"
    fi
  fi

  if (( consistency_only == 0 )); then
    local restore_args=(--uri "${uri}" --gzip --archive="${raw_path}"
      --nsFrom "${dbname}.*" --nsTo "${target_db}.*")
    if (( drop == 1 )); then
      restore_args+=(--drop)
    fi
    mongorestore "${restore_args[@]}"
    mogo_backup_log "恢复完成：${dbname} → ${target_db}"
  fi

  # 4) 一致性校验：清单里的每个集合文档数必须与恢复后一致
  if (( consistency_only == 1 )); then
    local actual_counts
    actual_counts="$(mogo_backup_collection_counts "$(mogo_backup_uri_with_db "${uri}" "${target_db}")")"
    mogo_backup_log "已恢复库 ${target_db} 的集合数：$(printf '%s\n' "${actual_counts}" | sed '/^$/d' | wc -l | tr -d ' ')"
    [[ -r "${manifest_path}" ]] || mogo_backup_die "缺少清单，无法比对基线"
    local expected_counts
    expected_counts="$(python3 - "${manifest_path}" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
for item in data.get("collections", []):
    print(f'{item["name"]}\t{item["count"]}')
PY
)"
    mogo_restore_compare_counts "${expected_counts}" "${actual_counts}" || mogo_backup_die "一致性校验失败：文档数与备份清单不一致"
    mogo_backup_log "一致性校验通过（$(printf '%s\n' "${expected_counts}" | sed '/^$/d' | wc -l | tr -d ' ') 个集合）"
    return 0
  fi

  # 恢复后的即时校验：恢复到别的库名时，比对目标库与清单基线
  if [[ -r "${manifest_path}" ]]; then
    local expected_counts actual_counts
    expected_counts="$(python3 - "${manifest_path}" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
for item in data.get("collections", []):
    print(f'{item["name"]}\t{item["count"]}')
PY
)"
    actual_counts="$(mogo_backup_collection_counts "$(mogo_backup_uri_with_db "${uri}" "${target_db}")")"
    mogo_restore_compare_counts "${expected_counts}" "${actual_counts}" \
      || mogo_backup_die "恢复后一致性校验失败：文档数与备份清单不一致"
    mogo_backup_log "恢复后一致性校验通过"
  fi

  printf '%s\n' "${target_db}"
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  mogo_restore_mongo_main "$@"
fi
