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
  mogo_compose up -d
  refresh_gateway_resolution
  wait_until_ready
  mogo_msg backup_complete "${target_dir}"
}

mogo_restore() {
  local source_dir="$1"
  local confirmed="${2:-false}"
  local prefix archived_prefix suffix volume
  if [[ "${source_dir}" != /* ]]; then
    source_dir="${ROOT_DIR}/${source_dir}"
  fi
  if [[ ! -d "${source_dir}" || ! -f "${source_dir}/SHA256SUMS" || ! -f "${source_dir}/volume-prefix.txt" ]]; then
    printf 'Invalid MOGO backup directory: %s\n' "${source_dir}" >&2
    return 2
  fi
  prefix="$(mogo_volume_prefix)"
  archived_prefix="$(tr -d '\r\n' < "${source_dir}/volume-prefix.txt")"
  if [[ "${archived_prefix}" != "${prefix}" ]]; then
    printf 'Backup volume prefix %s does not match configured prefix %s.\n' "${archived_prefix}" "${prefix}" >&2
    return 2
  fi
  (
    cd "${source_dir}"
    mogo_sha256_verify
  )
  if [[ "${confirmed}" != "true" ]]; then
    mogo_msg restore_confirm
    return 2
  fi

  mogo_compose down
  for suffix in "${MOGO_VOLUME_SUFFIXES[@]}"; do
    if [[ ! -f "${source_dir}/${suffix}.tar.gz" ]]; then
      printf 'Backup archive is missing: %s.tar.gz\n' "${suffix}" >&2
      return 1
    fi
    if ! mogo_restore_one_volume "${prefix}" "${source_dir}" "${suffix}"; then
      return 1
    fi
  done
  # Optional volumes are restored only when the archive carries them, so a
  # backup taken before a feature existed still restores cleanly.
  for suffix in "${MOGO_OPTIONAL_VOLUME_SUFFIXES[@]}"; do
    if [[ -f "${source_dir}/${suffix}.tar.gz" ]]; then
      printf 'Restoring optional volume: %s\n' "${suffix}"
      if ! mogo_restore_one_volume "${prefix}" "${source_dir}" "${suffix}"; then
        return 1
      fi
    fi
  done
  mogo_compose up -d
  refresh_gateway_resolution
  wait_until_ready
  mogo_msg restore_complete
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
