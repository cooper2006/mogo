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

# Images are published as ghcr.io/<owner>/<service>; the repository name is
# deliberately not part of the image name (it used to be
# ghcr.io/<owner>/<repository>-<service>, e.g. ghcr.io/mogoai/mogo-chat-api).
# Keep this in step with .github/workflows/container-release.yml, which builds
# the candidate tags under the same scheme.
owner="$(printf '%s' "${GITHUB_REPOSITORY_OWNER:-${GITHUB_REPOSITORY%%/*}}" | tr '[:upper:]' '[:lower:]')"
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
  image_name="ghcr.io/${owner}/${suffix}"
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

echo "Published all MOGO container tags for ${GITHUB_REF_NAME}."

# ── 024 T032 (FR-018)：晋级记录写入发布记录 ─────────────────────────────
# 每次把候选提升为版本 tag 的动作都落到 deploy/releases/，供审计回溯。
echo "Writing promotion record to deploy/releases/..."
python3 scripts/release/record_promotion.py \
  --action promote \
  --source-sha "${GITHUB_SHA}" \
  --source-tag "candidate-${GITHUB_SHA}" \
  --suffixes "$(printf '%s' "${image_suffixes[*]}")" \
  --target-tag "${GITHUB_REF_NAME}" \
  --actor "${GITHUB_ACTOR:-unknown}"
echo "Done. Promotion of ${GITHUB_REF_NAME} recorded."

