#!/usr/bin/env bash

MOGO_DSH_PACKAGE_JSON="${ROOT_DIR}/services/chat-api/dsh/runtime-host/package.json"

mogo_target_dsh_version() {
  sed -n 's/.*"@deepseek-ai\/dsh"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' \
    "${MOGO_DSH_PACKAGE_JSON}" | head -n 1
}

mogo_has_build_flag() {
  local argument
  for argument in "$@"; do
    if [[ "${argument}" == "--build" ]]; then
      return 0
    fi
  done
  return 1
}

mogo_print_dsh_build_target() {
  local version
  version="$(mogo_target_dsh_version)"
  if [[ -n "${version}" ]]; then
    mogo_msg dsh_build_target "${version}"
  fi
}

mogo_print_running_dsh_version() {
  local container_id version
  # The Runtime Host scales out as dsh-runtime-host-1/-2/-3 behind a sticky LB
  # (see docker-compose.yml); every replica runs the same image, so the first
  # running replica is representative of the deployed DSH version.
  container_id="$("${DOCKER_BIN}" compose ps -q dsh-runtime-host-1 2>/dev/null || true)"
  if [[ -z "${container_id}" ]]; then
    return 0
  fi
  version="$("${DOCKER_BIN}" compose exec -T dsh-runtime-host-1 \
    node -p "require('@deepseek-ai/dsh/package.json').version" 2>/dev/null || true)"
  if [[ -n "${version}" ]]; then
    mogo_msg dsh_running_version "${version}"
  fi
}
