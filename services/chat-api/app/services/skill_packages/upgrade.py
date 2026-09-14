from __future__ import annotations

import re
from typing import Any, Literal

from app.core.db import get_db
from app.core.tenant import resolve_main_id

from .validator import ValidatedSkillPackage


UpgradeAction = Literal["install", "duplicate", "upgrade", "replace", "downgrade"]


class SkillPackageUpgradeInspector:
    async def inspect(
        self,
        package: ValidatedSkillPackage,
        *,
        scope: Literal["personal", "organization"],
        main_id: str,
        user_id: str = "",
    ) -> dict[str, Any]:
        query: dict[str, Any] = {
            "main_id": resolve_main_id(main_id), "package_slug": package.name,
        }
        if scope == "personal":
            query["user_id"] = str(user_id)
        current = await (get_db().user_skills if scope == "personal" else get_db().skills).find_one(query)
        if current is None:
            return self._view("install", package, None)
        if str(current.get("package_digest") or "") == package.archive_digest:
            return self._view("duplicate", package, current)
        comparison = self._compare_versions(package.version, str(current.get("package_version") or ""))
        action: UpgradeAction = "upgrade" if comparison > 0 else "downgrade" if comparison < 0 else "replace"
        return self._view(action, package, current)

    @staticmethod
    def requires_confirmation(result: dict[str, Any]) -> bool:
        return str(result.get("action") or "") in {"upgrade", "replace", "downgrade"}

    @staticmethod
    def _view(action: UpgradeAction, package: ValidatedSkillPackage, current: dict[str, Any] | None) -> dict[str, Any]:
        return {
            "action": action,
            "slug": package.name,
            "name": package.display_name,
            "currentVersion": str((current or {}).get("package_version") or ""),
            "incomingVersion": package.version,
            "currentDigest": str((current or {}).get("package_digest") or ""),
            "incomingDigest": package.archive_digest,
            "currentFileCount": len((current or {}).get("package_files") or []),
            "incomingFileCount": len(package.files),
            "preservesEnabledState": current is not None,
        }

    @staticmethod
    def _compare_versions(left: str, right: str) -> int:
        def parts(value: str) -> tuple[int, int, int] | None:
            match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?", str(value or "").strip())
            return tuple(int(match.group(index)) for index in range(1, 4)) if match else None
        left_parts, right_parts = parts(left), parts(right)
        if left_parts is None or right_parts is None:
            return 0
        return (left_parts > right_parts) - (left_parts < right_parts)
