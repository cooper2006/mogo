"""055 菜单管理 —— 后端侧稳定常量。

这里**只放不随业务页面增减而漂移的少量常量**：一级分组 key、图标枚举、
强制锁定节点。完整的菜单节点清单由前端 ``appRoutes`` 静态派生，
后端不复制，避免每次新增页面都要同步两处（见 055 spec「实现细化」）。
"""

from __future__ import annotations

# 允许作为 parentKey 的一级分组。分组节点自身的 parentKey 必须为 None。
KNOWN_GROUP_KEYS: frozenset[str] = frozenset(
    {
        "/resources",
        "/assets",
        "/audit",
        "/organizations-group",
    }
)

# 图标只允许预设枚举；前端 ICON_REGISTRY 与本集合保持一致。
ICON_KEYS: frozenset[str] = frozenset(
    {
        "dashboard",
        "models",
        "knowledge",
        "token",
        "traffic",
        "users",
        "tools",
        "plugins",
        "skills",
        "settings",
        "roles",
        "audit",
        "hooks",
        "ontology",
        "resources",
        "accounts",
        "organization",
    }
)

# 防止把管理入口、默认落点与平台控制台隐藏掉导致锁死。
LOCKED_KEYS: frozenset[str] = frozenset(
    {
        "/dashboard",
        "/settings/menus",
        "/platform/tenants",
    }
)
