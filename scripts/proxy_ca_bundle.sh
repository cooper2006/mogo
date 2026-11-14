#!/usr/bin/env bash
set -Eeuo pipefail

# Manage the proxy root CA bundle used by the pip legs of the sandbox images.
#
# Why this exists: pip ships its own CA bundle (vendored certifi) and ignores
# the system trust store. On a host whose egress goes through a
# TLS-terminating proxy, the server certificate chains to a private root CA
# that the proxy's own store trusts but pip's bundle does not, so every pip
# invocation dies with
#
#   SSLCertVerificationError: [SSL: CERTIFICATE_VERIFY_FAILED]
#   certificate verify failed: unable to get local issuer certificate
#
# while the same host verifies the same host fine through the system CA
# bundle. The fix is to hand pip a bundle that contains the proxy's root in
# addition to the distro roots.
#
# Layout:
#   base-images/ca/proxy-root.crt   the proxy's root CA(s), PEM
#   services/sandbox-manager/proxy-root.crt   copy for that build context
#   services/chat-api/proxy-root.crt         copy for that build context
#
# Same contract as the other bundles (scripts/apt_packages_bundle.sh and
# friends): the file is NOT tracked in git, so a fresh clone has to run
# `pack` once before `docker build` resolves the bind mount. The mount fails
# loudly when the source is missing, which is deliberate -- a build that
# silently fell back to pip's own bundle would fail later with a confusing
# TLS error instead.
#
# Usage:
#   bash scripts/proxy_ca_bundle.sh pack    copy the CA into the build contexts
#   bash scripts/proxy_ca_bundle.sh export  capture the CA from a running
#                                           container (the host's proxy injects
#                                           it into /etc/ssl/certs at runtime)
#   bash scripts/proxy_ca_bundle.sh status  show what is in place

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

CA_CACHE="base-images/ca/proxy-root.crt"
TARGETS=(
  "services/sandbox-manager/proxy-root.crt"
  "services/chat-api/proxy-root.crt"
)

usage() {
  cat <<'EOF'
Usage: bash scripts/proxy_ca_bundle.sh <command>

  pack    Copy base-images/ca/proxy-root.crt into every build context that
          mounts it. Run this once after cloning, before docker build.
  export  Capture the proxy root CA from a running container (the host proxy
          injects it into the container's CA store at runtime) and store it in
          base-images/ca/proxy-root.crt.
  status  Report which build contexts have the CA in place.
EOF
}

# Copy the cached CA into every build context.
cmd_pack() {
  if [[ ! -s "${CA_CACHE}" ]]; then
    printf 'Missing %s.\n' "${CA_CACHE}" >&2
    printf 'Run `bash scripts/proxy_ca_bundle.sh export` first, or copy the proxy CA there by hand.\n' >&2
    return 1
  fi

  local target
  for target in "${TARGETS[@]}"; do
    mkdir -p "$(dirname "${target}")"
    cp "${CA_CACHE}" "${target}"
    printf '  [ok] %s\n' "${target}"
  done
}
# Capture the CA from a running container. The host's proxy adds its root to
# the container's CA store at runtime (it is not part of the image layer), so
# a running container is the only place to read it from.
cmd_export() {
  local container="${1:-}"
  if [[ -z "${container}" ]]; then
    container="$(docker ps --filter ancestor=alpine:3.21 --format '{{.ID}}' | head -1)"
  fi
  if [[ -z "${container}" ]]; then
    printf 'No container to read the CA from. Pass one explicitly:\n' >&2
    printf '  bash scripts/proxy_ca_bundle.sh export <container>\n' >&2
    return 1
  fi

  mkdir -p "$(dirname "${CA_CACHE}")"
  if ! docker exec "${container}" cat /etc/ssl/certs/orbstack-root.crt > "${CA_CACHE}"; then
    printf 'Could not read the proxy CA from %s.\n' "${container}" >&2
    return 1
  fi
  printf 'Stored %s (%s bytes).\n' "${CA_CACHE}" "$(wc -c < "${CA_CACHE}" | tr -d ' ')"
}

cmd_status() {
  local target missing=0
  for target in "${TARGETS[@]}"; do
    if [[ -s "${target}" ]]; then
      printf '  [ok] %s\n' "${target}"
    else
      printf '  [missing] %s - run pack (the bind mount fails until this exists)\n' "${target}"
      missing=1
    fi
  done
  return "${missing}"
}

main() {
  case "${1:-}" in
    pack) cmd_pack ;;
    export) cmd_export "${2:-}" ;;
    status) cmd_status ;;
    ""|-h|--help|help) usage ;;
    *)
      printf 'Unknown command: %s\n\n' "$1" >&2
      usage >&2
      return 1
      ;;
  esac
}

main "$@"
