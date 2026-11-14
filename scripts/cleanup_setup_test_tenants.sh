#!/usr/bin/env bash
#
# cleanup_setup_test_tenants.sh — remove orphaned `setup-test-*` probe tenants.
#
# Why these rows exist
# --------------------
# ``admin-api`` verifies a model during first-time setup by creating a
# throwaway tenant named ``setup-test-<hex>``, running a connectivity probe,
# and deleting it again (``app/services/setup_model.py``). Two bugs let rows
# survive that cleanup:
#
#   1. ``if instance_id:`` meant a failure inside ``create_instance`` skipped
#      cleanup entirely — ``instance_id`` was still "".
#   2. ``delete_instance`` only removes the ``admin_model_instances`` row. The
#      probe also causes rows to materialise in ``organizations``, the quota
#      policy collections and ``token_usage_logs``; those were never swept.
#
# Both are fixed in the service. This script clears what the old code left.
#
# Dry-run by default: pass --apply to delete.
#
# Usage
# -----
#   scripts/cleanup_setup_test_tenants.sh                 # dry-run (default)
#   scripts/cleanup_setup_test_tenants.sh --apply         # delete
#   scripts/cleanup_setup_test_tenants.sh --db othersvc   # other database
#
# Exit status: 0 on success (including "nothing to do"), 1 on error.
#
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

DOCKER_BIN="${DOCKER_BIN:-docker}"
MONGO_SERVICE="${MOGO_MONGO_SERVICE:-mongo}"
DB_NAME="${MOGO_DB_NAME:-mogo_dev}"
APPLY=false

usage() {
  sed -n '3,26p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply) APPLY=true ;;
    --db) DB_NAME="${2:?--db requires a database name}"; shift ;;
    --mongo-service) MONGO_SERVICE="${2:?--mongo-service requires a name}"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'Unknown argument: %s\n\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

if [[ -z "$(${DOCKER_BIN} compose ps -q "${MONGO_SERVICE}" 2>/dev/null || true)" ]]; then
  printf 'Error: compose service "%s" is not running.\n' "${MONGO_SERVICE}" >&2
  exit 1
fi

# The sweep runs as one mongosh program. Values arrive through the environment
# rather than being interpolated into the script text, so a database name can
# never be read as JavaScript.
mongo_program() {
  cat <<'JS'
const dbName = process.env.MOGO_CLEANUP_DB;
const apply = process.env.MOGO_CLEANUP_APPLY === 'true';
const pattern = new RegExp(process.env.MOGO_CLEANUP_PATTERN);
const collections = JSON.parse(process.env.MOGO_CLEANUP_COLLECTIONS);

const db = db.getSiblingDB(dbName);
let total = 0;
for (const c of collections) {
  const filter = { tenant_id: { $regex: pattern } };
  const n = db.getCollection(c).countDocuments(filter);
  if (n > 0) {
    print('  ' + c + ': ' + n);
    total += n;
    if (apply) {
      db.getCollection(c).deleteMany(filter);
    }
  }
}
print('TOTAL=' + total);
JS
}

# Mirrors SETUP_SCOPED_COLLECTIONS (+ token_usage_logs) in
# app/services/setup_cleanup.py, which stays the source of truth.
COLLECTIONS_JSON="$(python3 -c '
import json
print(json.dumps([
    "admin_account_groups", "admin_accounts", "admin_model_instances",
    "org_units", "end_users", "end_user_org_relations",
    "end_user_position_roles", "position_roles", "position_role_migrations",
    "position_role_audit_logs", "org_quota_policies", "user_quota_policies",
    "user_token_allocation_logs", "token_usage_logs",
    "external_search_configs", "knowledge_document_settings",
    "organizations", "tenants",
]))
')"

# Only ids of this exact shape are touched: the ``setup-test-`` probe prefix
# from setup_model.py plus 24 hex chars from secrets.token_hex(12). Real tenants
# (e.g. ``bonc-2331b8a0ecdbd2ebcbf253c4``) never match this prefix.
PATTERN='^setup-test-[0-9a-f]{24}$'

printf '\nDatabase: %s   (compose service: %s)\n' "${DB_NAME}" "${MONGO_SERVICE}"
printf 'Matching tenant ids: %s\n\n' "${PATTERN}"

# mongosh ignores a program on stdin and drops into its REPL, so hand it a
# file instead. The temp file is removed even when the sweep fails.
program_file="$(mktemp)"
trap 'rm -f "${program_file}"' EXIT
mongo_program > "${program_file}"

summary="$(${DOCKER_BIN} compose exec -T \
  -e MOGO_CLEANUP_DB="${DB_NAME}" \
  -e MOGO_CLEANUP_APPLY="${APPLY}" \
  -e MOGO_CLEANUP_PATTERN="${PATTERN}" \
  -e MOGO_CLEANUP_COLLECTIONS="${COLLECTIONS_JSON}" \
  "${MONGO_SERVICE}" mongosh --quiet --file /dev/stdin < "${program_file}" 2>&1 || true)"

printf '%s\n' "${summary}" | grep -v '^TOTAL=' || true

counted="$(printf '%s\n' "${summary}" | sed -n 's/^TOTAL=\([0-9]*\)$/\1/p' | tail -1)"
if [[ -z "${counted}" ]]; then
  printf '\nError: could not read a total from mongosh. Output above.\n' >&2
  exit 1
fi

if [[ "${counted}" == "0" ]]; then
  printf '\nNothing to clean — no orphaned setup-test-* tenants found.\n\n'
  exit 0
fi

if [[ "${APPLY}" != "true" ]]; then
  printf '\nDRY RUN: %s row(s) would be deleted.\n' "${counted}"
  printf 'Re-run with --apply to delete them.\n\n'
  exit 0
fi

printf '\nRemoved %s row(s) from the listed collections in "%s".\n\n' "${counted}" "${DB_NAME}"
