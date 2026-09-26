#!/usr/bin/env bash

# Base-image reuse for source builds.
#
# ``docker compose build`` sends every Dockerfile's base reference to the
# registry to resolve its manifest. Even when the image is already present
# locally, BuildKit may still re-resolve (and occasionally re-download) layers,
# which is the slow part of a rebuild that only changed application code.
#
# The helpers below close that gap: before a build we collect the base
# references from the Dockerfiles themselves, skip every one that is already in
# the local image store, and pull only what is genuinely missing. BuildKit is
# then invoked with --pull=false so it can never override that decision.

# Dockerfiles that participate in a source build. Kept in sync with the build
# targets in docker-compose.build.yml; the list only names the build contexts,
# because each Dockerfile's FROM lines are discovered from the file itself.
MOVO_BASE_IMAGE_DOCKERFILES=(
  "services/chat-api/Dockerfile"
  "services/chat-api/dsh/runtime-host/Dockerfile"
  "services/admin-api/Dockerfile"
  "services/document-parser/Dockerfile"
  "apps/user-web/Dockerfile.prod"
  "apps/admin-web/Dockerfile"
  "deploy/docker/gateway.Dockerfile"
)

# Print every base image reference used by the build, one per line.
#
# ``FROM`` may reference a build argument (the document parser does:
# ``ARG BASE_IMAGE=python:3.10-slim-bookworm``), so ARG defaults are resolved
# as well; an ARG without a default is skipped because there is nothing local
# to look up. Multi-stage builds also name earlier stages in FROM
# (``FROM dependencies``); those are internal references, not images, so they
# are filtered out by requiring a tag, a digest, or a slash.
movo_base_images() {
  local dockerfile line var value
  for dockerfile in "${MOVO_BASE_IMAGE_DOCKERFILES[@]}"; do
    [[ -f "${ROOT_DIR}/${dockerfile}" ]] || continue

    # Collect ARG defaults first so they can be substituted below.
    local -a arg_names=() arg_values=()
    while IFS= read -r line; do
      line="${line%%#*}"
      if [[ "${line}" =~ ^[[:space:]]*ARG[[:space:]]+([A-Za-z_][A-Za-z0-9_]*)=([^[:space:]]+) ]]; then
        arg_names+=("${BASH_REMATCH[1]}")
        arg_values+=("${BASH_REMATCH[2]}")
      fi
    done < "${ROOT_DIR}/${dockerfile}"

    while IFS= read -r line; do
      line="${line%%#*}"
      # Keep only FROM lines, then take the image reference.
      line="${line#"${line%%[![:space:]]*}"}"
      [[ "${line}" =~ ^FROM[[:space:]]+([^[:space:]]+) ]] || continue
      line="${BASH_REMATCH[1]}"

      # Substitute ${VAR} / $VAR from this file's ARG defaults.
      if [[ "${line}" == *'$'* ]]; then
        local index
        for index in "${!arg_names[@]}"; do
          var="${arg_names[${index}]}"
          value="${arg_values[${index}]}"
          line="${line//\$\{${var}\}/${value}}"
          line="${line//\$${var}/${value}}"
        done
        # Still unexpanded: the ARG has no usable default.
        [[ "${line}" == *'$'* ]] && continue
      fi

      if [[ "${line}" == *:* || "${line}" == */* ]]; then
        printf '%s\n' "${line}"
      fi
    done < "${ROOT_DIR}/${dockerfile}"
  done
}

# True when the reference already exists in the local image store. A bare name
# is looked up as "name:latest" to match Docker's own resolution.
movo_base_image_is_local() {
  local image="$1"
  local lookup="${image}"
  if [[ "${lookup}" != *:* && "${lookup}" != *@* ]]; then
    lookup="${lookup}:latest"
  fi
  "${DOCKER_BIN}" image inspect "${lookup}" >/dev/null 2>&1
}

# Ensure every base image referenced by the build exists locally, pulling only
# the ones that do not. Returns non-zero only when an image could not be made
# available, so a genuine failure still stops the build.
#
# MOVO_BASE_IMAGE_POLICY controls the behaviour:
#   reuse  (default) - use local images, pull only what is missing
#   pull             - always refresh base images from the registry
#   local            - never touch the network; fail when something is missing
movo_prepare_base_images() {
  local policy="${MOVO_BASE_IMAGE_POLICY:-reuse}"
  local image reused=0
  local -a missing=()

  while IFS= read -r image; do
    [[ -z "${image}" ]] && continue

    if [[ "${policy}" == "pull" ]]; then
      missing+=("${image}")
      continue
    fi

    if movo_base_image_is_local "${image}"; then
      reused=$((reused + 1))
      continue
    fi

    if [[ "${policy}" == "local" ]]; then
      movo_msg base_image_missing "${image}" >&2
      return 1
    fi

    missing+=("${image}")
  done < <(movo_base_images | awk '!seen[$0]++')

  if [[ "${reused}" -gt 0 ]]; then
    movo_msg base_images_reused "${reused}"
  fi

  [[ "${#missing[@]}" -eq 0 ]] && return 0

  for image in "${missing[@]}"; do
    movo_msg base_image_pulling "${image}"
    if ! "${DOCKER_BIN}" pull "${image}"; then
      movo_msg base_image_pull_failed "${image}" >&2
      return 1
    fi
  done
}
