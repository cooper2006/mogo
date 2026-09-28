#!/usr/bin/env bash
set -Eeuo pipefail

# Manage the Playwright browser bundle used by services/chat-api's Dockerfile.
#
# Why this exists: `playwright install --with-deps chromium` reaches out to the
# browser CDN *and* to apt for the system libraries. Both are slow and the apt
# leg fails outright whenever a distro mirror hiccups, which breaks an
# otherwise-cacheable image rebuild. With a saved bundle the build extracts the
# browsers from the build context instead of downloading ~900MB again.
#
# Layout:
#   base-images/playwright/                       local cache (git-ignored, /base-images/)
#       browsers/                                 the /ms-playwright tree as-is
#       manifest.txt                              playwright version + browser dirs
#   services/chat-api/playwright-browsers-bundle.tar.gz
#       - tracked in git as a <1KB placeholder so COPY never fails
#       - overwritten in place by `save` with the real bundle
#
# The build context is services/chat-api, so the bundle has to live there; the
# durable copy stays under base-images/ so it survives `git clean` and can be
# reused after the placeholder is restored.
#
# NOTE: the bundle covers the *browser binaries* only. The apt libraries that
# `--with-deps` would install still come from the distro mirror; cache those
# separately (base-images/apt) if a fully offline rebuild is needed.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

CONTEXT_DIR="services/chat-api"
BUNDLE_NAME="playwright-browsers-bundle.tar.gz"
BUNDLE_PATH="${CONTEXT_DIR}/${BUNDLE_NAME}"
CACHE_DIR="base-images/playwright"
BROWSERS_DIR="${CACHE_DIR}/browsers"
MANIFEST="${CACHE_DIR}/manifest.txt"

DOCKER_BIN="${DOCKER_BIN:-docker}"
IMAGE="${IMAGE:-chat-api:latest}"

usage() {
  cat <<'USAGE'
Usage:
  scripts/playwright_browsers_bundle.sh save [image]    Cache browsers from an image and
                                                        write the bundle into the build context
  scripts/playwright_browsers_bundle.sh pack            Re-pack the bundle from base-images/playwright
  scripts/playwright_browsers_bundle.sh list            Show cache + bundle status
  scripts/playwright_browsers_bundle.sh verify [image]  Check /ms-playwright inside an image

Environment:
  DOCKER_BIN        Docker binary to use (default: docker)
  IMAGE             Image for save/verify (default: chat-api:latest)

`save` defaults to chat-api:latest, which must already contain /ms-playwright
(build it once with INSTALL_PLAYWRIGHT_AT_BUILD=true). It copies the browser
tree into base-images/playwright/, records the playwright version, and packs
the bundle into the build context so later builds skip the download.
USAGE
}

die() {
  printf 'Error: %s\n' "$1" >&2
  exit 1
}

require_docker() {
  command -v "${DOCKER_BIN}" >/dev/null 2>&1 || die "Docker was not found."
  "${DOCKER_BIN}" info >/dev/null 2>&1 || die "Docker is not running."
}

# Human-readable size for a byte count.
human_size() {
  local bytes="$1"
  if [[ "${bytes}" -ge 1073741824 ]]; then
    printf '%.1f GiB' "$(echo "${bytes}" | awk '{print $1/1073741824}')"
  elif [[ "${bytes}" -ge 1048576 ]]; then
    printf '%.1f MiB' "$(echo "${bytes}" | awk '{print $1/1048576}')"
  else
    printf '%s KiB' "$((bytes / 1024))"
  fi
}

# The playwright version baked into the image; recorded so a cache taken from
# one version is never silently reused with another (browser dirs are
# version-suffixed, e.g. chromium-1194, so a mismatch is detectable).
image_playwright_version() {
  "${DOCKER_BIN}" run --rm --entrypoint sh "$1" \
    -c 'python -m playwright --version 2>/dev/null' 2>/dev/null | awk '{print $2}' || printf ''
}

cmd_save() {
  local image="${1:-${IMAGE}}"
  require_docker

  "${DOCKER_BIN}" image inspect "${image}" >/dev/null 2>&1 \
    || die "Image ${image} not found locally. Build it first (mogo build / docker compose build)."

  local version
  version="$(image_playwright_version "${image}")"
  [[ -n "${version}" ]] \
    || die "Could not read the playwright version from ${image}. Is playwright installed?"

  printf 'Caching /ms-playwright from %s (playwright %s) ...\n' "${image}" "${version}"

  mkdir -p "${CACHE_DIR}"
  local tmp_dir
  tmp_dir="$(mktemp -d)"
  trap 'rm -rf "${tmp_dir:-}"' EXIT

  # Copy the browser tree out of the image. --entrypoint sh keeps this working
  # regardless of the image's CMD.
  "${DOCKER_BIN}" run --rm --entrypoint sh "${image}" \
    -c 'tar -C / -czf - ms-playwright' > "${tmp_dir}/browsers.tgz" 2>/dev/null

  local raw_size
  raw_size="$(wc -c < "${tmp_dir}/browsers.tgz" | tr -d ' ')"
  [[ "${raw_size}" -gt 1024 ]] \
    || die "Extracted browser archive is suspiciously small (${raw_size} bytes). Was ${image} built with INSTALL_PLAYWRIGHT_AT_BUILD=true?"

  tar -xzf "${tmp_dir}/browsers.tgz" -C "${tmp_dir}"
  [[ -d "${tmp_dir}/ms-playwright" ]] || die "ms-playwright/ tree not found after extraction."

  rm -rf "${BROWSERS_DIR}"
  mkdir -p "${BROWSERS_DIR}"
  # Cache root = contents of /ms-playwright, so pack/extract round-trips
  # straight into PLAYWRIGHT_BROWSERS_PATH.
  cp -R "${tmp_dir}/ms-playwright/." "${BROWSERS_DIR}/"

  local browser_dirs
  browser_dirs="$(find "${BROWSERS_DIR}" -mindepth 1 -maxdepth 1 -type d -exec basename {} \; | sort | paste -sd ',' -)"
  {
    printf '# movo playwright browser cache\n'
    printf '# generated: %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    printf '# source image: %s\n' "${image}"
    printf 'playwright_version=%s\n' "${version}"
    printf 'browsers=%s\n' "${browser_dirs}"
  } > "${MANIFEST}"
  printf 'Wrote %s\n' "${MANIFEST}"

  cmd_pack
}

cmd_pack() {
  [[ -d "${BROWSERS_DIR}" ]] \
    || die "No cached browsers at ${BROWSERS_DIR}. Run save first."

  local count
  count="$(find "${BROWSERS_DIR}" -mindepth 1 -maxdepth 1 | wc -l | tr -d ' ')"
  [[ "${count}" -gt 0 ]] || die "${BROWSERS_DIR} is empty."

  printf 'Packing %s -> %s ...\n' "${BROWSERS_DIR}" "${BUNDLE_PATH}"
  # Bundle root = contents of /ms-playwright so the Dockerfile can extract
  # directly into PLAYWRIGHT_BROWSERS_PATH.
  tar -czf "${BUNDLE_PATH}" -C "${BROWSERS_DIR}" .

  local out_size entries
  out_size="$(wc -c < "${BUNDLE_PATH}" | tr -d ' ')"
  entries="$(tar -tzf "${BUNDLE_PATH}" | grep -c -v '/$' || true)"
  printf '\nBundle written: %s (%s, %s files)\n' \
    "${BUNDLE_PATH}" "$(human_size "${out_size}")" "${entries}"
  printf 'Rebuild the image to use it:\n'
  printf '  docker compose -f docker-compose.yml -f docker-compose.build.yml build chat-api\n'
  printf 'The COPY layer re-executes only when this tar.gz changes; same bundle = cached.\n'
}

cmd_list() {
  printf 'Playwright browser cache:\n\n'

  if [[ -d "${BROWSERS_DIR}" ]]; then
    local size
    size="$(du -sk "${BROWSERS_DIR}" | cut -f1)"
    printf '  [cache]     %s  (%s)\n' "${BROWSERS_DIR}" "$(human_size "$((size * 1024))")"
    find "${BROWSERS_DIR}" -mindepth 1 -maxdepth 1 -type d -exec basename {} \; | sort | sed 's/^/                /'
  else
    printf '  [missing]   %s  - run save first\n' "${BROWSERS_DIR}"
  fi

  if [[ -f "${MANIFEST}" ]]; then
    sed 's/^/                /' "${MANIFEST}"
  fi

  printf '\nBundle for the build context:\n\n'
  if [[ -f "${BUNDLE_PATH}" ]]; then
    local bsize
    bsize="$(wc -c < "${BUNDLE_PATH}" | tr -d ' ')"
    if [[ "${bsize}" -gt 1024 ]]; then
      printf '  [bundle]    %s  (%s)  - offline build will work\n' \
        "${BUNDLE_PATH}" "$(human_size "${bsize}")"
    else
      printf '  [placeholder] %s  (%s)  - online build path will be used\n' \
        "${BUNDLE_PATH}" "$(human_size "${bsize}")"
    fi
  else
    printf '  [missing]   %s  - run save (or restore the placeholder)\n' "${BUNDLE_PATH}"
  fi
}

cmd_verify() {
  local image="${1:-${IMAGE}}"
  require_docker
  "${DOCKER_BIN}" image inspect "${image}" >/dev/null 2>&1 \
    || die "Image ${image} not found locally."

  printf 'Checking /ms-playwright in %s ...\n' "${image}"
  "${DOCKER_BIN}" run --rm --entrypoint sh "${image}" -c '
    set -e
    [ -d /ms-playwright ] || { echo "MISSING /ms-playwright"; exit 3; }
    n=$(find /ms-playwright -maxdepth 1 -mindepth 1 -type d | wc -l | tr -d " ")
    sz=$(du -sh /ms-playwright | cut -f1)
    echo "  browser dirs: ${n}  size: ${sz}"
    ver=$(python -m playwright --version 2>/dev/null || echo unknown)
    echo "  ${ver}"
    # A chromium build is only usable when the headless shell binary exists and
    # is executable; an interrupted download leaves the directory present but
    # empty, which would otherwise pass a naive existence check.
    ok=0
    for d in /ms-playwright/chromium*-*; do
      [ -d "$d" ] || continue
      if [ -x "$d/chrome-linux/headless_shell" ] || [ -x "$d/chrome-linux/chrome" ]; then
        echo "  OK: $(basename "$d")"
        ok=1
      else
        echo "  BAD: $(basename "$d") has no runnable browser binary"
      fi
    done
    [ "${ok}" -eq 1 ] || { echo "  no runnable chromium found"; exit 4; }
  '
}

command="${1:-list}"
if [[ $# -gt 0 ]]; then
  shift
fi

case "${command}" in
  save)
    cmd_save "${1:-}"
    ;;
  pack)
    cmd_pack
    ;;
  list)
    cmd_list
    ;;
  verify)
    cmd_verify "${1:-}"
    ;;
  help|-h|--help)
    usage
    ;;
  *)
    printf 'Unknown command: %s\n\n' "${command}" >&2
    usage >&2
    exit 2
    ;;
esac
