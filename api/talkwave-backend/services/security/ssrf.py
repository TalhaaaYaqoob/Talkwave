"""Reusable SSRF guard for outbound, user/tenant-controlled URLs.

Any server-side fetch whose target URL can be influenced by a user (knowledge
base scraping, custom HTTP tools, workflow webhooks, etc.) must be validated
with :func:`validate_public_url` / :func:`assert_public_url` before the request
is made. This blocks requests to loopback, RFC1918 private ranges, link-local
addresses (including the cloud metadata endpoint 169.254.169.254), reserved,
multicast and unspecified addresses.

DNS is resolved and every resolved address is checked (not just the hostname
string) to mitigate DNS-rebinding.
"""

from __future__ import annotations

import asyncio
import ipaddress
from urllib.parse import urlparse

from loguru import logger


class UnsafeURLError(ValueError):
    """Raised when a URL targets a non-public / disallowed destination."""


def ip_is_blocked(ip_str: str) -> bool:
    """True if an IP is loopback / private / link-local / reserved / multicast."""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # not a parseable IP → be safe and block
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


async def validate_public_url(url: str) -> bool:
    """Return True only if ``url`` is http(s) and resolves to public IPs."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        logger.warning(f"[SSRF] Refusing non-http(s) URL: {url}")
        return False
    host = parsed.hostname
    if not host:
        logger.warning(f"[SSRF] Refusing URL with no host: {url}")
        return False

    # Literal IP in the URL → check directly.
    try:
        ipaddress.ip_address(host)
        if ip_is_blocked(host):
            logger.warning(f"[SSRF] Refusing private/loopback IP URL: {url}")
            return False
        return True
    except ValueError:
        pass  # hostname, resolve below

    try:
        loop = asyncio.get_event_loop()
        infos = await loop.getaddrinfo(host, None)
    except Exception as e:
        logger.warning(f"[SSRF] DNS resolution failed for {host}: {e}")
        return False

    resolved = {info[4][0] for info in infos}
    if not resolved:
        return False
    for ip_str in resolved:
        if ip_is_blocked(ip_str):
            logger.warning(
                f"[SSRF] Refusing {url} — host {host} resolves to "
                f"non-public address {ip_str}"
            )
            return False
    return True


async def assert_public_url(url: str) -> None:
    """Raise :class:`UnsafeURLError` if ``url`` is not a safe public target."""
    if not await validate_public_url(url):
        raise UnsafeURLError("URL target is not permitted")
