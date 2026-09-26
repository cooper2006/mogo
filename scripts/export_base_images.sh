#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

DOCKER_BIN="${DOCKER_BIN:-docker}"

# Reuse the build's own base-image discovery so the exported set can never
# drift from what the Dockerfiles actually reference.
# shellcheck source=../deploy/cli/base-images.sh
source "${ROOT_DIR}/deploy/cli/base-images.sh"

usage() {
  cat <<'USAGE'
Usage:
  scripts/export_base_images.sh save [directory]   Export base images to a directory
  scripts/export_base_images.sh load [directory]   Import base images from a directory
  scripts/export_base_images.sh list               List required base images and status

Options:
  --manifest-only   (save) Write manifest.txt without exporting archives

Environment:
  DOCKER_BIN        Docker binary to use (default: docker)

The archive set is derived from the FROM lines of the Dockerfiles that take
part in a source build, so it always matches the current requirements. Images
are saved for the current architecture only; import them on a machine whose
docker reports the same architecture.
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

# A filesystem-safe file name for one image reference:
#   node:20-slim      -> node_20-slim.tar
#   ghcr.io/a/b:1.2   -> ghcr.io_a_b_1.2.tar
archive_name_for() {
  local image="$1"
  image="${image//\//_}"
  image="${image//:/_}"
  printf '%s.tar' "${image}"
}

# Print the unique base image list, one per line.
required_images() {
  movo_base_images | awk '!seen[$0]++'
}

current_platform() {
  "${DOCKER_BIN}" version --format '{{.Server.Os}}/{{.Server.Arch}}' 2>/dev/null || printf 'unknown'
}

image_platform() {
  "${DOCKER_BIN}" image inspect "$1" --format '{{.Os}}/{{.Architecture}}' 2>/dev/null || printf ''
}

cmd_list() {
  local image present platform
  printf 'Required base images (from the build Dockerfiles):\n\n'
  while IFS= read -r image; do
    [[ -z "${image}" ]] && continue
    platform="$(image_platform "${image}")"
    if [[ -n "${platform}" ]]; then
      printf '  [local]   %-38s %s\n' "${image}" "${platform}"
    else
      printf '  [missing] %-38s\n' "${image}"
    fi
  done < <(required_images)
}

cmd_save() {
  local output_dir="${1:-}"
  local manifest_only="${2:-false}"

  [[ -n "${output_dir}" ]] || die "save requires an output directory."
  mkdir -p "${output_dir}"

  local platform
  platform="$(current_platform)"

  # Resolve the list first so a missing image fails before anything is written.
  local -a images=()
  local image
  while IFS= read -r image; do
    [[ -z "${image}" ]] && continue
    images+=("${image}")
  done < <(required_images)

  [[ "${#images[@]}" -gt 0 ]] || die "No base images were discovered in the Dockerfiles."

  printf 'Exporting %s base image(s) for %s\n\n' "${#images[@]}" "${platform}"

  if [[ "${manifest_only}" != "true" ]]; then
    # Fail fast when something is missing locally rather than writing a
    # partial set that would restore into a broken environment.
    for image in "${images[@]}"; do
      [[ -n "$(image_platform "${image}")" ]] \
        || die "Base image ${image} is not present locally. Run ./movo build first to fetch it."
    done
  fi

  local manifest="${output_dir}/manifest.txt"
  {
    printf '# movo base images\n'
    printf '# platform: %s\n' "${platform}"
    printf '# generated: %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    for image in "${images[@]}"; do
      printf '%s\n' "${image}"
    done
  } > "${manifest}"
  printf 'Wrote %s\n' "${manifest}"

  if [[ "${manifest_only}" == "true" ]]; then
    printf '\nManifest-only run: no archives were written.\n'
    return 0
  fi

  printf '\n'
  local archive
  for image in "${images[@]}"; do
    archive="${output_dir}/$(archive_name_for "${image}")"
    if [[ -f "${archive}" ]]; then
      printf '  [skip]    %s (already exported)\n' "${image}"
      continue
    fi
    printf '  [save]    %s -> %s\n' "${image}" "$(basename "${archive}")"
    "${DOCKER_BIN}" save --output "${archive}" "${image}"
  done

  printf '\n'
  # Report only the archives this run's image set owns, so stale files from an
  # older image list are not counted as part of the export.
  local archive saved=0 total=0 size
  for image in "${images[@]}"; do
    archive="${output_dir}/$(archive_name_for "${image}")"
    [[ -f "${archive}" ]] || continue
    size="$(wc -c < "${archive}")"
    total=$((total + size))
    saved=$((saved + 1))
  done
  printf 'Exported %s/%s image archive(s), %s total.\n' \
    "${saved}" "${#images[@]}" "$(human_size "${total}")"
  printf 'Import on the target machine with: scripts/export_base_images.sh load %s\n' "${output_dir}"
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

cmd_load() {
  local input_dir="${1:-}"

  [[ -n "${input_dir}" ]] || die "load requires an input directory."
  [[ -d "${input_dir}" ]] || die "Directory not found: ${input_dir}"

  local manifest="${input_dir}/manifest.txt"
  local -a archives=()
  local archive

  if [[ -f "${manifest}" ]]; then
    # Preferred path: load exactly the images the manifest records.
    local expected_platform=""
    expected_platform="$(sed -n 's/^# platform: //p' "${manifest}" | head -1)"
    local actual_platform
    actual_platform="$(current_platform)"
    if [[ -n "${expected_platform}" && "${expected_platform}" != "${actual_platform}" ]]; then
      printf 'Warning: archives were exported for %s but this machine is %s.\n' \
        "${expected_platform}" "${actual_platform}" >&2
    fi

    local image archive_path
    while IFS= read -r image; do
      [[ -z "${image}" || "${image}" == \#* ]] && continue
      archive_path="${input_dir}/$(archive_name_for "${image}")"
      if [[ ! -f "${archive_path}" ]]; then
        # A digest-qualified reference has no matching file name; fall back to
        # the plain archives present rather than failing the whole restore.
        printf 'Warning: no archive for %s (expected %s)\n' \
          "${image}" "$(basename "${archive_path}")" >&2
        continue
      fi
      archives+=("${archive_path}")
    done < "${manifest}"
  else
    # No manifest: import every archive in the directory.
    for archive in "${input_dir}"/*.tar; do
      [[ -f "${archive}" ]] || continue
      archives+=("${archive}")
    done
  fi

  [[ "${#archives[@]}" -gt 0 ]] || die "No image archives found in ${input_dir}."

  printf 'Importing %s image archive(s)...\n\n' "${#archives[@]}"
  for archive in "${archives[@]}"; do
    printf '  [load]    %s\n' "$(basename "${archive}")"
    "${DOCKER_BIN}" load --input "${archive}"
  done

  printf '\nImported %s archive(s). Verify with: scripts/export_base_images.sh list\n' "${#archives[@]}"
}

command="${1:-}"
if [[ $# -gt 0 ]]; then
  shift
fi

case "${command}" in
  save)
    manifest_only=false
    output_dir=""
    for argument in "$@"; do
      case "${argument}" in
        --manifest-only) manifest_only=true ;;
        -*) die "Unknown option: ${argument}" ;;
        *) output_dir="${argument}" ;;
      esac
    done
    require_docker
    cmd_save "${output_dir}" "${manifest_only}"
    ;;
  load)
    require_docker
    cmd_load "${1:-}"
    ;;
  list)
    require_docker
    cmd_list
    ;;
  help|-h|--help|"")
    usage
    ;;
  *)
    printf 'Unknown command: %s\n\n' "${command}" >&2
    usage >&2
    exit 2
    ;;
esac
