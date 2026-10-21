"""022 FR-16（T033）：CORS 显式白名单。

背景
----
admin-api / chat-api 原先把 ``allow_methods`` 与 ``allow_headers`` 都设为
``["*"]``。Starlette 对 ``["*"]`` 的处理是**把预检请求里提出的方法 / 头部原样
写回响应头**，等价于对跨域预检整体放行任意方法与任意头部 —— 这既不必要，也让
"服务端到底放行了哪些跨域能力"无法从配置读出来（QF-640）。

本模块把三件事收敛成一份显式配置：

1. ``allow_origins`` 由 ``CORS_ORIGINS`` 环境变量配置（逗号分隔），
   **默认空列表 = 拒绝所有跨域**。部署方必须显式声明可信来源。
2. ``allow_methods`` / ``allow_headers`` 为显式白名单，拒绝 ``*``。
3. 通配来源在 ``allow_credentials=True`` 下本来就无法被 Starlette 正确反射，
   这里在入口就过滤掉并告警，避免"配了 * 以为生效"的错觉。

用法
----
::

    from app.middleware.cors import build_cors_middleware_kwargs

    app.add_middleware(
        CORSMiddleware,
        **build_cors_middleware_kwargs(settings.cors_origins),
    )
"""

from __future__ import annotations

import logging
from typing import Iterable

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_ALLOW_HEADERS",
    "DEFAULT_ALLOW_METHODS",
    "build_cors_middleware_kwargs",
    "parse_origins",
]

#: 业务端点实际使用的 HTTP 方法白名单。
#: ``OPTIONS`` 是 CORS 预检方法，必须显式列出 —— 否则预检会被当普通请求处理。
DEFAULT_ALLOW_METHODS: tuple[str, ...] = (
    "GET",
    "POST",
    "PUT",
    "PATCH",
    "DELETE",
    "OPTIONS",
)

#: 客户端实际发送、服务端需要读取的请求头白名单。
#: 顺序无关（Starlette 做集合匹配），但保持固定顺序便于 diff。
DEFAULT_ALLOW_HEADERS: tuple[str, ...] = (
    "Authorization",
    "Content-Type",
    "Accept",
    "Accept-Language",
    "X-Request-ID",
    # 022 FR-12：服务间调用的独立凭证头（admin-api / chat-api 内部端点）。
    "X-MOGO-Service-Token",
)

#: 通配来源。在 ``allow_credentials=True`` 下 Starlette 不能正确反射通配源，
#: 放行它只会制造"以为生效"的错觉，因此入口就拦掉。
_WILDCARD = "*"


def parse_origins(value: str | Iterable[str] | None) -> list[str]:
    """把 ``CORS_ORIGINS`` 原始值归一化为来源列表。

    接受：
    - ``None`` / 空串 → 空列表（拒绝所有跨域）；
    - 逗号分隔字符串（``"http://a, http://b"``）；
    - 已经是列表 / 元组（pydantic ``list[str]`` 字段直接传入）。

    去空白、去重、保序、丢弃空项与通配符 ``*``。
    """
    if value is None:
        raw: Iterable[str] = ()
    elif isinstance(value, str):
        raw = value.split(",")
    else:
        raw = value

    origins: list[str] = []
    for item in raw:
        origin = str(item or "").strip().rstrip("/")
        if not origin:
            continue
        if "*" in origin:
            # allow_credentials=True 下通配源无法被 Starlette 正确反射；
            # 放行它只会让部署方误以为"跨域已开"。这里拒绝并告警。
            # 同时覆盖 ``*``、``*.example.com``、``http://a/*`` 等变体。
            logger.warning(
                "CORS_ORIGINS contains a wildcard origin (%r); refusing to apply it. "
                "List explicit origins instead of '*'.",
                origin,
            )
            continue
        if origin not in origins:
            origins.append(origin)
    return origins


def build_cors_middleware_kwargs(
    origins: str | Iterable[str] | None,
    *,
    allow_methods: Iterable[str] = DEFAULT_ALLOW_METHODS,
    allow_headers: Iterable[str] = DEFAULT_ALLOW_HEADERS,
    allow_credentials: bool = True,
) -> dict[str, object]:
    """构造 ``CORSMiddleware`` 的入参，并做防御性收敛。

    - 来源：经 :func:`parse_origins` 归一化；空列表表示"不放行任何跨域"。
    - 方法 / 头部：显式白名单，剔除 ``*``。
    - ``allow_origin_regex`` 不使用 —— 正则匹配容易引入前缀/后缀误判。
    """
    allow_origins = parse_origins(origins)

    methods = tuple(
        str(m).strip().upper()
        for m in allow_methods
        if str(m).strip() and str(m).strip().upper() != _WILDCARD
    )
    headers = tuple(
        str(h).strip()
        for h in allow_headers
        if str(h).strip() and str(h).strip() != _WILDCARD
    )

    if not allow_origins:
        # 不是错误 —— 服务端可以合法地"不接受任何跨域浏览器请求"。
        # 但必须让运维看得见，否则排障时会误判为配置缺失。
        logger.info(
            "CORS_ORIGINS is empty; all cross-origin browser requests will be denied. "
            "Set CORS_ORIGINS to a comma-separated list of trusted origins to enable CORS."
        )
    else:
        logger.info("CORS allow_origins=%s allow_methods=%s", list(allow_origins), list(methods))

    return {
        "allow_origins": allow_origins,
        "allow_credentials": bool(allow_credentials),
        "allow_methods": list(methods),
        "allow_headers": list(headers),
    }
