#!/usr/bin/env bash
set -Eeuo pipefail

# Manage the apt package bundle used by the service Dockerfiles.
#
# Why this exists: the document-parser build's apt layer measured 315s on a
# warm home link, and 268s of that was *download* — the Tsinghua apt mirror
# serves .deb files at ~895 kB/s, against 13-18 MB/s for the same mirror's PyPI
# endpoint. Only ~24s was actual dpkg unpack plus postinst. Unlike the PyPI
# stage there is nothing to gain from parallelism; the mirror is simply slow, so
# the only way to make a rebuild fast is to not download again.
#
# Layout:
#   base-images/apt/<service>/<arch>/             the .deb files as-is
#       Packages/                                 copied apt index (see below)
#       manifest.txt                              what was fetched and from where
#   services/<service>/apt-packages-bundle.tar.gz
#       - tracked in git as a <1KB placeholder so COPY never fails
#       - overwritten in place by `save` with the real bundle
#
# The build context is services/<service>, so the bundle has to live there; the
# durable copy stays under base-images/ so it survives `git clean` and can be
# re-packed without downloading again.
#
# How the offline install works — and what it needs:
#
#   apt-get install --download-only <pkgs>   pulls every .deb into
#                                            /var/cache/apt/archives
#   apt-get install --no-download <pkgs>     installs from those .deb files
#
# --no-download still needs the apt *index* to resolve names to versions, so
# the Debian Packages lists are copied into the bundle alongside the .deb files.
# Two traps were hit while building this:
#
#   1. /etc/apt/apt.conf.d/docker-clean installs a DPkg::Post-Invoke hook that
#      deletes /var/cache/apt/archives/*.deb after every apt operation. The
#      service Dockerfiles already `rm -f` that file; without that, the
#      downloaded .deb files vanish before the fetch can copy them out.
#   2. Editing sources.list to simulate "offline" changes the index identity
#      and makes apt report "Unable to locate package" even though the .deb is
#      cached and the index file is present. Offline verification must therefore
#      leave sources.list alone and rely on --no-download.
#
# The bundle is architecture-specific: the .deb set for arm64 differs from
# amd64 (different package names for some runtime libs), so each architecture
# gets its own directory and the Dockerfile selects by TARGETARCH.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

CACHE_DIR="base-images/apt"

DOCKER_BIN="${DOCKER_BIN:-docker}"

# Services whose apt layer is cached. Kept in sync with the Dockerfiles that
# declare INSTALL_SYSTEM_DEPS_AT_BUILD (plus dsh-runtime-host, which installs
# ca-certificates/gosu unconditionally).
SERVICE_LIST="${SERVICE_LIST:-document-parser chat-api dsh-runtime-host}"

# Dockerfile location per service. Most services keep it at services/<name>/,
# but dsh-runtime-host lives under services/chat-api/dsh/runtime-host/ and has
# its own build context.
dockerfile_for() {
  case "$1" in
    dsh-runtime-host) printf 'services/chat-api/dsh/runtime-host/Dockerfile' ;;
    *)                printf 'services/%s/Dockerfile' "$1" ;;
  esac
}

# Build context (where the bundle must live) per service.
context_dir_for() {
  case "$1" in
    dsh-runtime-host) printf 'services/chat-api/dsh/runtime-host' ;;
    *)                printf 'services/%s' "$1" ;;
  esac
}

# Base image per service: the .deb set must match the distro the Dockerfile
# installs into, because apt resolves against that image's package index.
base_image_for() {
  case "$1" in
    document-parser)  printf 'python:3.10-slim-bookworm' ;;
    chat-api)         printf 'python:3.13-slim-bookworm' ;;
    dsh-runtime-host) printf 'node:24-bookworm-slim' ;;
    *)                printf 'python:3.10-slim-bookworm' ;;
  esac
}

# Debian suite used by those base images.
SUITE="${SUITE:-bookworm}"

MOVO_APT_MIRROR="${MOVO_APT_MIRROR:-http://mirrors.tuna.tsinghua.edu.cn/debian}"
MOVO_APT_SECURITY_MIRROR="${MOVO_APT_SECURITY_MIRROR:-http://mirrors.tuna.tsinghua.edu.cn/debian-security}"

ARCH_LIST="${ARCH_LIST:-arm64 amd64}"

usage() {
  cat <<'USAGE'
Usage:
  scripts/apt_packages_bundle.sh fetch [service...]  Download .deb files into
                                                      base-images/apt/<service>/<arch>/
  scripts/apt_packages_bundle.sh pack [service...]   Re-pack bundles from the cache
  scripts/apt_packages_bundle.sh save [service...]   fetch + pack in one step
  scripts/apt_packages_bundle.sh list                Show cache + bundle status
  scripts/apt_packages_bundle.sh audit               Check every cached .deb
                                                      matches its target architecture
  scripts/apt_packages_bundle.sh verify [image]      Check that the expected
                                                      binaries/fonts exist in an image

Environment:
  DOCKER_BIN                Docker binary to use (default: docker)
  SERVICE_LIST              Services to process (default: "document-parser chat-api")
  ARCH_LIST                 Architectures to fetch (default: "arm64 amd64")
  MOVO_APT_MIRROR           Debian mirror (default: Tsinghua)
  MOVO_APT_SECURITY_MIRROR  Debian security mirror (default: Tsinghua)

The package list per service is read from the Dockerfile itself (the
`apt-get install` block), so adding a package there and re-running `save` is
enough — there is no second list to keep in sync.

Each service gets its own bundle in its own build context. The .deb set is
per-architecture and per-distro; the Dockerfile selects the directory matching
TARGETARCH and falls back to the network when the bundle is absent.
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

# pip platform label -> Debian architecture name.
debian_arch() {
  case "$1" in
    arm64) printf 'arm64' ;;
    amd64) printf 'amd64' ;;
    *) die "Unsupported arch: $1 (expected arm64 or amd64)" ;;
  esac
}

# The architecture the runtime images are built for. Production builds pass
# DOCKER_DEFAULT_PLATFORM=linux/amd64, so honour it: the deb dependency set is
# the same across architectures but the discovery container must be able to run.
host_debian_arch() {
  local platform="${DOCKER_DEFAULT_PLATFORM:-}"
  case "${platform}" in
    *amd64*) printf 'amd64'; return ;;
    *arm64*) printf 'arm64'; return ;;
  esac
  "${DOCKER_BIN}" version --format '{{.Server.Arch}}' 2>/dev/null || printf 'amd64'
}

bundle_path_for() {
  printf '%s/apt-packages-bundle.tar.gz' "$(context_dir_for "$1")"
}

# Extract the package list from a service Dockerfile's apt-get install block.
#
# Reading the Dockerfile instead of keeping a parallel list means a package
# added there is picked up by the next `save` with no second edit. The block is
# recognised by "apt-get install" followed by continuation lines, and the
# package names are the bare tokens that are neither flags nor continuations.
packages_for() {
  local service="$1"
  local dockerfile
  dockerfile="$(dockerfile_for "${service}")"
  [[ -f "${dockerfile}" ]] || die "Missing ${dockerfile}"

  python3 - "${dockerfile}" <<'PY'
import re, sys

lines = open(sys.argv[1]).read().splitlines()

# Two shapes are recognised:
#
#   apt-get install -y --no-install-recommends pkg-a pkg-b ...   (inline)
#   apt_install pkg-a pkg-b ...                                   (helper call)
#
# The helper form is what the Dockerfiles use once the package set grows: it
# keeps one install path for the offline (`--no-download`) and online branches,
# so the list cannot drift between them. `"$@"` inside the helper *definition*
# is skipped naturally, because it is a single quoted token and not a name.
NAME = re.compile(r'^[a-z0-9][a-z0-9.+-]*$')
SHELL_WORDS = {
    'rm', 'echo', 'else', 'fi', 'then', 'if', 'for', 'do', 'done', 'set',
    'unset', 'export', 'cd', 'cp', 'mv', 'true', 'false', 'apt', 'apt-get',
    'install', 'system', 'dependencies', 'build', 'stage', 'in', 'skip',
    'apt_install', 'no', 'download', 'recommends',
}

pkgs = []
collecting = False
for raw in lines:
    line = raw.rstrip()
    if not collecting:
        stripped = line.strip()
        if 'apt-get install' in line:
            line = line.split('apt-get install', 1)[1]
        elif re.match(r'^apt_install\b', stripped):
            line = re.sub(r'^apt_install\b', '', stripped)
        else:
            continue
        collecting = True

    continues = line.rstrip().endswith('\\')
    body = line.rstrip().rstrip('\\').strip()
    terminated = ';' in body

    # Everything after a shell operator is not a package name.
    body = re.split(r'&&|\|\||;', body)[0]

    for tok in body.split():
        tok = tok.strip('\\').strip('"')
        if not tok or tok.startswith('-') or tok.startswith('$'):
            continue
        if tok in SHELL_WORDS:
            continue
        if NAME.match(tok):
            pkgs.append(tok)

    if not continues or terminated:
        collecting = False

# De-duplicate while preserving order.
seen = set()
for pkg in pkgs:
    if pkg not in seen:
        seen.add(pkg)
        print(pkg)
PY
}

# Fetch the .deb files for one service and architecture into the cache.
fetch_one() {
  local service="$1" arch="$2"
  local dest="${CACHE_DIR}/${service}/${arch}"
  local packages=()
  # Not `mapfile`: macOS ships bash 3.2, which predates it.
  while IFS= read -r pkg; do
    [[ -n "${pkg}" ]] && packages+=("${pkg}")
  done < <(packages_for "${service}")
  [[ "${#packages[@]}" -gt 0 ]] || die "No apt packages parsed from $(dockerfile_for "${service}")"

  # De-duplicate, preserving order.
  local -a uniq=()
  local seen="" p
  for p in "${packages[@]}"; do
    case " ${seen} " in *" ${p} "*) continue ;; esac
    seen="${seen} ${p}"
    uniq+=("${p}")
  done
  packages=("${uniq[@]}")

  local host_uid host_gid
  host_uid="$(id -u)"
  host_gid="$(id -g)"

  local image
  image="$(base_image_for "${service}")"
  local darch
  darch="$(debian_arch "${arch}")"

  printf '  %s/%s: %s packages -> %s\n' \
    "${service}" "${arch}" "${#packages[@]}" "${dest}"

  rm -rf "${dest}"
  mkdir -p "${dest}"

  # The .deb set must match the target architecture, so the fetch runs in a
  # container of that architecture. A foreign-arch image is resolved through
  # MOGO_BASE_IMAGE_MIRROR when set (default: the same daocloud mirror the
  # release script uses), because Docker Hub is frequently unreachable from
  # these networks — and requiring it would make an amd64 fetch fail on an
  # arm64 host that only has native images cached.
  #
  # Doing this by architecture (rather than by apt tricks such as
  # dpkg --add-architecture plus an APT::Architecture pin) is deliberate: apt
  # will happily satisfy a dependency with the *host* architecture, and pinning
  # it globally then conflicts with the base image's already-installed host-arch
  # packages ("ca-certificates : Depends: openssl" — observed).
  local run_image="${image}"
  if [[ "${arch}" != "$(docker image inspect "${image}" --format '{{.Architecture}}' 2>/dev/null || printf 'unknown')" ]]; then
    local mirror="${MOGO_BASE_IMAGE_MIRROR-docker.m.daocloud.io}"
    if [[ -n "${mirror}" ]]; then
      # docker.m.daocloud.io/library/python:... — rewrite the Docker Hub
      # reference onto the mirror, adding the implicit library/ namespace.
      local mirrored
      mirrored="${mirror}/library/${image}"
      if "${DOCKER_BIN}" pull --platform "linux/${arch}" "${mirrored}" >/dev/null 2>&1; then
        run_image="${mirrored}"
      fi
    fi
  fi

  "${DOCKER_BIN}" run --rm \
    --platform "linux/${arch}" \
    -v "${ROOT_DIR}/${dest}:/out" \
    -e DEBIAN_FRONTEND=noninteractive \
    "${run_image}" bash -c "
      set -euo pipefail

      # The cached .deb files are deleted after every apt operation by this
      # hook, so it must go before anything is fetched.
      rm -f /etc/apt/apt.conf.d/docker-clean

      for f in /etc/apt/sources.list /etc/apt/sources.list.d/debian.sources; do
        [ -f \"\$f\" ] || continue
        sed -i 's|http://deb.debian.org/debian|${MOVO_APT_MIRROR}|g; s|https://deb.debian.org/debian|${MOVO_APT_MIRROR}|g' \"\$f\"
        sed -i 's|http://deb.debian.org/debian-security|${MOVO_APT_SECURITY_MIRROR}|g; s|https://deb.debian.org/debian-security|${MOVO_APT_SECURITY_MIRROR}|g; s|http://security.debian.org/debian-security|${MOVO_APT_SECURITY_MIRROR}|g; s|https://security.debian.org/debian-security|${MOVO_APT_SECURITY_MIRROR}|g' \"\$f\"
      done

      apt-get -o Acquire::Retries=5 update >/dev/null 2>&1

      # --reinstall matters: the base image already ships some of these
      # (ca-certificates, fonts-dejavu-core via fontconfig), and plain
      # --download-only skips anything already installed, so those .deb files
      # would never reach the cache. The offline install then fails with
      # "Unable to fetch some archives" because apt resolves the dependency
      # against the cached index but finds no matching file. Fetching with
      # --reinstall keeps the bundle self-sufficient.
      apt-get install -y --no-install-recommends --download-only --reinstall \
        $(printf '%s ' "${packages[@]}")

      # Guard: every .deb must match the requested architecture. The container is
      # the target architecture, so this should always hold; it is checked
      # because a stray foreign-arch file would be cached, shipped and installed
      # into the wrong image with no error until something fails at runtime.
      deb_arch_expected="$(debian_arch "${arch}")"
      for deb in /var/cache/apt/archives/*.deb; do
        [ -f \"\$deb\" ] || continue
        deb_arch=\"\$(dpkg-deb -f \"\$deb\" Architecture 2>/dev/null || echo unknown)\"
        case \"\$deb_arch\" in
          all|\${deb_arch_expected}) ;;
          *)
            echo \"ERROR: \$(basename \$deb) is \${deb_arch}, expected \${deb_arch_expected}\" >&2
            exit 3
            ;;
        esac
      done

      # Copy the .deb files and the package index. --no-download needs the
      # index to map names to versions; without it apt reports
      # \"Unable to locate package\" even though the .deb is right there.
      cp -f /var/cache/apt/archives/*.deb /out/ 2>/dev/null || true
      mkdir -p /out/Packages
      cp -f /var/lib/apt/lists/*Packages* /out/Packages/ 2>/dev/null || true
      cp -f /var/lib/apt/lists/*InRelease /out/Packages/ 2>/dev/null || true

      chown -R ${host_uid}:${host_gid} /out
    "

  local n
  n="$(find "${dest}" -maxdepth 1 -name '*.deb' | wc -l | tr -d ' ')"
  [[ "${n}" -gt 0 ]] || die "No .deb files fetched for ${service}/${arch}"

  # Record provenance so a stale cache is detectable when the package list or
  # mirror changes.
  local size
  size="$(du -sk "${dest}" | cut -f1)"
  {
    printf '# movo apt package cache\n'
    printf '# generated: %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    printf '# service: %s\n' "${service}"
    printf '# arch: linux/%s (debian %s)\n' "${arch}" "${darch}"
    printf '# base_image: %s\n' "${image}"
    printf '# suite: %s\n' "${SUITE}"
    printf '# mirror: %s\n' "${MOVO_APT_MIRROR}"
    printf '# security_mirror: %s\n' "${MOVO_APT_SECURITY_MIRROR}"
    printf '# dockerfile_sha256: %s\n' \
      "$(shasum -a 256 "$(dockerfile_for "${service}")" 2>/dev/null | cut -d' ' -f1 || printf 'n/a')"
    printf 'deb_count=%s\n' "${n}"
    printf 'size=%s\n' "$(human_size "$((size * 1024))")"
    printf 'packages=%s\n' "$(printf '%s,' "${packages[@]}" | sed 's/,$//')"
  } > "${dest}/manifest.txt"

  printf '    %s .deb, %s\n' "${n}" "$(human_size "$((size * 1024))")"
}

cmd_fetch() {
  local services=("$@")
  [[ "${#services[@]}" -eq 0 ]] && read -r -a services <<< "${SERVICE_LIST}"

  require_docker
  for service in "${services[@]}"; do
    for arch in ${ARCH_LIST}; do
      fetch_one "${service}" "${arch}"
    done
  done
  printf '\nRun `%s pack` to refresh the build-context bundles.\n' "$0"
}

cmd_pack() {
  local services=("$@")
  [[ "${#services[@]}" -eq 0 ]] && read -r -a services <<< "${SERVICE_LIST}"

  local found=0
  for service in "${services[@]}"; do
    local staged bundle
    staged="$(mktemp -d)"
    bundle="$(bundle_path_for "${service}")"

    local total=0
    for arch in ${ARCH_LIST}; do
      local d="${CACHE_DIR}/${service}/${arch}"
      [[ -d "${d}" ]] || continue
      local n
      n="$(find "${d}" -maxdepth 1 -name '*.deb' | wc -l | tr -d ' ')"
      [[ "${n}" -gt 0 ]] || continue
      mkdir -p "${staged}/${arch}"
      # .deb files plus the apt index the offline install needs.
      cp "${d}"/*.deb "${staged}/${arch}/" 2>/dev/null || true
      if [[ -d "${d}/Packages" ]]; then
        mkdir -p "${staged}/${arch}/Packages"
        cp "${d}/Packages/"* "${staged}/${arch}/Packages/" 2>/dev/null || true
      fi
      total=$((total + n))
    done

    if [[ "${total}" -eq 0 ]]; then
      rm -rf "${staged}"
      printf '  %s: no cached packages, skipped\n' "${service}"
      continue
    fi

    printf '  %s: packing %s .deb -> %s\n' "${service}" "${total}" "${bundle}"
    tar -czf "${bundle}" -C "${staged}" .
    rm -rf "${staged}"

    local out_size
    out_size="$(wc -c < "${bundle}" | tr -d ' ')"
    printf '    %s\n' "$(human_size "${out_size}")"
    found=1
  done

  [[ "${found}" -eq 1 ]] || die "Nothing packed. Run fetch first."
  printf '\nRebuild to use them:\n'
  printf '  docker compose -f docker-compose.yml -f docker-compose.build.yml build document-api\n'
}

cmd_save() {
  if [[ "$#" -gt 0 ]]; then
    cmd_fetch "$@"
    cmd_pack "$@"
  else
    cmd_fetch
    cmd_pack
  fi
}

cmd_list() {
  printf 'apt package cache:\n\n'
  local any=0
  for service in ${SERVICE_LIST}; do
    for arch in ${ARCH_LIST}; do
      local d="${CACHE_DIR}/${service}/${arch}"
      [[ -d "${d}" ]] || continue
      any=1
      local n size
      n="$(find "${d}" -maxdepth 1 -name '*.deb' | wc -l | tr -d ' ')"
      size="$(du -sk "${d}" | cut -f1)"
      printf '  [cache]  %-18s %-6s %4s .deb  %s\n' \
        "${service}" "${arch}" "${n}" "$(human_size "$((size * 1024))")"
    done
  done
  [[ "${any}" -eq 1 ]] || printf '  [empty]  %s - run fetch first\n' "${CACHE_DIR}"

  printf '\nBundles for the build contexts:\n\n'
  for service in ${SERVICE_LIST}; do
    local bundle
    bundle="$(bundle_path_for "${service}")"
    if [[ -f "${bundle}" ]]; then
      local bsize
      bsize="$(wc -c < "${bundle}" | tr -d ' ')"
      if [[ "${bsize}" -gt 1024 ]]; then
        printf '  [bundle] %-18s %s  (%s)\n' "${service}" "${bundle}" "$(human_size "${bsize}")"
      else
        printf '  [placeholder] %-13s %s  (%s) - online install will be used\n' \
          "${service}" "${bundle}" "$(human_size "${bsize}")"
      fi
    else
      printf '  [missing] %-14s %s - run pack\n' "${service}" "${bundle}"
    fi
  done
}

# Audit the cached .deb set for architecture purity.
#
# This exists because a wrong-architecture .deb is invisible until runtime: apt
# installs it into the image without complaint, and the failure surfaces much
# later as a missing library. It is cheap to check and has already caught one
# real mistake (a dpkg --add-architecture approach that pulled libssl3_arm64
# into an amd64 cache), so it is a first-class command rather than a footnote.
cmd_audit() {
  require_docker
  local bad=0 checked=0

  printf 'Auditing cached .deb architectures:\n\n'
  for service in ${SERVICE_LIST}; do
    for arch in ${ARCH_LIST}; do
      local d="${CACHE_DIR}/${service}/${arch}"
      [[ -d "${d}" ]] || continue
      local expect
      expect="$(debian_arch "${arch}")"

      # dpkg-deb is not available on the host (macOS), so the inspection runs in
      # a throwaway container; reading the control member by hand would
      # duplicate ar/tar parsing for no benefit.
      local counts
      counts="$("${DOCKER_BIN}" run --rm -v "${ROOT_DIR}/${d}:/d:ro" \
        python:3.10-slim-bookworm bash -c '
          for f in /d/*.deb; do
            [ -f "$f" ] || continue
            dpkg-deb -f "$f" Architecture 2>/dev/null || echo unreadable
          done | sort | uniq -c | sort -rn
        ' 2>/dev/null)"

      local n
      n="$(printf '%s\n' "${counts}" | awk '{s+=$1} END {print s+0}')"
      checked=$((checked + n))

      # Every entry must be the expected arch or "all".
      local offenders
      offenders="$(printf '%s\n' "${counts}" | awk -v e="${expect}" '$2 != e && $2 != "all" && $2 != "" {print}')"

      if [[ -n "${offenders}" ]]; then
        bad=1
        printf '  BAD  %-18s %-6s expected %s, found:\n' "${service}" "${arch}" "${expect}"
        printf '%s\n' "${offenders}" | sed 's/^/         /'
      else
        printf '  OK   %-18s %-6s %s files (%s)\n' "${service}" "${arch}" "${n}" \
          "$(printf '%s' "${counts}" | tr '\n' ' ' | sed 's/  */ /g')"
      fi
    done
  done

  [[ "${checked}" -gt 0 ]] || die "No cached .deb files found under ${CACHE_DIR}."
  printf '\n'
  if [[ "${bad}" -eq 0 ]]; then
    printf 'All %s cached .deb files match their target architecture.\n' "${checked}"
    return 0
  fi
  die "Architecture mismatches found. Re-run fetch for the affected service/arch."
}

cmd_verify() {
  local image="${1:-document-parser:latest}"
  require_docker
  "${DOCKER_BIN}" image inspect "${image}" >/dev/null 2>&1 \
    || die "Image ${image} not found locally."

  printf 'Checking apt-installed system deps in %s ...\n' "${image}"

  # The point of the cache is that these land in the image; a bundle that
  # quietly installed nothing would otherwise be invisible.
  local script
  script="$(mktemp)"
  trap 'rm -f "${script:-}"' EXIT

  cat > "${script}" <<'CHECK'
set -e
missing=0
check_bin() {
  if command -v "$1" >/dev/null 2>&1; then
    echo "  OK: $1 ($(command -v "$1"))"
  else
    echo "  BAD: $1 not found"
    missing=1
  fi
}
check_lib() {
  if ldconfig -p 2>/dev/null | grep -q "$1"; then
    echo "  OK: lib $1"
  else
    echo "  BAD: lib $1 missing"
    missing=1
  fi
}

check_bin curl
check_lib libGL.so.1
check_lib libglib-2.0.so.0
check_lib libgomp.so.1

echo "--- fonts ---"
if command -v fc-list >/dev/null 2>&1; then
  n=$(fc-list 2>/dev/null | wc -l | tr -d ' ')
  echo "  fc-list entries: ${n}"
  fc-list 2>/dev/null | grep -ci "wenquanyi\|noto.*cjk\|wqy" | xargs echo "  CJK font faces:"
  [ "${n}" -gt 0 ] || { echo "  BAD: fontconfig reports no fonts"; missing=1; }
else
  echo "  BAD: fc-list (fontconfig) not available"
  missing=1
fi

echo "--- libreoffice (document-parser only) ---"
if command -v libreoffice >/dev/null 2>&1; then
  libreoffice --version 2>/dev/null | head -1 | sed 's/^/  /'
elif command -v soffice >/dev/null 2>&1; then
  echo "  OK: soffice present"
else
  echo "  (not installed - expected for images without libreoffice)"
fi

exit "${missing}"
CHECK

  "${DOCKER_BIN}" run --rm \
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
    cmd_fetch "$@"
    ;;
  pack)
    cmd_pack "$@"
    ;;
  save)
    cmd_save "$@"
    ;;
  list)
    cmd_list
    ;;
  audit)
    cmd_audit
    ;;
  verify)
    cmd_verify "${1:-}"
    ;;
  packages)
    for service in ${SERVICE_LIST}; do
      printf '%s: ' "${service}"
      packages_for "${service}" | tr '\n' ' '
      printf '\n'
    done
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
