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
#       - tracked in git as a <1KB placeholder so COPY never fails
#       - overwritten in place by `save` with the real bundle
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

CONTEXT_DIR="services/document-parser"
BUNDLE_NAME="pip-wheels-bundle.tar.gz"
BUNDLE_PATH="${CONTEXT_DIR}/${BUNDLE_NAME}"
CACHE_DIR="base-images/pip-wheels"
MANIFEST="${CACHE_DIR}/manifest.txt"

REQUIREMENTS_MAIN="${CONTEXT_DIR}/requirements.txt"
REQUIREMENTS_DOCLING="${CONTEXT_DIR}/requirements-docling.txt"

DOCKER_BIN="${DOCKER_BIN:-docker}"

# Python target of the document-parser image (python:3.10-slim-bookworm).
PY_VERSION="3.10"
PY_TAG="310"

# Indexes. The CPU torch wheels only exist on the PyTorch CPU index (PyPI
# ships the CUDA build), so that leg cannot follow the PyPI mirror.
PYPI_INDEX="${PYPI_INDEX:-https://pypi.tuna.tsinghua.edu.cn/simple}"
PYTORCH_CPU_INDEX="${PYTORCH_CPU_INDEX:-https://mirror.sjtu.edu.cn/pytorch-wheels/cpu}"

# Platform labels pip must consider for each arch. manylinux tags are cumulative
# and pip does not infer older ones from a newer tag, so all of them are listed;
# omitting manylinux2014_x86_64 silently drops most amd64 wheels (verified).
ARCH_LIST="${ARCH_LIST:-arm64 amd64}"

usage() {
  cat <<'USAGE'
Usage:
  scripts/pip_wheels_bundle.sh fetch [arch...]  Download wheels into base-images/pip-wheels/
                                                (default: arm64 amd64)
  scripts/pip_wheels_bundle.sh pack             Re-pack the bundle from the cache
  scripts/pip_wheels_bundle.sh save [arch...]   fetch + pack in one step
  scripts/pip_wheels_bundle.sh list             Show cache + bundle status
  scripts/pip_wheels_bundle.sh verify [image]   Check that an image has the expected
                                                runtime packages installed

Environment:
  DOCKER_BIN        Docker binary to use (default: docker)
  ARCH_LIST         Architectures to fetch (default: "arm64 amd64")
  PYPI_INDEX        PyPI mirror (default: Tsinghua)
  PYTORCH_CPU_INDEX PyTorch CPU wheel index (default: SJTU)

`fetch` uses a throwaway python:3.10-slim-bookworm container and
`pip download --platform`, so the host architecture is irrelevant. The bundle
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
  local main="${REQUIREMENTS_MAIN}"

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
  local arch="$1" dest="$2"
  shift 2

  mkdir -p "${dest}"
  local host_uid host_gid
  host_uid="$(id -u)"
  host_gid="$(id -g)"

  # Derived requirement split, staged next to the real files so the container
  # sees them under /ctx.
  local staging="${CONTEXT_DIR}/.pip-wheels-staging"
  mkdir -p "${staging}"
  printf 'Deriving requirement split:\n'
  split_requirements "${staging}"

  # Probe which pins have no cross-platform wheel. Runs before the main
  # download so the split is decided by observation rather than by a list that
  # would rot when the pip-compile closure changes.
  local sdist_only
  sdist_only="$(
    "${DOCKER_BIN}" run --rm \
      -v "${ROOT_DIR}/${staging}:/stage:ro" \
      python:3.10-slim-bookworm bash -c "
        set -euo pipefail
        pip config set global.index-url '${PYPI_INDEX}' >/dev/null
        target=\"--only-binary=:all: $(platform_flags "${arch}") --python-version ${PY_TAG} --implementation cp --abi cp${PY_TAG}\"
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

  "${DOCKER_BIN}" run --rm \
    -v "${ROOT_DIR}/${dest}:/wheels" \
    -v "${ROOT_DIR}/${CONTEXT_DIR}:/ctx:ro" \
    python:3.10-slim-bookworm bash -c "
      set -euo pipefail
      pip config set global.index-url '${PYPI_INDEX}' >/dev/null

      # Platform + interpreter target: what pip is allowed to pick. Kept on one
      # physical line because the enclosing docker -c argument is itself a
      # double-quoted string and a backslash continuation would need a second
      # level of escaping to survive it.
      target=\"--only-binary=:all: $(platform_flags "${arch}") --python-version ${PY_TAG} --implementation cp --abi cp${PY_TAG}\"

      echo '--- [1/3] pip / setuptools / wheel ---'
      # tools=for-build: a wheel whose build backend needs these still resolves
      # locally, which matters because the cached set is installed offline.
      pip download --progress-bar off -d /wheels \$target \
        pip setuptools wheel 2>&1 | tail -2 || true

      echo '--- [2/3] torch + torchvision (CPU index) ---'
      pip download --progress-bar off -d /wheels \$target --no-deps \
        --index-url '${PYTORCH_CPU_INDEX}' \
        'torch>=2.2.2,<3.0.0' 'torchvision>=0,<1' 2>&1 | tail -3 || true
      # torch's own metadata deps must be present for the offline install; the
      # CPU index carries them too, so fetch them here rather than relying on
      # the PyPI mirror resolving the same names later.
      pip download --progress-bar off -d /wheels \$target \
        --index-url '${PYTORCH_CPU_INDEX}' \
        --no-deps 'filelock>=3.13.1' 'typing-extensions>=4.10.0' 'sympy>=1.13.3' \
        'networkx>=2.5.1' 'jinja2>=3.1.3' 'fsspec>=0.8.5' \
        'mpmath>=1.1.0' 'markupsafe>=2.0' 2>&1 | tail -2 || true

      echo '--- [3/3] application requirements ---'
      # requirements.txt is a pip-compile closure of 61 pins, one of which
      # (crcmod==1.7) upstream ships as an sdist only. A cross-platform download
      # requires --only-binary=:all:, so that single pin makes pip fail the whole
      # resolution atomically and not one of the 61 packages would be cached.
      # Strip the sdist-only pins into a second file, fetch the rest as wheels,
      # and take the stripped ones as sdists in the side directory below.
      pip download --progress-bar off -d /wheels \$target \
        -r /ctx/.pip-wheels-staging/requirements-wheels.txt 2>&1 | tail -3 || true

      # sdist-only pins. crcmod falls back to a pure-Python build (its setup.py
      # drops ext_modules when the C extension will not compile), so the
      # resulting install is py3-none-any and architecture independent — safe to
      # share between amd64 and arm64.
      mkdir -p /wheels-sdist
      while read -r spec; do
        [ -n \"\$spec\" ] || continue
        pip download --progress-bar off -d /wheels-sdist --no-deps \"\$spec\" 2>&1 | tail -1 || true
      done < /ctx/.pip-wheels-staging/requirements-sdist.txt

      pip download --progress-bar off -d /wheels \$target \
        -r /ctx/requirements-docling.txt 2>&1 | tail -3 || true

      # Merge the sdist-only artefacts in, then drop any non-CPU torch.
      cp -f /wheels-sdist/* /wheels/ 2>/dev/null || true

      # Drop any non-CPU torch/torchvision the resolver pulled in anyway, so the
      # offline install can only ever see the +cpu build. The CPU wheels are
      # the ones whose filename carries "+cpu"; everything else is the CUDA
      # build from PyPI and would both bloat the bundle and let --no-index pick
      # a torch the image was never tested with.
      find /wheels -maxdepth 1 -type f -name 'torch-*.whl' ! -name '*+cpu-*.whl' -delete
      find /wheels -maxdepth 1 -type f -name 'torchvision-*.whl' ! -name '*+cpu-*.whl' -delete

      chown -R ${host_uid}:${host_gid} /wheels
    " || die "pip download for ${arch} failed."

  # A CPU torch must be present; without it the offline install would fail
  # outright, and the failure would only surface much later in the image build.
  local cpu_torch
  cpu_torch="$(find "${dest}" -maxdepth 1 -name 'torch-*+cpu-*.whl' | wc -l | tr -d ' ')"
  [[ "${cpu_torch}" -ge 1 ]] \
    || die "No CPU torch wheel for ${arch} in ${dest}. Check PYTORCH_CPU_INDEX=${PYTORCH_CPU_INDEX}."
}

cmd_fetch() {
  local archs=("$@")
  [[ "${#archs[@]}" -eq 0 ]] && read -r -a archs <<< "${ARCH_LIST}"

  require_docker
  [[ -f "${REQUIREMENTS_MAIN}" ]] || die "Missing ${REQUIREMENTS_MAIN}"
  [[ -f "${REQUIREMENTS_DOCLING}" ]] || die "Missing ${REQUIREMENTS_DOCLING}"

  for arch in "${archs[@]}"; do
    platform_flags "${arch}" >/dev/null   # validate early
    local dest="${CACHE_DIR}/${arch}"
    printf 'Fetching wheels for linux/%s into %s ...\n' "${arch}" "${dest}"
    # Clear first: a wheel left from an earlier requirements revision would be
    # installed silently, because --no-index cannot tell it is stale.
    rm -rf "${dest}"
    pip_download_into "${arch}" "${dest}"

    local n size
    n="$(count_artifacts "${dest}")"
    size="$(du -sk "${dest}" | cut -f1)"
    [[ "${n}" -gt 0 ]] || die "No wheels downloaded for ${arch}."
    printf '  %s: %s artifacts, %s\n' "${arch}" "${n}" "$(human_size "$((size * 1024))")"
  done

  write_manifest
  printf '\nRun `%s pack` to refresh the build-context bundle.\n' "$0"
}

write_manifest() {
  mkdir -p "${CACHE_DIR}"
  {
    printf '# movo pip wheel cache\n'
    printf '# generated: %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    printf '# python: %s (cp%s)\n' "${PY_VERSION}" "${PY_TAG}"
    printf '# pypi_index: %s\n' "${PYPI_INDEX}"
    printf '# pytorch_cpu_index: %s\n' "${PYTORCH_CPU_INDEX}"
    for arch in ${ARCH_LIST}; do
      local d="${CACHE_DIR}/${arch}"
      [[ -d "${d}" ]] || continue
      local n size
      n="$(count_artifacts "${d}")"
      size="$(du -sk "${d}" | cut -f1)"
      printf 'arch_%s=%s artifacts, %s\n' "${arch}" "${n}" "$(human_size "$((size * 1024))")"
      # Record the torch cpu build so a stale cache is detectable when the
      # Dockerfile's torch constraint moves.
      local tv
      tv="$(find "${d}" -name 'torch-*+cpu-*.whl' -exec basename {} \; 2>/dev/null | head -1 || true)"
      [[ -n "${tv}" ]] && printf '  %s_torch=%s\n' "${arch}" "${tv}"
    done
    printf '# requirements_main_sha256=%s\n' \
      "$(shasum -a 256 "${REQUIREMENTS_MAIN}" 2>/dev/null | cut -d' ' -f1 || printf 'n/a')"
    printf '# requirements_docling_sha256=%s\n' \
      "$(shasum -a 256 "${REQUIREMENTS_DOCLING}" 2>/dev/null | cut -d' ' -f1 || printf 'n/a')"
  } > "${MANIFEST}"
}

cmd_pack() {
  [[ -d "${CACHE_DIR}" ]] || die "No cache at ${CACHE_DIR}. Run fetch first."

  local staged
  staged="$(mktemp -d)"
  trap 'rm -rf "${staged:-}"' EXIT

  local total=0 found=0
  for arch in ${ARCH_LIST}; do
    local d="${CACHE_DIR}/${arch}"
    [[ -d "${d}" ]] || continue
    local n
    # Count and copy wheels *and* sdists: the sdist-only pins (crcmod, oss2)
    # are what make the offline install of requirements.txt resolve at all, so
    # packing only *.whl would produce a bundle that cannot install.
    n="$(find "${d}" -maxdepth 1 -type f \( -name '*.whl' -o -name '*.tar.gz' \) | wc -l | tr -d ' ')"
    [[ "${n}" -gt 0 ]] || continue
    mkdir -p "${staged}/${arch}"
    cp "${d}"/*.whl "${staged}/${arch}/" 2>/dev/null || true
    cp "${d}"/*.tar.gz "${staged}/${arch}/" 2>/dev/null || true
    total=$((total + n))
    found=1
  done

  [[ "${found}" -eq 1 ]] || die "No wheels in ${CACHE_DIR}/*/. Run fetch first."

  printf 'Packing %s files -> %s ...\n' "${total}" "${BUNDLE_PATH}"
  tar -czf "${BUNDLE_PATH}" -C "${staged}" .

  local out_size
  out_size="$(wc -c < "${BUNDLE_PATH}" | tr -d ' ')"
  printf '\nBundle written: %s (%s, %s artifacts)\n' \
    "${BUNDLE_PATH}" "$(human_size "${out_size}")" "${total}"
  printf 'Sizes by arch:\n'
  for arch in ${ARCH_LIST}; do
    local d="${CACHE_DIR}/${arch}"
    [[ -d "${d}" ]] || continue
    printf '  %-6s %s\n' "${arch}" "$(human_size "$(( $(du -sk "${d}" | cut -f1) * 1024 ))")"
  done
  printf '\nRebuild the image to use it:\n'
  printf '  docker compose -f docker-compose.yml -f docker-compose.build.yml build document-api\n'
  printf 'The COPY layer re-executes only when this tar.gz changes; same bundle = cached.\n'
}

cmd_save() {
  cmd_fetch "$@"
  cmd_pack
}

cmd_list() {
  printf 'pip wheel cache:\n\n'

  if [[ -d "${CACHE_DIR}" ]]; then
    local any=0
    for arch in ${ARCH_LIST}; do
      local d="${CACHE_DIR}/${arch}"
      [[ -d "${d}" ]] || continue
      any=1
      local n size
      n="$(count_artifacts "${d}")"
      size="$(du -sk "${d}" | cut -f1)"
      printf '  [cache]     %-6s %s  (%s artifacts, %s)\n' \
        "${arch}" "${d}" "${n}" "$(human_size "$((size * 1024))")"
    done
    [[ "${any}" -eq 1 ]] || printf '  [empty]     %s  - run fetch first\n' "${CACHE_DIR}"
  else
    printf '  [missing]   %s  - run fetch first\n' "${CACHE_DIR}"
  fi

  if [[ -f "${MANIFEST}" ]]; then
    printf '\n'
    sed 's/^/  /' "${MANIFEST}"
  fi

  printf '\nBundle for the build context:\n\n'
  if [[ -f "${BUNDLE_PATH}" ]]; then
    local bsize
    bsize="$(wc -c < "${BUNDLE_PATH}" | tr -d ' ')"
    if [[ "${bsize}" -gt 1024 ]]; then
      printf '  [bundle]    %s  (%s)  - offline install will work\n' \
        "${BUNDLE_PATH}" "$(human_size "${bsize}")"
    else
      printf '  [placeholder] %s  (%s)  - online install path will be used\n' \
        "${BUNDLE_PATH}" "$(human_size "${bsize}")"
    fi
  else
    printf '  [missing]   %s  - run pack (or restore the placeholder)\n' "${BUNDLE_PATH}"
  fi
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
  pack)
    cmd_pack
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
