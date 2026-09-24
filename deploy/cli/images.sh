#!/usr/bin/env bash

MOVO_COMPOSE_BUILD=false
# Published images are named <registry>/<service> (ghcr.io/himovo/admin-web).
# A local source build keeps the bare service name (admin-web:latest) so local
# images never collide with the published ones.
MOVO_DEFAULT_IMAGE_REGISTRY=ghcr.io/himovo
MOVO_IMAGE_SERVICES=(
  MOVO_DSH_RUNTIME_HOST_IMAGE:dsh-runtime-host
  MOVO_CHAT_API_IMAGE:chat-api
  MOVO_ADMIN_API_IMAGE:admin-api
  MOVO_USER_WEB_IMAGE:user-web
  MOVO_ADMIN_WEB_IMAGE:admin-web
  MOVO_GATEWAY_IMAGE:gateway
)

movo_compose() {
  local compose_args=(-f "${ROOT_DIR}/docker-compose.yml")
  if [[ "${MOVO_COMPOSE_BUILD}" == "true" ]]; then
    compose_args+=(-f "${ROOT_DIR}/docker-compose.build.yml")
  fi
  "${DOCKER_BIN}" compose "${compose_args[@]}" "$@"
}

movo_export_shared_document_image() {
  MOVO_DOCUMENT_API_IMAGE="${MOVO_EXPORTED_IMAGE_PREFIX}document-parser:${MOVO_VERSION}"
  MOVO_DOCUMENT_WORKER_IMAGE="${MOVO_DOCUMENT_API_IMAGE}"
  export MOVO_DOCUMENT_API_IMAGE MOVO_DOCUMENT_WORKER_IMAGE
}

# Publish one complete image reference per service. The registry is empty for a
# source build, which is what yields the bare admin-web:latest style names.
movo_export_service_images() {
  local entry var service
  for entry in "${MOVO_IMAGE_SERVICES[@]}"; do
    var="${entry%%:*}"
    service="${entry##*:}"
    printf -v "${var}" '%s%s:%s' "${MOVO_EXPORTED_IMAGE_PREFIX}" "${service}" "${MOVO_VERSION}"
    export "${var?}"
  done
  movo_export_shared_document_image
}

movo_configure_images() {
  local source_build="${1:-false}"
  local configured_registry="${MOVO_IMAGE_REGISTRY:-$(dotenv_value MOVO_IMAGE_REGISTRY)}"
  MOVO_VERSION="${MOVO_VERSION:-$(dotenv_value MOVO_VERSION)}"
  MOVO_VERSION="${MOVO_VERSION:-latest}"
  export MOVO_VERSION

  if [[ "${source_build}" == "true" ]]; then
    # Local source build: bare service names (admin-web:latest), so they never
    # collide with the published images.
    MOVO_COMPOSE_BUILD=true
    MOVO_EXPORTED_IMAGE_PREFIX=""
  elif [[ -n "${configured_registry}" ]]; then
    MOVO_EXPORTED_IMAGE_PREFIX="${configured_registry%/}/"
  else
    MOVO_EXPORTED_IMAGE_PREFIX="${MOVO_DEFAULT_IMAGE_REGISTRY%/}/"
  fi

  MOVO_IMAGE_REGISTRY="${MOVO_EXPORTED_IMAGE_PREFIX%/}"
  export MOVO_IMAGE_REGISTRY
  movo_export_service_images
}
