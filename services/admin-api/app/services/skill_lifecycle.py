from __future__ import annotations

import datetime
import hashlib
import json
import re
import uuid
from typing import Any

from app.core.db import get_db


RELEASE_COLLECTION = "organization_skill_releases"
FIELDS = ("name", "description", "scenario", "type", "config")


def now() -> datetime.datetime: return datetime.datetime.now(datetime.timezone.utc)
def snapshot(row: dict[str, Any]) -> dict[str, Any]: return {key: row[key] for key in FIELDS if key in row}
def digest(row: dict[str, Any]) -> str: return hashlib.sha256(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


class OrganizationSkillLifecycle:
    async def initialize(self, *, main_id: str, skill_id: str, draft: dict[str, Any]) -> None:
        await get_db().skills.update_one({"_id": skill_id, "main_id": main_id}, {"$set": {
            "authoring_mode": "platform", "publication_status": "draft", "draft": snapshot(draft),
            "draft_revision": 1, "has_unpublished_changes": True, "draft_updated_at": now(),
        }})

    async def save(self, *, main_id: str, skill_id: str, draft: dict[str, Any]) -> dict[str, Any]:
        db = get_db(); query = {"_id": skill_id, "main_id": main_id}; row = await db.skills.find_one(query)
        if row is None: raise LookupError("技能不存在")
        baseline = await self._baseline(row)
        draft_data = snapshot(draft)
        await db.skills.update_one(query, {"$set": {**baseline, "authoring_mode": "platform", "draft": draft_data,
            "draft_revision": int(row.get("draft_revision") or 0) + 1, "draft_updated_at": now(),
            "has_unpublished_changes": digest(draft_data) != str(baseline.get("published_digest") or row.get("published_digest") or "")}})
        return await db.skills.find_one(query) or row

    async def publish(self, *, main_id: str, skill_id: str, version: str = "", notes: str = "") -> tuple[dict[str, Any], dict[str, Any]]:
        db = get_db(); query = {"_id": skill_id, "main_id": main_id}; row = await db.skills.find_one(query)
        if row is None: raise LookupError("技能不存在")
        draft = dict(row.get("draft") or snapshot(row)); current = str(row.get("published_version") or "")
        next_version = self._version(version) if version else self._next(current)
        if await db[RELEASE_COLLECTION].find_one({"main_id": main_id, "skill_id": skill_id, "version": next_version}):
            raise FileExistsError("该版本号已存在")
        stamp = now(); release = {"_id": uuid.uuid4().hex, "main_id": main_id, "skill_id": skill_id,
            "version": next_version, "digest": digest(draft), "snapshot": draft, "release_notes": notes.strip()[:2000], "created_at": stamp}
        await db[RELEASE_COLLECTION].insert_one(release)
        await db.skills.update_one(query, {"$set": {**draft, "publication_status": "published", "published_version": next_version,
            "published_digest": release["digest"], "published_release_id": release["_id"], "published_at": stamp,
            "draft": draft, "has_unpublished_changes": False, "updated_at": stamp}})
        return await db.skills.find_one(query) or row, release

    async def releases(self, *, main_id: str, skill_id: str) -> list[dict[str, Any]]:
        db = get_db(); query = {"_id": skill_id, "main_id": main_id}; skill = await db.skills.find_one(query)
        if skill is None: raise LookupError("技能不存在")
        baseline = await self._baseline(skill)
        if baseline: await db.skills.update_one(query, {"$set": baseline})
        rows = await db[RELEASE_COLLECTION].find({"main_id": main_id, "skill_id": skill_id}).sort("created_at", -1).limit(20).to_list(length=20)
        return [{"id": str(row["_id"]), "version": str(row["version"]), "releaseNotes": str(row.get("release_notes") or ""), "createdAt": row["created_at"].isoformat()} for row in rows]

    async def _baseline(self, row: dict[str, Any]) -> dict[str, Any]:
        if row.get("publication_status") == "draft" and not row.get("published_version"): return {}
        if row.get("published_version") and row.get("published_digest"): return {}
        db = get_db(); data = snapshot(row); release = {"_id": uuid.uuid4().hex, "main_id": row["main_id"], "skill_id": row["_id"],
            "version": "1.0.0", "digest": digest(data), "snapshot": data, "release_notes": "", "created_at": row.get("created_at") or now(), "migrated": True}
        existing = await db[RELEASE_COLLECTION].find_one({"main_id": row["main_id"], "skill_id": row["_id"], "version": "1.0.0"})
        if existing: release = existing
        else: await db[RELEASE_COLLECTION].insert_one(release)
        return {"publication_status": "published", "published_version": "1.0.0", "published_digest": release["digest"], "published_release_id": release["_id"]}

    @staticmethod
    def view(row: dict[str, Any]) -> dict[str, Any]:
        packaged = bool(row.get("package_id"))
        version = str(row.get("package_version") or "") if packaged else str(row.get("published_version") or ("1.0.0" if row.get("authoring_mode") != "platform" else ""))
        return {"authoringMode": "package" if packaged else "platform", "publicationStatus": "package" if packaged else str(row.get("publication_status") or ("published" if version else "draft")),
            "publishedVersion": version or str(row.get("package_version") or ""), "publishedReleaseId": str(row.get("published_release_id") or ""),
            "draftRevision": int(row.get("draft_revision") or 0), "hasUnpublishedChanges": bool(row.get("has_unpublished_changes"))}

    @staticmethod
    def display(row: dict[str, Any]) -> dict[str, Any]: return {**row, **dict(row.get("draft") or {})} if row.get("authoring_mode") == "platform" else row
    @staticmethod
    def _version(value: str) -> str:
        result = value.strip().lstrip("v")
        if not re.fullmatch(r"\d+\.\d+\.\d+", result): raise ValueError("版本号应为 1.2.0 格式")
        return result
    @classmethod
    def _next(cls, current: str) -> str:
        if not current: return "1.0.0"
        major, minor, patch = map(int, cls._version(current).split(".")); return f"{major}.{minor}.{patch + 1}"
