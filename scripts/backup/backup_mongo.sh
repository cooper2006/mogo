#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════
# scripts/backup/backup_mongo.sh — MongoDB 逻辑备份（T095 / T096）
# ═══════════════════════════════════════════════════════════════════════
#
# 用法：
#   scripts/backup/backup_mongo.sh [--mode full|oplog] [--db <name>] [--dry-run]
#
#   full   （每日全量）mongodump --gzip --archive
#   oplog  （每小时）mongodump --oplog --gzip --archive：dump 期间记录 oplog，
#          恢复时可回放到任意时点，小时窗口内 RPO 取决于 oplog 是否随归档保留
#
# 为什么不是"原生增量"：MongoDB 社区版没有 mongodump 级别的增量备份，
# 真正的增量要 `mongodump --oplog` 持续采集 + `mongorestore --oplogReplay`
# 回放，或改用 Percona Backup for MongoDB / Ops Manager。本仓库按"每小时带
# oplog 的 dump + 每日全量"落地，并在 docs/observability/rto-rpo.md 里把
# 这条限制写成前提——不写成"已实现增量"，否则演练时 RPO 会对不上。
#
# 产物（全部落在 MOGO_BACKUP_DIR，默认 <repo>/backups）：
#   mongo-<db>-<mode>-<UTC>.archive.gz.enc   加密后的 dump（AES-256-CBC + PBKDF2）
#   mongo-<db>-<mode>-<UTC>.archive.gz.json  清单：时间、耗时、字节数、sha256、
#                                            各集合文档数、密钥来源、工具版本
#   mongo-<db>-<mode>-<UTC>.archive.gz.enc.sha256  独立校验和文件
#
# 退出码：0 成功（含异地上传缺失告警）；非 0 失败。
#   dry-run 只打印将要做什么，不写任何文件。
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./lib.sh
source "${SCRIPT_DIR}/lib.sh"

mogo_backup_json_escape() {
  printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'
}

# 各集合文档数 → JSON 数组；counts 是 "<name>\t<count>" 的多行文本。
mogo_backup_counts_json() {
  local counts="$1" out="" line name count
  if [[ -z "${counts}" ]]; then
    printf '[]'
    return 0
  fi
  while IFS= read -r line; do
    [[ -n "${line}" ]] || continue
    name="${line%%	*}"
    count="${line##*	}"
    if [[ -n "${out}" ]]; then
      out="${out},"
    fi
    out="${out}{\"name\":\"$(mogo_backup_json_escape "${name}")\",\"count\":${count}}"
  done <<EOF
${counts}
EOF
  printf '[%s]' "${out}"
}

mogo_backup_mongo_main() {
  local mode="full" db="" dry_run=0
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --mode) mode="${2:-}"; shift 2 ;;
      --mode=*) mode="${1#*=}"; shift ;;
      --db) db="${2:-}"; shift 2 ;;
      --db=*) db="${1#*=}"; shift ;;
      --dry-run) dry_run=1; shift ;;
      -h|--help)
        sed -n '2,30p' "${BASH_SOURCE[0]}"
        return 0 ;;
      *) mogo_backup_die "未知参数：$1" ;;
    esac
  done
  if [[ "${mode}" != "full" && "${mode}" != "oplog" ]]; then
    mogo_backup_die "--mode 只能是 full 或 oplog（收到：${mode}）"
  fi
  if [[ -n "${db}" ]]; then
    MOGO_MONGODB_DB="${db}"
    export MOGO_MONGODB_DB
  fi

  local uri dbname backup_dir stamp archive manifest archive_path manifest_path
  uri="$(mogo_backup_uri)"
  dbname="$(mogo_backup_db)"
  backup_dir="$(mogo_backup_dir)"
  stamp="$(mogo_backup_utc_stamp)"
  archive="$(mogo_backup_archive_name "${dbname}" "${mode}" "${stamp}")"
  manifest="$(mogo_backup_manifest_name "${archive}")"
  archive_path="${backup_dir}/${archive}"
  manifest_path="${backup_dir}/${manifest}"

  mogo_backup_require_cmd mongodump mongosh openssl

  if (( dry_run == 1 )); then
    mogo_backup_log "dry-run: mode=${mode} db=${dbname} uri=$(mogo_backup_redact_uri "${uri}")"
    mogo_backup_log "dry-run: 将写入 ${archive_path}"
    mogo_backup_log "dry-run: 加密算法 $(mogo_backup_cipher)，KDF 迭代 $(mogo_backup_kdf_iter)"
    return 0
  fi

  mkdir -p "${backup_dir}"
  chmod 700 "${backup_dir}" 2>/dev/null || true

  # 口令在真正开始 dump 之前校验：先花 10 分钟 dump 完才发现没配密钥，是线上
  # 最容易漏掉的一类失败。
  local pass_file pass_source started_epoch started_at
  pass_file="$(mogo_backup_materialize_passphrase)"
  pass_source="$(mogo_backup_passphrase_source)"
  trap 'mogo_backup_cleanup' EXIT

  started_epoch="$(mogo_backup_now_epoch)"
  started_at="$(mogo_backup_epoch_to_iso "${started_epoch}")"
  mogo_backup_log "开始备份 db=${dbname} mode=${mode} → ${archive}"

  local raw_path counts dump_args
  raw_path="$(mktemp "${TMPDIR:-/tmp}/mogo-dump.XXXXXX")"
  mogo_backup_register_tmp "${raw_path}"

  # --oplog 只在副本集上可用；单节点 mongod 也支持（会记录空 oplog）。
  dump_args=(--uri "${uri}" --gzip --archive="${raw_path}")
  if [[ "${mode}" == "oplog" ]]; then
    dump_args+=(--oplog)
  fi
  mongodump "${dump_args[@]}"

  counts="$(mogo_backup_collection_counts "$(mogo_backup_uri_with_db "${uri}" "${dbname}")")"

  local raw_bytes raw_sha
  raw_bytes="$(wc -c <"${raw_path}" | tr -d ' ')"
  (( raw_bytes > 0 )) || mogo_backup_die "mongodump 产出为空，拒绝写入空备份"
  # AES-CBC 不提供认证：错误口令常常"解密成功"并输出乱码，openssl 退出码仍是 0。
  # 先把明文摘要写进清单，恢复时用它判断解出来的东西到底是不是原备份。
  raw_sha="$(mogo_backup_sha256 "${raw_path}")"

  mogo_backup_encrypt "${raw_path}" "${archive_path}" "${pass_file}"
  rm -f "${raw_path}"

  local encrypted_bytes sha finished_epoch finished_at duration
  encrypted_bytes="$(wc -c <"${archive_path}" | tr -d ' ')"
  sha="$(mogo_backup_sha256 "${archive_path}")"
  finished_epoch="$(mogo_backup_now_epoch)"
  finished_at="$(mogo_backup_epoch_to_iso "${finished_epoch}")"
  duration="$(( finished_epoch - started_epoch ))"

  printf '%s  %s\n' "${sha}" "${archive}" >"${archive_path}.sha256"
  chmod 600 "${archive_path}" "${archive_path}.sha256" 2>/dev/null || true

  cat >"${manifest_path}" <<EOF
{
  "schema_version": ${MOGO_BACKUP_SCHEMA_VERSION},
  "kind": "mongo-logical-backup",
  "db": "$(mogo_backup_json_escape "${dbname}")",
  "mode": "${mode}",
  "uri": "$(mogo_backup_json_escape "$(mogo_backup_redact_uri "${uri}")")",
  "archive": "$(mogo_backup_json_escape "${archive}")",
  "started_at": "${started_at}",
  "finished_at": "${finished_at}",
  "duration_seconds": ${duration},
  "dump_bytes": ${raw_bytes},
  "encrypted_bytes": ${encrypted_bytes},
  "sha256": "${sha}",
  "plaintext_sha256": "${raw_sha}",
  "collections": $(mogo_backup_counts_json "${counts}"),
  "encryption": {
    "cipher": "$(mogo_backup_cipher)",
    "kdf": "pbkdf2",
    "iterations": $(mogo_backup_kdf_iter),
    "passphrase_source": "${pass_source}"
  },
  "host": "$(mogo_backup_json_escape "$(hostname 2>/dev/null || printf unknown)")",
  "tool_versions": {
    "mongodump": "$(mongodump --version 2>/dev/null | head -1 | sed -e 's/"/'"'"'/g' || printf unknown)",
    "openssl": "$(openssl version 2>/dev/null | head -1 | sed -e 's/"/'"'"'/g' || printf unknown)"
  }
}
EOF

  mogo_backup_log "备份完成 ${archive}（${encrypted_bytes} 字节，sha256=${sha}，耗时 ${duration}s）"

  # 异地上传：缺失只告警。返回码 2 = 未配置异地，属于"本地成功但异地缺失"。
  local offsite_status="skipped" rc=0
  mogo_backup_offsite_upload "${backup_dir}" "${archive}" "${manifest}" "${archive}.sha256" || rc=$?
  if (( rc == 0 )); then
    offsite_status="uploaded"
  elif (( rc == 2 )); then
    offsite_status="not-configured"
  else
    mogo_backup_die "异地上传失败（本地备份已保留：${archive_path}）"
  fi
  mogo_backup_log "异地上传状态：${offsite_status}"

  # 把上传结果补进清单（事后可查"这份备份当时到底有没有异地副本"）。
  local tmp_manifest
  tmp_manifest="$(mktemp "${TMPDIR:-/tmp}/mogo-manifest.XXXXXX")"
  mogo_backup_register_tmp "${tmp_manifest}"
  sed -e "s/^{/{\n  \"offsite_status\": \"${offsite_status}\",/" "${manifest_path}" >"${tmp_manifest}"
  mv "${tmp_manifest}" "${manifest_path}"

  printf '%s\n' "${archive_path}"
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  mogo_backup_mongo_main "$@"
fi
