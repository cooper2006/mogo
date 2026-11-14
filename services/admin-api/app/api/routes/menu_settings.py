"""055 菜单管理 —— admin-web 侧边栏展示配置端点。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.api.deps import get_current_admin_user
from app.menu_settings.models import (
    MenuPlanPayload,
    MenuPlanResponse,
    MenuResetResponse,
)
from app.menu_settings.service import MenuSettingsService

router = APIRouter()
service = MenuSettingsService()


def _tenant_id(user: dict[str, Any]) -> str:
    return str(user.get("tenant_id") or "default")


def _admin_id(user: dict[str, Any]) -> str:
    return str(user.get("_id") or user.get("id") or "")


@router.get("", response_model=MenuPlanResponse)
async def get_menu_settings(current_user: dict = Depends(get_current_admin_user)):
    return await service.get_plan(_tenant_id(current_user))


@router.put("", response_model=MenuPlanResponse)
async def save_menu_settings(
    payload: MenuPlanPayload, current_user: dict = Depends(get_current_admin_user)
):
    return await service.save_plan(_tenant_id(current_user), _admin_id(current_user), payload)


@router.delete("", response_model=MenuResetResponse)
async def reset_menu_settings(current_user: dict = Depends(get_current_admin_user)):
    await service.delete_plan(_tenant_id(current_user))
    return MenuResetResponse()
