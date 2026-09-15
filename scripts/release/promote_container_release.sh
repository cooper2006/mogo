#!/usr/bin/env bash
set -Eeuo pipefail

required_variables=(
  ALL_IMAGES_JSON
  CHANGED_IMAGES_JSON
  GITHUB_REF_NAME
  GITHUB_REPOSITORY
  GITHUB_SHA
)

for variable_name in "${required_variables[@]}"; do
  if [[ -z "${!variable_name:-}" ]]; then
    echo "Missing required environment variable: ${variable_name}" >&2
    exit 2
  fi
done

repository="$(printf '%s' "${GITHUB_REPOSITORY}" | tr '[:upper:]' '[:lower:]')"
candidate_tag="candidate-${GITHUB_SHA}"
short_sha="${GITHUB_SHA:0:7}"

declare -a image_suffixes=()
while IFS= read -r suffix; do
  image_suffixes+=("${suffix}")
done < <(
  python3 -c \
    'import json, sys; print("\n".join(image["suffix"] for image in json.load(sys.stdin)))' \
    <<<"${ALL_IMAGES_JSON}"
)
if (( ${#image_suffixes[@]} == 0 )); then
  echo "The release plan contains no images." >&2
  exit 2
fi

declare -a image_names=()
declare -a source_refs=()

echo "Preflighting every release source before updating any public tag..."
for suffix in "${image_suffixes[@]}"; do
  image_name="ghcr.io/${repository}-${suffix}"
  if python3 -c \
      'import json, sys; suffix=sys.argv[1]; sys.exit(0 if any(image["suffix"] == suffix for image in json.load(sys.stdin)) else 1)' \
      "${suffix}" <<<"${CHANGED_IMAGES_JSON}"; then
    source_ref="${image_name}:${candidate_tag}"
  else
    if [[ -z "${BASE_REF:-}" ]]; then
      echo "No previous release is available for unchanged image ${suffix}." >&2
      exit 2
    fi
    source_ref="${image_name}:${BASE_REF}"
  fi

  echo "  checking ${source_ref}"
  docker buildx imagetools inspect "${source_ref}" >/dev/null
  image_names+=("${image_name}")
  source_refs+=("${source_ref}")
done

echo "All sources are available. Publishing ${GITHUB_REF_NAME}..."
for index in "${!image_names[@]}"; do
  image_name="${image_names[$index]}"
  source_ref="${source_refs[$index]}"
  tags=(
    --tag "${image_name}:${GITHUB_REF_NAME}"
    --tag "${image_name}:sha-${short_sha}"
  )
  if [[ "${GITHUB_REF_NAME}" != *-* ]]; then
    tags+=(--tag "${image_name}:latest")
  fi

  echo "  promoting ${source_ref}"
  docker buildx imagetools create "${tags[@]}" "${source_ref}"
done

echo "Published all MOVO container tags for ${GITHUB_REF_NAME}."
