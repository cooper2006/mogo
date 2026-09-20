from __future__ import annotations

import re
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator

from app.api.principal import ApiPrincipal, require_end_user_principal
from app.services.shortcuts import ShortcutService


router = APIRouter(dependencies=[Depends(require_end_user_principal)])
service = ShortcutService()


class PersonalShortcutEntry(BaseModel):
    id: str = Field(min_length=1, max_length=120)
    type: Literal["prompt", "skill"] = "prompt"
    categoryKey: str = Field(default="personal", min_length=1, max_length=80)
    categoryLabel: str = Field(default="我的常用", min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=80)
    iconKey: str = Field(default="document", max_length=40)
    iconSvg: str = Field(default="", max_length=20000)
    categoryIconKey: str = Field(default="grid", max_length=40)
    categoryIconSvg: str = Field(default="", max_length=20000)
    prompt: str = Field(default="", max_length=8000)
    resourceId: str = Field(default="", max_length=160)

    @field_validator("iconSvg", "categoryIconSvg")
    @classmethod
    def validate_svg(cls, value: str) -> str:
        value = value.strip()
        if value and (not value.startswith("<svg") or "<script" in value.lower() or "<foreignobject" in value.lower() or re.search(r"\son[a-z]+\s*=", value, re.I) or "javascript:" in value.lower()):
            raise ValueError("invalid_shortcut_icon_svg")
        return value


class PersonalShortcutGroup(BaseModel):
    key: Literal["personal"] = "personal"
    label: str = Field(default="我的常用", min_length=1, max_length=80)
    iconKey: str = Field(default="grid", max_length=40)
    iconSvg: str = Field(default="", max_length=20000)

    @field_validator("iconSvg")
    @classmethod
    def validate_svg(cls, value: str) -> str:
        return PersonalShortcutEntry.validate_svg(value)


class ShortcutPreferencePayload(BaseModel):
    groupOrders: dict[str, list[str]] = Field(default_factory=dict)
    personalGroup: PersonalShortcutGroup | None = None
    personalEntries: list[PersonalShortcutEntry] = Field(default_factory=list, max_length=6)

    @field_validator("groupOrders")
    @classmethod
    def limit_orders(cls, value: dict[str, list[str]]) -> dict[str, list[str]]:
        if len(value) > 7 or any(len(items) > 6 for items in value.values()):
            raise ValueError("shortcut_group_order_limit_exceeded")
        return value


@router.get("/shortcuts")
async def get_shortcuts(principal: ApiPrincipal = Depends(require_end_user_principal)):
    return {"code": 0, "data": await service.effective(principal.main_id, principal.user_id)}


@router.put("/shortcuts/preferences")
async def save_shortcut_preferences(payload: ShortcutPreferencePayload, principal: ApiPrincipal = Depends(require_end_user_principal)):
    return {"code": 0, "data": await service.save_preferences(principal.main_id, principal.user_id, payload.model_dump())}
