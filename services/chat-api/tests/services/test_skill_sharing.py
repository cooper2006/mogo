from __future__ import annotations

import asyncio
import base64
import datetime
import io
import zipfile

import pytest

from app.services.skill_packages import validate_skill_package
from app.services.skill_packages import installer as installer_module
from app.services.skill_sharing import SkillShareError, SkillShareService
from app.services.skill_sharing import service as service_module
from app.services.skill_sharing import distribution as distribution_module
from app.services.skill_sharing.exporter import SkillShareExporter
from app.enterprise_capabilities.content.styles import is_writing_style


def _matches(row, query):
    if "$and" in query:
        return all(_matches(row, part) for part in query["$and"])
    return all(row.get(key) == value for key, value in query.items())


class Result:
    def __init__(self, matched_count=1):
        self.matched_count = matched_count


class Collection:
    def __init__(self):
        self.rows = {}

    async def find_one(self, query, projection=None):
        for row in self.rows.values():
            if _matches(row, query):
                if projection:
                    return {key: row.get(key) for key in projection if key in row}
                return dict(row)
        return None

    async def insert_one(self, row):
        self.rows[row["_id"]] = dict(row)

    async def update_one(self, query, update):
        row = await self.find_one(query)
        if row is None:
            return Result(0)
        row.update(update["$set"])
        self.rows[row["_id"]] = row
        return Result(1)

    async def delete_one(self, query):
        row = await self.find_one(query)
        if row:
            self.rows.pop(row["_id"], None)

    async def delete_many(self, query):
        for key, row in list(self.rows.items()):
            values = query.get("_id", {}).get("$in", [])
            if row.get("_id") in values:
                self.rows.pop(key, None)


class Database:
    def __init__(self):
        self.user_skills = Collection()
        self.skill_packages = Collection()
        self.skill_shares = Collection()
        self.skill_distributions = Collection()
        self.skill_distribution_releases = Collection()
        self.skill_distribution_members = Collection()
        self.skill_update_notifications = Collection()
        self.skills = Collection()

    def __getitem__(self, name):
        return getattr(self, name)


def _archive(name="package-skill", version="1.0.0", body="Use the shared instructions."):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr(
            "SKILL.md",
            f"---\nname: {name}\ndisplayName: Package Skill\ndescription: Package description\nversion: {version}\n---\n{body}\n",
        )
    return output.getvalue()


def _install_db(monkeypatch, db):
    monkeypatch.setattr(service_module, "get_db", lambda: db)
    monkeypatch.setattr(distribution_module, "get_db", lambda: db)
    monkeypatch.setattr(installer_module, "get_db", lambda: db)


def test_generated_skill_share_installs_an_independent_profile(monkeypatch):
    db = Database()
    _install_db(monkeypatch, db)
    original_markdown = "---\nname: 招生写作规范\nskill_type: style\n---\n# Rules\nUse verified facts."
    db.user_skills.rows["source"] = {
        "_id": "source", "main_id": "tenant", "user_id": "owner",
        "name": "招生写作规范", "description": "学校招生内容规范", "scenario": "撰写招生内容",
        "type": "writing_style", "skill_type": "style", "role": "style",
        "skill_markdown": original_markdown,
        "config": {"styleNotes": "Use verified facts", "api_key": "must-not-be-shared"},
        "enabled": True, "is_active": True,
    }
    service = SkillShareService()
    created = asyncio.run(service.create(
        main_id="tenant", owner_user_id="owner", skill_id="source", expires_in_days=30,
    ))
    preview = asyncio.run(service.preview(
        main_id="tenant", recipient_user_id="recipient", token=created["token"],
    ))
    installed = asyncio.run(service.install(
        main_id="tenant", recipient_user_id="recipient", token=created["token"],
    ))

    recipient = next(row for row in db.user_skills.rows.values() if row.get("user_id") == "recipient")
    assert preview["name"] == "招生写作规范"
    assert preview["hasConflict"] is False
    assert installed["type"] == "writing_style"
    assert recipient["skill_markdown"] == original_markdown
    assert recipient["config"] == {"styleNotes": "Use verified facts"}
    assert is_writing_style(recipient) is True
    assert recipient["visibility"] == "private"
    assert recipient["package_source"]["kind"] == "movo_share"
    assert db.user_skills.rows["source"]["user_id"] == "owner"
    repeated = asyncio.run(service.install(
        main_id="tenant", recipient_user_id="recipient", token=created["token"],
    ))
    assert repeated["duplicate"] is True
    assert len([row for row in db.user_skills.rows.values() if row.get("user_id") == "recipient"]) == 1


def test_packaged_skill_share_reuses_validated_archive(monkeypatch):
    db = Database()
    archive = _archive()
    package = validate_skill_package(archive)
    db.user_skills.rows["source"] = {
        "_id": "source", "main_id": "tenant", "user_id": "owner", "name": "Package Skill",
        "description": "Package description", "type": "ordinary", "skill_type": "execution",
        "package_id": "package", "package_slug": package.name, "package_digest": package.archive_digest,
    }
    db.skill_packages.rows["package"] = {
        "_id": "package", "main_id": "tenant", "owner_scope": "personal", "owner_id": "owner",
        "archive_base64": base64.b64encode(archive).decode("ascii"),
    }

    snapshot = asyncio.run(SkillShareExporter().export(db, db.user_skills.rows["source"]))
    assert snapshot.package.archive_digest == package.archive_digest
    assert snapshot.package.markdown == "Use the shared instructions.\n"


def test_share_is_tenant_scoped_and_can_be_revoked(monkeypatch):
    db = Database()
    _install_db(monkeypatch, db)
    db.user_skills.rows["source"] = {
        "_id": "source", "main_id": "tenant-a", "user_id": "owner",
        "name": "Simple", "description": "Simple skill", "skill_markdown": "Do the task.",
    }
    service = SkillShareService()
    created = asyncio.run(service.create(main_id="tenant-a", owner_user_id="owner", skill_id="source"))

    with pytest.raises(SkillShareError) as cross_tenant:
        asyncio.run(service.preview(main_id="tenant-b", recipient_user_id="user", token=created["token"]))
    assert cross_tenant.value.code == "skill_share_unavailable"

    asyncio.run(service.revoke(
        main_id="tenant-a", owner_user_id="owner", skill_id="source", share_id=created["shareId"],
    ))
    with pytest.raises(SkillShareError) as revoked:
        asyncio.run(service.preview(main_id="tenant-a", recipient_user_id="user", token=created["token"]))
    assert revoked.value.code == "skill_share_unavailable"


def test_expired_share_and_conflicting_install_fail_closed(monkeypatch):
    db = Database()
    _install_db(monkeypatch, db)
    db.user_skills.rows["source"] = {
        "_id": "source", "main_id": "tenant", "user_id": "owner",
        "name": "Conflict Skill", "description": "Shared", "skill_markdown": "Shared instructions.",
    }
    service = SkillShareService()
    created = asyncio.run(service.create(main_id="tenant", owner_user_id="owner", skill_id="source"))
    share = db.skill_shares.rows[created["shareId"]]
    slug = share["package"]["slug"]
    db.user_skills.rows["existing"] = {
        "_id": "existing", "main_id": "tenant", "user_id": "recipient",
        "package_slug": slug, "package_digest": "different", "source_kind": "zip",
    }
    preview = asyncio.run(service.preview(main_id="tenant", recipient_user_id="recipient", token=created["token"]))
    assert preview["hasConflict"] is True
    with pytest.raises(SkillShareError) as conflict:
        asyncio.run(service.install(main_id="tenant", recipient_user_id="recipient", token=created["token"]))
    assert conflict.value.code == "skill_share_conflict"

    replaced = asyncio.run(service.install(
        main_id="tenant", recipient_user_id="recipient", token=created["token"], replace_existing=True,
    ))
    assert replaced["id"] == "existing"
    assert db.user_skills.rows["existing"]["name"] == "Conflict Skill"

    share["expires_at"] = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=1)
    with pytest.raises(SkillShareError) as expired:
        asyncio.run(service.preview(main_id="tenant", recipient_user_id="another", token=created["token"]))
    assert expired.value.code == "skill_share_expired"
