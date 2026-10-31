"""Keep an active Skill version available while its replacement prepares."""

from __future__ import annotations

from typing import Any
import logging

from app.core.db import get_db


LOG = logging.getLogger(__name__)


async def promote_if_ready(skill: dict[str, Any]) -> None:
    pending = skill.get("pending_package")
    if not isinstance(pending, dict) or not pending.get("digest"):
        return
    fields = pending.get("fields")
    if not isinstance(fields, dict):
        return
    personal = skill.get("user_id") and skill.get("user_id") != "organization"
    collection = get_db().user_skills if personal else get_db().skills
    skill_id = str(skill.get("_id") or skill.get("id") or "")
    if not personal:
        skill_id = skill_id.removeprefix("org_skill:")
    query = {"_id": skill_id, "pending_package.digest": pending["digest"]}
    result = await collection.update_one(query, {"$set": fields, "$unset": {"pending_package": ""}})
    if result.matched_count:
        skill.update(fields)
        skill.pop("pending_package", None)
        if personal:
            try:
                from app.services.skill_sharing.distribution import SkillDistributionService
                await SkillDistributionService().publish_from_skill(
                    main_id=str(skill.get("main_id") or "default"),
                    owner_user_id=str(skill["user_id"]),
                    source_skill_id=str(skill.get("_id") or skill.get("id")),
                    version=str(fields.get("package_version") or ""),
                )
            except Exception:
                LOG.exception("Skill distribution update failed after package promotion")
