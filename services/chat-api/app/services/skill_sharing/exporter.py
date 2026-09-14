from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import zipfile
from dataclasses import dataclass
from typing import Any

import yaml

from app.services.skill_packages import SkillPackageError, ValidatedSkillPackage, validate_skill_package


@dataclass(frozen=True)
class ShareSnapshot:
    package: ValidatedSkillPackage
    profile: dict[str, Any]


PROFILE_FIELDS = (
    "name", "description", "scenario", "summary", "category", "role", "skill_type", "type",
    "config", "tags", "formats", "input_profile", "contract_json", "skill_markdown", "advanced",
    "notes", "execution_plane", "skill_contract_version", "skill_contract", "skill_lint_warnings",
    "model_invocable", "user_invocable",
)


class SkillShareExporter:
    async def export(self, db: Any, skill: dict[str, Any]) -> ShareSnapshot:
        package_id = str(skill.get("package_id") or "").strip()
        if package_id:
            package_row = await db.skill_packages.find_one({
                "_id": package_id,
                "main_id": str(skill.get("main_id") or "default"),
                "owner_scope": "personal",
                "owner_id": str(skill.get("user_id") or ""),
            })
            if package_row is None:
                raise SkillPackageError("share_package_missing", "The Skill package archive is unavailable")
            try:
                archive = base64.b64decode(str(package_row.get("archive_base64") or ""), validate=True)
            except (ValueError, TypeError) as exc:
                raise SkillPackageError("share_package_invalid", "The Skill package archive is invalid") from exc
            package = validate_skill_package(archive)
        else:
            archive = self._generated_archive(skill)
            package = validate_skill_package(archive)
        return ShareSnapshot(package=package, profile=self._profile(skill))

    @staticmethod
    def _profile(skill: dict[str, Any]) -> dict[str, Any]:
        profile = {key: SkillShareExporter._without_secrets(skill[key]) for key in PROFILE_FIELDS if key in skill}
        raw_type = str(profile.get("type") or "").strip().lower()
        skill_type = str(profile.get("skill_type") or "").strip().lower()
        if raw_type not in {"writing_style", "workflow", "ordinary", "expert_package"}:
            if skill_type in {"style", "writing_style"}:
                raw_type = "writing_style"
            elif skill_type in {"workflow", "composite", "composite_task"}:
                raw_type = "workflow"
            elif skill_type == "expert_package":
                raw_type = "expert_package"
            else:
                raw_type = "ordinary"
        profile["type"] = raw_type
        # Owner, object-store paths and mutable database identity never cross the share boundary.
        profile["visibility"] = "private"
        return profile

    @staticmethod
    def _without_secrets(value: Any) -> Any:
        secret_keys = {
            "api_key", "apikey", "api_secret", "secret", "password", "access_token",
            "refresh_token", "authorization", "credential", "credentials",
        }
        if isinstance(value, dict):
            return {
                key: SkillShareExporter._without_secrets(item)
                for key, item in value.items()
                if str(key).strip().lower() not in secret_keys
            }
        if isinstance(value, list):
            return [SkillShareExporter._without_secrets(item) for item in value]
        if isinstance(value, tuple):
            return [SkillShareExporter._without_secrets(item) for item in value]
        return value

    def _generated_archive(self, skill: dict[str, Any]) -> bytes:
        source_id = str(skill.get("_id") or "skill")
        display_name = str(skill.get("name") or "Shared Skill").strip()[:256]
        description = str(skill.get("description") or skill.get("summary") or display_name).strip()[:2000]
        slug = self._slug(str(skill.get("package_slug") or display_name), source_id)
        version = str(skill.get("published_version") or "1.0.0").strip() or "1.0.0"
        body = str(skill.get("skill_markdown") or "").strip()
        if not body:
            body = f"# {display_name}\n\n{description}\n"
        metadata = {
            "name": slug,
            "displayName": display_name,
            "description": description,
            "version": version,
            "whenToUse": str(skill.get("scenario") or skill.get("notes") or description).strip()[:4000],
            "disable-model-invocation": not bool(skill.get("model_invocable", True)),
            "user-invocable": bool(skill.get("user_invocable", True)),
        }
        markdown = f"---\n{yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False).strip()}\n---\n\n{body}\n"
        files = {
            "SKILL.md": markdown.encode("utf-8"),
            "_meta.json": json.dumps({"slug": slug, "version": version}, ensure_ascii=False, sort_keys=True).encode("utf-8"),
        }
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            for path, content in sorted(files.items()):
                info = zipfile.ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o600 << 16
                archive.writestr(info, content)
        return output.getvalue()

    @staticmethod
    def _slug(name: str, source_id: str) -> str:
        value = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        if not value:
            value = f"shared-skill-{hashlib.sha256(source_id.encode()).hexdigest()[:12]}"
        return value[:126].rstrip("-")
