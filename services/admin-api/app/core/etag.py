"""025 FR-8 (T016)：ETag / If-Match 条件请求（QF-221, QF-222, QF-223, QF-224）。

提供两部分能力：

1. **工具函数**（路由层在写库前使用，保证「读-改-写」原子性）：
   - :func:`compute_etag`  根据资源内容生成强 ETag（对 JSON 做规范化序列化后 sha256）。
   - :func:`parse_etag` / :func:`parse_many` 解析 ``If-Match`` / ``If-None-Match`` 头。
   - :func:`matches`  判断 ``If-Match`` 头是否与当前 ETag 匹配（支持 ``*``、弱比较）。
   - 路由层约定：写库前用条件更新（filter 带 ``version`` 或 ``etag``），
     ``matched_count == 1`` 才提交，否则返回 **412** Precondition Failed ——
     这样并发写不会丢失更新。

2. **ASGI 中间件** :class:`ETagMiddleware`（协议层，风格同 T013/T015/T019）：
   - 请求阶段：解析 ``If-Match`` / ``If-None-Match`` 写入 ``scope["state"]``，
     供路由层比对；``require_match=True`` 时若缺 ``If-Match`` 直接 **428**。
   - 响应阶段：下游未自带 ``ETag`` 头时，为 ``application/json`` 响应自动生成
     强 ETag 头（按响应体哈希），让 GET 客户端后续可携带 ``If-Match`` 做条件写。

本轮**未挂载**到 admin-api app，留待 T048 统一装配。
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

_ETAG_HEADER = b"etag"
_IF_MATCH = b"if-match"
_IF_NONE_MATCH = b"if-none-match"


@dataclass(frozen=True)
class ETagValue:
    """解析后的单个 ETag 值。``opaque`` 为引号内的不透明字符串。"""

    opaque: str
    weak: bool = False


def compute_etag(data: Any) -> str:
    """计算强 ETag 的不透明值（不带引号）。

    - bytes：直接哈希。
    - str：UTF-8 编码后哈希。
    - 其它对象：按 JSON 规范化序列化（``sort_keys`` + 紧凑分隔符）后哈希，
      保证同一逻辑资源的 ETag 稳定。
    """
    if isinstance(data, bytes):
        raw = data
    elif isinstance(data, str):
        raw = data.encode("utf-8")
    else:
        raw = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def format_etag(opaque: str) -> str:
    """把不透明值格式化为 HTTP ETag 头值，如 ``"abc123"``。"""
    return f'"{opaque}"'


def parse_etag(value: str) -> ETagValue | None:
    """解析单个 ETag 头值；``*``（任意）与非法值返回 ``None``。"""
    text = value.strip()
    if text == "*" or text == "":
        return None
    weak = False
    if text.startswith("W/"):
        weak = True
        text = text[2:].strip()
    if len(text) >= 2 and text.startswith('"') and text.endswith('"'):
        return ETagValue(opaque=text[1:-1], weak=weak)
    return None


def parse_many(value: str | None) -> list[ETagValue | None]:
    """解析逗号分隔的 ETag 头；头缺失返回空列表。"""
    if not value:
        return []
    return [parse_etag(part) for part in value.split(",")]


def _weak_eq(a: ETagValue, b: ETagValue) -> bool:
    return a.opaque == b.opaque


def matches(header_value: str | None, current_etag: str) -> bool:
    """判断 ``If-Match`` 头是否满足（与当前 ETag 比较，支持弱比较）。

    头缺失（客户端未提供条件）视为「未提供」，由调用方决定是否拒绝（428）。
    ``*`` 匹配任意存在资源；空头返回 ``False``。
    """
    if not header_value:
        return False
    if header_value.strip() == "*":
        return True
    current = parse_etag(current_etag)
    if current is None:
        return False
    return any(
        parsed is not None and _weak_eq(parsed, current) for parsed in parse_many(header_value)
    )


def none_match_hits(header_value: str | None, current_etag: str) -> bool:
    """判断 ``If-None-Match`` 是否命中（GET/HEAD 时命中应返回 304）。"""
    if not header_value:
        return False
    if header_value.strip() == "*":
        return True
    current = parse_etag(current_etag)
    if current is None:
        return False
    return any(parsed is not None and _weak_eq(parsed, current) for parsed in parse_many(header_value))


# ── ASGI 中间件 ────────────────────────────────────────────────────────────


class ETagMiddleware:
    """ETag 协议层中间件：解析条件请求头 + 为 JSON 响应补 ETag。

    参数
    ----
    require_match:
        ``True`` 时，对非安全方法且请求缺少 ``If-Match`` 头直接返回 **428**
        Precondition Required。默认 ``False``（不改变现状，仅解析与补头）。
    """

    def __init__(
        self,
        app: Callable[[dict[str, Any], Any, Any], Awaitable[None]],
        require_match: bool = False,
    ) -> None:
        self.app = app
        self.require_match = require_match

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = (scope.get("method") or "GET").upper()
        headers = dict(scope.get("headers") or [])
        if_match = _decode(headers.get(_IF_MATCH))
        if_none_match = _decode(headers.get(_IF_NONE_MATCH))

        state = scope.setdefault("state", {})
        state["if_match"] = if_match
        state["if_none_match"] = if_none_match
        state["etag_middleware_active"] = True

        if self.require_match and method not in ("GET", "HEAD") and not if_match:
            await _respond(send, 428, "需要 If-Match 头（先 GET 取 ETag，再带 If-Match 做条件写）")
            return

        # 响应阶段：若下游未带 ETag 头，为 JSON 响应生成强 ETag。
        # 先缓冲 start + body，全部收到后再改写 headers 并一次发出。
        captured: dict[str, Any] = {}

        async def buffered_send(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                captured["status"] = message["status"]
                captured["headers"] = list(message.get("headers") or [])
                captured["started"] = True
            elif message["type"] == "http.response.body":
                captured.setdefault("chunks", bytearray()).extend(message.get("body", b""))

        await self.app(scope, receive, buffered_send)

        status = captured.get("status")
        if status is None:  # 下游未发 start（异常路径），交给上层
            return
        headers_out = list(captured.get("headers") or [])
        body = bytes(captured.get("chunks") or b"")
        content_type = _header_value(headers_out, b"content-type")
        has_etag = any(k.lower() == _ETAG_HEADER for k, _ in headers_out)
        if content_type and content_type.startswith("application/json") and body and not has_etag:
            etag = compute_etag(body)
            headers_out = [(k, v) for k, v in headers_out if k.lower() != b"content-length"]
            headers_out.append((_ETAG_HEADER, format_etag(etag).encode("ascii")))
            headers_out.append((b"content-length", str(len(body)).encode("ascii")))
            state["response_etag"] = etag

        await send({"type": "http.response.start", "status": status, "headers": headers_out})
        await send({"type": "http.response.body", "body": body})


def _header_value(headers: list[tuple[bytes, bytes]], name: bytes) -> str:
    for key, value in headers:
        if key.lower() == name:
            return value.decode("latin-1")
    return ""


def _decode(value: bytes | None) -> str | None:
    return value.decode("latin-1") if value else None


async def _respond(send: Any, status_code: int, detail: str) -> None:
    payload = json.dumps({"detail": detail}).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status_code,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(payload)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": payload})