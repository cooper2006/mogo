#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════
# Backup / restore / rollback exercise test (release-checklist item 4)
# ═══════════════════════════════════════════════════════════════════════
#
# Exercises the full backup → upgrade → rollback cycle against the
# backup.sh functions with Docker calls mocked. Covers:
#   1. backup:  stops compose, archives 8 named volumes, writes SHA256SUMS,
#               volume-prefix.txt, movo-version.txt, git-commit.txt, restarts.
#   2. restore: validates backup dir, verifies SHA256SUMS, checks volume
#               prefix match, recreates volumes, extracts archives, restarts.
#   3. rollback: update to a different MOGO_VERSION and back.
#
# Run: bash scripts/test_backup_restore_rollback.sh
# ═══════════════════════════════════════════════════════════════════════
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# shellcheck source=../deploy/cli/backup.sh
source "${ROOT_DIR}/deploy/cli/backup.sh"
# shellcheck source=../deploy/cli/images.sh
source "${ROOT_DIR}/deploy/cli/images.sh"

# ── mocks ────────────────────────────────────────────────────────────────
movo_msg() { :; }
sleep() { :; }
dotenv_value() { :; }
refresh_gateway_resolution() { :; }
wait_until_ready() { :; }

calls=()
mogo_compose() { calls+=("$*"); }

created_volumes=()
extracted_volumes=()

docker() {
  local cmd="$1"
  case "${cmd}" in
    volume)
      case "$2" in
        inspect)
          local suffix
          for suffix in \
            deployment-secrets mongo-data redis-data weaviate-data \
            dsh-runtime-data askai-storage knowledge-storage admin-static; do
            [[ "$3" == *"${suffix}" ]] && return 0
          done
          return 1
          ;;
        create)
          created_volumes+=("$3")
          return 0
          ;;
      esac
      ;;
    run)
      if [[ "$*" == *"tar -C /source"* ]]; then
        # backup: create dummy .tar.gz files in the mounted backup dir.
        local backup_host="" suffix="" prev=""
        for arg in "$@"; do
          if [[ "${prev}" == "-v" && "${arg}" == *":/backup" ]]; then
            backup_host="${arg%%:*}"
          fi
          if [[ "${arg}" == /backup/*.tar.gz ]]; then
            suffix="${arg##*/}"
            suffix="${suffix%.tar.gz}"
          fi
          prev="${arg}"
        done
        if [[ -n "${backup_host}" && -n "${suffix}" && -d "${backup_host}" ]]; then
          touch "${backup_host}/${suffix}.tar.gz"
        fi
      elif [[ "$*" == *"tar -xzf"* ]]; then
        local target="" prev=""
        for arg in "$@"; do
          if [[ "${prev}" == "-v" && "${arg}" == *":/target" ]]; then
            target="${arg%%:*}"
            target="${target##*/}"
            break
          fi
          prev="${arg}"
        done
        [[ -n "${target}" ]] && extracted_volumes+=("${target}")
      fi
      return 0
      ;;
    *) return 0 ;;
  esac
}
DOCKER_BIN="docker"
export DOCKER_BIN

# ── assertions ───────────────────────────────────────────────────────────
fail() { printf 'FAIL: %s\n' "$1" >&2; exit 1; }
assert_eq() {
  [[ "$1" == "$2" ]] || fail "$3: expected '$2', got '$1'"
}
assert_ge() {
  (( $1 >= $2 )) || fail "$3: expected >= $2, got $1"
}
assert_file_exists() {
  [[ -f "$1" ]] || fail "file not found: $1"
}

# ── setup ────────────────────────────────────────────────────────────────
MOGO_VERSION="abc1234"
MOVO_VERSION="abc1234"
export MOGO_VERSION MOVO_VERSION

tmp_parent="$(mktemp -d)"
trap 'rm -rf "${tmp_parent}"' EXIT
backup_dir="${tmp_parent}/movo-backup-test"

# ── 1. backup ────────────────────────────────────────────────────────────
echo "=== 1. backup ==="

movo_backup "${backup_dir}"

assert_file_exists "${backup_dir}/SHA256SUMS"
assert_file_exists "${backup_dir}/volume-prefix.txt"
assert_file_exists "${backup_dir}/movo-version.txt"
assert_file_exists "${backup_dir}/git-commit.txt"

tar_count=$(find "${backup_dir}" -maxdepth 1 -name '*.tar.gz' | wc -l | tr -d ' ')
assert_eq "${tar_count}" "8" "backup archives 8 volumes"

ver="$(tr -d '\r\n' < "${backup_dir}/movo-version.txt")"
assert_eq "${ver}" "abc1234" "backup records MOGO_VERSION"

stop_count=$(grep -c 'stop' <<< "$(printf '%s\n' "${calls[@]}")" || true)
restart_count=$(grep -c 'up -d' <<< "$(printf '%s\n' "${calls[@]}")" || true)
assert_ge "${stop_count}" "1" "backup stops compose"
assert_ge "${restart_count}" "1" "backup restarts compose"

echo "  backup artefacts: $(ls "${backup_dir}" | tr '\n' ' ')"
echo "  PASS"

# ── 2. restore ───────────────────────────────────────────────────────────
echo ""
echo "=== 2. restore ==="

calls=()
created_volumes=()
extracted_volumes=()

movo_restore "${backup_dir}" "true"

assert_eq "${#created_volumes[@]}" "8" "restore recreates 8 volumes"
assert_eq "${#extracted_volumes[@]}" "8" "restore extracts 8 archives"

stop_count=$(grep -c 'down' <<< "$(printf '%s\n' "${calls[@]}")" || true)
restart_count=$(grep -c 'up -d' <<< "$(printf '%s\n' "${calls[@]}")" || true)
assert_ge "${stop_count}" "1" "restore stops compose"
assert_ge "${restart_count}" "1" "restore restarts compose"

echo "  created volumes:   ${created_volumes[*]}"
echo "  extracted volumes: ${extracted_volumes[*]}"
echo "  PASS"

# ── 3. restore validation ────────────────────────────────────────────────
echo ""
echo "=== 3. restore validation ==="

if movo_restore "/nonexistent/dir" "true" 2>/dev/null; then
  fail "restore should reject missing backup dir"
fi

bad_dir="${tmp_parent}/bad-backup"
mkdir -p "${bad_dir}"
if movo_restore "${bad_dir}" "true" 2>/dev/null; then
  fail "restore should reject dir without SHA256SUMS"
fi

printf 'different\n' > "${bad_dir}/volume-prefix.txt"
printf 'dummy' > "${bad_dir}/SHA256SUMS"
if movo_restore "${bad_dir}" "true" 2>/dev/null; then
  fail "restore should reject volume prefix mismatch"
fi

echo "  PASS"

# ── 4. rollback ──────────────────────────────────────────────────────────
echo ""
echo "=== 4. rollback ==="

calls=()

MOGO_VERSION="def5678"
MOVO_VERSION="def5678"
export MOGO_VERSION MOVO_VERSION
movo_configure_images false

found_new=0
for entry in "${MOVO_IMAGE_SERVICES[@]}"; do
  var="${entry%%:*}"
  if [[ "${!var}" == *"def5678"* ]]; then
    found_new=$((found_new + 1))
  fi
done
assert_eq "${found_new}" "6" "update pins 6 array service images to new version"
if [[ "${MOVO_DOCUMENT_API_IMAGE}" != *"def5678"* ]]; then
  fail "document-parser image not pinned to new version"
fi

calls=()
MOGO_VERSION="abc1234"
MOVO_VERSION="abc1234"
export MOGO_VERSION MOVO_VERSION
movo_configure_images false

found_rollback=0
for entry in "${MOVO_IMAGE_SERVICES[@]}"; do
  var="${entry%%:*}"
  if [[ "${!var}" == *"abc1234"* ]]; then
    found_rollback=$((found_rollback + 1))
  fi
done
assert_eq "${found_rollback}" "6" "rollback pins 6 array service images to previous version"
if [[ "${MOVO_DOCUMENT_API_IMAGE}" != *"abc1234"* ]]; then
  fail "document-parser image not pinned to rollback version"
fi

echo "  upgrade → def5678: ${found_new}/6 + document-parser"
echo "  rollback → abc1234: ${found_rollback}/6 + document-parser"
echo "  PASS"

# ── 5. backup idempotency ────────────────────────────────────────────────
echo ""
echo "=== 5. backup idempotency ==="

if movo_backup "${backup_dir}" 2>/dev/null; then
  fail "backup should reject existing destination"
fi
echo "  PASS"

# ── summary ──────────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  All backup / restore / rollback tests passed."
echo "═══════════════════════════════════════════════════════════════"