"""025 FR-5 (T013)：载荷限制中间件（QF-211）。

对请求体实施三类限制（配置见 `app/config/payload_limits`）：
- `max_bytes`        请求体字节数超限 → **413** Payload Too Large
- `max_depth`        JSON 嵌套深度超限 → **422** Unprocessable Entity
- `max_array_length` 单个数组元素数超限 → **422**
- `max_string_length` 单个字符串长度超限 → **422**

实现为纯 ASGI 中间件（不用 `BaseHTTPMiddleware`）：先读完受限 body，
再以缓存流转发给下游，避免下游拿到已被消费的空流而读不到 body。

仅当 `Content-Type` 含 `application/json` 时做结构校验；非 JSON 只做字节数限制。
body 不是合法 JSON 时不在此处报错，交下游（400）。
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from app.config.payload_limits import PayloadLimits, load_payload_limits

JsonBody = dict[str, Any] | list[Any] | str | float | bool | None

# JSON 顶层标量不参与结构限制（depth 从 1 计；数组/对象自身算一层）
_BASE_DEPTH = 1


class _ShapeError(Exception):
    """结构校验失败，携带面向客户端的原因说明。"""


def _check_shape(node: JsonBody, limits: PayloadLimits, depth: int = _BASE_DEPTH) -> None:
    """递归校验嵌套深度、数组长度与字符串长度。"""
    if depth > limits.max_depth:
        raise _ShapeError(f"JSON 嵌套深度超过限制（最大 {limits.max_depth}）")

    if isinstance(node, dict):
        for key, value in node.items():
            if len(str(key)) > limits.max_string_length:
                raise _ShapeError(f"对象键长度超过限制（最大 {limits.max_string_length}）")
            _check_shape(value, limits, depth + 1)
    elif isinstance(node, list):
        if len(node) > limits.max_array_length:
            raise _ShapeError(f"数组元素数超过限制（最大 {limits.max_array_length}）")
        for item in node:
            _check_shape(item, limits, depth + 1)
    elif isinstance(node, str):
        if len(node) > limits.max_string_length:
            raise _ShapeError(f"字符串长度超过限制（最大 {limits.max_string_length}）")


def _is_json_request(scope: dict[str, Any]) -> bool:
    headers = dict(scope.get("headers") or [])
    content_type = headers.get(b"content-type", b"").decode("latin-1").lower()
    return "application/json" in content_type


class PayloadLimitMiddleware:
    """纯 ASGI 中间件；`limits` 未提供时在实例化时加载一次配置。"""

    def __init__(
        self,
        app: Callable[[dict[str, Any], Any, Any], Awaitable[None]],
        limits: PayloadLimits | None = None,
    ) -> None:
        self.app = app
        self.limits = limits if limits is not None else load_payload_limits()

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "/")
        limits = self.limits.for_path(path)

        # 先按上限读取完整 body，超限立即 413，不再调用下游。
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] != "http.request":
                await self.app(scope, receive, send)
                return
            body.extend(message.get("body", b""))
            if len(body) > limits.max_bytes:
                await self._respond(send, 413, f"请求体超过大小限制（最大 {limits.max_bytes} 字节）")
                return
            if not message.get("more_body"):
                break

        if _is_json_request(scope):
            try:
                data: JsonBody = json.loads(bytes(body))
            except (json.JSONDecodeError, UnicodeDecodeError):
                data = None  # 非法 JSON 交下游处理
            if data is not None:
                try:
                    _check_shape(data, limits)
                except _ShapeError as exc:
                    await self._respond(send, 422, str(exc))
                    return

        # 以缓存流转发下游，下游仍能读到完整 body。
        payload = bytes(body)

        async def cached_receive() -> dict[str, Any]:
            return {"type": "http.request", "body": payload, "more_body": False}

        await self.app(scope, cached_receive, send)

    @staticmethod
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