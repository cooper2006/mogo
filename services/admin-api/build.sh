#!/usr/bin/env bash
set -euo pipefail

# Resolve the script directory (admin/api).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

REGISTRY="${REGISTRY:-ghcr.io}"
REGISTRY_NAMESPACE="${REGISTRY_NAMESPACE:-}"
IMAGE_NAME="${IMAGE_NAME:-mogo-admin}"
IMAGE_TAG="${IMAGE_TAG:-dev-0.0.1}"
LOCAL_IMAGE="mogo-admin"
PUSH="${PUSH:-true}"
NO_CACHE="${NO_CACHE:-true}"

if [[ -z "${REGISTRY_NAMESPACE}" ]]; then
  echo "ERROR: set REGISTRY_NAMESPACE to the target registry owner or organization." >&2
  exit 2
fi
IMAGE_REF="${REGISTRY%/}/${REGISTRY_NAMESPACE#/}/${IMAGE_NAME}:${IMAGE_TAG}"

echo "Building Admin API Image..."
echo "  Image Tag:   ${IMAGE_REF}"
echo "  Context Dir: ${SCRIPT_DIR}"
echo "  No Cache:    ${NO_CACHE}"
echo "  Push:        ${PUSH}"

cd "${SCRIPT_DIR}"

build_args=()
if [[ "${NO_CACHE}" == "true" ]]; then
  build_args+=(--no-cache)
fi

# Build the image from admin/api.
docker build \
  "${build_args[@]}" \
  -f Dockerfile \
  -t "${LOCAL_IMAGE}:latest" \
  .

# Tag the image.
echo "Tagging image as ${IMAGE_REF}..."
docker tag "${LOCAL_IMAGE}:latest" "${IMAGE_REF}"

# Push to the remote image registry.
if [[ "${PUSH}" == "true" ]]; then
  echo "Pushing image to ${IMAGE_REF}..."
  docker push "${IMAGE_REF}"
fi

echo "Successfully built and pushed: ${IMAGE_REF}"
