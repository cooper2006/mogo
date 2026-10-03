#!/usr/bin/env bash
set -Eeuo pipefail

# Mutations for scripts/verify_assertions.sh — each one breaks something this
# script is supposed to guard, so the mutated copy must exit non-zero. If a
# mutation leaves the script passing, the corresponding assertion is dead.
# MUTATION: legacy-prefix-honoured | src.replace('  MOVO_IMAGE_PREFIX="ghcr.io/himovo/movo"\n  movo_configure_images false', '  MOVO_IMAGE_PREFIX="ghcr.io/himovo/movo"\n  configured_registry="${legacy_prefix}"\n  movo_configure_images false', 1) | the legacy prefix must never be used as a registry
# MUTATION: prebuilt-prefix-check | src.replace('grep -Fxq "${official_registry}/${suffix}:latest"', 'grep -Fxq "ghcr.io/himovo/movo-${suffix}:latest"', 1) | prebuilt compose image must match <registry>/<service>
# MUTATION: registry-override-broken | src.replace('  MOVO_IMAGE_REGISTRY="registry.example.com/team"\n', '', 1) | MOVO_IMAGE_REGISTRY override assertion

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
    -u MOVO_EXPORTED_IMAGE_PREFIX \
    -u MOVO_IMAGE_PREFIX \
    -u MOGO_VERSION \
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
    unset MOVO_IMAGE_REGISTRY MOVO_EXPORTED_IMAGE_PREFIX MOVO_IMAGE_PREFIX MOGO_VERSION MOVO_VERSION
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

# Assert a CLI-invariant expectation with an explicit failure branch.
#
# A bare `[[ ... ]]` is not portable as an assertion: on bash 3.2 (the version
# shipped with macOS) a failing `[[ ]]` does NOT trigger errexit, so the check
# silently passes locally while correctly failing on the bash 5.x used by CI.
# `test` / `[ ]` and external commands do abort on both versions, but an explicit
# `if` keeps the intent obvious and the behaviour identical everywhere.
# See scripts/test_serial_image_pull.sh for the same pattern.
assert_image() {
  local actual="$1" expected="$2" label="$3"
  if [[ "${actual}" != "${expected}" ]]; then
    printf 'FAIL: %s\n  expected: %s\n  actual:   %s\n' "${label}" "${expected}" "${actual}" >&2
    exit 1
  fi
}

# CLI configuration invariants.
(
  unset MOVO_IMAGE_REGISTRY MOVO_EXPORTED_IMAGE_PREFIX MOVO_IMAGE_PREFIX \
    MOGO_VERSION MOVO_VERSION MOVO_BUILD_IMAGE_REGISTRY
  ROOT_DIR="${ROOT_DIR}"
  DOCKER_BIN=docker
  # shellcheck source=../deploy/cli/images.sh
  source "${ROOT_DIR}/deploy/cli/images.sh"
  dotenv_value() { printf ''; }

  movo_configure_images false
  assert_image "${MOVO_ADMIN_WEB_IMAGE}" "${official_registry}/admin-web:latest" \
    "prebuilt admin-web image"
  assert_image "${MOVO_DOCUMENT_API_IMAGE}" "${official_registry}/document-parser:latest" \
    "prebuilt document-parser image"

  unset MOVO_DOCUMENT_API_IMAGE MOVO_DOCUMENT_WORKER_IMAGE
  movo_configure_images true
  assert_image "${MOVO_ADMIN_WEB_IMAGE}" "admin-web:latest" "source-build admin-web image"
  assert_image "${MOVO_DOCUMENT_API_IMAGE}" "document-parser:latest" \
    "source-build document-parser image"
)

# MOVO_IMAGE_REGISTRY must override the default registry.
(
  unset MOVO_EXPORTED_IMAGE_PREFIX MOVO_IMAGE_PREFIX
  ROOT_DIR="${ROOT_DIR}"
  DOCKER_BIN=docker
  source "${ROOT_DIR}/deploy/cli/images.sh"
  dotenv_value() { printf ''; }
  MOVO_IMAGE_REGISTRY="registry.example.com/team"
  movo_configure_images false
  assert_image "${MOVO_CHAT_API_IMAGE}" "registry.example.com/team/chat-api:latest" \
    "MOVO_IMAGE_REGISTRY override"
)

# The legacy MOVO_IMAGE_PREFIX must be ignored: its old "name prefix" meaning
# cannot be expressed as <registry>/<service>, so it must never produce a path
# such as ghcr.io/himovo/movo/chat-api nor leak a movo- image name.
(
  unset MOVO_IMAGE_REGISTRY MOVO_EXPORTED_IMAGE_PREFIX
  ROOT_DIR="${ROOT_DIR}"
  DOCKER_BIN=docker
  source "${ROOT_DIR}/deploy/cli/images.sh"
  dotenv_value() { printf ''; }
  MOVO_IMAGE_PREFIX="ghcr.io/himovo/movo"
  movo_configure_images false 2>/dev/null
  assert_image "${MOVO_CHAT_API_IMAGE}" "${official_registry}/chat-api:latest" \
    "legacy MOVO_IMAGE_PREFIX ignored"
  # Match the legacy prefix only as a path segment or name prefix; a naive
  # *"movo/"* test also matches the legitimate registry "ghcr.io/himovo/".
  case "${MOVO_CHAT_API_IMAGE}" in
    */movo/*|movo-*|*/movo-*)
      printf 'FAIL: legacy MOVO_IMAGE_PREFIX leaked into %s\n' "${MOVO_CHAT_API_IMAGE}" >&2
      exit 1
      ;;
  esac
)

# MOVO_EXPORTED_IMAGE_PREFIX remains the documented override.
(
  unset MOVO_IMAGE_REGISTRY MOVO_IMAGE_PREFIX
  ROOT_DIR="${ROOT_DIR}"
  DOCKER_BIN=docker
  source "${ROOT_DIR}/deploy/cli/images.sh"
  dotenv_value() { printf ''; }
  MOVO_EXPORTED_IMAGE_PREFIX="ghcr.io/other"
  movo_configure_images false
  assert_image "${MOVO_CHAT_API_IMAGE}" "ghcr.io/other/chat-api:latest" \
    "MOVO_EXPORTED_IMAGE_PREFIX override"
)

printf 'Compose image modes are valid.\n'
