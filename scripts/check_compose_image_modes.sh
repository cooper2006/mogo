#!/usr/bin/env bash
set -Eeuo pipefail

# Mutations for scripts/verify_assertions.sh — each one breaks something this
# script is supposed to guard, so the mutated copy must exit non-zero. If a
# mutation leaves the script passing, the corresponding assertion is dead.
# MUTATION: prebuilt-prefix-check | src.replace('grep -Fxq "${official_registry}/${suffix}:latest"', 'grep -Fxq "ghcr.io/mogoai/mogo-${suffix}:latest"', 1) | prebuilt compose image must match <registry>/<service>
# MUTATION: registry-override-broken | src.replace('  MOGO_IMAGE_REGISTRY="registry.example.com/team"\n', '', 1) | MOGO_IMAGE_REGISTRY override assertion

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

# Published images are named <registry>/<service>, for example
# ghcr.io/mogoai/admin-web. A local source build exports bare service names
# (admin-web:latest) so local images never collide with the published ones.
official_registry="ghcr.io/mogoai"
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
    -u MOGO_IMAGE_REGISTRY \
    -u MOGO_EXPORTED_IMAGE_PREFIX \
    -u MOGO_IMAGE_PREFIX \
    -u MOGO_VERSION \
    -u MOGO_DOCUMENT_API_IMAGE \
    -u MOGO_DOCUMENT_WORKER_IMAGE \
    -u MOGO_DSH_RUNTIME_HOST_IMAGE \
    -u MOGO_CHAT_API_IMAGE \
    -u MOGO_ADMIN_API_IMAGE \
    -u MOGO_USER_WEB_IMAGE \
    -u MOGO_ADMIN_WEB_IMAGE \
    -u MOGO_GATEWAY_IMAGE \
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
    unset MOGO_IMAGE_REGISTRY MOGO_EXPORTED_IMAGE_PREFIX MOGO_IMAGE_PREFIX MOGO_VERSION
    ROOT_DIR="${ROOT_DIR}"
    DOCKER_BIN=docker
    # shellcheck source=../deploy/cli/images.sh
    source "${ROOT_DIR}/deploy/cli/images.sh"
    dotenv_value() { printf ''; }

    mogo_configure_images true
    for entry in "${MOGO_IMAGE_SERVICES[@]}"; do
      var="${entry%%:*}"
      printf '%s=%s\n' "${var}" "${!var}"
    done
    printf 'MOGO_DOCUMENT_API_IMAGE=%s\n' "${MOGO_DOCUMENT_API_IMAGE}"
  )
)"
# Resolve the source-build images service by service. A bare
# ``config --images`` also reports the image of *running* containers, which
# makes the check depend on the developer's local state.
source_images=""
while IFS= read -r line; do
  var="${line%%=*}"
  value="${line#*=}"
  suffix="${var#MOGO_}"; suffix="${suffix%_IMAGE}"
  suffix="$(printf '%s' "${suffix}" | tr '[:upper:]' '[:lower:]' | tr '_' '-')"
  [[ "${suffix}" == "document-api" ]] && suffix="document-parser"
  source_images+="${value}"$'\n'
done <<<"${source_env}"
for suffix in "${image_suffixes[@]}"; do
  grep -Fxq "${suffix}:latest" <<<"${source_images}"
done

# No image name may keep the legacy `<prefix>-<service>` form, which the retired
# MOGO_IMAGE_PREFIX would have produced (e.g. ghcr.io/mogoai/mogo-chat-api).
# Match the prefix only as part of a name, never as the registry path itself:
# the legitimate registry is ghcr.io/mogoai.
if grep -Eq "(^|/)mogo-[a-z]" <<<"${prebuilt_images}${source_images}"; then
  printf 'Images must not use the legacy <prefix>-<service> form.\n' >&2
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
  unset MOGO_IMAGE_REGISTRY MOGO_EXPORTED_IMAGE_PREFIX MOGO_IMAGE_PREFIX \
    MOGO_VERSION MOGO_BUILD_IMAGE_REGISTRY
  ROOT_DIR="${ROOT_DIR}"
  DOCKER_BIN=docker
  # shellcheck source=../deploy/cli/images.sh
  source "${ROOT_DIR}/deploy/cli/images.sh"
  dotenv_value() { printf ''; }

  mogo_configure_images false
  assert_image "${MOGO_ADMIN_WEB_IMAGE}" "${official_registry}/admin-web:latest" \
    "prebuilt admin-web image"
  assert_image "${MOGO_DOCUMENT_API_IMAGE}" "${official_registry}/document-parser:latest" \
    "prebuilt document-parser image"

  unset MOGO_DOCUMENT_API_IMAGE MOGO_DOCUMENT_WORKER_IMAGE
  mogo_configure_images true
  assert_image "${MOGO_ADMIN_WEB_IMAGE}" "admin-web:latest" "source-build admin-web image"
  assert_image "${MOGO_DOCUMENT_API_IMAGE}" "document-parser:latest" \
    "source-build document-parser image"
)

# MOGO_IMAGE_REGISTRY must override the default registry.
(
  # 版本变量同样要清：CI 把 MOGO_VERSION=${{ github.ref_name }} 注入本步，泄漏进
  # 该子壳会把断言的 :latest 变成 :<branch> 而假失败（其余子壳均已清）。
  unset MOGO_EXPORTED_IMAGE_PREFIX MOGO_IMAGE_PREFIX MOGO_VERSION
  ROOT_DIR="${ROOT_DIR}"
  DOCKER_BIN=docker
  source "${ROOT_DIR}/deploy/cli/images.sh"
  dotenv_value() { printf ''; }
  MOGO_IMAGE_REGISTRY="registry.example.com/team"
  mogo_configure_images false
  assert_image "${MOGO_CHAT_API_IMAGE}" "registry.example.com/team/chat-api:latest" \
    "MOGO_IMAGE_REGISTRY override"
)

# The retired MOGO_IMAGE_PREFIX must be ignored: its old "name prefix" meaning
# cannot be expressed as <registry>/<service>, so it must never produce a path
# such as ghcr.io/mogoai/mogo-chat-api nor leak a mogo-<service> name.
(
  # 清版本变量防 CI 环境泄漏（同上）。
  unset MOGO_IMAGE_REGISTRY MOGO_EXPORTED_IMAGE_PREFIX MOGO_VERSION
  ROOT_DIR="${ROOT_DIR}"
  DOCKER_BIN=docker
  source "${ROOT_DIR}/deploy/cli/images.sh"
  dotenv_value() { printf ''; }
  MOGO_IMAGE_PREFIX="ghcr.io/mogoai"
  mogo_configure_images false 2>/dev/null
  assert_image "${MOGO_CHAT_API_IMAGE}" "${official_registry}/chat-api:latest" \
    "retired MOGO_IMAGE_PREFIX ignored"
  # Match the legacy name-prefix form only; a naive *"mogo/"* test would also
  # match the legitimate registry path "ghcr.io/mogoai/".
  case "${MOGO_CHAT_API_IMAGE}" in
    mogo-*|*/mogo-*)
      printf 'FAIL: retired MOGO_IMAGE_PREFIX leaked into %s\n' "${MOGO_CHAT_API_IMAGE}" >&2
      exit 1
      ;;
  esac
)

# MOGO_EXPORTED_IMAGE_PREFIX remains the documented override.
(
  # 清版本变量防 CI 环境泄漏（同上）。
  unset MOGO_IMAGE_REGISTRY MOGO_IMAGE_PREFIX MOGO_VERSION
  ROOT_DIR="${ROOT_DIR}"
  DOCKER_BIN=docker
  source "${ROOT_DIR}/deploy/cli/images.sh"
  dotenv_value() { printf ''; }
  MOGO_EXPORTED_IMAGE_PREFIX="ghcr.io/other"
  mogo_configure_images false
  assert_image "${MOGO_CHAT_API_IMAGE}" "ghcr.io/other/chat-api:latest" \
    "MOGO_EXPORTED_IMAGE_PREFIX override"
)

# --- Security baseline (024 T015) ---
# Every business container must run non-root with a read-only root filesystem,
# all capabilities dropped and no-new-privileges — the four invariants behind
# the QF-818 fix. Validated directly from docker-compose.yml so the check does
# not depend on a running docker daemon or override files.
security_baseline_services=(
  chat-api
  admin-api
  document-api
  document-worker
  user-web
  admin-web
  gateway
)
python3 - "${ROOT_DIR}/docker-compose.yml" "${security_baseline_services[@]}" <<'PY'
import sys
import yaml

path = sys.argv[1]
services = sys.argv[2:]
with open(path) as f:
    dc = yaml.safe_load(f)

fail = 0
for name in services:
    svc = dc.get("services", {}).get(name)
    if svc is None:
        print(f"FAIL: {name} not found in compose", file=sys.stderr)
        fail = 1
        continue
    user = svc.get("user")
    read_only = svc.get("read_only")
    cap_drop = svc.get("cap_drop") or []
    nnp = any(
        str(x).startswith("no-new-privileges:true")
        for x in (svc.get("security_opt") or [])
    )
    errors = []
    if not user or user in ("0", "0:0", "root"):
        errors.append("user is missing or root")
    if read_only is not True:
        errors.append("read_only is not true")
    if "ALL" not in cap_drop:
        errors.append("cap_drop does not drop ALL")
    if not nnp:
        errors.append("no-new-privileges not enabled")
    if errors:
        print(f"FAIL: {name}: " + "; ".join(errors), file=sys.stderr)
        fail = 1
    else:
        print(f"OK: {name}: user={user} read_only=true cap_drop=ALL no-new-privileges=true")
sys.exit(1 if fail else 0)
PY

# --- Compose vs build.yml consistency (024 B003) ---
# docker-compose.yml and docker-compose.build.yml must describe the same set of
# buildable business services: every service build.yml knows must exist in
# compose, and every buildable business service in compose must exist in
# build.yml. External/infra services (databases, caches, ha clones, canary
# variants, init containers) are exempt by design.
business_services=(
  chat-api
  admin-api
  document-api
  document-worker
  user-web
  admin-web
  gateway
  dsh-runtime-host
)
python3 - "${ROOT_DIR}/docker-compose.yml" "${ROOT_DIR}/docker-compose.build.yml" \
  "${business_services[@]}" <<'PY'
import sys
import yaml

with open(sys.argv[1]) as f:
    compose_services = set((yaml.safe_load(f) or {}).get("services", {}).keys())
with open(sys.argv[2]) as f:
    build_services = set((yaml.safe_load(f) or {}).get("services", {}).keys())
business = set(sys.argv[3:])

fail = 0
# 1) Every build.yml service must exist in compose.
for s in sorted(build_services):
    if s not in compose_services:
        print(f"FAIL: {s} is in docker-compose.build.yml but missing from docker-compose.yml",
              file=sys.stderr)
        fail = 1
# 2) Every buildable business service in compose must exist in build.yml.
for s in sorted(business):
    if s in compose_services and s not in build_services:
        print(f"FAIL: {s} is a buildable business service in docker-compose.yml but "
              f"missing from docker-compose.build.yml", file=sys.stderr)
        fail = 1
# 3) build.yml must not define services outside compose at all (no orphans).
orphans = build_services - compose_services
if orphans:
    print(f"FAIL: build.yml defines services absent from compose: {sorted(orphans)}",
          file=sys.stderr)
    fail = 1

if fail:
    sys.exit(1)
print(f"OK: compose/build.yml consistency: {len(build_services)} build services all present")
sys.exit(0)
PY

printf 'Compose image modes are valid.\n'
