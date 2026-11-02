#!/usr/bin/env bash
set -euo pipefail

secret_file="${ASKAI_RUNTIME_SECRETS_FILE:-/run/askai-secrets/runtime.env}"
if [[ -r "${secret_file}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${secret_file}"
  set +a
  
  # Write critical tokens to a readable temp file for Python processes.
  # Docker security profiles may filter os.environ and clear /proc/1/environ,
  # so we write secrets to /tmp where the process has write access.
  if command -v grep >/dev/null 2>&1; then
    grep -E "^(ADMIN_BACKEND_SERVICE_TOKEN|ASKAI_ADMIN_BACKEND_SERVICE_TOKEN)=" "${secret_file}" > "/tmp/mogo-secrets.env" 2>/dev/null || true
    chmod 644 "/tmp/mogo-secrets.env" 2>/dev/null || true
  fi
fi

exec "$@"
