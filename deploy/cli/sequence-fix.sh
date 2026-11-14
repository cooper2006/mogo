#!/usr/bin/env bash

mogo_fix_recover_on_exit() {
  local original_status=$?
  trap - EXIT INT TERM
  if [[ "${MOGO_FIX_RESTORE_PENDING:-false}" != "true" ]]; then
    return "${original_status}"
  fi
  MOGO_FIX_RESTORE_PENDING=false
  if [[ "${MOGO_FIX_BACKUP_VALID:-false}" == "true" ]]; then
    mogo_msg fix_restoring >&2
    if ! mogo_compose exec -T mongo mongorestore --drop --archive --gzip \
        --nsInclude='gragentic.chat_messages' \
        --nsInclude='gragentic.chat_sessions' \
        --nsInclude='gragentic.session_participants' < "${MOGO_FIX_BACKUP_FILE}"; then
      mogo_msg fix_restore_failed "${MOGO_FIX_BACKUP_DIR}" >&2
      exit 1
    fi
  fi
  if ! mogo_compose start chat-api; then
    mogo_msg fix_restore_failed "${MOGO_FIX_BACKUP_DIR}" >&2
    exit 1
  fi
  if [[ -n "${MOGO_FIX_MARKER:-}" ]]; then
    rm -f "${MOGO_FIX_MARKER}"
  fi
  if [[ "${MOGO_FIX_BACKUP_VALID:-false}" == "true" ]]; then
    mogo_msg fix_rolled_back "${MOGO_FIX_BACKUP_DIR}" >&2
  fi
  return "${original_status}"
}

mogo_fix_sequences() {
  local confirmed="false" use_build="false" argument backup_dir backup_file backup_base marker
  for argument in "$@"; do
    case "${argument}" in
      --yes) confirmed="true" ;;
      --build) use_build="true" ;;
      *) printf 'Unknown fix option: %s\n' "${argument}" >&2; return 2 ;;
    esac
  done
  if [[ "${confirmed}" != "true" ]]; then
    if [[ ! -t 0 ]]; then
      mogo_msg fix_confirm >&2
      return 2
    fi
    local answer=""
    mogo_msg fix_confirm
    read -r answer
    [[ "${answer}" == "FIX" ]] || return 2
  fi

  if [[ "${use_build}" == "true" ]]; then
    mogo_configure_images true
    mogo_compose build chat-api || return 1
  else
    mogo_configure_images false
    MOGO_PULL_POLICY=always
    export MOGO_PULL_POLICY
    mogo_pull_images_serially always || return 1
  fi
  # Check prerequisites before taking the writer offline. The official Mongo
  # image ships both tools; a custom image must supply them too.
  if ! mogo_compose exec -T mongo sh -c \
      'command -v mongodump && command -v mongorestore && mongorestore --help | grep -q -- --dryRun' >/dev/null; then
    mogo_msg fix_tools_missing >&2
    return 1
  fi
  backup_base="${MOGO_FIX_BACKUP_BASE_DIR:-${ROOT_DIR}/backups}"
  mkdir -p "${backup_base}"
  for marker in "${backup_base}"/session-seq-fix.*/IN_PROGRESS; do
    if [[ -f "${marker}" ]]; then
      mogo_msg fix_incomplete "${marker%/IN_PROGRESS}" >&2
      return 1
    fi
  done
  if [[ -z "$(mogo_compose ps -q chat-api 2>/dev/null || true)" ]]; then
    mogo_msg fix_requires_running_chat >&2
    return 1
  fi
  backup_dir="$(umask 077; mktemp -d "${backup_base}/session-seq-fix.XXXXXXXX")"
  backup_file="${backup_dir}/mongo.archive.gz"

  mogo_msg fix_stopping
  if ! mogo_compose stop -t 600 chat-api; then
    mogo_compose start chat-api || true
    return 1
  fi
  if [[ -n "$(mogo_compose ps -q chat-api 2>/dev/null || true)" ]]; then
    mogo_msg fix_writer_still_running >&2
    mogo_compose start chat-api || true
    return 1
  fi
  MOGO_FIX_BACKUP_DIR="${backup_dir}"
  MOGO_FIX_BACKUP_FILE="${backup_file}"
  MOGO_FIX_BACKUP_VALID=false
  MOGO_FIX_RESTORE_PENDING=true
  trap 'mogo_fix_recover_on_exit' EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  if ! mogo_compose exec -T mongo mongodump --db gragentic --archive --gzip > "${backup_file}"; then
    mogo_msg fix_backup_failed >&2
    return 1
  fi
  if [[ ! -s "${backup_file}" ]]; then
    mogo_msg fix_backup_failed >&2
    return 1
  fi
  if ! mogo_compose exec -T mongo mongorestore --dryRun --archive --gzip \
      --nsInclude='gragentic.chat_messages' \
      --nsInclude='gragentic.chat_sessions' \
      --nsInclude='gragentic.session_participants' < "${backup_file}"; then
    mogo_msg fix_backup_failed >&2
    return 1
  fi
  MOGO_FIX_BACKUP_VALID=true
  MOGO_FIX_MARKER="${backup_dir}/IN_PROGRESS"
  printf '%s\n' "${MOGO_VERSION}" > "${MOGO_FIX_MARKER}"
  mogo_msg fix_backup_complete "${backup_dir}"

  if mogo_compose run --rm --no-deps --pull never \
      -e MOGO_SESSION_FIX_WRITES_STOPPED=1 chat-api \
      python -m app.migrations.sequence_repair \
    && mogo_run_database_upgrade fix; then
    rm -f "${MOGO_FIX_MARKER}"
    MOGO_FIX_RESTORE_PENDING=false
    trap - EXIT INT TERM
    if [[ "${use_build}" == "true" ]]; then
      mogo_msg fix_complete_build
    else
      mogo_msg fix_complete
    fi
    return 0
  fi
  return 1
}
