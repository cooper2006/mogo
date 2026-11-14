#!/usr/bin/env bash
#
# reset_local_passwords.sh — reset local-development login passwords.
#
# Why this exists
# ---------------
# Password hashes are one-way (PBKDF2-HMAC-SHA256, 120k rounds), so a lost
# password can only be restored by writing a fresh hash. That is exactly what
# happens after the SDD merge: the management console lives in the ``mogo_dev``
# database while the accounts were created in the legacy ``gragentic`` one, and
# the operator no longer remembers the password that the setup wizard asked
# for. The symptom is a bare ``401 Invalid username or password`` even though
# the account, tenant and status are all healthy.
#
# This script resets the credentials of the three local accounts:
#
#   * ``admin``      — tenant administrator (admin-api, ``admin_accounts``)
#   * ``platform``   — platform super-admin (admin-api, ``admin_accounts``)
#   * ``zhujunfeng`` — employee end user (chat-api, ``end_users``)
#
# Each hash is produced by the *service's own* ``hash_password`` helper, run
# inside the running container, so the stored value is byte-identical to what
# the service would have written itself (both admin-api and chat-api use
# PBKDF2-HMAC-SHA256 with 120000 rounds and a 16-byte hex salt).
#
# The legacy ``gragentic`` database is updated as well: it is the source of
# ``migrate_movo_tenant.sh``, so a later re-run of that migration would
# otherwise copy the stale hash back over the fresh one.
#
# Dry-run by default: pass --apply to write.
#
# Usage
# -----
#   scripts/reset_local_passwords.sh --password 'Secret#1234'            # dry-run
#   scripts/reset_local_passwords.sh --password 'Secret#1234' --apply    # write
#   MOGO_RESET_PASSWORD='Secret#1234' scripts/reset_local_passwords.sh --apply
#
# The password is piped to the containers over stdin, never on a command line.
#
# Exit status: 0 on success, 1 on error.
#
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

DOCKER_BIN="${DOCKER_BIN:-docker}"
MONGO_SERVICE="${MOGO_MONGO_SERVICE:-mongo}"
ADMIN_API_SERVICE="${MOGO_ADMIN_API_SERVICE:-admin-api}"
CHAT_API_SERVICE="${MOGO_CHAT_API_SERVICE:-chat-api}"
TARGET_DB="${MOGO_RESET_TARGET_DB:-mogo_dev}"
LEGACY_DB="${MOGO_RESET_LEGACY_DB:-gragentic}"
TENANT_ID="${MOGO_RESET_TENANT_ID:-bonc-56e1ceaab0b0f60100c07b08}"
PLATFORM_TENANT_ID="__platform__"
END_USER_LOGIN_NAME="${MOGO_RESET_END_USER:-zhujunfeng}"
PASSWORD="${MOGO_RESET_PASSWORD:-}"
APPLY=false

usage() {
  sed -n '3,42p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --password) PASSWORD="${2:?--password requires a value}"; shift ;;
    --target-db) TARGET_DB="${2:?--target-db requires a name}"; shift ;;
    --legacy-db) LEGACY_DB="${2:?--legacy-db requires a name}"; shift ;;
    --tenant-id) TENANT_ID="${2:?--tenant-id requires a value}"; shift ;;
    --apply) APPLY=true ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'Unknown argument: %s\n\n' usage >&2; exit 2 ;;
  esac
  shift
done

if [[ -z "${PASSWORD}" ]]; then
  printf 'Enter the new password (input hidden): '
  read -r -s PASSWORD
  printf '\n'
fi

if [[ -z "${PASSWORD}" ]]; then
  printf 'Error: no password supplied.\n' >&2
  exit 2
fi

for service in "${MONGO_SERVICE}" "${ADMIN_API_SERVICE}" "${CHAT_API_SERVICE}"; do
  if [[ -z "$(${DOCKER_BIN} compose ps -q "${service}" 2>/dev/null || true)" ]]; then
    printf 'Error: compose service "%s" is not running.\n' "${service}" >&2
    exit 1
  fi
done

printf 'Target database : %s\n' "${TARGET_DB}"
printf 'Legacy database : %s\n' "${LEGACY_DB}"
printf 'Tenant          : %s\n' "${TENANT_ID}"
printf 'Accounts        : admin, platform, %s\n' "${END_USER_LOGIN_NAME}"
if [[ "${APPLY}" == true ]]; then
  printf 'Mode            : APPLY (writes)\n\n'
else
  printf 'Mode            : DRY-RUN (nothing is written)\n\n'
fi

# ── 1. Hash the password with each service's own helper ────────────────────
# The password travels over stdin so it never shows up in `ps` output.
admin_hashes="$(
  printf '%s' "${PASSWORD}" | ${DOCKER_BIN} compose exec -T "${ADMIN_API_SERVICE}" python -c '
import json, sys
from app.core.security import hash_password

password = sys.stdin.read()
out = {}
for username in ("admin", "platform"):
    digest, salt = hash_password(password)
    out[username] = {"hash": digest, "salt": salt}
print(json.dumps(out))
'
)"

end_user_hash="$(
  printf '%s' "${PASSWORD}" | ${DOCKER_BIN} compose exec -T "${CHAT_API_SERVICE}" python -c '
import json, sys
from app.core.end_user_auth import hash_password

password = sys.stdin.read()
digest, salt = hash_password(password)
print(json.dumps({"hash": digest, "salt": salt}))
'
)"

# ── 2. Write the hashes ────────────────────────────────────────────────────
${DOCKER_BIN} compose exec -T \
  -e MOGO_RESET_TARGET_DB="${TARGET_DB}" \
  -e MOGO_RESET_LEGACY_DB="${LEGACY_DB}" \
  -e MOGO_RESET_TENANT_ID="${TENANT_ID}" \
  -e MOGO_RESET_PLATFORM_TENANT_ID="${PLATFORM_TENANT_ID}" \
  -e MOGO_RESET_END_USER="${END_USER_LOGIN_NAME}" \
  -e MOGO_RESET_ADMIN_HASHES="${admin_hashes}" \
  -e MOGO_RESET_END_USER_HASH="${end_user_hash}" \
  -e MOGO_RESET_APPLY="${APPLY}" \
  "${MONGO_SERVICE}" mongosh --quiet --file /dev/stdin <<'JS'
const target = db.getSiblingDB(process.env.MOGO_RESET_TARGET_DB);
const legacy = db.getSiblingDB(process.env.MOGO_RESET_LEGACY_DB);
const tenantId = process.env.MOGO_RESET_TENANT_ID;
const platformTenantId = process.env.MOGO_RESET_PLATFORM_TENANT_ID;
const endUser = process.env.MOGO_RESET_END_USER;
const adminHashes = JSON.parse(process.env.MOGO_RESET_ADMIN_HASHES);
const endUserHash = JSON.parse(process.env.MOGO_RESET_END_USER_HASH);
const apply = process.env.MOGO_RESET_APPLY === "true";

function applyOne(scope, collection, filter, creds) {
  const doc = scope.getCollection(collection).findOne(filter);
  if (!doc) {
    print(`  MISS  ${collection} ${JSON.stringify(filter)}`);
    return;
  }
  const same = doc.password_hash === creds.hash && doc.password_salt === creds.salt;
  print(`  ${same ? "SAME" : "SET "}  ${collection} ${JSON.stringify(filter)}`);
  if (!apply || same) return;
  scope.getCollection(collection).updateOne(filter, {
    $set: { password_hash: creds.hash, password_salt: creds.salt, updated_at: new Date() },
  });
  print(`        written (hash=${creds.hash.slice(0, 12)}…, salt=${creds.salt.slice(0, 8)}…)`);
}

print("── admin-api · admin_accounts ──");
applyOne(target, "admin_accounts", { username: "admin", tenant_id: tenantId }, adminHashes.admin);
applyOne(target, "admin_accounts", { username: "platform", tenant_id: platformTenantId }, adminHashes.platform);

print("── chat-api · end_users ──");
applyOne(target, "end_users", { login_name: endUser }, endUserHash);

print("── legacy database (keeps migrate_movo_tenant.sh from restoring stale hashes) ──");
applyOne(legacy, "admin_accounts", { username: "admin" }, adminHashes.admin);
applyOne(legacy, "end_users", { login_name: endUser }, endUserHash);
JS

if [[ "${APPLY}" != true ]]; then
  printf '\nDry-run only. Re-run with --apply to write.\n'
else
  printf '\nPasswords updated.\n'
fi
