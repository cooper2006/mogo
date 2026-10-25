"""025 FR-9 (T019)：内容协商中间件（QF-225, QF-227）。

职责：
1. **406 + `Vary: Accept`**：当请求 `Accept` 声明了客户端愿意接受的响应类型，
   而白名单（默认 `application/json`，另接受 `application/*+json`、`application/*`、
   `*/*` 通配）无法满足时，返回 406 Not Acceptable，并带 `Vary: Accept`。
2. **`Accept-Encoding` 按声明生效**：仅当客户端声明 `gzip` 时，对 JSON 响应做
   gzip 压缩并加 `Content-Encoding: gzip` 与 `Vary: Accept-Encoding`；
   未声明则不压缩（避免向不能解压的客户端发送 gzip）。

实现为纯 ASGI 中间件：请求阶段做 Accept 判定（必要时 406 短路）；响应阶段缓冲
JSON 响应体以便按需 gzip。非 JSON 响应（SSE、二进制等）一律透传不缓冲。
"""

from __future__ import annotations

import gzip
from collections.abc import Awaitable, Callable
from typing import Any

# 默认可接受的响应类型；vendor json（application/*+json）、application/*、*/* 亦接受
_SUPPORTED = ("application/json",)


def _parse_accept(header: str) -> list[tuple[str, float]]:
    """返回 [(media_range, q)]，已剔除 q<=0 的段。"""
    result: list[tuple[str, float]] = []
    for part in header.split(","):
        piece = part.strip()
        if not piece:
            continue
        segments = [s.strip() for s in piece.split(";")]
        media_range = segments[0].lower()
        q = 1.0
        for seg in segments[1:]:
            if seg.startswith("q="):
                try:
                    q = float(seg[2:])
                except ValueError:
                    q = 0.0
        if q > 0:
            result.append((media_range, q))
    return result


def _accept_satisfied(header: str | None) -> bool:
    """Accept 是否可被白名单满足。无 Accept 头视为接受任意类型。"""
    if not header or not header.strip():
        return True
    for media_range, _q in _parse_accept(header):
        if media_range in _SUPPORTED:
            return True
        if media_range in ("*/*", "application/*"):
            return True
        if media_range.startswith("application/") and media_range.endswith("+json"):
            return True
    return False


def _wants_gzip(header: str | None) -> bool:
    if not header:
        return False
    for token in header.lower().split(","):
        if token.split(";")[0].strip() == "gzip":
            return True
    return False


def _header(scope: dict[str, Any], name: str) -> str | None:
    headers = dict(scope.get("headers") or [])
    value = headers.get(name.encode("latin-1"))
    return value.decode("latin-1") if value is not None else None


def _response_content_type(headers: list[tuple[bytes, bytes]]) -> str:
    for key, value in headers:
        if key.lower() == b"content-type":
            return value.decode("latin-1").lower()
    return ""


async def _add_vary(headers: list[tuple[bytes, bytes]], token: str) -> None:
    raw = b", ".join(v for k, v in headers if k.lower() == b"vary")
    existing = {t.strip().decode("latin-1") for t in raw.split(b",")} if raw else set()
    if token not in existing:
        parts = sorted(existing | {token})
        headers.append((b"vary", ", ".join(parts).encode("latin-1")))


class _BufferedSend:
    """按需 gzip 的响应转发器：缓冲 JSON 响应体，结束时统一压缩再发出。"""

    def __init__(self, send: Any, should_gzip: bool) -> None:
        self.send = send
        self.should_gzip = should_gzip
        self.buf = bytearray()
        self.start: dict[str, Any] | None = None
        self.compressing = False

    async def __call__(self, message: dict[str, Any]) -> None:
        mtype = message["type"]
        if mtype == "http.response.start":
            headers = list(message.get("headers") or [])
            if self.should_gzip and _response_content_type(headers).startswith("application/json"):
                self.compressing = True
                headers = [(k, v) for k, v in headers if k.lower() not in (b"content-length", b"content-encoding")]
                headers.append((b"content-encoding", b"gzip"))
            await _add_vary(headers, "Accept-Encoding")
            start = {**message, "headers": headers}
            if self.compressing:
                self.start = start
            else:
                await self.send(start)
            return

        if mtype == "http.response.body" and self.compressing:
            self.buf += message.get("body", b"")
            if not message.get("more_body"):
                payload = gzip.compress(bytes(self.buf))
                headers = [(k, v) for k, v in (self.start or {}).get("headers", []) if k.lower() != b"content-length"]
                headers.append((b"content-length", str(len(payload)).encode("ascii")))
                await self.send({**(self.start or {}), "headers": headers})
                await self.send({"type": "http.response.body", "body": payload})
            return

        await self.send(message)


class ContentNegotiationMiddleware:
    """纯 ASGI 中间件。"""

    def __init__(
        self,
        app: Callable[[dict[str, Any], Any, Any], Awaitable[None]],
        supported_types: tuple[str, ...] = _SUPPORTED,
        enable_gzip: bool = True,
    ) -> None:
        self.app = app
        self.supported_types = supported_types
        self.enable_gzip = enable_gzip

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        accept = _header(scope, "accept")
        if not _accept_satisfied(accept):
            payload = '{"detail": "不支持的响应类型，仅支持 application/json"}'.encode("utf-8")
            await send(
                {
                    "type": "http.response.start",
                    "status": 406,
                    "headers": [
                        (b"content-type", b"application/json; charset=utf-8"),
                        (b"content-length", str(len(payload)).encode("ascii")),
                        (b"vary", b"Accept"),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": payload})
            return

        should_gzip = self.enable_gzip and _wants_gzip(_header(scope, "accept-encoding"))
        buffered = _BufferedSend(send, should_gzip)
        await self.app(scope, receive, buffered)