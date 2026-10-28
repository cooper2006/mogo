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
#       - NOT tracked in git (as of 2026-10-21: git rm --cached, ignored)
#       - generated here by `save`; the Dockerfile's COPY needs it present
#
# IMPORTANT: because the bundle is no longer tracked, a fresh clone has no
# bundle file at all and `docker build` fails at the COPY line until you run
# `save` once. The real bundle is kept out of git so it never enters history;
# `.local-bundles/` holds a local copy.
#
# The build context is services/chat-api, so the bundle has to live there; the
# durable copy stays under base-images/ so it survives `git clean` and can be
# reused after the bundle is regenerated.
#
# NOTE: the bundle covers the *browser binaries* only. The apt libraries that
# `--with-deps` would install still come from the distro mirror; cache those
# separately (base-images/apt) if a fully offline rebuild is needed.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

# shellcheck source=scripts/bundle_pack_lib.sh
source "${ROOT_DIR}/scripts/bundle_pack_lib.sh"

CONTEXT_DIR="services/chat-api"
BUNDLE_NAME="playwright-browsers-bundle.tar.gz"
BUNDLE_PATH="${CONTEXT_DIR}/${BUNDLE_NAME}"
CACHE_DIR="base-images/playwright"
BROWSERS_DIR="${CACHE_DIR}/browsers"
MANIFEST="${CACHE_DIR}/manifest.txt"

DOCKER_BIN="${DOCKER_BIN:-docker}"
IMAGE="${IMAGE:-chat-api:latest}"

# Chromium is a compiled binary, so an arm64 build in an amd64 image fails to
# exec with ENOENT while still looking executable. The cache is therefore kept
# per architecture, exactly like pip wheels and .deb files:
#
#   base-images/playwright/browsers/<arch>/chromium-.../
#
# and the bundle mirrors that layout (`<arch>/...` at the top level), which is
# the tree the Dockerfile picks from via TARGETARCH. Keeping both arches side by
# side is the point: the old single-directory cache evicted arm64 whenever an
# amd64 fetch ran, so a machine that builds both could never hold both.
ARCH="${ARCH:-}"
ARCH_LIST="${ARCH_LIST:-arm64 amd64}"
PLAYWRIGHT_VERSION="${PLAYWRIGHT_VERSION:-}"
PLAYWRIGHT_DOWNLOAD_HOST="${PLAYWRIGHT_DOWNLOAD_HOST:-https://cdn.npmmirror.com/binaries/playwright}"

# Cache slot for one architecture.
browsers_dir_for() {
  printf '%s/%s' "${BROWSERS_DIR}" "$1"
}

# Architecture of the chromium binary in a directory tree, by reading the ELF
# header. `file` is not guaranteed present in the images, so the machine field
# is read directly: offset 18 of an ELF64 header holds e_machine.
elf_arch() {
  local path="$1"
  [[ -f "${path}" ]] || { printf 'missing'; return; }
  python3 - "$path" <<'PY'
import struct, sys
try:
    with open(sys.argv[1], 'rb') as fh:
        head = fh.read(20)
except OSError:
    print('unreadable'); raise SystemExit
if head[:4] != b'\x7fELF':
    print('not-elf'); raise SystemExit
machine = struct.unpack('<H', head[18:20])[0]
print({0x3e: 'amd64', 0xb7: 'arm64'}.get(machine, f'unknown-{machine:#x}'))
PY
}

# Architecture of the chromium binary in a directory tree, or empty when there
# is none. Takes the directory explicitly because each arch now has its own
# cache slot.
dir_arch() {
  local dir="$1" bin
  for bin in "${dir}"/chromium*-*/chrome-linux/headless_shell \
             "${dir}"/chromium*-*/chrome-linux/chrome; do
    [[ -f "${bin}" ]] || continue
    elf_arch "${bin}"
    return
  done
  printf ''
}

# Browser directory names present in a cache slot, comma-joined.
browsers_in() {
  find "$1" -mindepth 1 -maxdepth 1 -type d -exec basename {} \; 2>/dev/null \
    | sort | paste -sd ',' -
}

# Rewrite the manifest from whatever is on disk, so it always describes every
# architecture that is actually cached rather than just the last one fetched.
write_manifest() {
  local version="${1:-}"
  [[ -n "${version}" ]] || version="$(sed -n 's/^playwright_version=//p' "${MANIFEST}" 2>/dev/null | head -1)"
  mkdir -p "${CACHE_DIR}"
  {
    printf '# mogo playwright browser cache\n'
    printf '# generated: %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    printf 'playwright_version=%s\n' "${version}"
    local arch dir
    for arch in ${ARCH_LIST}; do
      dir="$(browsers_dir_for "${arch}")"
      [[ -d "${dir}" ]] || continue
      printf 'arch_%s=%s\n' "${arch}" "$(browsers_in "${dir}")"
    done
  } > "${MANIFEST}"
}

usage() {
  cat <<'USAGE'
Usage:
  scripts/playwright_browsers_bundle.sh fetch [arch]     Download browsers for an
                                                          architecture (arm64|amd64)
  scripts/playwright_browsers_bundle.sh save [image]     Cache browsers from an image and
                                                          write the bundle into the build context
  scripts/playwright_browsers_bundle.sh pack             Re-pack the bundle from
                                                          base-images/playwright/browsers
  scripts/playwright_browsers_bundle.sh list             Show cache + bundle status
  scripts/playwright_browsers_bundle.sh verify [image]   Check /ms-playwright inside an image,
                                                          including that chromium launches

Environment:
  DOCKER_BIN        Docker binary to use (default: docker)
  IMAGE             Image for save/verify (default: chat-api:latest)
  ARCH              Architecture for fetch/save (default: host architecture)
  ARCH_LIST         Architectures to pack, side by side (default: arm64 amd64)
  PLAYWRIGHT_VERSION  Version for fetch (default: read from chat-api requirements.txt)
  PLAYWRIGHT_DOWNLOAD_HOST  Browser CDN (default: npmmirror)

The cache is per architecture (base-images/playwright/browsers/<arch>/), and the
bundle carries them as top-level <arch>/ trees, so a single bundle serves both
amd64 and arm64 builds; the Dockerfile extracts the one TARGETARCH names.
Fetching one architecture never evicts the other.

`save` defaults to chat-api:latest, which must already contain /ms-playwright
(build it once with INSTALL_PLAYWRIGHT_AT_BUILD=true). It copies the browser
tree into the arch slot matching the binaries it finds, and packs the bundle
into the build context so later builds skip the download.
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

  # The arch comes from the chromium binary itself, not from the host: an amd64
  # image can be inspected from an arm64 laptop, and writing it into the wrong
  # slot would poison that slot for real amd64 builds.
  local src="${tmp_dir}/ms-playwright"
  local bin_arch
  bin_arch="$(dir_arch "${src}")"
  [[ -n "${bin_arch}" ]] \
    || die "No chromium binary found in ${image}; refusing to record an unusable cache."

  local dest
  dest="$(browsers_dir_for "${bin_arch}")"
  rm -rf "${dest}"
  mkdir -p "${dest}"
  # Cache root = contents of /ms-playwright, so pack/extract round-trips
  # straight into PLAYWRIGHT_BROWSERS_PATH. Only this arch's slot is replaced;
  # the other architecture's cache is left untouched.
  cp -R "${src}/." "${dest}/"

  write_manifest "${version}"
  printf 'Cached %s browsers into %s\n' "${bin_arch}" "${dest}"

  cmd_pack
}

# Download the browsers for one architecture directly from the CDN, without
# needing an image that already has them.
#
# This exists because the cache is architecture-specific and had silently gone
# stale: the saved browsers were arm64 while the production images are amd64,
# and an arm64 chromium in an amd64 image fails exec with ENOENT — the files
# still look executable, so only a launch check reveals it.
cmd_fetch() {
  local arch="${1:-${ARCH}}"
  require_docker

  [[ -n "${arch}" ]] || arch="$(host_arch)"
  case "${arch}" in
    arm64|amd64) ;;
    *) die "Unsupported arch: ${arch} (expected arm64 or amd64)" ;;
  esac

  local version="${PLAYWRIGHT_VERSION}"
  if [[ -z "${version}" ]]; then
    version="$(requirements_playwright_version)"
  fi
  [[ -n "${version}" ]] || die "Could not determine the playwright version; set PLAYWRIGHT_VERSION."

  printf 'Downloading playwright %s browsers for linux/%s ...\n' "${version}" "${arch}"

  # Incremental cache: reuse browsers already in this arch's slot so a re-run
  # (e.g. after a version bump or a partial download) only fetches what
  # changed, instead of wiping ~900MB and re-downloading everything.
  # A cache built for a *different* arch cannot live in this slot (the revision
  # dirs share names), so clear it -- but only this slot, never the other arch.
  local dest
  dest="$(browsers_dir_for "${arch}")"
  local cached
  cached="$(dir_arch "${dest}")"
  if [[ -n "${cached}" && "${cached}" != "${arch}" ]]; then
    printf '  %s holds %s binaries; clearing for linux/%s ...\n' "${dest}" "${cached}" "${arch}"
    rm -rf "${dest}"
  fi
  mkdir -p "${dest}"

  # The download runs in a container of the target architecture so the CDN
  # serves the matching build; the host architecture is irrelevant. The
  # existing cache is mounted as PLAYWRIGHT_BROWSERS_PATH, so `playwright
  # install` skips already-present browsers and downloads only the missing ones.
  "${DOCKER_BIN}" run --rm --platform "linux/${arch}" \
    -v "${ROOT_DIR}/${dest}:/out" \
    -e PLAYWRIGHT_BROWSERS_PATH=/out \
    -e PLAYWRIGHT_DOWNLOAD_HOST="${PLAYWRIGHT_DOWNLOAD_HOST}" \
    "python:3.13-slim-bookworm" bash -c "
      set -euo pipefail
      pip install --progress-bar off 'playwright==${version}' >/dev/null 2>&1
      # A failure to validate host libraries is expected here (this throwaway
      # container has none); the browser files are already written by then.
      playwright install chromium >/dev/null 2>&1 || true
      ls -d /out/chromium*-* >/dev/null 2>&1
    " || die "playwright install for ${arch} failed."

  # NOTE: `[[ -x glob ]]` does not perform pathname expansion in bash, so the
  # original guard (a literal glob inside [[ ]]) could never match and would
  # always report "No chromium binary". Use a loop, which does expand globs.
  local found=0
  for b in "${dest}"/chromium_headless_shell-*/chrome-linux/headless_shell \
           "${dest}"/chromium-*/chrome-linux/chrome; do
    [[ -x "${b}" ]] && { found=1; break; }
  done
  [[ "${found}" -eq 1 ]] \
    || die "No chromium binary was downloaded for ${arch}."

  local got_arch
  got_arch="$(dir_arch "${dest}")"
  [[ "${got_arch}" == "${arch}" ]] \
    || die "Downloaded browsers are ${got_arch:-unknown}, expected ${arch}."

  write_manifest "${version}"
  printf 'Cached %s browsers into %s\n' "${arch}" "${dest}"

  cmd_pack
}

# Host architecture as Docker reports it (amd64 / arm64).
host_arch() {
  "${DOCKER_BIN}" version --format '{{.Server.Arch}}' 2>/dev/null || printf 'amd64'
}

# The playwright version pinned in chat-api's requirements.txt.
requirements_playwright_version() {
  local req="services/chat-api/requirements.txt"
  [[ -f "${req}" ]] || return 0
  grep -oE '^playwright==[0-9.]+' "${req}" | head -1 | cut -d= -f3
}

cmd_pack() {
  [[ -d "${BROWSERS_DIR}" ]] \
    || die "No cached browsers at ${BROWSERS_DIR}. Run fetch or save first."

  # One bundle carries every architecture as a top-level <arch>/ tree, mirroring
  # the pip and apt bundles; the Dockerfile extracts only the one TARGETARCH
  # names. Missing arches are simply absent -- a single-arch bundle still works,
  # the image falls back to the network for the other one.
  local arch dir n total=0
  local packed_archs=()
  for arch in ${ARCH_LIST}; do
    dir="$(browsers_dir_for "${arch}")"
    [[ -d "${dir}" ]] || continue
    n="$(find "${dir}" -mindepth 1 -maxdepth 1 | wc -l | tr -d ' ')"
    [[ "${n}" -gt 0 ]] || continue
    packed_archs+=("${arch}")
    total=$((total + n))
  done
  [[ "${#packed_archs[@]}" -gt 0 ]] \
    || die "No cached browsers under ${BROWSERS_DIR}. Run fetch or save first."

  printf 'Packing %s (%s) -> %s ...\n' \
    "${BROWSERS_DIR}" "${packed_archs[*]}" "${BUNDLE_PATH}"

  # The fingerprint covers every arch slot plus the arch list, so dropping an
  # architecture (or changing ARCH_LIST) invalidates a previously packed bundle.
  local fp
  fp="$(bundle_fingerprint "${BROWSERS_DIR}") arch=${ARCH_LIST}"
  if bundle_fp_hit "${BUNDLE_PATH}" "${fp}"; then
    printf '\nBundle unchanged: %s (%s); nothing to rebuild.\n' \
      "${BUNDLE_PATH}" "$(human_size "$(wc -c < "${BUNDLE_PATH}" | tr -d ' ')")"
    printf 'The COPY layer stays cached.\n'
    return 0
  fi

  # Pack from a throwaway copy: bundle_pack rewrites mtimes to make the archive
  # reproducible, and stamping the durable base-images/playwright cache with
  # that fixed date would be a side effect the cache never asked for. The copy
  # is a same-volume APFS clone (bundle_clone), i.e. metadata only -- staging
  # under $TMPDIR would land on another volume and copy every byte.
  local staging
  staging="$(bundle_stage_dir)" || die "Cannot create a staging directory."
  trap 'rm -rf "${staging:-}" 2>/dev/null || true' EXIT
  for arch in "${packed_archs[@]}"; do
    bundle_clone "$(browsers_dir_for "${arch}")" "${staging}/${arch}"
  done

  local rc=0
  bundle_pack "${BUNDLE_PATH}" "${staging}" "${fp}" || rc=$?
  rm -rf "${staging}" 2>/dev/null || true
  [[ "${rc}" -le 1 ]] || die "Packing ${BUNDLE_PATH} failed."

  # rc=1: the archive already matches this cache, nothing was written. Say that
  # instead of "written", and skip the tar -tzf entry count it would need.
  if [[ "${rc}" -eq 1 ]]; then
    printf '\nBundle unchanged: %s (%s); nothing to rebuild.\n' \
      "${BUNDLE_PATH}" "$(human_size "$(wc -c < "${BUNDLE_PATH}" | tr -d ' ')")"
    printf 'The COPY layer stays cached.\n'
    return 0
  fi

  local out_size entries
  out_size="$(wc -c < "${BUNDLE_PATH}" | tr -d ' ')"
  entries="$(tar -tzf "${BUNDLE_PATH}" | grep -c -v '/$' || true)"
  printf '\nBundle written: %s (%s, %s files; arches: %s)\n' \
    "${BUNDLE_PATH}" "$(human_size "${out_size}")" "${entries}" "${packed_archs[*]}"
  printf 'Rebuild the image to use it:\n'
  printf '  docker compose -f docker-compose.yml -f docker-compose.build.yml build chat-api\n'
  printf 'The COPY layer re-executes only when this tar.gz changes; same bundle = cached.\n'
}

cmd_list() {
  printf 'Playwright browser cache:\n\n'

  local any=0 arch dir
  for arch in ${ARCH_LIST}; do
    dir="$(browsers_dir_for "${arch}")"
    if [[ -d "${dir}" ]] && [[ -n "$(browsers_in "${dir}")" ]]; then
      any=1
      local size
      size="$(du -sk "${dir}" | cut -f1)"
      printf '  [cache]     %-6s %s  (%s)\n' "${arch}" "${dir}" "$(human_size "$((size * 1024))")"
      printf '                       %s\n' "$(browsers_in "${dir}")"
    else
      printf '  [missing]   %-6s %s  - run: %s fetch %s\n' \
        "${arch}" "${dir}" "$0" "${arch}"
    fi
  done
  [[ "${any}" -eq 1 ]] || printf '\n  (no architecture cached yet)\n'

  if [[ -f "${MANIFEST}" ]]; then
    printf '\n'
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
    printf '  [missing]   %s  - run save (no placeholder in git: COPY will fail until this exists)\n' "${BUNDLE_PATH}"
  fi
}

cmd_verify() {
  local image="${1:-${IMAGE}}"
  require_docker
  "${DOCKER_BIN}" image inspect "${image}" >/dev/null 2>&1 \
    || die "Image ${image} not found locally."

  printf 'Checking /ms-playwright in %s ...\n' "${image}"

  # The body is written to a file and mounted rather than passed with -c: it
  # contains quotes, loops and an inline python program, and nesting all of
  # that inside a single-quoted -c argument is unmaintainable.
  local script
  script="$(mktemp)"
  trap 'rm -f "${script:-}"' EXIT

  cat > "${script}" <<'CHECK'
set -e
[ -d /ms-playwright ] || { echo "MISSING /ms-playwright"; exit 3; }
n=$(find /ms-playwright -maxdepth 1 -mindepth 1 -type d | wc -l | tr -d " ")
sz=$(du -sh /ms-playwright | cut -f1)
echo "  browser dirs: ${n}  size: ${sz}"
ver=$(python -m playwright --version 2>/dev/null || echo unknown)
echo "  ${ver}"
host_arch=$(dpkg --print-architecture 2>/dev/null || uname -m)
echo "  container arch: ${host_arch}"

# A chromium build is only usable when its binary exists and is executable; an
# interrupted download leaves the directory present but empty, which would
# otherwise pass a naive existence check.
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

# Executability is not enough: a browser built for another architecture still
# carries the executable bit and only fails at exec time (ENOENT). That is
# exactly how an arm64 bundle once shipped inside an amd64 image.
echo "--- arch check (binary vs image) ---"
bin_arch=unknown
for b in /ms-playwright/chromium*-*/chrome-linux/headless_shell /ms-playwright/chromium*-*/chrome-linux/chrome; do
  [ -f "$b" ] || continue
  bin_arch=$(python - "$b" <<'PY'
import struct, sys
head = open(sys.argv[1], 'rb').read(20)
machine = struct.unpack('<H', head[18:20])[0]
print({0x3e: 'amd64', 0xb7: 'arm64'}.get(machine, 'unknown-%#x' % machine))
PY
)
  echo "  chromium binary: ${bin_arch}"
  break
done
if [ "${bin_arch}" != "${host_arch}" ]; then
  echo "  BAD: browser is ${bin_arch} but the image is ${host_arch}"
  exit 5
fi
echo "  OK: browser arch matches the image"

# The only check that proves the browser actually runs.
echo "--- launch check ---"
cat > /tmp/launch_check.py <<'PY'
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser = p.chromium.launch(args=['--no-sandbox'])
    page = browser.new_page()
    page.set_content('<h1>ok</h1>')
    assert page.inner_text('h1') == 'ok'
    print('  chromium launched: ' + browser.version)
    browser.close()
PY
if python /tmp/launch_check.py; then
  echo "  OK: chromium launches and renders"
else
  echo "  BAD: chromium is present but does not launch"
  exit 6
fi
CHECK

  "${DOCKER_BIN}" run --rm \
    --platform "linux/$(docker image inspect "${image}" --format '{{.Architecture}}' 2>/dev/null || echo amd64)" \
    --entrypoint sh \
    -v "${script}:/check.sh:ro" \
    "${image}" /check.sh
}

command="${1:-list}"
if [[ $# -gt 0 ]]; then
  shift
fi

case "${command}" in
  fetch)
    cmd_fetch "${1:-}"
    ;;
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
