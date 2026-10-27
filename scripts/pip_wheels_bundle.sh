#!/usr/bin/env bash
set -Eeuo pipefail

# Manage the pip wheel bundle used by services/document-parser's Dockerfile.
#
# Why this exists: the document-parser build installs ~250 wheel files across
# three pip invocations (pip/setuptools, torch+torchvision, requirements.txt,
# requirements-docling.txt). The Dockerfile sets PIP_NO_CACHE_DIR=1 so every
# build re-downloads all of them from the network. Measured on a warm home
# link that is still ~65s for the torch leg alone, because the SJTU CPU index
# serves the 159MB (arm64) / 196MB (amd64) wheel over a single slow stream;
# the rest is the pip resolver walking a 137-entry dependency tree.
#
# Between an amd64 and an arm64 host there is *no* shared layer cache, so a
# machine that builds both (or CI plus a laptop) pays the download twice.
# With a saved bundle the build installs from the build context instead.
#
# Layout:
#   base-images/pip-wheels/                       local cache (git-ignored, /base-images/)
#       arm64/                                    wheels for linux/arm64
#       amd64/                                    wheels for linux/amd64
#       manifest.txt                              source refs + per-arch contents
#   services/document-parser/pip-wheels-bundle.tar.gz
#       - NOT tracked in git (as of 2026-10-21: git rm --cached, ignored)
#       - generated here by `pack`; the Dockerfile's COPY needs it present
#
# IMPORTANT: because the bundle is no longer tracked, a fresh clone has no
# bundle file at all and `docker build` fails at the COPY line until you run
# `pack` (or `fetch` then `pack`) once. The real bundle is kept out of git so a
# ~850MB binary never enters history; `.local-bundles/` holds a local copy.
#
# The build context is services/document-parser, so the bundle has to live
# there; the durable per-arch cache stays under base-images/ so it survives
# `git clean` and can be re-packed without re-downloading.
#
# Cross-architecture: wheels are fetched with `pip download --platform ...`,
# which works from any host (verified: an arm64 host pulls the amd64 torch CPU
# wheel). `fetch` caches whichever architectures are requested, `pack` bundles
# them all into one tar.gz whose entries are prefixed by arch, and the
# Dockerfile picks the matching prefix at build time.
#
# NOTE: this covers *wheels* only. Packages without a wheel for the target
# platform (sdists) are reported and skipped rather than silently dropped, and
# the Dockerfile still falls back to the network when a wheel is missing.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

# shellcheck source=scripts/bundle_pack_lib.sh
source "${ROOT_DIR}/scripts/bundle_pack_lib.sh"

BUNDLE_NAME="pip-wheels-bundle.tar.gz"
CACHE_DIR="base-images/pip-wheels"

# Services whose pip layer is cached. Each gets its own cache subtree and its
# own bundle inside its own build context, mirroring apt_packages_bundle.sh.
# document-parser additionally has requirements-docling.txt (the Docling/Torch
# stack) and is the only one that preinstalls torch from the PyTorch CPU index.
SERVICE_LIST="${SERVICE_LIST:-document-parser chat-api admin-api}"

DOCKER_BIN="${DOCKER_BIN:-docker}"

# Absolute path to this script, used to re-enter it as `fetch-one` from the
# parallel fetch path (xargs cannot call a shell function).
SELF="${ROOT_DIR}/scripts/$(basename "${BASH_SOURCE[0]}")"

# How many (service, arch) downloads run at once. Each one is a docker run
# against a PyPI mirror plus a short host-side probe; 3 keeps the link busy
# without starving any single download. Set to 1 for the old serial behaviour.
MAX_PARALLEL="${MAX_PARALLEL:-3}"

# Platform labels pip must consider for each arch. manylinux tags are cumulative
# and pip does not infer older ones from a newer tag, so all of them are listed;
# omitting manylinux2014_x86_64 silently drops most amd64 wheels (verified).
#
# Both architectures are built by default. They never mix: the cache keeps one
# directory per (service, arch) under base-images/pip-wheels/, and the bundle
# stores them as separate top-level <arch>/ trees, which is what the Dockerfile
# picks from at build time via TARGETARCH. Narrow it with ARCH_LIST=arm64 when
# only the local architecture is wanted.
ARCH_LIST="${ARCH_LIST:-arm64 amd64}"

# --- per-service configuration -------------------------------------------

context_dir_for() { printf 'services/%s' "$1"; }
bundle_path_for() { printf 'services/%s/%s' "$1" "${BUNDLE_NAME}"; }

# Python target of the service image. The interpreter tag decides which wheel
# ABI pip may pick, so it must match the base image.
py_version_for() {
  case "$1" in
    document-parser) printf '3.13' ;;
    chat-api)        printf '3.13' ;;
    admin-api)       printf '3.13' ;;
    *)               printf '3.13' ;;
  esac
}
py_tag_for() {
  case "$1" in
    document-parser) printf '313' ;;
    chat-api)        printf '313' ;;
    admin-api)       printf '313' ;;
    *)               printf '313' ;;
  esac
}
base_image_for() {
  case "$1" in
    document-parser) printf 'python:3.13-slim-bookworm' ;;
    chat-api)        printf 'python:3.13-slim-bookworm' ;;
    admin-api)       printf 'python:3.13-slim-bookworm' ;;
    *)               printf 'python:3.13-slim-bookworm' ;;
  esac
}
# Extra requirement files beyond requirements.txt, in install order.
extra_requirements_for() {
  case "$1" in
    document-parser) printf 'requirements-docling.txt' ;;
    *)               printf '' ;;
  esac
}
# Only document-parser preinstalls torch; the others resolve it (not at all) via
# their own closures.
needs_torch_for() {
  case "$1" in
    document-parser) printf 'true' ;;
    *)               printf 'false' ;;
  esac
}

# Sdist-only packages per service. These have no cross-platform wheel and would
# abort the whole --only-binary resolution; they are fetched separately. The
# set is *probed* at fetch time (see split_requirements), and this list only
# seeds the probe result for services whose closure is known.
# (Probing handles new ones automatically; nothing must be added here for
# correctness.)

# Indexes. The CPU torch wheels only exist on the PyTorch CPU index (PyPI
# ships the CUDA build), so that leg cannot follow the PyPI mirror.
PYPI_INDEX="${PYPI_INDEX:-https://pypi.tuna.tsinghua.edu.cn/simple}"
PYTORCH_CPU_INDEX="${PYTORCH_CPU_INDEX:-https://mirror.sjtu.edu.cn/pytorch-wheels/cpu}"

REQUIREMENTS_MAIN="requirements.txt"

usage() {
  cat <<'USAGE'
Usage:
  scripts/pip_wheels_bundle.sh fetch [service...] [--arch <a>]  Download wheels
  scripts/pip_wheels_bundle.sh pack [service...]                Re-pack bundles
  scripts/pip_wheels_bundle.sh save [service...]                fetch + pack
  scripts/pip_wheels_bundle.sh list                             Show cache + bundles
  scripts/pip_wheels_bundle.sh verify [image]                   Check an image's packages

Arguments:
  service     One or more of: document-parser chat-api admin-api
              (default: all of them)

Environment:
  DOCKER_BIN        Docker binary to use (default: docker)
  SERVICE_LIST      Services to process
  ARCH_LIST         Architectures to fetch (default: "arm64 amd64")
  MAX_PARALLEL      (service, arch) downloads to run at once (default: 3, 1 = serial)
  PYPI_INDEX        PyPI mirror (default: Tsinghua)
  PYTORCH_CPU_INDEX PyTorch CPU wheel index (default: SJTU)

`fetch` uses a throwaway container matching the service's base image and
`pip download --platform`, so the host architecture is irrelevant. Each bundle
is a tar.gz whose top level is <arch>/<wheel files>; the Dockerfile extracts
the directory matching TARGETARCH and installs from it with --no-index,
falling back to the network when the bundle is absent.
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

# Count the downloadable artefacts in a cache directory: wheels plus the
# sdist-only tarballs (crcmod, oss2) that requirements.txt needs.
count_artifacts() {
  find "$1" -maxdepth 1 -type f \( -name '*.whl' -o -name '*.tar.gz' \) 2>/dev/null \
    | wc -l | tr -d ' '
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

# pip platform labels for an architecture, space separated.
platform_flags() {
  case "$1" in
    arm64)
      printf '%s' "--platform manylinux_2_28_aarch64 --platform manylinux_2_17_aarch64 --platform manylinux2014_aarch64"
      ;;
    amd64)
      printf '%s' "--platform manylinux_2_28_x86_64 --platform manylinux_2_17_x86_64 --platform manylinux2014_x86_64"
      ;;
    *)
      die "Unsupported arch: $1 (expected arm64 or amd64)"
      ;;
  esac
}

# Split requirements.txt into two derived files used by the download step:
#
#   <staging>/candidates.txt           every "name==version" pin
#   <staging>/requirements-wheels.txt  kept pins, with their hash stanzas
#   <staging>/requirements-sdist.txt   pins that have no cross-platform wheel
#
# requirements.txt is pip-compile output with one pin per stanza
# ("name==version", continued with --hash/--via lines). A cross-platform
# download requires --only-binary=:all:, and any single pin that upstream ships
# as an sdist only aborts the *entire* resolution ("No matching distribution
# found ... from versions: none") — so with one such pin not a single package
# would be cached. Measured on this closure: crcmod==1.7 and oss2==2.19.1 are
# sdist-only, and either alone is enough to empty the cache.
#
# The split is decided by probing, not by a hand-kept list: a name-based
# exception list silently rots the moment the pip-compile closure changes.
# Probing runs in the same throwaway container as the download (see
# pip_download_into), which passes the sdist-only set back in.
split_requirements() {
  local staging="$1"
  local main="$2"

  python3 - "${main}" "${staging}" <<'PY'
import re, sys, pathlib

main = pathlib.Path(sys.argv[1])
staging = pathlib.Path(sys.argv[2])
text = main.read_text().splitlines()

# Parse pip-compile stanzas: a pin line starts a stanza, everything up to the
# next pin line (or EOF) belongs to it.
pins = []
current = None
for line in text:
    m = re.match(r'^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s\\;]+)', line)
    if m and not line.startswith('--'):
        current = [m.group(1), m.group(2), [line]]
        pins.append(current)
    elif current is not None:
        current[2].append(line)

(staging / "candidates.txt").write_text(
    "\n".join(f"{n}=={v}" for n, v, _ in pins) + "\n")

# Keep a pickled-free representation for the second pass: name -> stanza text.
import json
(staging / "stanzas.json").write_text(json.dumps(
    {f"{n}=={v}": "\n".join(s).rstrip() for n, v, s in pins}))

header = [l for l in text[:8] if l.startswith('--')]
(staging / "header.txt").write_text("\n".join(header) + "\n")

print(f"  {len(pins)} pins to probe")
PY
}

# Second half of the split: given the sdist-only names discovered by probing,
# emit the two files pip actually consumes.
emit_requirement_split() {
  local staging="$1"
  shift
  local sdist_names=("$@")

  python3 - "${staging}" "${sdist_names[@]}" <<'PY'
import json, sys, pathlib

staging = pathlib.Path(sys.argv[1])
sdist_only = set(sys.argv[2:])

stanzas = json.loads((staging / "stanzas.json").read_text())
header = (staging / "header.txt").read_text().rstrip("\n")

wheel_pins, sdist_pins = [], []
for spec, stanza in stanzas.items():
    # Compare on the full "name==version" spec: the probe reports exactly that,
    # and matching on the bare name would mis-handle a closure that pins two
    # versions of one distribution.
    if spec in sdist_only:
        sdist_pins.append(spec)
    else:
        wheel_pins.append(stanza)

(staging / "requirements-wheels.txt").write_text(
    header + "\n" + "\n".join(wheel_pins) + "\n")
(staging / "requirements-sdist.txt").write_text(
    "\n".join(sdist_pins) + "\n")

print(f"  {len(wheel_pins)} wheel pins, {len(sdist_pins)} sdist pins "
      f"({', '.join(sdist_pins) if sdist_pins else 'none'})")
PY
}

# Run pip download inside a throwaway container.
#
# $1 arch, $2 destination dir (host path), $3.. pip args
#
# --no-deps is deliberately NOT used for the main requirement files: their
# pins are a complete closure (pip-compile output), so --no-deps would keep
# the resolution fast and still fetch every needed wheel. requirements-docling
# is a hand-maintained 9-line list that *does* need deps resolved.
#
# Downloads happen as root inside the container, so the output is chowned back
# to the invoking user afterwards; a root-owned cache dir would break the next
# local `git clean`/mtime-sensitive tooling and is surprising on a dev box.
pip_download_into() {
  local service="$1" arch="$2" dest="$3"

  local ctx
  ctx="$(context_dir_for "${service}")"
  local py_tag base_image needs_torch
  py_tag="$(py_tag_for "${service}")"
  base_image="$(base_image_for "${service}")"
  needs_torch="$(needs_torch_for "${service}")"

  mkdir -p "${dest}"
  local host_uid host_gid
  host_uid="$(id -u)"
  host_gid="$(id -g)"

  # Derived requirement split, staged next to the real files so the container
  # sees them under /ctx.
  #
  # Per-arch, not per-service: `fetch` runs one combination per (service, arch)
  # in parallel, and a shared staging dir would have two processes truncating
  # and rewriting the same two files while the other's container reads them
  # through the :ro mount -- a half-written requirements-wheels.txt makes pip
  # resolve an empty list and the run dies with "No wheels downloaded".
  local staging="${ctx}/.pip-wheels-staging-${arch}"
  mkdir -p "${staging}"
  printf 'Deriving requirement split:\n'
  split_requirements "${staging}" "${ctx}/${REQUIREMENTS_MAIN}"

  # Probe which pins have no cross-platform wheel. Runs before the main
  # download so the split is decided by observation rather than by a list that
  # would rot when the pip-compile closure changes.
  local sdist_only
  sdist_only="$(
    "${DOCKER_BIN}" run --rm \
      -v "${ROOT_DIR}/${staging}:/stage:ro" \
      "${base_image}" bash -c "
        set -euo pipefail
        pip config set global.index-url '${PYPI_INDEX}' >/dev/null 2>&1 || true
        target=\"--only-binary=:all: $(platform_flags "${arch}") --python-version ${py_tag} --implementation cp --abi cp${py_tag}\"
        while read -r spec; do
          [ -n \"\$spec\" ] || continue
          if ! pip download --no-deps -q -d /tmp/probe \$target \"\$spec\" >/dev/null 2>&1; then
            printf '%s\n' \"\$spec\"
          fi
        done < /stage/candidates.txt
      " 2>/dev/null | tr '\n' ' '
  )"
  # shellcheck disable=SC2086  # word splitting is intended: names are space separated
  emit_requirement_split "${staging}" ${sdist_only}

  # Extra requirement files (e.g. requirements-docling.txt) are expanded on the
  # host so the container string needs no nested command substitution.
  local extras
  extras="$(extra_requirements_for "${service}")"

  "${DOCKER_BIN}" run --rm \
    -v "${ROOT_DIR}/${dest}:/wheels" \
    -v "${ROOT_DIR}/${ctx}:/ctx:ro" \
    "${base_image}" bash -c "
      set -euo pipefail
      pip config set global.index-url '${PYPI_INDEX}' >/dev/null 2>&1 || true

      # Platform + interpreter target: what pip is allowed to pick. Kept on one
      # physical line because the enclosing docker -c argument is itself a
      # double-quoted string and a backslash continuation would need a second
      # level of escaping to survive it.
      target=\"--only-binary=:all: $(platform_flags "${arch}") --python-version ${py_tag} --implementation cp --abi cp${py_tag}\"

      # Reuse wheels already in the cache so a re-run only downloads what
      # changed. With the rm -rf removed from cmd_fetch, fetch is incremental:
      # a bumped pin pulls just the new version, the old one is left in place
      # but ignored by the version-pinned offline install.
      fl=\"--find-links /wheels\"

      echo '--- [1/4] pip / setuptools / wheel ---'
      # A wheel whose build backend needs these still resolves locally, which
      # matters because the cached set is installed offline.
      pip download --progress-bar off -d /wheels \$fl \$target \
        pip setuptools wheel 2>&1 | tail -2

      echo '--- [2/4] torch + torchvision (CPU index) ---'
      if [ '${needs_torch}' = 'true' ]; then
        pip download --progress-bar off -d /wheels \$fl \$target --no-deps \
          --index-url '${PYTORCH_CPU_INDEX}' \
          'torch>=2.2.2,<3.0.0' 'torchvision>=0,<1' 2>&1 | tail -3
        # torch's own metadata deps must be present for the offline install;
        # the CPU index carries them too, so fetch them here rather than
        # relying on the PyPI mirror resolving the same names later.
        pip download --progress-bar off -d /wheels \$fl \$target \
          --index-url '${PYTORCH_CPU_INDEX}' \
          --no-deps 'filelock>=3.13.1' 'typing-extensions>=4.10.0' 'sympy>=1.13.3' \
          'networkx>=2.5.1' 'jinja2>=3.1.3' 'fsspec>=0.8.5' \
          'mpmath>=1.1.0' 'markupsafe>=2.0' 2>&1 | tail -2
      else
        echo '  (this service does not preinstall torch)'
      fi

      echo '--- [3/4] application requirements ---'
      # requirements.txt is a pip-compile closure whose pins may include
      # sdist-only packages (crcmod, oss2 in document-parser). A cross-platform
      # download requires --only-binary=:all:, so one such pin makes pip fail
      # the whole resolution atomically and nothing would be cached. The
      # sdist-only pins were stripped into a second file and are fetched below.
      pip download --progress-bar off -d /wheels \$fl \$target \
        -r /ctx/.pip-wheels-staging-${arch}/requirements-wheels.txt 2>&1 | tail -3

      # sdist-only pins. crcmod falls back to a pure-Python build (its setup.py
      # drops ext_modules when the C extension will not compile), so the
      # resulting install is py3-none-any and architecture independent — safe to
      # share between amd64 and arm64.
      mkdir -p /wheels-sdist
      if [ -s /ctx/.pip-wheels-staging-${arch}/requirements-sdist.txt ]; then
        while read -r spec; do
          [ -n \"\$spec\" ] || continue
          pip download --progress-bar off -d /wheels-sdist --no-deps \"\$spec\" 2>&1 | tail -1
        done < /ctx/.pip-wheels-staging-${arch}/requirements-sdist.txt
      fi

      echo '--- [4/4] extra requirement files ---'
      for extra in ${extras}; do
        [ -f \"/ctx/\$extra\" ] || continue
        pip download --progress-bar off -d /wheels \$fl \$target \
          -r \"/ctx/\$extra\" 2>&1 | tail -3
      done

      # Merge the sdist-only artefacts in, then drop any non-CPU torch.
      cp -f /wheels-sdist/* /wheels/ 2>/dev/null || true

      # Drop any non-CPU torch/torchvision the resolver pulled in anyway, so the
      # offline install can only ever see the +cpu build. The CPU wheels are
      # the ones whose filename carries \"+cpu\"; everything else is the CUDA
      # build from PyPI and would both bloat the bundle and let --no-index pick
      # a torch the image was never tested with.
      if [ '${needs_torch}' = 'true' ]; then
        find /wheels -maxdepth 1 -type f -name 'torch-*.whl' ! -name '*+cpu-*.whl' -delete
        find /wheels -maxdepth 1 -type f -name 'torchvision-*.whl' ! -name '*+cpu-*.whl' -delete
      fi

      chown -R ${host_uid}:${host_gid} /wheels
    " || die "pip download for ${service}/${arch} failed."

  # A CPU torch must be present when this service preinstalls it; without it the
  # offline install would fail outright, and the failure would only surface much
  # later in the image build.
  if [[ "${needs_torch}" == "true" ]]; then
    local cpu_torch
    cpu_torch="$(find "${dest}" -maxdepth 1 -name 'torch-*+cpu-*.whl' | wc -l | tr -d ' ')"
    [[ "${cpu_torch}" -ge 1 ]] \
      || die "No CPU torch wheel for ${service}/${arch} in ${dest}. Check PYTORCH_CPU_INDEX=${PYTORCH_CPU_INDEX}."
  fi

  # The staged requirement split exists only to feed this container. Leaving it
  # behind litters every service context with a dot-dir that `git status` hides
  # but `docker build` still has to hash.
  rm -rf "${staging}"
}

# One (service, arch) pair per line, in a stable order.
fetch_combinations() {
  local service arch
  for service in "$@"; do
    for arch in ${ARCH_LIST}; do
      printf '%s %s\n' "${service}" "${arch}"
    done
  done
}

# Count what landed in a cache dir and report it. Shared by the serial and
# parallel paths so both print the same summary line.
report_fetch_result() {
  local service="$1" arch="$2" dest="$3"
  local n size
  n="$(count_artifacts "${dest}")"
  size="$(du -sk "${dest}" | cut -f1)"
  [[ "${n}" -gt 0 ]] || die "No wheels downloaded for ${service}/${arch}."
  printf '  %s/%s: %s artifacts, %s\n' \
    "${service}" "${arch}" "${n}" "$(human_size "$((size * 1024))")"
}

# One (service, arch) wheel download. Called directly on the serial path and
# re-entered as the `fetch-one` subcommand from the parallel path.
fetch_one() {
  local service="$1" arch="$2"
  local dest="${CACHE_DIR}/${service}/${arch}"
  printf 'Fetching wheels for %s/linux/%s into %s ...\n' "${service}" "${arch}" "${dest}"
  # Incremental cache: keep already-downloaded wheels so a re-run only fetches
  # what actually changed (e.g. a bumped pin). pip reuses a local wheel that
  # satisfies the requirement via --find-links, so wheels are never
  # re-downloaded. A stale wheel of the same name is harmless: the offline
  # install pins exact versions (and --require-hashes), so an unreferenced wheel
  # is simply ignored, not installed.
  mkdir -p "${dest}"
  pip_download_into "${service}" "${arch}" "${dest}"
  report_fetch_result "${service}" "${arch}" "${dest}"
}

cmd_fetch() {
  local services=("$@")
  [[ "${#services[@]}" -eq 0 ]] && read -r -a services <<< "${SERVICE_LIST}"

  require_docker

  # Validate every input up front: a missing requirements file should fail in
  # the first second, not after several parallel downloads have already run.
  local service ctx main extra
  for service in "${services[@]}"; do
    ctx="$(context_dir_for "${service}")"
    main="${ctx}/${REQUIREMENTS_MAIN}"
    [[ -f "${main}" ]] || die "Missing ${main}"
    for extra in $(extra_requirements_for "${service}"); do
      [[ -f "${ctx}/${extra}" ]] || die "Missing ${ctx}/${extra}"
    done
  done
  local arch
  for arch in ${ARCH_LIST}; do
    platform_flags "${arch}" >/dev/null   # validate early
  done

  local -a combos=()
  local combo
  while IFS= read -r combo; do
    combos+=("${combo}")
  done < <(fetch_combinations "${services[@]}")

  # Serial path: one combination, or MAX_PARALLEL=1. Keeps the old behaviour
  # available for debugging and for links too slow to share.
  if [[ "${#combos[@]}" -le 1 || "${MAX_PARALLEL}" -le 1 ]]; then
    for combo in "${combos[@]}"; do
      read -r service arch <<< "${combo}"
      fetch_one "${service}" "${arch}"
    done
  else
    # Parallel path. Each combination re-executes this script as `fetch-one`
    # in its own process: the work is a docker run plus a host-side pip probe,
    # so there is no shared state to protect beyond the per-arch staging dir
    # (see pip_download_into). Logs go to files because six interleaved pip
    # progress bars are unreadable; they are replayed in a stable order after.
    local logdir="${CACHE_DIR}/.fetch-logs"
    rm -rf "${logdir}"
    mkdir -p "${logdir}"

    printf 'Fetching %s combinations, up to %s at a time ...\n' \
      "${#combos[@]}" "${MAX_PARALLEL}"
    printf '  logs: %s\n' "${logdir}"

    local rc=0
    printf '%s\n' "${combos[@]}" \
      | MOGO_FETCH_LOGDIR="${logdir}" MOGO_FETCH_SELF="${SELF}" \
        xargs -P "${MAX_PARALLEL}" -n 2 \
        bash -c 'bash "${MOGO_FETCH_SELF}" fetch-one "$1" "$2" > "${MOGO_FETCH_LOGDIR}/$1-$2.log" 2>&1' _ \
      || rc=$?

    if [[ "${rc}" -ne 0 ]]; then
      printf '\n--- failing combination(s) ---\n'
      local log
      for combo in "${combos[@]}"; do
        read -r service arch <<< "${combo}"
        log="${logdir}/${service}-${arch}.log"
        if [[ -f "${log}" ]] && grep -qE '(^Error|ERROR:|error:|failed)' "${log}" 2>/dev/null; then
          printf '\n== %s/%s ==\n' "${service}" "${arch}"
          tail -15 "${log}"
        fi
      done
      die "fetch failed (exit ${rc}); full logs: ${logdir}"
    fi

    for combo in "${combos[@]}"; do
      read -r service arch <<< "${combo}"
      grep -h 'artifacts' "${logdir}/${service}-${arch}.log" 2>/dev/null | tail -1
    done
  fi

  write_manifest
  printf '\nRun `%s pack` to refresh the build-context bundles.\n' "$0"
}

write_manifest() {
  mkdir -p "${CACHE_DIR}"
  {
    printf '# mogo pip wheel cache\n'
    printf '# generated: %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    printf '# pypi_index: %s\n' "${PYPI_INDEX}"
    printf '# pytorch_cpu_index: %s\n' "${PYTORCH_CPU_INDEX}"
    for service in ${SERVICE_LIST}; do
      printf '\n[%s]\n' "${service}"
      printf 'python=%s (cp%s)\n' "$(py_version_for "${service}")" "$(py_tag_for "${service}")"
      printf 'base_image=%s\n' "$(base_image_for "${service}")"
      local ctx
      ctx="$(context_dir_for "${service}")"
      for req in "${REQUIREMENTS_MAIN}" $(extra_requirements_for "${service}"); do
        printf '  %s_sha256=%s\n' "${req%.txt}" \
          "$(shasum -a 256 "${ctx}/${req}" 2>/dev/null | cut -d' ' -f1 || printf 'n/a')"
      done
      for arch in ${ARCH_LIST}; do
        local d="${CACHE_DIR}/${service}/${arch}"
        [[ -d "${d}" ]] || continue
        local n size
        n="$(count_artifacts "${d}")"
        size="$(du -sk "${d}" | cut -f1)"
        printf '  %s=%s artifacts, %s\n' "${arch}" "${n}" "$(human_size "$((size * 1024))")"
        # Record the torch cpu build so a stale cache is detectable when the
        # Dockerfile's torch constraint moves.
        #
        # Written as an `if`, not `[[ ... ]] && printf`: only document-parser
        # has a torch wheel, so for chat-api/admin-api this is the last command
        # in the redirected block and a bare `&&` would leave the block's exit
        # status at 1 -- under `set -e` that aborted `fetch` *after* every wheel
        # had downloaded successfully, with no error message.
        local tv
        tv="$(find "${d}" -name 'torch-*+cpu-*.whl' -exec basename {} \; 2>/dev/null | head -1 || true)"
        if [[ -n "${tv}" ]]; then
          printf '  %s_torch=%s\n' "${arch}" "${tv}"
        fi
      done
    done
  } > "${CACHE_DIR}/manifest.txt"
}

# --- cache freshness -------------------------------------------------------
#
# A reproducible bundle can still be an unusable one. The Dockerfiles install
# with `--no-index --find-links=<bundle>`, so a wheel that is missing from the
# bundle is a hard build failure -- there is no network fallback once the bundle
# is detected as real. That happens whenever a requirements.txt moves after the
# last `fetch`, which is easy to miss because nothing in the build says so until
# it dies minutes in. `write_manifest` records each requirements file's sha256
# at fetch time; these helpers compare that against the working tree.

# Recorded requirements hash for a service. Empty when the manifest is missing
# or predates the service.
manifest_req_sha() {
  local service="$1" req="${2:-${REQUIREMENTS_MAIN}}"
  local key="${req%.txt}_sha256"
  [[ -f "${CACHE_DIR}/manifest.txt" ]] || return 0
  awk -v svc="${service}" -v key="${key}" '
    /^\[.*\]$/ { in_svc = ($0 == "[" svc "]"); next }
    in_svc && index($0, key "=") { sub(/^[^=]*=/, ""); print; exit }
  ' "${CACHE_DIR}/manifest.txt"
}

# 0 = cache matches requirements, 1 = requirements moved after fetch (build will
# fail), 2 = cannot tell (no recorded hash).
cache_freshness() {
  local service="$1"
  local recorded current
  recorded="$(manifest_req_sha "${service}")"
  [[ -n "${recorded}" ]] || return 2
  current="$(shasum -a 256 "$(context_dir_for "${service}")/${REQUIREMENTS_MAIN}" 2>/dev/null | cut -d' ' -f1)"
  [[ -n "${current}" ]] || return 2
  [[ "${recorded}" == "${current}" ]] && return 0
  return 1
}

# Print a stale-cache warning for each named service that needs one.
warn_if_stale() {
  local stale=0 service fresh
  for service in "$@"; do
    fresh=0
    cache_freshness "${service}" || fresh=$?
    if [[ "${fresh}" -eq 1 ]]; then
      stale=1
      printf '  WARNING: %s/%s changed after the wheel cache was built.\n' \
        "${service}" "${REQUIREMENTS_MAIN}"
      printf '           An offline build will fail at --no-index. Run: %s fetch %s\n' \
        "$0" "${service}"
    fi
  done
  return "${stale}"
}

cmd_pack() {
  local services=("$@")
  [[ "${#services[@]}" -eq 0 ]] && read -r -a services <<< "${SERVICE_LIST}"

  [[ -d "${CACHE_DIR}" ]] || die "No cache at ${CACHE_DIR}. Run fetch first."

  local found=0
  for service in "${services[@]}"; do
    local staged bundle fp
    bundle="$(bundle_path_for "${service}")"

    # Fingerprint the whole per-service cache (every arch) plus the arch list,
    # so switching ARCH_LIST cannot reuse a bundle packed for another set.
    # Tested *before* staging: an untouched cache costs one stat pass instead
    # of a full copy plus a full re-tar (measured: 5m52s -> under a second).
    fp="$(bundle_fingerprint "${CACHE_DIR}/${service}") arch=${ARCH_LIST}"

    if bundle_fp_hit "${bundle}" "${fp}"; then
      printf '  %s: unchanged -> %s\n' "${service}" "${bundle}"
      printf '    %s (cache fingerprint matches; COPY layer stays cached)\n' \
        "$(human_size "$(wc -c < "${bundle}" | tr -d ' ')")"
      found=1
      continue
    fi

    staged="$(bundle_stage_dir)" || die "Cannot create a staging directory."

    local total=0
    for arch in ${ARCH_LIST}; do
      local d="${CACHE_DIR}/${service}/${arch}"
      [[ -d "${d}" ]] || continue
      local n
      # Count and copy wheels *and* sdists: the sdist-only pins are what make
      # the offline install of requirements.txt resolve at all, so packing only
      # *.whl would produce a bundle that cannot install.
      n="$(find "${d}" -maxdepth 1 -type f \( -name '*.whl' -o -name '*.tar.gz' \) | wc -l | tr -d ' ')"
      [[ "${n}" -gt 0 ]] || continue
      # Clone instead of copying: same-volume APFS clonefile is a metadata
      # operation, which is the difference between 0.1s and ~50s per arch.
      bundle_clone_files "${staged}/${arch}" "${d}"/*.whl 2>/dev/null || true
      bundle_clone_files "${staged}/${arch}" "${d}"/*.tar.gz 2>/dev/null || true
      total=$((total + n))
    done

    if [[ "${total}" -eq 0 ]]; then
      rm -rf "${staged}" 2>/dev/null || true
      printf '  %s: no cached wheels, skipped\n' "${service}"
      continue
    fi

    printf '  %s: packing %s artifacts -> %s\n' "${service}" "${total}" "${bundle}"
    local rc=0
    bundle_pack "${bundle}" "${staged}" "${fp}" || rc=$?
    rm -rf "${staged}" 2>/dev/null || true
    [[ "${rc}" -le 1 ]] || die "Packing ${bundle} failed."

    local out_size
    out_size="$(wc -c < "${bundle}" | tr -d ' ')"
    if [[ "${rc}" -eq 0 ]]; then
      printf '    %s (repacked)\n' "$(human_size "${out_size}")"
    else
      printf '    %s (unchanged; COPY layer stays cached)\n' "$(human_size "${out_size}")"
    fi
    found=1
  done

  [[ "${found}" -eq 1 ]] || die "Nothing packed. Run fetch first."
  printf '\n'
  warn_if_stale "${services[@]}" || true
  printf '\nRebuild to use them:\n'
  printf '  docker compose -f docker-compose.yml -f docker-compose.build.yml build document-api chat-api admin-api\n'
  printf 'The COPY layer re-executes only when a bundle changes; same bundle = cached.\n'
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
  printf 'pip wheel cache:\n\n'

  local any=0
  for service in ${SERVICE_LIST}; do
    for arch in ${ARCH_LIST}; do
      local d="${CACHE_DIR}/${service}/${arch}"
      [[ -d "${d}" ]] || continue
      any=1
      local n size
      n="$(count_artifacts "${d}")"
      size="$(du -sk "${d}" | cut -f1)"
      printf '  [cache]  %-18s %-6s %4s artifacts  %s\n' \
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
        printf '  [bundle]      %-18s %s  (%s)\n' \
          "${service}" "${bundle}" "$(human_size "${bsize}")"
      else
        printf '  [placeholder] %-18s %s  (%s) - online install will be used\n' \
          "${service}" "${bundle}" "$(human_size "${bsize}")"
      fi
    else
      printf '  [missing]     %-18s %s - run pack (no placeholder in git: COPY will fail until this exists)\n' "${service}" "${bundle}"
    fi

    local fresh=0
    cache_freshness "${service}" || fresh=$?
    if [[ "${fresh}" -eq 1 ]]; then
      printf '  [stale]       %-18s %s is newer than this cache - offline build fails; run: %s fetch %s\n' \
        "${service}" "${REQUIREMENTS_MAIN}" "$0" "${service}"
    elif [[ "${fresh}" -eq 2 ]]; then
      printf '  [unchecked]   %-18s no recorded %s hash (run fetch to record one)\n' \
        "${service}" "${REQUIREMENTS_MAIN}"
    fi
  done
}

cmd_verify() {
  local image="${1:-document-parser:latest}"
  require_docker
  "${DOCKER_BIN}" image inspect "${image}" >/dev/null 2>&1 \
    || die "Image ${image} not found locally."

  printf 'Checking installed packages in %s ...\n' "${image}"

  # The check body is written to a file and mounted rather than passed with
  # -c: it contains quotes, a loop and an inline python program, and nesting
  # all of that inside a single-quoted -c argument is unmaintainable.
  local script
  script="$(mktemp)"
  trap 'rm -f "${script:-}"' EXIT

  cat > "${script}" <<'CHECK'
set -e
# The point of the wheel cache is that these land in the image; a bundle that
# quietly installed nothing would otherwise be invisible.
missing=0
for mod in docling torch torchvision onnxruntime transformers cv2 numpy fastapi celery; do
  if python -c "import ${mod}" 2>/dev/null; then
    echo "  OK: ${mod}"
  else
    echo "  BAD: ${mod} not importable"
    missing=1
  fi
done

echo "--- versions ---"
python -c 'import importlib.metadata as md
for p in ("docling","torch","torchvision","onnxruntime","numpy","fastapi"):
    try:
        print("  %s==%s" % (p, md.version(p)))
    except Exception:
        pass'

echo "--- torch accelerator ---"
python -c 'import torch; print("  torch %s, cuda_available=%s" % (torch.__version__, torch.cuda.is_available()))'

echo "--- docling converter smoke ---"
python -c 'from docling.document_converter import DocumentConverter; print("  DocumentConverter import OK")'

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
  fetch-one)
    # Internal: a single (service, arch) combination. The parallel path above
    # re-enters this script through xargs, which cannot call a shell function.
    # Deliberately absent from `usage`.
    fetch_one "${1:-}" "${2:-}"
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
