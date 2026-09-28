#!/usr/bin/env bash
set -Eeuo pipefail

# Manage the Docling model bundle used by services/document-parser's Dockerfile.
# The bundle lets the image build skip the slow HuggingFace (hf-mirror) download
# of ~525MB of model files by extracting a pre-saved tar.gz into the image.
#
# Layout:
#   services/document-parser/docling-models-bundle.tar.gz
#       - tracked in git as a <1KB empty placeholder so COPY never fails
#       - overwritten in place by `save` with the real 485MB bundle
#   .gitignore keeps the real bundle out of git (only the placeholder ships).
#
# The build context is services/document-parser, so `save` runs against a
# locally-built image (or copies out of a running one) and writes the bundle
# straight into that context.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

CONTEXT_DIR="services/document-parser"
BUNDLE_NAME="docling-models-bundle.tar.gz"
BUNDLE_PATH="${CONTEXT_DIR}/${BUNDLE_NAME}"

DOCKER_BIN="${DOCKER_BIN:-docker}"

usage() {
  cat <<'USAGE'
Usage:
  scripts/docling_models_bundle.sh save [image]   Build/copy models from an image,
                                                   write the bundle into the build context
  scripts/docling_models_bundle.sh list            Show bundle status in the context
  scripts/docling_models_bundle.sh verify [image]  Check an image's /opt/docling/models

Environment:
  DOCKER_BIN        Docker binary to use (default: docker)

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

cmd_list() {
  if [[ -f "${BUNDLE_PATH}" ]]; then
    local size
    size="$(wc -c < "${BUNDLE_PATH}" | tr -d ' ')"
    if [[ "${size}" -gt 1024 ]]; then
      printf '  [bundle]  %s  (%s)  - real bundle, offline build will work\n' \
        "${BUNDLE_PATH}" "$(human_size "${size}")"
      local files
      files="$(tar -tzf "${BUNDLE_PATH}" 2>/dev/null | grep -c -v '/$' || echo '?')"
      printf '            %s files inside\n' "${files}"
    else
      printf '  [placeholder] %s  (%s)  - online build path will be used\n' \
        "${BUNDLE_PATH}" "$(human_size "${size}")"
    fi
  else
    printf '  [missing] %s  - run save first (or restore the placeholder)\n' "${BUNDLE_PATH}"
  fi
}

cmd_save() {
  local image="${1:-document-parser:latest}"
  require_docker

  # Ensure the image exists.
  "${DOCKER_BIN}" image inspect "${image}" >/dev/null 2>&1 \
    || die "Image ${image} not found locally. Build it first (mogo build / docker buildx build)."

  local tmp_dir
  tmp_dir="$(mktemp -d)"
  trap 'rm -rf "${tmp_dir:-}"' EXIT

  printf 'Extracting /opt/docling/models from %s ...\n' "${image}"
  # Copy the models tree out of the image into a temp dir.
  "${DOCKER_BIN}" run --rm --entrypoint sh "${image}" \
    -c "tar -C /opt/docling -czf - models" > "${tmp_dir}/docling-models.tgz" 2>/dev/null

  local extracted_size
  extracted_size="$(wc -c < "${tmp_dir}/docling-models.tgz" | tr -d ' ')"
  [[ "${extracted_size}" -gt 1024 ]] \
    || die "Extracted model bundle is suspiciously small (${extracted_size} bytes). Is ${image} built with models?"

  # Repack so the archive root matches DOCLING_ARTIFACTS_PATH layout: the
  # Dockerfile tar's into /opt/docling/models, so the bundle root must be the
  # same tree (docling-project--*, RapidOcr/...) and contain the model files.
  tar -xzf "${tmp_dir}/docling-models.tgz" -C "${tmp_dir}"
  [[ -d "${tmp_dir}/models" ]] || die "models/ tree not found after extraction."

  local staging
  staging="${tmp_dir}/bundle-root"
  mkdir -p "${staging}"
  # Bundle root = contents of /opt/docling/models (so extract -> DOCLING_ARTIFACTS_PATH).
  cp -R "${tmp_dir}/models/." "${staging}/"

  printf 'Packing %s -> %s ...\n' "${staging}" "${BUNDLE_PATH}"
  tar -czf "${BUNDLE_PATH}" -C "${staging}" .

  local out_size
  out_size="$(wc -c < "${BUNDLE_PATH}" | tr -d ' ')"
  printf '\nBundle written: %s (%s, %s entries)\n' \
    "${BUNDLE_PATH}" "$(human_size "${out_size}")" \
    "$(tar -tzf "${BUNDLE_PATH}" | grep -c -v '/$')"
  printf 'Rebuild the image to use it:\n'
  printf '  docker buildx build ... -f %s -t document-parser:%s %s\n' \
    "${CONTEXT_DIR}/Dockerfile" "$(git rev-parse --short HEAD 2>/dev/null || echo latest)" "${CONTEXT_DIR}"
  printf 'The COPY layer re-executes only when this tar.gz changes; same bundle = cached.\n'
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
  save)
    cmd_save "${1:-}"
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
