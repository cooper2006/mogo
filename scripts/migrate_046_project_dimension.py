"""P0 数据模型迁移（046 D6/D2/D4）—— 集合改名、默认项目、全量回填。

**为什么写成子命令**：035 §8 的三阶段（P0 数据模型 → P1 回填 → P2 切读）各自
可独立交付，每个子命令对应一个可独立执行、可独立回滚的操作。

Usage (all sub-commands are idempotent and support --dry-run):

    # P0: 集合改名（停旧实例 → 改名 → 起新实例，不可滚动升级）
    python scripts/migrate_046_project_dimension.py --rename-collection --dry-run
    python scripts/migrate_046_project_dimension.py --rename-collection

    # P0: 为每个 (tenant_id, user_id) 幂等生成默认项目
    python scripts/migrate_046_project_dimension.py --ensure-default-project --dry-run

    # P0: 给 chat_sessions 加 project_id 字段（先允许空，P2 再收紧）
    python scripts/migrate_046_project_dimension.py --add-session-field --dry-run

    # P1: 按 agent_kernel_bindings.source_workspace_id 回填历史会话 project_id
    python scripts/migrate_046_project_dimension.py --backfill --dry-run
    python scripts/migrate_046_project_dimension.py --backfill --batch-size 500

    # 断点续跑（记录最后处理的 binding _id）
    python scripts/migrate_046_project_dimension.py --backfill --resume-from <binding_id>

**安全约定**：
- 默认 `--dry-run`，不写任何数据；`--apply` 才落盘。
- 改名前强制要求先 `mongodump`（环境变量 `MOGO_MIGRATION_DUMP_DIR`）。
- 失败清单落 `backups/046-backfill-failures-<ts>.json`，不会吞掉错误。
- `_id = "default"` 的默认项目：`--ensure-default-project` 幂等生成，
  `--backfill` 与 `--add-session-field` 无绑定会话也落 `"default"`。
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import os
import sys
from typing import Any

MONGO_URI = os.environ.get("MONGODB_URI") or os.environ.get("MONGO_URL") or "mongodb://localhost:27017"
DB_NAME = os.environ.get("MOGO_DB_NAME") or "mogo"
BACKUP_DIR = os.environ.get("MOGO_MIGRATION_DUMP_DIR") or "backups"
DEFAULT_BATCH_SIZE = 500
DEFAULT_PROJECT_ID = "default"


def _get_db() -> Any:
    """Lazily import motor so the module can be imported for inspection."""
    from motor.motor_asyncio import AsyncIOMotorClient

    client = AsyncIOMotorClient(MONGO_URI)
    return client[DB_NAME]


def _timestamp() -> str:
    return datetime.datetime.now(tz=datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _failures_path() -> str:
    return os.path.join(BACKUP_DIR, f"046-backfill-failures-{_timestamp()}.json")


def _log(kind: str, message: str) -> None:
    print(f"[{kind}] {message}", file=sys.stderr if kind == "ERROR" else sys.stdout)


async def _collection_exists(db: Any, name: str) -> bool:
    try:
        names = await db.list_collection_names()
    except AttributeError:
        # PanWeiDB / test stub path: fall back to a single collection listing.
        names = await db.command("listCollections", 1, cursor={})
        return any(c["name"] == name for c in names["cursor"]["firstBatch"])
    return name in names


# --------------------------------------------------------------------------
# P0: 集合改名
# --------------------------------------------------------------------------

async def rename_collection(dry_run: bool) -> dict[str, Any]:
    """`desktop_projects` → `projects`（046 FR-001 / D6）。

    发布顺序必须是"停旧实例 → 改名 → 起新实例"（046 Edge Case 6）：滚动升级期间
    旧实例会把 `update_one` 发进已改名的集合而抛 `NamespaceNotFound`。
    """
    db = _get_db()
    old, new = "desktop_projects", "projects"
    result = {"renamed": False, "already": False, "dry_run": dry_run}

    exists_old = await _collection_exists(db, old)
    exists_new = await _collection_exists(db, new)

    if not exists_old:
        _log("WARN", f"源集合 {old} 不存在——可能已改名，跳过")
        result["already"] = True
        return result
    if exists_new:
        _log("WARN", f"目标集合 {new} 已存在——可能已改名，跳过")
        result["already"] = True
        return result

    if dry_run:
        _log("DRY-RUN", f"would rename {old} -> {new}")
        result["dry_run"] = True
        return result

    # 安全门禁：改名前必须有备份目录（约定的 mongodump 落点）
    if not os.path.isdir(BACKUP_DIR):
        raise RuntimeError(
            f"backup directory {BACKUP_DIR} not found; take a full mongodump "
            f"into it before renaming (set MOGO_MIGRATION_DUMP_DIR to override)"
        )

    await db.command("renameCollection", f"{DB_NAME}.{old}", to=f"{DB_NAME}.{new}")
    result["renamed"] = True
    _log("OK", f"renamed {old} -> {new}")
    return result


# --------------------------------------------------------------------------
# P0: 默认项目幂等生成（D2）
# --------------------------------------------------------------------------

async def ensure_default_project(dry_run: bool) -> dict[str, Any]:
    """为每个 (tenant_id, user_id) 幂等生成一条 `_id = "default"` 的默认项目。

    仿 `directory_repository.ensure_root_department` 的写法：`$setOnInsert`
    保首次创建、`$set` 保更新时间，`upsert=True` 保重复调用只有一条。
    `_id = "default"` 的项目不可归档、不可删除（046 Edge Case 3）。
    """
    db = _get_db()
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    result = {"inserted": 0, "updated": 0, "already": 0}

    cursor = db.chat_sessions.aggregate(
        [{"$group": {"_id": {"tenant_id": "$tenant_id", "user_id": "$user_id"}}}]
    )
    pairs = []
    async for row in cursor:
        if row["_id"].get("tenant_id") and row["_id"].get("user_id"):
            pairs.append(row["_id"])

    if not pairs:
        _log("WARN", "no (tenant_id, user_id) pairs found in chat_sessions; nothing to provision")
        return result

    for pair in pairs:
        tenant_id, user_id = pair["tenant_id"], pair["user_id"]
        scope = {"tenant_id": tenant_id, "user_id": user_id, "_id": DEFAULT_PROJECT_ID}
        if dry_run:
            result["dry_run"] = True
            continue

        outcome = await db.projects.update_one(
            scope,
            {
                "$setOnInsert": {
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "_id": DEFAULT_PROJECT_ID,
                    "title": "默认项目",
                    "status": "active",
                    "created_at": now,
                },
                "$set": {"updated_at": now},
            },
            upsert=True,
        )
        if outcome.upserted_id:
            result["inserted"] += 1
        elif outcome.modified_count:
            result["updated"] += 1
        else:
            result["already"] += 1

    _log("OK", f"default project: inserted={result['inserted']} updated={result['updated']} already={result['already']}")
    return result


# --------------------------------------------------------------------------
# P0: chat_sessions 加 project_id 字段（先允许空）
# --------------------------------------------------------------------------

async def add_session_field(dry_run: bool) -> dict[str, Any]:
    """`chat_sessions` 补 `project_id` 字段（FR-004），先允许空，P2 再收紧。"""
    db = _get_db()
    result = {"added": 0, "already": 0}

    if dry_run:
        _log("DRY-RUN", "would add project_id to chat_sessions")
        return result

    # 用 update_many 给已有文档补字段（不存在的会话创建时由 repository 写入）
    outcome = await db.chat_sessions.update_many(
        {"project_id": {"$exists": False}},
        {"$set": {"project_id": DEFAULT_PROJECT_ID}},
    )
    result["added"] = outcome.modified_count
    _log("OK", f"project_id added to {outcome.modified_count} existing chat_sessions")
    return result


# --------------------------------------------------------------------------
# P1: 全量回填
# --------------------------------------------------------------------------

async def backfill(dry_run: bool, batch_size: int, resume_from: str | None) -> dict[str, Any]:
    """遍历 `agent_kernel_bindings`，按 `source_workspace_id` 回填会话 `project_id`。

    无绑定 → `"default"`；已回填的会话跳过（幂等）；失败落清单；支持断点续跑。
    """
    db = _get_db()
    result = {"processed": 0, "written": 0, "skipped": 0, "failed": 0, "failures": []}

    query: dict[str, Any] = {}
    if resume_from:
        query["_id"] = {"$gt": resume_from}

    bindings = db.agent_kernel_bindings.find(query).sort("_id", 1)
    failures: list[dict[str, Any]] = []
    batch: list[dict[str, Any]] = []

    async for binding in bindings:
        source_ws = binding.get("source_workspace_id")
        project_id = source_ws or DEFAULT_PROJECT_ID
        result["processed"] += 1

        if dry_run:
            result["written"] += 1
            continue

        batch.append({"session_id": binding.get("kernel_session_id"), "project_id": project_id})
        if len(batch) >= batch_size:
            written, skipped, failed, more = await _flush_batch(db, batch)
            result["written"] += written
            result["skipped"] += skipped
            result["failed"] += failed
            result["failures"].extend(more)
            batch = []
            _log("PROGRESS", f"processed={result['processed']} written={result['written']} failed={result['failed']}")

    if batch:
        written, skipped, failed, more = await _flush_batch(db, batch)
        result["written"] += written
        result["skipped"] += skipped
        result["failed"] += failed
        result["failures"].extend(more)

    if not dry_run and result["failures"]:
        os.makedirs(BACKUP_DIR, exist_ok=True)
        path = _failures_path()
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(result["failures"], fh, indent=2, ensure_ascii=False)
        _log("WARN", f"{len(result['failures'])} failures written to {path}")
    elif not dry_run:
        _log("OK", f"backfill complete: processed={result['processed']} written={result['written']} skipped={result['skipped']} failed=0")
    else:
        _log("DRY-RUN", f"would process {result['processed']} bindings")
    return result


async def _flush_batch(db: Any, batch: list[dict[str, Any]]) -> tuple[int, int, int, list[dict[str, Any]]]:
    """`update_many` 幂等写入：已相同值的跳过，不同的覆盖。"""
    written = skipped = failed = 0
    failures: list[dict[str, Any]] = []
    for entry in batch:
        session_id, project_id = entry["session_id"], entry["project_id"]
        if not session_id:
            failed += 1
            failures.append({"session_id": None, "project_id": project_id, "reason": "no kernel_session_id on binding"})
            continue
        try:
            outcome = await db.chat_sessions.update_one(
                {"session_id": session_id},
                {"$set": {"project_id": project_id}},
            )
            if outcome.matched_count == 0:
                failed += 1
                failures.append({"session_id": session_id, "project_id": project_id, "reason": "no matching chat_session"})
            elif outcome.modified_count == 0:
                skipped += 1
            else:
                written += 1
        except Exception as exc:  # noqa: BLE001 — 回填必须记录每一条，不能中断整批
            failed += 1
            failures.append({"session_id": session_id, "project_id": project_id, "reason": f"{type(exc).__name__}: {exc}"})
    return written, skipped, failed, failures


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="046 项目维度迁移（P0 数据模型 + P1 全量回填）")
    parser.add_argument("--apply", action="store_true", help="实际落盘；缺省为 dry-run")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, help=f"回填分批大小（默认 {DEFAULT_BATCH_SIZE}）")
    parser.add_argument("--resume-from", type=str, default=None, help="断点续跑：从该 binding _id 之后继续")

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--rename-collection", action="store_true", help="P0: desktop_projects → projects")
    group.add_argument("--ensure-default-project", action="store_true", help="P0: 幂等生成默认项目")
    group.add_argument("--add-session-field", action="store_true", help="P0: chat_sessions 补 project_id")
    group.add_argument("--backfill", action="store_true", help="P1: 按 binding 回填历史会话 project_id")
    return parser


async def _main() -> int:
    args = _build_parser().parse_args()
    dry_run = not args.apply

    if args.rename_collection:
        await rename_collection(dry_run)
    elif args.ensure_default_project:
        await ensure_default_project(dry_run)
    elif args.add_session_field:
        await add_session_field(dry_run)
    elif args.backfill:
        await backfill(dry_run, args.batch_size, args.resume_from)
        if not dry_run:
            await _report_unassigned_ratio()
    return 0


async def _report_unassigned_ratio() -> None:
    """T020 (SC-001): 回填后校验——统计 project_id 为 null/空串的会话数和「未分配」占比。"""
    db = _get_db()
    total = await db.chat_sessions.count_documents({})
    null_count = await db.chat_sessions.count_documents({"project_id": None})
    empty_count = await db.chat_sessions.count_documents({"project_id": ""})
    unassigned = null_count + empty_count
    ratio = (unassigned / total * 100) if total > 0 else 0.0
    _log("REPORT", f"chat_sessions total={total} null={null_count} empty={empty_count} unassigned={unassigned} ({ratio:.2f}%)")
    if unassigned > 0:
        _log("WARN", f"{unassigned} sessions still lack project_id — check bindings coverage")


def main() -> int:
    try:
        return asyncio.run(_main())
    except Exception as exc:  # noqa: BLE001
        _log("ERROR", f"{type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
