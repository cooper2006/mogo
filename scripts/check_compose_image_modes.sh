#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

# Published images are named <registry>/<service>, for example
# ghcr.io/himovo/admin-web. A local source build exports bare service names
# (admin-web:latest) so local images never collide with the published ones.
official_registry="ghcr.io/himovo"
image_suffixes=(
  dsh-runtime-host
  chat-api
  admin-api
  document-parser
  user-web
  admin-web
  gateway
)

compose_images() {
  env \
    -u MOVO_IMAGE_REGISTRY \
    -u MOVO_VERSION \
    -u MOVO_DOCUMENT_API_IMAGE \
    -u MOVO_DOCUMENT_WORKER_IMAGE \
    -u MOVO_DSH_RUNTIME_HOST_IMAGE \
    -u MOVO_CHAT_API_IMAGE \
    -u MOVO_ADMIN_API_IMAGE \
    -u MOVO_USER_WEB_IMAGE \
    -u MOVO_ADMIN_WEB_IMAGE \
    -u MOVO_GATEWAY_IMAGE \
    docker compose --env-file /dev/null "$@" config --images
}

# Default (prebuilt) path: every service resolves to <registry>/<service>.
prebuilt_images="$(compose_images -f docker-compose.yml)"
for suffix in "${image_suffixes[@]}"; do
  grep -Fxq "${official_registry}/${suffix}:latest" <<<"${prebuilt_images}"
done

# Source-build path: the CLI exports bare service names.
source_env="$(
  (
    unset MOVO_IMAGE_REGISTRY MOVO_VERSION
    ROOT_DIR="${ROOT_DIR}"
    DOCKER_BIN=docker
    # shellcheck source=../deploy/cli/images.sh
    source "${ROOT_DIR}/deploy/cli/images.sh"
    dotenv_value() { printf ''; }

    movo_configure_images true
    for entry in "${MOVO_IMAGE_SERVICES[@]}"; do
      var="${entry%%:*}"
      printf '%s=%s\n' "${var}" "${!var}"
    done
    printf 'MOVO_DOCUMENT_API_IMAGE=%s\n' "${MOVO_DOCUMENT_API_IMAGE}"
  )
)"
# Resolve the source-build images service by service. A bare
# ``config --images`` also reports the image of *running* containers, which
# makes the check depend on the developer's local state.
source_images=""
while IFS= read -r line; do
  var="${line%%=*}"
  value="${line#*=}"
  suffix="${var#MOVO_}"; suffix="${suffix%_IMAGE}"
  suffix="$(printf '%s' "${suffix}" | tr '[:upper:]' '[:lower:]' | tr '_' '-')"
  [[ "${suffix}" == "document-api" ]] && suffix="document-parser"
  source_images+="${value}"$'\n'
done <<<"${source_env}"
for suffix in "${image_suffixes[@]}"; do
  grep -Fxq "${suffix}:latest" <<<"${source_images}"
done

# No image name may keep the legacy movo- prefix.
if grep -Eq "(^|/)movo-[a-z]" <<<"${prebuilt_images}${source_images}"; then
  printf 'Images must not use the legacy movo- prefix.\n' >&2
  exit 1
fi

# CLI configuration invariants.
(
  unset MOVO_IMAGE_REGISTRY MOVO_VERSION MOVO_BUILD_IMAGE_REGISTRY
  ROOT_DIR="${ROOT_DIR}"
  DOCKER_BIN=docker
  # shellcheck source=../deploy/cli/images.sh
  source "${ROOT_DIR}/deploy/cli/images.sh"
  dotenv_value() { printf ''; }

  movo_configure_images false
  [[ "${MOVO_ADMIN_WEB_IMAGE}" == "${official_registry}/admin-web:latest" ]]
  [[ "${MOVO_DOCUMENT_API_IMAGE}" == "${official_registry}/document-parser:latest" ]]

  unset MOVO_DOCUMENT_API_IMAGE MOVO_DOCUMENT_WORKER_IMAGE
  movo_configure_images true
  [[ "${MOVO_ADMIN_WEB_IMAGE}" == "admin-web:latest" ]]
  [[ "${MOVO_DOCUMENT_API_IMAGE}" == "document-parser:latest" ]]
)

printf 'Compose image modes are valid.\n'
