#!/usr/bin/env bash

MOGO_COMPOSE_BUILD=false
# Published images are named <registry>/<service> (ghcr.io/mogoai/admin-web).
# A local source build keeps the bare service name (admin-web:latest) so local
# images never collide with the published ones.
MOGO_DEFAULT_IMAGE_REGISTRY=ghcr.io/mogoai
MOGO_IMAGE_SERVICES=(
  MOGO_DSH_RUNTIME_HOST_IMAGE:dsh-runtime-host
  MOGO_CHAT_API_IMAGE:chat-api
  MOGO_ADMIN_API_IMAGE:admin-api
  MOGO_USER_WEB_IMAGE:user-web
  MOGO_ADMIN_WEB_IMAGE:admin-web
  MOGO_GATEWAY_IMAGE:gateway
)

# True when MOGO_DATA_BACKEND selects the PanWeiDB backend.
#
# This is the *intent* switch -- what the services connect to, and the only thing
# that may make a deployment fail for a missing image. Resolution mirrors
# compose's own precedence: the exported variable wins, then the .env file (which
# `docker compose` also reads).
mogo_panweidb_backend_selected() {
  local backend
  # `${VAR+x}` (not `${VAR:-}`) so that a deliberately-empty MOGO_DATA_BACKEND is
  # treated as "set to empty", exactly like compose's `${MOGO_DATA_BACKEND:-mongo}`
  # does: empty resolves to the mongo default, it does not fall through to .env.
  if [[ -n "${MOGO_DATA_BACKEND+x}" ]]; then
    backend="${MOGO_DATA_BACKEND}"
  else
    backend="$(dotenv_value MOGO_DATA_BACKEND)"
  fi
  # Trim and lower-case: the services resolve the same variable with
  # `raw.strip().lower()` (app/core/config.py) and the field has been written as
  # `PanWeiDB`. A raw string compare here would let the CLI and the apps disagree
  # about which backend is live.
  backend="${backend#"${backend%%[![:space:]]*}"}"
  backend="${backend%"${backend##*[![:space:]]}"}"
  backend="$(printf '%s' "${backend}" | tr '[:upper:]' '[:lower:]')"
  [[ "${backend}" == "panweidb" ]]
}

# True when the `panweidb` compose profile has to be passed for the lifecycle to
# stay closed.
#
# `panweidb` is a profile, not a default service: the image is local-only (arm64,
# shipped from base-images/images/arm64) and the default backend stays `mongo`,
# so a plain `./mogo up` must keep creating exactly the stack it created before.
# Turning MOGO_DATA_BACKEND=panweidb on therefore has to carry the database into
# the topology in the same breath -- otherwise the apps start and sit behind
# `depends_on: panweidb: service_healthy` waiting on a service that was never
# created.
#
# The second check covers the other direction: once the container exists it stays
# under management even if the backend switch is later flipped back to `mongo`,
# so `./mogo down` / `stop` / `restart` still take the database down instead of
# leaving it running outside the stack. The probe is best-effort and never fails
# the caller: `mogo_compose` runs it on every command, including on hosts where
# the daemon is unreachable, and a lookup error simply means "not enabled".
mogo_panweidb_enabled() {
  if mogo_panweidb_backend_selected; then
    return 0
  fi
  local existing=""
  existing="$("${DOCKER_BIN}" ps -aq \
    --filter "label=com.docker.compose.service=panweidb" 2>/dev/null | head -n 1 || true)"
  [[ -n "${existing}" ]]
}

# 把 profile 并进 COMPOSE_PROFILES 并导出。
#
# 这是 profile 的唯一投递通道，理由见 mogo_compose：compose 命令行上的
# `--profile` 会**覆盖** COMPOSE_PROFILES 而不是与之取并集。
mogo_enable_compose_profile() {
  local want="${1:-}"
  [[ -n "${want}" ]] || return 0
  # `mogo` 里 env-profiles.sh 在 images.sh 之后才 source；只 source 了 images.sh
  # 的脚本（scripts/check_compose_image_modes.sh）走下面的兜底实现。
  if declare -F mogo_profile_add_compose_profile >/dev/null 2>&1; then
    mogo_profile_add_compose_profile "${want}"
    return 0
  fi
  local existing="${COMPOSE_PROFILES:-}"
  case ",${existing}," in
    *",${want},"*)
      export COMPOSE_PROFILES="${existing}"
      return 0
      ;;
  esac
  if [[ -n "${existing}" ]]; then
    export COMPOSE_PROFILES="${existing},${want}"
  else
    export COMPOSE_PROFILES="${want}"
  fi
}

mogo_compose() {
  local compose_args=(-f "${ROOT_DIR}/docker-compose.yml")
  if [[ "${MOGO_COMPOSE_BUILD}" == "true" ]]; then
    compose_args+=(-f "${ROOT_DIR}/docker-compose.build.yml")
  fi
  # 外部数据库模式：把栈内 mongo / redis / panweidb 排除出拓扑，应用只连 .env
  # 里配的外部实例（MOGO_MONGODB_URI / MOGO_REDIS_URL / PANWEIDB_*）。
  if [[ "${MOGO_USE_EXTERNAL_DB:-}" == "1" ]]; then
    compose_args+=(-f "${ROOT_DIR}/docker-compose.external.yml")
  elif mogo_panweidb_enabled; then
    # 内部模式才需要把 panweidb 容器带进拓扑；外部模式下 PanWeiDB 也是外部的，
    # 靠 PANWEIDB_HOST 指过去（override 文件已把内部 panweidb 排除）。
    #
    # 只走 COMPOSE_PROFILES，不要写成 `--profile panweidb`：实测 docker compose
    # 5.5.0 里命令行 --profile 会覆盖（而非并集）COMPOSE_PROFILES，一旦带上它，
    # env-profiles.sh 导出的 dev/test/prod 全部失效 —— `./mogo down` 会漏掉
    # mongo 等别的环境的数据库容器，并把所属网络报成 "Resource is still in use"。
    mogo_enable_compose_profile panweidb
  fi
  "${DOCKER_BIN}" compose "${compose_args[@]}" "$@"
}

mogo_export_shared_document_image() {
  MOGO_DOCUMENT_API_IMAGE="${MOGO_EXPORTED_IMAGE_PREFIX}document-parser:${MOGO_VERSION}"
  MOGO_DOCUMENT_WORKER_IMAGE="${MOGO_DOCUMENT_API_IMAGE}"
  export MOGO_DOCUMENT_API_IMAGE MOGO_DOCUMENT_WORKER_IMAGE
}

# Publish one complete image reference per service. The registry is empty for a
# source build, which is what yields the bare admin-web:latest style names.
mogo_export_service_images() {
  local entry var service
  for entry in "${MOGO_IMAGE_SERVICES[@]}"; do
    var="${entry%%:*}"
    service="${entry##*:}"
    printf -v "${var}" '%s%s:%s' "${MOGO_EXPORTED_IMAGE_PREFIX}" "${service}" "${MOGO_VERSION}"
    export "${var?}"
  done
  mogo_export_shared_document_image
}

mogo_configure_images() {
  local source_build="${1:-false}"
  local configured_registry="${MOGO_IMAGE_REGISTRY:-}"
  if [ -z "${configured_registry}" ]; then
    configured_registry="$(dotenv_value MOGO_IMAGE_REGISTRY)"
  fi

  # MOGO_IMAGE_PREFIX is a legacy variable from before the image rename. Its old
  # semantics were a *name prefix* (`${MOGO_IMAGE_PREFIX}-chat-api` →
  # ghcr.io/mogoai/mogo-chat-api), which no longer matches the
  # `<registry>/<service>` form the release pipeline publishes
  # (ghcr.io/mogoai/chat-api). It is therefore ignored with a warning
  # and the default registry is used instead. Set MOGO_IMAGE_REGISTRY to point
  # at a different registry.
  local legacy_prefix="${MOGO_IMAGE_PREFIX:-$(dotenv_value MOGO_IMAGE_PREFIX)}"
  if [[ -n "${legacy_prefix}" ]]; then
    printf 'Warning: MOGO_IMAGE_PREFIX=%s is no longer supported (images were renamed from\n' "${legacy_prefix}" >&2
    printf '  %s-<service> to <registry>/<service>). It is being ignored.\n' "${legacy_prefix}" >&2
    printf '  Set MOGO_IMAGE_REGISTRY (e.g. ghcr.io/mogoai) instead.\n' >&2
  fi

  local configured_prefix="${MOGO_EXPORTED_IMAGE_PREFIX:-$(dotenv_value MOGO_EXPORTED_IMAGE_PREFIX)}"
  if [[ -n "${configured_prefix}" && -z "${configured_registry}" ]]; then
    configured_registry="${configured_prefix}"
  fi

  MOGO_VERSION="${MOGO_VERSION:-$(dotenv_value MOGO_VERSION)}"
  MOGO_VERSION="${MOGO_VERSION:-latest}"
  export MOGO_VERSION

  if [[ "${source_build}" == "true" ]]; then
    # Local source build: bare service names (admin-web:latest), so they never
    # collide with the published images.
    MOGO_COMPOSE_BUILD=true
    MOGO_EXPORTED_IMAGE_PREFIX=""
  elif [[ -n "${configured_registry}" ]]; then
    MOGO_EXPORTED_IMAGE_PREFIX="${configured_registry%/}/"
  else
    MOGO_EXPORTED_IMAGE_PREFIX="${MOGO_DEFAULT_IMAGE_REGISTRY%/}/"
  fi

  MOGO_IMAGE_REGISTRY="${MOGO_EXPORTED_IMAGE_PREFIX%/}"
  export MOGO_IMAGE_REGISTRY
  mogo_export_service_images
}
