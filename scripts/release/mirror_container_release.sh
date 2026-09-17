#!/usr/bin/env bash
set -Eeuo pipefail

DOCKER_BIN="${DOCKER_BIN:-docker}"
SOURCE_REPOSITORY="${SOURCE_REPOSITORY:-ghcr.io/himovo/movo}"
CN_REGISTRY_NAMESPACE="${CN_REGISTRY_NAMESPACE:-himovo}"
PUBLISH_LATEST="${PUBLISH_LATEST:-false}"
INCLUDE_DEPENDENCIES="${INCLUDE_DEPENDENCIES:-true}"

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

echo "Preflighting ${#source_refs[@]} source images before publishing to ${CN_REGISTRY_HOST}..."
for source_ref in "${source_refs[@]}"; do
  echo "  checking ${source_ref}"
  "${DOCKER_BIN}" buildx imagetools inspect "${source_ref}" >/dev/null
done

echo "All sources are available. Copying immutable image versions..."
for index in "${!source_refs[@]}"; do
  source_ref="${source_refs[$index]}"
  destination_ref="${destination_refs[$index]}"
  echo "  copying ${source_ref} -> ${destination_ref}"
  "${DOCKER_BIN}" buildx imagetools create \
    --tag "${destination_ref}" \
    "${source_ref}"
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
