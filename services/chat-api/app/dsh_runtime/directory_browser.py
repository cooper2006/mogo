"""Server-side directory browsing for the pure-web client.

MOGO's user-web is a pure web client, so the DSH desktop's native OS directory
chooser is unreachable from it. The DSH platform already models this case: its
``directoryPicker`` seam offers a ``browse`` capability beside the ``native``
one, documented as the interaction that "works for remote clients — nothing
renders on the host display" (``@deepseek-ai/dsh-host-directory-picker``).

This service is that ``browse`` capability reached from chat-api. The runtime
host owns the filesystem, so chat-api forwards the request and the host
answers with one directory level; the web client then drives a directory
browser over these calls exactly as the DSH client drives its native chooser.

The listing shape and the failure vocabulary mirror the DSH seam: a listing
carries ``path`` / ``home`` / ``crumbs`` / ``entries`` / ``truncated``, and
failures use the closed codes ``directory-unreadable`` / ``directory-exists``
/ ``directory-create-failed``.
"""

from __future__ import annotations

from typing import Any

from app.dsh_runtime.errors import DshRuntimeError
from app.dsh_runtime.transport import HttpKernelHostTransport

# The DSH directory-picker failure vocabulary, mirrored so a client can
# discriminate on the code rather than on message text.
DIRECTORY_UNREADABLE = "directory-unreadable"
DIRECTORY_EXISTS = "directory-exists"
DIRECTORY_CREATE_FAILED = "directory-create-failed"


class DirectoryBrowseError(DshRuntimeError):
    """One directory-browse failure carrying its closed DSH code."""

    def __init__(self, code: str, message: str, *, path: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.path = path


class DirectoryBrowserService:
    """Reads one directory level of the host's browsable workspace root."""

    def __init__(self, transport: HttpKernelHostTransport) -> None:
        self._transport = transport

    async def list(self, path: str | None = None) -> dict[str, Any]:
        """List one directory level.

        @param path absolute directory to list; absent lists the root.
        @returns the listing the DSH seam defines.
        """
        params = {"path": path} if path else None
        try:
            payload = await self._transport.request(
                "GET", "/v1/directories", params=params
            )
        except DshRuntimeError as error:
            raise self._translate(error, path or "") from error
        return {
            "path": str(payload.get("path") or ""),
            "home": str(payload.get("home") or ""),
            "crumbs": self._entries(payload.get("crumbs")),
            "entries": self._entries(payload.get("entries")),
            "truncated": bool(payload.get("truncated")),
        }

    async def create_directory(self, path: str, name: str) -> str:
        """Create one child directory under an existing parent.

        @param path absolute existing parent directory.
        @param name single non-blank path segment.
        @returns the created directory's absolute path.
        """
        try:
            payload = await self._transport.request(
                "POST", "/v1/directories", json={"path": path, "name": name}
            )
        except DshRuntimeError as error:
            raise self._translate(error, path) from error
        return str(payload.get("path") or "")

    @staticmethod
    def _entries(raw: Any) -> list[dict[str, Any]]:
        """Normalize one listing collection into the client-facing row shape."""
        if not isinstance(raw, list):
            return []
        rows: list[dict[str, Any]] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            rows.append({
                "name": str(item.get("name") or ""),
                "path": str(item.get("path") or ""),
                "hidden": bool(item.get("hidden")),
            })
        return rows

    @staticmethod
    def _translate(error: DshRuntimeError, path: str) -> DirectoryBrowseError:
        """Recover the closed code the host reported, keeping the message."""
        message = str(error)
        for code in (DIRECTORY_UNREADABLE, DIRECTORY_EXISTS, DIRECTORY_CREATE_FAILED):
            if code in message:
                return DirectoryBrowseError(code, message, path=path)
        return DirectoryBrowseError(DIRECTORY_UNREADABLE, message, path=path)
