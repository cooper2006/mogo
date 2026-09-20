from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class ShortcutEntry(BaseModel):
    id: str = Field(min_length=1, max_length=120)
    type: Literal["prompt", "skill", "agent"] = "prompt"
    categoryKey: str = Field(min_length=1, max_length=80)
    categoryLabel: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=80)
    iconKey: str = Field(default="document", max_length=40)
    iconSvg: str = Field(default="", max_length=20000)
    categoryIconKey: str = Field(default="grid", max_length=40)
    categoryIconSvg: str = Field(default="", max_length=20000)
    prompt: str = Field(default="", max_length=8000)
    resourceId: str = Field(default="", max_length=160)
    enabled: bool = True
    locked: bool = False

    @field_validator("id", "categoryKey", "categoryLabel", "label", "iconKey", "prompt", "resourceId")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("iconSvg", "categoryIconSvg")
    @classmethod
    def validate_svg(cls, value: str) -> str:
        value = value.strip()
        if value and (not value.startswith("<svg") or "<script" in value.lower() or "<foreignobject" in value.lower() or re.search(r"\son[a-z]+\s*=", value, re.I) or "javascript:" in value.lower()):
            raise ValueError("invalid_shortcut_icon_svg")
        return value

    @model_validator(mode="after")
    def locked_entries_are_visible(self) -> "ShortcutEntry":
        if self.locked:
            self.enabled = True
        return self


class ShortcutGroup(BaseModel):
    key: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=80)
    iconKey: str = Field(default="grid", max_length=40)
    iconSvg: str = Field(default="", max_length=20000)
    locked: bool = False

    @field_validator("key", "label", "iconKey", "iconSvg")
    @classmethod
    def strip_group_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("iconSvg")
    @classmethod
    def validate_group_svg(cls, value: str) -> str:
        if value and (not value.startswith("<svg") or "<script" in value.lower() or "<foreignobject" in value.lower() or re.search(r"\son[a-z]+\s*=", value, re.I) or "javascript:" in value.lower()):
            raise ValueError("invalid_shortcut_icon_svg")
        return value


class ShortcutCustomIcon(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    value: str = Field(min_length=1, max_length=120)
    svg: str = Field(min_length=1, max_length=20000)

    @field_validator("label", "value", "svg")
    @classmethod
    def strip_icon_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("svg")
    @classmethod
    def validate_icon_svg(cls, value: str) -> str:
        if not value.startswith("<svg") or "<script" in value.lower() or "<foreignobject" in value.lower() or re.search(r"\son[a-z]+\s*=", value, re.I) or "javascript:" in value.lower():
            raise ValueError("invalid_shortcut_icon_svg")
        return value


class ShortcutPlanPayload(BaseModel):
    name: str = Field(default="企业默认方案", min_length=1, max_length=80)
    entries: list[ShortcutEntry] = Field(default_factory=list, max_length=100)
    groups: list[ShortcutGroup] = Field(default_factory=list, max_length=6)
    customIcons: list[ShortcutCustomIcon] = Field(default_factory=list, max_length=100)

    @field_validator("entries")
    @classmethod
    def unique_entries(cls, entries: list[ShortcutEntry]) -> list[ShortcutEntry]:
        ids = [item.id for item in entries]
        if len(ids) != len(set(ids)):
            raise ValueError("shortcut_entry_ids_must_be_unique")
        return entries

    @field_validator("groups")
    @classmethod
    def unique_groups(cls, groups: list[ShortcutGroup]) -> list[ShortcutGroup]:
        keys = [item.key for item in groups]
        if len(keys) != len(set(keys)):
            raise ValueError("shortcut_group_keys_must_be_unique")
        return groups

    @field_validator("customIcons")
    @classmethod
    def unique_custom_icons(cls, icons: list[ShortcutCustomIcon]) -> list[ShortcutCustomIcon]:
        values = [item.value for item in icons]
        if len(values) != len(set(values)):
            raise ValueError("shortcut_custom_icon_values_must_be_unique")
        return icons

    @model_validator(mode="after")
    def limit_entries_per_group(self) -> "ShortcutPlanPayload":
        counts: dict[str, int] = {}
        for entry in self.entries:
            counts[entry.categoryKey] = counts.get(entry.categoryKey, 0) + 1
        if any(count > 6 for count in counts.values()):
            raise ValueError("shortcut_group_entries_limit_exceeded")
        return self
