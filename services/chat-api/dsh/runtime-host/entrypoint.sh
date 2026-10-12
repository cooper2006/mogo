#!/bin/sh
set -eu

secret_file="${ASKAI_RUNTIME_SECRETS_FILE:-/run/askai-secrets/runtime.env}"
if [ -r "$secret_file" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$secret_file"
  set +a
fi

runtime_token="${DSH_RUNTIME_HOST_TOKEN:-}"
if [ "${#runtime_token}" -lt 32 ]; then
  echo "DSH_RUNTIME_HOST_TOKEN is missing or too short." >&2
  exit 1
fi

# 022 US3 (T027): the image declares `USER node`, so the container already
# starts unprivileged and there is nothing left to drop. The root branch is kept
# for callers that force uid 0 (e.g. `docker run -u 0`) and for images built
# before the hardening; there gosu still hands the process to `node`.
#
# Both branches matter for the volume ownership: on a fresh dsh-runtime-data
# volume Docker copies the owner from the image (node), so the root branch is
# only a safety net. It must stay conditional — running `chown` as a non-root
# user would fail and `set -eu` would abort the start-up.
if [ "$(id -u)" = "0" ]; then
  mkdir -p /data/dsh-runtime
  chown -R node:node /data/dsh-runtime
  exec gosu node "$@"
fi

exec "$@"
