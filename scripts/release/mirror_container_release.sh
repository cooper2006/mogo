#!/usr/bin/env bash
set -Eeuo pipefail

DOCKER_BIN="${DOCKER_BIN:-docker}"
SOURCE_REPOSITORY="${SOURCE_REPOSITORY:-ghcr.io/himovo/movo}"
CN_REGISTRY_NAMESPACE="${CN_REGISTRY_NAMESPACE:-himovo}"
PUBLISH_LATEST="${PUBLISH_LATEST:-false}"
INCLUDE_DEPENDENCIES="${INCLUDE_DEPENDENCIES:-true}"
COPY_RETRY_ATTEMPTS="${COPY_RETRY_ATTEMPTS:-5}"
COPY_RETRY_DELAY_SECONDS="${COPY_RETRY_DELAY_SECONDS:-15}"

required_variables=(
  CN_REGISTRY_HOST
  SOURCE_VERSION
)

for variable_name in "${required_variables[@]}"; do
  if [[ -z "${!variable_name:-}" ]]; then
    echo "Missing required environment variable: ${variable_name}" >&2
    exit 2
  fi
done

destination_repository="${CN_REGISTRY_HOST%/}/${CN_REGISTRY_NAMESPACE}/movo"

self_managed_images=(
  dsh-runtime-host
  chat-api
  admin-api
  document-parser
  user-web
  admin-web
  gateway
)

dependency_images=(
  "docker.io/library/alpine:3.21|${destination_repository}-alpine:3.21"
  "docker.io/library/mongo:6.0.20|${destination_repository}-mongo:6.0.20"
  "docker.io/library/redis:7.4.2-alpine|${destination_repository}-redis:7.4.2-alpine"
  "docker.io/semitechnologies/weaviate:1.25.7|${destination_repository}-weaviate:1.25.7"
)

declare -a source_refs=()
declare -a destination_refs=()
declare -a platform_source_refs=()

for suffix in "${self_managed_images[@]}"; do
  source_refs+=("${SOURCE_REPOSITORY}-${suffix}:${SOURCE_VERSION}")
  destination_refs+=("${destination_repository}-${suffix}:${SOURCE_VERSION}")
done

if [[ "${INCLUDE_DEPENDENCIES}" == "true" ]]; then
  for mapping in "${dependency_images[@]}"; do
    source_refs+=("${mapping%%|*}")
    destination_refs+=("${mapping#*|}")
  done
fi

select_linux_platform_manifests() {
  local source_ref="$1"

  "${DOCKER_BIN}" buildx imagetools inspect --raw "${source_ref}" |
    python3 -c '
import json
import sys

source_ref = sys.argv[1]
index = json.load(sys.stdin)
manifests = index.get("manifests", [])

for architecture in ("amd64", "arm64"):
    matches = [
        manifest["digest"]
        for manifest in manifests
        if manifest.get("platform", {}).get("os") == "linux"
        and manifest.get("platform", {}).get("architecture") == architecture
    ]
    if not matches:
        raise SystemExit(
            f"{source_ref} does not provide the required linux/{architecture} image"
        )
    print(f"{source_ref}@{matches[0]}")
' "${source_ref}"
}

run_with_retry() {
  local operation="$1"
  shift
  local attempt=1
  local exit_code=0
  local delay_seconds="${COPY_RETRY_DELAY_SECONDS}"

  while (( attempt <= COPY_RETRY_ATTEMPTS )); do
    echo "    ${operation} (attempt ${attempt}/${COPY_RETRY_ATTEMPTS})"
    if "$@"; then
      return 0
    else
      exit_code=$?
    fi

    if (( attempt == COPY_RETRY_ATTEMPTS )); then
      echo "${operation} failed after ${COPY_RETRY_ATTEMPTS} attempts" >&2
      return "${exit_code}"
    fi

    echo "    transfer interrupted; retrying in ${delay_seconds}s..." >&2
    sleep "${delay_seconds}"
    delay_seconds=$((delay_seconds * 2))
    attempt=$((attempt + 1))
  done
}

echo "Preflighting ${#source_refs[@]} source images before publishing to ${CN_REGISTRY_HOST}..."
for source_ref in "${source_refs[@]}"; do
  echo "  checking ${source_ref}"
  # ACR Personal Edition rejects the OCI attestation/SBOM manifests attached to
  # the GHCR image index. Resolve only the two runnable Linux manifests here,
  # then build a clean destination index from those immutable digests.
  platform_source_refs+=("$(select_linux_platform_manifests "${source_ref}")")
done

echo "All sources are available. Copying immutable image versions..."
for index in "${!source_refs[@]}"; do
  source_ref="${source_refs[$index]}"
  destination_ref="${destination_refs[$index]}"
  selected_refs=()
  while IFS= read -r selected_ref; do
    [[ -n "${selected_ref}" ]] && selected_refs+=("${selected_ref}")
  done <<< "${platform_source_refs[$index]}"
  echo "  copying ${source_ref} -> ${destination_ref}"
  run_with_retry \
    "copying ${source_ref}" \
    "${DOCKER_BIN}" buildx imagetools create \
      --tag "${destination_ref}" \
      "${selected_refs[@]}"
done

echo "Verifying every copied image..."
for destination_ref in "${destination_refs[@]}"; do
  echo "  checking ${destination_ref}"
  "${DOCKER_BIN}" buildx imagetools inspect "${destination_ref}" >/dev/null
done

if [[ "${PUBLISH_LATEST}" == "true" ]]; then
  echo "All versioned images are available. Updating MOVO latest tags..."
  for suffix in "${self_managed_images[@]}"; do
    version_ref="${destination_repository}-${suffix}:${SOURCE_VERSION}"
    latest_ref="${destination_repository}-${suffix}:latest"
    echo "  publishing ${latest_ref}"
    run_with_retry \
      "publishing ${latest_ref}" \
      "${DOCKER_BIN}" buildx imagetools create \
        --tag "${latest_ref}" \
        "${version_ref}"
  done

  echo "Verifying every latest tag..."
  for suffix in "${self_managed_images[@]}"; do
    "${DOCKER_BIN}" buildx imagetools inspect \
      "${destination_repository}-${suffix}:latest" >/dev/null
  done
fi

echo "Published MOVO ${SOURCE_VERSION} to ${destination_repository}-*."
