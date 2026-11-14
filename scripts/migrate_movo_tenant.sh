#!/usr/bin/env bash
#
# migrate_movo_tenant.sh — migrate a legacy MOVO tenant into the MOGO
# multi-tenant model.
#
# Why this exists
# ---------------
# Before the SDD merge the admin/chat APIs ran on the legacy ``main_id``
# tenant model and stored everything in the ``gragentic`` database. The
# merged code speaks the multi-tenant model: ``tenant_id`` everywhere, the
# ``tenants`` registry as the source of truth, and 32-hex primary keys
# (``app/core/ids.py`` only accepts 32-hex for model instances / groups).
#
# The compose default database therefore switched to ``mogo_dev`` and the
# legacy tenant became invisible: ``admin_accounts`` no longer holds the
# ``admin`` account, so the management console cannot log in at all.
#
# This script copies one legacy tenant across:
#
#   * ``main_id`` → ``tenant_id`` on every scoped collection
#   * 24-hex primary keys → 32-hex (deterministic, so re-runs are stable)
#   * cross-collection references rewritten through the id map
#   * ``admin_model_instances.provider_id`` remapped by provider **code**,
#     because the target database already ships the full provider catalogue
#     (``provider_code_unique`` forbids inserting the legacy rows again)
#   * a ``tenants`` registry row, so the tenant is a first-class citizen
#
# The source database is **never modified** — the migration only inserts into
# the target, so ``--rollback`` (drops everything tagged with the tenant id)
# is always sufficient to undo it.
#
# Dry-run by default: pass --apply to write.
#
# Usage
# -----
#   scripts/migrate_movo_tenant.sh --tenant-id bonc-xxxx            # dry-run
#   scripts/migrate_movo_tenant.sh --tenant-id bonc-xxxx --apply    # write
#   scripts/migrate_movo_tenant.sh --tenant-id bonc-xxxx --rollback # undo
#
# Exit status: 0 on success, 1 on error.
#
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

DOCKER_BIN="${DOCKER_BIN:-docker}"
MONGO_SERVICE="${MOGO_MONGO_SERVICE:-mongo}"
SRC_DB="${MOGO_MIGRATE_SRC_DB:-gragentic}"
DST_DB="${MOGO_MIGRATE_DST_DB:-mogo_dev}"
TENANT_ID="${MOGO_MIGRATE_TENANT_ID:-}"
APPLY=false
ROLLBACK=false

usage() {
  sed -n '3,38p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --tenant-id) TENANT_ID="${2:?--tenant-id requires a value}"; shift ;;
    --source-db) SRC_DB="${2:?--source-db requires a name}"; shift ;;
    --target-db) DST_DB="${2:?--target-db requires a name}"; shift ;;
    --apply) APPLY=true ;;
    --rollback) ROLLBACK=true ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'Unknown argument: %s\n\n' usage >&2; exit 2 ;;
  esac
  shift
done

if [[ -z "${TENANT_ID}" ]]; then
  printf 'Error: --tenant-id is required.\n\n' >&2
  usage >&2
  exit 2
fi

if [[ -z "$(${DOCKER_BIN} compose ps -q "${MONGO_SERVICE}" 2>/dev/null || true)" ]]; then
  printf 'Error: compose service "%s" is not running.\n' "${MONGO_SERVICE}" >&2
  exit 1
fi

# The migration runs as one mongosh program. Values arrive through the
# environment rather than being interpolated into the script text, so a
# database name can never be read as JavaScript.
mongo_program() {
  cat <<'JS'
const srcName = process.env.MOVO_MIGRATE_SRC_DB;
const dstName = process.env.MOVO_MIGRATE_DST_DB;
const tenantId = process.env.MOVO_MIGRATE_TENANT_ID;
const apply = process.env.MOVO_MIGRATE_APPLY === 'true';
const rollback = process.env.MOVO_MIGRATE_ROLLBACK === 'true';

const src = db.getSiblingDB(srcName);
const dst = db.getSiblingDB(dstName);

// Collections whose documents carry the legacy ``main_id`` tenant key.
// ``position_roles`` is included on purpose: it is scoped, but its primary
// key is a semantic string (``system:<tenant>:full_access_admin``) and must
// NOT be rewritten into a 32-hex id.
const COLLECTIONS = [
  "admin_accounts",
  "admin_account_groups",
  "admin_model_instances",
  "end_user_org_relations",
  "end_user_position_roles",
  "end_users",
  "organizations",
  "org_quota_policies",
  "org_units",
  "position_role_migrations",
  "position_roles",
  "user_quota_policies",
  "user_token_allocation_logs",
];

// Primary keys that are semantic, not generated — leave them untouched.
const SEMANTIC_ID = new Set(["position_roles"]);

// Legacy ids are 24-hex (an ObjectId rendered as a string); the MOGO
// terminal model only accepts 32-hex (app/core/ids.py). The suffix is
// derived from the tenant id so the mapping is deterministic and re-runs
// never mint a second set of ids.
const suffix = tenantId.replace(/[^0-9a-f]/gi, "").slice(-8).padEnd(8, "0");
function newId(oldId) {
  if (typeof oldId !== "string" || !/^[0-9a-f]{24}$/i.test(oldId)) return oldId;
  return oldId + suffix;
}

function asIdString(value) {
  // Legacy documents store their primary keys as real ObjectIds, not as
  // strings — normalise both shapes before any comparison.
  if (value === null || value === undefined) return null;
  if (typeof value === "string") return value;
  if (typeof value === "object" && typeof value.toHexString === "function") {
    return value.toHexString();
  }
  return String(value);
}

function isHex24(value) {
  const s = asIdString(value);
  return typeof s === "string" && /^[0-9a-f]{24}$/i.test(s);
}

// Provider catalogue: the target database ships the full set of provider
// templates, and ``provider_code_unique`` makes inserting the legacy rows
// impossible. Remap the instance's provider by **code** instead.
const providerByCode = {};
dst.getCollection("admin_model_providers").find({}).forEach((p) => {
  providerByCode[p.code] = p._id;
});
const legacyProviderCode = {};
src.getCollection("admin_model_providers").find({}).forEach((p) => {
  legacyProviderCode[p._id] = p.code;
});

if (rollback) {
  let removed = 0;
  for (const c of COLLECTIONS) {
    const n = dst.getCollection(c).deleteMany({ tenant_id: tenantId }).deletedCount;
    if (n > 0) { print('  removed ' + n + ' from ' + c); removed += n; }
  }
  const t = dst.getCollection("tenants").deleteMany({ tenant_id: tenantId }).deletedCount;
  if (t > 0) { print('  removed ' + t + ' from tenants'); removed += t; }
  print('ROLLED_BACK=' + removed);
} else {
  // ---- 1. read the legacy tenant -------------------------------------
  const docs = {};
  for (const c of COLLECTIONS) {
    docs[c] = src.getCollection(c).find({ main_id: tenantId }).toArray();
  }

  // ---- 2. build the id map -------------------------------------------
  const idMap = {};
  for (const c of COLLECTIONS) {
    if (SEMANTIC_ID.has(c)) continue;
    for (const d of docs[c]) {
      const oldId = asIdString(d._id);
      if (isHex24(oldId)) idMap[oldId] = newId(oldId);
    }
  }

  // ---- 3. transform --------------------------------------------------
  let planned = 0;
  const preview = [];
  for (const c of COLLECTIONS) {
    for (const d of docs[c]) {
      const out = Object.assign({}, d);
      const oldOwnId = asIdString(out._id);
      if (idMap[oldOwnId]) out._id = idMap[oldOwnId];
      delete out.main_id;
      out.tenant_id = tenantId;

      // Rewrite every reference that points at a migrated document.
      for (const key of Object.keys(out)) {
        if (key === "_id") continue;
        const ref = asIdString(out[key]);
        if (ref && idMap[ref]) out[key] = idMap[ref];
      }

      if (c === "admin_model_instances") {
        const code = legacyProviderCode[asIdString(out.provider_id)];
        const target = code ? providerByCode[code] : undefined;
        if (target) {
          out.provider_id = target;
        } else if (code) {
          print('  WARNING: provider code "' + code + '" not found in target db');
        }
      }

      planned += 1;
      preview.push(c + ' ' + out._id);
      if (apply) {
        dst.getCollection(c).replaceOne({ _id: out._id }, out, { upsert: true });
      }
    }
  }

  // ---- 4. the tenant registry row ------------------------------------
  const orgDoc = src.getCollection("organizations").findOne({ main_id: tenantId });
  const existing = dst.getCollection("tenants").findOne({ tenant_id: tenantId });
  if (!existing) {
    const now = new Date();
    const row = {
      tenant_id: tenantId,
      status: "active",
      display_name: (orgDoc && orgDoc.org_name) || tenantId,
      org_name: (orgDoc && orgDoc.org_name) || tenantId,
      edition: (orgDoc && orgDoc.edition) || "community",
      tier: (orgDoc && orgDoc.tier) || "community",
      created_at: now,
      updated_at: now,
      source: "movo-tenant-migration",
    };
    if (apply) dst.getCollection("tenants").insertOne(row);
    print('  tenants: +1 (' + tenantId + ')');
    planned += 1;
  } else {
    print('  tenants: already present, left untouched');
  }

  print('MIGRATED=' + planned);
  for (const line of preview) print('  ' + line);
}
JS
}

printf '\nSource database: %s   Target database: %s\n' "${SRC_DB}" "${DST_DB}"
printf 'Tenant id: %s\n' "${TENANT_ID}"
if [[ "${ROLLBACK}" == true ]]; then
  printf 'Mode: ROLLBACK (removes the migrated rows from the target)\n\n'
elif [[ "${APPLY}" == true ]]; then
  printf 'Mode: APPLY (writes into the target database)\n\n'
else
  printf 'Mode: DRY-RUN (nothing is written; pass --apply to commit)\n\n'
fi

# mongosh ignores a program on stdin and drops into its REPL, so hand it a
# file instead. The temp file is removed even when the migration fails.
program_file="$(mktemp)"
trap 'rm -f "${program_file}"' EXIT
mongo_program > "${program_file}"

summary="$(${DOCKER_BIN} compose exec -T \
  -e MOVO_MIGRATE_SRC_DB="${SRC_DB}" \
  -e MOVO_MIGRATE_DST_DB="${DST_DB}" \
  -e MOVO_MIGRATE_TENANT_ID="${TENANT_ID}" \
  -e MOVO_MIGRATE_APPLY="${APPLY}" \
  -e MOVO_MIGRATE_ROLLBACK="${ROLLBACK}" \
  "${MONGO_SERVICE}" mongosh --quiet --file /dev/stdin < "${program_file}" 2>&1 || true)"

counted="$(printf '%s\n' "${summary}" | grep -oE '^(MIGRATED|ROLLED_BACK)=[0-9]+$' | grep -oE '[0-9]+$' | tail -1)"
printf '%s\n' "${summary}" | grep -vE '^(MIGRATED|ROLLED_BACK)=' || true

if [[ -z "${counted}" ]]; then
  printf '\nError: could not read a total from mongosh. Output above.\n' >&2
  exit 1
fi

if [[ "${ROLLBACK}" == true ]]; then
  printf '\nRollback complete: %s document(s) removed.\n' "${counted}"
elif [[ "${APPLY}" == true ]]; then
  printf '\nMigration complete: %s document(s) written to %s.\n' "${counted}" "${DST_DB}"
else
  printf '\nDry-run: %s document(s) would be written to %s.\n' "${counted}" "${DST_DB}"
  printf 'Re-run with --apply to commit.\n'
fi
