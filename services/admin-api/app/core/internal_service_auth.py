from __future__ import annotations

import os
from pathlib import Path


def _read_secret_file() -> str:
    """Read backend service token from exported secret file.

    Docker security profiles may filter os.environ and clear /proc/1/environ,
    so we write secrets to a file in the entrypoint and read from there.
    """
    secret_paths = [
        Path("/run/askai-secrets/exported.env"),
        Path("/run/askai-secrets/runtime.env"),
    ]
    for path in secret_paths:
        try:
            if path.exists() and path.stat().st_size > 0:
                content = path.read_text(encoding="utf-8", errors="replace")
                for line in content.splitlines():
                    line = line.strip()
                    if line.startswith("ADMIN_BACKEND_SERVICE_TOKEN="):
                        return line.split("=", 1)[1].strip()
                    if line.startswith("ASKAI_ADMIN_BACKEND_SERVICE_TOKEN="):
                        return line.split("=", 1)[1].strip()
        except Exception:
            continue
    return ""


def resolve_backend_service_token(configured_alias: str = "") -> str:
    """Resolve the canonical admin-api -> chat-api service credential.

    ADMIN_BACKEND_SERVICE_TOKEN is shared with chat-api and therefore wins
    over the prefixed compatibility alias when both are present.
    """

    # Try multiple sources in order of priority
    # 1. os.getenv (normal case)
    canonical = str(os.getenv("ADMIN_BACKEND_SERVICE_TOKEN") or "").strip()
    if canonical:
        return canonical

    # 2. Read from exported secret file (Docker security filter workaround)
    from_file = _read_secret_file()
    if from_file:
        return from_file

    # 3. Fallback to configured alias or prefixed alias
    return str(configured_alias or os.getenv("ASKAI_ADMIN_BACKEND_SERVICE_TOKEN") or "").strip()


__all__ = ["resolve_backend_service_token"]
