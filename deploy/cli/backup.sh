#!/usr/bin/env bash

MOGO_VOLUME_SUFFIXES=(
  deployment-secrets
  mongo-data
  redis-data
  weaviate-data
  dsh-runtime-data
  askai-storage
  knowledge-storage
  admin-static
)

# Volumes that only exist when their feature is switched on. `panweidb-storage`
# belongs to the `panweidb` compose profile (MOGO_DATA_BACKEND=panweidb), so a
# mongo-backend installation never has it.
#
# They are deliberately NOT in MOGO_VOLUME_SUFFIXES: that list is a hard
# requirement in both directions -- backup fails when a listed volume is absent,
# restore fails when a listed archive is absent. Putting an optional volume there
# would break `./mogo backup` for every mongo deployment, and adding it later
# would make every existing backup archive unrestorable. Optional volumes are
# backed up when present and restored when the archive exists.
MOGO_OPTIONAL_VOLUME_SUFFIXES=(
  panweidb-storage
)

mogo_sha256_create() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum ./*.tar.gz
  else
    shasum -a 256 ./*.tar.gz
  fi
}

# 生成目录内全部文件（含 .enc 与元数据）的校验和 —— 加密归档用。
mogo_sha256_all() {
  local dir="$1"
  (
    cd "${dir}"
    if command -v sha256sum >/dev/null 2>&1; then
      sha256sum ./* 2>/dev/null
    else
      shasum -a 256 ./* 2>/dev/null
    fi
  )
}

mogo_sha256_verify() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum -c SHA256SUMS
  else
    shasum -a 256 -c SHA256SUMS
  fi
}

# Archive one volume into the backup directory.
#
# `alpine` runs as root, which matters for panweidb-storage: that volume holds a
# data directory mode 0700 owned by UID 1000 (omm), and the non-root image users
# of the other services could not read it. tar preserves uid/gid, so a restore
# puts omm:dbgrp ownership back exactly as the database expects it.
mogo_backup_one_volume() {
  local volume="$1" target_dir="$2" suffix="$3"
  "${DOCKER_BIN}" run --rm \
    -v "${volume}:/source:ro" \
    -v "${target_dir}:/backup" \
    alpine:3.21 tar -C /source -czf "/backup/${suffix}.tar.gz" .
}

mogo_volume_prefix() {
  local prefix="${MOGO_VOLUME_PREFIX:-$(dotenv_value MOGO_VOLUME_PREFIX)}"
  # Must match the volume names in docker-compose.yml
  # (${MOGO_VOLUME_PREFIX:-mogo}_<suffix>), which now use the mogo prefix.
  prefix="${prefix:-mogo}"
  if [[ ! "${prefix}" =~ ^[A-Za-z0-9_.-]+$ ]]; then
    printf 'Invalid MOGO_VOLUME_PREFIX: %s\n' "${prefix}" >&2
    return 2
  fi
  printf '%s' "${prefix}"
}

mogo_write_backup() {
  local target_dir="$1"
  local prefix="$2"
  local suffix volume
  for suffix in "${MOGO_VOLUME_SUFFIXES[@]}"; do
    volume="${prefix}_${suffix}"
    if ! "${DOCKER_BIN}" volume inspect "${volume}" >/dev/null 2>&1; then
      printf 'Required Docker volume does not exist: %s\n' "${volume}" >&2
      return 1
    fi
    if ! mogo_backup_one_volume "${volume}" "${target_dir}" "${suffix}"; then
      return 1
    fi
  done
  # Optional volumes (profiles) are archived only when they exist, so a
  # mongo-only backup stays byte-for-byte what it was before.
  for suffix in "${MOGO_OPTIONAL_VOLUME_SUFFIXES[@]}"; do
    volume="${prefix}_${suffix}"
    if "${DOCKER_BIN}" volume inspect "${volume}" >/dev/null 2>&1; then
      printf 'Optional volume found, archiving: %s\n' "${volume}"
      if ! mogo_backup_one_volume "${volume}" "${target_dir}" "${suffix}"; then
        return 1
      fi
    fi
  done
  printf '%s\n' "${prefix}" > "${target_dir}/volume-prefix.txt"
  printf '%s\n' "${MOGO_VERSION:-latest}" > "${target_dir}/mogo-version.txt"
  git -C "${ROOT_DIR}" rev-parse HEAD > "${target_dir}/git-commit.txt" 2>/dev/null || true
  (
    cd "${target_dir}"
    mogo_sha256_create > SHA256SUMS
  )
}

mogo_backup() {
  local requested="${1:-}"
  local target_dir prefix timestamp
  prefix="$(mogo_volume_prefix)"
  timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
  target_dir="${requested:-${ROOT_DIR}/backups/mogo-backup-${timestamp}}"
  if [[ "${target_dir}" != /* ]]; then
    target_dir="${ROOT_DIR}/${target_dir}"
  fi
  if [[ -e "${target_dir}" ]]; then
    printf 'Backup destination already exists: %s\n' "${target_dir}" >&2
    return 2
  fi
  mkdir -p "${target_dir}"

  mogo_msg backup_stopping
  mogo_compose stop
  if ! mogo_write_backup "${target_dir}" "${prefix}"; then
    mogo_msg backup_failed >&2
    mogo_compose up -d || true
    return 1
  fi
  # 024 T065 (FR-035)：归档加密，防止备份集泄露。密钥不与备份集同机（T066）。
  if ! mogo_backup_encrypt_dir "${target_dir}"; then
    mogo_msg backup_failed >&2
    mogo_compose up -d || true
    return 1
  fi
  mogo_compose up -d
  refresh_gateway_resolution
  wait_until_ready
  mogo_msg backup_complete "${target_dir}"
}

mogo_restore() {
  local source_dir="$1"
  local confirmed="${2:-false}"
  local verify="${3:-false}"
  local prefix archived_prefix suffix volume
  local effective_dir="${source_dir}" work_dir=""
  if [[ "${source_dir}" != /* ]]; then
    source_dir="${ROOT_DIR}/${source_dir}"
    effective_dir="${source_dir}"
  fi
  if [[ ! -d "${source_dir}" || ! -f "${source_dir}/SHA256SUMS" || ! -f "${source_dir}/volume-prefix.txt" ]]; then
    printf 'Invalid MOGO backup directory: %s\n' "${source_dir}" >&2
    return 2
  fi
  # 024 T065 (FR-035)：归档若已加密，先解密到临时工作目录再校验/恢复，
  # 密钥必须与备份集分离（T066），解密后立即用后清理，不落明文。
  if [[ -f "${source_dir}/ENCRYPTED" ]] && \
     [[ "$(tr -d '\r\n' < "${source_dir}/ENCRYPTED")" == "true" ]]; then
    work_dir="$(mktemp -d)"
    if ! mogo_backup_decrypt_dir "${source_dir}" "${work_dir}"; then
      printf 'Decrypt failed: %s\n' "${source_dir}" >&2
      rm -rf "${work_dir}"
      return 1
    fi
    effective_dir="${work_dir}"
    trap 'rm -rf "${work_dir}"' RETURN
  fi
  prefix="$(mogo_volume_prefix)"
  archived_prefix="$(tr -d '\r\n' < "${source_dir}/volume-prefix.txt")"
  if [[ "${archived_prefix}" != "${prefix}" ]]; then
    printf 'Backup volume prefix %s does not match configured prefix %s.\n' "${archived_prefix}" "${prefix}" >&2
    return 2
  fi
  (
    cd "${effective_dir}"
    mogo_sha256_verify
  )
  if [[ "${confirmed}" != "true" ]]; then
    mogo_msg restore_confirm
    return 2
  fi

  mogo_compose down
  for suffix in "${MOGO_VOLUME_SUFFIXES[@]}"; do
    if [[ ! -f "${effective_dir}/${suffix}.tar.gz" ]]; then
      printf 'Backup archive is missing: %s.tar.gz\n' "${suffix}" >&2
      return 1
    fi
    if ! mogo_restore_one_volume "${prefix}" "${effective_dir}" "${suffix}"; then
      return 1
    fi
  done
  # Optional volumes are restored only when the archive carries them, so a
  # backup taken before a feature existed still restores cleanly.
  for suffix in "${MOGO_OPTIONAL_VOLUME_SUFFIXES[@]}"; do
    if [[ -f "${effective_dir}/${suffix}.tar.gz" ]]; then
      printf 'Restoring optional volume: %s\n' "${suffix}"
      if ! mogo_restore_one_volume "${prefix}" "${effective_dir}" "${suffix}"; then
        return 1
      fi
    fi
  done
  mogo_compose up -d
  refresh_gateway_resolution
  wait_until_ready
  mogo_msg restore_complete
  # 024 T072 (FR-037)：--verify 时自动执行恢复后业务校验（T071 脚本）。
  if [[ "${verify}" == "true" ]]; then
    local base_url report_dir
    base_url="${MOGO_VERIFY_BASE_URL:-${MOGO_LOCAL_BASE:-http://127.0.0.1:3000}}"
    report_dir="${ROOT_DIR}/backups"
    mkdir -p "${report_dir}" 2>/dev/null || true
    printf 'Restore verification (T071) against %s\n' "${base_url}"
    if ! python3 "${ROOT_DIR}/scripts/verify_restore_business.py" \
         --base-url "${base_url}" --json \
         > "${report_dir}/restore-verify.json" 2> "${report_dir}/restore-verify.err"; then
      printf 'FAIL 恢复后业务校验未通过: %s\n' "${base_url}" >&2
      cat "${report_dir}/restore-verify.err" 2>/dev/null >&2 || true
      return 1
    fi
    cat "${report_dir}/restore-verify.json"
    printf 'OK 恢复后业务校验通过（报告 %s）\n' "${report_dir}/restore-verify.json"
  fi
}

# Replace one volume's contents with the archive. The wipe-then-extract order is
# the existing one; `tar -xpf` restores owner/mode as recorded, which the
# PanWeiDB data directory needs (omm:dbgrp, 0700) to start at all.
mogo_restore_one_volume() {
  local prefix="$1" source_dir="$2" suffix="$3"
  local volume
  volume="${prefix}_${suffix}"
  "${DOCKER_BIN}" volume create "${volume}" >/dev/null
  "${DOCKER_BIN}" run --rm \
    -v "${volume}:/target" \
    -v "${source_dir}:/backup:ro" \
    alpine:3.21 sh -ec \
    "find /target -mindepth 1 -maxdepth 1 -exec rm -rf {} +; tar -xzf '/backup/${suffix}.tar.gz' -C /target"
}

# ── 024 T065 (FR-035)：备份归档加密 ──────────────────────────────────────
# 密钥来源优先级（MUST NOT 内置默认口令，MUST NOT 与备份集同机，见
# deploy/runbook/backup-key-management.md）：
#   MOGO_BACKUP_KEY        （环境变量，优先）
#   MOGO_BACKUP_KEY_FILE   （密钥文件路径）
# 两者都不设 → 未启用加密（保持与旧版本完全兼容的明文备份）。

MOGO_BACKUP_CIPHER="${MOGO_BACKUP_CIPHER:-aes-256-cbc}"
MOGO_BACKUP_KDF_ITER="${MOGO_BACKUP_KDF_ITER:-200000}"

# 取回密钥：成功输出密钥到 stdout，未启用返回 1。
mogo_backup_key() {
  if [[ -n "${MOGO_BACKUP_KEY:-}" ]]; then
    printf '%s' "${MOGO_BACKUP_KEY}"
    return 0
  fi
  local key_file="${MOGO_BACKUP_KEY_FILE:-}"
  if [[ -n "${key_file}" ]]; then
    if [[ ! -r "${key_file}" ]]; then
      printf 'MOGO_BACKUP_KEY_FILE not readable: %s\n' "${key_file}" >&2
      return 1
    fi
    tr -d '\r\n' < "${key_file}"
    return 0
  fi
  return 1
}

mogo_backup_encrypt_enabled() {
  local key
  key="$(mogo_backup_key 2>/dev/null)" || return 1
  [[ -n "${key}" ]]
}

# 加密整个备份目录中的 *.tar.gz。默认删除明文（否则等于没加密），
# 测试可用 MOGO_BACKUP_KEEP_PLAIN=1 保留明文。
mogo_backup_encrypt_dir() {
  local target_dir="$1"
  local key files f enc
  key="$(mogo_backup_key)" || {
    printf 'Backup encryption skipped: no key source configured (MOGO_BACKUP_KEY / MOGO_BACKUP_KEY_FILE)\n'
    return 0
  }
  local keep_plain="${MOGO_BACKUP_KEEP_PLAIN:-0}"
  printf '%s\n' "${MOGO_BACKUP_CIPHER}" > "${target_dir}/BACKUP_CIPHER"
  printf '%s\n' "true" > "${target_dir}/ENCRYPTED"
  printf '%s\n' "$(printf '%s' "${key}" | shasum -a 256 | awk '{print $1}' | cut -c1-32)" \
    > "${target_dir}/KEY_SHA256_PREFIX"
  shopt -s nullglob
  files=("${target_dir}"/*.tar.gz)
  shopt -u nullglob
  for f in "${files[@]}"; do
    enc="${f}.enc"
    if ! printf '%s' "${key}" | \
         openssl enc -${MOGO_BACKUP_CIPHER} -pbkdf2 -iter "${MOGO_BACKUP_KDF_ITER}" \
          -salt -in "${f}" -out "${enc}" -pass stdin; then
      printf 'Encryption failed for %s\n' "${f}" >&2
      return 1
    fi
    if [[ "${keep_plain}" != "1" ]]; then
      rm -f "${f}"
    fi
  done
  # 重新对加密后的归档生成校验和（含 ENCRYPTED / BACKUP_CIPHER / KEY_SHA256_PREFIX）
  mogo_sha256_all "${target_dir}" > "${target_dir}/SHA256SUMS"
  printf 'Encrypted %d archive(s) with %s\n' "${#files[@]}" "${MOGO_BACKUP_CIPHER}"
}

# 解密目录到工作目录：校验密钥指纹一致，避免用错密钥导致"静默解出垃圾"。
mogo_backup_decrypt_dir() {
  local source_dir="$1" work_dir="$2"
  local key expected actual cipher files f base
  cipher="$(tr -d '\r\n' < "${source_dir}/BACKUP_CIPHER" 2>/dev/null || printf '%s' "${MOGO_BACKUP_CIPHER}")"
  expected="$(tr -d '\r\n' < "${source_dir}/KEY_SHA256_PREFIX" 2>/dev/null || true)"
  key="$(mogo_backup_key)" || {
    printf 'Decryption required but no key source configured\n' >&2
    return 1
  }
  actual="$(printf '%s' "${key}" | shasum -a 256 | awk '{print $1}' | cut -c1-32)"
  if [[ -n "${expected}" && "${actual}" != "${expected}" ]]; then
    printf 'KEY_SHA256_PREFIX mismatch: expected %s got %s (wrong key?)\n' \
      "${expected}" "${actual}" >&2
    return 1
  fi
  shopt -s nullglob
  files=("${source_dir}"/*.tar.gz.enc)
  shopt -u nullglob
  for f in "${files[@]}"; do
    base="$(basename "${f}" .enc)"
    if ! printf '%s' "${key}" | \
         openssl enc -d -${cipher} -pbkdf2 -iter "${MOGO_BACKUP_KDF_ITER}" \
          -salt -in "${f}" -out "${work_dir}/${base}" -pass stdin; then
      printf 'Decryption failed for %s\n' "${f}" >&2
      return 1
    fi
  done
  # 复制元数据并生成明文校验和，使后续 restore 校验与未加密备份一致
  for meta in volume-prefix.txt mogo-version.txt git-commit.txt; do
    if [[ -f "${source_dir}/${meta}" ]]; then
      cp "${source_dir}/${meta}" "${work_dir}/${meta}"
    fi
  done
  (
    cd "${work_dir}"
    mogo_sha256_create > SHA256SUMS
  )
  printf 'Decrypted %d archive(s) into %s\n' "${#files[@]}" "${work_dir}"
}
