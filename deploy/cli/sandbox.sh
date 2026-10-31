#!/usr/bin/env bash
# sandbox（P1 移植自 himovo/movo）
# 容器隔离执行的 CLI 辅助函数。默认**不**自动启用；调用 mogo_sandbox_start
# 才会拉起 sandbox-manager。启用条件：COMPOSE_PROFILES 含 sandbox 且
# MOGO_SANDBOX_MANAGER_URL 为 http://sandbox-manager:8300。

mogo_sandbox_defaults() {
  COMPOSE_PROFILES="${COMPOSE_PROFILES:-$(dotenv_value COMPOSE_PROFILES)}"
  MOGO_SANDBOX_MANAGER_URL="${MOGO_SANDBOX_MANAGER_URL:-$(dotenv_value MOGO_SANDBOX_MANAGER_URL)}"
  COMPOSE_PROFILES="${COMPOSE_PROFILES:-sandbox}"
  MOGO_SANDBOX_MANAGER_URL="${MOGO_SANDBOX_MANAGER_URL:-http://sandbox-manager:8300}"
  export COMPOSE_PROFILES MOGO_SANDBOX_MANAGER_URL
}

mogo_sandbox_preflight() {
  local profiles configured_url engine_version major
  profiles="${COMPOSE_PROFILES:-$(dotenv_value COMPOSE_PROFILES)}"
  configured_url="${MOGO_SANDBOX_MANAGER_URL:-$(dotenv_value MOGO_SANDBOX_MANAGER_URL)}"
  if [[ ",${profiles}," != *,sandbox,* && -z "${configured_url}" ]]; then
    return 0
  fi
  if [[ ",${profiles}," != *,sandbox,* || "${configured_url}" != "http://sandbox-manager:8300" ]]; then
    mogo_msg sandbox_config_mismatch >&2
    return 2
  fi
  engine_version="$("${DOCKER_BIN}" version --format '{{.Server.Version}}' 2>/dev/null || true)"
  major="${engine_version%%.*}"
  if [[ ! "${major}" =~ ^[0-9]+$ || "${major}" -lt 26 ]]; then
    mogo_msg sandbox_engine_old "${engine_version:-unknown}" >&2
    return 2
  fi
}

mogo_sandbox_enabled() {
  local profiles
  profiles="${COMPOSE_PROFILES:-$(dotenv_value COMPOSE_PROFILES)}"
  [[ ",${profiles}," == *,sandbox,* ]]
}

mogo_sandbox_start() {
  if ! mogo_sandbox_enabled; then
    return 0
  fi
  local configured_image
  configured_image="${MOGO_SANDBOX_SCRIPT_IMAGE:-$(dotenv_value MOGO_SANDBOX_SCRIPT_IMAGE)}"
  if [[ " $* " == *" --build "* && -z "${configured_image}" ]]; then
    mogo_compose build sandbox-script || return 1
  else
    local script_image
    script_image="${configured_image:-ghcr.io/mogoai/sandbox-script:${MOGO_VERSION:-latest}}"
    if ! "${DOCKER_BIN}" image inspect "${script_image}" >/dev/null 2>&1; then
      if [[ -n "${configured_image}" ]]; then
        "${DOCKER_BIN}" pull "${script_image}" || return 1
      else
        mogo_compose pull sandbox-script || return 1
      fi
    fi
  fi
  mogo_compose up -d "$@" sandbox-manager || return 1
  local container_id status attempt
  container_id="$(mogo_compose ps -q sandbox-manager)"
  for attempt in $(seq 1 30); do
    status="$("${DOCKER_BIN}" inspect --format '{{.State.Health.Status}}' "${container_id}" 2>/dev/null || true)"
    if [[ "${status}" == healthy ]]; then
      return 0
    fi
    if [[ "${status}" == unhealthy ]]; then
      break
    fi
    sleep 2
  done
  mogo_msg sandbox_unavailable >&2
  return 1
}
