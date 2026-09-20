from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.api.deps import get_current_admin_user
from app.shortcut_settings.models import ShortcutPlanPayload
from app.shortcut_settings.service import ShortcutSettingsService


router = APIRouter()
service = ShortcutSettingsService()


def _main_id(user: dict[str, Any]) -> str:
    return str(user.get("main_id") or "default")


@router.get("")
async def get_shortcut_settings(current_user: dict = Depends(get_current_admin_user)):
    return await service.get_default_plan(_main_id(current_user))


@router.put("")
async def save_shortcut_settings(payload: ShortcutPlanPayload, current_user: dict = Depends(get_current_admin_user)):
    return await service.save_default_plan(
        _main_id(current_user),
        str(current_user.get("_id") or current_user.get("id") or ""),
        payload,
    )
