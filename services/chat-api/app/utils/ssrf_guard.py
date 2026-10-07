"""QF-402~406: SSRF protection — reject requests to internal/private IP addresses.

Provides `is_safe_url` and `validate_outbound_url` helpers for outbound HTTP calls.
Blocks private (RFC 1918), loopback, link-local, and cloud metadata addresses.
"""

from __future__ import annotations
from app.infrastructure.observability.config import log_print

import ipaddress
import socket
from urllib.parse import urlparse

# RFC 1918 + special ranges that must never be reachable from user-triggered fetches.
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),  # link-local / cloud metadata
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]

_ALLOWED_SCHEMES = {"http", "https"}


def _is_private_address(address: str) -> bool:
    """Return True if the IP address falls in a blocked private/special range."""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        # Non-IP hostnames that fail DNS are also unsafe.
        return True
    return any(ip in net for net in _BLOCKED_NETWORKS)


def is_safe_url(url: str) -> bool:
    """Return True if *url* points to a public, non-private HTTP(S) address."""
    try:
        parsed = urlparse(url)
    except Exception as exc:
        log_print(f"[utils.ssrf_guard] silent exception caught: {exc}", flush=True)
        return False
    if parsed.scheme not in _ALLOWED_SCHEMES:
        return False
    hostname = parsed.hostname
    if not hostname:
        return False
    # Direct IP literals
    try:
        ip = ipaddress.ip_address(hostname)
        return not _is_private_address(str(ip))
    except ValueError:
        pass
    # Resolve hostname and check all returned addresses.
    try:
        infos = socket.getaddrinfo(hostname, None)
    except (socket.gaierror, OSError):
        return False
    for info in infos:
        addr = info[4][0]
        if _is_private_address(addr):
            return False
    return True


def validate_outbound_url(url: str, *, field_name: str = "url") -> str:
    """Validate *url* for SSRF safety; raise ValueError if unsafe.

    Returns the validated URL string unchanged.
    """
    if not url or not isinstance(url, str):
        raise ValueError(f"{field_name} must be a non-empty string")
    if not is_safe_url(url):
        raise ValueError(
            f"{field_name} '{url[:120]}' resolves to a private or unreachable address; "
            "only public HTTP/HTTPS URLs are allowed"
        )
    return url
