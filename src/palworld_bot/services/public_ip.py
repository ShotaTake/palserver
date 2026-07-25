"""Look up the site's current public IPv4 address.

The home connection has a dynamic global IPv4, so the address friends need
changes over time. The bot asks an external echo service over outbound HTTPS
only — nothing new is exposed inbound, and it still answers while the game PC
is powered off.

The response comes from outside, so it is never shown as-is: only a value that
parses as a global IP address is accepted.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
from collections.abc import Awaitable, Callable, Sequence

logger = logging.getLogger(__name__)

DEFAULT_ENDPOINTS: tuple[str, ...] = (
    "https://api.ipify.org",
    "https://checkip.amazonaws.com",
)

# An address is at most 45 characters; anything longer is not a plain IP reply.
_MAX_RESPONSE_BYTES = 64

HttpGet = Callable[[str, float], Awaitable[str]]


def parse_public_ip(raw: str) -> str | None:
    """Return the address only when it is a syntactically valid, global IP."""
    candidate = raw.strip()
    if not candidate or len(candidate) > _MAX_RESPONSE_BYTES:
        return None
    try:
        address = ipaddress.ip_address(candidate)
    except ValueError:
        return None
    # Private, loopback, and link-local replies mean we asked the wrong thing.
    if not address.is_global:
        return None
    return str(address)


async def _aiohttp_get(url: str, timeout_seconds: float) -> str:
    import aiohttp

    timeout = aiohttp.ClientTimeout(total=timeout_seconds)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url) as response:
            response.raise_for_status()
            body = await response.content.read(_MAX_RESPONSE_BYTES + 1)
    return body.decode("ascii", errors="replace")


async def fetch_public_ip(
    *,
    endpoints: Sequence[str] = DEFAULT_ENDPOINTS,
    timeout_seconds: float = 10.0,
    http_get: HttpGet | None = None,
) -> str | None:
    """Return the current public IP, or None when no endpoint gives a usable answer."""
    getter = http_get if http_get is not None else _aiohttp_get
    for url in endpoints:
        try:
            body = await getter(url, timeout_seconds)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("public IP lookup failed for one endpoint")
            continue
        address = parse_public_ip(body)
        if address is not None:
            return address
        logger.warning("public IP endpoint returned an unusable value")
    return None
