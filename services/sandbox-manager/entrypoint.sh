#!/bin/sh
set -eu
set -a
. "${ASKAI_RUNTIME_SECRETS_FILE:-/run/askai-secrets/runtime.env}"
set +a
exec "$@"
