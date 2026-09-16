from __future__ import annotations

from copy import deepcopy
from typing import Any


COMMON_IMAGE_FIELDS = ("size", "quality", "output_format", "response_format", "n", "ratio")


def build_image_payload(
    *,
    model: str,
    prompt: str,
    settings: dict[str, Any],
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    extra = settings.get("extra_params")
    payload = deepcopy(extra) if isinstance(extra, dict) else {}
    payload["model"] = str(model or "").strip()
    payload["prompt"] = prompt
    supplied = dict(overrides or {})
    for field in COMMON_IMAGE_FIELDS:
        configured = settings.get(field)
        if configured in (None, ""):
            continue
        value = supplied.get(field)
        payload[field] = configured if value in (None, "") else value
    return payload


def image_endpoint(base_url: str, request_path: str) -> str:
    base = str(base_url or "").strip().rstrip("/")
    path = str(request_path or "/images/generations").strip()
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{base}{path}"


def response_value(data: Any, path: str) -> Any:
    current = data
    for token in str(path or "").split("."):
        if not token:
            continue
        if isinstance(current, list):
            try:
                current = current[int(token)]
            except (IndexError, TypeError, ValueError):
                return None
        elif isinstance(current, dict):
            current = current.get(token)
        else:
            return None
        if current is None:
            return None
    return current


__all__ = ["build_image_payload", "image_endpoint", "response_value"]
