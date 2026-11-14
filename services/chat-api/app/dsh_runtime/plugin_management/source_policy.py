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


def is_supported_plugin_source(spec: str) -> bool:
    """Only finished packages: pinned npm version, github: ref or https tarball.

    Keeps the mogo-side `github:` / `git+https:` support (see
    is_safe_personal_source) while giving install/preflight a single
    source-format gate that rejects local paths, shell prefixes and
    credentials-in-URL. Host safety is enforced by is_safe_personal_source.
    """
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
    return bool(parsed.scheme == "https" and parsed.hostname
                and not parsed.username and not parsed.password and not parsed.query)


def is_safe_personal_source(spec: str) -> bool:
    if not is_supported_plugin_source(spec):
        return False
    value = spec.strip()
    if is_fixed_npm_source(value) or value.startswith("github:"):
        return True
    parsed = urlsplit(value.removeprefix("git+"))
    host = (parsed.hostname or "").lower()
    if not host or host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        return False
    # fail-open-exempt: 解析失败表示 host 是域名而非 IP 字面量，是正常的允许路径，
    # 不是异常兜底放行；上方已拒绝 localhost/.local/.internal、内嵌凭据/query 且强制 https。
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return True
    return address.is_global
