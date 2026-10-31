"""Resolve a Runtime-reported Skill against the published execution profile."""

from __future__ import annotations

from typing import Any


def invoked_skill_source_id(profile: Any, skill_name: str) -> str:
    for skill in profile.skills:
        if skill.name == skill_name:
            return skill.source_id
    raise ValueError("Invoked Skill is absent from the authorized Runtime Profile")
