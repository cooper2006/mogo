"""回归：admin-api 顶层路由必须可导入，且 057 的兼容性端点正确登记。

历史缺陷（commit da0c4b8a 引入）：``router.py`` 里
``api_router.include_router(compatibility.router, ...)`` 引用了
``compatibility.router``，但 ``compatibility.py`` 实际导出的是 ``api_router``，
导致 ``import app.api.router`` 直接 ``AttributeError``，整个 admin-api 应用无法加载。

本测试同时固化两点，避免同类回归：
1. 顶层路由可被导入（不抛 AttributeError）。
2. 兼容性端点登记在 ``/admin/compatibility/pipeline-support``
   （全局再叠加 ``/api/v1`` 前缀），而非被错误叠加 ``/compatibility``。
"""

from __future__ import annotations

import app.api.router as router_module


def test_top_level_router_imports_without_attribute_error() -> None:
    """导入顶层路由时不得因 compatibility.router 不存在而失败。"""
    assert router_module.api_router is not None


def test_compatibility_endpoint_registered_at_expected_path() -> None:
    """057 管线兼容端点必须登记在 /admin/compatibility/pipeline-support。"""
    path = router_module.api_router.url_path_for("get_pipeline_support")
    assert path == "/admin/compatibility/pipeline-support", path
