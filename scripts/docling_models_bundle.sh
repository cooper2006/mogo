#!/usr/bin/env bash
set -Eeuo pipefail

# Manage the Docling model bundle used by services/document-parser's Dockerfile.
# The bundle lets the image build skip the slow HuggingFace (hf-mirror) download
# of ~525MB of model files by extracting a pre-saved tar.gz into the image.
#
# Layout:
#   base-images/docling-models/                    persistent cache (git-ignored,
#                                                   /base-images/ via .gitignore)
#       models/                                    the /opt/docling/models tree
#       manifest.txt                               docling version + model inventory
#   services/document-parser/docling-models-bundle.tar.gz
#       - tracked in git as a <1KB empty placeholder so COPY never fails
#       - overwritten in place by `save` with the real bundle
#
# The build context is services/document-parser, so `save` runs against a
# locally-built image (or copies out of a running one) and writes the bundle
# straight into that context.
#
# Incremental download. The model files are expensive (~525MB from hf-mirror)
# and the docling version pins the exact model set, so re-fetching on every run
# is pure waste. The cache under base-images/ records the docling version and a
# model-file inventory, which gates every step:
#
#   - `fetch` downloads from HuggingFace into the cache. huggingface_hub skips
#     files already present in DOCLING_ARTIFACTS_PATH, so a version bump pulls
#     only the new/changed files; and the manifest makes a re-run whose version
#     is unchanged skip the whole container (including the CPU torch + docling
#     install, which a persistent pip cache makes incremental too).
#   - `save` extracts from an image into the cache only when the cache is not
#     current for that image's docling version.
#   - `pack` re-packs the bundle only when it does not already match the cache.
#
# The net effect: the first fetch/save pays the full cost; every later run with
# the same docling version is a manifest comparison and nothing more.
#
# NOTE: the bundle covers the *model files* only. The apt libraries and the
# Python stack (torch etc.) are cached separately (base-images/apt,
# base-images/pip-wheels).

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

CONTEXT_DIR="services/document-parser"
BUNDLE_NAME="docling-models-bundle.tar.gz"
BUNDLE_PATH="${CONTEXT_DIR}/${BUNDLE_NAME}"

CACHE_DIR="base-images/docling-models"
MODELS_DIR="${CACHE_DIR}/models"
MANIFEST="${CACHE_DIR}/manifest.txt"

DOCKER_BIN="${DOCKER_BIN:-docker}"

# HuggingFace endpoint + timeout, matching the Dockerfile's MOVO_HF_ENDPOINT /
# MOVO_HF_TIMEOUT args so `fetch` and the build never disagree about the mirror.
HF_ENDPOINT="${MOVO_HF_ENDPOINT:-https://hf-mirror.com}"
HF_TIMEOUT="${MOVO_HF_TIMEOUT:-120}"

usage() {
  cat <<'USAGE'
Usage:
  scripts/docling_models_bundle.sh fetch            Download Docling models from
                                                   HuggingFace into the cache
                                                   (incremental: skips when the
                                                   recorded version is current)
  scripts/docling_models_bundle.sh save [image]     Cache models from an image and
                                                   write the bundle into the build
                                                   context (incremental)
  scripts/docling_models_bundle.sh pack             Re-pack the bundle from the cache
  scripts/docling_models_bundle.sh list             Show cache + bundle status
  scripts/docling_models_bundle.sh verify [image]  Check an image's /opt/docling/models

Environment:
  DOCKER_BIN              Docker binary to use (default: docker)
  MOVO_HF_ENDPOINT        HuggingFace mirror (default: hf-mirror.com)
  MOVO_HF_TIMEOUT         Per-request timeout in seconds (default: 120)

`save` defaults to document-parser:latest. The bundle is a tar.gz of the
image's /opt/docling/models tree; build the image normally (or with
INSTALL_DOCLING_MODELS_AT_BUILD=true) first so the models are present.
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
    printf '%s B' "${bytes}"
  fi
}

# The docling version pinned in the service's requirement file. `fetch` uses
# this to decide whether the cache is already current *before* spinning up the
# download container, so a re-run with an unchanged pin costs a manifest read.
docling_version_pin() {
  local req="${CONTEXT_DIR}/requirements-docling.txt"
  [[ -f "${req}" ]] || return 0
  grep -oE '^docling==[0-9.]+' "${req}" | head -1 | cut -d= -f3
}

# The docling version actually installed in an image.
docling_version_in() {
  local image="$1"
  "${DOCKER_BIN}" run --rm --entrypoint sh "${image}" \
    -c 'python -c "import importlib.metadata as m; print(m.version(\"docling\"))" 2>/dev/null' \
    2>/dev/null | tr -d '[:space:]'
}

# Model-file inventory: "<count> <total_bytes>". Portable across macOS/Linux —
# `wc -c` totalises over `find -exec ... +`, so no GNU `-printf` is needed.
inventory() {
  local dir="$1"
  local n bytes
  n="$(find "${dir}" -type f 2>/dev/null | wc -l | tr -d ' ')"
  bytes="$(find "${dir}" -type f -exec wc -c {} + 2>/dev/null | tail -1 | awk '{print $1}')"
  [[ -n "${bytes}" ]] || bytes=0
  printf '%s %s' "${n}" "${bytes}"
}

# Is the cache already current for a given docling version? The version must
# match the manifest *and* the model tree must still hold exactly the inventory
# the manifest recorded — a partial download or a stray file fails the check.
cache_current() {
  local version="$1"
  [[ -f "${MANIFEST}" ]] || return 1
  local mv
  mv="$(sed -n 's/^docling_version=//p' "${MANIFEST}" | head -1)"
  [[ -n "${mv}" && "${mv}" == "${version}" ]] || return 1
  [[ -d "${MODELS_DIR}" ]] || return 1
  local cur want
  cur="$(inventory "${MODELS_DIR}")"
  want="$(sed -n 's/^inventory=//p' "${MANIFEST}" | head -1)"
  [[ -n "${want}" && "${cur}" == "${want}" ]] || return 1
  return 0
}

write_manifest() {
  local version="$1" source="$2"
  mkdir -p "${CACHE_DIR}"
  {
    printf '# movo docling model cache\n'
    printf '# generated: %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    printf '# source: %s\n' "${source}"
    printf 'docling_version=%s\n' "${version}"
    printf 'inventory=%s\n' "$(inventory "${MODELS_DIR}")"
  } > "${MANIFEST}"
}

# Set (or append) one key=value line in the manifest. Written via a temp file +
# rename rather than `sed -i`: the host may be macOS (BSD sed), where
# `sed -i "script" file` silently treats the script as a backup suffix and
# corrupts the manifest. `sed` without -i to a temp + mv is portable.
set_manifest_key() {
  local key="$1" value="$2"
  local tmp
  tmp="$(mktemp)"
  if [[ -f "${MANIFEST}" ]] && grep -q "^${key}=" "${MANIFEST}"; then
    sed "s|^${key}=.*|${key}=${value}|" "${MANIFEST}" > "${tmp}"
  else
    { cat "${MANIFEST}" 2>/dev/null; printf '%s=%s\n' "${key}" "${value}"; } > "${tmp}"
  fi
  mv "${tmp}" "${MANIFEST}"
}

cmd_fetch() {
  require_docker
  mkdir -p "${MODELS_DIR}"

  local pin
  pin="$(docling_version_pin)"
  [[ -n "${pin}" ]] \
    || die "Could not read the docling version pin from ${CONTEXT_DIR}/requirements-docling.txt."

  # Manifest gate: skip the whole container when the recorded version +
  # inventory already match the pin. This is the "version unchanged / local
  # already has it -> do not re-download" check.
  if cache_current "${pin}"; then
    printf 'Docling model cache is current (docling %s); skipping fetch.\n' "${pin}"
    return 0
  fi

  printf 'Fetching Docling models (docling %s) from %s ...\n' "${pin}" "${HF_ENDPOINT}"

  # The download runs in a throwaway container with the docling stack installed,
  # so the HuggingFace client resolves the model repo list exactly the way the
  # Dockerfile build does. Two layers of incrementality:
  #   1. huggingface_hub skips files already present in /out, so a version
  #      bump pulls only the new/changed files;
  #   2. a persistent pip cache makes the CPU torch + docling reinstall
  #      incremental across fetches.
  #
  # The cache is cleared first: cache_current returned false, so either the
  # version or the inventory changed, and a smaller old tree must not be
  # mistaken for part of the new one.
  rm -rf "${MODELS_DIR}"
  mkdir -p "${MODELS_DIR}"

  "${DOCKER_BIN}" run --rm \
    -v "${ROOT_DIR}/${MODELS_DIR}:/out" \
    -v "${ROOT_DIR}/${CACHE_DIR}/.pip-cache:/root/.cache/pip" \
    -v "${ROOT_DIR}/${CONTEXT_DIR}:/ctx:ro" \
    -e DOCLING_ARTIFACTS_PATH=/out \
    -e HF_ENDPOINT="${HF_ENDPOINT}" \
    -e HF_HUB_DISABLE_XET=1 \
    -e HF_HUB_ETAG_TIMEOUT="${HF_TIMEOUT}" \
    -e HF_HUB_DOWNLOAD_TIMEOUT="${HF_TIMEOUT}" \
    "python:3.13-slim-bookworm" bash -c "
      set -euo pipefail
      # CPU torch from the PyTorch CPU index, matching the Dockerfile. It is
      # installed first so the docling stack sees it satisfied and never pulls
      # the CUDA build from PyPI.
      pip install --progress-bar off --index-url https://download.pytorch.org/whl/cpu \
        'torch>=2.2.2,<3.0.0' >/dev/null 2>&1
      pip install --progress-bar off -r /ctx/requirements-docling.txt >/dev/null 2>&1
      if [ -n '${HF_ENDPOINT}' ]; then export HF_ENDPOINT='${HF_ENDPOINT}'; fi
      export HF_HUB_DISABLE_XET=1 HF_HUB_ETAG_TIMEOUT='${HF_TIMEOUT}' \
        HF_HUB_DOWNLOAD_TIMEOUT='${HF_TIMEOUT}'
      DOCLING_ARTIFACTS_PATH=/out python /ctx/scripts/download_docling_models.py
      python -c \"import importlib.metadata as m; print(m.version('docling'))\" > /out/.docling_version
    " || die "Docling model fetch for docling ${pin} failed."

  local actual
  actual="$(cat "${MODELS_DIR}/.docling_version" 2>/dev/null || printf '')"
  rm -f "${MODELS_DIR}/.docling_version"
  [[ -n "${actual}" ]] || actual="${pin}"
  [[ "${actual}" == "${pin}" ]] \
    || printf '  note: installed docling %s, pinned %s\n' "${actual}" "${pin}"

  local n size
  n="$(find "${MODELS_DIR}" -type f | wc -l | tr -d ' ')"
  [[ "${n}" -gt 0 ]] || die "No model files downloaded for docling ${pin}."
  size="$(du -sk "${MODELS_DIR}" | cut -f1)"
  write_manifest "${actual}" "${HF_ENDPOINT} (docling ${actual})"
  printf '  %s model files, %s\n' "${n}" "$(human_size "$((size * 1024))")"

  cmd_pack
}

cmd_save() {
  local image="${1:-${IMAGE:-document-parser:latest}}"
  require_docker

  "${DOCKER_BIN}" image inspect "${image}" >/dev/null 2>&1 \
    || die "Image ${image} not found locally. Build it first (mogo build / docker buildx build)."

  local version
  version="$(docling_version_in "${image}")"
  [[ -n "${version}" ]] \
    || die "Could not read the docling version from ${image}. Is the docling stack installed?"

  if cache_current "${version}"; then
    printf 'Docling model cache is current (docling %s); skipping extraction from %s.\n' \
      "${version}" "${image}"
  else
    printf 'Extracting /opt/docling/models from %s (docling %s) ...\n' "${image}" "${version}"

    local tmp_dir
    tmp_dir="$(mktemp -d)"
    trap 'rm -rf "${tmp_dir:-}"' EXIT

    # Copy the models tree out of the image. --entrypoint sh keeps this working
    # regardless of the image's CMD.
    "${DOCKER_BIN}" run --rm --entrypoint sh "${image}" \
      -c "tar -C /opt/docling -czf - models" > "${tmp_dir}/docling-models.tgz" 2>/dev/null

    local extracted_size
    extracted_size="$(wc -c < "${tmp_dir}/docling-models.tgz" | tr -d ' ')"
    [[ "${extracted_size}" -gt 1024 ]] \
      || die "Extracted model bundle is suspiciously small (${extracted_size} bytes). Is ${image} built with models?"

    tar -xzf "${tmp_dir}/docling-models.tgz" -C "${tmp_dir}"
    [[ -d "${tmp_dir}/models" ]] || die "models/ tree not found after extraction."

    # Cache root = contents of /opt/docling/models, so pack/extract round-trips
    # straight into DOCLING_ARTIFACTS_PATH. Clear the old tree first: the
    # version changed (cache_current was false), so a stale smaller tree must
    # not be mistaken for part of the new one.
    rm -rf "${MODELS_DIR}"
    mkdir -p "${MODELS_DIR}"
    cp -R "${tmp_dir}/models/." "${MODELS_DIR}/"

    rm -rf "${tmp_dir}"
    trap - EXIT
    write_manifest "${version}" "${image}"
  fi

  cmd_pack
}

cmd_pack() {
  [[ -d "${MODELS_DIR}" ]] \
    || die "No cached models at ${MODELS_DIR}. Run fetch or save first."

  local count
  count="$(find "${MODELS_DIR}" -type f | wc -l | tr -d ' ')"
  [[ "${count}" -gt 0 ]] || die "${MODELS_DIR} is empty."

  local cur_inv
  cur_inv="$(inventory "${MODELS_DIR}")"

  # Skip re-packing when the bundle already matches the cache exactly. The
  # manifest records what was last packed; identical inventory = identical bundle.
  if [[ -f "${BUNDLE_PATH}" ]]; then
    local packed
    packed="$(sed -n 's/^packed_inventory=//p' "${MANIFEST}" 2>/dev/null | head -1 || true)"
    if [[ -n "${packed}" && "${packed}" == "${cur_inv}" ]]; then
      local bsize
      bsize="$(wc -c < "${BUNDLE_PATH}" | tr -d ' ')"
      printf 'Bundle already matches the cache (%s files, %s); skipping re-pack.\n' \
        "${count}" "$(human_size "${bsize}")"
      return 0
    fi
  fi

  printf 'Packing %s -> %s ...\n' "${MODELS_DIR}" "${BUNDLE_PATH}"
  local staging
  staging="$(mktemp -d)"
  trap 'rm -rf "${staging:-}"' EXIT
  # Bundle root = contents of /opt/docling/models so the Dockerfile can extract
  # directly into DOCLING_ARTIFACTS_PATH.
  cp -R "${MODELS_DIR}/." "${staging}/"
  tar -czf "${BUNDLE_PATH}" -C "${staging}" .
  rm -rf "${staging}"

  set_manifest_key "packed_inventory" "${cur_inv}"

  local out_size entries
  out_size="$(wc -c < "${BUNDLE_PATH}" | tr -d ' ')"
  entries="$(tar -tzf "${BUNDLE_PATH}" | grep -c -v '/$' || true)"
  printf '\nBundle written: %s (%s, %s entries)\n' \
    "${BUNDLE_PATH}" "$(human_size "${out_size}")" "${entries}"
  printf 'Rebuild the image to use it:\n'
  printf '  docker buildx build ... -f %s -t document-parser:%s %s\n' \
    "${CONTEXT_DIR}/Dockerfile" "$(git rev-parse --short HEAD 2>/dev/null || echo latest)" "${CONTEXT_DIR}"
  printf 'The COPY layer re-executes only when this tar.gz changes; same bundle = cached.\n'
}

cmd_list() {
  printf 'Docling model cache:\n\n'

  if [[ -d "${MODELS_DIR}" ]]; then
    local size
    size="$(du -sk "${MODELS_DIR}" | cut -f1)"
    printf '  [cache]     %s  (%s)\n' "${MODELS_DIR}" "$(human_size "$((size * 1024))")"
    local n
    n="$(find "${MODELS_DIR}" -type f | wc -l | tr -d ' ')"
    printf '                %s model files\n' "${n}"
  else
    printf '  [missing]   %s  - run fetch or save first\n' "${MODELS_DIR}"
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
    printf '  [missing]   %s  - run pack (or restore the placeholder)\n' "${BUNDLE_PATH}"
  fi
}

cmd_verify() {
  local image="${1:-document-parser:latest}"
  require_docker
  "${DOCKER_BIN}" image inspect "${image}" >/dev/null 2>&1 \
    || die "Image ${image} not found locally."

  printf 'Checking /opt/docling/models in %s ...\n' "${image}"
  "${DOCKER_BIN}" run --rm --entrypoint sh "${image}" -c '
    set -e
    [ -d /opt/docling/models ] || { echo "MISSING /opt/docling/models"; exit 3; }
    n=$(find /opt/docling/models -type f | wc -l | tr -d " ")
    sz=$(du -sh /opt/docling/models | cut -f1)
    echo "  files: ${n}  size: ${sz}"
    # Safetensors magic: first 4 bytes are the little-endian JSON length, not null.
    bad=0
    for f in $(find /opt/docling/models -name "*.safetensors"); do
      len=$(head -c 4 "$f" | od -An -tu4 -N4 | tr -d " ")
      [ "${len:-0}" -gt 0 ] || { echo "  BAD magic: $f"; bad=1; }
    done
    [ "${bad}" -eq 0 ] && echo "  safetensors headers OK"
  '
}

command="${1:-list}"
if [[ $# -gt 0 ]]; then
  shift
fi

case "${command}" in
  fetch)
    cmd_fetch "$@"
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