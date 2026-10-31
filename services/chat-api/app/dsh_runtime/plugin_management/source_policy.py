"""Keep user supplied package locations away from server files and private hosts."""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit


_WINDOWS_PATH = re.compile(r"^[a-zA-Z]:[\\/]")
_NPM_VERSION = re.compile(r"^(?:@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*@[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?$")
_UNSAFE_PREFIXES = ("/", "~", "./", "../", "\\", "file:", "link:", "workspace:", "git@", "ssh:")


def is_fixed_npm_source(spec: str) -> bool:
    return bool(_NPM_VERSION.fullmatch(spec.strip()))


def is_safe_personal_source(spec: str) -> bool:
    value = spec.strip()
    if not value or any(ch.isspace() for ch in value) or value.startswith(_UNSAFE_PREFIXES):
        return False
    if _WINDOWS_PATH.match(value) or "\\" in value:
        return False
    if value.startswith("github:"):
        return bool(re.fullmatch(r"github:[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:#[A-Za-z0-9_.-]+)?", value))
    if "://" not in value:
        return is_fixed_npm_source(value)
    parsed = urlsplit(value.removeprefix("git+"))
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query:
        return False
    host = parsed.hostname.lower()
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return True
    return address.is_global
