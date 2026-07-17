"""Wake on LAN magic packet generation and sending."""

from __future__ import annotations

import re
import socket
import time

_MAC_SEPARATOR_RE = re.compile(r"[:-]")
_WOL_PORT = 9


def build_magic_packet(mac_address: str) -> bytes:
    """Return the 102-byte WOL magic packet for the given MAC address."""
    parts = _MAC_SEPARATOR_RE.split(mac_address.strip())
    if len(parts) != 6 or any(len(part) != 2 for part in parts):
        raise ValueError("invalid MAC address format")
    try:
        mac_bytes = bytes(int(part, 16) for part in parts)
    except ValueError:
        raise ValueError("invalid MAC address format") from None
    return b"\xff" * 6 + mac_bytes * 16


def send_magic_packets(
    mac_address: str,
    broadcast_address: str,
    *,
    count: int,
    interval_seconds: float,
) -> int:
    """Broadcast the magic packet ``count`` times and return how many were sent.

    Blocking; call from async code via ``asyncio.to_thread``.
    """
    packet = build_magic_packet(mac_address)
    sent = 0
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for attempt in range(count):
            if attempt:
                time.sleep(interval_seconds)
            sock.sendto(packet, (broadcast_address, _WOL_PORT))
            sent += 1
    return sent
