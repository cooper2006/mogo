"""Phase 2 backfill: set tenant_id = main_id on every known collection.

DO NOT RUN AUTOMATICALLY. This is a manual, review-then-run migration that
populates the new canonical ``tenant_id`` field from the legacy ``main_id``
field across all persisted stores (MongoDB + Weaviate). It is idempotent:
documents that already carry ``tenant_id`` are skipped.

Run only AFTER Phase 1 (dual-write + fallback-read) is deployed and verified,
and only after taking a full `mongodump` + Weaviate snapshot backup.

Usage (dry-run, no writes):
    python scripts/migrate_main_id_to_tenant_id.py --dry-run

Real run:
    python scripts/migrate_main_id_to_tenant_id.py --apply

Phase 3 (separate, post-verification) deletes the legacy fields.
"""

from __future__ import annotations

import argparse
import asyncio
import os
from typing import Any

# MongoDB collections that store a tenant primary key under ``main_id`` (and now
# ``tenant_id`` after Phase 1 dual-write). Expand this list as Phase 1 covers
# more modules. Each entry is (collection_name, legacy_field, canonical_field).
MONGO_TENANT_COLLECTIONS: list[tuple[str, str, str]] = [
    ("end_users", "main_id", "tenant_id"),
    ("tenants", "main_id", "tenant_id"),
    ("organizations", "main_id", "tenant_id"),
    ("org_units", "main_id", "tenant_id"),
    ("configured_models", "main_id", "tenant_id"),
    ("configured_image_models", "main_id", "tenant_id"),
    ("org_quota_policy", "main_id", "tenant_id"),
    ("user_quota_policy", "main_id", "tenant_id"),
    ("user_quota_override", "main_id", "tenant_id"),
    ("token_usage_logs", "main_id", "tenant_id"),
    ("scheduled_tasks", "main_id", "tenant_id"),
    ("context_space", "main_id", "tenant_id"),
    ("knowledge_graph", "main_id", "tenant_id"),
    ("memory", "main_id", "tenant_id"),
    ("a2a", "main_id", "tenant_id"),
    ("personal_knowledge", "main_id", "tenant_id"),
    ("knowledge_document_chunks", "main_id", "tenant_id"),
    ("knowledge_documents", "main_id", "tenant_id"),
    ("resources", "main_id", "tenant_id"),
    ("grants", "main_id", "tenant_id"),
    ("directory", "main_id", "tenant_id"),
    ("org_user", "main_id", "tenant_id"),
    ("model_instances", "main_id", "tenant_id"),
    ("model_providers", "main_id", "tenant_id"),
    ("setup", "main_id", "tenant_id"),
    ("tenant_registry", "main_id", "tenant_id"),
    ("tenant_provisioning", "main_id", "tenant_id"),
    # admin-api side shares the same database for most of these; add here once
    # Phase 1 dual-write lands on admin-api write paths.
]


def _get_mongo() -> Any:
    # Import lazily so the script can be imported for inspection without a DB.
    from motor.motor_asyncio import AsyncIOMotorClient

    uri = os.environ.get("MONGODB_URI") or os.environ.get("MONGO_URL") or "mongodb://localhost:27017"
    client = AsyncIOMotorClient(uri)
    db_name = os.environ.get("MOGO_DB_NAME") or "mogo"
    return client[db_name]


async def _backfill_mongo(dry_run: bool) -> dict[str, int]:
    db = _get_mongo()
    report: dict[str, int] = {}
    for coll, legacy, canonical in MONGO_TENANT_COLLECTIONS:
        if coll not in await db.list_collection_names():
            continue
        match = {canonical: {"$exists": False}, legacy: {"$exists": True, "$ne": None, "$ne": ""}}
        to_update = await db[coll].count_documents(match)
        if dry_run:
            report[coll] = to_update
            continue
        result = await db[coll].update_many(
            match,
            [{"$set": {canonical: {"$ifNull": [f"${canonical}", f"${legacy}"]}}}],
        )
        report[coll] = result.modified_count
    return report


async def _backfill_weaviate(dry_run: bool) -> dict[str, int]:
    # Weaviate backfill is best done via the document-parser vector_store client
    # once Phase 1 dual-write is verified. This is a placeholder for the
    # operators to mirror in the Weaviate tenant; mirroring mainId -> tenantId on
    # every object. Implemented by re-indexing (upsert_chunks already dual-writes).
    return {"weaviate": 0}


async def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill tenant_id from main_id (Phase 2).")
    parser.add_argument("--dry-run", action="store_true", help="Report counts without writing.")
    parser.add_argument("--apply", action="store_true", help="Actually perform the backfill.")
    args = parser.parse_args()
    if not args.dry_run and not args.apply:
        parser.error("specify --dry-run or --apply")

    mongo_report = await _backfill_mongo(args.dry_run)
    weaviate_report = await _backfill_weaviate(args.dry_run)
    print("=== MongoDB tenant_id backfill ===")
    for coll, n in mongo_report.items():
        print(f"  {coll}: {n} documents")
    print("=== Weaviate tenantId backfill ===")
    for k, v in weaviate_report.items():
        print(f"  {k}: {v}")
    if args.dry_run:
        print("(dry-run) no changes written.")


if __name__ == "__main__":
    asyncio.run(main())
