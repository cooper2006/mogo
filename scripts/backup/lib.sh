#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════
# scripts/backup/lib.sh — MongoDB 逻辑备份 / 恢复 / 演练的共用函数（T095–T100）
# ═══════════════════════════════════════════════════════════════════════
#
# 只放「多个脚本都要用」的东西；每个脚本自己保留 main，便于被测试 source。
# 目标 shell：bash 3.2（macOS 自带）——不用关联数组、mapfile、`${v,,}`。
#
# 环境变量（全部有默认值，密钥类必须由调用方提供，仓库里不留任何口令）：
#   MOGO_MONGODB_URI                 连接串，默认 mongodb://mongo:27017
#   MOGO_MONGODB_DB                  库名，默认 mogo
#   MOGO_BACKUP_DIR                  本地备份目录，默认 <repo>/backups
#   MOGO_BACKUP_OFFSITE_DIR          异地目录（本地路径或挂载点），空=不上传
#   MOGO_BACKUP_OFFSITE_RCLONE_REMOTE rclone 远端（如 s3:mogo-backup），空=不用 rclone
#   MOGO_BACKUP_PASSPHRASE           加密口令（优先）；MOGO_BACKUP_PASSPHRASE_FILE 次之
#   MOGO_BACKUP_LOCAL_RETENTION_DAYS 本地保留天数，默认 30
#   MOGO_BACKUP_OFFSITE_RETENTION_DAYS 异地保留天数，默认 90
#   MOGO_BACKUP_CIPHER / _KDF_ITER   默认 aes-256-cbc / 200000
#
# 为什么口令只走环境变量/文件：T102 要求「备份密钥从环境变量或密钥管理系统读取，
# 不进代码仓库」。这里再补一条硬约束——两个来源都没有时直接失败退出，绝不回退到
# 内置默认口令：一个有默认口令的加密等于没加密，而它看起来又是"加密过的"。
set -Eeuo pipefail

MOGO_BACKUP_SCHEMA_VERSION=1

# ── 基础输出 ────────────────────────────────────────────────────────────

mogo_backup_log() {
  printf '[backup %s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >&2
}

mogo_backup_die() {
  printf '[backup %s] ERROR: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >&2
  exit 1
}

mogo_backup_utc_stamp() {
  date -u +%Y%m%dT%H%M%SZ
}

mogo_backup_now_epoch() {
  date -u +%s
}

# epoch → ISO8601 UTC（BSD date 与 GNU date 参数不同，两条路都试）
mogo_backup_epoch_to_iso() {
  local epoch="$1"
  if date -u -r "${epoch}" +%Y-%m-%dT%H:%M:%SZ >/dev/null 2>&1; then
    date -u -r "${epoch}" +%Y-%m-%dT%H:%M:%SZ
  else
    date -u -d "@${epoch}" +%Y-%m-%dT%H:%M:%SZ
  fi
}

mogo_backup_require_cmd() {
  local cmd
  for cmd in "$@"; do
    command -v "${cmd}" >/dev/null 2>&1 || mogo_backup_die "缺少命令：${cmd}"
  done
}

# ── 配置读取（调用方可用 env 覆盖；全部单点定义，避免各脚本各读一遍） ────

mogo_backup_uri() {
  printf '%s' "${MOGO_MONGODB_URI:-mongodb://mongo:27017}"
}

# 日志/清单里落盘前必须脱敏：连接串常带账号口令。
mogo_backup_redact_uri() {
  printf '%s' "$1" | sed -E 's#(mongodb(\+srv)?://)[^@/]*@#\1***:***@#'
}

mogo_backup_db() {
  local uri db
  uri="$(mogo_backup_uri)"
  if [[ -n "${MOGO_MONGODB_DB:-}" ]]; then
    printf '%s' "${MOGO_MONGODB_DB}"
    return 0
  fi
  # 连接串尾部的 /dbname 优先（与 mongodump 的 --uri 语义一致）
  db="$(printf '%s' "${uri}" | sed -E 's#^[^/]*//[^/]*/?([^?]*).*#\1#')"
  printf '%s' "${db:-mogo}"
}

mogo_backup_dir() {
  printf '%s' "${MOGO_BACKUP_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/backups}"
}

mogo_backup_cipher() {
  printf '%s' "${MOGO_BACKUP_CIPHER:-aes-256-cbc}"
}

mogo_backup_kdf_iter() {
  printf '%s' "${MOGO_BACKUP_KDF_ITER:-200000}"
}

mogo_backup_local_retention_days() {
  printf '%s' "${MOGO_BACKUP_LOCAL_RETENTION_DAYS:-30}"
}

mogo_backup_offsite_retention_days() {
  printf '%s' "${MOGO_BACKUP_OFFSITE_RETENTION_DAYS:-90}"
}

# ── 密钥 ────────────────────────────────────────────────────────────────

# 解析口令来源，回显 "env" / "file"（便于清单记录「密钥来自哪」而不记内容）。
mogo_backup_passphrase_source() {
  if [[ -n "${MOGO_BACKUP_PASSPHRASE:-}" ]]; then
    printf 'env'
  elif [[ -n "${MOGO_BACKUP_PASSPHRASE_FILE:-}" ]]; then
    printf 'file'
  else
    mogo_backup_die "未提供备份口令：请设置 MOGO_BACKUP_PASSPHRASE 或 MOGO_BACKUP_PASSPHRASE_FILE（不允许使用内置默认口令）"
  fi
}

# 生成供 openssl 使用的临时口令文件（0600），回显路径。
# 调用方必须把它登记到 MOGO_BACKUP_TMP_FILES，交由 mogo_backup_cleanup 删除。
mogo_backup_materialize_passphrase() {
  local source tmp
  source="$(mogo_backup_passphrase_source)"
  if [[ "${source}" == "file" ]]; then
    [[ -r "${MOGO_BACKUP_PASSPHRASE_FILE}" ]] || mogo_backup_die "口令文件不可读：${MOGO_BACKUP_PASSPHRASE_FILE}"
    printf '%s' "${MOGO_BACKUP_PASSPHRASE_FILE}"
    return 0
  fi
  tmp="$(mktemp "${TMPDIR:-/tmp}/mogo-backup-pass.XXXXXX")"
  chmod 600 "${tmp}"
  printf '%s' "${MOGO_BACKUP_PASSPHRASE}" >"${tmp}"
  mogo_backup_register_tmp "${tmp}"
  printf '%s' "${tmp}"
}

# ── 临时文件回收 ────────────────────────────────────────────────────────

MOGO_BACKUP_TMP_FILES=""

mogo_backup_register_tmp() {
  MOGO_BACKUP_TMP_FILES="${MOGO_BACKUP_TMP_FILES}${1}
"
}

mogo_backup_cleanup() {
  local path
  [[ -n "${MOGO_BACKUP_TMP_FILES:-}" ]] || return 0
  while IFS= read -r path; do
    [[ -n "${path}" ]] || continue
    rm -rf "${path}"
  done <<EOF
${MOGO_BACKUP_TMP_FILES}
EOF
  MOGO_BACKUP_TMP_FILES=""
}

# ── 校验与加解密 ────────────────────────────────────────────────────────

# 优先 sha256sum（GNU），回退 shasum -a 256（BSD/macOS）；只回显摘要。
mogo_backup_sha256() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

mogo_backup_encrypt() {
  local src="$1" dst="$2" pass_file="$3"
  openssl enc -"$(mogo_backup_cipher)" -pbkdf2 -iter "$(mogo_backup_kdf_iter)" -salt \
    -in "${src}" -out "${dst}" -pass "file:${pass_file}"
}

mogo_backup_decrypt() {
  local src="$1" dst="$2" pass_file="$3"
  openssl enc -d -"$(mogo_backup_cipher)" -pbkdf2 -iter "$(mogo_backup_kdf_iter)" \
    -in "${src}" -out "${dst}" -pass "file:${pass_file}"
}

# 解密验证口令是否正确（只读前 16 字节，不解出整份数据）。
mogo_backup_verify_passphrase() {
  local enc="$1" pass_file="$2"
  openssl enc -d -"$(mogo_backup_cipher)" -pbkdf2 -iter "$(mogo_backup_kdf_iter)" \
    -in "${enc}" -out /dev/null -pass "file:${pass_file}" 2>/dev/null
}

# ── 备份文件命名与发现 ──────────────────────────────────────────────────

# 形如 mongo-mogo-full-20261025T031500Z.archive.gz.enc —— 名字里带库名、模式、
# UTC 时间戳，保留策略与演练都靠解析文件名判断年龄，不依赖 mtime（rsync/rclone
# 复制后 mtime 会变，按 mtime 清理会误删刚同步过来的备份）。
mogo_backup_archive_name() {
  local db="$1" mode="$2" stamp="$3"
  printf 'mongo-%s-%s-%s.archive.gz.enc' "${db}" "${mode}" "${stamp}"
}

mogo_backup_manifest_name() {
  local archive="$1"
  printf '%s.json' "${archive%.enc}"
}

# 从归档名解析 UTC 时间戳为 epoch。
mogo_backup_stamp_of_archive() {
  local name base stamp
  name="$(basename "$1")"
  base="${name%.archive.gz.enc}"
  stamp="${base##*-}"
  if date -u -j -f '%Y%m%dT%H%M%SZ' "${stamp}" +%s >/dev/null 2>&1; then
    date -u -j -f '%Y%m%dT%H%M%SZ' "${stamp}" +%s
  elif date -u -d "${stamp}" +%s >/dev/null 2>&1; then
    date -u -d "${stamp}" +%s
  else
    printf '0'
  fi
}

mogo_backup_age_days() {
  local epoch="$1" now
  now="$(mogo_backup_now_epoch)"
  printf '%s' "$(( (now - epoch) / 86400 ))"
}

# 取目录里最新一份归档（按文件名时间戳，不按 mtime）。
mogo_backup_latest_archive() {
  local dir="$1" latest="" latest_stamp=-1 path stamp
  [[ -d "${dir}" ]] || return 1
  for path in "${dir}"/mongo-*.archive.gz.enc; do
    [[ -e "${path}" ]] || continue
    stamp="$(mogo_backup_stamp_of_archive "${path}")"
    if (( stamp > latest_stamp )); then
      latest_stamp="${stamp}"
      latest="${path}"
    fi
  done
  [[ -n "${latest}" ]] || return 1
  printf '%s' "${latest}"
}

# ── 异地存储 ────────────────────────────────────────────────────────────

# 上传一份归档 + 清单 + 校验和到异地存储。
#   MOGO_BACKUP_OFFSITE_DIR      直接拷到该目录（NFS/对象存储挂载点都适用）
#   MOGO_BACKUP_OFFSITE_RCLONE_REMOTE  rclone 远端，适合 S3/OSS 等
# 两者都没配置时只告警不失败：本地备份仍然有效，但异地副本缺失必须显式可见。
mogo_backup_offsite_upload() {
  local src_dir="$1"; shift
  local file offsite remote
  offsite="${MOGO_BACKUP_OFFSITE_DIR:-}"
  remote="${MOGO_BACKUP_OFFSITE_RCLONE_REMOTE:-}"
  if [[ -z "${offsite}" && -z "${remote}" ]]; then
    mogo_backup_log "WARN: 未配置 MOGO_BACKUP_OFFSITE_DIR / MOGO_BACKUP_OFFSITE_RCLONE_REMOTE，跳过异地上传（异地副本缺失）"
    return 2
  fi
  if [[ -n "${offsite}" ]]; then
    mkdir -p "${offsite}"
    for file in "$@"; do
      cp -p "${src_dir}/${file}" "${offsite}/${file}"
    done
    mogo_backup_log "已上传 $(($#)) 个文件到异地目录 ${offsite}"
  fi
  if [[ -n "${remote}" ]]; then
    mogo_backup_require_cmd rclone
    rclone copy "${src_dir}" "${remote}" --include "mongo-*" --log-level ERROR
    mogo_backup_log "已上传到 rclone 远端 ${remote}"
  fi
  return 0
}

# 把异地副本取回本地目录（演练用：证明"只靠异地副本也能恢复"）。
mogo_backup_offsite_fetch() {
  local archive_name="$1" dest_dir="$2"
  local offsite remote tmp_dir
  offsite="${MOGO_BACKUP_OFFSITE_DIR:-}"
  remote="${MOGO_BACKUP_OFFSITE_RCLONE_REMOTE:-}"
  if [[ -n "${offsite}" ]]; then
    [[ -e "${offsite}/${archive_name}" ]] || mogo_backup_die "异地目录缺少 ${archive_name}"
    cp -p "${offsite}/${archive_name}" "${dest_dir}/"
    local manifest
    manifest="$(mogo_backup_manifest_name "${archive_name}")"
    if [[ -e "${offsite}/${manifest}" ]]; then
      cp -p "${offsite}/${manifest}" "${dest_dir}/"
    fi
    return 0
  fi
  if [[ -n "${remote}" ]]; then
    mogo_backup_require_cmd rclone
    tmp_dir="$(mktemp -d "${dest_dir}/.fetch.XXXXXX")"
    rclone copy "${remote}" "${tmp_dir}" --include "${archive_name}" --log-level ERROR
    [[ -e "${tmp_dir}/${archive_name}" ]] || mogo_backup_die "rclone 远端缺少 ${archive_name}"
    mv "${tmp_dir}/${archive_name}" "${dest_dir}/"
    rm -rf "${tmp_dir}"
    return 0
  fi
  mogo_backup_die "未配置异地存储，无法演练异地取回"
}

# ── 集合统计（备份时记基线、恢复/演练时比对） ───────────────────────────

# 输出：每行 "<集合名>\t<文档数>"，按集合名排序。
# 用 countDocuments 而不是 estimatedDocumentCount：后者读元数据，恢复后可能
# 因为分片/压缩差异而不同，用它做一致性校验会产生假阳性。
# 让 mongosh 直接按行打印，不在 bash 里解析 JSON——JSON 解析一旦有嵌套引号就会
# 悄悄错位，而一致性校验错位的代价是"校验通过但数据不对"。
mogo_backup_collection_counts() {
  local uri="$1"
  mongosh "${uri}" --quiet --eval '
    db.getCollectionNames().sort().forEach(function (name) {
      print(name + "\t" + db.getCollection(name).countDocuments({}));
    });
  '
}

# 把连接串末尾的库名换成指定库（演练恢复到 drill 库、校验别的库时用）。
# 保留 query（authSource/replicaSet 都在里面，丢了下场就是认证失败）。
mogo_backup_uri_with_db() {
  local uri="$1" db="$2" base query=""
  case "${uri}" in
    *\?*) query="?${uri#*\?}"; base="${uri%%\?*}" ;;
    *) base="${uri}" ;;
  esac
  base="$(printf '%s' "${base}" | sed -E 's#^([^/]*//[^/]+)/.*#\1#')"
  printf '%s/%s%s' "${base}" "${db}" "${query}"
}
