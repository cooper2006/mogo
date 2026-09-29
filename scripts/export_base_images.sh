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
  --platform <os>/<arch>     (save) Export for this platform instead of the host
                             platform, for example linux/amd64. The target
                             platform is fetched first, so an Apple Silicon
                             machine can produce archives for an x86_64 server.
  --mirror <host>            (save) Resolve Docker Hub images through this
                             registry mirror, for example
                             docker.m.daocloud.io, when docker.io itself is
                             unreachable. The mirror must be a faithful
                             pull-through cache (identical digests) so the
                             exported archives keep the tags the Dockerfiles
                             reference.
  --manifest-only            (save) Write manifest.txt without exporting archives
  --allow-platform-mismatch  (load) Import archives built for another platform
                             instead of failing.

Environment:
  DOCKER_BIN        Docker binary to use (default: docker)

The archive set is derived from the FROM lines of the Dockerfiles that take
part in a source build, so it always matches the current requirements.

Export and import must agree on the platform. To build on an x86_64 host from
archives produced on Apple Silicon, export with an explicit target:

  scripts/export_base_images.sh save --platform linux/amd64 ./base-images-amd64

When docker.io is unreachable, point the export at the mirror the build uses:

  scripts/export_base_images.sh save --platform linux/amd64 \
    --mirror docker.m.daocloud.io ./base-images-amd64
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

# Read the platform out of a saved archive instead of trusting the daemon. The
# archive is the artifact that ships, so it is the only ground truth: a local
# image store that keeps several platforms under one tag would otherwise let a
# wrong-architecture archive pass unnoticed.
#
# Prints "<os>/<arch>", or nothing when the archive cannot be read.
archive_platform() {
  local archive="$1" config arch os
  config="$(tar -xOf "${archive}" manifest.json 2>/dev/null \
    | tr ',' '\n' | grep -m1 '"Config"' | cut -d'"' -f4)"
  [[ -n "${config}" ]] || return 0
  arch="$(tar -xOf "${archive}" "${config}" 2>/dev/null \
    | tr ',' '\n' | grep -m1 '"architecture"' | cut -d'"' -f4)"
  os="$(tar -xOf "${archive}" "${config}" 2>/dev/null \
    | tr ',' '\n' | grep -m1 '"os"' | cut -d'"' -f4)"
  [[ -n "${arch}" && -n "${os}" ]] || return 0
  printf '%s/%s' "${os}" "${arch}"
}

# Reject anything that is not "<os>/<arch>" (an optional "/<variant>" suffix is
# allowed), so a typo cannot silently export the host platform while the
# operator believes they targeted another one.
assert_platform() {
  [[ "$1" =~ ^[a-z0-9]+/[a-z0-9]+(/[a-z0-9]+)?$ ]] \
    || die "--platform expects <os>/<arch>, for example linux/amd64 (got: $1)."
}

# ``docker save --platform`` is what makes a single-architecture archive out of
# an image whose local store also holds other architectures. Without it the
# save aborts with "unable to create manifests file: NotFound", because the
# on-disk index references manifests that were never downloaded.
supports_save_platform() {
  "${DOCKER_BIN}" save --help 2>&1 | grep -q -- '--platform'
}

# Rewrite a Docker Hub reference onto a registry mirror. The mapping itself
# lives next to the build's own pull logic so the export and the build can
# never disagree about how a Hub reference is resolved.
#
# The mirror is expected to be a faithful pull-through cache. Images are
# content addressed, so a matching digest fills the canonical reference in
# place and the archive keeps the tag the Dockerfiles ask for; a divergent
# mirror is caught later by the archive platform check.
mirror_ref() {
  movo_mirror_ref "$1" "$2"
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

# "linux/arm64/v8" -> "linux/arm64"; the variant only refines the platform.
platform_base() {
  local platform="$1" os arch
  IFS='/' read -r os arch _ <<< "${platform}"
  printf '%s/%s' "${os}" "${arch}"
}

# Confirm the archive really carries the requested platform. Both the fetch and
# the save ask for it, but a mirror that rewrites manifests, or an image that
# only exists for another architecture, would otherwise ship silently and only
# fail much later on the target host.
assert_archive_platform() {
  local archive="$1" expected="$2" image="$3" actual
  actual="$(archive_platform "${archive}")"
  [[ -n "${actual}" ]] || die "Could not read the platform out of ${archive}."
  [[ "${actual}" == "$(platform_base "${expected}")" ]] \
    || die "Exported ${image} for ${actual}, but ${expected} was requested."
}

cmd_save() {
  local output_dir="${SAVE_OUTPUT_DIR}"
  local manifest_only="${SAVE_MANIFEST_ONLY}"
  local mirror="${SAVE_MIRROR}"
  local platform="${SAVE_PLATFORM:-$(current_platform)}"

  [[ -n "${output_dir}" ]] || die "save requires an output directory."
  mkdir -p "${output_dir}"

  assert_platform "${platform}"
  supports_save_platform \
    || die "This Docker CLI cannot save a single platform (docker save --platform is missing). Upgrade Docker, or export on a host whose architecture already matches the target."

  # Resolve the list first so a missing image fails before anything is written.
  local -a images=()
  local image
  while IFS= read -r image; do
    [[ -z "${image}" ]] && continue
    images+=("${image}")
  done < <(required_images)

  [[ "${#images[@]}" -gt 0 ]] || die "No base images were discovered in the Dockerfiles."

  printf 'Exporting %s base image(s) for %s\n' "${#images[@]}" "${platform}"
  if [[ -n "${mirror}" ]]; then
    printf 'Docker Hub images resolve through %s\n' "${mirror}"
  fi
  printf '\n'

  local manifest="${output_dir}/manifest.txt"
  {
    printf '# mogo base images\n'
    printf '# platform: %s\n' "$(platform_base "${platform}")"
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
  local archive tmp source
  for image in "${images[@]}"; do
    archive="${output_dir}/$(archive_name_for "${image}")"
    if [[ -f "${archive}" ]]; then
      printf '  [skip]    %s (already exported)\n' "${image}"
      continue
    fi

    # The archive is written to "<archive>.part" and only renamed once the
    # platform has been verified, so an interrupted run cannot leave something
    # behind that the next run mistakes for a finished archive.
    tmp="${archive}.part"
    printf '  [save]    %s -> %s\n' "${image}" "$(basename "${archive}")"

    # Saving straight from the local store keeps a repeat export offline. It
    # only fails when the store cannot produce the requested platform, which is
    # exactly the case that needs a fetch.
    if ! "${DOCKER_BIN}" save --platform "${platform}" --output "${tmp}" "${image}" 2>/dev/null; then
      source="$(mirror_ref "${image}" "${mirror}")"
      printf '  [fetch]   %s has no %s locally, pulling %s\n' \
        "${image}" "${platform}" "${source}"
      "${DOCKER_BIN}" pull --platform "${platform}" "${source}" >/dev/null \
        || die "Could not fetch ${source} for ${platform}."
      "${DOCKER_BIN}" save --platform "${platform}" --output "${tmp}" "${image}" \
        || die "Fetched ${source} but ${image} still does not provide ${platform}. Point --mirror at a faithful pull-through cache of docker.io."
    fi

    assert_archive_platform "${tmp}" "${platform}" "${image}"
    mv "${tmp}" "${archive}"
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
  local input_dir="${LOAD_INPUT_DIR}"
  local allow_mismatch="${LOAD_ALLOW_MISMATCH}"

  [[ -n "${input_dir}" ]] || die "load requires an input directory."
  [[ -d "${input_dir}" ]] || die "Directory not found: ${input_dir}"

  local host_platform
  host_platform="$(current_platform)"

  local manifest="${input_dir}/manifest.txt"
  local -a archives=()
  local archive

  if [[ -f "${manifest}" ]]; then
    # Preferred path: load exactly the images the manifest records.
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

  # The platform is read out of each archive rather than out of the manifest,
  # because the archive is what actually gets imported. Importing Apple Silicon
  # archives on an x86_64 host would succeed and only fail later at build time
  # with a far less obvious error, so the mismatch is reported up front.
  local actual
  local -a mismatched=()
  for archive in "${archives[@]}"; do
    actual="$(archive_platform "${archive}")"
    [[ -n "${actual}" ]] || continue
    if [[ "${actual}" != "${host_platform}" ]]; then
      mismatched+=("$(basename "${archive}") (${actual})")
    fi
  done

  if [[ "${#mismatched[@]}" -gt 0 ]]; then
    printf 'These archives were built for another platform (this host is %s):\n' \
      "${host_platform}" >&2
    printf '  %s\n' "${mismatched[@]}" >&2
    if [[ "${allow_mismatch}" != "true" ]]; then
      die "Refusing to import. Re-export with --platform ${host_platform}, or pass --allow-platform-mismatch to import them anyway (the target host can only run them under emulation)."
    fi
    printf 'Continuing because --allow-platform-mismatch was given.\n\n' >&2
  fi

  printf 'Importing %s image archive(s)...\n\n' "${#archives[@]}"
  for archive in "${archives[@]}"; do
    printf '  [load]    %s\n' "$(basename "${archive}")"
    "${DOCKER_BIN}" load --input "${archive}"
  done

  printf '\nImported %s archive(s).\n' "${#archives[@]}"
  printf 'Note: a single-platform archive replaces the tag locally, so those images\n'
  printf 'now resolve to %s only. Verify with: scripts/export_base_images.sh list\n' \
    "${host_platform}"
}

command="${1:-}"
if [[ $# -gt 0 ]]; then
  shift
fi

SAVE_OUTPUT_DIR=""
SAVE_MANIFEST_ONLY=false
SAVE_PLATFORM=""
SAVE_MIRROR=""
LOAD_INPUT_DIR=""
LOAD_ALLOW_MISMATCH=false

case "${command}" in
  save)
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --platform)
          [[ $# -ge 2 ]] || die "--platform requires a value."
          SAVE_PLATFORM="$2"
          shift 2
          ;;
        --mirror)
          [[ $# -ge 2 ]] || die "--mirror requires a value."
          SAVE_MIRROR="$2"
          shift 2
          ;;
        --manifest-only)
          SAVE_MANIFEST_ONLY=true
          shift
          ;;
        -*)
          die "Unknown option: $1"
          ;;
        *)
          SAVE_OUTPUT_DIR="$1"
          shift
          ;;
      esac
    done
    [[ "${SAVE_MIRROR}" != */* ]] || die "--mirror expects a registry host, for example docker.m.daocloud.io (got: ${SAVE_MIRROR})."
    require_docker
    cmd_save
    ;;
  load)
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --allow-platform-mismatch)
          LOAD_ALLOW_MISMATCH=true
          shift
          ;;
        -*)
          die "Unknown option: $1"
          ;;
        *)
          LOAD_INPUT_DIR="$1"
          shift
          ;;
      esac
    done
    require_docker
    cmd_load
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
