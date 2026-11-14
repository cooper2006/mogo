"""055 菜单管理 —— 请求 / 响应模型与校验。

覆盖层节点只描述「展示元数据」，不含 path 到 component 的映射：
菜单树由前端静态 ``appRoutes`` 提供，配置里出现未知 key 最多被丢弃，
不可能凭空造出一条可访问的路由（见 055 spec 安全边界）。
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.menu_settings.catalog import ICON_KEYS, KNOWN_GROUP_KEYS, LOCKED_KEYS

KEY_PATTERN = re.compile(r"^/[A-Za-z0-9_/:.\-]*$")
ALLOWED_LABEL_LOCALES = frozenset({"zh-CN", "en-US"})


def validate_menu_key(value: str) -> str:
    value = value.strip()
    if not KEY_PATTERN.fullmatch(value):
        raise ValueError("invalid_menu_key")
    if "//" in value or ".." in value:
        raise ValueError("invalid_menu_key")
    return value


class MenuNode(BaseModel):
    key: str = Field(min_length=1, max_length=160)
    parentKey: str | None = Field(default=None, max_length=160)
    label: dict[str, str] | None = None
    iconKey: str | None = Field(default=None, max_length=40)
    visible: bool | None = None
    order: int | None = Field(default=None, ge=-1000, le=1000)
    locked: bool = False

    @field_validator("key")
    @classmethod
    def check_key(cls, value: str) -> str:
        return validate_menu_key(value)

    @field_validator("parentKey")
    @classmethod
    def check_parent_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = validate_menu_key(value)
        if value not in KNOWN_GROUP_KEYS:
            raise ValueError("menu_parent_key_not_a_group")
        return value

    @field_validator("iconKey")
    @classmethod
    def check_icon_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if value and value not in ICON_KEYS:
            raise ValueError("invalid_menu_icon_key")
        return value or None

    @field_validator("label")
    @classmethod
    def check_label(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        if value is None:
            return None
        if set(value) - ALLOWED_LABEL_LOCALES:
            raise ValueError("invalid_menu_label_locale")
        cleaned: dict[str, str] = {}
        for locale, text in value.items():
            item = str(text).strip()
            if len(item) > 80:
                raise ValueError("menu_label_too_long")
            if item:
                cleaned[locale] = item
        return cleaned or None

    @model_validator(mode="after")
    def check_hierarchy_and_lock(self) -> "MenuNode":
        # 分组节点不能挂到别的分组下；非分组节点必须明确所属分组，杜绝环与跨组挂接。
        if self.key in KNOWN_GROUP_KEYS:
            if self.parentKey is not None:
                raise ValueError("menu_group_cannot_have_parent")
        elif self.parentKey is None:
            # 一级单项（/dashboard、/settings 等）允许 parentKey=None。
            # 由前端合并层按静态树判定它是否真的是一级项，未知 key 会被丢弃。
            pass
        if self.locked or self.key in LOCKED_KEYS:
            self.locked = True
            self.visible = True
        return self


class MenuPlanPayload(BaseModel):
    schemeKey: Literal["default"] = "default"
    nodes: list[MenuNode] = Field(default_factory=list, max_length=200)

    @field_validator("nodes")
    @classmethod
    def unique_keys(cls, nodes: list[MenuNode]) -> list[MenuNode]:
        keys = [item.key for item in nodes]
        if len(keys) != len(set(keys)):
            raise ValueError("menu_node_keys_must_be_unique")
        return nodes


class MenuPlanResponse(BaseModel):
    id: str = "default"
    schemeKey: str = "default"
    version: int = 1
    nodes: list[MenuNode] = Field(default_factory=list)
    updatedAt: str = ""
    updatedBy: str = ""


class MenuResetResponse(BaseModel):
    ok: bool = True
    schemeKey: str = "default"


def node_from_row(row: dict[str, Any]) -> MenuNode | None:
    """把库里的单条节点安全转成模型；坏数据跳过而不是让整个侧边栏 500。"""
    try:
        return MenuNode.model_validate(row)
    except Exception:  # noqa: BLE001 - 容错读取，坏数据不允许拖垮菜单
        return None
