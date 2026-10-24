"""统一门户 + 自助申领（037）—— 终端用户侧服务层。

职责切分：

* :mod:`.listings` —— ``portal_listings`` 上架标记的读取与目录聚合视图
  （join ``skills`` / ``capability_assets`` + 016 效果分摘要 + 036 评级可选字段）；
* :mod:`.requests` —— ``portal_requests`` 申领单状态机（条件更新幂等 + 防自审 +
  审计）与开通 / 回收授权（直写 ``permission_grants`` 用户级记录）。

集合字段契约由 admin-api 侧测试（``tests/test_portal_admin.py``）锁定，防止
跨服务漂移；本服务只按契约读写共享 MongoDB 集合，不新建存储。
"""

from .listings import (
    CATALOG_ASSET_TYPES,
    PORTAL_LISTINGS_COLLECTION,
    find_listing,
    get_asset_basics,
    list_catalog,
    list_categories,
)
from .requests import (
    PORTAL_REQUESTS_COLLECTION,
    STATUS_TERMINAL,
    build_asset_use_code,
    expire_stale_grants,
    issue_request,
    list_my_requests,
    resolve_approver,
    revoke_grant,
    decide_request,
)

__all__ = [
    "CATALOG_ASSET_TYPES",
    "PORTAL_LISTINGS_COLLECTION",
    "PORTAL_REQUESTS_COLLECTION",
    "STATUS_TERMINAL",
    "build_asset_use_code",
    "decide_request",
    "expire_stale_grants",
    "find_listing",
    "get_asset_basics",
    "issue_request",
    "list_catalog",
    "list_categories",
    "list_my_requests",
    "resolve_approver",
    "revoke_grant",
]