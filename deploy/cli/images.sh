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

mogo_compose() {
  local compose_args=(-f "${ROOT_DIR}/docker-compose.yml")
  if [[ "${MOGO_COMPOSE_BUILD}" == "true" ]]; then
    compose_args+=(-f "${ROOT_DIR}/docker-compose.build.yml")
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
