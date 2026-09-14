from __future__ import annotations

import datetime
import hashlib
import json
import re
import uuid
from typing import Any

from app.core.db import get_db
from app.core.tenant import add_main_scope, resolve_main_id


RELEASE_COLLECTION = "skill_releases"
PLATFORM_TYPES = {"writing_style", "workflow"}
PUBLISH_FIELDS = (
    "name", "description", "scenario", "summary", "category", "role", "skill_type", "type",
    "config", "tags", "formats", "input_profile", "contract_json", "skill_markdown", "advanced",
    "notes", "execution_plane", "skill_contract_version", "skill_contract", "skill_lint_warnings",
    "model_invocable", "user_invocable",
)


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


class SkillLifecycleError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code

    def detail(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


class SkillLifecycleService:
    """Draft/publish boundary for platform-authored Skills.

    Published fields stay at the document root so the existing DSH catalog remains
    the runtime projection. Mutable authoring data lives under ``draft``.
    """

    async def initialize_draft(
        self, *, main_id: str, user_id: str, skill_id: str, draft: dict[str, Any], new_skill: bool,
    ) -> dict[str, Any]:
        db = get_db()
        scope = add_main_scope({"_id": skill_id, "user_id": str(user_id)}, main_id)
        row = await db.user_skills.find_one(scope)
        if row is None:
            raise SkillLifecycleError("skill_not_found", "Skill not found", status_code=404)
        now = _utcnow()
        update = {
            "authoring_mode": "platform",
            "publication_status": "draft" if new_skill else "published",
            "draft": self._snapshot(draft),
            "draft_revision": int(row.get("draft_revision") or 0) + 1,
            "draft_updated_at": now,
            "has_unpublished_changes": bool(new_skill),
        }
        if not new_skill:
            baseline = await self._ensure_baseline(row)
            update.update(baseline)
        await db.user_skills.update_one(scope, {"$set": update})
        return await db.user_skills.find_one(scope) or {**row, **update}

    async def save_draft(
        self, *, main_id: str, user_id: str, skill_id: str, draft: dict[str, Any],
    ) -> dict[str, Any]:
        db = get_db()
        scope = add_main_scope({"_id": skill_id, "user_id": str(user_id)}, main_id)
        row = await db.user_skills.find_one(scope)
        if row is None:
            raise SkillLifecycleError("skill_not_found", "Skill not found", status_code=404)
        if not self.is_platform_skill(row):
            raise SkillLifecycleError("skill_draft_unsupported", "Only platform-authored Skills have drafts")
        baseline = await self._ensure_baseline(row)
        draft_snapshot = self._snapshot(draft)
        published_digest = str(baseline.get("published_digest") or row.get("published_digest") or "")
        update = {
            **baseline,
            "authoring_mode": "platform",
            "draft": draft_snapshot,
            "draft_revision": int(row.get("draft_revision") or 0) + 1,
            "draft_updated_at": _utcnow(),
            "has_unpublished_changes": self._digest(draft_snapshot) != published_digest,
        }
        await db.user_skills.update_one(scope, {"$set": update})
        return await db.user_skills.find_one(scope) or {**row, **update}

    async def publish(
        self,
        *,
        main_id: str,
        user_id: str,
        skill_id: str,
        version: str = "",
        release_notes: str = "",
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        from app.services.skills import user_skill_service

        db = get_db()
        tenant_id = resolve_main_id(main_id)
        scope = add_main_scope({"_id": skill_id, "user_id": str(user_id)}, tenant_id)
        row = await db.user_skills.find_one(scope)
        if row is None:
            raise SkillLifecycleError("skill_not_found", "Skill not found", status_code=404)
        if not self.is_platform_skill(row):
            raise SkillLifecycleError("skill_publish_unsupported", "Only platform-authored Skills can be published")
        draft = dict(row.get("draft") or self._snapshot(row))
        if not str(draft.get("name") or "").strip():
            raise SkillLifecycleError("skill_publish_invalid", "Skill name is required")
        current_version = str(row.get("published_version") or "")
        next_version = self._normalize_version(version) if version else self._next_version(current_version)
        existing = await db[RELEASE_COLLECTION].find_one({
            "main_id": tenant_id, "skill_id": skill_id, "version": next_version,
        })
        if existing:
            raise SkillLifecycleError("skill_version_exists", "This Skill version already exists", status_code=409)
        updated = await user_skill_service.update_skill(user_id, skill_id, draft, main_id=tenant_id)
        if updated is None:
            raise SkillLifecycleError("skill_not_found", "Skill not found", status_code=404)
        published_snapshot = self._snapshot(updated)
        digest = self._digest(published_snapshot)
        now = _utcnow()
        release = {
            "_id": uuid.uuid4().hex,
            "main_id": tenant_id,
            "skill_id": skill_id,
            "owner_user_id": str(user_id),
            "version": next_version,
            "digest": digest,
            "snapshot": published_snapshot,
            "release_notes": str(release_notes or "").strip()[:2000],
            "created_at": now,
        }
        await db[RELEASE_COLLECTION].insert_one(release)
        lifecycle = {
            "authoring_mode": "platform",
            "publication_status": "published",
            "published_version": next_version,
            "published_digest": digest,
            "published_release_id": release["_id"],
            "published_at": now,
            "draft": published_snapshot,
            "has_unpublished_changes": False,
        }
        await db.user_skills.update_one(scope, {"$set": lifecycle})
        row = await db.user_skills.find_one(scope) or {**updated, **lifecycle}
        return row, release

    async def list_releases(
        self, *, main_id: str, user_id: str, skill_id: str, limit: int = 20,
    ) -> list[dict[str, Any]]:
        db = get_db()
        tenant_id = resolve_main_id(main_id)
        owner_scope = add_main_scope({
            "_id": skill_id, "user_id": str(user_id),
        }, tenant_id)
        owner = await db.user_skills.find_one(owner_scope)
        if owner is None:
            raise SkillLifecycleError("skill_not_found", "Skill not found", status_code=404)
        baseline = await self._ensure_baseline(owner)
        if baseline:
            await db.user_skills.update_one(owner_scope, {"$set": baseline})
        rows = await db[RELEASE_COLLECTION].find({
            "main_id": tenant_id, "skill_id": skill_id,
        }).sort("created_at", -1).limit(min(max(limit, 1), 50)).to_list(length=min(max(limit, 1), 50))
        return [self.release_view(row) for row in rows]

    async def _ensure_baseline(self, row: dict[str, Any]) -> dict[str, Any]:
        if row.get("publication_status") == "draft" and not row.get("published_version"):
            return {}
        if row.get("published_version") and row.get("published_digest"):
            return {}
        db = get_db()
        snapshot = self._snapshot(row)
        digest = self._digest(snapshot)
        tenant_id = resolve_main_id(row.get("main_id"))
        skill_id = str(row.get("_id") or "")
        release = await db[RELEASE_COLLECTION].find_one({
            "main_id": tenant_id, "skill_id": skill_id, "version": "1.0.0",
        })
        if release is None:
            release = {
                "_id": uuid.uuid4().hex,
                "main_id": tenant_id,
                "skill_id": skill_id,
                "owner_user_id": str(row.get("user_id") or ""),
                "version": "1.0.0",
                "digest": digest,
                "snapshot": snapshot,
                "release_notes": "",
                "created_at": row.get("created_at") or _utcnow(),
                "migrated": True,
            }
            await db[RELEASE_COLLECTION].insert_one(release)
        return {
            "publication_status": "published",
            "published_version": "1.0.0",
            "published_digest": digest,
            "published_release_id": str(release.get("_id") or ""),
            "published_at": row.get("updated_at") or row.get("created_at") or _utcnow(),
        }

    @staticmethod
    def is_platform_skill(row: dict[str, Any]) -> bool:
        if row.get("package_id"):
            return False
        raw_type = str(row.get("type") or "").strip().lower()
        skill_type = str(row.get("skill_type") or "").strip().lower()
        return raw_type in PLATFORM_TYPES or skill_type in {"style", "writing_style", "workflow", "composite_task"}

    @staticmethod
    def lifecycle_view(row: dict[str, Any]) -> dict[str, Any]:
        platform = SkillLifecycleService.is_platform_skill(row)
        published_version = str(row.get("published_version") or ("1.0.0" if platform and row.get("publication_status") != "draft" else ""))
        return {
            "authoringMode": "platform" if platform else "package",
            "publicationStatus": str(row.get("publication_status") or ("published" if published_version else "package")),
            "publishedVersion": published_version or str(row.get("package_version") or ""),
            "publishedReleaseId": str(row.get("published_release_id") or ""),
            "draftRevision": int(row.get("draft_revision") or 0),
            "hasUnpublishedChanges": bool(row.get("has_unpublished_changes", False)),
        }

    @staticmethod
    def display_snapshot(row: dict[str, Any]) -> dict[str, Any]:
        if SkillLifecycleService.is_platform_skill(row) and isinstance(row.get("draft"), dict):
            return {**row, **dict(row["draft"])}
        return row

    @staticmethod
    def release_view(row: dict[str, Any]) -> dict[str, Any]:
        created = row.get("created_at")
        return {
            "id": str(row.get("_id") or ""),
            "version": str(row.get("version") or ""),
            "digest": str(row.get("digest") or ""),
            "releaseNotes": str(row.get("release_notes") or ""),
            "createdAt": created.isoformat() if isinstance(created, datetime.datetime) else "",
        }

    @staticmethod
    def _snapshot(row: dict[str, Any]) -> dict[str, Any]:
        return {key: row[key] for key in PUBLISH_FIELDS if key in row}

    @staticmethod
    def _digest(snapshot: dict[str, Any]) -> str:
        encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @staticmethod
    def _normalize_version(value: str) -> str:
        version = str(value or "").strip().lstrip("v")
        if not re.fullmatch(r"\d+\.\d+\.\d+", version):
            raise SkillLifecycleError("skill_version_invalid", "Version must use semantic version format, for example 1.2.0")
        return version

    @classmethod
    def _next_version(cls, current: str) -> str:
        if not current:
            return "1.0.0"
        version = cls._normalize_version(current)
        major, minor, patch = (int(item) for item in version.split("."))
        return f"{major}.{minor}.{patch + 1}"
